"""Legacy .xls / .doc / .ppt (and the .doc files that are really RTF)."""

from __future__ import annotations

import datetime as dt

import pytest
from typer.testing import CliRunner

from doc2md.cli.main import app
from doc2md.core.converter import Converter
from doc2md.core.router import FileKind, detect
from doc2md.engine.doc_engine import DocEngine
from doc2md.engine.ppt_engine import PptEngine
from doc2md.engine.rtf import rtf_to_text
from tests.legacy_builders import build_cfb, build_doc, build_ppt

olefile = pytest.importorskip("olefile")
runner = CliRunner()


# ------------------------------------------------------------------------ .doc


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_doc_text_headings_and_lists(tmp_path):
    path = _write(
        tmp_path,
        "รายงาน.doc",
        build_doc([
            ("หัวข้อใหญ่", "para", {"istd": 1}),
            ("ย่อหน้าธรรมดา ภาษาไทย", "para", {}),
            ("รายการแรก", "para", {"ilfo": 1}),
            ("รายการย่อย", "para", {"ilfo": 1, "ilvl": 1}),
        ]),
    )

    output = DocEngine().convert(path, {})

    assert "# รายงาน.doc" in output
    assert "# หัวข้อใหญ่" in output
    assert "ย่อหน้าธรรมดา ภาษาไทย" in output
    assert "- รายการแรก" in output
    assert "  - รายการย่อย" in output


def test_doc_table_keeps_empty_cells_in_their_columns(tmp_path):
    path = _write(
        tmp_path,
        "t.doc",
        build_doc([
            ("ชื่อ", "cell", {}), ("จำนวน", "cell", {}), ("หมายเหตุ", "cell", {}), ("", "rowend", {}),
            ("น้ำ", "cell", {}), ("", "cell", {}), ("ขวด", "cell", {}), ("", "rowend", {}),
            ("ข้าว", "cell", {}), ("5", "cell", {}), ("", "cell", {}), ("", "rowend", {}),
            ("หลังตาราง", "para", {}),
        ]),
    )

    output = DocEngine().convert(path, {})

    assert "| ชื่อ | จำนวน | หมายเหตุ |" in output
    assert "| น้ำ |  | ขวด |" in output
    assert "| ข้าว | 5 |  |" in output
    assert output.index("หลังตาราง") > output.index("| ข้าว")


def test_doc_compressed_text_pieces(tmp_path):
    path = _write(tmp_path, "c.doc", build_doc([("Plain ASCII text", "para", {})], compressed=True))

    assert "Plain ASCII text" in DocEngine().convert(path, {})


def test_doc_field_codes_are_dropped_and_results_kept(tmp_path):
    field = "\x13 HYPERLINK \"http://x\" \x14ลิงก์ที่มองเห็น\x15 ต่อท้าย"
    path = _write(tmp_path, "f.doc", build_doc([(field, "para", {})]))

    output = DocEngine().convert(path, {})

    assert "ลิงก์ที่มองเห็น ต่อท้าย" in output
    assert "HYPERLINK" not in output


def test_a_doc_with_only_pictures_says_so(tmp_path):
    path = _write(tmp_path, "scan.doc", build_doc([("\x01", "para", {})]))

    with pytest.raises(Exception, match="only 1 picture"):
        DocEngine().convert(path, {})


def test_a_non_word_file_named_doc_is_rejected_clearly(tmp_path):
    path = _write(tmp_path, "x.doc", b"just some text, not a Word file")

    with pytest.raises(Exception, match="Not a Word binary document"):
        DocEngine().convert(path, {})


def test_an_ole_file_without_a_word_stream_is_rejected(tmp_path):
    path = _write(tmp_path, "x.doc", build_cfb({"Other": b"data"}))

    with pytest.raises(Exception, match="no WordDocument stream"):
        DocEngine().convert(path, {})


def test_rtf_saved_as_doc_is_converted_through_the_converter(tmp_path):
    thai = "สวัสดีชาวโลก"
    escaped = "".join(f"\\'{byte:02x}" for byte in thai.encode("cp874"))
    rtf = "{\\rtf1\\ansi\\ansicpg874{\\fonttbl{\\f0 Tahoma;}}\\pard " + escaped + "\\par second line\\par}"
    path = _write(tmp_path, "r.doc", rtf.encode("latin-1"))

    result = Converter(timeout=30).convert_file(path)

    assert result.success, result.error
    assert thai in result.markdown
    assert "second line" in result.markdown
    assert "Tahoma" not in result.markdown


def test_rtf_unicode_escapes_and_skipped_groups():
    text = rtf_to_text(b"{\\rtf1{\\info{\\title hidden}}\\u3585?\\u3586? tail}")

    assert text == "กข tail"


def test_router_sends_doc_by_extension_and_sniffs_ole(tmp_path):
    path = _write(tmp_path, "x.doc", build_doc([("a", "para", {})]))

    assert detect(path).kind is FileKind.DOC
    assert detect(_write(tmp_path, "y.xls", build_cfb({"Workbook": b"x"}))).kind is FileKind.XLSX
    assert detect(_write(tmp_path, "z.ppt", build_cfb({"x": b"y"}))).kind is FileKind.PPT


def test_a_docx_renamed_to_doc_still_converts(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("real docx content")
    path = tmp_path / "renamed.doc"
    document.save(path)

    result = Converter(timeout=30).convert_file(path)

    assert result.success, result.error
    assert result.engine == "docx"
    assert "real docx content" in result.markdown


# ------------------------------------------------------------------------ .ppt


def test_ppt_slides_in_order_with_titles_bullets_and_text_boxes(tmp_path):
    path = _write(
        tmp_path,
        "สไลด์.ppt",
        build_ppt([
            ("หัวข้อแรก", ["ข้อหนึ่ง", "ข้อสอง"], ["กล่องข้อความ"]),
            ("Second slide", [], []),
        ]),
    )

    output = PptEngine().convert(path, {})

    assert output.index("## Slide 1: หัวข้อแรก") < output.index("## Slide 2: Second slide")
    assert "- ข้อหนึ่ง" in output
    assert "- ข้อสอง" in output
    assert "- กล่องข้อความ" in output


def test_ppt_an_incremental_save_shows_the_new_slide_not_the_old_one(tmp_path):
    path = _write(
        tmp_path,
        "e.ppt",
        build_ppt(
            [("One", [], ["old text"]), ("Two", [], ["also old"])],
            edit_slide=(1, ["replacement text"]),
        ),
    )

    output = PptEngine().convert(path, {})

    assert "replacement text" in output
    assert "also old" not in output
    assert "old text" in output  # slide 1 was not edited


def test_a_non_powerpoint_ole_file_is_rejected(tmp_path):
    path = _write(tmp_path, "x.ppt", build_cfb({"Other": b"data"}))

    with pytest.raises(Exception, match="Not a PowerPoint presentation"):
        PptEngine().convert(path, {})


# ------------------------------------------------------------------------ .xls


def _xls(tmp_path):
    xlwt = pytest.importorskip("xlwt")
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("ข้อมูล")
    date_style = xlwt.easyxf(num_format_str="YYYY-MM-DD")
    percent_style = xlwt.easyxf(num_format_str="0%")
    sheet.write_merge(0, 0, 0, 3, "รายงานประจำเดือน")
    for column, label in enumerate(("ลำดับ", "ชื่อ", "วันที่", "สัดส่วน")):
        sheet.write(1, column, label)
    sheet.write(2, 0, 1)
    sheet.write(2, 1, "สมชาย")
    sheet.write(2, 2, dt.datetime(2026, 8, 17), date_style)
    sheet.write(2, 3, 0.256, percent_style)
    hidden = book.add_sheet("ซ่อน")
    hidden.write(0, 0, "archive")
    hidden.write(0, 1, "x")
    hidden.write(0, 2, "y")
    hidden.visibility = 1
    path = tmp_path / "ข้อมูล.xls"
    book.save(str(path))
    return path


def test_xls_values_dates_percentages_and_title(tmp_path):
    path = _xls(tmp_path)

    result = Converter(timeout=30).convert_file(path)

    assert result.success, result.error
    assert "รายงานประจำเดือน\n" in result.markdown
    assert "| ลำดับ | ชื่อ | วันที่ | สัดส่วน |" in result.markdown
    assert "| 1 | สมชาย | 2026-08-17 | 26% |" in result.markdown


def test_xls_hidden_sheets_are_skipped_with_a_note_and_can_be_included(tmp_path):
    path = _xls(tmp_path)

    plain = Converter(timeout=30).convert_file(path)
    full = Converter(timeout=30, options={"include_hidden_sheets": True}).convert_file(path)

    assert "archive" not in plain.markdown
    assert "1 hidden sheet(s) were not converted" in plain.markdown
    assert "archive" in full.markdown


def test_a_corrupt_xls_fails_with_a_reason(tmp_path):
    path = _write(tmp_path, "bad.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"garbage" * 100)

    result = Converter(timeout=30).convert_file(path)

    assert not result.success
    assert result.error


def test_an_html_page_saved_as_xls_converts_as_html(tmp_path):
    path = _write(
        tmp_path, "report.xls",
        "<html><body><table><tr><th>ก</th><th>ข</th></tr><tr><td>1</td><td>2</td></tr></table></body></html>".encode(),
    )

    result = Converter(timeout=30).convert_file(path)

    assert result.success, result.error
    assert "| ก | ข |" in result.markdown


def test_html_without_a_title_does_not_crash(tmp_path):
    path = _write(tmp_path, "t.html", b"<html><body><p>no title here</p></body></html>")

    result = Converter(timeout=30).convert_file(path)

    assert result.success, result.error
    assert "no title here" in result.markdown


def test_cli_converts_legacy_files_found_in_a_folder(tmp_path):
    _write(tmp_path, "a.doc", build_doc([("hello legacy", "para", {})]))
    _write(tmp_path, "b.ppt", build_ppt([("Only slide", [], [])]))
    _xls(tmp_path)

    result = runner.invoke(app, ["convert", str(tmp_path), "--stdout"])

    assert result.exit_code == 0, result.output
    assert "hello legacy" in result.output
    assert "Only slide" in result.output
    assert "สมชาย" in result.output
