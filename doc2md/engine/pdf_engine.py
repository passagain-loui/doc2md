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

DEFAULT_OCR_DPI = 200


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


def _text_outside_tables(page, tables) -> str | None:
    """PyMuPDF text for the words positioned outside every table's bounding box.

    Words come from PyMuPDF - the same extractor the rest of the document
    uses - rather than pdfplumber, whose per-glyph line rebuilding can split
    Thai combining vowels and tone marks from their base consonants. Cells are
    excluded by position, never by string comparison. Returns ``None`` (leave
    the page's original text alone rather than guess) for a rotated page or
    if anything required is unavailable.
    """
    if page is None:
        return None
    try:
        boxes = [t.bbox for t in tables]
        if not boxes or page.rotation:
            return None
        words = page.get_text("words")
    except Exception:
        return None

    def _inside_any_box(word) -> bool:
        cx = (word[0] + word[2]) / 2
        cy = (word[1] + word[3]) / 2
        return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

    try:
        lines: dict[tuple[int, int], list[tuple[int, str]]] = {}
        for word in words:
            if _inside_any_box(word):
                continue
            lines.setdefault((word[5], word[6]), []).append((word[7], word[4]))
    except Exception:
        return None
    out: list[str] = []
    previous_block = None
    for block, line in sorted(lines):
        if previous_block is not None and block != previous_block:
            out.append("")
        out.append(" ".join(text for _, text in sorted(lines[(block, line)])))
        previous_block = block
    return "\n".join(out).strip()


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

            pages, unreadable = self._read_text_layer(doc)
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
                tables_by_page, outside_text_by_page = self._extract_tables(source, options, doc)
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
    def _read_text_layer(doc) -> tuple[list[str], int]:
        """Return per-page text plus the number of pages that could not be read.

        One page failing must not lose the other 199, so failures are recorded
        rather than raised. The caller escalates only when *every* page fails,
        which means the document - not a page - is the problem.
        """
        pages: list[str] = []
        unreadable = 0
        for page in doc:
            try:
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
        self, source: Path, options: dict, doc=None
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
                    rendered = [
                        markdown
                        for t in tables
                        if (markdown := render_table(_safe_extract(t)))
                    ]
                    if not rendered:
                        continue
                    found[index] = rendered
                    outside_text[index] = _text_outside_tables(
                        doc[index - 1] if doc is not None else None, tables
                    )
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
                    text = pytesseract.image_to_string(
                        str(png_path), lang=language
                    ).strip()
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
