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

import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MIN_LINE_CONFIDENCE = 40.0
MIN_SHORT_LINE_CONFIDENCE = 60.0
SHORT_LINE_CHARS = 3
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


def recognize(image_path: str | Path, language: str) -> str:
    """Text of the image at *image_path*, panel by panel, noise removed."""
    import pytesseract

    def plain(target) -> str:
        return pytesseract.image_to_string(target, lang=language)

    if not hasattr(pytesseract, "image_to_data") or not hasattr(pytesseract, "Output"):
        return plain(str(image_path))
    try:
        from PIL import Image

        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
        bands = split_into_bands(image)
    except Exception:
        return plain(str(image_path))

    pieces: list[str] = []
    for band in bands:
        band = prepare_for_ocr(band)
        text = plain(band)
        try:
            data = pytesseract.image_to_data(
                band, lang=language, output_type=pytesseract.Output.DICT
            )
            text = _without_junk(text, _low_confidence_lines(data))
        except Exception as exc:
            if _is_missing_language(exc):
                raise
        if text.strip():
            pieces.append(text.strip())
    return "\n\n".join(pieces)


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
    return merge_readings(readings)
