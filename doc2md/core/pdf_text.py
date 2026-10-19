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
from collections import Counter
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


# --------------------------------------------------------------------------
# Dingbat fonts: ticks and crosses that extract as private-use junk
# --------------------------------------------------------------------------
#
# A tick or a cross in a table (Word's checkboxes, an itinerary's "meal included")
# is a character of a symbol font: Wingdings, Wingdings 2, ZapfDingbats ... Such a
# font has no meaningful Unicode map, so PyMuPDF returns either the private-use
# code point U+F0xx or the bare byte (e.g. U+F0FB) - invisible junk in the
# Markdown - or, when the PDF carries a ToUnicode table, the right symbol.
# The table below maps only well-known code points, and only when the character's
# own font is that dingbat font: the same code in an ordinary font is a letter.
# Each entry was checked against the glyph in a real PDF (marked "seen") or is the
# standard published code for it; anything not certain is left out on purpose
# (for instance Wingdings 2 0x4F, 0x50, 0xA3, whose glyphs could not be verified).
_DINGBAT_MAP: dict[str, dict[int, str]] = {
    "wingdings": {
        0xFC: chr(0x2713),  # check mark
        0xFB: chr(0x2717),  # ballot x, seen: a plain cross in a meal table
        0xFE: chr(0x2611),  # ballot box with check
        0xFD: chr(0x2612),  # ballot box with x
        0xA8: chr(0x2610),  # empty ballot box
        0x6C: chr(0x25CF),  # black circle
    },
    "wingdings2": {
        0x52: chr(0x2611),  # seen: a check inside a box
        0x54: chr(0x2612),  # seen: a cross inside a box
    },
    "webdings": {
        0xE3: chr(0x1F6CF),  # seen: a bed, beside hotel names
    },
    "zapfdingbats": {
        0x33: chr(0x2713),  # check mark
        0x34: chr(0x2714),  # heavy check mark
        0x35: chr(0x2715),  # multiplication x
        0x36: chr(0x2716),  # heavy multiplication x
        0x37: chr(0x2717),  # ballot x
        0x38: chr(0x2718),  # heavy ballot x
    },
}


def dingbat_family(font: str) -> str | None:
    """The key of :data:`_DINGBAT_MAP` for a font name (``BCDJEE+Wingdings-Regular``
    -> ``wingdings``), or ``None`` for any other font."""
    family = re.sub(r"[^a-z0-9]", "", font_family(font))
    if family.endswith("zapfdingbats"):
        return "zapfdingbats"
    return family if family in _DINGBAT_MAP else None


def map_dingbat(text: str, font: str) -> str:
    """*text* (one character) as the Unicode symbol its dingbat *font* draws.

    Only the private-use form (U+F020-U+F0FF) and the bare byte (below U+0100) are
    mapped; text that is already a real symbol, and any character of any other
    font, is returned unchanged."""
    if len(text) != 1:
        return text
    family = dingbat_family(font)
    if family is None:
        return text
    code = ord(text)
    if 0xF020 <= code <= 0xF0FF:
        code -= 0xF000
    elif code >= 0x100:
        return text
    return _DINGBAT_MAP[family].get(code, text)


def page_has_dingbat_font(page) -> bool:
    """Whether any font used on *page* is a dingbat font (cheap: font list only)."""
    try:
        return any(dingbat_family(str(font[3])) for font in page.get_fonts())
    except Exception:
        return False


def _repair(chars: list[Char], buggy: frozenset[str]) -> list[Char]:
    out: list[Char] = []
    for position, char in enumerate(chars):
        if _is_zero_width_space(char):
            continue  # an unmapped nikhahit or similar: never real text
        if char.text == SARA_AM and font_family(char.font) in buggy:
            if not _nikhahit_before(chars, position):
                char = Char(SARA_AA, char.x0, char.y0, char.x1, char.y1, char.font)
        symbol = map_dingbat(char.text, char.font)
        if symbol != char.text:
            char = Char(symbol, char.x0, char.y0, char.x1, char.y1, char.font)
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

# Latin-1 Supplement / Latin Extended-A/B *letters* (U+00C0-U+024F) with the two
# non-letters in that block, multiplication and division signs, taken out.
_LATIN_EXT = "\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u024f"
# One or two such letters with a Thai character (letter or mark) touching both
# sides: a legit "Café" or "Škoda" is never glued into the middle of a Thai word.
_THAI_LATIN_THAI = re.compile(rf"[\u0e01-\u0e5b][{_LATIN_EXT}]{{1,2}}(?=[\u0e01-\u0e5b])")

# A font with a wrong cmap can map Thai tone marks and upper/lower vowels to Latin
# Extended code points. Smallest number of such sandwiched letters on a page that
# counts as mis-encoded, and the most Thai letters allowed per hit (one in 500), so
# that a long, clean page with a few oddities is not condemned.
MOJIBAKE_MIN_HITS = 3
MOJIBAKE_MAX_THAI_PER_HIT = 500


def latin_ext_in_thai_count(text: str) -> int:
    """How many times Latin Extended letters sit directly between Thai characters."""
    return len(_THAI_LATIN_THAI.findall(text))


def has_latin_mojibake(text: str) -> bool:
    """Whether Latin Extended letters inside Thai words reach the page threshold."""
    hits = latin_ext_in_thai_count(text)
    if hits < MOJIBAKE_MIN_HITS:
        return False
    thai = len(_THAI_LETTER.findall(text))
    return thai <= hits * MOJIBAKE_MAX_THAI_PER_HIT


def thai_text_is_corrupt(text: str) -> bool:
    """Whether a page's text layer is mis-encoded Thai (see the two checks below).

    :func:`has_latin_mojibake` marks swapped for Latin letters - a consistent
    substitution that :func:`learn_mojibake_map` can undo; :func:`has_lost_marks`
    is the older, unrepairable kind (symbols, digits or control characters).
    """
    return has_latin_mojibake(text) or has_lost_marks(text)


def has_lost_marks(text: str) -> bool:
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


# --------------------------------------------------------------------------
# Marks swapped for other characters, undone with a map learned from the document
# --------------------------------------------------------------------------
#
# When the font's cmap sends marks to Latin Extended letters it does so
# consistently ("ē" is always one tone mark in that document), but which letter
# stands for which mark differs from font to font, so no fixed table is kept.
# The map is learned instead: OCR reads the same page correctly, and wherever
# the text layer and OCR agree on the surrounding letters, the marks OCR has
# in the gap are what the stray character stood for. A few pages' worth of
# agreement is enough to trust a character.
#
# Marks are not letters here: the "skeleton" of a text is its Thai consonants,
# vowels and digits with every mark (and every swapped-in character) removed.
# That is what the two readings are compared on.

MOJIBAKE_MAP_MIN_VOTES = 2
"""Aligned occurrences that must agree before a character is mapped."""
MOJIBAKE_MAP_MIN_AGREEMENT = 0.75
"""Share of a character's votes the winning mark(s) must hold."""
_CONTEXT_BEFORE = 3  # skeleton letters up to and including the one carrying the gap
_CONTEXT_AFTER = 3
_MIN_CONTEXT = 4  # letters a window needs before it is searched for in the OCR text
_LEARN_ROUNDS = 3  # a character learned in one round resolves gaps of two in the next

_THAI_MARK_CHARS = frozenset(
    chr(code) for code in (0x0E31, *range(0x0E34, 0x0E3B), 0x0E47, 0x0E48, 0x0E49, 0x0E4A, 0x0E4B, 0x0E4C, 0x0E4D, 0x0E4E)
)
# The Latin letters above plus the Private Use Area, where Thai fonts keep the
# raised, lowered and shifted forms of tone marks and vowels (U+F700-U+F71A).
_MOJIBAKE_CHARS = _LATIN_EXT + "-"
_MOJIBAKE_RUN = re.compile(
    rf"(?<=[ก-๛])[{_MOJIBAKE_CHARS}]+|[{_MOJIBAKE_CHARS}]+(?=[ก-๛])"
)


_MOJIBAKE_CHAR = re.compile(f"[{_MOJIBAKE_CHARS}]")


def _is_mojibake_char(char: str) -> bool:
    return _MOJIBAKE_CHAR.match(char) is not None


def _is_skeleton_char(char: str) -> bool:
    if "ก" <= char <= "๛":
        return char not in _THAI_MARK_CHARS
    return "0" <= char <= "9"


@dataclass
class _Clusters:
    """A text read as base letters, each with the marks (and stray characters) after it."""

    skeleton: str
    gaps: list[str]
    runs: list[int]  # which unbroken stretch (no space, newline, Latin letter...) each letter is in


def _clusters(text: str) -> _Clusters:
    skeleton: list[str] = []
    gaps: list[str] = []
    runs: list[int] = []
    run = 0
    broken = False
    for char in text:
        if _is_skeleton_char(char):
            if broken:
                run += 1
                broken = False
            skeleton.append(char)
            gaps.append("")
            runs.append(run)
        elif char in _THAI_MARK_CHARS or _is_mojibake_char(char):
            if skeleton and not broken:
                gaps[-1] += char
        else:
            broken = True
    return _Clusters("".join(skeleton), gaps, runs)


def _window(layer: _Clusters, index: int) -> tuple[str, int] | None:
    """The skeleton letters around *index*, and where *index* sits in them.

    Taken from its own unbroken run of text when that is long enough; a word
    ending in the stray character ("...รอ" then a space) has too little after
    it, so the window then reaches over the break into the neighbouring words.
    """
    start = index
    while start > 0 and layer.runs[start - 1] == layer.runs[index] and index - start < _CONTEXT_BEFORE - 1:
        start -= 1
    end = index
    while end + 1 < len(layer.runs) and layer.runs[end + 1] == layer.runs[index] and end - index < _CONTEXT_AFTER:
        end += 1
    if end - start + 1 < _MIN_CONTEXT:
        start = max(0, index - (_CONTEXT_BEFORE - 1))
        end = min(len(layer.skeleton) - 1, index + _CONTEXT_AFTER)
    if end - start + 1 < _MIN_CONTEXT:
        return None
    return layer.skeleton[start:end + 1], index - start


_UPPER_VOWELS = frozenset("ัิีึื็ํ")
_TONE_MARKS = frozenset("่้๊๋")
_LOWER_VOWELS = frozenset("ฺุู")
_THANTHAKHAT = "์"


def _is_valid_cluster(marks: str) -> bool:
    """Whether *marks* can sit on one Thai letter: at most one of each kind."""
    return (
        sum(char in _UPPER_VOWELS for char in marks) <= 1
        and sum(char in _TONE_MARKS for char in marks) <= 1
        and sum(char in _LOWER_VOWELS for char in marks) <= 1
        and marks.count(_THANTHAKHAT) <= 1
    )


def _collect_votes(layer: _Clusters, ocr: _Clusters, known: dict[str, str]) -> dict[str, Counter]:
    votes: dict[str, Counter] = {}
    for index, gap in enumerate(layer.gaps):
        if not gap or not any(_is_mojibake_char(char) for char in gap):
            continue
        expanded = "".join(known.get(char, char) if _is_mojibake_char(char) else char for char in gap)
        strays = [at for at, char in enumerate(expanded) if _is_mojibake_char(char)]
        # One stray may stand for one mark or two; two strays side by side can
        # only be told apart when OCR has exactly one mark for each.
        if not strays or len(strays) > 2 or strays[-1] - strays[0] + 1 != len(strays):
            continue
        first, last = strays[0], strays[-1]
        before, after = expanded[:first], expanded[last + 1:]
        window = _window(layer, index)
        if window is None:
            continue
        pattern, offset = window
        values: set[str] = set()
        found = ocr.skeleton.find(pattern)
        while found != -1:
            theirs = ocr.gaps[found + offset]
            middle = theirs[len(before):len(theirs) - len(after)]
            if (
                theirs.startswith(before)
                and theirs.endswith(after)
                and (len(middle) in (1, 2) if len(strays) == 1 else len(middle) == 2)
                and not any(_is_mojibake_char(char) for char in theirs)
                and _is_valid_cluster(theirs)
            ):
                values.add(middle)
            found = ocr.skeleton.find(pattern, found + 1)
        if len(values) == 1:
            (value,) = values
            if len(strays) == 1:
                votes.setdefault(expanded[first], Counter())[value] += 1
            else:
                for at, mark in zip(strays, value):
                    votes.setdefault(expanded[at], Counter())[mark] += 1
    return votes


def _accepted(votes: dict[str, Counter]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for char, counter in votes.items():
        value, count = counter.most_common(1)[0]
        if count >= MOJIBAKE_MAP_MIN_VOTES and count / sum(counter.values()) >= MOJIBAKE_MAP_MIN_AGREEMENT:
            mapping[char] = value
    return mapping


def mojibake_votes(text_layer: str, ocr_text: str) -> dict[str, Counter]:
    """For each swapped-in character, how often OCR had each mark (or pair) in its place."""
    layer, ocr = _clusters(text_layer), _clusters(ocr_text)
    known: dict[str, str] = {}
    votes: dict[str, Counter] = {}
    for _ in range(_LEARN_ROUNDS):
        votes = _collect_votes(layer, ocr, known)
        learned = _accepted(votes)
        if learned == known:
            break
        known = learned
    return votes


def learn_mojibake_map(text_layer: str, ocr_text: str) -> dict[str, str]:
    """Which Thai mark(s) each swapped-in character stands for, learned from one document.

    *text_layer* and *ocr_text* are two readings of the same pages (pass every
    affected page of the document joined together: more pages, more votes).
    A character is mapped only when at least ``MOJIBAKE_MAP_MIN_VOTES``
    aligned occurrences agree on it and those make up at least
    ``MOJIBAKE_MAP_MIN_AGREEMENT`` of all its votes. One character may stand for
    two marks (a vowel mark plus a tone mark), so values are one or two marks.
    """
    return _accepted(mojibake_votes(text_layer, ocr_text))


def repair_mojibake(
    text: str, mapping: dict[str, str], *, drop_unmapped: bool = False
) -> tuple[str, int]:
    """*text* with swapped-in characters replaced by their marks, and how many had none.

    Only characters touching Thai (directly after a Thai character or directly
    before one) are considered, so a real "Café" or "Škoda" is never altered.
    The count is of those characters that had no mapping; they stay in the
    text, or are left out of it with ``drop_unmapped``.
    """
    left = 0

    def swap(match: re.Match) -> str:
        nonlocal left
        out = []
        for char in match.group():
            if char in mapping:
                out.append(mapping[char])
            else:
                left += 1
                if not drop_unmapped:
                    out.append(char)
        return "".join(out)

    return _MOJIBAKE_RUN.sub(swap, text), left
