"""Regression tests for bug #6: PDF scanned-page OCR status messages must
accurately reflect whether OCR ran, was disabled, or genuinely found
nothing - never claim "completed" when it never executed.

Uses PyMuPDF directly (installed in this environment) to build real blank
PDFs, and calls `PdfEngine._render_scanned_pdf()` directly rather than
through `Converter.convert_file()` - PdfEngine sets
`requires_process_isolation = True`, so a `monkeypatch`/`sys.modules` edit
made in the test process would not reach a spawned worker process; calling
the engine's own method directly keeps the fakes effective (same pattern as
`tests/test_thai_documents.py`).
"""

from __future__ import annotations

import sys
import types

import pytest

import doc2md.engine.pdf_engine as pdf_engine_module
from doc2md.engine.pdf_engine import PdfEngine


def _blank_pdf(tmp_path, name="scan.pdf", pages=1):
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / name
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def test_ocr_disabled_message_says_switched_off_not_completed(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    path = _blank_pdf(tmp_path)
    doc = pymupdf.open(str(path))
    try:
        body, warning = PdfEngine()._render_scanned_pdf(
            path, doc, {"pdf_ocr_fallback": False}
        )
    finally:
        doc.close()

    text = "\n".join(body)
    assert "switched off" in text
    assert "OCR completed" not in text
    assert warning is not None and "OCR disabled" in warning


def test_ocr_unavailable_message_says_unavailable_not_completed(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    path = _blank_pdf(tmp_path)
    monkeypatch.setattr(pdf_engine_module.shutil, "which", lambda name: None)

    doc = pymupdf.open(str(path))
    try:
        body, warning = PdfEngine()._render_scanned_pdf(
            path, doc, {"pdf_ocr_fallback": True}
        )
    finally:
        doc.close()

    text = "\n".join(body)
    assert "OCR is unavailable" in text
    assert "OCR completed" not in text
    assert warning is not None and "OCR unavailable" in warning


def test_partial_page_ocr_failure_is_reported_per_page_others_still_succeed(
    tmp_path, monkeypatch
):
    """One page's OCR raising must be reported as a failure for that page
    specifically (not "completed but empty"), must not stop other pages
    from being processed, AND must surface as an overall warning - a
    partially-failed OCR run is not a clean Success just because some other
    page happened to find text."""
    pymupdf = pytest.importorskip("pymupdf")
    path = _blank_pdf(tmp_path, pages=2)
    monkeypatch.setattr(
        pdf_engine_module.shutil, "which", lambda name: "C:/fake/tesseract.exe"
    )

    fake_pytesseract = types.ModuleType("pytesseract")
    call_count = {"n": 0}

    def image_to_string(img_path, lang="eng"):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("decoder crashed on this page")
        return "page two text"

    fake_pytesseract.image_to_string = image_to_string
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    doc = pymupdf.open(str(path))
    try:
        body, warning = PdfEngine()._render_scanned_pdf(
            path, doc, {"pdf_ocr_fallback": True}
        )
    finally:
        doc.close()

    text = "\n".join(body)
    assert "OCR failed" in text, "the failing page's failure must be reported"
    assert "page two text" in text, "the second page must still succeed"
    assert warning is not None, (
        "a page-level OCR exception must surface as a warning even when "
        "another page succeeded - it must not be masked into a plain Success"
    )
    assert "partially failed" in warning
    assert "1 of 2" in warning


def test_all_pages_ocr_failure_reports_failed_on_all(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    path = _blank_pdf(tmp_path, pages=2)
    monkeypatch.setattr(
        pdf_engine_module.shutil, "which", lambda name: "C:/fake/tesseract.exe"
    )

    fake_pytesseract = types.ModuleType("pytesseract")

    def image_to_string(img_path, lang="eng"):
        raise RuntimeError("decoder crashed")

    fake_pytesseract.image_to_string = image_to_string
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    doc = pymupdf.open(str(path))
    try:
        body, warning = PdfEngine()._render_scanned_pdf(
            path, doc, {"pdf_ocr_fallback": True}
        )
    finally:
        doc.close()

    assert warning is not None
    assert "failed on all 2 page" in warning


def test_ocr_genuinely_ran_and_found_nothing_is_a_warning(tmp_path, monkeypatch):
    """Contrast case: OCR actually executing and finding nothing IS a
    legitimate "completed but empty" warning - distinct from disabled or
    unavailable."""
    pymupdf = pytest.importorskip("pymupdf")
    path = _blank_pdf(tmp_path)
    monkeypatch.setattr(
        pdf_engine_module.shutil, "which", lambda name: "C:/fake/tesseract.exe"
    )

    fake_pytesseract = types.ModuleType("pytesseract")
    fake_pytesseract.image_to_string = lambda img_path, lang="eng": ""
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)

    doc = pymupdf.open(str(path))
    try:
        body, warning = PdfEngine()._render_scanned_pdf(
            path, doc, {"pdf_ocr_fallback": True}
        )
    finally:
        doc.close()

    assert warning is not None
    assert "no readable text was found" in warning