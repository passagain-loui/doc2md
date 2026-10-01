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
