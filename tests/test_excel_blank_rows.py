"""Trailing blank rows are not counted as data."""

from __future__ import annotations

from doc2md.engine.excel_engine import BLANK_RUN_LIMIT, ExcelEngine


def test_csv_trailing_blank_lines_do_not_inflate_the_row_count(tmp_path):
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n3,4\n" + ",\n" * 50, encoding="utf-8")

    output = ExcelEngine().convert_structured(path, {})

    assert output.metrics.rows_detected == 3
    assert output.metrics.rows_detected_is_exact is True


def test_xlsx_with_a_huge_blank_tail_stops_early_and_says_inexact(tmp_path):
    import openpyxl

    path = tmp_path / "t.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["h1", "h2"])
    sheet.append(["x", "y"])
    sheet.cell(row=BLANK_RUN_LIMIT + 500, column=1).value = None
    sheet["A%d" % (BLANK_RUN_LIMIT + 500)].number_format = "0.00"
    workbook.save(path)

    output = ExcelEngine().convert_structured(path, {})

    assert output.metrics.rows_detected == 2
    assert output.metrics.rows_detected_is_exact is False
