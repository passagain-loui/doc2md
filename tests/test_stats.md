# test_stats.py

```python
import pytest

from doc2md.core.converter import ConversionResult
from doc2md.core.stats import build_rows, human_size, render_table
from pathlib import Path


def make_result(name, content, size=None, tmp_path=None):
    source = (tmp_path / name) if tmp_path else Path(name)
    if tmp_path:
        source.write_bytes(b"x" * (size or 0))
    return ConversionResult(
        source=source,
        success=True,
        markdown=content,
        engine="code",
        kind="text",
    )


def test_human_size_units():
    assert human_size(0) == "0 B"
    assert human_size(512) == "512 B"
    assert human_size(2048).endswith("KB")
    assert human_size(5 * 1024 * 1024).endswith("MB")


def test_build_rows_computes_metrics(tmp_path):
    content = "# Hello\n\n" + "word " * 100
    result = make_result("doc.txt", content, size=4000, tmp_path=tmp_path)
    rows = build_rows([result])
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "doc.txt"
    assert row.original_size == 4000
    assert row.markdown_size == len(content.encode("utf-8"))
    assert row.tokens > 0
    assert 0.0 <= row.saved_ratio <= 100.0


def test_failed_results_excluded(tmp_path):
    ok = make_result("ok.txt", "data", size=40, tmp_path=tmp_path)
    failed = ConversionResult(source=tmp_path / "bad.bin", success=False, error="x")
    rows = build_rows([ok, failed])
    assert [r.name for r in rows] == ["ok.txt"]


def test_missing_source_file_defaults_zero(tmp_path):
    result = ConversionResult(source=Path("Z:/nope/ghost.md"), success=True, markdown="tiny")
    rows = build_rows([result])
    assert rows[0].original_size == 0


def test_render_table_layout(tmp_path):
    rows = build_rows([make_result("a.txt", "hello world", size=44, tmp_path=tmp_path)])
    table = render_table(rows)
    lines = table.splitlines()
    assert "File" in lines[0] and "~Tokens" in lines[0]
    assert set(lines[1]) <= {"-"}
    assert "a.txt" in lines[2]


def test_render_table_empty():
    assert "(no successful conversions)" in render_table([])
```
