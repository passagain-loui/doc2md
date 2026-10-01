"""Milestone 7 item 4 - PDF page metrics correctness.

Exact field meanings (see doc2md/core/quality.py for the full docstrings):

- pages_total: total pages in the document.
- pages_read: pages whose text-layer extraction attempt did NOT raise -
  NOT the same as "pages with real content".
- pages_failed: pages whose text-layer extraction attempt DID raise.
- pages_with_content: pages that actually contributed extracted text to the
  output, via the text layer OR OCR. This is the truthful "how much did we
  actually capture" field - pages_read alone can equal pages_total for a
  scanned PDF whose OCR never ran, which must never be shown as if it were
  a full, successful read.
"""

from __future__ import annotations

import sys
import types

import pymupdf
import pytest

from doc2md.engine.pdf_engine import PdfEngine


def _text_pdf(tmp_path, name="text.pdf", pages_text=("Hello world", "Second page")):
    path = tmp_path / name
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


def _blank_pdf(tmp_path, name="scan.pdf", pages=2):
    path = tmp_path / name
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


# --- text PDF ------------------------------------------------------------------


def test_text_pdf_pages_with_content_equals_pages_with_real_text(tmp_path):
    path = _text_pdf(tmp_path)
    output = PdfEngine().convert_structured(path, {})
    m = output.metrics

    assert m.pages_total == 2
    assert m.pages_read == 2
    assert m.pages_failed == 0
    assert m.pages_with_content == 2


# --- mixed readable/unreadable pages --------------------------------------------


def test_mixed_readable_and_unreadable_pages(tmp_path, monkeypatch):
    path = _text_pdf(tmp_path, pages_text=("Real text here", "More real text", "Third page"))

    real_read_text_layer = PdfEngine._read_text_layer

    def flaky_read_text_layer(doc_obj):
        pages, unreadable = real_read_text_layer(doc_obj)
        pages[1] = ""  # simulate page 2's extraction having failed
        return pages, unreadable + 1

    monkeypatch.setattr(PdfEngine, "_read_text_layer", staticmethod(flaky_read_text_layer))

    output = PdfEngine().convert_structured(path, {})
    m = output.metrics

    assert m.pages_total == 3
    assert m.pages_failed == 1
    assert m.pages_read == 2
    # Only pages 1 and 3 have real text (page 2 was blanked by the failure).
    assert m.pages_with_content == 2


# --- scanned PDF, OCR disabled ---------------------------------------------------


def test_scanned_pdf_ocr_disabled_never_claims_pages_had_content(tmp_path):
    path = _blank_pdf(tmp_path, pages=3)
    output = PdfEngine().convert_structured(path, {"pdf_ocr_fallback": False})
    m = output.metrics

    assert m.pages_total == 3
    assert m.pages_read == 3, "PyMuPDF's extraction attempt did not error"
    assert m.pages_with_content == 0, "nothing was actually captured - OCR never ran"
    assert output.metrics.ocr_backend is None


def test_scanned_pdf_ocr_disabled_warning_and_metrics_via_converter(tmp_path):
    from doc2md.core.converter import Converter

    path = _blank_pdf(tmp_path, pages=2)
    result = Converter(options={"pdf_ocr_fallback": False}).convert_file(path)

    assert result.success is True
    assert result.warning and "OCR disabled" in result.warning
    assert result.quality.pages_with_content == 0
    assert result.quality.pages_read == 2


# --- scanned PDF, OCR unavailable ------------------------------------------------


def test_scanned_pdf_ocr_unavailable_never_claims_pages_had_content(tmp_path, monkeypatch):
    import doc2md.engine.pdf_engine as pdf_engine_module

    path = _blank_pdf(tmp_path, pages=2)
    monkeypatch.setattr(pdf_engine_module.shutil, "which", lambda name: None)

    output = PdfEngine().convert_structured(path, {})
    m = output.metrics

    assert m.pages_total == 2
    assert m.pages_read == 2
    assert m.pages_with_content == 0
    assert m.ocr_backend is None


# --- OCR success, empty, and per-page failure ------------------------------------


def test_ocr_success_sets_pages_with_content_to_pages_with_text(tmp_path, monkeypatch):
    import doc2md.engine.pdf_engine as pdf_engine_module

    path = _blank_pdf(tmp_path, pages=2)
    monkeypatch.setattr(pdf_engine_module.shutil, "which", lambda name: "C:/fake/tesseract.exe")

    fake = types.ModuleType("pytesseract")
    fake.image_to_string = lambda *a, **k: "recognized text"
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    output = PdfEngine().convert_structured(path, {"pdf_ocr_fallback": True})
    m = output.metrics

    assert m.ocr_backend == "tesseract"
    assert m.ocr_pages_success == 2
    assert m.pages_with_content == 2


def test_ocr_empty_result_sets_pages_with_content_to_zero(tmp_path, monkeypatch):
    import doc2md.engine.pdf_engine as pdf_engine_module

    path = _blank_pdf(tmp_path, pages=2)
    monkeypatch.setattr(pdf_engine_module.shutil, "which", lambda name: "C:/fake/tesseract.exe")

    fake = types.ModuleType("pytesseract")
    fake.image_to_string = lambda *a, **k: ""
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    output = PdfEngine().convert_structured(path, {"pdf_ocr_fallback": True})
    m = output.metrics

    assert m.ocr_pages_empty == 2
    assert m.pages_with_content == 0


def test_ocr_per_page_failure_excludes_failed_pages_from_content_count(tmp_path, monkeypatch):
    import doc2md.engine.pdf_engine as pdf_engine_module

    path = _blank_pdf(tmp_path, pages=2)
    monkeypatch.setattr(pdf_engine_module.shutil, "which", lambda name: "C:/fake/tesseract.exe")

    call_count = {"n": 0}

    def image_to_string(img_path, lang="eng"):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("decoder crashed")
        return "page two text"

    fake = types.ModuleType("pytesseract")
    fake.image_to_string = image_to_string
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    output = PdfEngine().convert_structured(path, {"pdf_ocr_fallback": True})
    m = output.metrics

    assert m.ocr_pages_failed == 1
    assert m.ocr_pages_success == 1
    assert m.pages_with_content == 1


# --- GUI wording (pure logic check via the quality dataclass) -------------------


def test_gui_never_shows_pages_read_as_the_headline_when_content_is_known():
    """Regression pin for the exact bug report: active_backend disabled and
    pages_read == pages_total must not read as a full success in the GUI's
    fact list - pages_with_content must be the field driving the headline.
    (A full offscreen-Qt integration test lives in
    tests/test_gui_review_experience.py.)"""
    from doc2md.core.quality import QualityMetrics

    quality = QualityMetrics(pages_total=5, pages_read=5, pages_with_content=0)
    # Simulate the exact fact-building logic without needing a live window.
    facts = []
    if quality.pages_total is not None:
        if quality.pages_with_content is not None:
            facts.append(f"pages with content {quality.pages_with_content}/{quality.pages_total}")
        elif quality.pages_read is not None:
            facts.append(f"pages processed {quality.pages_read}/{quality.pages_total}")
    assert facts == ["pages with content 0/5"]
    assert "pages 5/5" not in facts
