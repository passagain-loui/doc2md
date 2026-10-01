"""How spreadsheet content is presented: titles, dates, percentages, hidden sheets."""

from __future__ import annotations

import datetime as dt

import openpyxl
import pytest
from typer.testing import CliRunner

from doc2md.cli.main import app
from doc2md.engine.excel_engine import ExcelEngine, format_cell_value

runner = CliRunner()


def _convert(path, **options):
    return ExcelEngine().convert(path, options)


def test_a_title_row_is_text_not_the_table_header(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet["A1"] = "Internal Audit Result Report "
    sheet.append(["No.", "Ref", "Department", "Result"])
    sheet.append([1, "CAR26/01", "Customer Service ", "Minor"])
    path = tmp_path / "t.xlsx"
    workbook.save(path)

    output = _convert(path)

    assert "Internal Audit Result Report\n" in output
    assert "| No. | Ref | Department | Result |" in output
    assert "col2" not in output
    assert "| 1 | CAR26/01 | Customer Service | Minor |" in output


def test_a_sparse_two_value_row_is_left_as_the_header(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Name", "Value"])
    sheet.append(["a", 1])
    path = tmp_path / "t.xlsx"
    workbook.save(path)

    assert "| Name | Value |" in _convert(path)


def test_midnight_datetimes_are_plain_dates(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["a", "b", "c"])
    sheet.append([dt.datetime(2026, 8, 17), dt.datetime(2026, 8, 17, 13, 30, 5), 1])
    path = tmp_path / "t.xlsx"
    workbook.save(path)

    output = _convert(path)

    assert "2026-08-17 |" in output
    assert "2026-08-17 13:30:05" in output
    assert "00:00:00" not in output


@pytest.mark.parametrize(
    ("value", "number_format", "expected"),
    [
        (-0.1724137931034483, "0%", "-17%"),
        (0.256, "0.0%", "25.6%"),
        (3.0, "General", "3"),
        (0.1 + 0.2, "General", "0.3"),
        (12.5, "0.00", "12.50"),
        ("  padded  ", "General", "padded"),
        ("   ", "General", None),
        (7, "General", 7),
    ],
)
def test_cell_value_formatting(value, number_format, expected):
    assert format_cell_value(value, number_format) == expected


def _workbook_with_hidden_sheet(path):
    workbook = openpyxl.Workbook()
    shown = workbook.active
    shown.title = "Shown"
    shown.append(["a", "b", "c"])
    shown.append([1, 2, 3])
    secret = workbook.create_sheet("Old Archive ")
    secret.append(["x", "y", "z"])
    secret.append(["old", "data", "here"])
    secret.sheet_state = "hidden"
    workbook.save(path)


def test_hidden_sheets_are_skipped_with_a_note_naming_them(tmp_path):
    path = tmp_path / "t.xlsx"
    _workbook_with_hidden_sheet(path)

    output = _convert(path)

    assert "## Sheet: Shown" in output
    assert "old" not in output
    assert "1 hidden sheet(s) were not converted: `Old Archive`" in output


def test_include_hidden_sheets_converts_everything(tmp_path):
    path = tmp_path / "t.xlsx"
    _workbook_with_hidden_sheet(path)

    output = _convert(path, include_hidden_sheets=True)

    assert "## Sheet: Old Archive" in output
    assert "hidden sheet(s) were not converted" not in output


def test_cli_include_hidden_flag(tmp_path):
    path = tmp_path / "t.xlsx"
    _workbook_with_hidden_sheet(path)

    plain = runner.invoke(app, ["convert", str(path), "--stdout"])
    full = runner.invoke(app, ["convert", str(path), "--stdout", "--include-hidden"])

    assert "Old Archive" in plain.output  # named in the note only
    assert "| old | data | here |" not in plain.output
    assert "| old | data | here |" in full.output
