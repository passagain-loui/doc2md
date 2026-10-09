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
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError, wrap_warning
from doc2md.core.quality import EngineOutput, QualityMetrics
from doc2md.core.ocr_setup import find_tesseract, prepare_tesseract
from doc2md.core.ocr_text import recognize, recognize_region
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
                if metrics is not None:
                    metrics.pages_with_content = sum(1 for text in pages if text.strip())
                corrupt = [i for i, text in enumerate(pages) if thai_text_is_corrupt(text)]
                reread: set[int] = set()
                if corrupt:
                    warning, reread = self._reread_corrupt_pages(
                        source, doc, pages, corrupt, options, metrics
                    )
                tables_by_page, outside_text_by_page = self._extract_tables(
                    source, options, doc, buggy
                )
                for index in reread:
                    tables_by_page.pop(index + 1, None)
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

    def _reread_corrupt_pages(self, source, doc, pages, corrupt, options, metrics):
        """Replace pages whose text layer is mis-encoded Thai with OCR of the page.

        Returns ``(warning_or_none, set_of_zero_based_pages_replaced)``. When OCR
        cannot run, the text is kept (it is all there is) and the result carries a
        warning, so it is never presented as a clean read.

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
            return (
                f"The text layer of page(s) {numbers} is mis-encoded Thai (symbols in place of "
                f"tone marks and vowels) and OCR is unavailable to read it instead: {reason}",
                set(),
            )

        import pytesseract  # noqa: F401  (availability was checked above)

        language = self._ocr_language(options)
        prepare_tesseract(language)
        dpi = self._ocr_dpi(options)
        scale = dpi / 72.0
        replaced: set[int] = set()
        failed = 0

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
                for index in corrupt:
                    png_path = Path(tmpdir) / f"page_{index + 1}.png"
                    try:
                        pix = doc[index].get_pixmap(dpi=dpi)
                        pix.save(str(png_path))
                        del pix
                        text = self._ocr_page_with_tables(
                            png_path, plumber_pages, index, scale, language
                        )
                    except Exception:
                        failed += 1
                        continue
                    if text:
                        pages[index] = (
                            "> The text layer of this page is mis-encoded Thai; it was read by "
                            f"OCR instead.\n\n{text}"
                        )
                        replaced.add(index)
                    else:
                        failed += 1
        finally:
            if plumber_doc is not None:
                plumber_doc.close()
        if metrics is not None and replaced:
            metrics.ocr_backend = "tesseract"
            metrics.ocr_language = language
            metrics.ocr_pages_success = len(replaced)
        if failed:
            return (
                f"The text layer of {failed} page(s) is mis-encoded Thai and OCR could not "
                "replace it; those pages may contain wrong characters.",
                replaced,
            )
        return None, replaced

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
                grid = _grid_from_cell_ocr(t, page_image, scale, language)
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
