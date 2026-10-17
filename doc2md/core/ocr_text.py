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
    profile = list(ink.resize((sw, 1), Image.BOX).getdata())

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


def prepare_for_ocr(image):
    """Make a light page easier for Tesseract; dark pages are returned unchanged.

    * pale coloured fills are whitened (see :func:`_whiten_coloured_fills`);
    * large pages are median-filtered to remove scanner speckle;
    * contrast is stretched.

    Measured on three pages of a scanned company certificate, the contrast
    stretch with the median filter cut ข-read-as-ย errors from 8 to 4 against the
    unprocessed page, while flattening every light pixel (the first version of
    the fill fix) raised them to 11.
    """
    gray = image.convert("L")
    sample = list(gray.resize((64, 64)).getdata())
    if sum(sample) / len(sample) < LIGHT_PAGE_BRIGHTNESS:
        return image
    from PIL import ImageFilter, ImageOps

    if image.mode == "RGB":
        gray = _whiten_coloured_fills(gray, image)
    if gray.size[1] >= DENOISE_MIN_HEIGHT:
        gray = gray.filter(ImageFilter.MedianFilter(3))
    return ImageOps.autocontrast(gray, cutoff=1)


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


def _merge_marks(base: str, reread: str) -> str:
    """*base* with marks from *reread*, where the two agree on the letters.

    A single-line re-read recovers marks, but it also sometimes turns a Thai
    word into Latin or swaps a consonant. So the letters always come from the
    base read, and only the marks of a letter the re-read also has are taken.
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
    for tag, b1, b2, r1, r2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(b2 - b1):
                mine, theirs = base_clusters[b1 + offset], reread_clusters[r1 + offset]
                gap = mine[2] if offset == 0 else theirs[2]
                if "|" in mine[2] and "|" not in gap:
                    gap = mine[2]  # a table bar the re-read (one line) lost
                pieces.append((gap, _pick_cluster(mine[1], theirs[1])))
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
        band = prepare_for_ocr(band)
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
