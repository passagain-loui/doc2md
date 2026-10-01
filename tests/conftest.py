import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import pymupdf


@pytest.fixture
def simple_pdf(tmp_path):
    path = tmp_path / "simple.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello doc2md from PDF")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def simple_docx(tmp_path):
    import docx

    path = tmp_path / "simple.docx"
    d = docx.Document()
    d.add_heading("Report Title", level=1)
    d.add_paragraph("Intro paragraph with details.")
    d.add_heading("Section", level=2)
    d.add_paragraph("First item", style="List Bullet")
    table = d.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Name"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "alpha"
    table.cell(1, 1).text = "42"
    d.save(str(path))
    return path


@pytest.fixture
def simple_pptx(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches

    path = tmp_path / "simple.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = "Deck Title"
    bullets = slide.shapes.add_textbox(Inches(1), Inches(2.2), Inches(4), Inches(2))
    tf = bullets.text_frame
    tf.text = "Point one"
    tf.add_paragraph().text = "Point two"
    prs.save(str(path))
    return path


@pytest.fixture
def simple_xlsx(tmp_path):
    import openpyxl

    path = tmp_path / "simple.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["col_a", "col_b"])
    ws.append([1, "x|y"])
    ws.append([2, None])
    wb.save(str(path))
    return path


# --- Thai-language fixtures --------------------------------------------------
#
# Thai is the hard case for every stage of the pipeline: the text layer has to
# round-trip combining vowel/tone marks, tables must not skew when cells have
# different visual widths, and paths themselves are non-ASCII. These fixtures
# build real documents so the tests exercise the actual libraries rather than
# a mock of them.

THAI_FONT_CANDIDATES = (
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/leelawui.ttf",
    "C:/Windows/Fonts/LeelawUI.ttf",
    "C:/Windows/Fonts/browallia.ttf",
    "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
)

THAI_TABLE = [
    ["รายการ", "จำนวน", "ราคา (บาท)"],
    ["เครื่องวัดความดันโลหิต", "12", "45,000"],
    ["ชุดตรวจภูมิคุ้มกัน", "300", "9,900"],
]


@pytest.fixture(scope="session")
def thai_font():
    """Path to a system font with Thai coverage, or skip."""
    for candidate in THAI_FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    pytest.skip("no Thai-capable font available on this machine")


@pytest.fixture
def thai_pdf(tmp_path, thai_font):
    """A Thai PDF with a heading and a ruled three-column table."""
    path = tmp_path / "รายงานประจำปี ๒๕๖๗.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(
        (60, 70), "รายงานสรุปผลการดำเนินงาน",
        fontname="TH", fontfile=thai_font, fontsize=15,
    )
    x0, y0, cell_w, row_h = 60, 100, 160, 26
    for row_index, row in enumerate(THAI_TABLE):
        for col_index, cell in enumerate(row):
            x, y = x0 + col_index * cell_w, y0 + row_index * row_h
            page.draw_rect(
                pymupdf.Rect(x, y, x + cell_w, y + row_h), color=(0, 0, 0), width=0.8
            )
            page.insert_text(
                (x + 5, y + 18), cell,
                fontname="TH", fontfile=thai_font, fontsize=11,
            )
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def thai_docx(tmp_path):
    """A Thai DOCX exercising headings, nested lists, emphasis and a table."""
    import docx

    path = tmp_path / "บันทึกข้อความ ฉบับที่ ๑.docx"
    document = docx.Document()
    document.add_heading("รายงานผลการตรวจสอบ", level=1)
    document.add_heading("บทสรุปผู้บริหาร", level=2)

    paragraph = document.add_paragraph("ผลการตรวจสอบพบว่า ")
    paragraph.add_run("ครุภัณฑ์ทั้งหมดอยู่ในสภาพดี").bold = True
    paragraph.add_run(" และ ")
    paragraph.add_run("ควรบำรุงรักษาต่อเนื่อง").italic = True

    document.add_paragraph("ตรวจนับครุภัณฑ์", style="List Bullet")
    document.add_paragraph("บันทึกผลลงระบบ", style="List Bullet")
    document.add_paragraph("รายงานผู้บริหาร", style="List Number")

    table = document.add_table(rows=len(THAI_TABLE), cols=3)
    for row_index, row in enumerate(THAI_TABLE):
        for col_index, cell in enumerate(row):
            table.cell(row_index, col_index).text = cell
    document.save(str(path))
    return path


@pytest.fixture
def thai_xlsx(tmp_path):
    """A Thai workbook whose cells include a pipe and an embedded newline."""
    import openpyxl

    path = tmp_path / "งบประมาณ ปี ๒๕๖๗.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "งบประมาณ"
    for row in THAI_TABLE:
        sheet.append(row)
    sheet.append(["หมายเหตุ | สำคัญ", "รวม\nทั้งสิ้น", None])
    workbook.save(str(path))
    return path


@pytest.fixture
def thai_pptx(tmp_path):
    """A Thai deck with a title, two bullet levels and a table."""
    from pptx import Presentation
    from pptx.util import Inches

    path = tmp_path / "นำเสนอผลงาน.pptx"
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "แผนการดำเนินงาน"

    body = slide.placeholders[1].text_frame
    body.text = "ขั้นตอนที่หนึ่ง"
    nested = body.add_paragraph()
    nested.text = "รายละเอียดย่อย"
    nested.level = 1

    table_slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    shape = table_slide.shapes.add_table(
        len(THAI_TABLE), 3, Inches(0.5), Inches(1.5), Inches(9), Inches(2)
    )
    for row_index, row in enumerate(THAI_TABLE):
        for col_index, cell in enumerate(row):
            shape.table.cell(row_index, col_index).text = cell
    presentation.save(str(path))
    return path


@pytest.fixture
def thai_image(tmp_path, thai_font):
    """A PNG containing rendered Thai text (for the OCR path)."""
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path / "สแกนเอกสาร.png"
    image = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(thai_font, 34)
    except OSError:  # pragma: no cover - font present but unreadable
        pytest.skip("Thai font cannot be loaded by Pillow")
    draw.text((20, 50), "ใบเสร็จรับเงิน เลขที่ 12345", fill="black", font=font)
    image.save(str(path))
    return path


@pytest.fixture(autouse=True)
def _isolated_tesseract_lookup(monkeypatch, tmp_path_factory):
    """Tests must not depend on, or change, a Tesseract installed on the dev machine."""
    from doc2md.core import ocr_setup

    monkeypatch.setattr(ocr_setup, "KNOWN_LOCATIONS", [])
    monkeypatch.setattr(ocr_setup, "user_tessdata_dir", lambda: tmp_path_factory.mktemp("tessdata"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setenv("DOC2MD_NO_TESSERACT_SEARCH", "1")
