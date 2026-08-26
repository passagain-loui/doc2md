# clipboard.py

```python
"""Clipboard integration built on pyperclip with graceful degradation."""

from __future__ import annotations


def copy_text(text: str) -> tuple[bool, str]:
    """Copy *text* to the system clipboard. Returns (ok, human message)."""
    if not text:
        return False, "nothing to copy"
    try:
        import pyperclip
    except ImportError:
        return False, "pyperclip is not installed; run pip install pyperclip"
    try:
        pyperclip.copy(text)
    except Exception as exc:
        return False, f"clipboard unavailable: {exc}"
    return True, f"copied {len(text)} characters to the clipboard"
```
