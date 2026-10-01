"""Regression tests for Bug B2: OCR unavailable/disabled/no-text results must
be a distinct Warning, never indistinguishable from a full Success.

Before this fix, `ConversionResult.success` was True and there was no signal
at all that the "conversion" was really just metadata plus an explanatory
sentence - a caller (CLI/GUI) had no way to avoid reporting Success.

Note on process isolation: OcrEngine/PdfEngine run `requires_process_isolation
= True`, so `Converter.convert_file()` spawns a fresh interpreter for them and
`monkeypatch`/`sys.modules` edits made in the test process do not reach it.
Tests that need to force "no backend" therefore call the engine directly (the
same pattern `tests/test_rapidocr.py` and `tests/test_thai_documents.py` use);
tests that only need to pass plain option values (which ARE pickled across
the process boundary, e.g. `pdf_ocr_fallback=False`) go through the full
`Converter` to also verify the ConversionResult-level unwrapping.
"""

from __future__ import annotations

import sys

import pytest

from doc2md.core.converter import Converter
from doc2md.core.errors import split_warning


def test_image_ocr_unavailable_sets_warning_not_plain_success(tmp_path, monkeypatch):
    """Engine-level: with neither Tesseract nor RapidOCR available, the raw
    markdown must carry a warning marker instead of embedding the hint as
    ordinary content."""
    from PIL import Image
    import doc2md.engine.ocr_engine as ocr_engine

    p = tmp_path / "scan.png"
    Image.new("RGB", (40, 20), color="white").save(p)

    monkeypatch.setattr(ocr_engine.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        ocr_engine.OcrEngine, "_get_rapidocr",
        lambda self: (_ for _ in ()).throw(
            ocr_engine.EngineUnavailableError(
                "neither Tesseract nor RapidOCR is available; install Tesseract OCR"
            )
        ),
    )

    raw = ocr_engine.OcrEngine().convert(p, {})
    warning, markdown = split_warning(raw)

    assert warning, "a missing OCR backend must set a warning"
    assert "OCR unavailable" in warning
    assert "\x00" not in markdown
    assert "DOC2MD-WARNING" not in markdown


def test_image_ocr_unavailable_body_text_says_not_run_not_completed(tmp_path, monkeypatch):
    """Bug #6: when no OCR backend exists, OCR never ran - the document body
    a user actually reads must say so, not the "OCR completed but no
    readable text was found" sentence (which is only true when OCR really
    executed and simply found nothing)."""
    from PIL import Image
    import doc2md.engine.ocr_engine as ocr_engine

    p = tmp_path / "scan.png"
    Image.new("RGB", (40, 20), color="white").save(p)

    monkeypatch.setattr(ocr_engine.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        ocr_engine.OcrEngine, "_get_rapidocr",
        lambda self: (_ for _ in ()).throw(
            ocr_engine.EngineUnavailableError("neither Tesseract nor RapidOCR is available")
        ),
    )

    raw = ocr_engine.OcrEngine().convert(p, {})
    _warning, markdown = split_warning(raw)

    assert "was not run" in markdown
    assert "no OCR backend is available" in markdown
    assert "OCR completed" not in markdown, (
        "the unavailable-backend body text must not claim OCR completed - "
        "it never ran"
    )


def test_image_ocr_ran_but_empty_body_text_says_completed(tmp_path, monkeypatch):
    """Contrast case: when OCR genuinely executed and found nothing, "OCR
    completed but no readable text was found" IS the accurate message - this
    pins that the fix for the unavailable case didn't break the true case."""
    import doc2md.engine.ocr_engine as ocr_engine

    p = tmp_path / "blank.png"
    from PIL import Image

    Image.new("RGB", (40, 20), color="white").save(p)

    monkeypatch.setattr(ocr_engine.shutil, "which", lambda name: "C:/fake/tesseract.exe")

    class FakePytesseract:
        @staticmethod
        def image_to_string(*args, **kwargs):
            return ""

    monkeypatch.setitem(sys.modules, "pytesseract", FakePytesseract())

    raw = ocr_engine.OcrEngine().convert(p, {})
    _warning, markdown = split_warning(raw)

    assert "OCR completed" in markdown
    assert "was not run" not in markdown


def test_image_ocr_no_text_found_sets_warning(tmp_path, monkeypatch):
    """Engine-level: OCR runs but the image has no text -> warning, not a
    bare Success that looks like a real transcription."""
    from PIL import Image
    import doc2md.engine.ocr_engine as ocr_engine

    p = tmp_path / "blank.png"
    Image.new("RGB", (40, 20), color="white").save(p)

    monkeypatch.setattr(ocr_engine.shutil, "which", lambda name: "C:/fake/tesseract.exe")

    class FakePytesseract:
        @staticmethod
        def image_to_string(*args, **kwargs):
            return ""

    monkeypatch.setitem(sys.modules, "pytesseract", FakePytesseract())

    raw = ocr_engine.OcrEngine().convert(p, {})
    warning, markdown = split_warning(raw)

    assert warning
    assert "no readable text" in warning.lower()
    assert "\x00" not in markdown


def test_scanned_pdf_ocr_disabled_sets_warning(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")

    p = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(p))
    doc.close()

    result = Converter(options={"pdf_ocr_fallback": False}).convert_file(p)

    assert result.success is True
    assert result.warning
    assert "OCR disabled" in result.warning
    assert "\x00" not in result.markdown


def test_scanned_pdf_ocr_unavailable_sets_warning(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")

    p = tmp_path / "scan2.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(p))
    doc.close()

    monkeypatch.setattr("doc2md.engine.pdf_engine.shutil.which", lambda name: None)

    result = Converter().convert_file(p)

    assert result.success is True
    assert result.warning
    assert "OCR unavailable" in result.warning
    assert "\x00" not in result.markdown


def test_normal_text_conversion_has_no_warning(tmp_path):
    """A plain successful conversion must not carry a spurious warning."""
    p = tmp_path / "note.txt"
    p.write_text("ordinary content", encoding="utf-8")

    result = Converter().convert_file(p)

    assert result.success is True
    assert result.warning is None