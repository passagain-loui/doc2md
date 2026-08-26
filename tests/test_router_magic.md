# test_router_magic.py

```python
import sys

import pytest

from doc2md.core.converter import Converter
from doc2md.core.router import FileKind, detect


@pytest.mark.parametrize(
    "magic,mime",
    [
        (b"BM" + b"\x00" * 40, "image/bmp"),
        (b"II*\x00" + b"\x00" * 40, "image/tiff"),
        (b"MM\x00*" + b"\x00" * 40, "image/tiff"),
    ],
)
def test_image_magic_families(tmp_path, magic, mime):
    p = tmp_path / "img"
    p.write_bytes(magic)
    detection = detect(p)
    assert detection.kind == FileKind.IMAGE
    assert detection.mime == mime
    assert detection.confidence == "magic"


def test_gif_magic(tmp_path):
    for header in (b"GIF87a", b"GIF89a"):
        p = tmp_path / "anim.gif"
        p.write_bytes(header + b"\x00" * 20)
        d = detect(p)
        assert d.kind == FileKind.IMAGE
        assert d.mime == "image/gif"


def test_generic_zip_without_ooxml_entries_is_unknown(tmp_path):
    import zipfile

    p = tmp_path / "plain.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("data/readme.txt", "just a zip")
    d = detect(p)
    assert d.kind == FileKind.UNKNOWN


def test_invalid_json_fallthrough_is_unknown(tmp_path):
    p = tmp_path / "broken.jsonx"
    p.write_text("{ definitely :: not json ]", encoding="utf-8")
    d = detect(p)
    assert d.kind == FileKind.UNKNOWN


def test_webp_riff_magic(tmp_path):
    p = tmp_path / "pic.webp"
    p.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 20)
    d = detect(p)
    assert d.kind == FileKind.IMAGE and d.mime == "image/webp"


def test_shebang_heuristic_routes_to_code(tmp_path):
    p = tmp_path / "tool.run"
    p.write_text("#!/usr/bin/env python3\nprint('hi')\n", encoding="utf-8")
    d = detect(p)
    assert d.kind == FileKind.CODE
    assert d.confidence == "heuristic"


def test_extension_only_image_and_code_kinds(tmp_path):
    webp = tmp_path / "junk.webp"
    webp.write_bytes(b"\x00\x01\x02not-a-real-webp")
    assert detect(webp).kind == FileKind.IMAGE

    yml = tmp_path / "conf.yaml"
    yml.write_text("key: value\n", encoding="utf-8")
    assert detect(yml).kind == FileKind.CODE


def test_pdf_ocr_fallback_pytesseract_import_failure(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    from PIL import Image as _  # noqa: F401  ensure Pillow stack present

    p = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(p))
    doc.close()

    monkeypatch.setattr("doc2md.engine.pdf_engine.shutil.which", lambda n: "C:/fake/tess.exe")
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    out = Converter().convert_file(p)
    assert out.success
    assert "(OCR)" not in out.markdown
    assert "No extractable text" in out.markdown


def test_pdf_ocr_fallback_generic_exception_yields_hint(tmp_path, monkeypatch):
    pymupdf = pytest.importorskip("pymupdf")
    from tests.helpers import make_fake_pytesseract

    p = tmp_path / "scan2.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(p))
    doc.close()

    failing = make_fake_pytesseract()

    def explode(path, lang="eng"):
        raise ValueError("decoder crashed")

    failing.image_to_string = explode
    monkeypatch.setitem(sys.modules, "pytesseract", failing)
    monkeypatch.setattr("doc2md.engine.pdf_engine.shutil.which", lambda n: "C:/fake/tess.exe")

    out = Converter().convert_file(p)
    assert out.success
    assert "(OCR)" not in out.markdown
    assert "No extractable text" in out.markdown
```
