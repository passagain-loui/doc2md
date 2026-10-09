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


def _pdf_with_corrupt_table(path, thai_font):
    """A corrupt-text page with a real 2x2 ruling-line table on it - the
    lines are vector drawing, not text, so they survive a broken font map
    exactly as they would on a correctly-encoded page."""
    doc = pymupdf.open()
    page = doc.new_page()
    y = 40
    for chunk in [GARBLED[i:i + 55] for i in range(0, len(GARBLED), 55)]:
        page.insert_text((50, y), chunk, fontname="TH", fontfile=thai_font, fontsize=12)
        y += 18
    x0, y0, x1, y1 = 50, 300, 250, 400
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    for p1, p2 in [
        ((x0, y0), (x1, y0)), ((x0, ym), (x1, ym)), ((x0, y1), (x1, y1)),
        ((x0, y0), (x0, y1)), ((xm, y0), (xm, y1)), ((x1, y0), (x1, y1)),
    ]:
        page.draw_line(p1, p2, width=1)
    doc.save(str(path))
    doc.close()
    return path


def test_a_corrupt_page_with_a_table_gets_cell_by_cell_ocr_not_flattened_text(
    tmp_path, thai_font, monkeypatch
):
    """A comparison table flattens into one wall of running text under plain
    whole-page OCR, with no way to tell which value belongs to which column.
    A table's ruling lines are vector drawing, untouched by the font's
    broken character map, so pdfplumber can still find the table's geometry
    on a corrupt page - each cell should be OCR'd from its own crop and the
    result rendered as a real Markdown table, not lumped into the page's
    flat OCR text."""
    pytest.importorskip("pdfplumber")
    path = _pdf_with_corrupt_table(tmp_path / "c.pdf", thai_font)

    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: None))
    monkeypatch.setattr(pdf_engine, "prepare_tesseract", lambda language: "tesseract")
    monkeypatch.setattr(pdf_engine, "recognize", lambda image_path, language: "หน้านี้ทั้งหมด")
    monkeypatch.setattr(pdf_engine, "recognize_region", lambda image, language: "ค่าในเซลล์")

    output = PdfEngine().convert_structured(path, {})

    assert "| --- |" in output.markdown, "the table must render as a real Markdown table"
    assert "ค่าในเซลล์" in output.markdown
    assert "หน้านี้ทั้งหมด" in output.markdown, "the rest of the page is still OCR'd as prose"
    assert "read by OCR" in output.markdown


def test_a_corrupt_page_falls_back_to_plain_ocr_when_pdfplumber_is_unavailable(
    tmp_path, thai_font, monkeypatch
):
    """The table-aware path must never be the only way a corrupt page can be
    read - if pdfplumber can't be imported, the page still gets the plain
    whole-page OCR it always did, never an empty or failed result."""
    path = _pdf_with_corrupt_table(tmp_path / "c.pdf", thai_font)

    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: None))
    monkeypatch.setattr(pdf_engine, "prepare_tesseract", lambda language: "tesseract")
    monkeypatch.setattr(pdf_engine, "recognize", lambda image_path, language: "ข้อความทั้งหน้า")
    monkeypatch.setattr(pdf_engine, "_pdfplumber_available", lambda: False)

    output = PdfEngine().convert_structured(path, {})

    assert "ข้อความทั้งหน้า" in output.markdown
    assert "read by OCR" in output.markdown


def _pdf_scanned_with_table(path):
    """A page with NO text layer at all (triggers the fully-scanned-PDF
    path, not the mis-encoded-text-layer reread path) but a real 2x2
    ruling-line table drawn on it - as a print brochure exported straight to
    PDF with no OCR layer would look before doc2md ever touches it."""
    doc = pymupdf.open()
    page = doc.new_page()
    x0, y0, x1, y1 = 50, 100, 250, 200
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    for p1, p2 in [
        ((x0, y0), (x1, y0)), ((x0, ym), (x1, ym)), ((x0, y1), (x1, y1)),
        ((x0, y0), (x0, y1)), ((xm, y0), (xm, y1)), ((x1, y0), (x1, y1)),
    ]:
        page.draw_line(p1, p2, width=1)
    doc.save(str(path))
    doc.close()
    return path


def test_a_fully_scanned_page_with_a_table_gets_cell_by_cell_ocr_too(tmp_path, monkeypatch):
    """Same problem as the corrupt-text-layer case, a different code path:
    a page with no text layer at all (a print brochure scanned straight to
    PDF, no OCR layer, no corrupt font to detect) goes through
    _render_scanned_pdf, not _reread_corrupt_pages - it must get the same
    table-aware OCR treatment, not just the mis-encoded-text-layer case,
    or a real scanned catalogue's spec table flattens into running text
    exactly like the mis-encoded case did before 1.4.8."""
    pytest.importorskip("pdfplumber")
    path = _pdf_scanned_with_table(tmp_path / "scan.pdf")

    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: None))
    monkeypatch.setattr(pdf_engine, "prepare_tesseract", lambda language: "tesseract")
    monkeypatch.setattr(pdf_engine, "recognize", lambda image_path, language: "ข้อความหน้านี้")
    monkeypatch.setattr(pdf_engine, "recognize_region", lambda image, language: "ค่าในเซลล์")

    output = PdfEngine().convert_structured(path, {})

    assert "| --- |" in output.markdown, "the table must render as a real Markdown table"
    assert "ค่าในเซลล์" in output.markdown
    assert "## Page 1 (OCR)" in output.markdown
