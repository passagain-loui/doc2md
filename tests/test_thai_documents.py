"""End-to-end conversion of Thai-language documents.

One test module per deliverable requirement: PDF, DOCX, XLSX, PPTX and images
all have to survive Thai content *and* Thai filenames, and the tables they
contain have to come out as real Markdown tables with stable columns.

Everything here goes through the public :class:`Converter` rather than an
engine directly, so the routing, the process-isolation boundary and the output
sanitizer are all exercised on the way.
"""

from __future__ import annotations

import re
import shutil

import pytest

from doc2md.core.converter import Converter
from doc2md.core.tables import is_table_line

THAI_RANGE = re.compile(r"[\u0e00-\u0e7f]")


def convert(path, **options):
    result = Converter(options=options).convert_file(path)
    assert result.success, result.error
    return result.markdown


def table_blocks(markdown: str) -> list[list[str]]:
    """Return each contiguous run of table lines found in *markdown*."""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if is_table_line(line):
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def assert_columns_are_stable(markdown: str) -> list[list[str]]:
    """Every row of every table must have the same number of unescaped pipes."""
    blocks = table_blocks(markdown)
    assert blocks, f"no table found in:\n{markdown}"
    for block in blocks:
        widths = {len(re.split(r"(?<!\\)\|", line.strip().strip("|"))) for line in block}
        assert len(widths) == 1, f"column drift {widths} in:\n" + "\n".join(block)
        assert len(block) >= 3, "a table needs a header, a separator and a body"
        assert set(block[1].replace("|", "").replace(" ", "")) <= {"-", ":"}
    return blocks


# --- PDF ---------------------------------------------------------------------


def test_thai_pdf_text_is_extracted_with_marks_intact(thai_pdf):
    markdown = convert(thai_pdf)

    assert "รายงานสรุปผลการดำเนินงาน" in markdown
    assert "## Page 1" in markdown


def test_thai_pdf_filename_survives_into_the_heading(thai_pdf):
    markdown = convert(thai_pdf)

    assert markdown.splitlines()[0] == f"# {thai_pdf.name}"
    assert THAI_RANGE.search(markdown.splitlines()[0])


def test_thai_pdf_table_becomes_a_markdown_table(thai_pdf):
    markdown = convert(thai_pdf)

    blocks = assert_columns_are_stable(markdown)
    joined = "\n".join("\n".join(block) for block in blocks)
    assert "รายการ" in joined
    assert "เครื่องวัดความดันโลหิต" in joined
    assert "45,000" in joined


def test_pdf_table_extraction_can_be_switched_off(thai_pdf):
    with_tables = convert(thai_pdf, pdf_tables=True)
    without_tables = convert(thai_pdf, pdf_tables=False)

    assert table_blocks(with_tables)
    assert not table_blocks(without_tables)
    # The text layer is still there either way.
    assert "รายงานสรุปผลการดำเนินงาน" in without_tables


def test_text_pdf_never_reaches_the_ocr_path(thai_pdf, monkeypatch):
    """A PDF with a text layer must not be rasterized.

    This is the automatic routing requirement: OCR is minutes of work per
    document, and running it on a text PDF is the single biggest speed
    regression this engine can have.
    """
    import doc2md.engine.pdf_engine as pdf_engine

    def explode(*_args, **_kwargs):
        raise AssertionError("OCR path taken for a text PDF")

    monkeypatch.setattr(pdf_engine.PdfEngine, "_render_scanned_pdf", explode)
    engine = pdf_engine.PdfEngine()

    assert "รายงานสรุปผลการดำเนินงาน" in engine.convert(thai_pdf, {})


def test_scanned_pdf_is_routed_to_ocr(tmp_path, monkeypatch):
    """A PDF with no text layer must be detected and sent to OCR."""
    pymupdf = pytest.importorskip("pymupdf")
    import doc2md.engine.pdf_engine as pdf_engine

    path = tmp_path / "สแกน.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()

    taken: list[str] = []

    def record(self, source, document, options):
        taken.append(options.get("ocr_lang", "default"))
        return ["## Page 1 (OCR)", "", "ใบเสร็จรับเงิน"], None

    monkeypatch.setattr(pdf_engine.PdfEngine, "_render_scanned_pdf", record)
    out = pdf_engine.PdfEngine().convert(path, {"ocr_lang": "tha+eng"})

    assert taken == ["tha+eng"]
    assert "ใบเสร็จรับเงิน" in out


def test_scanned_pdf_says_why_when_ocr_is_unavailable(tmp_path, monkeypatch):
    """A scan with no OCR backend must explain itself, not return empty text."""
    pymupdf = pytest.importorskip("pymupdf")
    import doc2md.engine.pdf_engine as pdf_engine

    path = tmp_path / "สแกนไม่มี ocr.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()

    monkeypatch.setattr(pdf_engine.shutil, "which", lambda _name: None)
    out = pdf_engine.PdfEngine().convert(path, {})

    assert "No extractable text" in out
    assert "OCR is unavailable" in out


# --- DOCX --------------------------------------------------------------------


def test_thai_docx_keeps_heading_hierarchy(thai_docx):
    markdown = convert(thai_docx)

    assert "# รายงานผลการตรวจสอบ" in markdown
    assert "## บทสรุปผู้บริหาร" in markdown


def test_thai_docx_keeps_bullets_and_numbering(thai_docx):
    markdown = convert(thai_docx)

    assert "- ตรวจนับครุภัณฑ์" in markdown
    assert "- บันทึกผลลงระบบ" in markdown
    assert "1. รายงานผู้บริหาร" in markdown


def test_thai_docx_keeps_bold_and_italic_runs(thai_docx):
    markdown = convert(thai_docx)

    assert "**ครุภัณฑ์ทั้งหมดอยู่ในสภาพดี**" in markdown
    assert "*ควรบำรุงรักษาต่อเนื่อง*" in markdown


def test_thai_docx_emphasis_markers_hug_their_text(thai_docx):
    """``** bold **`` is not bold in any CommonMark renderer.

    Word splits a styled phrase across several runs, so wrapping each run
    individually produced spans whose contents began or ended with a space -
    which renders as visible asterisks rather than bold text.
    """
    markdown = convert(thai_docx)

    expected = (
        "ผลการตรวจสอบพบว่า **ครุภัณฑ์ทั้งหมดอยู่ในสภาพดี** "
        "และ *ควรบำรุงรักษาต่อเนื่อง*"
    )
    assert expected in markdown


def test_thai_docx_table_columns_are_stable(thai_docx):
    assert_columns_are_stable(convert(thai_docx))


def test_docx_inline_styles_can_be_switched_off(thai_docx):
    markdown = convert(thai_docx, inline_styles=False)

    assert "**" not in markdown
    assert "ครุภัณฑ์ทั้งหมดอยู่ในสภาพดี" in markdown


# --- XLSX --------------------------------------------------------------------


def test_thai_xlsx_sheet_name_and_content(thai_xlsx):
    markdown = convert(thai_xlsx)

    assert "## Sheet: งบประมาณ" in markdown
    assert "เครื่องวัดความดันโลหิต" in markdown


def test_thai_xlsx_columns_are_stable_despite_ragged_rows(thai_xlsx):
    assert_columns_are_stable(convert(thai_xlsx))


def test_xlsx_cell_pipe_and_newline_do_not_break_the_grid(thai_xlsx):
    markdown = convert(thai_xlsx)

    assert r"หมายเหตุ \| สำคัญ" in markdown
    assert "รวม<br>ทั้งสิ้น" in markdown
    assert_columns_are_stable(markdown)


# --- PPTX --------------------------------------------------------------------


def test_thai_pptx_title_becomes_a_slide_heading(thai_pptx):
    markdown = convert(thai_pptx)

    assert "## Slide 1: แผนการดำเนินงาน" in markdown


def test_thai_pptx_keeps_bullet_nesting(thai_pptx):
    markdown = convert(thai_pptx)

    assert "- ขั้นตอนที่หนึ่ง" in markdown
    assert "  - รายละเอียดย่อย" in markdown


def test_thai_pptx_table_columns_are_stable(thai_pptx):
    assert_columns_are_stable(convert(thai_pptx))


# --- images ------------------------------------------------------------------


def test_thai_image_reports_metadata_even_without_ocr(thai_image):
    markdown = convert(thai_image)

    assert markdown.startswith(f"# {thai_image.name}")
    assert "- **Dimensions:** 640 x 160" in markdown


def test_image_without_an_ocr_backend_says_so(thai_image, monkeypatch):
    """Never return a bare metadata block that looks like a successful read."""
    import doc2md.engine.ocr_engine as ocr_engine

    monkeypatch.setattr(ocr_engine.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        ocr_engine.OcrEngine, "_get_rapidocr",
        lambda self: (_ for _ in ()).throw(
            ocr_engine.EngineUnavailableError(
                "neither Tesseract nor RapidOCR is available; install Tesseract OCR"
            )
        ),
    )
    out = ocr_engine.OcrEngine().convert(thai_image, {})

    assert "OCR unavailable" in out


def test_default_ocr_language_is_thai_plus_english():
    from doc2md.engine.ocr_engine import DEFAULT_OCR_LANG, OcrEngine

    assert DEFAULT_OCR_LANG == "tha+eng"
    assert OcrEngine.language({}) == "tha+eng"
    assert OcrEngine.language({"ocr_lang": ""}) == "tha+eng"
    assert OcrEngine.language({"ocr_lang": "eng"}) == "eng"


def test_missing_thai_model_falls_back_to_english(thai_image, monkeypatch):
    """A machine with English-only tessdata must still read the English half."""
    import sys
    import types

    import doc2md.engine.ocr_engine as ocr_engine

    calls: list[str] = []

    class TesseractError(RuntimeError):
        pass

    def image_to_string(_path, lang="eng"):
        calls.append(lang)
        if "tha" in lang:
            raise TesseractError("Failed loading language 'tha' from tessdata")
        return "RECEIPT 12345"

    fake = types.ModuleType("pytesseract")
    fake.image_to_string = image_to_string
    fake.TesseractError = TesseractError
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(ocr_engine.shutil, "which", lambda _name: "C:/fake/tesseract.exe")

    out = ocr_engine.OcrEngine().convert(thai_image, {"ocr_lang": "tha+eng"})

    assert calls == ["tha+eng", "eng"]
    assert "RECEIPT 12345" in out
    assert "not installed" in out


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract not installed")
def test_real_tesseract_reads_the_thai_image(thai_image):
    """Only runs where Tesseract is actually present (CI, packaging machine)."""
    markdown = convert(thai_image, ocr_lang="tha+eng")

    assert "## Extracted text" in markdown
    assert "12345" in markdown


# --- paths -------------------------------------------------------------------


@pytest.mark.parametrize(
    "folder_name",
    ["เอกสาร ทั่วไป", "งบ & ค่าใช้จ่าย (100%)", "รายงาน - ฉบับที่ ๒"],
)
def test_thai_and_symbol_paths_convert(tmp_path, folder_name):
    folder = tmp_path / folder_name
    folder.mkdir()
    target = folder / "บันทึก ข้อความ.txt"
    target.write_text("เนื้อหาภาษาไทยในไฟล์", encoding="utf-8")

    assert "เนื้อหาภาษาไทยในไฟล์" in convert(target)
