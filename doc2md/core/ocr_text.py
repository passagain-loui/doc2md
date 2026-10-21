"""Tesseract text recognition with two guards against what brochures do to OCR.

Plain ``image_to_string`` on a catalogue page has two typical failures, both
seen on a real Thai car brochure:

* **Panels read as one text.** A spec table laid out in four side-by-side
  panels is read line by line across all four, so each output line mixes
  fragments of four different rows. Pages are first cut at blank vertical
  gutters, and each panel is read on its own, left to right.
* **Noise from pictures.** Photographs and logos come back as lines of stray
  symbols (``@ ee & ZB งง57``). Each line carries Tesseract's own confidence;
  lines below it are dropped.

Both fall back to the plain call when anything is unavailable (an older
pytesseract, an image that cannot be analysed), so recognition never gets
worse than before.
"""

from __future__ import annotations

import difflib
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from doc2md.core import review

MIN_LINE_CONFIDENCE = 40.0
MIN_SHORT_LINE_CONFIDENCE = 60.0
SHORT_LINE_CHARS = 3
# A line above the drop floor is still kept, but one this shaky is worth a
# reader double-checking against the original - see _mark_uncertain().
REVIEW_LINE_CONFIDENCE = 70.0
EDGE_STRENGTH = 40
GUTTER_INK_LEVEL = 3  # of 255: a column with ink on at most ~1% of its rows is blank
MIN_GUTTER_FRACTION = 0.0035
TOP_MARGIN = 0.05  # headers and footer strips (logos, page numbers) span the gutters
BOTTOM_MARGIN = 0.07
MIN_BAND_FRACTION = 0.10
_ANALYSIS_WIDTH = 1600


def _pixel_values(image) -> list:
    """Every pixel value of *image*, row by row.

    ``Image.getdata()`` is deprecated (removed in Pillow 14); its replacement
    ``get_flattened_data()`` only exists in newer Pillow, and requirements.txt
    allows older, so fall back to the old call there.
    """
    flatten = getattr(image, "get_flattened_data", None)
    return list(flatten() if flatten is not None else image.getdata())


def find_vertical_gutters(image) -> list[tuple[int, int]]:
    """Blank vertical bands between content, as ``(start, end)`` pixel columns.

    Uses edge density per column rather than brightness, so dark pages and
    light pages are treated alike. Margins at the left and right edges are not
    gutters.
    """
    from PIL import Image, ImageFilter

    width, height = image.size
    if width < 200 or height < 100:
        return []
    scale = min(1.0, _ANALYSIS_WIDTH / width)
    small = image.convert("L")
    if scale < 1.0:
        small = small.resize((max(1, int(width * scale)), max(1, int(height * scale))))
    sw, _sh = small.size
    sh = small.size[1]
    body = small.crop((0, int(sh * TOP_MARGIN), sw, max(int(sh * TOP_MARGIN) + 1, int(sh * (1 - BOTTOM_MARGIN)))))
    ink = body.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > EDGE_STRENGTH else 0)
    profile = _pixel_values(ink.resize((sw, 1), Image.BOX))

    quiet = [value <= GUTTER_INK_LEVEL for value in profile]
    if not any(not q for q in quiet):
        return []
    first = quiet.index(False)
    last = len(quiet) - 1 - quiet[::-1].index(False)
    min_gutter = max(3, int(sw * MIN_GUTTER_FRACTION))

    gutters: list[tuple[int, int]] = []
    start = None
    for x in range(first, last + 1):
        if quiet[x]:
            if start is None:
                start = x
        elif start is not None:
            if x - start >= min_gutter:
                gutters.append((int(start / scale), int(x / scale)))
            start = None
    return gutters


def split_into_bands(image) -> list:
    """Cut *image* at its gutters; return the panels, left to right.

    A band narrower than ``MIN_BAND_FRACTION`` of the page is merged into its
    neighbour (a lone column of page numbers is not a panel). If nothing
    qualifies, the whole image comes back unchanged.
    """
    width, height = image.size
    gutters = find_vertical_gutters(image)
    if not gutters:
        return [image]
    edges = [0]
    for start, end in gutters:
        edges.extend([start, end])
    edges.append(width)
    spans = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
    minimum = width * MIN_BAND_FRACTION

    merged: list[list[int]] = []
    for left, right in spans:
        if right - left <= 0:
            continue
        if merged and (right - left < minimum or merged[-1][1] - merged[-1][0] < minimum):
            merged[-1][1] = right
        else:
            merged.append([left, right])
    if len(merged) < 2:
        return [image]
    return [image.crop((left, 0, right, height)) for left, right in merged]


LIGHT_PAGE_BRIGHTNESS = 200
FILL_LEVEL = 175
FILL_CHROMA = 25  # a pastel fill is coloured; paper and pencil-grey are not
DENOISE_MIN_HEIGHT = 2500  # px; only text this large survives a median filter
AUTOCONTRAST_CUTOFF = 1.0  # percent of pixels clipped at each end of the stretch, at most
AUTOCONTRAST_INK_SHARE = 0.1  # of the page's dark pixels the black point may clip
BLACK_POINT_ON_PAPER = 160  # gray level: a stretch whose black point is this light has landed on the paper
LIMIT_CONTRAST = True  # off: the stretch always clips AUTOCONTRAST_CUTOFF, as before 1.5.6


def _whiten_coloured_fills(gray, image):
    """White out light *coloured* regions (a pastel table header bar).

    Tesseract's layout analysis reads such a bar as a picture, so the row that
    names the columns disappears. Only pixels that are both light and noticeably
    coloured are whitened: grey scans keep every stroke, which matters because
    thinning strokes turns ข into ย.
    """
    from PIL import ImageChops

    channels = image.split()
    brightest = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    dullest = ImageChops.darker(ImageChops.darker(channels[0], channels[1]), channels[2])
    coloured = ImageChops.subtract(brightest, dullest).point(lambda v: 255 if v > FILL_CHROMA else 0)
    light = gray.point(lambda v: 255 if v >= FILL_LEVEL else 0)
    return ImageChops.lighter(gray, ImageChops.multiply(coloured, light))


RULE_CELL = 12  # px: rules are found on a grid this coarse
RULE_MIN_LENGTH = 120  # px: a dark line this long is a rule, not a stroke
RULE_MAX_THICKNESS = 18  # px: anything thicker is a filled bar, not a rule
RULE_DARK_LEVEL = 140  # gray level below which a pixel is ink
RULE_FILL = 0.85  # share of a grid cell that must be ink
RULE_MARGIN = 5  # px the erased rule is widened by, to take its blurred edges


def _runs_along(strip, cells: int, axis: int):
    """255 where at least *cells* consecutive cells of *strip* are 255 along
    *axis* (0 = x, 1 = y), spread over the whole run."""
    from PIL import ImageChops

    def shifted(image, step):
        return ImageChops.offset(image, step, 0) if axis == 0 else ImageChops.offset(image, 0, step)

    both = strip
    for step in range(1, cells):
        both = ImageChops.darker(both, shifted(strip, step))
    spread = both
    for step in range(1, cells):
        spread = ImageChops.lighter(spread, shifted(both, -step))
    return spread


def _rule_mask(gray, shrink: int = 1):
    """255 on the long thin dark lines of *gray* (table borders, underlines,
    separators), 0 elsewhere; filled bars (a coloured header) are not lines.

    With *shrink* > 1 the lines are searched on an image that many times
    smaller, and the mask comes back at that size.
    """
    from PIL import Image, ImageChops, ImageFilter

    if shrink > 1:
        gray = gray.resize((max(1, gray.size[0] // shrink), max(1, gray.size[1] // shrink)), Image.BOX)
    width, height = gray.size
    cell = max(2, RULE_CELL // shrink)
    cells = max(2, RULE_MIN_LENGTH // shrink // cell)
    thickness = max(3, RULE_MAX_THICKNESS // shrink)
    margin = max(1, RULE_MARGIN // shrink)
    dark = gray.point(lambda v: 255 if v < RULE_DARK_LEVEL else 0)
    found = []
    for axis in (0, 1):
        size = (max(1, width // cell), height) if axis == 0 else (width, max(1, height // cell))
        strip = dark.resize(size, Image.BOX).point(lambda v: 255 if v >= 255 * RULE_FILL else 0)
        runs = _runs_along(strip, cells, axis)
        # a run that is also `thickness` deep the other way is a bar
        bar = _runs_along(runs, thickness, 1 - axis)
        found.append(ImageChops.subtract(runs, bar).resize((width, height), Image.NEAREST))
    return ImageChops.lighter(found[0], found[1]).filter(ImageFilter.MaxFilter(2 * max(1, margin // 2) + 1))


def _erase_rules(gray):
    """*gray* with its ruling lines painted white.

    Tesseract's layout analysis takes a ruled box for a picture and skips the
    text inside it: on a clean 300 dpi scan a six-row bordered table came back
    as a single line of noise. Without the lines the rows are ordinary text
    lines, the columns separated by spacing.
    """
    from PIL import ImageChops

    return ImageChops.lighter(gray, _rule_mask(gray))


def prepare_for_ocr(image, limit_clipping: bool = False):
    """Make a light page easier for Tesseract; dark pages are returned unchanged.

    * pale coloured fills are whitened (see :func:`_whiten_coloured_fills`);
    * large pages are median-filtered to remove scanner speckle;
    * contrast is stretched; with *limit_clipping* the black point may clip only a
      share of the page's own ink (see :func:`_dark_cutoff`), which a sparse page
      needs and a table cell does not.

    Measured on three pages of a scanned company certificate, the contrast
    stretch with the median filter cut ข-read-as-ย errors from 8 to 4 against the
    unprocessed page, while flattening every light pixel (the first version of
    the fill fix) raised them to 11. (On a clean 300 dpi scan the same median
    breaks some thin Thai strokes, but on a scanned procedure a Gaussian blur,
    speck removal and no filter at all each cost 3 to 7 of its 24 checked
    phrases, so the median stays.)
    """
    gray = image.convert("L")
    sample = _pixel_values(gray.resize((64, 64)))
    if sum(sample) / len(sample) < LIGHT_PAGE_BRIGHTNESS:
        return image
    from PIL import ImageFilter, ImageOps

    if image.mode == "RGB":
        gray = _whiten_coloured_fills(gray, image)
    if gray.size[1] >= DENOISE_MIN_HEIGHT:
        gray = gray.filter(ImageFilter.MedianFilter(3))
    dark = _dark_cutoff(gray) if limit_clipping and LIMIT_CONTRAST else AUTOCONTRAST_CUTOFF
    return ImageOps.autocontrast(gray, cutoff=(dark, AUTOCONTRAST_CUTOFF))


def _dark_cutoff(gray) -> float:
    """Percent of the darkest pixels the contrast stretch may clip.

    ``AUTOCONTRAST_CUTOFF`` (1%) is more than the ink of a very sparse page (a
    table of contents has 0.8% dark pixels): the black point lands on the paper,
    every grey stroke edge turns black and the text comes out fat and misread.
    Only then, when the 1% black point is lighter than ``BLACK_POINT_ON_PAPER``,
    is the clip limited to ``AUTOCONTRAST_INK_SHARE`` of the page's own ink; any
    page whose 1% black point is on ink is stretched exactly as before.
    """
    histogram = gray.histogram()
    total = max(1, sum(histogram))
    clipped, black_point = 0, 0
    for level, count in enumerate(histogram):
        clipped += count
        if clipped >= total * AUTOCONTRAST_CUTOFF / 100.0:
            black_point = level
            break
    if black_point < BLACK_POINT_ON_PAPER:
        return AUTOCONTRAST_CUTOFF
    ink_percent = 100.0 * sum(histogram[:128]) / total
    return min(AUTOCONTRAST_CUTOFF, AUTOCONTRAST_INK_SHARE * ink_percent)


def _normalized(text: str) -> str:
    return "".join(text.split())


def _low_confidence_lines(data: dict) -> set[str]:
    """Space-free text of every line Tesseract itself was unsure about.

    Tesseract's word data is the only source of per-line confidence, but it
    reports Thai in small pieces, so joining them for output puts spaces inside
    words. The plain-text result has Tesseract's own spacing; the word data is
    used only to say which of its lines to drop.
    """
    lines: dict[tuple, tuple[list[str], list[float]]] = {}
    for index, text in enumerate(data.get("text", [])):
        word = (text or "").strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, ValueError, TypeError):
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        words, confidences = lines.setdefault(key, ([], []))
        words.append(word)
        if confidence >= 0:
            confidences.append(confidence)
    junk: set[str] = set()
    for words, confidences in lines.values():
        text = "".join(words)
        mean = sum(confidences) / len(confidences) if confidences else 0.0
        floor = MIN_SHORT_LINE_CONFIDENCE if len(text) <= SHORT_LINE_CHARS else MIN_LINE_CONFIDENCE
        if mean < floor:
            junk.add(_normalized(text))
    return junk


def _without_junk(plain: str, junk: set[str]) -> str:
    kept: list[str] = []
    for line in plain.splitlines():
        if line.strip() and _normalized(line) in junk:
            continue
        if not line.strip() and (not kept or not kept[-1].strip()):
            continue  # collapse blank runs left behind by dropped lines
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


# A logo or emblem has no text for Tesseract to find, so it reads it as a row of
# stray marks ("AY ¢ AY ๐ ๑", "a y an a ๑ a") whose confidence is middling, well
# above the drop floor. What sets such a row apart from a real short line is not
# its confidence alone but that it has nothing a reader could use: no word, no
# number, no list marker, and nearly every token a stray letter or symbol.
LOGO_NOISE_MAX_CONFIDENCE = 75.0  # a row Tesseract is surer of is kept
LOGO_NOISE_MIN_TOKENS = 2  # a lone stray mark is the drop floor's business
LOGO_NOISE_MIN_STRAY_SHARE = 0.6  # of the tokens that are a stray letter or symbol
LOGO_NOISE_WORD_LETTERS = 3  # letters of one script that make a token a word
_LIST_MARKER = re.compile(r"^\(?[A-Za-zก-ฮ][.)]$|^\([A-Za-zก-ฮ]\)$")
# One-letter Thai words are real (ที่ นี้ ดี ปี ผู้ ก็ ณ): a consonant with an
# above/below vowel and perhaps a tone mark, or one of a few particles. A bare
# consonant, or one with only a tone mark, mai han-akat or thanthakhat, is not.
_PLAUSIBLE_THAI_WORD = re.compile(
    "^[ก-ฮ][ิ-ู][่-๋]?$|^[ก-ฮ]็$|^[ณๆฯ]$"
)
# Lowercase two-letter Latin tokens that are real words or abbreviations; any other
# ("ae", "te", "wl") is taken for a stray mark.
_SHORT_LATIN_WORDS = frozenset(
    "of to in is it at on or an as by be we he me my no so do if up us am go oh ok "
    "vs pm tv pc id ex ie eg re hr qa qc gm".split()
)


def _base_letters(token: str) -> list[str]:
    """The letters of *token*; Thai vowel and tone marks, digits and symbols are not."""
    return [char for char in token if unicodedata.category(char)[0] == "L"]


def _is_number_token(token: str) -> bool:
    """A digit anywhere, or two Thai digits in a row (a lone ๐ ๑ is a stray mark)."""
    run = 0
    for char in token:
        if char.isascii() and char.isdigit():
            return True
        run = run + 1 if 0x0E50 <= ord(char) <= 0x0E59 else 0
        if run >= 2:
            return True
    return False


def _is_word_token(token: str) -> bool:
    letters = _base_letters(token)
    if len(letters) < LOGO_NOISE_WORD_LETTERS:
        return False
    return len({0x0E01 <= ord(char) <= 0x0E5B for char in letters}) == 1


def _is_stray_token(token: str) -> bool:
    """A token that is a stray mark rather than a word: no letter or digit, a lone letter
    that is not a Thai word, or two lowercase Latin letters that are not a
    short word."""
    if _is_number_token(token):
        return False
    letters = _base_letters(token)
    if len(letters) <= 1:
        return not _PLAUSIBLE_THAI_WORD.match(token)
    return (
        len(letters) == 2
        and all(char.isascii() for char in letters)
        and token.islower()
        and token not in _SHORT_LATIN_WORDS
    )


def _is_logo_noise(line: str, confidence: float | None) -> bool:
    """Whether *line* (read at mean *confidence*) is a row of stray marks.

    All of: a confidence below ``LOGO_NOISE_MAX_CONFIDENCE``; at least
    ``LOGO_NOISE_MIN_TOKENS`` tokens; no word, no number and no list marker
    (``ก.``, ``a)``, ``(ข)``) among them; and at least ``LOGO_NOISE_MIN_STRAY_SHARE``
    of the tokens stray (:func:`_is_stray_token`). Anything less certain is kept
    (and, below ``REVIEW_LINE_CONFIDENCE``, flagged for review as usual). A digit
    always protects a row: "- 2 -" is a page number, not a logo.
    """
    if confidence is None or confidence >= LOGO_NOISE_MAX_CONFIDENCE:
        return False
    tokens = line.split()
    if len(tokens) < LOGO_NOISE_MIN_TOKENS:
        return False
    if any(_is_word_token(t) or _is_number_token(t) or _LIST_MARKER.match(t) for t in tokens):
        return False
    return sum(1 for t in tokens if _is_stray_token(t)) / len(tokens) >= LOGO_NOISE_MIN_STRAY_SHARE


def _logo_noise_keys(text: str, means: dict[str, float]) -> set[str]:
    """Space-free keys of the lines of *text* that are :func:`_is_logo_noise`."""
    keys: set[str] = set()
    for line in text.splitlines():
        key = _normalized(line)
        if key and _is_logo_noise(line, means.get(key)):
            keys.add(key)
    return keys


def _line_mean_confidences(data: dict) -> dict[str, float]:
    """Mean Tesseract confidence for every line, including ones that pass
    the drop floor - keyed the same way :func:`_low_confidence_lines` keys
    its junk set (space-free line text), so a caller can look a surviving
    line back up by the same normalization.
    """
    lines: dict[tuple, tuple[list[str], list[float]]] = {}
    for index, text in enumerate(data.get("text", [])):
        word = (text or "").strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, ValueError, TypeError):
            continue
        key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        words, confidences = lines.setdefault(key, ([], []))
        words.append(word)
        if confidence >= 0:
            confidences.append(confidence)
    means: dict[str, float] = {}
    for words, confidences in lines.values():
        text = "".join(words)
        means[_normalized(text)] = sum(confidences) / len(confidences) if confidences else 0.0
    return means


def _mark_uncertain(text: str, means: dict[str, float]) -> str:
    """Append a review marker to a line that survived the drop floor but is
    still shaky, so the lines worth checking against the original scan can be
    told apart from the rest.

    The marker is invisible private-use text (:func:`review.encode`), not a
    visible ``⚠58%``: :class:`~doc2md.core.converter.Converter` lifts it out
    into ``ConversionResult.review_lines`` so the Markdown handed to an AI
    stays clean. The visible flag is opt-in (:func:`review.with_inline_flags`).
    """
    marked: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            confidence = means.get(_normalized(line))
            if confidence is not None and confidence < REVIEW_LINE_CONFIDENCE:
                line = review.encode(line, confidence)
        marked.append(line)
    return "\n".join(marked)


def count_uncertain_lines(text: str) -> int:
    """How many lines in *text* carry the :func:`_mark_uncertain` flag."""
    return review.count_marked(text)


# --------------------------------------------------------------------------
# Thai spelling that Tesseract gets "visually right" but string-wrong
# --------------------------------------------------------------------------

_NIKHAHIT = chr(0x0E4D)
_SARA_AA = chr(0x0E32)
_SARA_AM = chr(0x0E33)
_TONE_MARKS = "".join(chr(code) for code in range(0x0E48, 0x0E4C))
_SARA_AM_AS_PARTS = re.compile(f"([{_TONE_MARKS}]?){_NIKHAHIT}([{_TONE_MARKS}]?){_SARA_AA}")
# Every combining mark (above/below vowels, tone marks, nikhahit, ...); sara aa
# and sara am are letters, not marks.
_COMBINING = "".join(chr(code) for code in (0x0E31, *range(0x0E34, 0x0E3B), *range(0x0E47, 0x0E4F)))
_DOUBLED_TONE_AA = re.compile(f"([{_TONE_MARKS}])\\1{_SARA_AA}")
_DOUBLED_MARK = re.compile(f"([{_COMBINING}])\\1+")


def normalize_thai(text: str) -> str:
    """Repair Thai spellings Tesseract gets visually right but string-wrong.

    * Sara am: Tesseract writes ``จำ`` as nikhahit + sara aa (U+0E4D U+0E32),
      which looks the same but is a different string, so searching for
      ``จำกัด`` - or an AI reading it - misses it. The tone mark belongs
      *before* sara am (``น้ำ``), wherever Tesseract put it. A nikhahit not
      followed by sara aa is left alone.
    * The nikhahit ring is sometimes read as a second tone mark, giving tone +
      the same tone + sara aa (``ซ้้า``): that is tone + sara am (``ซ้ำ``).
    * The same combining mark twice in a row is never valid Thai: one is kept.
    """
    if not any(char in _COMBINING for char in text):
        return text
    text = _DOUBLED_TONE_AA.sub(lambda m: f"{m.group(1)}{_SARA_AM}", text)
    text = _DOUBLED_MARK.sub(lambda m: m.group(1), text)
    return _SARA_AM_AS_PARTS.sub(lambda m: f"{m.group(1)}{m.group(2)}{_SARA_AM}", text)


# --------------------------------------------------------------------------
# Upper vowels and tone marks that layout analysis cut off their line
# --------------------------------------------------------------------------
#
# On bold or large Thai lines, Tesseract's page layout analysis can take the
# marks above the line (ิ ื ั ่ ้ ์ ...) for a text line of their own: a junk
# row of low confidence, with the real row directly beneath it, correct except
# that every mark is missing ("เรอง" for "เรื่อง"). Reading the two rows
# together as a single line (--psm 7) recovers the marks - but on a scribble
# that same call returns garbage, so a re-read is only trusted when it keeps
# the base row's letters and does nothing except add marks.

_THAI_MARKS = frozenset(
    chr(code) for code in (0x0E31, *range(0x0E34, 0x0E3B), *range(0x0E47, 0x0E4F))
)
MARK_ROW_MIN_OVERLAP = 0.3  # of the mark row's width, shared with its base row
MARK_ROW_TOP_SLACK = 5  # px the base row's top may sit above the mark row's
MARK_ROW_BELOW_MIN = 20  # px (or half the mark row's height) the base may start below
MARK_ROW_INSIDE = 0.8  # share of a mark row that must lie within a base row starting above it
MARK_ROW_SLIVER = 0.4  # a confident row this much shorter than its base row is still a candidate
MARK_ROW_PAD = 10 # px around the union of the two rows when re-reading
MARK_REREAD_MIN_SIMILARITY = 0.8
MAX_MARK_REREADS = 40  # per band: each is one more Tesseract call


@dataclass
class _LineBox:
    text: str  # words joined without spaces, as in the other per-line helpers
    confidence: float
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def _line_boxes(data: dict) -> list[_LineBox]:
    """One box per Tesseract text line: joined words, mean confidence, union box."""
    if not all(name in data for name in ("left", "top", "width", "height")):
        return []
    lines: dict[tuple, list] = {}
    for index, text in enumerate(data.get("text", [])):
        word = (text or "").strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][index])
            left, top = int(data["left"][index]), int(data["top"][index])
            right, bottom = left + int(data["width"][index]), top + int(data["height"][index])
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        entry = lines.setdefault(key, [[], [], left, top, right, bottom])
        entry[0].append(word)
        if confidence >= 0:
            entry[1].append(confidence)
        entry[2], entry[3] = min(entry[2], left), min(entry[3], top)
        entry[4], entry[5] = max(entry[4], right), max(entry[5], bottom)
    return [
        _LineBox("".join(words), sum(confs) / len(confs) if confs else 0.0, *box)
        for words, confs, *box in lines.values()
    ]


def _base_row(candidate: _LineBox, boxes: list[_LineBox]) -> _LineBox | None:
    """The row a mark-only row sits on: at least as confident, overlapping it
    horizontally, starting at about the same height; the closest top wins."""
    if candidate.width <= 0:
        return None
    best: _LineBox | None = None
    for other in boxes:
        if other is candidate or other.confidence < candidate.confidence:
            continue
        shared = min(candidate.right, other.right) - max(candidate.left, other.left)
        if shared < MARK_ROW_MIN_OVERLAP * candidate.width:
            continue
        lowest = candidate.bottom + max(MARK_ROW_BELOW_MIN, 0.5 * candidate.height)
        if other.top > lowest:
            continue
        if other.top < candidate.top - MARK_ROW_TOP_SLACK:
            # A base row that starts a little higher still counts when the mark
            # row lies inside its height (a thin sliver across a taller row).
            inside = min(candidate.bottom, other.bottom) - candidate.top
            if inside < MARK_ROW_INSIDE * candidate.height:
                continue
        if best is None or abs(other.top - candidate.top) < abs(best.top - candidate.top):
            best = other
    return best


def _skeleton(text: str) -> str:
    """*text* without Thai combining marks, whitespace and table bars."""
    return "".join(
        char for char in text if char not in _THAI_MARKS and not char.isspace() and char != "|"
    )


def _mark_count(text: str) -> int:
    return sum(1 for char in text if char in _THAI_MARKS)


def _letters(text: str) -> tuple[list[list[str]], str]:
    """Split *text* into clusters: a non-mark character plus the combining
    marks after it. Whitespace and ``|`` are not clusters but the "gap" before
    the next one. Returns ``([[base char, cluster, gap before], ...], trailing gap)``.
    """
    clusters: list[list[str]] = []
    gap = ""
    for char in text:
        if char.isspace() or char == "|":
            gap += char
        elif char in _THAI_MARKS and clusters and not gap:
            clusters[-1][1] += char
        else:
            clusters.append([char, char, gap])
            gap = ""
    return clusters, gap


def _worth_inserting(run: list[list[str]]) -> bool:
    """Letters only the re-read has: kept when they are Thai (a word the first
    read dropped) or no letters at all (digits, punctuation), not when they are
    Latin noise."""
    chars = [cluster[0] for cluster in run]
    thai = sum(1 for char in chars if 0x0E01 <= ord(char) <= 0x0E5B)
    return thai * 2 > len(chars) or not any(char.isalpha() for char in chars)


def _pick_cluster(base: str, reread: str) -> str:
    """The cluster for a letter both reads agree on.

    The re-read exists to add marks the base read missed, so it wins when the
    base has none, or when the base's marks are all there in the re-read too (it
    only adds). When the two disagree about a mark the base read stands (a
    re-read turned ิ into ี on a correct word). One exception: a base nikhahit
    is the ring of a sara am, which the re-read often saw as a tone mark; the
    re-read's tone mark is added in front of the ring. And the other way round:
    when the base has only a tone mark where the re-read has the ring, the base
    mistook the ring for a tone mark.
    """
    base_marks, reread_marks = base[1:], reread[1:]
    if not base_marks:
        return reread
    remaining = iter(reread_marks)
    if all(mark in remaining for mark in base_marks):  # a subsequence
        return reread
    if (
        _NIKHAHIT in base_marks
        and _NIKHAHIT not in reread_marks
        and any(mark in _TONE_MARKS for mark in reread_marks)
    ):
        return base[0] + reread_marks + _NIKHAHIT
    if _NIKHAHIT in reread_marks and all(mark in _TONE_MARKS for mark in base_marks):
        return reread  # the base read the ring as a tone mark (จ้า for จำ)
    return base


# Consonants that differ only in a small stroke or loop, which Tesseract swaps
# between two reads of the same word (ซ/ช, ข/ฃ, ...). When aligning a re-read with
# the base read they count as the same letter, so the marks over the word are
# still merged; the base read's letter is the one that stays.
_LOOKALIKE_PAIRS = ("ซช", "ขฃ", "ดต", "บป", "พฟ", "ถภ")
_LOOKALIKE = {char: pair[0] for pair in _LOOKALIKE_PAIRS for char in pair}


def _shape(char: str) -> str:
    """*char*, or the first letter of its look-alike pair."""
    return _LOOKALIKE.get(char, char)


def _merge_marks(base: str, reread: str) -> str:
    """*base* with marks from *reread*, where the two agree on the letters.

    A single-line re-read recovers marks, but it also sometimes turns a Thai
    word into Latin or swaps a consonant. So the letters always come from the
    base read, and only the marks of a letter the re-read also has are taken.
    Where the reads disagree on exactly as many letters as they differ by and
    every one of those is a look-alike pair (see ``_LOOKALIKE_PAIRS``), the
    letters still count as the same: the marks are taken, the base letter kept.
    A run of letters only the re-read has is added if it is Thai or has no
    letters (see :func:`_worth_inserting`).
    """
    base_clusters, base_tail = _letters(base)
    reread_clusters, _tail = _letters(reread)
    matcher = difflib.SequenceMatcher(
        None,
        [cluster[0] for cluster in base_clusters],
        [cluster[0] for cluster in reread_clusters],
        autojunk=False,
    )
    pieces: list[tuple[str, str]] = []  # (gap before, cluster)

    def take_marks(b1: int, b2: int, r1: int) -> None:
        for offset in range(b2 - b1):
            mine, theirs = base_clusters[b1 + offset], reread_clusters[r1 + offset]
            gap = mine[2] if offset == 0 else theirs[2]
            if "|" in mine[2] and "|" not in gap:
                gap = mine[2]  # a table bar the re-read (one line) lost
            # the base letter always stays, even where the re-read swapped it
            pieces.append((gap, _pick_cluster(mine[1], mine[0] + theirs[1][1:])))

    for tag, b1, b2, r1, r2 in matcher.get_opcodes():
        if tag == "equal":
            take_marks(b1, b2, r1)
        elif tag == "replace" and b2 - b1 == r2 - r1 and all(
            _shape(base_clusters[b1 + offset][0]) == _shape(reread_clusters[r1 + offset][0])
            for offset in range(b2 - b1)
        ):
            take_marks(b1, b2, r1)  # the same letters, but for look-alikes
        elif tag in ("replace", "delete"):
            pieces.extend((cluster[2], cluster[1]) for cluster in base_clusters[b1:b2])
        elif tag == "insert" and _worth_inserting(reread_clusters[r1:r2]):
            pieces.extend((cluster[2], cluster[1]) for cluster in reread_clusters[r1:r2])
    if base_clusters and pieces:
        pieces[0] = (base_clusters[0][2], pieces[0][1])
    return ("".join(gap + cluster for gap, cluster in pieces) + base_tail).rstrip()


def _merged_marks(reread: str, base_line: str) -> str | None:
    """*base_line* with the marks of *reread*, or ``None`` if the re-read is not
    to be trusted: empty, a different text, or no gain in marks."""
    if not reread:
        return None
    skeleton = _skeleton(reread)
    if not skeleton:
        return None
    if difflib.SequenceMatcher(None, skeleton, _skeleton(base_line)).ratio() < MARK_REREAD_MIN_SIMILARITY:
        return None
    merged = _merge_marks(base_line, reread)
    return merged if _mark_count(merged) > _mark_count(base_line) else None


def _find_line(text: str, key: str) -> str | None:
    """The first line of *text* whose space-free form is *key*."""
    for line in text.split("\n"):
        if line.strip() and _normalized(line) == key:
            return line
    return None


def _rejoin_marks(
    band, data: dict, language: str, tesseract, plain: str
) -> list[tuple[str, str, float, str]]:
    """Find mark-only rows and re-read each with its base row.

    *plain* is the band's plain-text read: the base row's line is found in it
    (that line has Tesseract's own spacing) and the re-read's marks are merged
    into it. Returns ``(base key, merged line, base confidence, mark row key)``
    for every accepted re-read. Keys are space-free line text
    (:func:`_normalized`).
    """
    boxes = _line_boxes(data)
    replacements: list[tuple[str, str, float, str]] = []
    taken: set[int] = set()
    attempts = 0
    for candidate in sorted(boxes, key=lambda box: box.top):
        if id(candidate) in taken:
            continue
        base = _base_row(candidate, boxes)
        if base is None or id(base) in taken:
            continue
        # Normally a shaky row; but the marks of a short word can be read
        # confidently (a lone "ม" over "จัดซือ"), so a very thin row on a much
        # taller one is tried too.
        if candidate.confidence >= REVIEW_LINE_CONFIDENCE and (
            candidate.height > MARK_ROW_SLIVER * base.height
        ):
            continue
        base_key = _normalized(base.text)
        base_line = _find_line(plain, base_key)
        if base_line is None:
            continue
        attempts += 1
        if attempts > MAX_MARK_REREADS:
            break
        width, height = band.size
        crop = band.crop((
            max(0, min(candidate.left, base.left) - MARK_ROW_PAD),
            max(0, min(candidate.top, base.top) - MARK_ROW_PAD),
            min(width, max(candidate.right, base.right) + MARK_ROW_PAD),
            min(height, max(candidate.bottom, base.bottom) + MARK_ROW_PAD),
        ))
        reread = " ".join(
            tesseract.image_to_string(crop, lang=language, config="--psm 7").split()
        )
        merged = _merged_marks(reread, base_line)
        if merged is None:
            continue
        taken.update((id(candidate), id(base)))
        replacements.append((base_key, merged, base.confidence, _normalized(candidate.text)))
    return replacements


def _replace_line(text: str, key: str, replacement: str) -> tuple[str, bool]:
    """Swap the first line of *text* whose space-free form is *key*."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.strip() and _normalized(line) == key:
            lines[index] = replacement
            return "\n".join(lines), True
    return text, False


# --------------------------------------------------------------------------
# Latin abbreviations read as Thai
# --------------------------------------------------------------------------
#
# With Thai and English loaded together, a short uppercase abbreviation beside
# an English word ("QM Manager") is sometimes read as two Thai letters ("อห
# Manager") at middling confidence, because the Thai model gets the first say.
# The same pixels read with English alone come back as the abbreviation. So a
# short, shaky run of Thai letters right next to a Latin word is read again with
# eng only, and swapped only if that read is a confident run of capitals; the
# many ways Thai letters misread as English (lowercase, symbols, low confidence)
# all fail that test.

LATIN_REREAD_MAX_CONFIDENCE = 80.0  # a Thai run any surer than this is left alone
LATIN_REREAD_MIN_CONFIDENCE = 85.0  # the eng-only read must be at least this sure
LATIN_REREAD_MAX_PIECES = 4  # Tesseract reports Thai in pieces (letters, marks)
LATIN_REREAD_MAX_GAP = 0.8  # of the run's height, between the run and the Latin word
LATIN_REREAD_PAD = 8  # px around the run when re-reading
MAX_LATIN_REREADS = 20  # per band: each is one more Tesseract call
_LATIN_ABBREVIATION = re.compile(r"[A-Z]{2,5}")


def _is_thai_piece(text: str) -> bool:
    return bool(text) and all(0x0E01 <= ord(char) <= 0x0E5B for char in text)


def _is_latin_word(text: str) -> bool:
    return len(text) >= 3 and text.isascii() and text.isalpha()


def _reread_latin_runs(
    band, data: dict, tesseract
) -> list[tuple[str, str, str, bool]]:
    """Short shaky runs of Thai that are really a Latin abbreviation.

    Returns ``(run text, neighbour word, abbreviation, neighbour_follows)`` for
    every run whose eng-only re-read is accepted (see the section comment).
    """
    if not all(name in data for name in ("left", "top", "width", "height", "conf", "text")):
        return []
    lines: dict[tuple, list[tuple[int, int, int, int, float, str]]] = {}
    for index, text in enumerate(data["text"]):
        word = (text or "").strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][index])
            left, top = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        lines.setdefault(key, []).append((left, top, left + width, top + height, confidence, word))

    found: list[tuple[str, str, str, bool]] = []
    attempts = 0
    for pieces in lines.values():
        pieces.sort(key=lambda piece: piece[0])
        start = 0
        while start < len(pieces):
            if not _is_thai_piece(pieces[start][5]):
                start += 1
                continue
            stop = start + 1
            while (
                stop < len(pieces)
                and _is_thai_piece(pieces[stop][5])
                and pieces[stop][0] - pieces[stop - 1][2]
                <= LATIN_REREAD_MAX_GAP * (pieces[stop][3] - pieces[stop][1])
            ):  # one run is one word: Thai pieces a word-gap apart are not
                stop += 1
            run = pieces[start:stop]
            before = pieces[start - 1] if start > 0 else None
            after = pieces[stop] if stop < len(pieces) else None
            start = stop
            confidences = [piece[4] for piece in run if piece[4] >= 0]
            if (
                len(run) > LATIN_REREAD_MAX_PIECES
                or not confidences
                or sum(confidences) / len(confidences) >= LATIN_REREAD_MAX_CONFIDENCE
            ):
                continue
            left = min(piece[0] for piece in run)
            top = min(piece[1] for piece in run)
            right = max(piece[2] for piece in run)
            bottom = max(piece[3] for piece in run)
            reach = LATIN_REREAD_MAX_GAP * (bottom - top)
            if after is not None and _is_latin_word(after[5]) and after[0] - right <= reach:
                neighbour, follows = after[5], True
            elif before is not None and _is_latin_word(before[5]) and left - before[2] <= reach:
                neighbour, follows = before[5], False
            else:
                continue
            attempts += 1
            if attempts > MAX_LATIN_REREADS:
                return found
            width, height = band.size
            crop = band.crop((
                max(0, left - LATIN_REREAD_PAD), max(0, top - LATIN_REREAD_PAD),
                min(width, right + LATIN_REREAD_PAD), min(height, bottom + LATIN_REREAD_PAD),
            ))
            reread = tesseract.image_to_data(
                crop, lang="eng", config="--psm 8", output_type=tesseract.Output.DICT
            )
            words = [
                (str(text).strip(), float(conf))
                for text, conf in zip(reread.get("text", []), reread.get("conf", []))
                if str(text).strip()
            ]
            if len(words) != 1:
                continue
            latin, confidence = words[0]
            if confidence >= LATIN_REREAD_MIN_CONFIDENCE and _LATIN_ABBREVIATION.fullmatch(latin):
                found.append(("".join(piece[5] for piece in run), neighbour, latin, follows))
    return found


def _swap_run(line: str, run: str, neighbour: str, latin: str, follows: bool) -> str | None:
    """*line* with the Thai *run* next to *neighbour* replaced by *latin*, or
    ``None`` when the line does not have that run there. Whitespace inside the
    run is ignored when matching; the abbreviation is set off from what it sits
    against by a space."""
    spaced = r"\s*".join(re.escape(char) for char in run)
    if follows:
        match = re.search(f"({spaced})(?=\\s*{re.escape(neighbour)})", line)
    else:
        match = re.search(f"(?<={re.escape(neighbour)})(\\s*)({spaced})", line)
    if match is None:
        return None
    if follows:
        start, end = match.span(1)
    else:
        start, end = match.span(2)
    lead = " " if start > 0 and not line[start - 1].isspace() else ""
    return line[:start] + lead + latin + line[end:]


def _apply_latin_runs(
    text: str, runs: list[tuple[str, str, str, bool]], junk: set[str], means: dict[str, float]
) -> str:
    """*text* with every accepted run swapped on the first line that has it;
    a line that is about to be dropped as junk is left alone. The new line
    inherits the old line's confidence."""
    lines = text.split("\n")
    for run, neighbour, latin, follows in runs:
        for index, line in enumerate(lines):
            key = _normalized(line)
            if not key or key in junk:
                continue
            swapped = _swap_run(line, run, neighbour, latin, follows)
            if swapped is None:
                continue
            if key in means:
                means[_normalized(swapped)] = means[key]
            lines[index] = swapped
            break
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Thai words read as Latin
# --------------------------------------------------------------------------
#
# The other way round from the abbreviations above: next to a number, the unit
# word วัน comes back as "Tu" or "Iu" ("119 Iu", "13 Tu"). The Latin read is
# shaky, and the same pixels read with Thai alone are the word. So a short,
# lower-case-looking Latin token right after a number (or right before one, after
# Thai) is read again with tha only, and swapped only if that read is a confident
# Thai word of at least two letters. Real units and abbreviations ("km", "PM 2.5",
# "LED", "QM") are either capitals or come back from the Thai model as
# nothing it is sure of.

THAI_REREAD = True  # off: a Latin-looking Thai word is not read again
THAI_REREAD_MAX_CONFIDENCE = 90.0  # a Latin token any surer than this is left alone
THAI_REREAD_MIN_CONFIDENCE = 80.0  # the Thai-only read (mean over its pieces) must be at least this sure
THAI_REREAD_MIN_LETTERS = 2  # of the Thai result: a lone letter is not a word
THAI_REREAD_MAX_LATIN = 3  # letters of the Latin token
THAI_REREAD_MAX_GAP = 1.3  # of the token's height, between it and the number
THAI_REREAD_PAD = 8  # px around the token when re-reading
MAX_THAI_REREADS = 30  # per band: each is one more Tesseract call


def _is_digit_token(text: str) -> bool:
    return bool(text) and any(char.isdigit() for char in text) and all(
        char.isdigit() or char in ".,/:-" for char in text
    )


def _reread_thai_words(band, data: dict, tesseract) -> list[tuple[str, str, str, bool]]:
    """Short Latin tokens that are really a Thai word, as ``(token, neighbour,
    Thai word, neighbour_follows)`` (see the section comment)."""
    if not all(name in data for name in ("left", "top", "width", "height", "conf", "text")):
        return []
    lines: dict[tuple, list[tuple[int, int, int, int, float, str]]] = {}
    for index, text in enumerate(data["text"]):
        word = (text or "").strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][index])
            left, top = int(data["left"][index]), int(data["top"][index])
            width, height = int(data["width"][index]), int(data["height"][index])
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        lines.setdefault(key, []).append((left, top, left + width, top + height, confidence, word))

    found: list[tuple[str, str, str, bool]] = []
    attempts = 0
    for pieces in lines.values():
        pieces.sort(key=lambda piece: piece[0])
        for at, (left, top, right, bottom, confidence, word) in enumerate(pieces):
            if not (word.isascii() and word.isalpha() and 2 <= len(word) <= THAI_REREAD_MAX_LATIN):
                continue
            if word.isupper() or confidence >= THAI_REREAD_MAX_CONFIDENCE:
                continue
            reach = THAI_REREAD_MAX_GAP * (bottom - top)
            before = pieces[at - 1] if at > 0 else None
            after = pieces[at + 1] if at + 1 < len(pieces) else None
            if before is not None and _is_digit_token(before[5]) and left - before[2] <= reach:
                neighbour, follows = before[5], False
            elif (
                before is not None and _is_thai_piece(before[5]) and left - before[2] <= reach
                and after is not None and _is_digit_token(after[5]) and after[0] - right <= reach
            ):
                neighbour, follows = after[5], True
            else:
                continue
            attempts += 1
            if attempts > MAX_THAI_REREADS:
                return found
            width, height = band.size
            crop = band.crop((
                max(0, left - THAI_REREAD_PAD), max(0, top - THAI_REREAD_PAD),
                min(width, right + THAI_REREAD_PAD), min(height, bottom + THAI_REREAD_PAD),
            ))
            reread = tesseract.image_to_data(
                crop, lang="tha", config="--psm 8", output_type=tesseract.Output.DICT
            )
            # Tesseract reports Thai in pieces (letters, marks): one word, many pieces
            pieces_read = [
                (str(text).strip(), float(conf))
                for text, conf in zip(reread.get("text", []), reread.get("conf", []))
                if str(text).strip()
            ]
            if not pieces_read:
                continue
            thai = "".join(piece[0] for piece in pieces_read)
            thai_confidence = sum(piece[1] for piece in pieces_read) / len(pieces_read)
            if (
                thai_confidence >= THAI_REREAD_MIN_CONFIDENCE
                and _is_thai_piece(thai)
                and len(_base_letters(thai)) >= THAI_REREAD_MIN_LETTERS
            ):
                found.append((word, neighbour, thai, follows))
    return found


# --------------------------------------------------------------------------
# Text that Tesseract skipped
# --------------------------------------------------------------------------
#
# Tesseract's layout analysis sometimes drops text it has plainly seen: it takes
# a bordered table, or a column of one, for a picture (on a clean 300 dpi scan a
# six-row table came back as one line of noise, and in another table every value
# of the right-hand column went missing), or it splits a line in two and leaves
# the middle of it unread ("ครบ" ... "8 วัน" with the years between them gone).
# Erasing the rules on every page is no cure - a ruled table Tesseract *does*
# read comes out as "a | b | c" rows, and with its rules gone the columns fell
# apart into separate blocks. So the page's own read is checked instead: runs of
# ink the size of a line of text, rules left out, that no word covers. Each run
# is read again on its own, rules erased, and its text kept only if the re-read
# is sure and has a word or a number in it (a logo or a signature never does); it
# is then put on the line it sits beside, or on a line of its own.

RESCUE_UNREAD = True  # off: no run of unread text is read again
RESCUE_SHRINK = 3  # rules are searched for on a page this many times smaller
RESCUE_CELL = 8  # px per cell when measuring how much of the ink was read
RESCUE_TEXT_DENSITY = (0.03, 0.6)  # ink share of a cell that looks like text, not blank or solid
RESCUE_WORD_CONFIDENCE = 60.0  # a word less sure than this does not count as reading its cell
RESCUE_SHORT_CONFIDENCE = 80.0  # ... nor does a Latin token of one or two characters unless this sure
RESCUE_LINE_CONFIDENCE = 60.0  # a run inside the box of a line this sure is part of that line
RESCUE_JOIN = (3, 1)  # cells (across, down) by which unread cells still belong to one run
RESCUE_MIN_RUN = 12  # cells: fewer is a speck or a stroke, not a word
RESCUE_MIN_HEIGHT = 3  # cells: a thinner run is a rule's remains, not a line of text
RESCUE_MIN_ASPECT = 2.0  # width over height: a word or two of text is wide, a logo or a stamp is squarer
RESCUE_MAX_RUN_HEIGHT = 14  # cells: a taller run is a picture, not a line or two of text
RESCUE_ROW_CONFIDENCE = 75.0  # a re-read row less sure than this is dropped
RESCUE_THAI_FIGURE_LETTERS = 5  # Thai letters a token needs to carry digits ('ธั่อว3' is a scrap, 'ครบ3ปี' is text)
RESCUE_LATIN_WORD_LETTERS = 4  # a Latin word shorter than this is as likely a logo's scrap (IVI) as a word (ABS)
RESCUE_PAD = 6  # px around a run when re-reading it
RESCUE_INK = (0.09, 0.62)  # share of ink in a run's box: more is a bar or a photograph, less a smudge; text has about a third
RESCUE_REPLACE_SHARE = 0.6  # of a shaky line's width that a run must cover for the re-read to replace the line
RESCUE_COLUMN_GAP = 1.5  # of the row height: a wider gap is a column break
MAX_RUN_RESCUES = 16  # per band: each is one more Tesseract call
RESCUE_MAX_MISSES = 6  # re-reads in a row that gave nothing, after which a band is given up on


def _reads_its_cell(text: str, confidence: float) -> bool:
    """Whether a word of *data* counts as having read the ink under it.

    Tesseract covers a stretch it cannot read with scraps - ``W``, ``av``, ``PR`` at
    41 to 78 - so a Latin token of one or two characters has to be sure to count;
    anything else has to reach ``RESCUE_WORD_CONFIDENCE``.
    """
    if text.isascii() and not any(char.isdigit() for char in text) and len(text) <= 2:
        return confidence >= RESCUE_SHORT_CONFIDENCE
    return confidence >= RESCUE_WORD_CONFIDENCE


def _unread_runs(gray, data: dict) -> list[tuple[int, int, int, int]]:
    """Runs of text-like ink in *gray* that no word of *data* covers, as boxes
    ``(left, top, right, bottom)``, text-sized and no more than a couple of lines high.

    The ink counted is that of cells (``RESCUE_CELL`` px square) whose density is
    the density of text, rules left out; a cell is read if a word of at least
    ``RESCUE_WORD_CONFIDENCE`` overlaps it. Unread cells that lie close together
    (``RESCUE_JOIN``) make one run.
    """
    from PIL import Image, ImageChops

    dark = gray.point(lambda v: 255 if v < RULE_DARK_LEVEL else 0)
    rules = _rule_mask(gray, RESCUE_SHRINK).resize(gray.size, Image.NEAREST)
    dark = ImageChops.subtract(dark, rules)
    cols, rows = max(1, gray.size[0] // RESCUE_CELL), max(1, gray.size[1] // RESCUE_CELL)
    density = _pixel_values(dark.resize((cols, rows), Image.BOX))
    low, high = (255 * share for share in RESCUE_TEXT_DENSITY)
    unread = {index for index, value in enumerate(density) if low <= value <= high}
    for index, word in enumerate(data.get("text", [])):
        if not unread:
            return []
        if not (word or "").strip():
            continue
        try:
            if not _reads_its_cell(word.strip(), float(data["conf"][index])):
                continue
            x0, y0 = int(data["left"][index]), int(data["top"][index])
            x1, y1 = x0 + int(data["width"][index]), y0 + int(data["height"][index])
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        for cy in range(max(0, y0 // RESCUE_CELL), min(rows, y1 // RESCUE_CELL + 1)):
            for cx in range(max(0, x0 // RESCUE_CELL), min(cols, x1 // RESCUE_CELL + 1)):
                unread.discard(cy * cols + cx)
    runs: list[tuple[int, int, int, int]] = []
    seen: set[int] = set()
    join_x, join_y = RESCUE_JOIN
    for start in sorted(unread):
        if start in seen:
            continue
        stack, members = [start], 0
        seen.add(start)
        x0 = x1 = start % cols
        y0 = y1 = start // cols
        while stack:
            at = stack.pop()
            members += 1
            x, y = at % cols, at // cols
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for ny in range(max(0, y - join_y), min(rows, y + join_y + 1)):
                for nx in range(max(0, x - join_x), min(cols, x + join_x + 1)):
                    neighbour = ny * cols + nx
                    if neighbour in unread and neighbour not in seen:
                        seen.add(neighbour)
                        stack.append(neighbour)
        rows_high, columns_wide = y1 - y0 + 1, x1 - x0 + 1
        if (
            members >= RESCUE_MIN_RUN
            and RESCUE_MIN_HEIGHT <= rows_high <= RESCUE_MAX_RUN_HEIGHT
            and columns_wide >= RESCUE_MIN_ASPECT * rows_high
        ):
            runs.append((x0 * RESCUE_CELL, y0 * RESCUE_CELL, (x1 + 1) * RESCUE_CELL, (y1 + 1) * RESCUE_CELL))
    return runs


def _join_row(pieces: list[tuple[str, int, int, int]]) -> str:
    """One row's words ``(text, left, width, height)``, joined as posters are
    (:func:`_join_pieces`), a wide gap (a column break) as three spaces."""
    pieces = sorted(pieces, key=lambda piece: piece[1])
    groups: list[list[tuple[str, int, int, int]]] = [[pieces[0]]]
    for previous, piece in zip(pieces, pieces[1:]):
        if piece[1] - (previous[1] + previous[2]) > RESCUE_COLUMN_GAP * max(previous[3], piece[3]):
            groups.append([])
        groups[-1].append(piece)
    return "   ".join(_join_pieces(group) for group in groups)


_ASCII_NUMBER = re.compile(r"^[0-9][0-9.,/:-]*$")
_NUMBER_THEN_THAI = re.compile(r"^([0-9][0-9.,/:-]*)([ก-๛]+)$")
_EDGE_PUNCTUATION = ".,:;()\"'"
_LEADING_VOWELS = frozenset(chr(code) for code in range(0x0E40, 0x0E45))


def _is_plausible_thai_word(token: str) -> bool:
    """Whether *token*, all Thai, could be spelt: it does not start with a
    combining mark, does not end with a mark that needs a letter after it (mai
    han-akat) or with a vowel that is written before its letter."""
    if token[0] in _THAI_MARKS or token[-1] in _LEADING_VOWELS or token[-1] == chr(0x0E31):
        return False
    return True


def _has_thai(token: str) -> bool:
    return any(0x0E01 <= ord(char) <= 0x0E5B for char in token)


_STRAY_SYMBOLS = frozenset("[]{}|=<>~^*_")


def _is_plausible_thai_token(token: str) -> bool:
    """A token with Thai letters in it that can be a Thai word: no stray symbol
    inside it, and spelt in a way Thai can be (see :func:`_is_plausible_thai_word`)."""
    core = token.strip(_EDGE_PUNCTUATION)
    if not core or any(char in _STRAY_SYMBOLS for char in core):
        return False
    thai = "".join(char for char in core if 0x0E01 <= ord(char) <= 0x0E5B)
    return _is_plausible_thai_word(thai) if thai == core else core[0] not in _THAI_MARKS


def _is_real_row(tokens: list[str]) -> bool:
    """Whether a re-read row has something a reader could use: a word (three or more
    letters of one script, four for Latin, and nothing else in the token but
    punctuation at its edges; a Thai word must be spelt in a way Thai can be), an
    ASCII number (``1.5``, ``01-10-2569``) or a Latin code (``INT-QP-PR-007``). Two
    Thai numerals, a lone capital, a Thai word with a digit stuck to it ("ธั่อว3")
    or one with a bracket in it are what a logo or a stamp reads as."""
    for token in tokens:  # one unspellable Thai token spoils the row
        if _has_thai(token) and not _is_plausible_thai_token(token):
            return False
    for token in tokens:
        if _ASCII_NUMBER.match(token):
            return True
        word = token.strip(_EDGE_PUNCTUATION)
        stuck = _NUMBER_THEN_THAI.match(word)  # "1.5เท่า", "30วัน": the join left no space
        if stuck and len(_base_letters(stuck.group(2))) >= 2 and _is_plausible_thai_word(stuck.group(2)):
            return True
        letters = _base_letters(word)
        if len(letters) < LOGO_NOISE_WORD_LETTERS or not _is_word_token(word):
            continue
        has_digit = any(char.isdigit() for char in word)
        latin = all(char.isascii() for char in letters)
        if has_digit:
            # a Latin code such as INT-QP-PR-007; or a Thai phrase with figures stuck in it
            # ("ครบ3ปีแต่ไม่เกิน6ปี") - long enough that it is not a scrap with a digit on it
            if latin or len(letters) >= RESCUE_THAI_FIGURE_LETTERS:
                return True
        elif latin:
            if len(letters) >= RESCUE_LATIN_WORD_LETTERS and word.isalpha():
                return True
        elif all(0x0E01 <= ord(char) <= 0x0E5B for char in word) and _is_plausible_thai_word(word):
            return True
    return False


def _reread_run(gray, run: tuple[int, int, int, int], language: str, tesseract) -> list[tuple[str, float]]:
    """The rows of *run* read as a block with rules erased: ``(text, mean
    confidence)`` for the rows that are sure and have a word or a number."""
    width, height = gray.size
    left, top, right, bottom = run
    crop = _erase_rules(gray.crop((
        max(0, left - RESCUE_PAD), max(0, top - RESCUE_PAD),
        min(width, right + RESCUE_PAD), min(height, bottom + RESCUE_PAD),
    )))
    data = tesseract.image_to_data(
        crop, lang=language, config="--psm 6", output_type=tesseract.Output.DICT
    )
    rows: dict[tuple, list] = {}
    for index, text in enumerate(data.get("text", [])):
        word = (text or "").strip()
        if not word:
            continue
        try:
            confidence = float(data["conf"][index])
            piece = (word, int(data["left"][index]), int(data["width"][index]), int(data["height"][index]))
            at = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            word_top = int(data["top"][index])
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        entry = rows.setdefault(at, [[], [], word_top])
        entry[0].append(piece)
        if confidence >= 0:
            entry[1].append(confidence)
        entry[2] = min(entry[2], word_top)
    result = []
    for pieces, confidences, _row_top in sorted(rows.values(), key=lambda entry: entry[2]):
        mean = sum(confidences) / len(confidences) if confidences else 0.0
        row = _join_row(pieces)
        tokens = row.split()
        if mean >= RESCUE_ROW_CONFIDENCE and _is_real_row(tokens):
            result.append((row, mean))
    return result


def _run_ink(gray, run: tuple[int, int, int, int]) -> float:
    """Share of the pixels of *run* that are ink."""
    crop = gray.crop(run)
    histogram = crop.histogram()
    return sum(histogram[:RULE_DARK_LEVEL]) / max(1, sum(histogram))


def _rescue_unread_text(band, data: dict, language: str, tesseract) -> list[tuple[tuple[int, int, int, int], list[tuple[str, float]]]]:
    """``[(run, rows)]`` for the unread runs of text of *band* (the image the
    read in *data* was made on) whose re-read is good."""
    gray = band.convert("L")
    good = [line for line in _line_boxes(data) if line.confidence >= RESCUE_LINE_CONFIDENCE]
    rescued = []
    misses = 0
    reads = 0
    for run in _unread_runs(gray, data):
        if reads >= MAX_RUN_RESCUES or misses >= RESCUE_MAX_MISSES:
            break
        centre_x, centre_y = (run[0] + run[2]) / 2, (run[1] + run[3]) / 2
        if any(line.left <= centre_x <= line.right and line.top <= centre_y <= line.bottom for line in good):
            continue  # a scrap inside a line that was read: the line has it already
        if not RESCUE_INK[0] <= _run_ink(gray, run) <= RESCUE_INK[1]:
            continue  # measured on a tour brochure: two thirds of all re-reads, none of the text
        reads += 1
        rows = _reread_run(gray, run, language, tesseract)
        if rows:
            rescued.append((run, rows))
            misses = 0
        else:
            misses += 1
    return rescued


def _splice_rescued(
    text: str, data: dict, rescued: list[tuple[tuple[int, int, int, int], list[tuple[str, float]]]],
    means: dict[str, float],
) -> str:
    """*text* with each re-read run put where it belongs.

    A run goes at the end of the sure line it sits beside (a value on the row of
    its label); if no such line was read, onto a row already made from a run on the
    same level, or a new line after the last line read above it. Lines the first
    read made inside the run, too shaky to count, are replaced.
    """
    lines = text.split("\n")
    boxes = _line_boxes(data)
    made: list[tuple[int, int, str, int]] = []  # (top, bottom, key, left) of rows made from runs

    def find(key: str) -> int | None:
        for index, existing in enumerate(lines):
            if existing.strip() and _normalized(existing) == key:
                return index
        return None

    for run, rows in sorted(rescued, key=lambda item: (item[0][1], item[0][0])):
        left, top, right, bottom = run
        height = bottom - top
        beside = None
        for line in boxes:
            overlap = min(bottom, line.bottom) - max(top, line.top)
            if overlap >= 0.5 * min(height, line.height) and line.confidence >= RESCUE_WORD_CONFIDENCE and line.right <= left + RESCUE_PAD:
                if beside is None or line.right > beside.right:
                    beside = line
            elif (
                line.confidence < RESCUE_WORD_CONFIDENCE
                and top - RESCUE_PAD <= (line.top + line.bottom) / 2 <= bottom + RESCUE_PAD
                and min(right, line.right) - max(left, line.left) >= RESCUE_REPLACE_SHARE * line.width
            ):  # a shaky line the run covers, not a long one it merely touches
                shaky = find(_normalized(line.text))
                if shaky is not None:
                    del lines[shaky]
        previous: str | None = None
        for row_index, (row, confidence) in enumerate(rows):
            target = None
            first = False  # the run lies left of the row it joins: it goes in front
            if row_index == 0:
                if beside is not None:
                    target = find(_normalized(beside.text))
                if target is None:
                    for made_top, made_bottom, made_key, made_left in made:
                        if min(bottom, made_bottom) - max(top, made_top) >= 0.5 * min(height, made_bottom - made_top):
                            target = find(made_key)
                            first = left < made_left
                            break
            if target is not None:
                old = lines[target]
                lines[target] = f"{row}   {old}" if first else f"{old}   {row}"
                new_key, old_key = _normalized(lines[target]), _normalized(old)
                means[new_key] = min(means.get(old_key, confidence), confidence)
                for index, entry in enumerate(made):
                    if entry[2] == old_key:
                        made[index] = (entry[0], max(entry[1], bottom), new_key, min(entry[3], left))
                previous = new_key
                continue
            if previous is not None and find(previous) is not None:
                at = find(previous) + 1
            else:
                anchors = [
                    (line.bottom, _normalized(line.text)) for line in boxes
                    if line.bottom <= top + RESCUE_PAD and line.confidence >= RESCUE_WORD_CONFIDENCE
                ]
                anchors += [(made_bottom, made_key) for _top, made_bottom, made_key, _left in made if made_bottom <= top + RESCUE_PAD]
                at = 0
                if anchors:
                    found = find(max(anchors, key=lambda anchor: anchor[0])[1])
                    at = len(lines) if found is None else found + 1
            lines[at:at] = ["", row, ""]
            means[_normalized(row)] = confidence
            made.append((top, bottom, _normalized(row), left))
            previous = _normalized(row)
    return "\n".join(lines)


def recognize_region(image, language: str) -> str:
    """OCR of a single, already-isolated crop (a table cell) - no panel/gutter
    splitting or line-confidence filtering, since a cell crop is already a
    small, pre-separated fragment rather than a mixed page with pictures and
    noise to tell apart from text."""
    import pytesseract

    prepared = prepare_for_ocr(image.convert("RGB"))
    try:
        return normalize_thai(
            pytesseract.image_to_string(prepared, lang=language, config="--psm 6").strip()
        )
    except Exception:
        return ""


def recognize(image_path: str | Path, language: str) -> str:
    """Text of the image at *image_path*, panel by panel, noise removed."""
    import pytesseract

    def plain(target) -> str:
        return pytesseract.image_to_string(target, lang=language)

    if not hasattr(pytesseract, "image_to_data") or not hasattr(pytesseract, "Output"):
        return normalize_thai(plain(str(image_path)))
    try:
        from PIL import Image

        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        bands = split_into_bands(image)
    except Exception:
        return normalize_thai(plain(str(image_path)))

    pieces: list[str] = []
    for band in bands:
        band = prepare_for_ocr(band, limit_clipping=True)
        text = plain(band)
        try:
            data = pytesseract.image_to_data(
                band, lang=language, output_type=pytesseract.Output.DICT
            )
            junk = _low_confidence_lines(data)
            means = _line_mean_confidences(data)
            try:
                replacements = _rejoin_marks(band, data, language, pytesseract, text)
            except Exception as exc:
                if _is_missing_language(exc):
                    raise
                replacements = []
            for base_key, new_text, confidence, mark_key in replacements:
                text, found = _replace_line(text, base_key, new_text)
                if found:  # the mark row goes only once its base row is fixed
                    means[_normalized(new_text)] = confidence
                    junk.add(mark_key)
            if "eng" in language.split("+"):
                try:
                    runs = _reread_latin_runs(band, data, pytesseract)
                except Exception as exc:
                    if _is_missing_language(exc):
                        raise
                    runs = []
                text = _apply_latin_runs(text, runs, junk, means)
            if THAI_REREAD and "tha" in language.split("+"):
                try:
                    words = _reread_thai_words(band, data, pytesseract)
                except Exception as exc:
                    if _is_missing_language(exc):
                        raise
                    words = []
                text = _apply_latin_runs(text, words, junk, means)
            try:
                rescued = _rescue_unread_text(band, data, language, pytesseract) if RESCUE_UNREAD else []
                if rescued:
                    text = _splice_rescued(text, data, rescued, means)
            except Exception as exc:
                if _is_missing_language(exc):
                    raise
            junk |= _logo_noise_keys(text, means)
            text = _without_junk(text, junk)
            text = _mark_uncertain(text, means)
        except Exception as exc:
            if _is_missing_language(exc):
                raise
        if text.strip():
            pieces.append(text.strip())
    return normalize_thai("\n\n".join(pieces))


def _is_missing_language(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("failed loading language", "could not initialize tesseract", "tessdata")
    )


# --------------------------------------------------------------------------
# Posters and photographs: several readings, merged
# --------------------------------------------------------------------------
#
# Text scattered over a picture (a product poster: a title, a ring of short
# claims, a footer) is read differently by each Tesseract page mode and by each
# scale. Measured on one such poster, "auto layout" got the footer but missed
# "ต้านการอักเสบ"; "sparse text" got that but garbled "ลดน้ำตาลในเลือด"; and no
# single setting read more than about 70% of the phrases. Each reading finds
# lines the others miss, so the readings are pooled and, where two cover the same
# part of the image, the more confident one wins.

IMAGE_MIN_LINE_CONFIDENCE = 45.0
MIN_WORDLIKE_RATIO = 0.6
IMAGE_SPACE_GAP_RATIO = 0.55
IMAGE_UPSCALE_BELOW = 1500  # px on the short side
OVERLAP_REJECT = 0.5


@dataclass
class _Reading:
    text: str
    confidence: float
    left: float
    top: float
    right: float
    bottom: float

    @property
    def quality(self) -> float:
        return self.confidence * math.sqrt(max(1, len(_normalized(self.text))))

    @property
    def area(self) -> float:
        return max(1.0, (self.right - self.left) * (self.bottom - self.top))


def _join_pieces(pieces: list[tuple[str, float, float, float]]) -> str:
    """Join word pieces, spacing Latin words and wide Thai gaps (see ``prepare_for_ocr``)."""
    out = ""
    previous_end = None
    for text, left, width, height in pieces:
        if previous_end is not None:
            both_latin = out[-1:].isascii() and text[:1].isascii()
            if both_latin or left - previous_end > IMAGE_SPACE_GAP_RATIO * height:
                out += " "
        out += text
        previous_end = left + width
    return out


# Public name for callers outside this module (table OCR joins a cell's words
# with exactly the rule posters use).
join_word_pieces = _join_pieces


def _readings(data: dict, scale: float) -> list[_Reading]:
    lines: dict[tuple, list[int]] = {}
    for index, text in enumerate(data.get("text", [])):
        if (text or "").strip():
            key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
            lines.setdefault(key, []).append(index)
    readings: list[_Reading] = []
    for indexes in lines.values():
        confidences = []
        pieces = []
        for index in indexes:
            try:
                value = float(data["conf"][index])
            except (ValueError, TypeError):
                continue
            if value >= 0:
                confidences.append(value)
            pieces.append((
                data["text"][index].strip(), data["left"][index],
                data["width"][index], data["height"][index],
            ))
        if not confidences or not pieces:
            continue
        mean = sum(confidences) / len(confidences)
        text = _join_pieces(pieces)
        floor = MIN_SHORT_LINE_CONFIDENCE if len(_normalized(text)) <= SHORT_LINE_CHARS else IMAGE_MIN_LINE_CONFIDENCE
        if mean < floor or _wordlike_ratio(text) < MIN_WORDLIKE_RATIO:
            continue
        left = min(p[1] for p in pieces)
        right = max(p[1] + p[2] for p in pieces)
        top = min(data["top"][i] for i in indexes)
        bottom = max(data["top"][i] + data["height"][i] for i in indexes)
        readings.append(_Reading(text, mean, left / scale, top / scale, right / scale, bottom / scale))
    return readings


def _wordlike_ratio(text: str) -> float:
    """Share of characters that are letters, digits or the marks that belong to letters."""
    compact = _normalized(text)
    if not compact:
        return 0.0
    return sum(1 for char in compact if unicodedata.category(char)[0] in "LNM") / len(compact)


def _overlap(a: _Reading, b: _Reading) -> float:
    width = min(a.right, b.right) - max(a.left, b.left)
    height = min(a.bottom, b.bottom) - max(a.top, b.top)
    if width <= 0 or height <= 0:
        return 0.0
    return width * height / min(a.area, b.area)


def merge_readings(readings: list[_Reading]) -> str:
    """Keep the most confident reading for each region, then lay them out top to bottom."""
    accepted: list[_Reading] = []
    for reading in sorted(readings, key=lambda item: item.quality, reverse=True):
        if all(_overlap(reading, kept) <= OVERLAP_REJECT for kept in accepted):
            accepted.append(reading)
    if not accepted:
        return ""
    accepted.sort(key=lambda item: (item.top + item.bottom) / 2)
    rows: list[list[_Reading]] = []
    for reading in accepted:
        centre = (reading.top + reading.bottom) / 2
        height = reading.bottom - reading.top
        for row in rows:
            anchor = row[0]
            if abs((anchor.top + anchor.bottom) / 2 - centre) <= 0.5 * max(anchor.bottom - anchor.top, height):
                row.append(reading)
                break
        else:
            rows.append([reading])
    return "\n".join(
        " ".join(item.text for item in sorted(row, key=lambda item: item.left)) for row in rows
    )


def recognize_image(image_path: str | Path, language: str) -> str:
    """Text of a poster or photograph: several readings pooled (see above).

    Falls back to :func:`recognize` when word data is unavailable.
    """
    import pytesseract

    if not hasattr(pytesseract, "image_to_data") or not hasattr(pytesseract, "Output"):
        return recognize(image_path, language)
    try:
        from PIL import Image, ImageOps

        with Image.open(image_path) as opened:
            base = opened.convert("RGB")
    except Exception:
        return recognize(image_path, language)

    scale = 2.0 if min(base.size) < IMAGE_UPSCALE_BELOW else 1.0
    enlarged = base
    if scale != 1.0:
        enlarged = base.resize((int(base.size[0] * scale), int(base.size[1] * scale)), Image.LANCZOS)
    flattened = ImageOps.autocontrast(enlarged.convert("L"), cutoff=2)

    passes = [
        (base, "--psm 3", 1.0),
        (base, "--psm 11", 1.0),
        (flattened, "--psm 11", scale),
        # White text on dark bars (table headers, buttons) reads better inverted.
        (ImageOps.invert(flattened), "--psm 11", scale),
    ]
    readings: list[_Reading] = []
    failures = 0
    for image, config, factor in passes:
        try:
            data = pytesseract.image_to_data(
                image, lang=language, config=config, output_type=pytesseract.Output.DICT
            )
        except Exception as exc:
            if _is_missing_language(exc):
                raise
            failures += 1
            continue
        readings.extend(_readings(data, factor))
    if failures == len(passes):
        return recognize(image_path, language)
    return normalize_thai(merge_readings(readings))
