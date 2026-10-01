"""Legacy binary Word (.doc) engine, pure Python on top of ``olefile``.

A .doc stores its text as a list of *pieces* (the piece table in the ``Clx``)
and its paragraph formatting in separate *FKP* pages. This reader follows the
[MS-DOC] layout far enough to recover what a converted document needs:

* the text, in order, with field codes dropped and field results kept;
* real **table** structure - rows and cells come from the paragraph flags
  (``fInTable`` / ``fTtp``), not from guessing at the cell marks, so a table with
  empty cells keeps its columns;
* **headings** (built-in ``Heading 1..9`` styles) and **list** items with depth.

Not recovered: bold/italic, headers and footers, footnotes, text boxes and
pictures. A note at the top of every result says so, so the output is never
mistaken for a full-fidelity conversion.

Some ``.doc`` files are not Word binaries at all (an RTF or HTML page saved
with a .doc name). Those are sniffed and routed accordingly.
"""

from __future__ import annotations

import bisect
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.core.tables import render_table
from doc2md.engine.base import BaseEngine

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
LEGACY_NOTE = (
    "> Legacy .doc: text, headings, lists and tables were recovered; bold/italic, "
    "headers/footers, footnotes and text boxes were not."
)

_SPRM_IN_TABLE = 0x2416
_SPRM_TTP = 0x2417
_SPRM_ILVL = 0x260A
_SPRM_ILFO = 0x460B
_SPRM_ISTD = 0x4600
_MAX_PARAGRAPHS = 400_000


@dataclass
class _Piece:
    cp_start: int
    cp_end: int
    fc: int
    compressed: bool

    def fc_at(self, cp: int) -> int:
        step = 1 if self.compressed else 2
        return self.fc + (cp - self.cp_start) * step


@dataclass
class _Para:
    text: str
    in_table: bool = False
    row_end: bool = False
    istd: int = 0
    ilvl: int = 0
    ilfo: int = 0
    ends_cell: bool = False


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _parse_sprms(grpprl: bytes) -> dict[int, int]:
    """Read the paragraph sprms we care about; skip every other one correctly."""
    found: dict[int, int] = {}
    i = 0
    while i + 2 <= len(grpprl):
        opcode = _u16(grpprl, i)
        i += 2
        spra = opcode >> 13
        if spra in (0, 1):
            size = 1
        elif spra in (2, 4, 5):
            size = 2
        elif spra == 3:
            size = 4
        elif spra == 7:
            size = 3
        else:  # 6: variable length
            if i >= len(grpprl):
                break
            if opcode == 0xD608:
                if i + 2 > len(grpprl):
                    break
                size = _u16(grpprl, i) + 2
            else:
                size = grpprl[i] + 1
        operand = grpprl[i:i + size]
        i += size
        if opcode in (_SPRM_IN_TABLE, _SPRM_TTP, _SPRM_ILVL, _SPRM_ISTD, _SPRM_ILFO) and operand:
            found[opcode] = int.from_bytes(operand[:4], "little")
    return found


class _WordBinary:
    """Everything read out of one WordDocument/Table stream pair."""

    def __init__(self, word: bytes, table: bytes) -> None:
        self.word = word
        self.table = table
        self.pieces: list[_Piece] = []
        self.ccp_text = 0
        self.fc_lcb = 0
        self._papx: list[tuple[int, int, dict[int, int], int]] = []
        self._papx_starts: list[int] = []

    # ------------------------------------------------------------------ header
    @classmethod
    def open(cls, word: bytes, table: bytes) -> "_WordBinary":
        doc = cls(word, table)
        csw = _u16(word, 0x20)
        cslw_at = 0x22 + csw * 2
        cslw = _u16(word, cslw_at)
        rg_lw = cslw_at + 2
        doc.ccp_text = _u32(word, rg_lw + 3 * 4)
        cb_at = rg_lw + cslw * 4
        doc.fc_lcb = cb_at + 2
        doc._read_pieces()
        doc._read_papx()
        return doc

    def _fc_lcb(self, index: int) -> tuple[int, int]:
        at = self.fc_lcb + index * 8
        return _u32(self.word, at), _u32(self.word, at + 4)

    def _read_pieces(self) -> None:
        fc_clx, lcb_clx = self._fc_lcb(33)
        clx = self.table[fc_clx:fc_clx + lcb_clx]
        i = 0
        while i < len(clx) and clx[i] == 0x01:
            i += 3 + _u16(clx, i + 1)
        if i >= len(clx) or clx[i] != 0x02:
            raise ConversionError("unreadable piece table (not a supported Word 97+ document)")
        lcb = _u32(clx, i + 1)
        plc = clx[i + 5:i + 5 + lcb]
        count = (lcb - 4) // 12
        cps = struct.unpack_from(f"<{count + 1}I", plc, 0)
        base = (count + 1) * 4
        for n in range(count):
            fc_raw = _u32(plc, base + n * 8 + 2)
            compressed = bool(fc_raw & 0x40000000)
            fc = (fc_raw & 0x3FFFFFFF) // 2 if compressed else fc_raw
            self.pieces.append(_Piece(cps[n], cps[n + 1], fc, compressed))

    def _read_papx(self) -> None:
        fc_plc, lcb_plc = self._fc_lcb(13)
        plc = self.table[fc_plc:fc_plc + lcb_plc]
        count = (lcb_plc - 4) // 8
        if count <= 0:
            return
        fcs = struct.unpack_from(f"<{count + 1}I", plc, 0)
        pages = struct.unpack_from(f"<{count}I", plc, (count + 1) * 4)
        entries: list[tuple[int, int, dict[int, int], int]] = []
        for page_number in pages:
            page = self.word[(page_number & 0x3FFFFF) * 512:(page_number & 0x3FFFFF) * 512 + 512]
            if len(page) < 512:
                continue
            runs = page[511]
            rgfc = struct.unpack_from(f"<{runs + 1}I", page, 0)
            for r in range(runs):
                b_offset = page[(runs + 1) * 4 + r * 13]
                if not b_offset:
                    entries.append((rgfc[r], rgfc[r + 1], {}, 0))
                    continue
                at = b_offset * 2
                cb = page[at]
                if cb == 0:
                    cb = page[at + 1]
                    data = page[at + 2:at + 2 + cb * 2]
                else:
                    data = page[at + 1:at + cb * 2]
                if len(data) < 2:
                    entries.append((rgfc[r], rgfc[r + 1], {}, 0))
                    continue
                entries.append((rgfc[r], rgfc[r + 1], _parse_sprms(data[2:]), _u16(data, 0)))
        entries.sort(key=lambda entry: entry[0])
        self._papx = entries
        self._papx_starts = [entry[0] for entry in entries]

    # -------------------------------------------------------------------- text
    def text(self) -> str:
        chunks: list[str] = []
        for piece in self.pieces:
            length = piece.cp_end - piece.cp_start
            if piece.compressed:
                raw = self.word[piece.fc:piece.fc + length]
                chunks.append(raw.decode("cp1252", errors="replace"))
            else:
                raw = self.word[piece.fc:piece.fc + length * 2]
                chunks.append(raw.decode("utf-16-le", errors="replace"))
        return "".join(chunks)[: self.ccp_text]

    def paragraph_props(self, cp: int, piece_starts: list[int]) -> tuple[dict[int, int], int]:
        index = bisect.bisect_right(piece_starts, cp) - 1
        if index < 0 or index >= len(self.pieces) or cp >= self.pieces[index].cp_end:
            return {}, 0
        fc = self.pieces[index].fc_at(cp)
        at = bisect.bisect_right(self._papx_starts, fc) - 1
        if at < 0:
            return {}, 0
        start, end, props, istd = self._papx[at]
        return (props, istd) if start <= fc < end else ({}, 0)


_FIELD_BEGIN, _FIELD_SEP, _FIELD_END = "\x13", "\x14", "\x15"


def _strip_fields(text: str) -> str:
    """Keep field results, drop field instructions (``HYPERLINK ...``, ``PAGE``)."""
    out: list[str] = []
    stack: list[str] = []
    for ch in text:
        if ch == _FIELD_BEGIN:
            stack.append("code")
        elif ch == _FIELD_SEP:
            if stack:
                stack[-1] = "result"
        elif ch == _FIELD_END:
            if stack:
                stack.pop()
        elif all(state == "result" for state in stack):
            out.append(ch)
    return "".join(out)


_DROP = {
    code: None
    for code in (
        0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x08, 0x0E, 0x0F, 0x10, 0x11,
        0x12, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1F,
    )
}


def _clean_inline(text: str) -> str:
    text = text.replace("\x0b", "\n").replace("\x1e", "-").replace("\xa0", " ").replace("\x09", " ")
    text = text.translate(_DROP)
    return text.strip()


def paragraphs_of(doc: _WordBinary) -> list[_Para]:
    raw = doc.text()
    piece_starts = [piece.cp_start for piece in doc.pieces]
    paragraphs: list[_Para] = []
    start = 0
    for index, ch in enumerate(raw):
        if ch not in ("\r", "\x07", "\x0c"):
            continue
        body = raw[start:index]
        mark_cp = index
        start = index + 1
        if ch == "\x0c":
            # A page break ends a page, not a paragraph; keep what precedes it.
            if body.strip():
                paragraphs.append(_Para(_clean_inline(_strip_fields(body))))
            continue
        props, istd = doc.paragraph_props(mark_cp, piece_starts)
        istd = props.get(_SPRM_ISTD, istd)
        in_table = bool(props.get(_SPRM_IN_TABLE, 0)) or bool(props.get(_SPRM_TTP, 0))
        paragraphs.append(
            _Para(
                text=_clean_inline(_strip_fields(body)),
                in_table=in_table or ch == "\x07",
                row_end=bool(props.get(_SPRM_TTP, 0)),
                ends_cell=ch == "\x07",
                istd=istd,
                ilvl=props.get(_SPRM_ILVL, 0) & 0x0F,
                ilfo=props.get(_SPRM_ILFO, 0) & 0xFFFF,
            )
        )
        if len(paragraphs) > _MAX_PARAGRAPHS:
            raise ConversionError("document is too large to convert")
    tail = _clean_inline(_strip_fields(raw[start:]))
    if tail:
        paragraphs.append(_Para(tail))
    return paragraphs


def render_paragraphs(paragraphs: list[_Para]) -> list[str]:
    lines: list[str] = []
    rows: list[list[str]] = []
    cell_parts: list[str] = []
    row: list[str] = []

    def flush_table() -> None:
        if rows:
            table = render_table(rows)
            if table:
                lines.extend([table, ""])
            rows.clear()

    for para in paragraphs:
        if para.in_table:
            if para.row_end:
                if row:
                    rows.append(row)
                row = []
                cell_parts = []
                continue
            cell_parts.append(para.text)
            if para.ends_cell:
                row.append("<br>".join(part for part in cell_parts if part))
                cell_parts = []
            continue
        flush_table()
        if not para.text:
            continue
        level = para.istd if 1 <= para.istd <= 9 else 0
        if level:
            lines.extend([f"{'#' * min(level, 6)} {para.text}", ""])
        elif para.ilfo:
            lines.append(f"{'  ' * min(para.ilvl, 5)}- {para.text}")
        else:
            lines.extend([para.text, ""])
    flush_table()
    return lines


class DocEngine(BaseEngine):
    name = "doc"
    supported_kinds = (FileKind.DOC,)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        head = source.read_bytes()[:16]
        if head.startswith(b"{\\rtf"):
            from doc2md.engine.rtf import rtf_to_text

            return "\n".join([f"# {source.name}", "", LEGACY_NOTE, "", rtf_to_text(source.read_bytes()), ""])
        if not head.startswith(OLE_MAGIC):
            raise ConversionError(f"Not a Word binary document: {source}")
        try:
            import olefile
        except ImportError as exc:
            raise EngineUnavailableError(
                "DOC backend missing: pip install -r requirements.txt (olefile)"
            ) from exc

        try:
            ole = olefile.OleFileIO(str(source))
        except Exception as exc:
            raise ConversionError(f"Corrupted or unreadable DOC: {source} ({exc})") from exc
        try:
            if not ole.exists("WordDocument"):
                raise ConversionError(f"Not a Word document (no WordDocument stream): {source}")
            word = ole.openstream("WordDocument").read()
            if len(word) < 0x200 or _u16(word, 0) != 0xA5EC:
                raise ConversionError(f"Unsupported Word version (before Word 97): {source}")
            flags = _u16(word, 0x0A)
            if flags & 0x0100:
                raise ConversionError(f"Password-protected DOC cannot be converted: {source}")
            table_name = "1Table" if flags & 0x0200 else "0Table"
            if not ole.exists(table_name):
                raise ConversionError(f"Corrupted DOC (missing {table_name}): {source}")
            table = ole.openstream(table_name).read()
            try:
                document = _WordBinary.open(word, table)
                paragraphs = paragraphs_of(document)
            except ConversionError:
                raise
            except (struct.error, IndexError, ValueError) as exc:
                raise ConversionError(f"Corrupted or unsupported DOC: {source} ({exc})") from exc
        finally:
            ole.close()

        body = render_paragraphs(paragraphs)
        text = "\n".join(body).strip()
        if not text:
            pictures = document.text().count("\x01")
            if pictures:
                raise ConversionError(
                    f"This .doc holds only {pictures} picture(s) and no text (a scan placed in "
                    f"Word). Save it as PDF or export the pictures, then convert that: {source}"
                )
            raise ConversionError(f"No text could be extracted from: {source}")
        return "\n".join([f"# {source.name}", "", LEGACY_NOTE, "", text, ""])
