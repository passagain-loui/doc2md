"""Shared Markdown table construction.

Every engine (PDF, DOCX, XLSX, PPTX) funnels its extracted grids through this
module so a table looks identical no matter which format it came from, and so
the three failure modes that used to skew Thai tables are fixed in one place:

1. **Column drift.** Ragged source grids (merged cells, trailing empty cells,
   a header row shorter than the body) used to emit rows with different pipe
   counts, which every Markdown renderer resolves by silently dropping or
   shifting cells. ``normalize_rows`` pads every row to the widest row first.
2. **Broken cells.** A literal ``|``, a newline, or a stray backslash inside a
   cell terminates the cell early. ``escape_cell`` neutralizes all three.
3. **Padding by character count.** Aligning columns with spaces measured in
   Python characters is wrong for Thai: ``สระ``/vowel marks and tone marks are
   zero-width combining characters, so a visually short cell counts as long and
   the pipes zig-zag. This module deliberately emits *unpadded* canonical
   Markdown - the pipes are then guaranteed to line up structurally, and the
   renderer (not us) decides visual width.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "escape_cell",
    "is_table_line",
    "normalize_rows",
    "render_table",
    "display_width",
]

# Control characters that must never reach a cell. Newlines are handled
# separately (converted to <br>), so they are excluded from this class.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"[^\S\n]+")
_NEWLINE_RE = re.compile(r"\r\n|\r|\n")
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")

# Unicode general categories with no advance width. Thai vowel/tone marks are
# Mn (nonspacing mark); Cf covers ZWJ/ZWNJ and friends.
_ZERO_WIDTH_CATEGORIES = frozenset({"Mn", "Me", "Cf"})

CELL_LINE_BREAK = "<br>"


def display_width(text: str) -> int:
    """Approximate rendered width of *text* in terminal cells.

    Thai combining marks contribute 0; CJK/fullwidth characters contribute 2.
    Used for diagnostics and column-width heuristics, never for padding the
    Markdown output itself.
    """
    width = 0
    for char in text:
        if unicodedata.category(char) in _ZERO_WIDTH_CATEGORIES:
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def escape_cell(value: object) -> str:
    """Render *value* as a single safe Markdown table cell.

    ``None`` becomes an empty cell, embedded newlines become ``<br>`` so
    multi-line cells stay inside their column, and pipes/backslashes are
    escaped so they cannot terminate the cell.
    """
    if value is None:
        return ""
    if value is True or value is False:
        return "true" if value else "false"

    text = value if isinstance(value, str) else str(value)
    text = _CONTROL_RE.sub("", text)
    # Escape backslashes before pipes, otherwise the backslash we add below
    # would itself be escaped and re-expose the pipe.
    text = text.replace("\\", "\\\\").replace("|", "\\|")

    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in _NEWLINE_RE.split(text)]
    lines = [line for line in lines if line]
    return CELL_LINE_BREAK.join(lines)


def normalize_rows(rows, *, drop_empty_rows: bool = True) -> list[list[str]]:
    """Escape every cell and pad every row to a single common width.

    Rows that are entirely empty after escaping are dropped by default; a table
    made only of such rows normalizes to ``[]`` so callers can skip it.
    """
    escaped: list[list[str]] = []
    for row in rows or []:
        if row is None:
            continue
        cells = [escape_cell(cell) for cell in row]
        if drop_empty_rows and not any(cells):
            continue
        escaped.append(cells)

    if not escaped:
        return []

    width = max(len(row) for row in escaped)
    return [row + [""] * (width - len(row)) for row in escaped]


def _header_row(cells: list[str], *, name_empty: bool) -> list[str]:
    """Return the header row, optionally naming its empty columns.

    Spreadsheets want ``col1..colN`` placeholders - their first row is often
    data rather than a header, and an unnamed column is unreferenceable.
    Documents do not: inventing a column name that is not in the source is a
    change to the content, so DOCX/PPTX/PDF leave empty headers empty.
    """
    if not name_empty:
        return list(cells)
    return [cell if cell else f"col{index + 1}" for index, cell in enumerate(cells)]


def render_table(
    rows, *, header: bool = True, alignments=None, name_empty_headers: bool = False
) -> str:
    """Render *rows* (an iterable of iterables) as a GitHub-flavoured table.

    ``header=False`` emits a generated ``col1..colN`` header, which Markdown
    requires: a table without a separator row is not a table at all and renders
    as a wall of pipe characters.
    """
    grid = normalize_rows(rows)
    if not grid:
        return ""

    width = len(grid[0])
    if header:
        head, body = _header_row(grid[0], name_empty=name_empty_headers), grid[1:]
    else:
        head, body = [f"col{i + 1}" for i in range(width)], grid

    separator = _separator_cells(width, alignments)
    lines = [
        "| " + " | ".join(head) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _separator_cells(width: int, alignments) -> list[str]:
    if not alignments:
        return ["---"] * width
    out: list[str] = []
    for index in range(width):
        align = alignments[index] if index < len(alignments) else None
        if align == "left":
            out.append(":---")
        elif align == "right":
            out.append("---:")
        elif align == "center":
            out.append(":---:")
        else:
            out.append("---")
    return out


def is_table_line(line: str) -> bool:
    """True when *line* is part of a pipe table.

    Used by the output sanitizer to leave table blocks alone: the generic
    prose cleanup collapses consecutive duplicate lines, which would silently
    delete a legitimately repeated table row.
    """
    return bool(_TABLE_LINE_RE.match(line))
