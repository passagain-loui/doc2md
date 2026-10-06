"""Thai-safe text from a PDF page, built from characters rather than from the page string.

Why not just ``page.get_text()``: some producers (found in a Microsoft Excel
export set in AngsanaUPC) embed a font whose character map is wrong in two ways
that together turn Thai into garbage while the page still *looks* right:

* the glyph for **sara aa** (า) is mapped to **sara am** (ำ), so every "ค่าขนส่ง"
  extracts as "ค่ำขนส่ง";
* a real sara am is drawn as a zero-width nikhahit followed by that same glyph,
  and the nikhahit is mapped to a plain space, so "ตำบล" extracts as "ต ำบล".

Both are decidable from the characters themselves: a zero-width space directly
before U+0E33 marks a true sara am, while a bare U+0E33 in the same font is a
sara aa. A font is treated as affected only when that pattern is actually seen
in it, so correctly encoded PDFs are never touched.

Building text from characters also lets table cells be filled from the PDF's own
text (clipped to the cell) instead of pdfminer's, which inserts spaces inside
Thai words and inside numbers ("1 0,400.00").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SARA_AM = "ำ"
SARA_AA = "า"
_ZERO_WIDTH = 0.05
_SCAN_PAGES = 40


@dataclass
class Char:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font: str

    @property
    def centre(self) -> tuple[float, float]:
        # Combining marks have no width; their left edge is where they sit.
        x = self.x0 if self.x1 - self.x0 < _ZERO_WIDTH else (self.x0 + self.x1) / 2
        return x, (self.y0 + self.y1) / 2


@dataclass
class Line:
    chars: list[Char]

    @property
    def text(self) -> str:
        return "".join(char.text for char in self.chars)


_STYLE_RE = re.compile(r"[,\-\s]*(bold|italic|oblique|regular|black|light|medium|semibold)+", re.IGNORECASE)


def font_family(name: str) -> str:
    """``Angsana New,Bold`` and ``Angsana New`` are one typeface with one bad map."""
    return _STYLE_RE.sub("", name.split("+")[-1]).strip().lower()


def _is_zero_width_space(char: Char) -> bool:
    return char.text == " " and char.x1 - char.x0 < _ZERO_WIDTH


def _raw_lines(page) -> list[list[Char]]:
    lines: list[list[Char]] = []
    for block in page.get_text("rawdict").get("blocks", []):
        for line in block.get("lines", []):
            chars: list[Char] = []
            for span in line.get("spans", []):
                font = span.get("font", "")
                for item in span.get("chars", []):
                    x0, y0, x1, y1 = item["bbox"]
                    chars.append(Char(item["c"], x0, y0, x1, y1, font))
            if chars:
                lines.append(chars)
    return lines


def find_sara_bug_fonts(doc) -> frozenset[str]:
    """Fonts in which a true sara am is a zero-width space plus U+0E33."""
    fonts: set[str] = set()
    for index, page in enumerate(doc):
        if index >= _SCAN_PAGES:
            break
        try:
            if SARA_AM not in page.get_text("text"):
                continue
            for chars in _raw_lines(page):
                for position, char in enumerate(chars):
                    if char.text == SARA_AM and _nikhahit_before(chars, position):
                        fonts.add(font_family(char.font))
        except Exception:
            continue
    return frozenset(fonts)


def _nikhahit_before(chars: list[Char], position: int) -> bool:
    """True if the zero-width space that stands for nikhahit precedes *position*,
    possibly with tone marks between them ("น้ำ" is space, tone mark, glyph)."""
    index = position - 1
    while index >= 0 and chars[index].x1 - chars[index].x0 < _ZERO_WIDTH and chars[index].text != " ":
        index -= 1
    return index >= 0 and _is_zero_width_space(chars[index])


def _repair(chars: list[Char], buggy: frozenset[str]) -> list[Char]:
    out: list[Char] = []
    for position, char in enumerate(chars):
        if _is_zero_width_space(char):
            continue  # an unmapped nikhahit or similar: never real text
        if char.text == SARA_AM and font_family(char.font) in buggy:
            if not _nikhahit_before(chars, position):
                char = Char(SARA_AA, char.x0, char.y0, char.x1, char.y1, char.font)
        out.append(char)
    return out


def page_lines(page, buggy: frozenset[str] = frozenset()) -> list[Line]:
    return [Line(_repair(chars, buggy)) for chars in _raw_lines(page)]


def _inside(char: Char, rect) -> bool:
    x, y = char.centre
    left, top, right, bottom = rect
    return left <= x <= right and top <= y <= bottom


def text_in(lines: list[Line], include=None, exclude=(), merge_lines: bool = False) -> str:
    """Text of the characters inside *include* (a ``(x0, top, x1, bottom)`` box,
    or everywhere) and outside every box in *exclude*, one string per line.

    ``merge_lines`` joins fragments that sit on the same visual row (a label and a
    right-aligned note are separate lines to PyMuPDF), which table cells need so
    that the lines of neighbouring cells stay aligned row for row.
    """
    fragments: list[tuple[float, float, float, str]] = []  # y centre, height, x0, text
    for line in lines:
        kept = [
            char for char in line.chars
            if (include is None or _inside(char, include))
            and not any(_inside(char, box) for box in exclude)
        ]
        text = "".join(char.text for char in kept).strip()
        if not text:
            continue
        top = min(char.y0 for char in kept)
        bottom = max(char.y1 for char in kept)
        fragments.append(((top + bottom) / 2, bottom - top, min(char.x0 for char in kept), text))
    if not merge_lines:
        return "\n".join(text for _y, _h, _x, text in fragments)

    rows: list[list[tuple[float, float, float, str]]] = []
    for fragment in sorted(fragments, key=lambda item: item[0]):
        for row in rows:
            if abs(row[0][0] - fragment[0]) <= 0.5 * max(row[0][1], fragment[1]):
                row.append(fragment)
                break
        else:
            rows.append([fragment])
    return "\n".join(
        " ".join(item[3] for item in sorted(row, key=lambda item: item[2])) for row in rows
    )


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_THAI_SYMBOL_THAI = re.compile(r"[\u0e01-\u0e4e][!?\"#$%&()*+<=>@\[\]^_`{|}~0-9][\u0e01-\u0e4e]")
_THAI_LETTER = re.compile(r"[\u0e01-\u0e3a\u0e40-\u0e4e]")


def thai_text_is_corrupt(text: str) -> bool:
    """Whether a page's text layer is mis-encoded Thai that no rule can repair.

    Some producers (a Ghostscript rewrite was seen) lose the character map: tone
    marks and vowels come out as ``!``, ``?``, digits or control characters, as in
    "น้ำท!วมป5". Real Thai text has almost no control characters, and a symbol or
    digit sandwiched between two Thai letters is rare, so either, in quantity, is
    a reliable sign.

    The control-character check runs regardless of how much Thai survived in
    the text - a font whose character map is broken badly enough can lose
    every single Thai codepoint (an Identity-H/Type0 font with no usable
    ToUnicode map extracts as near-total control-character noise), and that
    is the more severe corruption, not a reason to skip the check. Only the
    symbol-sandwiched-in-Thai heuristic needs a real Thai-letter baseline to
    be statistically meaningful.
    """
    if len(_CONTROL.findall(text)) >= 3:
        return True
    thai = len(_THAI_LETTER.findall(text))
    if thai < 50:
        return False
    return len(_THAI_SYMBOL_THAI.findall(text)) >= max(6, thai // 300)
