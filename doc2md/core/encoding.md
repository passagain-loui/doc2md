# encoding.py

```python
"""Encoding-safe text reading built on charset_normalizer with strict utf-8 defaults."""

from __future__ import annotations

from pathlib import Path

ZERO_WIDTH = ["\ufeff", "\u200b", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c"]


def decode_bytes(data: bytes, *, prefer_encodings: tuple[str, ...] = ("utf-8",)) -> str:
    """Decode bytes to str.

    Tries explicit preferred encodings first (strict), then falls back to
    charset_normalizer detection for corrupted/unknown encodings. Raises
    UnicodeDecodeError only if every strategy fails.
    """
    for encoding in prefer_encodings:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except ImportError:
        pass
    return data.decode("utf-8", errors="replace")


def read_text_smart(path: Path | str, *, prefer_encodings: tuple[str, ...] = ("utf-8",)) -> str:
    """Read a file enforcing utf-8 first with charset_normalizer fallback."""
    data = Path(path).read_bytes()
    text = decode_bytes(data, prefer_encodings=tuple(prefer_encodings))
    return strip_zero_width(text)


def strip_zero_width(text: str) -> str:
    for ch in ZERO_WIDTH:
        text = text.replace(ch, "")
    return text
```
