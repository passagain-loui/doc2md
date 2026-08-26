import json

from doc2md.core.router import FileKind, detect, guess_language


def test_pdf_magic_bytes(tmp_path):
    p = tmp_path / "doc.pdf"
    p.write_bytes(b"%PDF-1.7\n%junk")
    assert detect(p).kind == FileKind.PDF
    assert detect(p).confidence == "magic"


def test_png_and_jpeg_magic(tmp_path):
    png = tmp_path / "img.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    jpg = tmp_path / "img.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    assert detect(png).kind == FileKind.IMAGE
    assert detect(jpg).mime == "image/jpeg"


def test_ooxml_zip_sniffing(simple_docx, simple_xlsx, simple_pptx):
    assert detect(simple_docx).kind == FileKind.DOCX
    assert detect(simple_xlsx).kind == FileKind.XLSX
    assert detect(simple_pptx).kind == FileKind.PPTX


def test_html_content_heuristic(tmp_path):
    p = tmp_path / "page.binx"
    p.write_text("<!DOCTYPE html><html><body>hi</body></html>", encoding="utf-8")
    d = detect(p)
    assert d.kind == FileKind.HTML
    assert d.confidence == "heuristic"


def test_eml_header_heuristic(tmp_path):
    p = tmp_path / "message.dat"
    p.write_text(
        "From: a@b.c\r\nTo: x@y.z\r\nSubject: hi\r\n\r\nbody\r\n", encoding="utf-8"
    )
    assert detect(p).kind == FileKind.EML


def test_json_heuristic(tmp_path):
    p = tmp_path / "data.jsonx"
    p.write_text(json.dumps({"k": [1, 2, 3]}), encoding="utf-8")
    assert detect(p).kind == FileKind.JSON


def test_extension_fallback_for_code(tmp_path):
    p = tmp_path / "script.xyzpy"
    p.write_text("print(1)\n", encoding="utf-8")
    assert detect(p).kind == FileKind.UNKNOWN


def test_known_code_extension(tmp_path):
    p = tmp_path / "app.py"
    p.write_text("print(1)\n", encoding="utf-8")
    d = detect(p)
    assert d.kind == FileKind.CODE
    assert guess_language(p) == "python"


def test_unknown_binary(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(bytes(range(256)) * 8)
    assert detect(p).kind == FileKind.UNKNOWN


def test_missing_file_is_unknown(tmp_path):
    assert not detect(tmp_path / "nope.pdf").is_known
