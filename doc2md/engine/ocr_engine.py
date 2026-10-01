"""Image OCR engine (Thai + English). Runs in an isolated worker process.

Backend priority:

1. Tesseract binary on PATH (via pytesseract), using ``tha+eng`` by default so
   Thai documents are read correctly without any per-file configuration.
2. ``rapidocr_onnxruntime`` if it happens to be installed - it bundles its own
   ONNX models and needs no external binary. It is *not* a dependency of this
   project (the ONNX runtime alone would triple the size of the executable),
   only an opt-in upgrade path.
3. Metadata-only output with an explanatory hint, so a missing OCR backend is
   visible in the output rather than silently producing an empty file.

Thread-safety: the RapidOCR singleton is created and invoked under a
class-level lock so concurrent in-process workers can never race ONNX
initialization or inference.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError, wrap_warning
from doc2md.core.quality import EngineOutput, QualityMetrics
from doc2md.core.ocr_setup import find_tesseract, prepare_tesseract
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine

DEFAULT_OCR_LANG = "tha+eng"

_MISSING_LANGUAGE_MARKERS = (
    "failed loading language",
    "could not initialize tesseract",
    "tessdata",
)


class OcrEngine(BaseEngine):
    name = "ocr"
    supported_kinds = (FileKind.IMAGE,)
    requires_process_isolation = True
    _rapidocr_engine = None
    _rapidocr_lock = threading.Lock()

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
        parts = self._metadata_markdown(source)

        if self._tesseract_usable():
            if metrics is not None:
                metrics.pages_total = 1
                metrics.ocr_backend = "tesseract"
                metrics.ocr_language = self.language(options)
            text = self._run_tesseract(source, options)
            markdown, warning = self._plain_assemble(parts, text)
            if metrics is not None:
                metrics.ocr_pages_success = 0 if warning else 1
                metrics.ocr_pages_empty = 1 if warning else 0
                metrics.ocr_pages_failed = 0
            return wrap_warning(markdown, warning) if warning else markdown

        try:
            text = self._run_rapidocr(source)
        except EngineUnavailableError as exc:
            # OCR never ran here - it must not read like it did. The body
            # text a user actually sees (not just the internal `warning`
            # field) previously reused the "completed but no readable text"
            # sentence for this case too, which is false: no backend means
            # no attempt was made at all.
            note = f"OCR was not run: no OCR backend is available ({exc})."
            body = "\n".join([*parts, f"> {note}"])
            if metrics is not None:
                metrics.pages_total = 1
                metrics.ocr_backend = None
                metrics.ocr_pages_success = 0
                metrics.ocr_pages_empty = 0
                metrics.ocr_pages_failed = 0
            return wrap_warning(body, f"OCR unavailable: {exc}")

        if metrics is not None:
            metrics.pages_total = 1
            metrics.ocr_backend = "rapidocr"
        markdown, warning = self._plain_assemble(parts, text)
        if metrics is not None:
            metrics.ocr_pages_success = 0 if warning else 1
            metrics.ocr_pages_empty = 1 if warning else 0
            metrics.ocr_pages_failed = 0
        return wrap_warning(markdown, warning) if warning else markdown

    @staticmethod
    def _tesseract_usable() -> bool:
        """Binary on PATH *and* pytesseract importable - the same test the setup
        assistant uses, so a half-installed Tesseract falls through to RapidOCR."""
        if find_tesseract() is None:
            return False
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def language(options: dict) -> str:
        """Resolve the Tesseract language string for this conversion."""
        value = str(options.get("ocr_lang") or DEFAULT_OCR_LANG).strip()
        return value or DEFAULT_OCR_LANG

    def _metadata_markdown(self, source: Path) -> list[str]:
        try:
            from PIL import Image, UnidentifiedImageError
        except ImportError as exc:
            raise EngineUnavailableError(
                "OCR backend missing: pip install -r requirements.txt (Pillow)"
            ) from exc

        try:
            with Image.open(source) as image:
                image.load()
                width, height = image.size
                mode = image.mode
                fmt = (image.format or "UNKNOWN").lower()
        except UnidentifiedImageError as exc:
            raise ConversionError(
                f"Corrupted or unsupported image: {source} ({exc})"
            ) from exc
        except OSError as exc:
            raise ConversionError(f"Unreadable image file: {source} ({exc})") from exc

        return [
            f"# {source.name}",
            "",
            f"- **Type:** image ({fmt})",
            f"- **Dimensions:** {width} x {height}",
            f"- **Mode:** {mode}",
            "",
        ]

    @staticmethod
    def _normalized_rgb(source: Path, workdir: Path) -> Path:
        """Decode any PIL-supported format into an EXIF-upright RGB PNG.

        Also gives Tesseract a path it can definitely open: passing a Thai
        filename straight through would be re-encoded with the Windows code
        page by the Tesseract CLI and fail to open.
        """
        from PIL import Image, ImageOps

        out_path = workdir / "normalized.png"
        with Image.open(source) as image:
            upright = ImageOps.exif_transpose(image)
            rgb = upright.convert("RGB")
            rgb.save(out_path, format="PNG")
            del rgb, upright
        return out_path

    def _run_tesseract(self, source: Path, options: dict) -> str | None:
        try:
            import pytesseract
        except ImportError as exc:
            raise EngineUnavailableError(
                f"Tesseract binary detected but the pytesseract package is missing "
                f"({exc}); run pip install pytesseract"
            ) from exc
        prepare_tesseract(self.language(options))

        language = self.language(options)
        try:
            with tempfile.TemporaryDirectory(prefix="doc2md_ocr_") as tmpdir:
                normalized = self._normalized_rgb(source, Path(tmpdir))
                try:
                    return pytesseract.image_to_string(str(normalized), lang=language)
                except Exception as exc:
                    fallback = self._language_fallback(language, exc)
                    if fallback is None:
                        raise
                    text = pytesseract.image_to_string(str(normalized), lang=fallback)
                    return (
                        f"> The `{language}` Tesseract language data is not installed; "
                        f"this image was read with `{fallback}` instead.\n\n{text}"
                    )
        except ConversionError:
            raise
        except Exception as exc:
            tesseract_error = getattr(pytesseract, "TesseractError", ())
            if tesseract_error and isinstance(exc, tesseract_error):
                raise ConversionError(f"Tesseract OCR failed: {exc}") from exc
            raise ConversionError(f"OCR conversion failed: {source} ({exc})") from exc

    @staticmethod
    def _language_fallback(language: str, exc: Exception) -> str | None:
        """Return a reduced language string when *exc* is a missing-model error.

        A Thai-capable install is the goal, but a machine with plain English
        tessdata should still read the English half of a document rather than
        failing the whole conversion.
        """
        message = str(exc).lower()
        if not any(marker in message for marker in _MISSING_LANGUAGE_MARKERS):
            return None
        remaining = [
            part for part in language.split("+") if part and part.lower() != "tha"
        ]
        candidate = "+".join(remaining) or "eng"
        return candidate if candidate != language else None

    def _get_rapidocr(self):
        cls = type(self)
        if cls._rapidocr_engine is not None:
            return cls._rapidocr_engine
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise EngineUnavailableError(
                "neither Tesseract nor RapidOCR is available; "
                "install Tesseract OCR or pip install rapidocr-onnxruntime"
            ) from exc
        try:
            with cls._rapidocr_lock:
                if cls._rapidocr_engine is None:
                    cls._rapidocr_engine = RapidOCR()
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"RapidOCR failed to initialize: {exc}") from exc
        return cls._rapidocr_engine

    def _run_rapidocr(self, source: Path) -> str | None:
        # No backend at all: let EngineUnavailableError propagate to convert(),
        # which turns it into a warning result instead of embedding the hint
        # as ordinary Markdown that a caller could mistake for real content.
        engine = self._get_rapidocr()
        cls = type(self)
        try:
            with cls._rapidocr_lock:
                raw_result, _elapsed = engine(str(source))
        except Exception as exc:
            raise ConversionError(f"RapidOCR failed during inference: {exc}") from exc

        try:
            items = sorted(raw_result or [], key=lambda item: item[0])
            lines = [str(item[1]).strip() for item in items if str(item[1]).strip()]
        except Exception as exc:
            raise ConversionError(f"RapidOCR returned malformed output: {exc}") from exc
        return "\n".join(lines) if lines else None

    def _plain_assemble(self, parts: list[str], text: str | None) -> tuple[str, str | None]:
        """Build the markdown without applying the warning wrap.

        Returns ``(markdown, warning_or_none)`` so a caller (``convert``) that
        needs to attach a *different* warning - e.g. "OCR unavailable" rather
        than "no text found" - can do so without double-wrapping the result.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            note = "OCR completed but no readable text was found in the image."
            body = "\n".join([*parts, f"> {note}"])
            return body, note
        body = "\n".join([*parts, "## Extracted text", "", cleaned])
        return body, None
