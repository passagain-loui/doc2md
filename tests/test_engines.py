import json

import pytest

from doc2md.core.errors import ConversionError
from doc2md.engine import get_engine
from doc2md.core.router import FileKind


def test_code_engine_python_fence(tmp_path):
    p = tmp_path / "app.py"
    p.write_text("def main():\n    return 42\n", encoding="utf-8")
    out = get_engine(FileKind.CODE).convert(p, {})
    assert "```python" in out
    assert "def main():" in out


def test_code_engine_json_pretty_print(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"b":1,"a":[true,null]}', encoding="utf-8")
    out = get_engine(FileKind.CODE).convert(p, {})
    parsed = json.loads(out.split("```json")[1].split("```")[0])
    assert parsed == {"b": 1, "a": [True, None]}
    assert '"a"' in out and '"b"' in out


def test_code_engine_invalid_json_warns(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not valid", encoding="utf-8")
    out = get_engine(FileKind.CODE).convert(p, {})
    assert "invalid JSON" in out
    assert "{not valid" in out


def test_excel_engine_normal_table(simple_xlsx):
    out = get_engine(FileKind.XLSX).convert(simple_xlsx, {})
    assert "| col_a | col_b |" in out
    assert "| 1 | x\\|y |" in out
    assert "Truncated Summary" not in out


def test_excel_engine_truncated_summary_guard(tmp_path):
    import openpyxl

    p = tmp_path / "big.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["id", "payload"])
    for i in range(200):
        ws.append([i, "x" * 10])
    wb.save(str(p))
    out = get_engine(FileKind.XLSX).convert(p, {"max_rows": 100, "sample_rows": 5})
    assert "Truncated Summary" in out
    assert "| id | payload |" in out
    assert "| 4 " in out
    assert "| 5 " not in out.replace("Truncated", "")


def test_excel_engine_csv_streaming_limit(tmp_path):
    p = tmp_path / "wide.csv"
    lines = ["a,b"] + [f"{i},row{i}" for i in range(500)]
    p.write_text("\n".join(lines), encoding="utf-8")
    out = get_engine(FileKind.XLSX).convert(p, {"max_rows": 50, "sample_rows": 3})
    assert "Truncated Summary" in out
    assert "row2" in out
    assert "row400" not in out


def test_docx_engine_headings_lists_tables(simple_docx):
    out = get_engine(FileKind.DOCX).convert(simple_docx, {})
    assert "# Report Title" in out
    assert "## Section" in out
    assert "- First item" in out
    assert "| Name | Value |" in out
    assert "| alpha | 42 |" in out


def test_pptx_engine_slides(simple_pptx):
    out = get_engine(FileKind.PPTX).convert(simple_pptx, {})
    assert "## Slide 1" in out
    assert "Point one" in out
    assert "Point two" in out


def test_web_engine_html_structure(tmp_path):
    p = tmp_path / "page.html"
    p.write_text(
        """<html><head><title>My Page</title><style>body{color:#000}</style></head>
        <body><script>alert(1)</script><h1>Heading</h1>
        <p>Hello <a href="https://x.example">link</a></p>
        <ul><li>one</li><li>two</li></ul>
        <table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
        </body></html>""",
        encoding="utf-8",
    )
    out = get_engine(FileKind.HTML).convert(p, {})
    assert "# My Page" in out
    assert "# Heading" in out
    assert "[link](https://x.example)" in out
    assert "- one" in out
    assert "| A | B |" in out
    assert "alert(1)" not in out
    assert "color:#000" not in out


def test_web_engine_eml_utf8_thai(tmp_path):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = "sender@example.co.th"
    msg["To"] = "me@example.com"
    msg["Subject"] = "รายงานประจำวัน"
    msg.set_content("สวัสดีครับ นี่คือเนื้อหาอีเมล")
    p = tmp_path / "thai.eml"
    p.write_bytes(bytes(msg))
    out = get_engine(FileKind.EML).convert(p, {})
    assert "รายงานประจำวัน" in out
    assert "สวัสดีครับ" in out
    assert "- **From:** sender@example.co.th" in out


def test_ocr_engine_graceful_without_tesseract_or_corrupt(tmp_path):
    pytest.importorskip("PIL")
    engine = get_engine(FileKind.IMAGE)
    good = tmp_path / "blank.png"
    try:
        from PIL import Image

        Image.new("RGB", (60, 30), "white").save(good)
    except Exception:
        pytest.skip("Pillow cannot create image")
    out = engine.convert(good, {})
    assert "- **Dimensions:** 60 x 30" in out

    bad = tmp_path / "corrupt.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\nNOT_REALLY_A_PNG")
    with pytest.raises(ConversionError):
        engine.convert(bad, {})


def test_pdf_engine_extracts_text(simple_pdf):
    out = get_engine(FileKind.PDF).convert(simple_pdf, {})
    assert "Hello doc2md from PDF" in out
    assert "## Page 1" in out


def test_pdf_engine_corrupted_raises(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"%PDF-1.4\n" + b"\xde\xad\xbe\xef" * 512)
    with pytest.raises(ConversionError):
        get_engine(FileKind.PDF).convert(p, {})
