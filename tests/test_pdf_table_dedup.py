"""PDF table deduplication is position-based, not string matching.

Bug: removing any prose line equal to a table cell's text deleted a heading or
paragraph outside the table that merely read the same ("Approved"). The page
text is now rebuilt from PyMuPDF's words positioned outside every table box.

These tests build real PDFs (ruled tables drawn with PyMuPDF) and run them
through the real pdfplumber table finder.
"""

from __future__ import annotations

import pymupdf
import pytest

from doc2md.engine.pdf_engine import PdfEngine, _text_outside_tables

pytest.importorskip("pdfplumber")


def _draw_table(page, rows, x0=60, y0=300, cell_w=120, row_h=26, font=None):
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            x, y = x0 + c * cell_w, y0 + r * row_h
            page.draw_rect(pymupdf.Rect(x, y, x + cell_w, y + row_h), color=(0, 0, 0), width=0.8)
            kwargs = {"fontname": "TH", "fontfile": font} if font else {}
            page.insert_text((x + 5, y + 18), cell, fontsize=11, **kwargs)


def _make_pdf(path, prose, rows, font=None):
    doc = pymupdf.open()
    page = doc.new_page()
    kwargs = {"fontname": "TH", "fontfile": font} if font else {}
    y = 70
    for line in prose:
        page.insert_text((60, y), line, fontsize=12, **kwargs)
        y += 24
    _draw_table(page, rows, font=font)
    doc.save(str(path))
    doc.close()
    return path


def _prose_and_table(markdown: str):
    lines = markdown.splitlines()
    first_pipe = next(i for i, line in enumerate(lines) if line.startswith("|"))
    return lines[:first_pipe], lines[first_pipe:]


def test_prose_outside_table_matching_a_cell_value_is_preserved(tmp_path):
    path = _make_pdf(
        tmp_path / "dup.pdf",
        ["Introduction paragraph", "Approved"],
        [["Status", "Owner"], ["Approved", "Alice"]],
    )

    prose, table = _prose_and_table(PdfEngine().convert(path, {"pdf_tables": True}))

    assert any("Introduction" in line for line in prose)
    assert any(line.strip() == "Approved" for line in prose), (
        "a paragraph outside the table that reads like a cell must survive"
    )
    assert any("Alice" in line for line in table)


def test_cell_text_inside_the_table_is_not_repeated_in_prose(tmp_path):
    path = _make_pdf(
        tmp_path / "cells.pdf",
        ["Header line"],
        [["Item", "Qty"], ["UniqueCellValue", "42"]],
    )

    prose, table = _prose_and_table(PdfEngine().convert(path, {"pdf_tables": True}))

    assert any("Header line" in line for line in prose)
    assert not any("UniqueCellValue" in line for line in prose)
    assert any("UniqueCellValue" in line for line in table)


def test_thai_prose_outside_table_keeps_its_combining_marks(tmp_path, thai_font):
    sentence = "รายงานสรุปผลการดำเนินงานประจำปี"
    path = _make_pdf(
        tmp_path / "thai.pdf",
        [sentence],
        [["ชื่อ", "จำนวน"], ["น้ำดื่ม", "๑๒"]],
        font=thai_font,
    )

    prose, _table = _prose_and_table(PdfEngine().convert(path, {"pdf_tables": True}))

    assert sentence in "\n".join(prose)


def test_pages_without_tables_keep_the_original_text(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((60, 70), "Plain paragraph, no table on this page.", fontsize=12)
    path = tmp_path / "plain.pdf"
    doc.save(str(path))
    doc.close()

    markdown = PdfEngine().convert(path, {"pdf_tables": True})

    assert "Plain paragraph, no table on this page." in markdown
    assert not any(line.startswith("|") for line in markdown.splitlines())


def test_unusable_geometry_falls_back_to_none():
    class Boom:
        bbox = None

    assert _text_outside_tables(None, [Boom()]) is None

    class Page:
        rotation = 90

        def get_text(self, *_args):
            return []

    class Table:
        bbox = (0, 0, 10, 10)

    assert _text_outside_tables(Page(), [Table()]) is None


def test_tables_detected_is_not_measured_without_pdfplumber(tmp_path, monkeypatch):
    path = _make_pdf(tmp_path / "t.pdf", ["Some text on the page"], [["a", "b"], ["c", "d"]])
    monkeypatch.setattr("doc2md.engine.pdf_engine._pdfplumber_available", lambda: False)
    monkeypatch.setitem(__import__("sys").modules, "pdfplumber", None)

    output = PdfEngine().convert_structured(path, {"pdf_tables": True})

    assert output.metrics.tables_detected is None
