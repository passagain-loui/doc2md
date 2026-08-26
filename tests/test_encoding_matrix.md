# test_encoding_matrix.py

```python
import sys

from doc2md.core.converter import Converter
from doc2md.core.encoding import decode_bytes, read_text_smart, strip_zero_width
from doc2md.engine import get_engine
from doc2md.core.router import FileKind


def test_utf8_bom_stripped_everywhere(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbfBOM content here")
    text = read_text_smart(p)
    assert not text.startswith("\ufeff")
    assert "BOM content" in text
    result = Converter().convert_file(p)
    assert result.success
    assert "\ufeff" not in result.markdown


def test_cp874_thai_full_pipeline(tmp_path):
    thai = "การแปลงไฟล์ด้วยระบบ doc2md ต้องรองรับภาษาไทย "
    p = tmp_path / "thai_cp874.txt"
    p.write_bytes((thai * 12).encode("cp874"))
    result = Converter().convert_file(p)
    assert result.success
    assert "doc2md" in result.markdown and "ต้องรองรับภาษาไทย" in result.markdown


def test_tis620_alias_encoding_with_explicit_hint(tmp_path):
    payload = "ทดสอบมาตรฐาน TIS-620 ให้ครบถ้วนถ้วนถ้วน " * 8
    p = tmp_path / "tis.txt"
    raw = payload.encode("tis-620")
    assert raw == payload.encode("cp874")
    p.write_bytes(raw)
    text = read_text_smart(p, prefer_encodings=("tis-620", "utf-8"))
    assert "ทดสอบมาตรฐาน" in text
    assert "ครบถ้วน" in text


def test_mixed_ascii_and_cp874_tail(tmp_path):
    head = b"PLAIN ASCII HEADER LINE\n"
    tail = "ส่วนท้ายภาษาไทยข้อมูลเพียงพอสำหรับการตรวจจับ ".encode("cp874") * 10
    p = tmp_path / "mixed.log"
    p.write_bytes(head + tail)
    result = Converter().convert_file(p)
    assert result.success
    assert "PLAIN ASCII HEADER LINE" in result.markdown


def test_decode_bytes_explicit_preferred_encodings():
    raw = "กากกากาข้อมูลไทยล้วนๆ".encode("cp874")
    assert decode_bytes(raw, prefer_encodings=("cp874",)) == "กากกากาข้อมูลไทยล้วนๆ"
    assert decode_bytes(b"ascii only", prefer_encodings=("utf-32", "utf-8")) == "ascii only"


def test_decode_bytes_without_charset_normalizer_never_crashes(monkeypatch):
    monkeypatch.setitem(sys.modules, "charset_normalizer", None)
    out = decode_bytes("fallback path é".encode("utf-8"))
    assert "fallback path" in out
    out2 = decode_bytes(bytes(range(0x80, 0x100)))
    assert isinstance(out2, str)


def test_router_head_decoding_latin1_fallback(monkeypatch, tmp_path):
    from doc2md.core import router

    monkeypatch.setitem(sys.modules, "charset_normalizer", None)
    p = tmp_path / "highbytes.txt"
    p.write_bytes(b"\xe9\xe8 high bytes \xff\xfe no structure")
    detection = router.detect(p)
    assert detection.kind in (FileKind.TEXT, FileKind.UNKNOWN)


def test_strip_zero_width_utility():
    assert strip_zero_width("a\u200bb\u200ec\ufeffd\u202ae") == "abcde"
```
