"""Builders for legacy binary Office fixtures (OLE container, .doc, .ppt).

No Word or PowerPoint is available to produce real files in CI, so these write
the structures the engines read, straight from the [MS-CFB], [MS-DOC] and
[MS-PPT] layouts. They are deliberately small and only cover what the tests
need; the engines are also run against real files outside the test suite.
"""

from __future__ import annotations

import struct

END = 0xFFFFFFFE
FREE = 0xFFFFFFFF
FAT_SECTOR = 0xFFFFFFFD
SECTOR = 512


# ------------------------------------------------------------------ container


def build_cfb(streams: dict[str, bytes]) -> bytes:
    """A minimal OLE compound file. Streams are padded to 4096 bytes so none
    lives in the mini stream (which this writer does not implement)."""
    names = list(streams)
    payloads = []
    for name in names:
        data = streams[name]
        size = len(data)
        data = data + bytes(max(4096, -(-size // SECTOR) * SECTOR) - size)
        payloads.append((len(data), data))  # the recorded size must be >= 4096

    entries = 1 + len(names)
    dir_sectors = -(-entries // 4)
    data_sectors = [len(data) // SECTOR for _size, data in payloads]
    fat_sectors = 1
    while True:
        total = fat_sectors + dir_sectors + sum(data_sectors)
        if fat_sectors * 128 >= total:
            break
        fat_sectors += 1

    fat = [FREE] * (fat_sectors * 128)
    for index in range(fat_sectors):
        fat[index] = FAT_SECTOR
    cursor = fat_sectors
    dir_start = cursor
    for n in range(dir_sectors):
        fat[cursor + n] = cursor + n + 1 if n < dir_sectors - 1 else END
    cursor += dir_sectors
    starts = []
    for count in data_sectors:
        starts.append(cursor)
        for n in range(count):
            fat[cursor + n] = cursor + n + 1 if n < count - 1 else END
        cursor += count

    def entry(name: str, kind: int, left=FREE, right=FREE, child=FREE, start=END, size=0) -> bytes:
        raw = name.encode("utf-16-le")
        record = raw + bytes(64 - len(raw))
        record += struct.pack("<HBB", len(raw) + 2 if name else 0, kind, 1)
        record += struct.pack("<III", left, right, child)
        record += bytes(16) + struct.pack("<I", 0) + bytes(16)
        record += struct.pack("<III", start, size, 0)
        return record

    directory = [entry("Root Entry", 5, child=1 if names else FREE)]
    for index, name in enumerate(names):
        right = index + 2 if index + 1 < len(names) else FREE
        directory.append(entry(name, 2, right=right, start=starts[index], size=payloads[index][0]))
    directory_bytes = b"".join(directory)
    directory_bytes += bytes(dir_sectors * SECTOR - len(directory_bytes))

    difat = list(range(fat_sectors)) + [FREE] * (109 - fat_sectors)
    header = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(16)
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + bytes(6)
        + struct.pack("<IIIIIIIII", 0, fat_sectors, dir_start, 0, 4096, END, 0, END, 0)
        + struct.pack("<109I", *difat)
    )
    body = struct.pack(f"<{len(fat)}I", *fat) + directory_bytes + b"".join(d for _s, d in payloads)
    return header + body


# ------------------------------------------------------------------------ .doc


def _papx(istd: int, in_table=False, ttp=False, ilfo=0, ilvl=0) -> bytes:
    sprms = b""
    if in_table:
        sprms += struct.pack("<HB", 0x2416, 1)
    if ttp:
        sprms += struct.pack("<HB", 0x2417, 1)
    if ilvl:
        sprms += struct.pack("<HB", 0x260A, ilvl)
    if ilfo:
        sprms += struct.pack("<HH", 0x460B, ilfo)
    data = struct.pack("<H", istd) + sprms
    if len(data) % 2 == 0:
        data += b"\x00"
    return bytes([(len(data) + 1) // 2]) + data


BOLD, ITALIC, CISTD = 0x0835, 0x0836, 0x4A30
_CHP_PACK = {BOLD: "<HB", ITALIC: "<HB", CISTD: "<HH"}
NO_STYLE = 0x0FFF


def _grpprl(ops: dict[int, int]) -> bytes:
    return b"".join(struct.pack(_CHP_PACK[opcode], opcode, value) for opcode, value in ops.items())


def _chpx_page(runs, text_fc: int, step: int, total: int) -> bytes:
    """One ChpxFkp page. *runs*: ascending ``(start_cp, end_cp, ops)``; gaps stay unformatted."""
    spans = []
    position = 0
    for start, end, ops in runs:
        if start > position:
            spans.append((position, start, None))
        spans.append((start, end, ops))
        position = end
    if position < total:
        spans.append((position, total, None))
    page = bytearray(SECTOR)
    count = len(spans)
    for index, (start, _end, _ops) in enumerate(spans):
        struct.pack_into("<I", page, index * 4, text_fc + start * step)
    struct.pack_into("<I", page, count * 4, text_fc + total * step)
    free = SECTOR - 1
    for index, (_start, _end, ops) in enumerate(spans):
        if not ops:
            continue
        grpprl = _grpprl(ops)
        chpx = bytes([len(grpprl)]) + grpprl
        free = (free - len(chpx)) & ~1
        assert free > (count + 1) * 5, "too many runs for one FKP page"
        page[free:free + len(chpx)] = chpx
        page[(count + 1) * 4 + index] = free // 2
    page[SECTOR - 1] = count
    return bytes(page)


def _stsh(styles: dict[int, tuple[int, int, dict[int, int]]], cb_base: int = 18) -> bytes:
    """The style sheet. *styles*: ``istd -> (sgc, istdBase, character sprms)``; gaps are empty slots."""
    count = max(styles) + 1
    stshi = struct.pack("<HH", count, cb_base) + bytes(14)
    out = struct.pack("<H", len(stshi)) + stshi
    for istd in range(count):
        if istd not in styles:
            out += b"\x00\x00"
            continue
        sgc, base, ops = styles[istd]
        name = f"Style{istd}"
        std = struct.pack("<HHHHH", istd & 0x0FFF, sgc | (base << 4), (2 if sgc == 1 else 1) | (istd << 4), 0, 0)
        std += bytes(cb_base - 10)
        std += struct.pack("<H", len(name)) + name.encode("utf-16-le") + b"\x00\x00"
        upxs = [struct.pack("<H", 0)] if sgc == 1 else []  # a paragraph style starts with its (empty) UpxPapx
        upxs.append(_grpprl(ops))
        for upx in upxs:
            std += struct.pack("<H", len(upx)) + upx + (b"\x00" if len(upx) % 2 else b"")
        std += bytes(len(std) % 2)
        out += struct.pack("<H", len(std)) + std
    return out


def build_doc(paragraphs, *, compressed: bool = False, styles=None, damage: str | None = None) -> bytes:
    """*paragraphs*: ``(text, kind, props)`` where kind is ``para``, ``cell`` or
    ``rowend`` and props may hold ``istd``, ``ilfo``, ``ilvl`` and ``chp`` - a
    list of ``(offset, length, ops)`` giving character sprms (``BOLD``,
    ``ITALIC``, ``CISTD``) to a slice of the paragraph's text.

    *styles* (``istd -> (sgc, istdBase, ops)``) adds a style sheet. *damage*
    breaks one formatting structure on purpose (``"fkp"``, ``"plc"``,
    ``"stsh"``) to show the text still converts."""
    text = ""
    spans = []
    chp_runs = []
    for body, kind, props in paragraphs:
        start = len(text)
        for offset, length, ops in (props or {}).get("chp", ()):
            chp_runs.append((start + offset, start + offset + length, ops))
        text += body + ("\r" if kind == "para" else "\x07")
        spans.append((start, len(text), kind, props or {}))
    total = len(text)
    text_fc = 0x400
    step = 1 if compressed else 2
    raw_text = text.encode("cp1252") if compressed else text.encode("utf-16-le")

    # FKP page holding one entry per paragraph
    page = bytearray(SECTOR)
    runs = len(spans)
    for index, (start, _end, _kind, _props) in enumerate(spans):
        struct.pack_into("<I", page, index * 4, text_fc + start * step)
    struct.pack_into("<I", page, runs * 4, text_fc + total * step)
    free = SECTOR - 1
    for index, (_s, _e, kind, props) in enumerate(spans):
        papx = _papx(
            props.get("istd", 0),
            in_table=kind in ("cell", "rowend"),
            ttp=kind == "rowend",
            ilfo=props.get("ilfo", 0),
            ilvl=props.get("ilvl", 0),
        )
        free = (free - len(papx)) & ~1
        page[free:free + len(papx)] = papx
        page[(runs + 1) * 4 + index * 13] = free // 2
    page[SECTOR - 1] = runs

    word = bytearray(0x400 + len(raw_text))
    pn = 6  # the FKP page lives at 6 * 512, after the text
    word += bytes(pn * SECTOR - len(word))
    word += page
    struct.pack_into("<H", word, 0x00, 0xA5EC)
    struct.pack_into("<H", word, 0x02, 0x00C1)
    struct.pack_into("<H", word, 0x0A, 0x0200)
    struct.pack_into("<H", word, 0x20, 14)
    struct.pack_into("<H", word, 0x3E, 22)
    struct.pack_into("<I", word, 0x40 + 3 * 4, total)
    struct.pack_into("<H", word, 0x98, 93)
    word[text_fc:text_fc + len(raw_text)] = raw_text

    fc_value = (text_fc * 2) | 0x40000000 if compressed else text_fc
    plc_pcd = struct.pack("<II", 0, total) + struct.pack("<HIH", 0, fc_value, 0)
    clx = b"\x02" + struct.pack("<I", len(plc_pcd)) + plc_pcd
    plcf_bte = struct.pack("<II", text_fc, text_fc + total * step) + struct.pack("<I", pn)
    table = clx + plcf_bte
    fc_lcb_at = 0x9A
    struct.pack_into("<II", word, fc_lcb_at + 33 * 8, 0, len(clx))
    struct.pack_into("<II", word, fc_lcb_at + 13 * 8, len(clx), len(plcf_bte))

    if chp_runs:
        chpx_pn = 7  # right after the paragraph FKP page
        word += _chpx_page(sorted(chp_runs, key=lambda run: run[0]), text_fc, step, total)
        if damage == "fkp":
            word[chpx_pn * SECTOR + SECTOR - 1] = 250  # a run count no 512-byte page can hold
        plcf_chpx = struct.pack("<II", text_fc, text_fc + total * step) + struct.pack(
            "<I", 900 if damage == "plc" else chpx_pn
        )
        struct.pack_into("<II", word, fc_lcb_at + 12 * 8, len(table), len(plcf_chpx))
        table += plcf_chpx
    if styles:
        stsh = _stsh(styles)
        if damage == "stsh":
            stsh = b"\xff\xff" + stsh[2:40]  # a size field that points past the data
        struct.pack_into("<II", word, fc_lcb_at + 1 * 8, len(table), len(stsh))
        table += stsh
    return build_cfb({"WordDocument": bytes(word), "1Table": table})


# ------------------------------------------------------------------------ .ppt


def _record(rec_type: int, payload: bytes = b"", *, instance: int = 0, container: bool = False) -> bytes:
    ver = 0x0F if container else 0
    return struct.pack("<HHI", ver | (instance << 4), rec_type, len(payload)) + payload


def _text(kind: int, value: str, *, unicode_text: bool = True) -> bytes:
    header = _record(0x0F9F, struct.pack("<I", kind))
    if unicode_text:
        return header + _record(0x0FA0, value.encode("utf-16-le"))
    return header + _record(0x0FA8, value.encode("cp1252"))


def _slide_container(box_texts, notes_ref: int | None = None) -> bytes:
    """A slide. With *notes_ref* it opens with a SlideAtom whose ``notesIdRef`` is that value."""
    atom = b""
    if notes_ref is not None:
        atom = _record(0x03EF, struct.pack("<I8sIIHH", 0x10, bytes(8), 0x80000000, notes_ref, 7, 0))
    boxes = b"".join(
        _record(0xF00D, _record(0x0FA0, text.encode("utf-16-le")), container=True) for text in box_texts
    )
    return _record(0x03EE, atom + _record(0x040C, boxes, container=True), container=True)


def _notes_container(slide_id: int, lines: list[str]) -> bytes:
    """A notes page: NotesAtom, the slide-number placeholder, the notes body and a stray text box."""
    atom = _record(0x03F1, struct.pack("<IHH", slide_id, 7, 0))
    number_box = _record(0xF00D, _text(4, "*"), container=True)
    body_box = _record(0xF00D, _text(2, "\r".join(lines)), container=True)
    stray_box = _record(0xF00D, _text(4, "stray text box on the notes page"), container=True)
    drawing = _record(0x040C, number_box + body_box + stray_box, container=True)
    return _record(0x03F0, atom + drawing, container=True)


def build_ppt(
    slides, *, edit_slide: tuple[int, list[str]] | None = None, edits=(), notes_mode: str = "id"
) -> bytes:
    """*slides*: ``(title, [bullet text, ...], [text box, ...][, [note line, ...]])``.

    A fourth element (even an empty list) switches speaker notes on: every slide
    then opens with a SlideAtom, and slides with note lines get a notes page.

    ``edit_slide=(index, new_boxes)`` appends an incremental save that replaces
    one slide, leaving its old version in the stream, as PowerPoint does.
    ``edits`` is a list of further saves, each ``(index, new_boxes_or_None,
    new_notes_or_None)``: ``None`` boxes leave the slide alone, ``None`` notes
    leave the notes alone, ``[]`` notes remove them (notesIdRef becomes 0). The
    slide must already have notes to change them.

    ``notes_mode`` picks how notes are wired, as different producers do:
    ``"id"`` (PowerPoint: notesIdRef is the notes-list id), ``"persist"``
    (notesIdRef is the notes persist id, no notes list), ``"no_atom"`` (slides
    have no SlideAtom) and ``"list_text"`` (the note text sits in the notes
    list, no notes page).
    """
    notes_on = any(len(slide) > 3 for slide in slides)
    notes = {number: list(slide[3]) for number, slide in enumerate(slides) if len(slide) > 3 and slide[3]}
    k_of = {number: k for k, number in enumerate(notes)}  # position among slides that have notes
    notes_persist = lambda number: 100 + k_of[number]  # noqa: E731
    notes_id = lambda number: 256 + k_of[number]  # noqa: E731
    with_atom = notes_on and notes_mode != "no_atom"
    with_list = notes_on and notes_mode != "persist"
    with_pages = notes_on and notes_mode != "list_text"

    def ref_for(number: int) -> int:
        if number not in notes:
            return 0
        return notes_persist(number) if notes_mode == "persist" else notes_id(number)

    stream = bytearray()
    slide_list = b""
    for number, slide in enumerate(slides):
        title, body = slide[0], slide[1]
        slide_list += _record(0x03F3, struct.pack("<IIiII", number + 2, 0, 0, 256 + number, 0))
        slide_list += _text(0, title)
        if body:
            slide_list += _text(1, "\r".join(body))
    notes_list = b""
    if with_list:
        for number in notes:
            notes_list += _record(0x03F3, struct.pack("<IIiII", notes_persist(number), 4, 0, notes_id(number), 0))
            if notes_mode == "list_text":
                notes_list += _text(2, "\r".join(notes[number]))
    document_body = _record(0x0FF0, slide_list, instance=0, container=True)
    if notes_list:
        document_body += _record(0x0FF0, notes_list, instance=2, container=True)
    document = _record(0x03E8, document_body, container=True)
    offsets = {1: len(stream)}
    stream += document
    for number, slide in enumerate(slides):
        offsets[number + 2] = len(stream)
        stream += _slide_container(slide[2], ref_for(number) if with_atom else None)
    if with_pages:
        for number, lines in notes.items():
            offsets[notes_persist(number)] = len(stream)
            stream += _notes_container(256 + number, lines)

    def persist_directory(mapping: dict[int, int]) -> bytes:
        ids = sorted(mapping)
        payload = b""
        for persist_id in ids:
            payload += struct.pack("<I", (1 << 20) | persist_id) + struct.pack("<I", mapping[persist_id])
        return _record(0x1772, payload)

    def user_edit(previous: int, directory: int) -> bytes:
        body = struct.pack("<IHBBIIIIHH", 0, 0, 0, 3, previous, directory, 1, 100, 0, 0)
        return _record(0x0FF5, body)

    directory_at = len(stream)
    stream += persist_directory(offsets)
    first_edit = len(stream)
    stream += user_edit(0, directory_at)
    current_edit = first_edit

    saves = list(edits)
    if edit_slide is not None:
        saves.insert(0, (edit_slide[0], edit_slide[1], None))
    for index, new_boxes, new_notes in saves:
        mapping: dict[int, int] = {}
        if new_notes is not None:
            if index not in k_of:
                raise ValueError("only a slide that already has notes can have them changed")
            if new_notes:
                notes[index] = list(new_notes)
                mapping[notes_persist(index)] = len(stream)
                stream += _notes_container(256 + index, notes[index])
            else:
                notes.pop(index, None)
        if new_boxes is not None:
            mapping[index + 2] = len(stream)
            stream += _slide_container(new_boxes, ref_for(index) if with_atom else None)
        elif new_notes is not None and not new_notes and with_atom:
            raise ValueError("removing notes needs a new slide container (pass its boxes)")
        directory_at = len(stream)
        stream += persist_directory(mapping)
        previous, current_edit = current_edit, len(stream)
        stream += user_edit(previous, directory_at)

    current_user = _record(0x0FF6, struct.pack("<IIIHH", 0x14, 0xF3D1C4DF, current_edit, 0, 0))
    return build_cfb({"PowerPoint Document": bytes(stream), "Current User": current_user})

