r"""Minimal RTF to text, for the .doc files that are really RTF.

Handles paragraphs, tabs, table cells/rows, ``\uN`` Unicode escapes and
``\'hh`` bytes in the document's code page (874 for Thai). Everything else -
font and colour tables, pictures, headers, field instructions - is skipped.
"""

from __future__ import annotations

import re

_CONTROL_RE = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])")
_SKIP_DESTINATIONS = frozenset({
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer",
    "headerl", "headerr", "footerl", "footerr", "fldinst", "listtable",
    "listoverridetable", "rsidtbl", "generator", "themedata", "colorschememapping",
    "latentstyles", "datastore", "xmlnstbl", "object", "shppict", "nonshppict",
})


def rtf_to_text(data: bytes) -> str:
    text = data.decode("latin-1")
    codepage = "cp1252"
    match = re.search(r"\\ansicpg(\d+)", text)
    if match:
        codepage = f"cp{match.group(1)}"
    unicode_skip = 1

    out: list[str] = []
    pending = bytearray()
    stack: list[tuple[bool, int]] = []
    skipping = False
    skip_chars = 0
    position = 0
    length = len(text)

    def flush_bytes() -> None:
        if pending:
            try:
                out.append(pending.decode(codepage))
            except (UnicodeDecodeError, LookupError):
                out.append(pending.decode("cp1252", errors="replace"))
            pending.clear()

    while position < length:
        char = text[position]
        if char == "{":
            stack.append((skipping, unicode_skip))
            position += 1
            if text.startswith("\\*", position):
                skipping = True
            continue
        if char == "}":
            if stack:
                skipping, unicode_skip = stack.pop()
            position += 1
            continue
        if char in "\r\n":
            position += 1
            continue
        if char != "\\":
            if skip_chars:
                skip_chars -= 1
            elif not skipping:
                flush_bytes()
                out.append(char)
            position += 1
            continue

        match = _CONTROL_RE.match(text, position)
        if not match:
            position += 1
            continue
        position = match.end()
        word, number, hex_byte, symbol = match.groups()
        if hex_byte is not None:
            if skip_chars:
                skip_chars -= 1
            elif not skipping:
                pending.append(int(hex_byte, 16))
            continue
        flush_bytes()
        if symbol is not None:
            if skipping:
                continue
            if symbol in "\\{}":
                out.append(symbol)
            elif symbol == "~":
                out.append(" ")
            elif symbol == "_":
                out.append("-")
            continue
        if word in _SKIP_DESTINATIONS:
            skipping = True
            continue
        if skipping:
            continue
        if word in ("par", "sect", "page"):
            out.append("\n\n")
        elif word == "line":
            out.append("\n")
        elif word == "tab":
            out.append("\t")
        elif word == "cell":
            out.append(" | ")
        elif word == "row":
            out.append("\n")
        elif word == "uc" and number is not None:
            unicode_skip = int(number)
        elif word == "u" and number is not None:
            code = int(number)
            out.append(chr(code + 65536 if code < 0 else code))
            skip_chars = unicode_skip
    flush_bytes()
    result = "".join(out)
    result = re.sub(r"[ \t]+\n", "\n", result)
    return re.sub(r"\n{3,}", "\n\n", result).strip()
