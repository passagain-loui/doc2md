# test_cli_errors.py

```python
import sys

import pytest
from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


def test_config_warning_goes_to_stderr_stream(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "doc2md.toml").write_text("[doc2md]\nbroken = = =\n", encoding="utf-8")
    p = tmp_path / "w.txt"
    p.write_text("warned", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "--stdout"])
    assert result.exit_code == 0
    assert "ignoring unreadable config" in result.output


def test_stdout_skips_failed_results(tmp_path):
    good = tmp_path / "g.txt"
    good.write_text("good content", encoding="utf-8")
    bad = tmp_path / "b.bin"
    bad.write_bytes(bytes(range(256)) * 4)
    result = runner.invoke(
        app, ["convert", str(good), str(bad), "--stdout", "--ignore-errors"]
    )
    assert result.exit_code == 0
    assert "good content" in result.output


def test_nothing_to_copy_message(tmp_path):
    bad = tmp_path / "x.bin"
    bad.write_bytes(bytes(range(256)) * 4)
    result = runner.invoke(app, ["convert", str(bad), "--copy", "--ignore-errors", "-q"])
    assert "Nothing to copy" in result.output


def test_clipboard_error_reported_as_warning(tmp_path, monkeypatch):
    class Failing:
        def copy(self, text):
            raise RuntimeError("clipboard locked")

    monkeypatch.setitem(sys.modules, "pyperclip", Failing())
    p = tmp_path / "ce.txt"
    p.write_text("content", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "-q", "--copy"])
    assert result.exit_code == 0
    assert "Clipboard error" in result.output


@pytest.fixture(name="fake_registry")
def _fake_registry(monkeypatch):
    from tests.test_contextmenu import FakeWinreg

    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    return fake


def test_context_menu_error_paths_on_non_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    result = runner.invoke(app, ["install-context-menu"])
    assert result.exit_code == 1
    assert "requires Windows" in result.output
    removed = runner.invoke(app, ["uninstall-context-menu"])
    assert removed.exit_code == 1
    status = runner.invoke(app, ["context-menu-status"])
    assert status.exit_code == 0
    assert "not installed" in status.output


def test_winreg_import_failure_handled(monkeypatch):
    from doc2md.core import contextmenu as cm

    monkeypatch.setitem(sys.modules, "winreg", None)
    with pytest.raises(cm.ContextMenuError, match="winreg unavailable"):
        cm.install()
```
