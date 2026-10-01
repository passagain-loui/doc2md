"""Token estimation: exact via tiktoken when it can load, else a calibrated estimate.

``chars / 4`` is right for English and badly wrong for Thai, which tokenizes at
roughly one token per character. Measured on 2,501 segments (1.34M cl100k tokens)
of real converted office documents, ``chars / 4`` was off by 43% on average and
undercounted Thai-heavy text about threefold. The fallback instead weights each
character by its class; the weights below were fitted on that data and held out
by document (mean error 5.7%, 91 documents, a third of them unseen when fitting).

The reference tokenizer is OpenAI's ``cl100k_base``. Claude's tokenizer is not
public, so for Claude the figure is an estimate of the same order, not a count.
"""

from __future__ import annotations

import math
from collections import Counter
from functools import lru_cache

_ENCODER = None
_ENCODER_STATE = "uninitialized"


def reset_encoder_cache() -> None:
    global _ENCODER, _ENCODER_STATE
    _ENCODER = None
    _ENCODER_STATE = "uninitialized"


def _get_encoder():
    global _ENCODER, _ENCODER_STATE
    if _ENCODER_STATE == "ready":
        return _ENCODER
    if _ENCODER_STATE == "failed":
        return None
    try:
        import tiktoken

        _ENCODER = tiktoken.get_encoding("cl100k_base")
        _ENCODER_STATE = "ready"
        return _ENCODER
    except Exception:
        _ENCODER_STATE = "failed"
        _ENCODER = None
        return None


HEURISTIC_BACKEND = "heuristic/script-weights"

# Tokens per character, by class (fitted against cl100k_base; see module docstring).
_WEIGHTS = {
    "thai_base": 0.877,
    "thai_mark": 1.069,
    "latin": 0.160,
    "digit": 0.715,
    "space": 0.644,
    "newline": 1.604,
    "ascii_punct": 0.865,
    "pipe_dash": 0.440,
    # Other scripts and symbols were too rare in the fitting data to estimate;
    # one token per character is the cautious choice for multi-byte characters.
    "other": 1.0,
}
_THAI_COMBINING = frozenset([0x0E31, *range(0x0E34, 0x0E3B), *range(0x0E47, 0x0E4F)])


@lru_cache(maxsize=None)
def _char_weight(char: str) -> float:
    code = ord(char)
    if 0x0E00 <= code <= 0x0E7F:
        return _WEIGHTS["thai_mark" if code in _THAI_COMBINING else "thai_base"]
    if char.isascii():
        if char.isalpha():
            return _WEIGHTS["latin"]
        if char.isdigit():
            return _WEIGHTS["digit"]
        if char == "\n":
            return _WEIGHTS["newline"]
        if char in " \t":
            return _WEIGHTS["space"]
        if char in "|-#*>":
            return _WEIGHTS["pipe_dash"]
        return _WEIGHTS["ascii_punct"]
    return _WEIGHTS["other"]


def _heuristic_tokens(text: str) -> int:
    return math.ceil(sum(_char_weight(char) * count for char, count in Counter(text).items()))


def estimate_tokens(text: str) -> int:
    """Tokens in *text*: exact via cl100k_base if tiktoken loads, else estimated."""
    if not text:
        return 0
    encoder = _get_encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(text, disallowed_special=()))
        except Exception:
            pass
    return _heuristic_tokens(text)


def encoder_backend() -> str:
    if _get_encoder() is not None:
        return "tiktoken/cl100k_base"
    return HEURISTIC_BACKEND


def saved_ratio(original: int, optimized: int) -> float:
    """Percentage of size removed (0-100)."""
    if original <= 0:
        return 0.0
    return max(0.0, min(100.0, (1 - optimized / original) * 100))
