"""Milestone 1 - structured quality report.

Test-first coverage for the ``QualityMetrics``/``EngineOutput`` data model
(``doc2md/core/quality.py``) and its wiring through ``BaseEngine.convert_structured``,
``Converter.convert_file`` and the JSON report writer. Every assertion checks a
*real* measured fact (page counts, table counts, row counts, OCR outcomes) -
never a string parsed out of the rendered Markdown, per the "no guessing"
requirement: an engine that has not been migrated must report ``None``, not 0.
"""

from __future__ import annotations

import pickle
import sys
import types

import pymupdf
import pytest

from doc2md.core.converter import Converter
from doc2md.core.quality import (
    STATUS_ERROR,
    STATUS_SUCCESS,
    STATUS_WARNING,
    EngineOutput,
    QualityMetrics,
    build_report,
    status_of,
    write_report_atomic,
)
from doc2md.engine.excel_engine import ExcelEngine
from doc2md.engine.ocr_engine import OcrEngine
from doc2md.engine.pdf_engine import PdfEngine


# --- process-isolated transport ----------------------------------------------


def test_engine_output_and_metrics_survive_a_pickle_round_trip():
    """The multiprocessing Pipe pickles whatever an isolated engine returns;
    a non-picklable field here would silently break every PDF/OCR conversion."""
    metrics = QualityMetrics(pages_total=3, pages_read=2, tables_detected=1)
    output = EngineOutput(markdown="# hi", metrics=metrics)
    restored = pickle.loads(pickle.dumps(output))
    assert restored.markdown == "# hi"
    assert restored.metrics.pages_total == 3
    assert restored.metrics.tables_detected == 1


def test_pdf_conversion_through_real_process_isolation_carries_metrics(simple_pdf):
    """End-to-end through Converter: PdfEngine actually runs in a spawned
    worker process (requires_process_isolation=True), so this proves metrics
    cross the real Pipe, not just a local pickle.dumps/loads."""
    result = Converter().convert_file(simple_pdf)
    assert result.success
    assert result.quality.pages_total == 1
    assert result.quality.pages_read == 1
    assert result.quality.pages_failed == 0


def test_docx_conversion_reports_null_quality_not_zero(simple_docx):
    """DocxEngine has not been migrated to convert_structured - every field
    must be None ("not measured"), never a guessed 0."""
    result = Converter().convert_file(simple_docx)
    assert result.success
    assert result.quality.pages_total is None
    assert result.quality.tables_detected is None
    assert result.quality.rows_detected is None


# --- PDF page/table metrics ---------------------------------------------------


def _ruled_table_pdf(tmp_path, name="table.pdf"):
    path = tmp_path / name
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 50), "Report intro paragraph.")
    x0, y0, cell_w, row_h = 72, 100, 100, 24
    rows = [["Name", "Value"], ["alpha", "1"], ["beta", "2"]]
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            x, y = x0 + c * cell_w, y0 + r * row_h
            page.draw_rect(
                pymupdf.Rect(x, y, x + cell_w, y + row_h), color=(0, 0, 0), width=0.8
            )
            page.insert_text((x + 5, y + 16), cell)
    doc.save(str(path))
    doc.close()
    return path


def test_pdf_table_metrics_count_a_real_extracted_table(tmp_path):
    pytest.importorskip("pdfplumber")
    path = _ruled_table_pdf(tmp_path)
    output = PdfEngine().convert_structured(path, {"pdf_tables": True})
    assert output.metrics.pages_total == 1
    assert output.metrics.pages_read == 1
    assert output.metrics.tables_detected == 1


def test_pdf_table_metrics_are_null_when_extraction_switched_off(tmp_path):
    path = _ruled_table_pdf(tmp_path)
    output = PdfEngine().convert_structured(path, {"pdf_tables": False})
    assert output.metrics.tables_detected is None, (
        "extraction never ran - must be None, not a false '0 tables found'"
    )


def test_pdf_page_failure_metrics_reflect_real_unreadable_pages(tmp_path, monkeypatch):
    """One page whose text extraction raises must be counted in
    pages_failed/pages_read - not silently folded into a clean pages_read."""
    path = tmp_path / "two_pages.pdf"
    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_text((72, 72), "enough real text to avoid the scanned path here")
    doc.save(str(path))
    doc.close()

    real_read_text_layer = PdfEngine._read_text_layer

    def flaky_read_text_layer(doc_obj):
        pages, unreadable = real_read_text_layer(doc_obj)
        # Simulate the second page's extraction having failed, the way
        # `_read_text_layer` itself would record a real PyMuPDF exception.
        pages[1] = ""
        return pages, unreadable + 1

    monkeypatch.setattr(PdfEngine, "_read_text_layer", staticmethod(flaky_read_text_layer))

    output = PdfEngine().convert_structured(path, {})
    assert output.metrics.pages_total == 2
    assert output.metrics.pages_failed == 1
    assert output.metrics.pages_read == 1


# --- partial OCR metrics (PDF scanned path) -----------------------------------


def _blank_scanned_pdf(tmp_path, pages=2, name="scan.pdf"):
    path = tmp_path / name
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def test_pdf_scanned_ocr_metrics_report_partial_failure(tmp_path, monkeypatch):
    import doc2md.engine.pdf_engine as pdf_engine_module

    path = _blank_scanned_pdf(tmp_path, pages=2)
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

    output = PdfEngine().convert_structured(path, {"pdf_ocr_fallback": True})
    m = output.metrics
    assert m.pages_total == 2
    assert m.ocr_backend == "tesseract"
    assert m.ocr_pages_success == 1
    assert m.ocr_pages_failed == 1
    assert m.ocr_pages_empty == 0


def test_pdf_scanned_ocr_unavailable_metrics_have_no_backend(tmp_path, monkeypatch):
    import doc2md.engine.pdf_engine as pdf_engine_module

    path = _blank_scanned_pdf(tmp_path, pages=1)
    monkeypatch.setattr(pdf_engine_module.shutil, "which", lambda name: None)

    output = PdfEngine().convert_structured(path, {})
    assert output.metrics.ocr_backend is None
    assert output.metrics.pages_total == 1


def test_ocr_engine_metrics_record_success(tmp_path, monkeypatch):
    from PIL import Image

    p = tmp_path / "scan.png"
    Image.new("RGB", (40, 20), color="white").save(p)

    import doc2md.engine.ocr_engine as ocr_engine_module

    monkeypatch.setattr(ocr_engine_module.shutil, "which", lambda name: "C:/fake/tesseract.exe")

    fake = types.ModuleType("pytesseract")
    fake.image_to_string = lambda *a, **k: "some real text"
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    output = OcrEngine().convert_structured(p, {})
    assert output.metrics.ocr_backend == "tesseract"
    assert output.metrics.ocr_pages_success == 1
    assert output.metrics.ocr_pages_empty == 0


def test_ocr_engine_metrics_record_unavailable(tmp_path, monkeypatch):
    from PIL import Image
    import doc2md.engine.ocr_engine as ocr_engine_module

    p = tmp_path / "scan.png"
    Image.new("RGB", (40, 20), color="white").save(p)

    monkeypatch.setattr(ocr_engine_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        OcrEngine, "_get_rapidocr",
        lambda self: (_ for _ in ()).throw(
            ocr_engine_module.EngineUnavailableError("no backend")
        ),
    )

    output = OcrEngine().convert_structured(p, {})
    assert output.metrics.ocr_backend is None
    assert output.metrics.ocr_pages_success == 0


# --- Excel row/sheet/truncation metrics ---------------------------------------


def test_csv_metrics_under_limit_are_not_truncated(tmp_path):
    p = tmp_path / "small.csv"
    lines = ["id,label"] + [f"{i},row{i}" for i in range(10)]
    p.write_text("\n".join(lines), encoding="utf-8")

    output = ExcelEngine().convert_structured(p, {})
    assert output.metrics.sheets_detected == 1
    assert output.metrics.rows_detected == 11  # header + 10 data rows
    assert output.metrics.rows_exported == 11
    assert output.metrics.truncated is False


def test_csv_metrics_over_limit_report_truncation(tmp_path):
    p = tmp_path / "big.csv"
    lines = ["id,label"] + [f"{i},row{i}" for i in range(500)]
    p.write_text("\n".join(lines), encoding="utf-8")

    output = ExcelEngine().convert_structured(p, {"max_rows": 50, "sample_rows": 4})
    # Milestone 7 item 3: rows_detected is the REAL total (header + 500 data
    # rows), never frozen at max_rows + 1 - counting continues past the
    # retention limit without retaining the extra rows.
    assert output.metrics.rows_detected == 501
    assert output.metrics.rows_detected_is_exact is True
    assert output.metrics.rows_exported == 4
    assert output.metrics.truncated is True


def test_xlsx_metrics_count_multiple_sheets(tmp_path):
    import openpyxl

    p = tmp_path / "multi.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "One"
    ws1.append(["a", "b"])
    ws1.append([1, 2])
    ws2 = wb.create_sheet("Two")
    ws2.append(["x"])
    ws2.append([9])
    ws2.append([10])
    wb.save(str(p))

    output = ExcelEngine().convert_structured(p, {})
    assert output.metrics.sheets_detected == 2
    assert output.metrics.rows_detected == 5  # 2 rows in sheet one + 3 in sheet two
    assert output.metrics.rows_exported == 5
    assert output.metrics.truncated is False


# --- mixed batch ---------------------------------------------------------------


def test_mixed_batch_each_result_carries_its_own_quality(simple_pdf, simple_docx, tmp_path):
    txt = tmp_path / "note.txt"
    txt.write_text("plain text file", encoding="utf-8")

    results = Converter().convert_many([simple_pdf, simple_docx, txt])
    assert all(r.success for r in results)

    pdf_result, docx_result, txt_result = results
    assert pdf_result.quality.pages_total == 1
    assert docx_result.quality.pages_total is None
    assert txt_result.quality.pages_total is None


# --- status classification ------------------------------------------------------


def test_status_of_success_warning_error():
    from doc2md.core.converter import ConversionResult
    from pathlib import Path

    ok = ConversionResult(source=Path("a.txt"), success=True, markdown="x")
    warn = ConversionResult(source=Path("b.txt"), success=True, markdown="x", warning="OCR unavailable")
    err = ConversionResult(source=Path("c.txt"), success=False, error="boom")

    assert status_of(ok) == STATUS_SUCCESS
    assert status_of(warn) == STATUS_WARNING
    assert status_of(err) == STATUS_ERROR


# --- report building and atomic writing -----------------------------------------


def test_build_report_shape_for_a_pdf_conversion(simple_pdf):
    result = Converter().convert_file(simple_pdf)
    report = build_report(result, output_path=simple_pdf.with_suffix(".md"))

    assert report["status"] == STATUS_SUCCESS
    assert report["kind"] == "pdf"
    assert report["engine"] == "pdf"
    assert report["pages_total"] == 1
    assert report["pages_read"] == 1
    assert report["output"] == str(simple_pdf.with_suffix(".md"))
    assert report["warning"] is None
    assert report["error"] is None


def test_write_report_atomic_writes_valid_json(tmp_path):
    dest = tmp_path / "report.json"
    write_report_atomic([{"a": 1}, {"b": 2}], dest)

    import json

    assert json.loads(dest.read_text(encoding="utf-8")) == [{"a": 1}, {"b": 2}]
    # no leftover temp file
    leftovers = [p for p in tmp_path.iterdir() if p.name != "report.json"]
    assert leftovers == []


def test_write_report_atomic_leaves_no_partial_file_on_failure(tmp_path):
    dest = tmp_path / "report.json"
    dest.mkdir()  # force os.replace() onto a directory to fail

    with pytest.raises(OSError):
        write_report_atomic({"x": 1}, dest)

    # the temp file created for the attempt must have been cleaned up
    leftovers = [p for p in tmp_path.iterdir() if p != dest]
    assert leftovers == []


def test_write_report_atomic_overwrites_existing_report(tmp_path):
    dest = tmp_path / "report.json"
    write_report_atomic({"version": 1}, dest)
    write_report_atomic({"version": 2}, dest)

    import json

    assert json.loads(dest.read_text(encoding="utf-8")) == {"version": 2}
