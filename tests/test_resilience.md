# test_resilience.py

```python
import tempfile
from pathlib import Path

import pytest

from doc2md.core.converter import Converter
from doc2md.core.encoding import decode_bytes, read_text_smart
from doc2md.engine import get_engine
from doc2md.core.router import FileKind


def test_tis620_thai_decoding_fallback(tmp_path):
    thai = "สวัสดีชาวโลก การเข้ารหัสภาษาไทยต้องปลอดภัย " * 10
    p = tmp_path / "thai.txt"
    p.write_bytes(thai.encode("cp874"))
    text = read_text_smart(p)
    assert "สวัสดีชาวโลก" in text


def test_decode_bytes_prefers_strict_utf8_then_fallback():
    assert decode_bytes("ok".encode("utf-8")) == "ok"
    raw = "แล้วพบกันใหม่".encode("cp874")
    assert "แล้วพบกันใหม่" in decode_bytes(raw)


def test_large_csv_bypasses_table_and_summarizes(tmp_path):
    p = tmp_path / "huge.csv"
    rows = ["idx,name,value"] + [f'{i},item{i},"{i * 7}"' for i in range(20_000)]
    p.write_text("\n".join(rows), encoding="utf-8")
    result = Converter(timeout=30, options={"max_rows": 10_000, "sample_rows": 20}).convert_file(p)
    assert result.success
    assert "Truncated Summary" in result.markdown
    assert len(result.markdown) < 5_000


def test_ocr_temp_artifacts_cleaned_up(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    img = tmp_path / "scan.png"
    Image.new("RGB", (40, 40), "white").save(img)

    temp_root = Path(tempfile.gettempdir())
    before = set(temp_root.glob("doc2md_ocr_*"))
    get_engine(FileKind.IMAGE).convert(img, {})
    after = set(temp_root.glob("doc2md_ocr_*"))
    assert not (after - before)


def test_truncated_real_pdf_header_with_junk(tmp_path, simple_pdf):
    data = simple_pdf.read_bytes()
    cut = len(data) // 3
    broken = tmp_path / "truncated.pdf"
    broken.write_bytes(data[:cut])
    result = Converter().convert_file(broken)
    assert not result.success
    assert result.error
```
