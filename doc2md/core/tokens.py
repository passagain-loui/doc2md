"""Token estimation with a cached tiktoken backend and deterministic fallback."""

from __future__ import annotations

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


def estimate_tokens(text: str) -> int:
    """Estimate LLM tokens via cl100k_base, falling back to chars/4."""
    if not text:
        return 0
    encoder = _get_encoder()
    if encoder is not None:
        try:
            return len(encoder.encode(text, disallowed_special=()))
        except Exception:
            pass
    return (len(text) + 3) // 4


def encoder_backend() -> str:
    if _get_encoder() is not None:
        return "tiktoken/cl100k_base"
    return "heuristic/chars4"


def saved_ratio(original: int, optimized: int) -> float:
    """Percentage of size removed (0-100)."""
    if original <= 0:
        return 0.0
    return max(0.0, min(100.0, (1 - optimized / original) * 100))
