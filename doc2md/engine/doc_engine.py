"""Legacy binary Word (.doc) engine, pure Python on top of ``olefile``.

A .doc stores its text as a list of *pieces* (the piece table in the ``Clx``)
and its paragraph formatting in separate *FKP* pages. This reader follows the
[MS-DOC] layout far enough to recover what a converted document needs:

* the text, in order, with field codes dropped and field results kept;
* real **table** structure - rows and cells come from the paragraph flags
  (``fInTable`` / ``fTtp``), not from guessing at the cell marks, so a table with
  empty cells keeps its columns;
* **headings** (built-in ``Heading 1..9`` styles) and **list** items with depth;
* **bold and italic** - the character-property FKPs (``PlcBteChpx`` in the FIB,
  the ``ChpxFkp`` pages, the CHPX ``grpprl``) give ``sprmCFBold`` (0x0835) and
  ``sprmCFItalic`` (0x0836) per run of the text stream. Both are *toggle*
  properties: ``0``/``1`` set the value, ``0x80`` keeps and ``0x81`` inverts the
  value the style gives. The style value comes from the style sheet (the
  ``Stshf``): the paragraph style's character formatting, its ``istdBase``
  chain, and a character style named by ``sprmCIstd`` (``Strong``, ``Emphasis``).
  Runs become ``**..**`` / ``*..*`` (``***..***`` for both), trimmed of
  surrounding spaces, merged across a plain space, never split inside a Thai
  syllable (a combining mark or vowel stays with its consonant, a leading vowel
  with the one after it), and never emitted in headings or in a table's
  header row. If any of those structures is missing or malformed the text comes
  out plain - formatting can never make a conversion fail.

Not recovered: headers and footers, footnotes, text boxes and pictures. A note
at the top of every result says so, so the output is never mistaken for a
full-fidelity conversion.

Some ``.doc`` files are not Word binaries at all (an RTF or HTML page saved
with a .doc name). Those are sniffed and routed accordingly.
"""

from __future__ import annotations

import bisect
import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.core.tables import render_table
from doc2md.engine.base import BaseEngine

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
LEGACY_NOTE = (
    "> Legacy .doc: text, headings, lists, tables and bold/italic were recovered; "
    "headers/footers, footnotes and text boxes were not."
)
# A .doc that is really RTF goes through the plain-text RTF reader, which keeps no emphasis.
RTF_NOTE = (
    "> Legacy .doc (RTF inside): text was recovered; bold/italic, headers/footers, "
    "footnotes and text boxes were not."
)

_SPRM_IN_TABLE = 0x2416
_SPRM_TTP = 0x2417
_SPRM_ILVL = 0x260A
_SPRM_ILFO = 0x460B
_SPRM_ISTD = 0x4600
_SPRM_C_BOLD = 0x0835
_SPRM_C_ITALIC = 0x0836
_SPRM_C_ISTD = 0x4A30
_PAP_SPRMS = frozenset((_SPRM_IN_TABLE, _SPRM_TTP, _SPRM_ILVL, _SPRM_ISTD, _SPRM_ILFO))
_CHP_SPRMS = frozenset((_SPRM_C_BOLD, _SPRM_C_ITALIC, _SPRM_C_ISTD))
_NO_STYLE = 0x0FFF
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
    md: str = ""  # *text* with bold/italic markers; empty when there is nothing to mark


@dataclass
class _Style:
    sgc: int  # 1 paragraph, 2 character
    base: int
    ops: dict[int, int]


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _toggle(operand: int | None, inherited: bool) -> bool:
    """Apply a ToggleOperand: 0/1 set, 0x80 keep the style's value, 0x81 invert it."""
    if operand is None or operand == 0x80:
        return inherited
    if operand == 0x81:
        return not inherited
    return bool(operand & 1)


def _parse_sprms(grpprl: bytes, wanted: frozenset[int] = _PAP_SPRMS) -> dict[int, int]:
    """Read the sprms in *wanted*; skip every other one correctly."""
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
        if opcode in wanted and operand:
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
        # Character formatting. Every part is optional: when one is missing or
        # malformed it stays empty and the text simply comes out unmarked.
        self._piece_starts: list[int] = []
        self._chpx: list[tuple[int, int, dict[int, int]]] = []
        self._chpx_starts: list[int] = []
        self._styles: dict[int, _Style] = {}
        self._style_cache: dict[tuple[int, int, bool], bool] = {}
        self._flag_cache: dict[tuple, int] = {}
        self.formatting = False

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
        doc._piece_starts = [piece.cp_start for piece in doc.pieces]
        doc._read_formatting()
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

    # --------------------------------------------------- character formatting
    def _read_formatting(self) -> None:
        """Load the CHPX runs and the style sheet; never raise."""
        try:
            self._read_chpx()
        except Exception:
            self._chpx, self._chpx_starts = [], []
        try:
            self._read_styles()
        except Exception:
            self._styles = {}
        self._style_cache.clear()
        self._flag_cache.clear()
        self.formatting = bool(self._chpx) or any(
            _SPRM_C_BOLD in style.ops or _SPRM_C_ITALIC in style.ops
            for style in self._styles.values()
        )

    def _read_chpx(self) -> None:
        """``PlcBteChpx`` -> ``ChpxFkp`` pages -> (fc start, fc end, bold/italic/style sprms)."""
        fc_plc, lcb_plc = self._fc_lcb(12)
        plc = self.table[fc_plc:fc_plc + lcb_plc]
        count = (len(plc) - 4) // 8
        if lcb_plc < 12 or count <= 0:
            return
        pages = struct.unpack_from(f"<{count}I", plc, (count + 1) * 4)
        entries: list[tuple[int, int, dict[int, int]]] = []
        for page_number in pages:
            base = (page_number & 0x3FFFFF) * 512
            page = self.word[base:base + 512]
            if len(page) < 512:
                continue
            runs = page[511]
            if runs == 0 or (runs + 1) * 4 + runs > 511:
                continue
            rgfc = struct.unpack_from(f"<{runs + 1}I", page, 0)
            for r in range(runs):
                b_offset = page[(runs + 1) * 4 + r]
                if not b_offset or rgfc[r + 1] <= rgfc[r]:
                    continue
                at = b_offset * 2
                if at >= 511:
                    continue
                cb = page[at]
                ops = _parse_sprms(page[at + 1:at + 1 + cb], _CHP_SPRMS)
                if ops:
                    entries.append((rgfc[r], rgfc[r + 1], ops))
        entries.sort(key=lambda entry: entry[0])
        self._chpx = entries
        self._chpx_starts = [entry[0] for entry in entries]

    def _read_styles(self) -> None:
        """``Stshf``: per style, its kind, parent and character-formatting sprms."""
        fc_stsh, lcb_stsh = self._fc_lcb(1)
        stsh = self.table[fc_stsh:fc_stsh + lcb_stsh]
        if len(stsh) < 4:
            return
        cb_stshi = _u16(stsh, 0)
        stshi = stsh[2:2 + cb_stshi]
        if len(stshi) < 4:
            return
        count, cb_base = _u16(stshi, 0), _u16(stshi, 2)
        if cb_base < 10:
            return
        at = 2 + cb_stshi
        for istd in range(count):
            if at + 2 > len(stsh):
                break
            cb_std = _u16(stsh, at)
            std = stsh[at + 2:at + 2 + cb_std]
            at += 2 + cb_std
            if cb_std == 0 or len(std) < cb_base + 2:
                continue
            try:
                style = self._read_style(std, cb_base)
            except (struct.error, IndexError):
                continue
            if style is not None:
                self._styles[istd] = style

    @staticmethod
    def _read_style(std: bytes, cb_base: int) -> "_Style | None":
        sgc = _u16(std, 2) & 0x0F
        base = _u16(std, 2) >> 4
        cupx = _u16(std, 4) & 0x0F
        pos = cb_base + 2 + _u16(std, cb_base) * 2 + 2  # Xstz: cch, characters, terminator
        upxs: list[bytes] = []
        for _ in range(cupx):
            if pos + 2 > len(std):
                break
            size = _u16(std, pos)
            upxs.append(std[pos + 2:pos + 2 + size])
            pos += 2 + size + (size & 1)
        if sgc == 1 and len(upxs) >= 2:
            chp = upxs[1]  # UpxPapx, then UpxChpx
        elif sgc == 2 and upxs:
            chp = upxs[0]
        else:
            return _Style(sgc, base, {}) if sgc in (1, 2) else None
        return _Style(sgc, base, _parse_sprms(chp, _CHP_SPRMS))

    def _style_value(self, istd: int, sprm: int, start: bool = False) -> bool:
        """Bold/italic a style gives, folding its ``istdBase`` chain onto *start*."""
        key = (istd, sprm, start)
        cached = self._style_cache.get(key)
        if cached is not None:
            return cached
        chain: list[_Style] = []
        seen: set[int] = set()
        current = istd
        while current not in seen and current != _NO_STYLE and current in self._styles and len(chain) < 32:
            seen.add(current)
            chain.append(self._styles[current])
            current = self._styles[current].base
        value = start
        for style in reversed(chain):
            value = _toggle(style.ops.get(sprm), value)
        self._style_cache[key] = value
        return value

    def _flags_for(self, ops: dict[int, int] | None, para_istd: int) -> int:
        """Bit 0 bold, bit 1 italic, for a run with direct sprms *ops* in a paragraph of style *para_istd*."""
        ops = ops or {}
        key = (para_istd, ops.get(_SPRM_C_BOLD), ops.get(_SPRM_C_ITALIC), ops.get(_SPRM_C_ISTD))
        cached = self._flag_cache.get(key)
        if cached is not None:
            return cached
        flags = 0
        for bit, sprm in ((1, _SPRM_C_BOLD), (2, _SPRM_C_ITALIC)):
            value = self._style_value(para_istd, sprm)
            char_style = ops.get(_SPRM_C_ISTD)
            if char_style is not None:
                value = self._style_value(char_style & 0xFFFF, sprm, value)
            if _toggle(ops.get(sprm), value):
                flags |= bit
        self._flag_cache[key] = flags
        return flags

    def char_flags(self, cp_start: int, cp_end: int, para_istd: int) -> list[int] | None:
        """Bold/italic flags for each character of ``[cp_start, cp_end)``, or ``None``."""
        out: list[int] = []
        cp = cp_start
        while cp < cp_end:
            index = bisect.bisect_right(self._piece_starts, cp) - 1
            if index < 0 or index >= len(self.pieces) or cp >= self.pieces[index].cp_end:
                return None
            piece = self.pieces[index]
            step = 1 if piece.compressed else 2
            stop = min(cp_end, piece.cp_end)
            while cp < stop:
                fc = piece.fc_at(cp)
                at = bisect.bisect_right(self._chpx_starts, fc) - 1
                if at >= 0 and fc < self._chpx[at][1]:
                    run_end, ops = self._chpx[at][1], self._chpx[at][2]
                else:
                    ops = None
                    run_end = (
                        self._chpx_starts[at + 1] if at + 1 < len(self._chpx_starts) else fc + (stop - cp) * step
                    )
                count = min(stop - cp, max(1, -(-(run_end - fc) // step)))
                out.extend([self._flags_for(ops, para_istd)] * count)
                cp += count
        return out

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


def _field_mask(text: str) -> list[bool]:
    """Per character: is it kept? Field results are, field instructions are not."""
    keep: list[bool] = []
    stack: list[str] = []
    for ch in text:
        if ch == _FIELD_BEGIN:
            stack.append("code")
            keep.append(False)
        elif ch == _FIELD_SEP:
            if stack:
                stack[-1] = "result"
            keep.append(False)
        elif ch == _FIELD_END:
            if stack:
                stack.pop()
            keep.append(False)
        else:
            keep.append(all(state == "result" for state in stack))
    return keep


def _strip_fields(text: str) -> str:
    """Keep field results, drop field instructions (``HYPERLINK ...``, ``PAGE``)."""
    return "".join(ch for ch, keep in zip(text, _field_mask(text)) if keep)


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


_INLINE_MAP = {"\x0b": "\n", "\x1e": "-", "\xa0": " ", "\x09": " "}


def _clean_marked(body: str, flags: list[int]) -> tuple[list[str], list[int]]:
    """:func:`_strip_fields` + :func:`_clean_inline`, keeping a flag per character."""
    chars: list[str] = []
    kept: list[int] = []
    for ch, keep, flag in zip(body, _field_mask(body), flags):
        if not keep:
            continue
        ch = _INLINE_MAP.get(ch, ch)
        if ord(ch) in _DROP:
            continue
        chars.append(ch)
        kept.append(flag)
    low, high = 0, len(chars)
    while low < high and chars[low].isspace():
        low += 1
    while high > low and chars[high - 1].isspace():
        high -= 1
    return chars[low:high], kept[low:high]


# Thai marks that must stay with the character before them, and the leading
# vowels that must stay with the one after: a marker between the two would cut
# a syllable in half.
_THAI_AFTER = frozenset("ะาำๆ")
_THAI_LEADING = frozenset("เแโใไ")
_JOINERS = frozenset("‌‍")


def _tidy_stream(chars: list[str], on: list[bool]) -> list[bool]:
    """One emphasis kind: bridge a plain space between two runs, trim spaces off the edges."""
    size = len(chars)
    on = [flag and chars[i] != "\n" for i, flag in enumerate(on)]
    i = 0
    while i < size:
        if on[i] or not chars[i].isspace() or chars[i] == "\n":
            i += 1
            continue
        j = i
        while j < size and not on[j] and chars[j].isspace() and chars[j] != "\n":
            j += 1
        if i > 0 and j < size and on[i - 1] and on[j]:
            on[i:j] = [True] * (j - i)
        i = j
    i = 0
    while i < size:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < size and on[j]:
            j += 1
        low, high = i, j
        while low < high and chars[low].isspace():
            on[low] = False
            low += 1
        while high > low and chars[high - 1].isspace():
            on[high - 1] = False
            high -= 1
        i = j
    return on


def _emphasize(chars: list[str], flags: list[int]) -> str:
    """Markdown for *chars* with bold (bit 0) / italic (bit 1) runs wrapped in ``**`` / ``*``."""
    flags = list(flags)
    for i in range(1, len(chars)):
        if (
            unicodedata.category(chars[i]).startswith("M")
            or chars[i] in _JOINERS
            or chars[i] in _THAI_AFTER
        ):
            flags[i] = flags[i - 1]
    for i in range(len(chars) - 2, -1, -1):
        if chars[i] in _THAI_LEADING:
            flags[i] = flags[i + 1]
    bold = _tidy_stream(chars, [bool(flag & 1) for flag in flags])
    italic = _tidy_stream(chars, [bool(flag & 2) for flag in flags])
    marker = {"b": "**", "i": "*"}
    out: list[str] = []
    stack: list[str] = []
    start = 0
    while start < len(chars):
        state = (bold[start], italic[start])
        end = start
        while end < len(chars) and (bold[end], italic[end]) == state:
            end += 1
        want = [name for name, on in zip("bi", state) if on]
        text = "".join(chars[start:end])
        stale = [k for k, name in enumerate(stack) if name not in want]
        reopen: list[str] = []
        if stale:
            # A marker that ends while one opened after it stays open: close both,
            # and reopen the survivor once the text really starts (a marker
            # followed by a space does not open emphasis).
            popped = stack[stale[0]:]
            del stack[stale[0]:]
            out.extend(marker[name] for name in reversed(popped))
            reopen = [name for name in popped if name in want]
            out.append(text[: len(text) - len(text.lstrip())])
            text = text.lstrip()
        for name in reopen + [name for name in want if name not in stack and name not in reopen]:
            out.append(marker[name])
            stack.append(name)
        out.append(text)
        start = end
    out.extend(marker[name] for name in reversed(stack))
    return "".join(out)


def _emphasis_markdown(doc: _WordBinary, cp_start: int, cp_end: int, body: str, istd: int, plain: str) -> str:
    """The paragraph with ``**``/``*`` markers, or ``""`` to use *plain* (any problem, or nothing to mark)."""
    if not doc.formatting or not plain:
        return ""
    try:
        flags = doc.char_flags(cp_start, cp_end, istd)
        if flags is None or len(flags) != len(body) or not any(flags):
            return ""
        chars, kept = _clean_marked(body, flags)
        if "".join(chars) != plain or not any(kept):
            return ""
        marked = _emphasize(chars, kept)
        return marked if marked != plain else ""
    except Exception:
        return ""


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
        text = _clean_inline(_strip_fields(body))
        paragraphs.append(
            _Para(
                text=text,
                in_table=in_table or ch == "\x07",
                row_end=bool(props.get(_SPRM_TTP, 0)),
                ends_cell=ch == "\x07",
                istd=istd,
                ilvl=props.get(_SPRM_ILVL, 0) & 0x0F,
                ilfo=props.get(_SPRM_ILFO, 0) & 0xFFFF,
                md=_emphasis_markdown(doc, mark_cp - len(body), mark_cp, body, istd, text),
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
            # The first row is the Markdown header, which renders bold already.
            cell_parts.append(para.text if not rows else para.md or para.text)
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
            lines.append(f"{'  ' * min(para.ilvl, 5)}- {para.md or para.text}")
        else:
            lines.extend([para.md or para.text, ""])
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

            return "\n".join([f"# {source.name}", "", RTF_NOTE, "", rtf_to_text(source.read_bytes()), ""])
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
