# pdf_engine.py

```python
"""PDF engine. Runs in an isolated worker process (PyMuPDF can segfault).

If a PDF contains no extractable text (scanned document), the engine can
optionally fall back to OCR: pages are rendered to temporary PNGs and passed
to Tesseract (guarded by `pdf_ocr_fallback` option, default enabled).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine


class PdfEngine(BaseEngine):
    name = "pdf"
    supported_kinds = (FileKind.PDF,)
    requires_process_isolation = True

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        try:
            import pymupdf
        except ImportError as exc:
            raise EngineUnavailableError(
                "PDF backend missing: pip install 'doc2md[docs]' (pymupdf)"
            ) from exc

        try:
            doc = pymupdf.open(str(source))
        except Exception as exc:
            raise ConversionError(f"Corrupted or unreadable PDF: {source} ({exc})") from exc

        try:
            if doc.needs_pass:
                raise ConversionError(f"Password-protected PDF cannot be converted: {source}")
            parts: list[str] = [f"# {Path(source).name}", ""]
            text_pages = 0
            for index, page in enumerate(doc, start=1):
                text = page.get_text("text").strip()
                if not text:
                    continue
                text_pages += 1
                parts.append(f"## Page {index}")
                parts.append("")
                parts.append(text)
                parts.append("")
            if text_pages == 0:
                ocr_markdown = self._try_ocr_fallback(doc, options)
                if ocr_markdown:
                    parts.extend(ocr_markdown)
                else:
                    parts.append(
                        f"> No extractable text found on {doc.page_count} page(s). "
                        "The PDF is likely scanned; re-run with OCR enabled."
                    )
            return "\n".join(parts)
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"PDF conversion failed: {source} ({exc})") from exc
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def _try_ocr_fallback(self, doc, options: dict) -> list[str] | None:
        if not options.get("pdf_ocr_fallback", True):
            return None
        if shutil.which("tesseract") is None:
            return None
        try:
            import pytesseract
        except ImportError:
            return None

        language = str(options.get("ocr_lang", "eng"))
        out: list[str] = []
        try:
            with tempfile.TemporaryDirectory(prefix="doc2md_pdfocr_") as tmpdir:
                for index, page in enumerate(doc, start=1):
                    png_path = Path(tmpdir) / f"page_{index}.png"
                    pix = page.get_pixmap(dpi=150)
                    pix.save(str(png_path))
                    del pix
                    text = pytesseract.image_to_string(str(png_path), lang=language).strip()
                    out.extend([f"## Page {index} (OCR)", "", text or "_(no text detected)_", ""])
        except Exception:
            return None
        return out or None
```
