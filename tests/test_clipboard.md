# test_clipboard.py

```python
import pytest

from doc2md.core import clipboard


class StubPyperclip:
    def __init__(self, fail=False):
        self.copied = None
        self.fail = fail

    def copy(self, text):
        if self.fail:
            raise RuntimeError("no clipboard device")
        self.copied = text


def test_copy_success(monkeypatch):
    stub = StubPyperclip()
    monkeypatch.setitem(__import__("sys").modules, "pyperclip", stub)
    ok, message = clipboard.copy_text("# payload\n")
    assert ok
    assert "copied" in message
    assert stub.copied == "# payload\n"


def test_copy_failure_returns_message(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pyperclip", StubPyperclip(fail=True))
    ok, message = clipboard.copy_text("data")
    assert not ok
    assert "clipboard unavailable" in message


def test_copy_empty_short_circuits():
    ok, message = clipboard.copy_text("")
    assert not ok
    assert "nothing to copy" in message


def test_missing_pyperclip_reports_import_error(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pyperclip", None)
    ok, message = clipboard.copy_text("data")
    assert not ok
    assert "not installed" in message
```
