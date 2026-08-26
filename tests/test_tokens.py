import pytest

from doc2md.core import tokens


@pytest.fixture
def heuristic_only(monkeypatch):
    monkeypatch.setattr(tokens, "_get_encoder", lambda: None)
    yield


def test_estimate_empty_string():
    assert tokens.estimate_tokens("") == 0


def test_fallback_estimate_is_chars_div_four(heuristic_only):
    assert tokens.estimate_tokens("abcd") == 1
    assert tokens.estimate_tokens("abc") == 1
    assert tokens.estimate_tokens("x" * 400) == 100


def test_backend_name_reflects_availability(monkeypatch):
    monkeypatch.setattr(tokens, "_get_encoder", lambda: object())
    assert tokens.encoder_backend() == "tiktoken/cl100k_base"
    monkeypatch.setattr(tokens, "_get_encoder", lambda: None)
    assert tokens.encoder_backend() == "heuristic/chars4"


def test_real_tiktoken_if_available():
    encoder = tokens._get_encoder()
    if encoder is None:
        pytest.skip("tiktoken encoding unavailable (offline)")
    count = tokens.estimate_tokens("hello world, this is a tokenizer test")
    assert 5 <= count <= 25


def test_reset_cache_reinitializes():
    tokens.reset_encoder_cache()
    assert tokens._ENCODER_STATE == "uninitialized"
    tokens.estimate_tokens("warm the cache")
    assert tokens._ENCODER_STATE in ("ready", "failed")
    tokens.reset_encoder_cache()


def test_encoder_exception_falls_back_gracefully(monkeypatch):
    class Boom:
        def encode(self, text, disallowed_special=()):
            raise RuntimeError("tokenizer exploded")

    monkeypatch.setattr(tokens, "_get_encoder", lambda: Boom())
    assert tokens.estimate_tokens("fallback please") == (len("fallback please") + 3) // 4
