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


def build_doc(paragraphs, *, compressed: bool = False) -> bytes:
    """*paragraphs*: ``(text, kind, props)`` where kind is ``para``, ``cell`` or
    ``rowend`` and props may hold ``istd``, ``ilfo``, ``ilvl``."""
    text = ""
    spans = []
    for body, kind, props in paragraphs:
        start = len(text)
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


def _slide_container(box_texts) -> bytes:
    boxes = b"".join(
        _record(0xF00D, _record(0x0FA0, text.encode("utf-16-le")), container=True) for text in box_texts
    )
    return _record(0x03EE, _record(0x040C, boxes, container=True), container=True)


def build_ppt(slides, *, edit_slide: tuple[int, list[str]] | None = None) -> bytes:
    """*slides*: ``(title, [bullet text, ...], [text box, ...])``.

    ``edit_slide=(index, new_boxes)`` appends an incremental save that replaces
    one slide, leaving its old version in the stream, as PowerPoint does.
    """
    stream = bytearray()
    slide_list = b""
    for number, (title, body, _boxes) in enumerate(slides):
        slide_list += _record(0x03F3, struct.pack("<IIiII", number + 2, 0, 0, 256 + number, 0))
        slide_list += _text(0, title)
        if body:
            slide_list += _text(1, "\r".join(body))
    document = _record(
        0x03E8, _record(0x0FF0, slide_list, instance=0, container=True), container=True
    )
    offsets = {1: len(stream)}
    stream += document
    for number, (_title, _body, boxes) in enumerate(slides):
        offsets[number + 2] = len(stream)
        stream += _slide_container(boxes)

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

    if edit_slide is not None:
        index, new_boxes = edit_slide
        new_offset = len(stream)
        stream += _slide_container(new_boxes)
        directory_at = len(stream)
        stream += persist_directory({index + 2: new_offset})
        current_edit = len(stream)
        stream += user_edit(first_edit, directory_at)

    current_user = _record(0x0FF6, struct.pack("<IIIHH", 0x14, 0xF3D1C4DF, current_edit, 0, 0))
    return build_cfb({"PowerPoint Document": bytes(stream), "Current User": current_user})
