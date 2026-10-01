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
from doc2md.core.ocr_text import recognize
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
                    warning, reread = self._reread_corrupt_pages(doc, pages, corrupt, options, metrics)
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

    def _reread_corrupt_pages(self, doc, pages, corrupt, options, metrics):
        """Replace pages whose text layer is mis-encoded Thai with OCR of the page.

        Returns ``(warning_or_none, set_of_zero_based_pages_replaced)``. When OCR
        cannot run, the text is kept (it is all there is) and the result carries a
        warning, so it is never presented as a clean read.
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
        replaced: set[int] = set()
        failed = 0
        with tempfile.TemporaryDirectory(prefix="doc2md_pdfocr_") as tmpdir:
            for index in corrupt:
                png_path = Path(tmpdir) / f"page_{index + 1}.png"
                try:
                    pix = doc[index].get_pixmap(dpi=dpi)
                    pix.save(str(png_path))
                    del pix
                    text = recognize(png_path, language).strip()
                except Exception:
                    failed += 1
                    continue
                if text:
                    pages[index] = (
                        "> The text layer of this page is mis-encoded Thai; it was read by OCR "
                        f"instead.\n\n{text}"
                    )
                    replaced.add(index)
                else:
                    failed += 1
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
        out: list[str] = []
        pages_total = 0
        pages_failed = 0
        pages_with_text = 0
        with tempfile.TemporaryDirectory(prefix="doc2md_pdfocr_") as tmpdir:
            for index, page in enumerate(doc, start=1):
                pages_total += 1
                png_path = Path(tmpdir) / f"page_{index}.png"
                try:
                    pix = page.get_pixmap(dpi=dpi)
                    pix.save(str(png_path))
                    del pix
                    text = recognize(png_path, language).strip()
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
