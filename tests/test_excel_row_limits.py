"""Regression tests for the XLSX/CSV row-limit bug (silent truncation).

Bug: a file well under `max_rows` (e.g. 40 data rows against the default
10,000) was silently clipped to ~25 rows with no "Truncated Summary" warning,
because the row-collection loop capped itself at `sample_rows` unconditionally
instead of only capping when the file actually exceeds `max_rows`.

These tests pin the two boundaries the fix must get right:
  1. total data rows <= max_rows -> every row is present, no warning.
  2. total data rows >  max_rows -> a bounded preview plus an explicit
     "Truncated Summary" warning.
"""

from __future__ import annotations

import pytest

from doc2md.core.router import FileKind
from doc2md.engine import get_engine


def _write_csv(path, header, n_data_rows):
    lines = [header] + [f"{i},row{i}" for i in range(n_data_rows)]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_xlsx(path, header, n_data_rows):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for i in range(n_data_rows):
        ws.append([i, f"row{i}"])
    wb.save(str(path))
    return path


@pytest.mark.parametrize("n_data_rows", [25, 26, 40])
def test_csv_under_default_max_rows_outputs_every_row(tmp_path, n_data_rows):
    p = _write_csv(tmp_path / "data.csv", "id,label", n_data_rows)
    out = get_engine(FileKind.XLSX).convert(p, {})
    assert "Truncated Summary" not in out
    assert f"row{n_data_rows - 1}" in out, f"last of {n_data_rows} rows missing"
    assert "row0" in out


@pytest.mark.parametrize("n_data_rows", [25, 26, 40])
def test_xlsx_under_default_max_rows_outputs_every_row(tmp_path, n_data_rows):
    p = _write_xlsx(tmp_path / "data.xlsx", ["id", "label"], n_data_rows)
    out = get_engine(FileKind.XLSX).convert(p, {})
    assert "Truncated Summary" not in out
    assert f"row{n_data_rows - 1}" in out, f"last of {n_data_rows} rows missing"
    assert "row0" in out


def test_csv_exactly_max_rows_is_not_truncated(tmp_path):
    """max_rows counts total physical rows including the header."""
    max_rows = 10
    n_data_rows = max_rows - 1  # header + 9 data rows = 10 total rows
    p = _write_csv(tmp_path / "exact.csv", "id,label", n_data_rows)
    out = get_engine(FileKind.XLSX).convert(p, {"max_rows": max_rows})
    assert "Truncated Summary" not in out
    assert f"row{n_data_rows - 1}" in out


def test_csv_max_rows_plus_one_triggers_truncation(tmp_path):
    max_rows = 10
    n_data_rows = max_rows  # header + 10 data rows = 11 total rows > max_rows
    p = _write_csv(tmp_path / "over.csv", "id,label", n_data_rows)
    out = get_engine(FileKind.XLSX).convert(p, {"max_rows": max_rows})
    assert "Truncated Summary" in out
    assert f"row{n_data_rows - 1}" not in out


def test_xlsx_exactly_max_rows_is_not_truncated(tmp_path):
    max_rows = 10
    n_data_rows = max_rows - 1
    p = _write_xlsx(tmp_path / "exact.xlsx", ["id", "label"], n_data_rows)
    out = get_engine(FileKind.XLSX).convert(p, {"max_rows": max_rows})
    assert "Truncated Summary" not in out
    assert f"row{n_data_rows - 1}" in out


def test_xlsx_max_rows_plus_one_triggers_truncation(tmp_path):
    max_rows = 10
    n_data_rows = max_rows
    p = _write_xlsx(tmp_path / "over.xlsx", ["id", "label"], n_data_rows)
    out = get_engine(FileKind.XLSX).convert(p, {"max_rows": max_rows})
    assert "Truncated Summary" in out
    assert f"row{n_data_rows - 1}" not in out


def test_csv_truncated_preview_respects_sample_rows_count(tmp_path):
    """When truncated, the preview must show exactly sample_rows total rows
    (header + sample_rows - 1 data rows) - not sample_rows + 1 (the old
    off-by-one) and not the untruncated full set."""
    p = _write_csv(tmp_path / "preview.csv", "id,label", 500)
    out = get_engine(FileKind.XLSX).convert(p, {"max_rows": 50, "sample_rows": 4})
    assert "Truncated Summary" in out
    assert "row0" in out and "row1" in out and "row2" in out
    assert "row3" not in out
    assert "row49" not in out