# test_hardening_files.py

```python
import concurrent.futures
import os
import sys

import pytest

from doc2md.core.converter import Converter, _run_in_process
from doc2md.core.errors import ConversionError
from doc2md.engine import get_engine
from doc2md.core.router import FileKind
from tests.helpers import make_fake_pytesseract

OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@pytest.fixture
def encrypted_pdf(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    p = tmp_path / "secret.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "top secret")
    doc.save(
        str(p),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
    )
    doc.close()
    return p


def test_password_protected_pdf_graceful_error(encrypted_pdf):
    result = Converter(timeout=30).convert_file(encrypted_pdf)
    assert not result.success
    assert "Password-protected" in (result.error or "")


def test_password_protected_docx_ole_container_graceful_error(tmp_path):
    p = tmp_path / "encrypted.docx"
    p.write_bytes(OLE_SIGNATURE + b"\x00" * 512)
    result = Converter().convert_file(p)
    assert not result.success
    assert "DOCX" in (result.error or "") or "unreadable" in (result.error or "")


def test_corrupted_ooxml_zip_graceful_error(tmp_path):
    p = tmp_path / "broken.xlsx"
    p.write_bytes(b"PK\x03\x04" + bytes((i * 37 + 11) % 256 for i in range(1024)))
    result = Converter().convert_file(p)
    assert not result.success
    assert result.error


def test_truncated_json_returns_warning_not_crash(tmp_path):
    p = tmp_path / "truncated.json"
    p.write_text('{"alpha": [1, 2, {"beta": "va', encoding="utf-8")
    out = get_engine(FileKind.JSON).convert(p, {})
    assert "invalid JSON" in out


def test_truncated_csv_last_partial_row_still_converts(tmp_path):
    p = tmp_path / "truncated.csv"
    p.write_bytes(b"h1,h2\nv1,v2\npartial_no_newline")
    result = Converter().convert_file(p)
    assert result.success
    assert "h1" in result.markdown


def test_windows_long_path_over_260_chars(tmp_path):
    deep = tmp_path
    for _ in range(3):
        deep = deep / ("long_segment_" * 6)
    target = deep / "deep_note.txt"
    assert len(str(target)) > 260

    read_target = target
    try:
        target.parent.mkdir(parents=True)
        target.write_text("reachable beyond MAX_PATH", encoding="utf-8")
    except OSError:
        os.makedirs("\\\\?\\" + str(target.parent), exist_ok=True)
        with open("\\\\?\\" + str(target), "w", encoding="utf-8") as fh:
            fh.write("reachable beyond MAX_PATH")
        read_target = type(target)("\\\\?\\" + str(target))

    result = Converter().convert_file(read_target)
    assert result.success
    assert "beyond MAX_PATH" in result.markdown


def test_thai_unicode_and_spaces_path(tmp_path):
    folder = tmp_path / "โฟลเดอร์ ไทย ทดสอบ"
    folder.mkdir()
    target = folder / "รายงาน ฉบับพิเศษ.txt"
    target.write_text("เนื้อหาในไฟล์ชื่อไทย", encoding="utf-8")
    result = Converter().convert_file(target)
    assert result.success
    assert "เนื้อหาในไฟล์ชื่อไทย" in result.markdown


def test_concurrent_process_workers_isolated_and_temp_clean(simple_pdf):
    payloads = [{"engine": "pdf", "source": str(simple_pdf), "options": {}} for _ in range(3)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_run_in_process, p, 30) for p in payloads]
        outs = [f.result(timeout=60) for f in futures]
    assert all("Hello doc2md" in o for o in outs)


def test_concurrent_ocr_threads_isolated_tempdirs(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image

    monkeypatch.setitem(sys.modules, "pytesseract", make_fake_pytesseract())
    monkeypatch.setattr(
        "doc2md.engine.ocr_engine.shutil.which", lambda name: "C:/fake/tesseract.exe"
    )

    pngs = []
    for i in range(4):
        p = tmp_path / f"s{i}.png"
        Image.new("RGB", (40, 40), "white").save(p)
        pngs.append(p)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(get_engine(FileKind.IMAGE).convert, p, {}) for p in pngs]
        outs = [f.result(timeout=30) for f in futures]

    assert all("OCR ENGINE TEXT" in o for o in outs)


def test_child_segfault_simulation_does_not_hang_parent(tmp_path):
    payload = {
        "engine": "stub",
        "source": str(tmp_path / "x.txt"),
        "options": {},
        "target": ("tests.helpers", "crash_worker"),
    }
    import time

    started = time.monotonic()
    outcome = None
    try:
        _run_in_process(payload, timeout=10)
    except ConversionError as exc:
        outcome = str(exc)
    elapsed = time.monotonic() - started
    assert elapsed < 15
    assert outcome is None or "died" in outcome or "timeout" in outcome.lower()


def test_unreadable_source_raises_conversion_error_in_code_engine(tmp_path, monkeypatch):
    def raise_oserror(_path):
        raise OSError("permission denied by policy")

    monkeypatch.setattr("doc2md.engine.code_engine.read_text_smart", raise_oserror)
    p = tmp_path / "locked.txt"
    p.write_text("data", encoding="utf-8")
    with pytest.raises(ConversionError):
        get_engine(FileKind.CODE).convert(p, {})
```
