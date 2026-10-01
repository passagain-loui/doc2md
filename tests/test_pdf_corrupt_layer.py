"""A PDF whose text layer is mis-encoded Thai is read by OCR instead, or flagged."""

from __future__ import annotations

import pymupdf
import pytest

from doc2md.engine import pdf_engine
from doc2md.engine.pdf_engine import PdfEngine

GARBLED = "แจ งสถานการณ น้ำท!วมในเขตพื้นที่กรุงเทพฯ ผ!านมา ต!อไป ท!วมขัง " * 4
CLEAN = "ขอรับรองว่าบริษัทนี้ได้จดทะเบียนเป็นนิติบุคคลตามประมวลกฎหมายแพ่งและพาณิชย์ " * 4


def _pdf(path, thai_font, *pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        y = 80
        for chunk in [text[i:i + 55] for i in range(0, len(text), 55)]:
            page.insert_text((50, y), chunk, fontname="TH", fontfile=thai_font, fontsize=12)
            y += 18
    doc.save(str(path))
    doc.close()
    return path


def test_a_corrupt_page_without_ocr_is_flagged_not_passed_off_as_clean(tmp_path, thai_font):
    path = _pdf(tmp_path / "c.pdf", thai_font, GARBLED)

    output = PdfEngine().convert_structured(path, {})

    assert "mis-encoded Thai" in output.markdown
    assert "OCR is unavailable" in output.markdown or "\x00DOC2MD-WARNING" in output.markdown


def test_a_corrupt_page_is_replaced_by_ocr_when_it_is_available(tmp_path, thai_font, monkeypatch):
    pytest.importorskip("pytesseract")
    path = _pdf(tmp_path / "c.pdf", thai_font, GARBLED, CLEAN)
    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: None))
    monkeypatch.setattr(pdf_engine, "prepare_tesseract", lambda language: "tesseract")
    monkeypatch.setattr(pdf_engine, "recognize", lambda image_path, language: "ข้อความจาก OCR")

    output = PdfEngine().convert_structured(path, {})

    assert "ข้อความจาก OCR" in output.markdown
    assert "read by OCR" in output.markdown
    assert "ท!วม" not in output.markdown
    assert "ขอรับรองว่าบริษัทนี้" in output.markdown  # the clean page keeps its own text
    assert output.metrics.ocr_pages_success == 1


def test_a_clean_thai_pdf_never_triggers_the_fallback(tmp_path, thai_font, monkeypatch):
    path = _pdf(tmp_path / "ok.pdf", thai_font, CLEAN)
    monkeypatch.setattr(
        pdf_engine, "recognize", lambda *args: pytest.fail("OCR must not run for a clean text layer")
    )

    output = PdfEngine().convert(path, {})

    assert "ขอรับรองว่าบริษัทนี้" in output
    assert "mis-encoded" not in output


def test_the_fallback_respects_ocr_being_switched_off(tmp_path, thai_font):
    path = _pdf(tmp_path / "c.pdf", thai_font, GARBLED)

    output = PdfEngine().convert(path, {"pdf_ocr_fallback": False})

    assert "OCR is switched off" in output
