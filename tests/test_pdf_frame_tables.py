"""A page-sized "frame" table around the real tables must not duplicate the page.

pdfplumber can report the outline of a layout (a box with a divider, around the
content) as a table of its own. Rendered like any other table it repeated the
whole page inside one cell, and excluding its box hid the page's prose.
"""

from __future__ import annotations

import pymupdf
import pytest

from doc2md.engine.pdf_engine import PdfEngine, _without_frame_tables

pdfplumber = pytest.importorskip("pdfplumber")


def _framed_page_pdf(path):
    """A frame (box + vertical divider = a 1 x 2 'table') holding prose and, in
    its left half, a real 2 x 2 ruled table."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(30, 40, 560, 700), color=(0, 0, 0), width=1)
    page.draw_line((295, 40), (295, 700), width=1)
    page.insert_text((45, 80), "Frame prose line one", fontsize=12)
    page.insert_text((45, 104), "Frame prose line two", fontsize=12)
    x0, y0, cell_w, row_h = 45, 300, 120, 26
    for r, row in enumerate([["Item", "Qty"], ["UniqueCellValue", "42"]]):
        for c, cell in enumerate(row):
            x, y = x0 + c * cell_w, y0 + r * row_h
            page.draw_rect(pymupdf.Rect(x, y, x + cell_w, y + row_h), color=(0, 0, 0), width=0.8)
            page.insert_text((x + 5, y + 18), cell, fontsize=10)
    page.insert_text((320, 80), "Right half text", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def _detected(path):
    with pdfplumber.open(str(path)) as pdf:
        return pdf.pages[0].find_tables()


def test_the_synthetic_page_really_has_a_frame_table_around_an_inner_one(tmp_path):
    """Guards the other tests: if pdfplumber stopped finding the frame they would pass for nothing."""
    tables = _detected(_framed_page_pdf(tmp_path / "f.pdf"))

    assert len(tables) >= 2
    assert len(_without_frame_tables(tables)) < len(tables)


def test_the_inner_table_is_rendered_once_and_no_page_sized_cell_is_made(tmp_path):
    path = _framed_page_pdf(tmp_path / "f.pdf")

    markdown = PdfEngine().convert(path, {"pdf_tables": True})

    table_lines = [line for line in markdown.splitlines() if line.startswith("|")]
    assert sum("UniqueCellValue" in line for line in table_lines) == 1
    assert markdown.count("UniqueCellValue") == 1
    assert all(len(line) < 200 for line in table_lines), "a frame table repeated the page in one cell"
    assert markdown.count("Frame prose line one") == 1


def test_prose_inside_the_frame_but_outside_the_inner_table_is_kept(tmp_path):
    path = _framed_page_pdf(tmp_path / "f.pdf")

    markdown = PdfEngine().convert(path, {"pdf_tables": True})

    lines = markdown.splitlines()
    first_pipe = next(i for i, line in enumerate(lines) if line.startswith("|"))
    prose = "\n".join(lines[:first_pipe])
    assert "Frame prose line one" in prose
    assert "Frame prose line two" in prose
    assert "Right half text" in markdown


def test_the_table_list_for_text_and_rendering_comes_from_the_same_detection(tmp_path, monkeypatch):
    """The frame is dropped before both the rendered tables and the outside-text box are built."""
    from doc2md.engine import pdf_engine

    seen = []
    real = pdf_engine._text_outside_tables

    def spy(page, tables, buggy=frozenset()):
        seen.append(len(tables))
        return real(page, tables, buggy)

    monkeypatch.setattr(pdf_engine, "_text_outside_tables", spy)
    path = _framed_page_pdf(tmp_path / "f.pdf")
    detected = len(_detected(path))

    PdfEngine().convert(path, {"pdf_tables": True})

    assert seen and seen[0] < detected


def test_a_page_with_a_single_ordinary_table_is_unchanged(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 70), "Intro line", fontsize=12)
    for r, row in enumerate([["Item", "Qty"], ["Widget", "7"]]):
        for c, cell in enumerate(row):
            x, y = 60 + c * 120, 300 + r * 26
            page.draw_rect(pymupdf.Rect(x, y, x + 120, y + 26), color=(0, 0, 0), width=0.8)
            page.insert_text((x + 5, y + 18), cell, fontsize=11)
    path = tmp_path / "t.pdf"
    doc.save(str(path))
    doc.close()

    markdown = PdfEngine().convert(path, {"pdf_tables": True})

    assert "| Widget | 7 |" in markdown
    assert "Intro line" in markdown
