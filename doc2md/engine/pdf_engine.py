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

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

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
    page_lines,
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
TABLE_BORDER_PX = 3  # width painted white along every cell edge before reading
TABLE_CELL_INSET_PX = 4  # a cell's inner area for the ink test excludes this margin
TABLE_CELL_INK_SHARE = 0.01  # dark share of a wordless cell above which it is re-read alone
TABLE_DARK_CELL_LEVEL = 170  # mean gray (of 255) below which a cell is light-on-dark (a grey bar is ~110-140, a light row ~215)
_INK_LEVEL = 128


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
        stats.update(big_read_s=0.0, reread_ink=0, reread_low_confidence=0, cells=0)
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
                if box is None:
                    cells_text.append("")
                elif (r, c) in words_by_cell:
                    text = _cell_text(words_by_cell[(r, c)])
                    if _cell_is_doubtful(words_by_cell[(r, c)]):
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
                        text = self._ocr_page_with_tables(
                            png_path, plumber_pages, index, scale, language
                        )
                    except Exception:
                        if is_corrupt:
                            failed += 1
                        else:
                            image_failed.append(index)
                            pages[index] = _join_blocks(pages[index], IMAGE_PAGE_OCR_FAILED_NOTE)
                            touched.add(index)
                        continue
                    if is_corrupt:
                        if text:
                            pages[index] = (
                                "> The text layer of this page is mis-encoded Thai; it was read by "
                                f"OCR instead.\n\n{text}"
                            )
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
        )

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
                if buggy:
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
