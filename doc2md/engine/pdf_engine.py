"""PDF engine: automatic text-vs-scanned routing, table extraction, Thai OCR.

Runs in an isolated worker process because both PyMuPDF and Tesseract are
native code that can abort the interpreter outright.

Two distinct paths, chosen per document rather than per installation:

* **Text PDF** - PyMuPDF pulls the embedded text layer. This is the fast path
  (milliseconds per page) and is used whenever the document actually has text.
  Tables are recovered separately through pdfplumber, whose ruling-line/word
  clustering handles Thai glyphs that a naive x-position sort scrambles.
* **Scanned PDF** - detected when the text layer yields almost nothing, the
  page is rendered to a bitmap and pushed through Tesseract with the Thai +
  English models. No manual switch, no silent empty output.

Inside a text PDF, routing is also decided per page: a page whose own text layer
is mis-encoded Thai, or that is only an image with no text layer, is read by OCR
page by page instead of being dropped.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from doc2md.core import review
from doc2md.core.errors import ConversionError, EngineUnavailableError, wrap_warning
from doc2md.core.quality import EngineOutput, QualityMetrics
from doc2md.core.ocr_setup import find_tesseract, prepare_tesseract
from doc2md.core.ocr_text import (
    count_uncertain_lines,
    join_word_pieces,
    normalize_thai,
    prepare_for_ocr,
    recognize,
    recognize_region,
)
from doc2md.core.pdf_text import (
    find_sara_bug_fonts,
    has_latin_mojibake,
    has_lost_marks,
    learn_mojibake_map,
    page_has_dingbat_font,
    page_lines,
    repair_mojibake,
    text_in,
    thai_text_is_corrupt,
)
from doc2md.core.router import FileKind
from doc2md.core.tables import render_table
from doc2md.engine.base import BaseEngine
from doc2md.engine.ocr_engine import DEFAULT_OCR_LANG

# A document whose entire text layer yields fewer than this many characters is
# treated as a scan rather than as a text PDF. Measured across the whole
# document, not per page: a text PDF with one scanned cover page should not
# send all 200 of its pages through OCR, and a genuine scan yields only the
# handful of characters a stray page-number layer contributes.
SCANNED_TEXT_THRESHOLD = 16

DEFAULT_OCR_DPI = 300

# In a text PDF, a page whose own text is shorter than SCANNED_TEXT_THRESHOLD
# and which is at least this much picture is an image page (a scanned appendix,
# a photo spread) and is read by OCR; a small logo or icon does not make one.
IMAGE_ONLY_MIN_COVERAGE = 0.25
# Safety cap: a text PDF never sends more than this many image pages to OCR.
MAX_IMAGE_ONLY_PAGES = 100
MAX_LISTED_PAGE_RANGES = 10

IMAGE_PAGE_OCR_NOTE = "> This page has no text layer (it is an image); it was read by OCR."
IMAGE_PAGE_EMPTY_NOTE = "> This page is an image; OCR found no text on it."
IMAGE_PAGE_OCR_FAILED_NOTE = "> This page is an image; OCR failed on it."
MOJIBAKE_REPAIRED_NOTE = "> Thai marks on this page were mis-encoded in the PDF and were repaired."
_OCR_REPLACED_NOTE = (
    "> The text layer of this page is mis-encoded Thai; it was read by OCR instead.\n\n"
)


def _repaired_note(left_out: int = 0) -> str:
    """The note on a page whose own text layer was kept with its marks put back."""
    if not left_out:
        return MOJIBAKE_REPAIRED_NOTE
    return (
        f"{MOJIBAKE_REPAIRED_NOTE[:-1]}; {left_out} character(s) could not be "
        "recovered (highlighted lines)."
    )


# A page whose marks were swapped for other characters (not lost) is repaired in
# place when the document's own map explains enough of them, and is otherwise read
# by OCR. This is the share of such characters allowed to stay unexplained for the
# repaired text to be kept: they are left out of it, the line each came from is
# flagged for review (``review.REPAIR_LOSS_CONFIDENCE``) and the page note counts
# them. 0 would demand that all of them be explained.
MOJIBAKE_MAX_UNMAPPED_SHARE = 0.2


def _read_in_full(read_page: Callable[[int], str] | None, index: int) -> str:
    """The full OCR read of page *index*, or "" when there is none to be had."""
    if read_page is None:
        return ""
    try:
        return read_page(index).strip()
    except Exception:
        return ""


def _repair_flagged(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """*text* with swapped marks put back, line by line, and how many it had to leave out.

    A line that lost characters is flagged for review. The flag is added after
    the Thai normalisation, so it stays attached to the end of its line.
    """
    lines = []
    lost_total = 0
    for line in text.split("\n"):
        fixed, lost = repair_mojibake(line, mapping, drop_unmapped=True)
        fixed = normalize_thai(fixed)
        if lost:
            fixed = review.encode(fixed, review.REPAIR_LOSS_CONFIDENCE)
            lost_total += lost
        lines.append(fixed)
    return "\n".join(lines), lost_total


@dataclass
class _OcrOutcome:
    """What the OCR pass over a text PDF's weak pages did (zero-based pages)."""

    warning: str | None = None
    replaced: set[int] = field(default_factory=set)
    """Pages whose text is now OCR text (their pdfplumber tables are dropped)."""
    touched: set[int] = field(default_factory=set)
    """Image pages whose text was changed (a note was added), read or not."""
    unread_images: set[int] = field(default_factory=set)
    """Image pages OCR gave no text for: whatever text layer they have (a
    footer) is not content."""
    repaired: dict[int, int] = field(default_factory=dict)
    """Pages whose own text layer is kept with the swapped marks put back, each
    with how many swapped characters could not be and were left out."""
    mojibake_map: dict[str, str] = field(default_factory=dict)
    """What each swapped character was learned to stand for (see ``repaired``)."""
    read_page: Callable[[int], str] | None = None
    """Reads one page by OCR in full (tables cell by cell): for a repaired page
    whose tables turn out not to be repairable after all."""


def _page_ranges(indexes, limit: int = MAX_LISTED_PAGE_RANGES) -> str:
    """Zero-based page indexes as 1-based numbers with consecutive runs
    compressed: ``[18, 19, 20, 25]`` -> ``"19-21, 26"``. Past *limit* runs the
    list ends with ``...``."""
    runs: list[list[int]] = []
    for number in sorted({index + 1 for index in indexes}):
        if runs and number == runs[-1][1] + 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    parts = [str(a) if a == b else f"{a}-{b}" for a, b in runs[:limit]]
    return ", ".join(parts) + ("..." if len(runs) > limit else "")


def _join_blocks(*blocks: str) -> str:
    """Non-empty *blocks* separated by a blank line."""
    return "\n\n".join(block for block in blocks if block)


def _union_area(boxes) -> float:
    """Area covered by the union of ``(x0, y0, x1, y1)`` boxes."""
    if not boxes:
        return 0.0
    xs = sorted({x for box in boxes for x in (box[0], box[2])})
    total = 0.0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((b[1], b[3]) for b in boxes if b[0] < right and b[2] > left)
        covered, end = 0.0, None
        for top, bottom in spans:
            if end is None or top > end:
                covered += bottom - top
                end = bottom
            elif bottom > end:
                covered += bottom - end
                end = bottom
        total += covered * (right - left)
    return total


def _report_progress(options: dict, current: int, total: int) -> None:
    """Tell the parent process which page a scanned/OCR'd PDF is up to.

    ``_progress_sender`` is a live ``multiprocessing.Connection`` injected
    only inside the already-spawned worker (see
    ``doc2md.core.converter._isolated_convert_entry``) - it never crosses
    the picklable-options filter, so most callers simply never find it in
    *options* and this is a no-op. A broken pipe (parent gave up waiting) is
    not this conversion's problem, so any send failure is swallowed.
    """
    sender = options.get("_progress_sender")
    if sender is None:
        return
    try:
        sender.send(("progress", (current, total)))
    except Exception:
        pass


def _pdfplumber_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pdfplumber") is not None


def _safe_extract(table) -> list:
    """``Table.extract()`` can itself raise on a malformed table; a single
    bad table must not fail the whole page's table extraction.
    """
    try:
        return table.extract() or []
    except Exception:
        return []


def _text_outside_tables(page, tables, buggy=frozenset()) -> str | None:
    """The page's own text for characters positioned outside every table box.

    Characters come from PyMuPDF - the extractor the rest of the document uses,
    with the Thai repair of :mod:`doc2md.core.pdf_text` - rather than from
    pdfplumber, whose per-glyph line rebuilding splits Thai combining marks from
    their base consonants. Cells are excluded by position, never by comparing
    strings. Returns ``None`` (leave the page's text alone rather than guess) for
    a rotated page or if anything required is unavailable.
    """
    if page is None:
        return None
    try:
        boxes = [t.bbox for t in tables]
        if not boxes or page.rotation:
            return None
        lines = page_lines(page, buggy)
    except Exception:
        return None
    return text_in(lines, exclude=boxes).strip()


def _grid_from_page_text(table, lines) -> list[list[str]] | None:
    """Table cells filled with the PDF's own text clipped to each cell.

    pdfplumber finds the cell boxes; its text for the cells is not used, because
    pdfminer inserts spaces inside Thai words and inside numbers ("1 0,400.00").
    """
    try:
        grid = [
            [text_in(lines, include=cell, merge_lines=True) if cell else "" for cell in row.cells]
            for row in table.rows
        ]
    except Exception:
        return None
    return grid if any(any(cell for cell in row) for row in grid) else None


def _scaled_box(bbox, scale: float, width: int, height: int) -> tuple[int, int, int, int] | None:
    """A PDF-point ``(x0, top, x1, bottom)`` box to pixel space at *scale*
    (pixels per point), clamped to the rendered image's own bounds."""
    x0, top, x1, bottom = bbox
    box = (
        max(0, int(x0 * scale)), max(0, int(top * scale)),
        min(width, int(x1 * scale)), min(height, int(bottom * scale)),
    )
    return box if box[2] > box[0] and box[3] > box[1] else None


def _grid_from_cell_ocr(table, page_image, scale: float, language: str) -> list[list[str]] | None:
    """Table cells filled by OCR-cropping *page_image* to each cell's own box.

    Used in place of :func:`_grid_from_page_text` when the page's text layer
    is corrupt: pdfplumber's cell geometry comes from the PDF's vector ruling
    lines, which a broken font's character map never touches, so the grid
    shape is still trustworthy - only the font's own (garbage) text is
    replaced, with an OCR read of that exact cell instead.
    """
    try:
        width, height = page_image.size
        grid = []
        for row in table.rows:
            cells_text = []
            for cell in row.cells:
                if not cell:
                    cells_text.append("")
                    continue
                box = _scaled_box(cell, scale, width, height)
                cells_text.append(recognize_region(page_image.crop(box), language) if box else "")
            grid.append(cells_text)
    except Exception:
        return None
    return grid if any(any(cell for cell in row) for row in grid) else None


# One Tesseract read of a whole table instead of one per cell (psm 6; psm 4 and
# 11 scored 0.91-0.93 at best). Full Fortuner conversion, Balanced AI, same
# session; accuracy = difflib ratio of table 1 (71 rows x 8) against a hand
# transcription (spacing, bars, dots, dashes ignored):
#
#   config              total    _ocr_page_with_tables   table-1 accuracy
#   per-cell (old)     118.6 s         93.0 s                 0.831
#   NEW, conf < 70      74.3 s         50.8 s                 0.941
#   NEW, conf < 50      51.3 s         27.4 s                 0.934   <- chosen
#   NEW, no re-read     38.5 s         15.0 s                 0.930
#
# About 9.6 s of the NEW page time is prose OLD never read: the page-sized frame
# table masked the whole page. Doubtful cells are re-read alone because that
# restores short labels the big read garbles; the per-cell reader's own accuracy
# is low as pdfplumber splits a merged value cell into column boxes.
TABLE_OCR_CONFIG = "--psm 6"
TABLE_CELL_MIN_CONFIDENCE: float | None = 50.0  # a cell below this mean word confidence is re-read alone
# Measured on the same table (v1.5.3 -> v1.5.4, accuracy without / with bullets and
# dashes kept): 0.934 / 0.931 -> 0.941 / 0.940, cells re-read alone 9 -> 22; on the
# second table 178 bullet/dash cells now read as "•" / "–" instead of noise. Full
# Fortuner page time +4-7% over v1.5.3 in back-to-back runs. Short-label rules: the
# Latin one alone gave 0.939 / 0.938 (12 re-reads), both together are the best.
TABLE_SYMBOL_CELLS = True  # decide bullet / dash cells from the image
TABLE_SHORT_TEXT_MAX_CHARS: int | None = 3  # a cell read as this few characters is re-read alone
TABLE_SHORT_LATIN_MAX_CHARS: int | None = 6  # ... or this few, when they are only ASCII letters (Thai misread as Latin)
TABLE_BORDER_PX = 3  # width painted white along every cell edge before reading
TABLE_CELL_INSET_PX = 4  # a cell's inner area for the ink test excludes this margin
TABLE_CELL_INK_SHARE = 0.01  # dark share of a wordless cell above which it is re-read alone
TABLE_DARK_CELL_LEVEL = 170  # mean gray (of 255) below which a cell is light-on-dark (a grey bar is ~110-140, a light row ~215)
TABLE_DARK_BAND_MIN_PX = 8  # a dark band inside a light cell is at least this tall (about 2 pt at 300 dpi)
_INK_LEVEL = 128

# A bullet or dash cell holds one small mark and nothing else. Tesseract reads
# such a cell as noise, so it is decided from the image: if ALL the ink in the
# cell's inner area is a single compact blob it is a bullet, if it is a single
# short thin stroke it is a dash. Sizes are in PDF points (pixels / scale) so
# they hold at any render DPI. Anything bigger, thinner, wider than one mark or
# in two pieces ("5.8", "1", "-" inside a number, a Thai word) is not a symbol.
TABLE_SYMBOL_MIN_AREA_PT2 = 0.5  # less ink than this is a speck, not a mark
TABLE_DOT_MIN_PT = 0.7  # a dot is between this and the next many points across ...
TABLE_DOT_MAX_PT = 5.0
TABLE_DOT_MAX_ASPECT = 1.6  # ... roughly as wide as tall ...
TABLE_DOT_MIN_FILL = 0.55  # ... and solid (a disc fills 0.79 of its box)
TABLE_DASH_MIN_PT = 1.2  # a dash is this long up to the next, ...
TABLE_DASH_MAX_PT = 9.0
TABLE_DASH_MAX_THICKNESS_PT = 1.6  # ... thin,
TABLE_DASH_MIN_ASPECT = 2.5  # ... and at least this much wider than thick
TABLE_DASH_MIN_FILL = 0.6
TABLE_SYMBOL_MAX_CELL_SHARE = 0.5  # a mark is at most this share of the cell's height
TABLE_SYMBOL_CENTRE_BAND = (0.1, 0.9)  # and sits in this middle part of the cell, both ways
# Ink touching the edge of the inner area belongs to something outside the cell (a
# neighbour's glyph, a ruling-line remnant) and is ignored, as long as it is only
# a few pixels; a big text touching the edge is not a symbol cell at all.
TABLE_SYMBOL_MAX_EDGE_INK_PT2 = 1.5
BULLET = "•"
EN_DASH = "–"
CHECK = chr(0x2713)
CROSS = chr(0x2717)

# A tick or a cross in a table cell is decided from the ink too, and more strictly
# than a dot or a dash: the whole ink of the cell must be ONE connected shape of a
# plausible size (in points, like the constants above) that passes the shape test
# of :func:`_looks_like_check` / :func:`_looks_like_cross`. Letters that resemble
# them ("V", "/", the "x" of "4 x 4", an "X" inside a word) fail those tests:
# they are two pieces, or wide, or have ink in the wrong corners.
TABLE_MARK_MIN_PT = 2.5  # a tick or cross is this big ...
TABLE_MARK_MAX_PT = 14.0  # ... up to this, each way
TABLE_MARK_MAX_CELL_SHARE = 0.95  # of the cell's height
TABLE_MARK_MIN_FILL = 0.08  # thin strokes: a stroke shape fills this much of its box ...
TABLE_MARK_MAX_FILL = 0.65  # ... but not a solid block
TABLE_CHECK_MIN_ASPECT = 0.8  # width / height of a tick
TABLE_CHECK_MAX_ASPECT = 2.2
TABLE_CHECK_FOOT_X = (0.1, 0.55)  # the lowest ink is this far across: left of centre
TABLE_CHECK_TIP_MIN_X = 0.6  # the highest ink is at least this far across: the right arm
TABLE_CHECK_CORNER_MAX_SHARE = 0.12  # ink share allowed in the empty top-left / bottom-right corners
TABLE_CHECK_ARM_MIN_SHARE = 0.08  # ink share needed on the short left arm
TABLE_CHECK_LEFT_TIP_Y = (0.25, 0.75)  # the leftmost ink (end of the short arm) is this far down: a "/" ends at the bottom
TABLE_CROSS_MIN_ASPECT = 0.65  # width / height of a cross: roughly square
TABLE_CROSS_MAX_ASPECT = 1.55
TABLE_CROSS_CORNER_MIN_SHARE = 0.15  # ink share needed in each of the four corners
TABLE_CROSS_CENTRE_MIN_SHARE = 0.25  # ... and in the middle, where the strokes cross
TABLE_CROSS_SIDE_MAX_SHARE = 0.1  # ... and allowed in the middle of each side, which stays empty
TABLE_CROSS_BALANCE = (0.6, 1.67)  # ink in the left half / right half (and top / bottom)


def _whiten_cell_borders(image, boxes) -> None:
    """Paint a few pixels along every edge of every ``(x0, y0, x1, y1)`` box
    white, in place. Ruling lines read as strokes (``|``, ``l``, ``1``) and break
    Tesseract's layout analysis; the cell boxes say exactly where they are."""
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    for x0, y0, x1, y1 in boxes:
        for edge in ((x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)):
            draw.line(edge, fill=(255, 255, 255) if image.mode == "RGB" else 255, width=TABLE_BORDER_PX)


def _invert_dark_cells(image, boxes) -> int:
    """Invert, in place, every cell whose fill is dark (a section bar or header
    with white text), so the whole table reads as dark text on light paper.

    A per-cell read handles such a cell itself (a dark crop is left alone and
    Tesseract reads light-on-dark); in the one read of a whole table the
    surrounding light paper decides and white-on-dark text is lost. Returns the
    number of cells inverted.
    """
    from PIL import ImageOps, ImageStat

    inverted = 0
    for x0, y0, x1, y1 in boxes:
        if x1 <= x0 or y1 <= y0:
            continue
        region = image.crop((x0, y0, x1, y1))
        if ImageStat.Stat(region.convert("L")).mean[0] < TABLE_DARK_CELL_LEVEL:
            # Inverting alone leaves a mid-grey fill; the page-wide contrast
            # stretch that follows would turn it dark again. Stretching the cell
            # on its own makes the fill white and the text black.
            image.paste(ImageOps.autocontrast(ImageOps.invert(region), cutoff=2), (x0, y0))
            inverted += 1
        else:
            inverted += _invert_dark_bands(image, (x0, y0, x1, y1))
    return inverted


def _invert_dark_bands(image, box) -> int:
    """Invert the dark horizontal bands of one mostly light cell, in place.

    pdfplumber sometimes gives one tall cell that holds a dark section bar and
    the light row under it; the bar's white text is lost unless the bar alone is
    inverted. A row of pixels is dark when its *median* is below
    ``TABLE_DARK_CELL_LEVEL`` (white text on a dark bar still has a dark median;
    dark text on a light row never does), and a run of such rows at least
    ``TABLE_DARK_BAND_MIN_PX`` tall is a band. Returns the number of bands inverted.
    """
    from PIL import ImageOps

    x0, y0, x1, y1 = box
    gray = image.crop(box).convert("L")
    width, height = gray.size
    pixels = list(gray.getdata())
    dark_rows = [
        sorted(pixels[row * width:(row + 1) * width])[width // 2] < TABLE_DARK_CELL_LEVEL
        for row in range(height)
    ]
    inverted = 0
    row = 0
    while row < height:
        if not dark_rows[row]:
            row += 1
            continue
        start = row
        while row < height and dark_rows[row]:
            row += 1
        if row - start >= TABLE_DARK_BAND_MIN_PX:
            band = (x0, y0 + start, x1, y0 + row)
            image.paste(ImageOps.autocontrast(ImageOps.invert(image.crop(band)), cutoff=2), (band[0], band[1]))
            inverted += 1
    return inverted


def _cell_has_ink(gray, box) -> bool:
    """Whether the inner area of *box* in the grayscale *gray* holds enough dark
    pixels to be text rather than an empty cell."""
    x0, y0, x1, y1 = box
    inner = (x0 + TABLE_CELL_INSET_PX, y0 + TABLE_CELL_INSET_PX, x1 - TABLE_CELL_INSET_PX, y1 - TABLE_CELL_INSET_PX)
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        return False
    histogram = gray.crop(inner).histogram()
    total = sum(histogram)
    return total > 0 and sum(histogram[:_INK_LEVEL]) / total > TABLE_CELL_INK_SHARE


def _clear_edge_ink(ink) -> int:
    """Erase, in place, every ink blob of the binary image *ink* that touches its
    edge, and return how many ink pixels that removed."""
    from PIL import ImageDraw

    width, height = ink.size
    before = ink.histogram()[255]
    if before == 0:
        return 0
    pixels = ink.load()
    seeds = (
        [(x, 0) for x in range(width)] + [(x, height - 1) for x in range(width)]
        + [(0, y) for y in range(height)] + [(width - 1, y) for y in range(height)]
    )
    for seed in seeds:
        if pixels[seed] == 255:
            ImageDraw.floodfill(ink, seed, 0)
    return before - ink.histogram()[255]


def _ink_grid(ink, found) -> list[list[int]]:
    """The ink pixels (0 / 1) inside the bounding box *found* of the binary image *ink*, by row."""
    shape = ink.crop(found)
    width = shape.width
    flat = [1 if value else 0 for value in shape.getdata()]
    return [flat[row * width:(row + 1) * width] for row in range(shape.height)]


def _one_piece(grid: list[list[int]]) -> bool:
    """Whether all the ink of *grid* is one 8-connected blob."""
    height, width = len(grid), len(grid[0])
    start = next(((y, x) for y in range(height) for x in range(width) if grid[y][x]), None)
    if start is None:
        return False
    seen = {start}
    stack = [start]
    while stack:
        y, x = stack.pop()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ny, nx = y + dy, x + dx
                if 0 <= ny < height and 0 <= nx < width and grid[ny][nx] and (ny, nx) not in seen:
                    seen.add((ny, nx))
                    stack.append((ny, nx))
    return len(seen) == sum(map(sum, grid))


def _region_share(grid: list[list[int]], x_range, y_range) -> float:
    """Share of the pixels in the fractional box (x0, x1) x (y0, y1) of *grid* that are ink."""
    height, width = len(grid), len(grid[0])
    left, right = int(x_range[0] * width), max(int(x_range[0] * width) + 1, round(x_range[1] * width))
    top, bottom = int(y_range[0] * height), max(int(y_range[0] * height) + 1, round(y_range[1] * height))
    cells = [grid[y][x] for y in range(top, min(bottom, height)) for x in range(left, min(right, width))]
    return sum(cells) / len(cells) if cells else 0.0


def _centroid_x(grid: list[list[int]], rows) -> float | None:
    """Mean x (as a fraction of the width) of the ink pixels in *rows*, or ``None``."""
    width = len(grid[0])
    xs = [x for y in rows for x in range(width) if grid[y][x]]
    return sum(xs) / len(xs) / width if xs else None


def _looks_like_check(grid: list[list[int]]) -> bool:
    """A tick: one stroke, a short left arm going down to a foot left of centre
    and a long right arm rising to the top right; the top-left and bottom-right
    corners stay empty (a "V" has ink top left, a "/" has no left arm)."""
    height, width = len(grid), len(grid[0])
    if not TABLE_CHECK_MIN_ASPECT <= width / height <= TABLE_CHECK_MAX_ASPECT:
        return False
    band = max(1, round(height * 0.2))
    foot = _centroid_x(grid, range(height - band, height))
    tip = _centroid_x(grid, range(0, band))
    if foot is None or tip is None:
        return False
    if not (TABLE_CHECK_FOOT_X[0] <= foot <= TABLE_CHECK_FOOT_X[1] and tip >= TABLE_CHECK_TIP_MIN_X):
        return False
    if _region_share(grid, (0, 0.3), (0, 0.3)) > TABLE_CHECK_CORNER_MAX_SHARE:
        return False
    if _region_share(grid, (0.7, 1), (0.7, 1)) > TABLE_CHECK_CORNER_MAX_SHARE:
        return False
    if _region_share(grid, (0, 0.3), (0.3, 0.8)) < TABLE_CHECK_ARM_MIN_SHARE:
        return False
    columns = max(1, round(width * 0.15))
    ys = [y for y in range(height) for x in range(columns) if grid[y][x]]
    tip_y = sum(ys) / len(ys) / height if ys else None
    return tip_y is not None and TABLE_CHECK_LEFT_TIP_Y[0] <= tip_y <= TABLE_CHECK_LEFT_TIP_Y[1]


def _looks_like_cross(grid: list[list[int]]) -> bool:
    """A cross: two strokes crossing in the middle of a roughly square box, ink in
    all four corners and the centre, and nothing in the middle of any side."""
    height, width = len(grid), len(grid[0])
    if not TABLE_CROSS_MIN_ASPECT <= width / height <= TABLE_CROSS_MAX_ASPECT:
        return False
    for x_range, y_range in (((0, 0.3), (0, 0.3)), ((0.7, 1), (0, 0.3)), ((0, 0.3), (0.7, 1)), ((0.7, 1), (0.7, 1))):
        if _region_share(grid, x_range, y_range) < TABLE_CROSS_CORNER_MIN_SHARE:
            return False
    if _region_share(grid, (0.35, 0.65), (0.35, 0.65)) < TABLE_CROSS_CENTRE_MIN_SHARE:
        return False
    for x_range, y_range in (((0.4, 0.6), (0, 0.2)), ((0.4, 0.6), (0.8, 1)), ((0, 0.2), (0.4, 0.6)), ((0.8, 1), (0.4, 0.6))):
        if _region_share(grid, x_range, y_range) > TABLE_CROSS_SIDE_MAX_SHARE:
            return False
    left, right = _region_share(grid, (0, 0.5), (0, 1)), _region_share(grid, (0.5, 1), (0, 1))
    upper, lower = _region_share(grid, (0, 1), (0, 0.5)), _region_share(grid, (0, 1), (0.5, 1))
    low, high = TABLE_CROSS_BALANCE
    return bool(right and lower and low <= left / right <= high and low <= upper / lower <= high)


def _symbol_in_cell(gray, box, scale: float) -> str | None:
    """``"\u2022"``, ``"\u2013"``, ``"\u2713"`` or ``"\u2717"`` when the whole ink of the
    cell is one bullet, one dash, one tick or one cross.

    Looks at the dark pixels of *box*'s inner area in the grayscale *gray*: their
    bounding box and how solidly they fill it (and, for a tick or a cross, the
    shape of the strokes). Two marks, a digit, a decimal point beside digits or
    any text have a bigger or emptier box and give ``None``, as does an empty cell."""
    x0, y0, x1, y1 = box
    inner = (
        x0 + TABLE_CELL_INSET_PX, y0 + TABLE_CELL_INSET_PX,
        x1 - TABLE_CELL_INSET_PX, y1 - TABLE_CELL_INSET_PX,
    )
    if inner[2] <= inner[0] or inner[3] <= inner[1]:
        return None
    region = gray.crop(inner)
    ink = region.point(lambda value: 255 if value < _INK_LEVEL else 0)
    if _clear_edge_ink(ink) / (scale * scale) > TABLE_SYMBOL_MAX_EDGE_INK_PT2:
        return None
    found = ink.getbbox()
    if found is None:
        return None
    width, height = (found[2] - found[0]) / scale, (found[3] - found[1]) / scale  # points
    area = ink.histogram()[255]
    if area / (scale * scale) < TABLE_SYMBOL_MIN_AREA_PT2 or width <= 0 or height <= 0:
        return None
    region_w, region_h = region.size
    low, high = TABLE_SYMBOL_CENTRE_BAND
    centre_x = (found[0] + found[2]) / 2 / region_w
    centre_y = (found[1] + found[3]) / 2 / region_h
    if not (low <= centre_x <= high and low <= centre_y <= high):
        return None
    fill = area / ((found[2] - found[0]) * (found[3] - found[1]))
    longer, shorter = max(width, height), min(width, height)
    if (found[3] - found[1]) <= TABLE_SYMBOL_MAX_CELL_SHARE * region_h:
        if (
            TABLE_DOT_MIN_PT <= shorter and longer <= TABLE_DOT_MAX_PT
            and longer / shorter <= TABLE_DOT_MAX_ASPECT and fill >= TABLE_DOT_MIN_FILL
        ):
            return BULLET
        if (
            TABLE_DASH_MIN_PT <= width <= TABLE_DASH_MAX_PT
            and height <= TABLE_DASH_MAX_THICKNESS_PT
            and width / height >= TABLE_DASH_MIN_ASPECT and fill >= TABLE_DASH_MIN_FILL
        ):
            return EN_DASH
    if (
        TABLE_MARK_MIN_PT <= shorter and longer <= TABLE_MARK_MAX_PT
        and (found[3] - found[1]) <= TABLE_MARK_MAX_CELL_SHARE * region_h
        and TABLE_MARK_MIN_FILL <= fill <= TABLE_MARK_MAX_FILL
    ):
        grid = _ink_grid(ink, found)
        if _one_piece(grid):
            if _looks_like_check(grid):
                return CHECK
            if _looks_like_cross(grid):
                return CROSS
    return None


def _is_symbol_only(words) -> bool:
    """Whether a cell's words hold no letter and no digit: a bullet, a dash, a dot.

    Tesseract is always unsure of those, and a crop of such a cell reads back as
    noise ("0", "5๐031"), so re-reading them alone only costs time."""
    return not any(char.isalnum() for word in words for char in word[1])


def _cell_is_doubtful(words) -> bool:
    """Whether the single read was unsure of a cell: the mean confidence of its
    words (Tesseract's -1 "no confidence" values left out) is below
    ``TABLE_CELL_MIN_CONFIDENCE``. Symbol-only cells (:func:`_is_symbol_only`)
    are never doubtful."""
    if TABLE_CELL_MIN_CONFIDENCE is None or _is_symbol_only(words):
        return False
    confidences = [word[6] for word in words if word[6] >= 0]
    return bool(confidences) and sum(confidences) / len(confidences) < TABLE_CELL_MIN_CONFIDENCE


# Why a short Thai label ("สี", "มม.") came out as "a" / "uw.": with ``eng`` loaded
# next to ``tha``, Tesseract takes a few small Thai glyphs for Latin letters, and a
# plain per-cell read of a wide cell holding one tiny word (psm 6) can return
# nothing at all. Read alone, a short label is cropped to its ink, enlarged to a
# size Tesseract likes, and read as one line with ``tha`` only. Measured on eight
# short cells ("สี", four "มม.", "หน้า", "หลัง"): the per-cell read got 7, this 8.
TABLE_SHORT_REREAD_PAD_PT = 3.0  # white margin around the ink of a short cell
TABLE_SHORT_REREAD_TARGET_PX = 45  # enlarge the ink to about this height ...
TABLE_SHORT_REREAD_MAX_FACTOR = 4  # ... by at most this factor
TABLE_SHORT_REREAD_MIN_CONF = 50.0  # mean word confidence below which the Thai-only read is not trusted
_THAI_LETTER = re.compile("[ก-ฮ]")


def _join_label_words(words) -> str:
    """The words of a one-line short label, left to right. Thai pieces and
    punctuation are joined as they come ("มม" + "." is "มม."); only two Latin
    words get a space between them."""
    out = ""
    for word in sorted(words, key=lambda item: item[2]):
        text = word[1]
        if out and out[-1].isascii() and out[-1].isalnum() and text[0].isascii() and text[0].isalnum():
            out += " "
        out += text
    return normalize_thai(out)


def _reread_short_cell(crop, language: str, scale: float) -> str:
    """Re-read of a short label's cell.

    The plain per-cell read goes first and is kept if it found Thai ("ลิตร", "มม."
    read right that way, and a Thai-only read sometimes garbles them). Only when
    it found nothing or only Latin letters (the failures described at
    ``TABLE_SHORT_REREAD_*``) is the cell cropped to its ink, enlarged and read as
    one line with ``tha`` only; that read is used if it has a Thai letter and a mean
    confidence of at least ``TABLE_SHORT_REREAD_MIN_CONF``, else the plain read
    stands (a genuine short Latin word such as "LED" reads as itself)."""
    import pytesseract
    from PIL import Image, ImageOps

    plain = recognize_region(crop, language)
    if _THAI_LETTER.search(plain) or "tha" not in language.split("+"):
        return plain
    gray = prepare_for_ocr(crop.convert("RGB")).convert("L")
    found = gray.point(lambda value: 255 if value < _INK_LEVEL else 0).getbbox()
    if found is None:
        return plain
    pad = round(TABLE_SHORT_REREAD_PAD_PT * scale)
    tight = gray.crop((
        max(0, found[0] - pad), max(0, found[1] - pad),
        min(gray.width, found[2] + pad), min(gray.height, found[3] + pad),
    ))
    factor = max(1, min(TABLE_SHORT_REREAD_MAX_FACTOR, round(TABLE_SHORT_REREAD_TARGET_PX / max(1, found[3] - found[1]))))
    if factor > 1:
        tight = tight.resize((tight.width * factor, tight.height * factor), Image.LANCZOS)
    data = pytesseract.image_to_data(
        ImageOps.expand(tight, 10, fill=255), lang="tha", config="--psm 7",
        output_type=pytesseract.Output.DICT,
    )
    words = []
    confidences = []
    for index, text in enumerate(data.get("text", [])):
        word = (text or "").strip()
        if not word:
            continue
        words.append((
            (data["block_num"][index], data["par_num"][index], data["line_num"][index]),
            word, int(data["left"][index]), int(data["top"][index]),
            int(data["width"][index]), int(data["height"][index]), float(data["conf"][index]),
        ))
        if float(data["conf"][index]) >= 0:
            confidences.append(float(data["conf"][index]))
    text = _join_label_words(words)
    trusted = (
        bool(_THAI_LETTER.search(text))
        and confidences
        and sum(confidences) / len(confidences) >= TABLE_SHORT_REREAD_MIN_CONF
    )
    return text if trusted else plain


def _needs_short_reread(text: str) -> bool:
    """Whether the single read of a cell returned so little that it is worth a
    second look on its own: see ``TABLE_SHORT_TEXT_MAX_CHARS`` and
    ``TABLE_SHORT_LATIN_MAX_CHARS``. Decided from what the read returned, not
    from where the cell is."""
    compact = "".join(text.split())
    if not compact or any(char.isdigit() for char in compact):
        return False
    if not any(char.isalpha() for char in compact):
        return False  # a dash, a dot or a mark: not a misread label, and a Thai read would invent letters
    if TABLE_SHORT_TEXT_MAX_CHARS is not None and len(compact) <= TABLE_SHORT_TEXT_MAX_CHARS:
        return True
    return (
        TABLE_SHORT_LATIN_MAX_CHARS is not None
        and len(compact) <= TABLE_SHORT_LATIN_MAX_CHARS
        and compact.isascii()
        and compact.isalpha()
    )


def _cell_text(words) -> str:
    """The text of one cell from its words ``(line key, text, left, top, width, height, conf)``.

    Lines in Tesseract's order (by where they start), words left to right, each
    line joined with the spacing rule posters use; lines joined with ``\\n`` like
    a per-cell read."""
    lines: dict[tuple, list] = {}
    for key, text, left, top, width, height, _conf in words:
        lines.setdefault(key, []).append((text, left, width, height, top))
    ordered = sorted(lines.items(), key=lambda item: (min(w[4] for w in item[1]), item[0]))
    rows = [
        join_word_pieces([w[:4] for w in sorted(line_words, key=lambda w: w[1])])
        for _key, line_words in ordered
    ]
    return normalize_thai("\n".join(row for row in rows if row.strip()))


def _grid_from_table_ocr(
    table, page_image, scale: float, language: str, stats: dict | None = None
) -> list[list[str]] | None:
    """Table cells filled from ONE Tesseract read of the whole table.

    The table is cropped once, its cell borders painted white and the crop read
    with a single ``image_to_data`` call; every word goes to the cell holding
    the centre of its box. A cell that got no words but has ink (text Tesseract
    skipped in the big read) is read on its own as :func:`_grid_from_cell_ocr`
    would. If the single read fails or finds nothing at all, the whole table
    falls back to that per-cell reading.

    *stats*, if given, is filled in for measurement: ``big_read_s`` (the time of
    the one read), ``reread_ink`` / ``reread_low_confidence`` (cells re-read alone,
    by reason) and ``cells``.
    """
    import time

    if stats is not None:
        stats.update(big_read_s=0.0, reread_ink=0, reread_low_confidence=0, reread_short=0, symbols=0, cells=0)
    try:
        import pytesseract

        width, height = page_image.size
        crop_box = _scaled_box(table.bbox, scale, width, height)
        if crop_box is None:
            return _grid_from_cell_ocr(table, page_image, scale, language)
        origin_x, origin_y = crop_box[0], crop_box[1]
        crop = page_image.crop(crop_box).convert("RGB")
        crop_w, crop_h = crop.size

        # cell boxes in crop pixels (None for a merged-away cell)
        layout: list[list[tuple[int, int, int, int] | None]] = []
        for row in table.rows:
            cells = []
            for cell in row.cells:
                box = _scaled_box(cell, scale, width, height) if cell else None
                if box is None:
                    cells.append(None)
                    continue
                cells.append((
                    max(0, box[0] - origin_x), max(0, box[1] - origin_y),
                    min(crop_w, box[2] - origin_x), min(crop_h, box[3] - origin_y),
                ))
            layout.append(cells)

        boxes = [box for row in layout for box in row if box]
        _invert_dark_cells(crop, boxes)
        _whiten_cell_borders(crop, boxes)
        prepared = prepare_for_ocr(crop)
        started = time.perf_counter()
        data = pytesseract.image_to_data(
            prepared, lang=language, config=TABLE_OCR_CONFIG, output_type=pytesseract.Output.DICT
        )
        if stats is not None:
            stats["big_read_s"] = time.perf_counter() - started
            stats["cells"] = len(boxes)

        owners = [(r, c, box) for r, row in enumerate(layout) for c, box in enumerate(row) if box]
        words_by_cell: dict[tuple[int, int], list] = {}
        for index, text in enumerate(data.get("text", [])):
            word = (text or "").strip()
            if not word:
                continue
            left, top = int(data["left"][index]), int(data["top"][index])
            w, h = int(data["width"][index]), int(data["height"][index])
            try:
                conf = float(data["conf"][index])
            except (KeyError, ValueError, TypeError, IndexError):
                conf = -1.0
            centre_x, centre_y = left + w / 2, top + h / 2
            for r, c, (x0, y0, x1, y1) in owners:
                if x0 <= centre_x < x1 and y0 <= centre_y < y1:
                    key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
                    words_by_cell.setdefault((r, c), []).append((key, word, left, top, w, h, conf))
                    break
        if not words_by_cell:
            return _grid_from_cell_ocr(table, page_image, scale, language)

        gray = prepared.convert("L")
        grid: list[list[str]] = []
        for r, row in enumerate(layout):
            cells_text = []
            for c, box in enumerate(row):
                symbol = _symbol_in_cell(gray, box, scale) if box is not None and TABLE_SYMBOL_CELLS else None
                if box is None:
                    cells_text.append("")
                elif symbol:
                    # Decided from the image; never re-read, whatever the big read made of it.
                    cells_text.append(symbol)
                    if stats is not None:
                        stats["symbols"] += 1
                elif (r, c) in words_by_cell:
                    text = _cell_text(words_by_cell[(r, c)])
                    if _needs_short_reread(text):
                        page_box = _scaled_box(table.rows[r].cells[c], scale, width, height)
                        alone = (
                            _reread_short_cell(page_image.crop(page_box), language, scale) if page_box else ""
                        )
                        text = alone or text
                        if stats is not None:
                            stats["reread_short"] += 1
                    elif _cell_is_doubtful(words_by_cell[(r, c)]):
                        page_box = _scaled_box(table.rows[r].cells[c], scale, width, height)
                        alone = recognize_region(page_image.crop(page_box), language) if page_box else ""
                        text = alone or text
                        if stats is not None:
                            stats["reread_low_confidence"] += 1
                    cells_text.append(text)
                elif _cell_has_ink(gray, box):
                    if stats is not None:
                        stats["reread_ink"] += 1
                    page_box = _scaled_box(table.rows[r].cells[c], scale, width, height)
                    cells_text.append(
                        recognize_region(page_image.crop(page_box), language) if page_box else ""
                    )
                else:
                    cells_text.append("")
            grid.append(cells_text)
    except Exception:
        return _grid_from_cell_ocr(table, page_image, scale, language)
    return grid if any(any(cell for cell in row) for row in grid) else None


# pdfplumber sometimes reports the layout frame of a page (a spread's outline) as
# a "table" whose box holds the real tables. Read as cells it duplicates the whole
# page in one blob and costs a giant read. Such a frame has a handful of cells
# (2-3 on the samples) and contains another detected table's box, give or take a
# few points; a real table that merely has a small table nested in one cell (88
# cells on one sample) is not a frame and is kept.
FRAME_TABLE_TOLERANCE_PT = 2.0
FRAME_TABLE_MAX_CELLS = 4


def _without_frame_tables(
    tables, tolerance: float = FRAME_TABLE_TOLERANCE_PT, max_cells: int = FRAME_TABLE_MAX_CELLS
) -> list:
    """*tables* without any frame table: one with at most *max_cells* cells whose
    bbox contains another table's bbox (within *tolerance* points). The order of
    the others is kept. Two tables that only overlap, a single table, and a big
    table with a small one inside it are all kept."""

    def area(table) -> float:
        return (table.bbox[2] - table.bbox[0]) * (table.bbox[3] - table.bbox[1])

    def cell_count(table) -> int:
        return sum(1 for row in table.rows for cell in row.cells if cell)

    def contains(outer, inner) -> bool:
        return (
            area(outer) > area(inner)  # two tables with the same box are not frames of each other
            and outer.bbox[0] <= inner.bbox[0] + tolerance
            and outer.bbox[1] <= inner.bbox[1] + tolerance
            and outer.bbox[2] >= inner.bbox[2] - tolerance
            and outer.bbox[3] >= inner.bbox[3] - tolerance
        )

    return [
        table
        for table in tables
        if not (
            cell_count(table) <= max_cells
            and any(other is not table and contains(table, other) for other in tables)
        )
    ]


def _mask_table_regions(page_image, tables, scale: float):
    """A copy of *page_image* with every table's bounding box painted white.

    Keeps the full-page prose OCR (:func:`recognize`) from also trying to
    read the table content, which is OCR'd separately and more reliably one
    cell at a time via :func:`_grid_from_cell_ocr` - without this, the table
    would be read twice, once well (cell by cell) and once as a jumble of
    rows flattened into running text.
    """
    from PIL import ImageDraw

    masked = page_image.copy()
    draw = ImageDraw.Draw(masked)
    width, height = masked.size
    for t in tables:
        box = _scaled_box(t.bbox, scale, width, height)
        if box:
            draw.rectangle(box, fill="white")
    return masked


class PdfEngine(BaseEngine):
    name = "pdf"
    supported_kinds = (FileKind.PDF,)
    requires_process_isolation = True

    def convert(self, source: Path, options: dict) -> str:
        return self._convert_impl(source, options, None)

    def convert_structured(self, source: Path, options: dict) -> EngineOutput:
        metrics = QualityMetrics()
        markdown = self._convert_impl(source, options, metrics)
        return EngineOutput(markdown=markdown, metrics=metrics)

    def _convert_impl(
        self, source: Path, options: dict, metrics: QualityMetrics | None
    ) -> str:
        self.validate_source(source)
        doc = self._open(source)
        try:
            if doc.needs_pass:
                raise ConversionError(
                    f"Password-protected PDF cannot be converted: {source}"
                )

            buggy = find_sara_bug_fonts(doc)
            pages, unreadable = (
                self._read_text_layer(doc, buggy) if buggy else self._read_text_layer(doc)
            )
            if doc.page_count and unreadable == doc.page_count:
                raise ConversionError(
                    f"PDF conversion failed: {source} "
                    f"(the text layer is unreadable on all {doc.page_count} page(s))"
                )
            has_text = sum(len(text) for text in pages) >= SCANNED_TEXT_THRESHOLD

            if metrics is not None:
                metrics.pages_total = doc.page_count
                metrics.pages_failed = unreadable
                metrics.pages_read = doc.page_count - unreadable

            warning = None
            if has_text:
                corrupt = [i for i, text in enumerate(pages) if thai_text_is_corrupt(text)]
                image_only = self._image_only_pages(doc, pages, skip=set(corrupt))
                outcome = _OcrOutcome()
                if corrupt or image_only:
                    outcome = self._ocr_weak_pages(
                        source, doc, pages, corrupt, image_only, options, metrics
                    )
                    warning = outcome.warning
                if metrics is not None:
                    # A page counts when its final text is real content: a footer
                    # on a page that is only a picture is not.
                    metrics.pages_with_content = sum(
                        1
                        for index, text in enumerate(pages)
                        if text.strip()
                        and index not in outcome.unread_images
                    )
                tables_by_page, outside_text_by_page = self._extract_tables(
                    source, options, doc, buggy
                )
                if outcome.repaired:
                    stuck = self._repair_swapped_tables(
                        outcome, pages, tables_by_page, outside_text_by_page
                    )
                    warning = " ".join(part for part in (warning, stuck) if part) or None
                for index in outcome.replaced:
                    tables_by_page.pop(index + 1, None)
                for index in outcome.replaced | outcome.touched:
                    outside_text_by_page.pop(index + 1, None)
                if metrics is not None and options.get("pdf_tables", True) and _pdfplumber_available():
                    # Only a genuine "we looked and found N" is 0/N - when
                    # table extraction itself was switched off, the dicts
                    # come back empty regardless of the PDF's real content,
                    # so the count stays None ("not measured") rather than
                    # falsely reading as "0 tables in this document".
                    metrics.tables_detected = sum(len(v) for v in tables_by_page.values())
                body = self._render_text_pdf(
                    source, pages, options, tables_by_page, outside_text_by_page
                )
            else:
                if metrics is not None:
                    body, warning = self._render_scanned_pdf(
                        source, doc, options, metrics=metrics
                    )
                else:
                    body, warning = self._render_scanned_pdf(source, doc, options)

            markdown = "\n".join([f"# {source.name}", "", *body]).rstrip() + "\n"
            return wrap_warning(markdown, warning) if warning else markdown
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"PDF conversion failed: {source} ({exc})") from exc
        finally:
            try:
                doc.close()
            except Exception:
                pass

    @staticmethod
    def _image_coverage(page) -> float:
        """Share of *page*'s area covered by placed images (0.0 - 1.0).

        Uses where the images are drawn (PyMuPDF's image placement boxes), clipped
        to the page and unioned, so an image drawn twice or overlapping another
        is not counted twice. Any failure reads as "no images".
        """
        try:
            bounds = page.rect
            area = bounds.width * bounds.height
            if area <= 0:
                return 0.0
            boxes = []
            for info in page.get_image_info():
                x0, y0, x1, y1 = info["bbox"]
                x0, y0 = max(x0, bounds.x0), max(y0, bounds.y0)
                x1, y1 = min(x1, bounds.x1), min(y1, bounds.y1)
                if x1 > x0 and y1 > y0:
                    boxes.append((x0, y0, x1, y1))
            return _union_area(boxes) / area
        except Exception:
            return 0.0

    def _image_only_pages(self, doc, pages: list[str], skip=frozenset()) -> list[int]:
        """Zero-based pages with (almost) no text layer that are mostly picture.

        A text PDF can hold whole pages that are only an image (a scanned
        appendix, a photo spread); the document-level text check never sees them
        and they would vanish from the output. A page with a stray footer
        ("19 | P a g e") is still such a page, so the test is the page's own
        text length, not whether it is empty.
        """
        found: list[int] = []
        for index, text in enumerate(pages):
            if index in skip or len(text.strip()) >= SCANNED_TEXT_THRESHOLD:
                continue
            if self._image_coverage(doc[index]) >= IMAGE_ONLY_MIN_COVERAGE:
                found.append(index)
        return found

    def _ocr_weak_pages(self, source, doc, pages, corrupt, image_only, options, metrics):
        """OCR the pages of a text PDF whose text layer cannot be trusted.

        Two kinds go through one pass (one progress count, one set of metrics):
        pages whose text layer is mis-encoded Thai (*corrupt*), and pages that
        are only a picture (*image_only*). Returns an :class:`_OcrOutcome`.
        When OCR cannot run, the text is kept (it is all there is) and the
        result carries a warning, so it is never presented as a clean read.

        A page that also has a table loses that structure to plain OCR text
        otherwise - a comparison table flattens into running text with no way
        to tell which value belongs to which column. When pdfplumber can
        still find the table's geometry (it comes from the PDF's own vector
        ruling lines, not the broken font), the table region is masked out of
        the page before the prose is OCR'd, and each cell is OCR'd on its own
        from its own crop instead - the same geometry a correctly-encoded
        page gets, just with OCR'd cell text instead of the font's garbage.
        Any failure in that path (pdfplumber unavailable, no tables found,
        cropping or masking raising) falls back to the plain whole-page OCR
        this always did.
        """
        numbers = ", ".join(str(i + 1) for i in corrupt[:10]) + ("..." if len(corrupt) > 10 else "")
        if not options.get("pdf_ocr_fallback", True):
            reason = "OCR is switched off"
        else:
            reason = self._ocr_unavailable_reason()
        if reason:
            warnings = []
            if corrupt:
                warnings.append(
                    f"The text layer of page(s) {numbers} is mis-encoded Thai (symbols in place of "
                    f"tone marks and vowels) and OCR is unavailable to read it instead: {reason}"
                )
            if image_only:
                warnings.append(
                    f"Page(s) {_page_ranges(image_only)} are images with no text layer and OCR is "
                    f"unavailable to read them: {reason}"
                )
            return _OcrOutcome(warning=" ".join(warnings), unread_images=set(image_only))

        import pytesseract  # noqa: F401  (availability was checked above)

        to_read_images = image_only[:MAX_IMAGE_ONLY_PAGES]
        skipped_images = image_only[MAX_IMAGE_ONLY_PAGES:]
        targets = sorted([*corrupt, *to_read_images])
        language = self._ocr_language(options)
        prepare_tesseract(language)
        dpi = self._ocr_dpi(options)
        scale = dpi / 72.0
        corrupt_set = set(corrupt)
        replaced: set[int] = set()  # pages whose text is now OCR text
        failed = 0  # mis-encoded pages OCR could not replace
        image_success: set[int] = set()
        image_empty: set[int] = set()
        image_failed: list[int] = []
        touched: set[int] = set()
        # Pages whose marks were swapped for other characters, and nothing worse:
        # OCR is only the reference for repairing their own text layer (below).
        swapped = {
            index for index in corrupt
            if has_latin_mojibake(pages[index]) and not has_lost_marks(pages[index])
        }
        swapped_ocr: dict[int, str] = {}

        def read_page(index: int) -> str:
            return self._ocr_one_page(source, doc, index, options)

        plumber_doc = None
        plumber_pages = None
        if options.get("pdf_tables", True) and _pdfplumber_available():
            try:
                import pdfplumber

                plumber_doc = pdfplumber.open(str(source))
                plumber_pages = plumber_doc.pages
            except Exception:
                plumber_doc = None
                plumber_pages = None

        try:
            with tempfile.TemporaryDirectory(prefix="doc2md_pdfocr_") as tmpdir:
                for position, index in enumerate(targets, start=1):
                    _report_progress(options, position, len(targets))
                    is_corrupt = index in corrupt_set
                    png_path = Path(tmpdir) / f"page_{index + 1}.png"
                    try:
                        pix = doc[index].get_pixmap(dpi=dpi)
                        pix.save(str(png_path))
                        del pix
                        if index in swapped:
                            # Only a reference for repairing the page's own text:
                            # one plain read, not the table-by-table one.
                            text = recognize(png_path, language).strip()
                        else:
                            text = self._ocr_page_with_tables(
                                png_path, plumber_pages, index, scale, language
                            )
                    except Exception:
                        if index in swapped:
                            swapped_ocr[index] = ""
                        elif is_corrupt:
                            failed += 1
                        else:
                            image_failed.append(index)
                            pages[index] = _join_blocks(pages[index], IMAGE_PAGE_OCR_FAILED_NOTE)
                            touched.add(index)
                        continue
                    if index in swapped:
                        swapped_ocr[index] = text  # decided once every such page is read
                    elif is_corrupt:
                        if text:
                            pages[index] = _OCR_REPLACED_NOTE + text
                            replaced.add(index)
                        else:
                            failed += 1
                    elif text:
                        pages[index] = _join_blocks(pages[index], IMAGE_PAGE_OCR_NOTE, text)
                        replaced.add(index)
                        image_success.add(index)
                        touched.add(index)
                    else:
                        # A photo page is legitimately textless: say so on the
                        # page rather than leaving it silently absent.
                        pages[index] = _join_blocks(pages[index], IMAGE_PAGE_EMPTY_NOTE)
                        image_empty.add(index)
                        touched.add(index)
        finally:
            if plumber_doc is not None:
                plumber_doc.close()
        repaired: dict[int, int] = {}
        mojibake_map: dict[str, str] = {}
        if swapped:
            repaired, mojibake_map, ocr_replaced, ocr_failed = self._repair_swapped_pages(
                pages, swapped, swapped_ocr, read_page
            )
            replaced |= ocr_replaced
            failed += ocr_failed
        if metrics is not None and targets:
            metrics.ocr_backend = "tesseract"
            metrics.ocr_language = language
            metrics.ocr_pages_success = len(replaced)
            metrics.ocr_pages_failed = failed + len(image_failed)
            metrics.ocr_pages_empty = len(image_empty)
            if replaced:
                metrics.ocr_review_lines = sum(
                    count_uncertain_lines(pages[index]) for index in replaced
                )
        warnings = []
        if failed:
            warnings.append(
                f"The text layer of {failed} page(s) is mis-encoded Thai and OCR could not "
                "replace it; those pages may contain wrong characters."
            )
        if image_failed:
            warnings.append(
                f"OCR failed on page(s) {_page_ranges(image_failed)}, which are images with "
                "no text layer; those pages are missing from the output."
            )
        if skipped_images:
            warnings.append(
                f"{len(skipped_images)} more page(s) that are images with no text layer were not "
                f"read (at most {MAX_IMAGE_ONLY_PAGES} are OCR'd per document): "
                f"{_page_ranges(skipped_images)}."
            )
        return _OcrOutcome(
            warning=" ".join(warnings) or None,
            replaced=replaced,
            touched=touched,
            unread_images=(set(image_only) - image_success),
            repaired=repaired,
            mojibake_map=mojibake_map,
            read_page=read_page,
        )

    @staticmethod
    def _repair_swapped_pages(pages, swapped, swapped_ocr, read_page):
        """Settle the pages whose marks were swapped for other characters.

        *swapped_ocr* holds a cheap plain OCR read of each, only a reference: the
        map of which character stands for which mark is learned over all of them
        together (more pages, more votes). A page whose swapped characters the
        map explains keeps its own text layer with the marks put back. Any other
        page is read by OCR in full with ``read_page(index)`` (tables cell by
        cell), as a page with lost marks is; if that read fails, the plain
        reference stands in. Returns ``(repaired, map, ocr_replaced, ocr_failed)``;
        ``pages`` is updated in place.
        """
        ordered = sorted(swapped)
        mapping = learn_mojibake_map(
            "\n".join(pages[index] for index in ordered),
            "\n".join(swapped_ocr[index] for index in ordered if swapped_ocr.get(index)),
        )
        repaired: dict[int, int] = {}
        ocr_replaced: set[int] = set()
        ocr_failed = 0
        for index in ordered:
            layer = pages[index]
            _, total = repair_mojibake(layer, {})
            unmapped = repair_mojibake(layer, mapping)[1]
            if unmapped <= MOJIBAKE_MAX_UNMAPPED_SHARE * total:
                fixed, lost = _repair_flagged(layer, mapping)
                pages[index] = _join_blocks(_repaired_note(lost), fixed)
                repaired[index] = lost
            elif text := _read_in_full(read_page, index) or swapped_ocr.get(index):
                pages[index] = _OCR_REPLACED_NOTE + text
                ocr_replaced.add(index)
            else:
                ocr_failed += 1
        return repaired, mapping, ocr_replaced, ocr_failed

    @staticmethod
    def _repair_swapped_tables(outcome, pages, tables_by_page, outside_text_by_page) -> str | None:
        """Put the marks back in the tables and the outside-table text of repaired pages.

        Both come from the text layer too (and the outside text replaces the
        page's own text where a table was found), so they carry the same swapped
        characters. A page whose tables hold one the map does not explain takes
        its OCR text instead when there is one; the returned warning says so when
        there is none.
        """
        mapping = outcome.mojibake_map
        stuck = 0
        for index in sorted(outcome.repaired):
            number = index + 1
            tables = tables_by_page.get(number, [])
            outside = outside_text_by_page.get(number)
            if not tables and outside is None:
                continue
            fixed_tables = [_repair_flagged(table, mapping) for table in tables]
            fixed_outside = _repair_flagged(outside, mapping) if outside is not None else None
            lost = sum(count for _, count in fixed_tables) + (fixed_outside[1] if fixed_outside else 0)
            total = sum(repair_mojibake(table, {})[1] for table in tables) + (
                repair_mojibake(outside, {})[1] if outside is not None else 0
            )
            if lost > MOJIBAKE_MAX_UNMAPPED_SHARE * total:
                if text := _read_in_full(outcome.read_page, index):
                    pages[index] = _OCR_REPLACED_NOTE + text
                    outcome.replaced.add(index)
                    del outcome.repaired[index]
                    continue
                stuck += 1
            # What the reader sees: the outside text replaces the page's own text,
            # otherwise the tables come in addition to it.
            before = outcome.repaired[index]
            visible = lost if outside is not None else before + lost
            outcome.repaired[index] = visible
            if tables:
                tables_by_page[number] = [text for text, _ in fixed_tables]
            if fixed_outside is not None:
                outside_text_by_page[number] = _join_blocks(_repaired_note(visible), fixed_outside[0])
            elif visible != before:
                pages[index] = pages[index].replace(_repaired_note(before), _repaired_note(visible), 1)
        if stuck:
            return (
                f"The text layer of {stuck} page(s) is mis-encoded Thai and its tables could not be "
                "fully repaired; those pages may contain wrong characters."
            )
        return None

    def _ocr_one_page(self, source, doc, index: int, options: dict) -> str:
        """Render page *index* and read it by OCR with its tables (see
        :meth:`_ocr_page_with_tables`). For the odd page read on its own, after
        the pass over the others; raises when the page cannot be rendered or read."""
        language = self._ocr_language(options)
        prepare_tesseract(language)
        dpi = self._ocr_dpi(options)
        plumber_doc = None
        plumber_pages = None
        if options.get("pdf_tables", True) and _pdfplumber_available():
            try:
                import pdfplumber

                plumber_doc = pdfplumber.open(str(source))
                plumber_pages = plumber_doc.pages
            except Exception:
                plumber_doc = None
        try:
            with tempfile.TemporaryDirectory(prefix="doc2md_pdfocr_") as tmpdir:
                png_path = Path(tmpdir) / f"page_{index + 1}.png"
                pix = doc[index].get_pixmap(dpi=dpi)
                pix.save(str(png_path))
                del pix
                return self._ocr_page_with_tables(png_path, plumber_pages, index, dpi / 72.0, language)
        finally:
            if plumber_doc is not None:
                plumber_doc.close()

    @staticmethod
    def _ocr_page_with_tables(png_path, plumber_pages, index: int, scale: float, language: str) -> str:
        """OCR of the rendered page at *png_path*, with any table on it (by
        pdfplumber's own geometry, 0-based *index*) read cell by cell instead
        of as flattened prose. Falls back to a plain whole-page OCR the
        moment anything about the table path is unavailable or fails."""
        tables = []
        if plumber_pages is not None and index < len(plumber_pages):
            try:
                tables = plumber_pages[index].find_tables()
            except Exception:
                tables = []

        tables = _without_frame_tables(tables)
        if not tables:
            return recognize(png_path, language).strip()

        from PIL import Image

        try:
            with Image.open(png_path) as opened:
                page_image = opened.convert("RGB")
        except Exception:
            return recognize(png_path, language).strip()

        try:
            masked_path = png_path.with_name(png_path.stem + "_masked.png")
            _mask_table_regions(page_image, tables, scale).save(masked_path)
            prose = recognize(masked_path, language).strip()

            table_blocks = []
            for t in tables:
                grid = _grid_from_table_ocr(t, page_image, scale, language)
                markdown = render_table(grid) if grid else None
                if markdown:
                    table_blocks.append(markdown)
        except Exception:
            return recognize(png_path, language).strip()

        if not table_blocks:
            # Tables were found but every one failed to OCR into anything -
            # the masked-prose read is missing that content for nothing;
            # the plain whole-page read at least keeps it, flattened.
            return recognize(png_path, language).strip()
        return "\n\n".join(part for part in (prose, *table_blocks) if part)

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _open(source: Path):
        try:
            import pymupdf
        except ImportError as exc:
            raise EngineUnavailableError(
                "PDF backend missing: pip install -r requirements.txt (pymupdf)"
            ) from exc
        try:
            # str() rather than the Path: PyMuPDF encodes the filename with the
            # active code page on Windows, which mangles Thai directory names.
            # Passing the raw bytes of an already-resolved path avoids that.
            return pymupdf.open(filename=str(source))
        except Exception as exc:
            raise ConversionError(
                f"Corrupted or unreadable PDF: {source} ({exc})"
            ) from exc

    @staticmethod
    def _read_text_layer(doc, buggy=frozenset()) -> tuple[list[str], int]:
        """Return per-page text plus the number of pages that could not be read.

        One page failing must not lose the other 199, so failures are recorded
        rather than raised. The caller escalates only when *every* page fails,
        which means the document - not a page - is the problem.
        """
        pages: list[str] = []
        unreadable = 0
        for page in doc:
            try:
                if buggy or page_has_dingbat_font(page):
                    # Characters, not the page string: a symbol font's ticks and
                    # crosses are only mapped where the font of each one is known.
                    pages.append(text_in(page_lines(page, buggy)).strip())
                else:
                    pages.append(page.get_text("text").strip())
            except Exception:
                unreadable += 1
                pages.append("")
        return pages, unreadable

    # -------------------------------------------------------------- text path

    def _render_text_pdf(
        self,
        source: Path,
        pages: list[str],
        options: dict,
        tables_by_page: dict[int, list[str]] | None = None,
        outside_text_by_page: dict[int, str | None] | None = None,
    ) -> list[str]:
        if tables_by_page is None or outside_text_by_page is None:
            tables_by_page, outside_text_by_page = self._extract_tables(source, options)
        out: list[str] = []
        for index, text in enumerate(pages, start=1):
            tables = tables_by_page.get(index, [])
            replacement = outside_text_by_page.get(index)
            if tables and replacement is not None:
                # PyMuPDF's plain-text extraction does not know a table is a
                # table - it emits every cell's text as ordinary lines, which
                # pdfplumber has *also* just rendered as a real Markdown
                # table. `replacement` is pdfplumber's own text restricted by
                # character *position* to the area outside every table's
                # bounding box (see `_text_outside_tables`), so a cell's
                # content is excluded by geometry, never by comparing
                # strings - prose that happens to read the same as a cell
                # value is never wrongly dropped. If position-based exclusion
                # could not be computed (`replacement is None`), the original
                # text is left untouched rather than guessing.
                text = replacement
            if not text and not tables:
                continue
            out.extend([f"## Page {index}", ""])
            if text:
                out.extend([text, ""])
            for table in tables:
                out.extend([table, ""])
        if not out:
            out.append("_(the PDF contains pages but no extractable content)_")
        return out

    def _extract_tables(
        self, source: Path, options: dict, doc=None, buggy=frozenset()
    ) -> tuple[dict[int, list[str]], dict[int, str | None]]:
        """Recover tables per page as Markdown, keyed by 1-based page number.

        Returns ``(tables_by_page, outside_text_by_page)``. The second dict
        holds, for any page where a table was found, pdfplumber's own text
        extraction restricted to characters positioned *outside* every
        table's bounding box (``None`` when that computation itself failed).
        ``_render_text_pdf`` substitutes this for PyMuPDF's plain text on
        that page so table content is excluded by geometry rather than by
        string comparison - the latter previously deleted any paragraph or
        heading whose text happened to equal a cell value verbatim.

        Failure here is never fatal: a document whose tables cannot be parsed
        still converts using PyMuPDF's original per-page text, it just loses
        the grid formatting. pdfplumber is also optional, so a slim install
        degrades to text-only instead of crashing.
        """
        if not options.get("pdf_tables", True):
            return {}, {}
        try:
            import pdfplumber
        except ImportError:
            return {}, {}

        found: dict[int, list[str]] = {}
        outside_text: dict[int, str | None] = {}
        try:
            with pdfplumber.open(str(source)) as pdf:
                for index, page in enumerate(pdf.pages, start=1):
                    try:
                        tables = page.find_tables()
                    except Exception:
                        continue
                    # A page-sized frame "table" around the real ones would render
                    # the whole page again as one giant cell and, by excluding its
                    # box, hide the page's prose. The same list feeds the rendered
                    # tables and the outside-text box below.
                    tables = _without_frame_tables(tables)
                    if not tables:
                        continue
                    fitz_page = doc[index - 1] if doc is not None else None
                    lines = None
                    if fitz_page is not None and not fitz_page.rotation:
                        try:
                            lines = page_lines(fitz_page, buggy)
                        except Exception:
                            lines = None
                    rendered = []
                    for t in tables:
                        grid = _grid_from_page_text(t, lines) if lines is not None else None
                        markdown = render_table(grid if grid is not None else _safe_extract(t))
                        if markdown:
                            rendered.append(markdown)
                    if not rendered:
                        continue
                    found[index] = rendered
                    outside_text[index] = _text_outside_tables(fitz_page, tables, buggy)
        except Exception:
            return found, outside_text
        return found, outside_text

    # ----------------------------------------------------------- scanned path

    def _render_scanned_pdf(
        self,
        source: Path,
        doc,
        options: dict,
        metrics: QualityMetrics | None = None,
    ) -> tuple[list[str], str | None]:
        """Returns ``(body_lines, warning_or_none)``.

        A scan converted with OCR disabled, OCR unavailable, or OCR that found
        no text on any page is not a real read of the document: the caller
        must surface that as a warning, not a plain Success.
        """
        if not options.get("pdf_ocr_fallback", True):
            note = (
                f"No extractable text found on {doc.page_count} page(s); this PDF "
                "appears to be scanned and OCR is switched off. Re-run with OCR "
                "enabled to read it."
            )
            if metrics is not None:
                metrics.pages_total = doc.page_count
                metrics.pages_with_content = 0
            return [f"> {note}"], f"OCR disabled: {note}"

        reason = self._ocr_unavailable_reason()
        if reason:
            note = (
                f"No extractable text found on {doc.page_count} page(s); this PDF "
                f"appears to be scanned, but OCR is unavailable: {reason}"
            )
            if metrics is not None:
                metrics.pages_total = doc.page_count
                metrics.pages_with_content = 0
            return [f"> {note}"], f"OCR unavailable: {reason}"

        import pytesseract

        language = self._ocr_language(options)
        prepare_tesseract(language)
        dpi = self._ocr_dpi(options)
        scale = dpi / 72.0
        out: list[str] = []
        pages_total = 0
        pages_failed = 0
        pages_with_text = 0

        # A fully scanned page (no text layer at all) has exactly the same
        # table-structure problem a mis-encoded-text-layer page does: plain
        # whole-page OCR flattens a comparison table into running text with
        # no way to tell which value belongs to which column. pdfplumber's
        # table geometry comes from vector ruling lines, which a scan's
        # *image* obviously has none of - but the PDF page itself can still
        # carry them as real vector objects even though its text layer is
        # empty (common for a print brochure re-exported to PDF), so it is
        # still worth checking.
        plumber_doc = None
        plumber_pages = None
        if options.get("pdf_tables", True) and _pdfplumber_available():
            try:
                import pdfplumber

                plumber_doc = pdfplumber.open(str(source))
                plumber_pages = plumber_doc.pages
            except Exception:
                plumber_doc = None
                plumber_pages = None

        try:
            with tempfile.TemporaryDirectory(prefix="doc2md_pdfocr_") as tmpdir:
                for index, page in enumerate(doc, start=1):
                    pages_total += 1
                    _report_progress(options, index, doc.page_count)
                    png_path = Path(tmpdir) / f"page_{index}.png"
                    try:
                        pix = page.get_pixmap(dpi=dpi)
                        pix.save(str(png_path))
                        del pix
                        text = self._ocr_page_with_tables(
                            png_path, plumber_pages, index - 1, scale, language
                        )
                    except Exception as exc:
                        # A page-level OCR exception must not be masked by other
                        # pages succeeding: a batch where 1 of 2 pages raised
                        # previously reported warning=None (because *a* page had
                        # text), making a partially-failed OCR run
                        # indistinguishable from a clean Success.
                        pages_failed += 1
                        out.extend(
                            [f"## Page {index} (OCR)", "", f"> OCR failed: {exc}", ""]
                        )
                        continue
                    if text:
                        pages_with_text += 1
                    out.extend(
                        [
                            f"## Page {index} (OCR)",
                            "",
                            text or "_(no text detected on this page)_",
                            "",
                        ]
                    )
        finally:
            if plumber_doc is not None:
                plumber_doc.close()
        if pages_failed and pages_failed == pages_total:
            warning = f"OCR failed on all {pages_total} page(s)."
        elif pages_failed:
            warning = f"OCR partially failed on {pages_failed} of {pages_total} page(s)."
        elif pages_with_text == 0:
            warning = "OCR completed but no readable text was found in the scanned PDF."
        else:
            warning = None
        if metrics is not None:
            metrics.pages_total = pages_total
            metrics.pages_with_content = pages_with_text
            metrics.ocr_backend = "tesseract"
            metrics.ocr_language = language
            metrics.ocr_pages_success = pages_with_text
            metrics.ocr_pages_failed = pages_failed
            metrics.ocr_pages_empty = max(pages_total - pages_with_text - pages_failed, 0)
            metrics.ocr_review_lines = count_uncertain_lines("\n".join(out))
        return out, warning

    @staticmethod
    def _ocr_unavailable_reason() -> str | None:
        if find_tesseract() is None:
            return (
                "Tesseract is not installed "
                "(the OCR Diagnostics button in the app can install it with the Thai language data)"
            )
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return "the pytesseract package is not installed"
        return None

    @staticmethod
    def _ocr_language(options: dict) -> str:
        language = str(options.get("ocr_lang") or DEFAULT_OCR_LANG).strip()
        return language or DEFAULT_OCR_LANG

    @staticmethod
    def _ocr_dpi(options: dict) -> int:
        try:
            dpi = int(options.get("ocr_dpi", DEFAULT_OCR_DPI))
        except (TypeError, ValueError):
            return DEFAULT_OCR_DPI
        return min(max(dpi, 72), 600)
