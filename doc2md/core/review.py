"""Lines OCR kept but was unsure about, carried beside the text, not in it.

Up to 1.4.11 a shaky OCR line was flagged by appending `` ⚠58%`` to the
Markdown itself. That text then went everywhere the Markdown went - into files
handed to an AI, where "58%" reads like data. Since 1.5.0 the flag travels as
two private-use characters an engine appends to the line (:func:`encode`), and
:class:`~doc2md.core.converter.Converter` lifts them out (:func:`extract`) into
``ConversionResult.review_lines``. The Markdown a caller gets is clean; the GUI
highlights those lines in its preview, and an output only carries a visible
flag when the user asks for one (:func:`with_inline_flags`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REVIEW_OPEN = ""
REVIEW_CLOSE = ""
VISIBLE_MARK = "⚠"
REPAIR_LOSS_CONFIDENCE = 0
"""Code for a line that lost characters when a mis-encoded PDF text layer was
repaired. It is not an OCR confidence (those are always between 40 and 70), so
0 cannot be mistaken for one: it is shown as a bare flag, never as ``0%``."""

_ENCODED = re.compile(r"[ \t]*(\d{1,3})")
_STRAY = re.compile(r"[]")


@dataclass(frozen=True)
class ReviewLine:
    """One line worth checking against the original.

    ``line`` is a 0-based index into ``markdown.split("\\n")`` of the clean
    Markdown - the same numbering as a ``QPlainTextEdit`` block number.
    """

    line: int
    confidence: int
    text: str


def encode(line: str, confidence: float) -> str:
    """*line* with its review marker appended (used by OCR engines)."""
    return f"{line.rstrip()}{REVIEW_OPEN}{round(confidence)}{REVIEW_CLOSE}"


def count_marked(text: str) -> int:
    """How many lines of an engine's raw output carry a review marker."""
    return text.count(REVIEW_OPEN)


def extract(markdown: str) -> tuple[str, list[ReviewLine]]:
    """Split engine output into clean Markdown and its review lines."""
    if REVIEW_OPEN not in markdown and REVIEW_CLOSE not in markdown:
        return markdown, []
    lines = markdown.split("\n")
    found: list[ReviewLine] = []
    for index, line in enumerate(lines):
        match = _ENCODED.search(line)
        if match:
            line = _ENCODED.sub("", line)
            line = _STRAY.sub("", line)
            found.append(ReviewLine(index, int(match.group(1)), line.strip()))
        lines[index] = _STRAY.sub("", line)
    return "\n".join(lines), found


def with_inline_flags(markdown: str, review_lines: list[ReviewLine]) -> str:
    """*markdown* with a visible `` ⚠NN%`` after every review line.

    For a user who wants the flags inside an output file (to proofread it or
    hand it to someone who will). Out-of-range entries are ignored. A line that
    lost characters in a repair (``REPAIR_LOSS_CONFIDENCE``) gets a bare `` ⚠``.

    On a pipe-table row the flag goes inside the last cell, before the closing
    ``|``: appended after it, the flag would be an extra cell-less fragment and
    break the row.
    """
    if not review_lines:
        return markdown
    lines = markdown.split("\n")
    for entry in review_lines:
        if 0 <= entry.line < len(lines):
            flag = VISIBLE_MARK if entry.confidence == REPAIR_LOSS_CONFIDENCE else f"{VISIBLE_MARK}{entry.confidence}%"
            lines[entry.line] = _flagged(lines[entry.line], flag)
    return "\n".join(lines)


def _flagged(line: str, flag: str) -> str:
    stripped = line.strip()
    if len(stripped) >= 2 and stripped.startswith("|") and stripped.endswith("|"):
        body = line.rstrip()[:-1].rstrip()
        return f"{body} {flag} |"
    return f"{line.rstrip()} {flag}"
