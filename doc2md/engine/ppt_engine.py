"""Legacy binary PowerPoint (.ppt) engine, pure Python on top of ``olefile``.

Slide order and slide contents are found the way PowerPoint itself finds them,
not by scanning the stream for text (a .ppt that was edited and saved
incrementally still holds the *old* versions of slides, and a scan would emit
those too):

1. ``Current User`` points at the newest ``UserEditAtom``.
2. Each edit links to the previous one and to a ``PersistDirectoryAtom`` that
   maps persist ids to stream offsets; older edits are applied first so newer
   ones override them.
3. The document container's ``SlideListWithText`` lists the slides in order as
   persist ids, which resolve to the current slide containers.

Placeholder text (titles, bullets) lives in the slide list; text boxes live in
each slide's drawing. Both are collected.

Speaker notes are found the same way, through the *current* edit chain, so an
older version of a note that was later changed is never emitted:

4. A slide's ``SlideAtom`` carries ``notesIdRef`` (0 = the slide has no notes).
   In files PowerPoint writes it is a *notes page identifier*, not a persist
   id: the document's notes list (``SlideListWithText`` instance 2) records that
   id for each notes page together with the page's persist id, and the persist
   directory maps that to the ``Notes`` container. (A producer that puts the
   notes persist id there directly is accepted too, when the container's
   ``NotesAtom`` names the same slide; with no ``SlideAtom`` at all, the notes
   page whose ``NotesAtom`` names the slide is used.)
5. The note text is the notes body placeholder of that container (a
   ``TextHeaderAtom`` of type 2 followed by ``TextCharsAtom``/``TextBytesAtom``);
   text boxes added to the notes page and slide-number placeholders are
   skipped. Text kept in the notes list itself is used if the page has none.

Each note is emitted under its slide as ``> Speaker notes: ...`` on one line,
exactly as the .pptx engine does. Not recovered: tables as grids (cell text
comes through in shape order), levels of bullet indentation and pictures. A note
on every result says so.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
LEGACY_NOTE = (
    "> Legacy .ppt: slide text and speaker notes were recovered; table layout, "
    "bullet levels and pictures were not."
)

_REC_DOCUMENT = 0x03E8
_REC_SLIDE = 0x03EE
_REC_SLIDE_ATOM = 0x03EF
_REC_NOTES = 0x03F0
_REC_NOTES_ATOM = 0x03F1
_REC_SLIDE_LIST = 0x0FF0
_REC_SLIDE_PERSIST = 0x03F3
_REC_USER_EDIT = 0x0FF5
_REC_PERSIST_DIR = 0x1772
_REC_TEXT_HEADER = 0x0F9F
_REC_CLIENT_TEXTBOX = 0xF00D
_REC_TEXT_CHARS = 0x0FA0
_REC_TEXT_BYTES = 0x0FA8
_TITLE_TYPES = {0, 6}
_NOTES_TYPE = 2
_MAX_RECORDS = 2_000_000
_MAX_DEPTH = 32


@dataclass
class _TextBlock:
    kind: int
    text: str


@dataclass
class _SlideText:
    placeholders: list[_TextBlock] = field(default_factory=list)
    boxes: list[str] = field(default_factory=list)
    slide_id: int = 0


@dataclass
class _NotesEntry:
    """One page of the document's notes list: which slide it belongs to, and any text kept there."""

    slide_id: int = 0
    texts: list[str] = field(default_factory=list)


def _header(data: bytes, offset: int) -> tuple[int, int, int, int]:
    """Return ``(version, instance, type, length)`` of the record at *offset*."""
    ver_inst, rec_type, length = struct.unpack_from("<HHI", data, offset)
    return ver_inst & 0x0F, ver_inst >> 4, rec_type, length


def _decode_text(rec_type: int, payload: bytes) -> str:
    if rec_type == _REC_TEXT_CHARS:
        text = payload.decode("utf-16-le", errors="replace")
    else:
        text = payload.decode("cp1252", errors="replace")
    text = text.replace("\x0b", "\n").replace("\xa0", " ")
    return "".join(ch for ch in text if ch in "\r\n\t" or ch >= " ")


def _walk(data: bytes, start: int, end: int, depth: int = 0, recurse: bool = True):
    """Yield ``(type, instance, payload_start, payload_end, is_container)`` in order."""
    if depth > _MAX_DEPTH:
        return
    offset = start
    count = 0
    while offset + 8 <= end:
        version, instance, rec_type, length = _header(data, offset)
        body = offset + 8
        stop = min(body + length, end)
        yield rec_type, instance, body, stop, version == 0x0F
        count += 1
        if count > _MAX_RECORDS:
            raise ConversionError("presentation is too large to convert")
        if version == 0x0F and recurse:
            yield from _walk(data, body, stop, depth + 1)
        offset = body + length


def _persist_offsets(data: bytes, current_user: bytes) -> tuple[dict[int, int], int]:
    """Resolve persist id -> stream offset across the whole edit chain."""
    edit_at = struct.unpack_from("<I", current_user, 16)[0]
    chain: list[tuple[int, int]] = []
    doc_persist_id = 0
    seen: set[int] = set()
    while edit_at and edit_at not in seen and edit_at + 8 <= len(data):
        seen.add(edit_at)
        _version, _instance, rec_type, _length = _header(data, edit_at)
        if rec_type != _REC_USER_EDIT:
            break
        body = edit_at + 8
        last_edit, directory, doc_ref = struct.unpack_from("<III", data, body + 8)
        if not doc_persist_id:
            doc_persist_id = doc_ref
        chain.append((edit_at, directory))
        edit_at = last_edit

    offsets: dict[int, int] = {}
    for _edit, directory in reversed(chain):
        if directory + 8 > len(data):
            continue
        _v, _i, rec_type, length = _header(data, directory)
        if rec_type != _REC_PERSIST_DIR:
            continue
        pos = directory + 8
        stop = min(pos + length, len(data))
        while pos + 4 <= stop:
            head = struct.unpack_from("<I", data, pos)[0]
            pos += 4
            first, count = head & 0xFFFFF, head >> 20
            for n in range(count):
                if pos + 4 > stop:
                    break
                offsets[first + n] = struct.unpack_from("<I", data, pos)[0]
                pos += 4
    return offsets, doc_persist_id


def _slide_order(
    data: bytes, offsets: dict[int, int], doc_persist_id: int
) -> tuple[list[int], dict[int, _SlideText], dict[int, _NotesEntry]]:
    """Slide persist ids in order, placeholder text from the slide list, and the notes list."""
    doc_at = offsets.get(doc_persist_id)
    if doc_at is None or doc_at + 8 > len(data):
        raise ConversionError("unreadable presentation (document container not found)")
    _v, _i, rec_type, length = _header(data, doc_at)
    if rec_type != _REC_DOCUMENT:
        raise ConversionError("unreadable presentation (unexpected document record)")

    order: list[int] = []
    text_by_slide: dict[int, _SlideText] = {}
    notes_list: dict[int, _NotesEntry] = {}
    for rec_type, instance, body, stop, _container in _walk(
        data, doc_at + 8, doc_at + 8 + length, recurse=False
    ):
        # Instance 0 lists the slides; 1 is the masters and 2 the notes pages.
        if rec_type != _REC_SLIDE_LIST or instance not in (0, 2):
            continue
        current: _SlideText | None = None
        note: _NotesEntry | None = None
        kind = 4
        for rec_type, _instance, atom, atom_stop, _c in _walk(data, body, stop, recurse=False):
            if rec_type == _REC_SLIDE_PERSIST:
                persist_id = struct.unpack_from("<I", data, atom)[0]
                slide_id = struct.unpack_from("<I", data, atom + 12)[0] if atom_stop - atom >= 16 else 0
                kind = 4
                if instance == 0:
                    current = _SlideText(slide_id=slide_id)
                    text_by_slide[persist_id] = current
                    order.append(persist_id)
                else:
                    note = _NotesEntry(slide_id=slide_id)
                    notes_list[persist_id] = note
            elif rec_type == _REC_TEXT_HEADER and (current is not None or note is not None):
                kind = struct.unpack_from("<I", data, atom)[0]
            elif rec_type in (_REC_TEXT_CHARS, _REC_TEXT_BYTES):
                text = _decode_text(rec_type, data[atom:atom_stop])
                if not text.strip():
                    continue
                if instance == 0 and current is not None and kind != _NOTES_TYPE:
                    current.placeholders.append(_TextBlock(kind, text))
                elif instance == 2 and note is not None and kind == _NOTES_TYPE:
                    note.texts.append(text)
    return order, text_by_slide, notes_list


def _notes_page_text(data: bytes, notes_at: int) -> tuple[list[str], int]:
    """Notes-body text of the ``Notes`` container at *notes_at*, and the slide id it names."""
    if notes_at + 8 > len(data):
        return [], 0
    _v, _i, rec_type, length = _header(data, notes_at)
    if rec_type != _REC_NOTES:
        return [], 0
    texts: list[str] = []
    slide_id = 0
    kind = 4
    for rec_type, _instance, body, stop, _container in _walk(data, notes_at + 8, notes_at + 8 + length):
        if rec_type == _REC_NOTES_ATOM and stop - body >= 4:
            slide_id = struct.unpack_from("<I", data, body)[0]
        elif rec_type == _REC_CLIENT_TEXTBOX:
            kind = 4
        elif rec_type == _REC_TEXT_HEADER:
            kind = struct.unpack_from("<I", data, body)[0]
        elif rec_type in (_REC_TEXT_CHARS, _REC_TEXT_BYTES) and kind == _NOTES_TYPE:
            text = _decode_text(rec_type, data[body:stop])
            if text.strip():
                texts.append(text)
    return texts, slide_id


def _slide_notes_ref(data: bytes, slide_at: int) -> int | None:
    """``notesIdRef`` from the slide's ``SlideAtom``, or ``None`` if it has none."""
    if slide_at + 8 > len(data):
        return None
    _v, _i, rec_type, length = _header(data, slide_at)
    if rec_type != _REC_SLIDE:
        return None
    for rec_type, _instance, body, stop, _container in _walk(
        data, slide_at + 8, slide_at + 8 + length, recurse=False
    ):
        if rec_type == _REC_SLIDE_ATOM and stop - body >= 20:
            return struct.unpack_from("<I", data, body + 16)[0]
        break  # the SlideAtom is always the first record
    return None


def _speaker_notes(
    data: bytes,
    offsets: dict[int, int],
    notes_list: dict[int, _NotesEntry],
    slide_at: int | None,
    slide_id: int,
) -> str:
    """The slide's speaker notes as one whitespace-collapsed line ("" if none)."""
    notes_ref = _slide_notes_ref(data, slide_at) if slide_at is not None else None
    if notes_ref == 0:
        return ""  # PowerPoint's own statement that this slide has no notes page
    persist_id: int | None = None
    if notes_ref is not None:
        persist_id = next((pid for pid, entry in notes_list.items() if entry.slide_id == notes_ref), None)
        if persist_id is None and slide_id and notes_ref in offsets:
            # notesIdRef holding the notes persist id itself; trust it only if
            # the container names this very slide.
            if _notes_page_text(data, offsets[notes_ref])[1] == slide_id:
                persist_id = notes_ref
    elif slide_id:
        # No SlideAtom to ask: find the notes page that names this slide.
        persist_id = next(
            (
                pid
                for pid in notes_list
                if pid in offsets and _notes_page_text(data, offsets[pid])[1] == slide_id
            ),
            None,
        )
    if persist_id is None:
        return ""
    texts: list[str] = []
    if persist_id in offsets:
        texts, _named = _notes_page_text(data, offsets[persist_id])
    if not texts and persist_id in notes_list:
        texts = notes_list[persist_id].texts
    return " ".join(" ".join(text.split()) for text in texts).strip()


def _slide_boxes(data: bytes, slide_at: int) -> list[_TextBlock]:
    _v, _i, rec_type, length = _header(data, slide_at)
    if rec_type != _REC_SLIDE:
        return []
    boxes: list[_TextBlock] = []
    kind = 4
    for rec_type, _instance, body, stop, _container in _walk(data, slide_at + 8, slide_at + 8 + length):
        if rec_type == _REC_CLIENT_TEXTBOX:
            kind = 4
        elif rec_type == _REC_TEXT_HEADER:
            kind = struct.unpack_from("<I", data, body)[0]
        elif rec_type in (_REC_TEXT_CHARS, _REC_TEXT_BYTES):
            text = _decode_text(rec_type, data[body:stop])
            if text.strip() and kind != _NOTES_TYPE:
                boxes.append(_TextBlock(kind, text))
    return boxes


def _paragraphs(text: str) -> list[str]:
    return [line.strip() for line in text.replace("\n", "\r").split("\r") if line.strip()]


def slides_from_stream(data: bytes, current_user: bytes) -> list[list[str]]:
    offsets, doc_persist_id = _persist_offsets(data, current_user)
    order, text_by_slide, notes_list = _slide_order(data, offsets, doc_persist_id)
    slides: list[list[str]] = []
    for index, persist_id in enumerate(order, start=1):
        content = text_by_slide[persist_id]
        blocks = list(content.placeholders)
        slide_at = offsets.get(persist_id)
        if slide_at is not None and slide_at + 8 <= len(data):
            blocks.extend(_slide_boxes(data, slide_at))
        try:
            notes = _speaker_notes(data, offsets, notes_list, slide_at, content.slide_id)
        except Exception:  # notes are a bonus: a damaged notes page never fails the slide
            notes = ""
        title = ""
        body: list[str] = []
        for block in blocks:
            lines = _paragraphs(block.text)
            if block.kind in _TITLE_TYPES and not title:
                title = " ".join(lines)
            else:
                body.append(lines)
        if not title and body and len(body[0]) == 1:
            # No placeholder marked the title; the first text on a slide is it.
            title = body.pop(0)[0]
        body = [f"- {line}" for lines in body for line in lines]
        heading = f"## Slide {index}: {title}" if title else f"## Slide {index}"
        lines = [heading, ""]
        if body:
            lines.extend([*body, ""])
        if notes:
            lines.extend([f"> Speaker notes: {notes}", ""])
        slides.append(lines)
    return slides


class PptEngine(BaseEngine):
    name = "ppt"
    supported_kinds = (FileKind.PPT,)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        if not source.read_bytes()[:8] == OLE_MAGIC:
            raise ConversionError(f"Not a PowerPoint binary presentation: {source}")
        try:
            import olefile
        except ImportError as exc:
            raise EngineUnavailableError(
                "PPT backend missing: pip install -r requirements.txt (olefile)"
            ) from exc
        try:
            ole = olefile.OleFileIO(str(source))
        except Exception as exc:
            raise ConversionError(f"Corrupted or unreadable PPT: {source} ({exc})") from exc
        try:
            if not (ole.exists("PowerPoint Document") and ole.exists("Current User")):
                raise ConversionError(f"Not a PowerPoint presentation: {source}")
            data = ole.openstream("PowerPoint Document").read()
            current_user = ole.openstream("Current User").read()
            if len(current_user) < 20:
                raise ConversionError(f"Corrupted PPT (Current User stream): {source}")
            if b"Encrypted" in current_user[:40]:
                raise ConversionError(f"Password-protected PPT cannot be converted: {source}")
            try:
                slides = slides_from_stream(data, current_user)
            except ConversionError:
                raise
            except (struct.error, IndexError, ValueError, KeyError) as exc:
                raise ConversionError(f"Corrupted or unsupported PPT: {source} ({exc})") from exc
        finally:
            ole.close()

        if not slides:
            raise ConversionError(f"No slides could be read from: {source}")
        parts = [f"# {source.name}", "", LEGACY_NOTE, ""]
        for slide in slides:
            parts.extend(slide)
        return "\n".join(parts).rstrip() + "\n"
