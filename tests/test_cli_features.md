# test_cli_features.py

```python
import sys
import types

import pytest
from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


class FakeClipboard:
    def __init__(self):
        self.copied = None
        self.fail = False

    def copy(self, text):
        if self.fail:
            raise RuntimeError("clipboard busy")
        self.copied = text


@pytest.fixture
def clipboard(monkeypatch):
    fake = FakeClipboard()
    monkeypatch.setitem(sys.modules, "pyperclip", types.SimpleNamespace(copy=fake.copy))
    return fake


def test_copy_flag_single_file(clipboard, tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("copy me to the board", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "--stdout", "-c"])
    assert result.exit_code == 0
    assert "Copied Markdown to clipboard." in result.output
    assert clipboard.copied and "copy me" in clipboard.copied


def test_copy_concatenates_multiple_successes(clipboard, tmp_path):
    files = []
    for i in range(2):
        f = tmp_path / f"m{i}.txt"
        f.write_text(f"payload {i}", encoding="utf-8")
        files.append(str(f))
    result = runner.invoke(app, ["convert", *files, "--copy"])
    assert result.exit_code == 0
    assert "(concatenated)" in result.output
    assert "---" in clipboard.copied and "payload 0" in clipboard.copied


def test_clipboard_failure_reported_as_error_line(clipboard, tmp_path):
    clipboard.fail = True
    p = tmp_path / "w.txt"
    p.write_text("still converts", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "-c", "--stdout"])
    assert result.exit_code == 0
    assert "Clipboard error" in result.output


def test_stats_table_printed(tmp_path):
    p = tmp_path / "stats.txt"
    p.write_text("some content for statistics " * 5, encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "--stdout", "-s"])
    assert result.exit_code == 0
    assert "~Tokens" in result.output and "Saved" in result.output
    assert "%" in result.output


def test_chunk_writes_part_files(tmp_path):
    p = tmp_path / "big.txt"
    body = "\n\n".join(f"## Section {i}\n\n{'lorem ipsum dolor sit amet ' * 20}" for i in range(6))
    p.write_text(body, encoding="utf-8")
    out = tmp_path / "chunks"
    result = runner.invoke(app, ["convert", str(p), "--chunk", "120", "-o", str(out)])
    assert result.exit_code == 0
    parts = sorted(out.glob("*.part*.md"))
    assert len(parts) >= 2
    first = parts[0].read_text(encoding="utf-8")
    assert "Section" in first or "lorem" in first
    assert "chunk file(s)" in result.output


def test_chunk_via_config_default(tmp_path, monkeypatch):
    (tmp_path / "doc2md.toml").write_text("chunk = 100\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from doc2md.core.config import load_config

    cfg = load_config([tmp_path])
    assert cfg["chunk"] == 100


def test_timeout_and_maxrows_defaults_from_config(tmp_path, monkeypatch):
    (tmp_path / "doc2md.toml").write_text('timeout = 12.5\nmax_rows = 2500\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    from typer.testing import CliRunner as _R

    p = tmp_path / "t.txt"
    p.write_text("cfg defaults", encoding="utf-8")

    captured = {}

    class SpyConverter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def convert_file(self, target):
            from doc2md.core.converter import ConversionResult

            return ConversionResult(source=p, success=True, markdown="# ok\n")

    import doc2md.cli.main as cli_mod

    original = cli_mod.Converter
    cli_mod.Converter = SpyConverter
    try:
        result = _R().invoke(app, ["convert", str(p)])
    finally:
        cli_mod.Converter = original
    assert result.exit_code == 0
    assert captured["timeout"] == 12.5
    assert captured["options"]["max_rows"] == 2500


def test_ocr_disabled_from_config(tmp_path, monkeypatch):
    p = tmp_path / "x.txt"
    p.write_text("hello", encoding="utf-8")

    captured = {}

    class SpyConverter:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def convert_file(self, target):
            from doc2md.core.converter import ConversionResult

            return ConversionResult(source=p, success=True, markdown="# spy\n")

    monkeypatch.setattr(
        "doc2md.cli.main.load_config",
        lambda on_error=None: {"timeout": 60.0, "max_rows": 10000, "default_copy": False,
                               "stats": False, "chunk": None, "ocr_enabled": False},
    )
    import doc2md.cli.main as cli_mod

    original = cli_mod.Converter
    cli_mod.Converter = SpyConverter
    try:
        result = runner.invoke(app, ["convert", str(p)])
    finally:
        cli_mod.Converter = original
    assert result.exit_code == 0
    assert captured["options"]["pdf_ocr_fallback"] is False
```
