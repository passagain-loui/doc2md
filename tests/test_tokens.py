import pytest

from doc2md.core import tokens


@pytest.fixture
def heuristic_only(monkeypatch):
    monkeypatch.setattr(tokens, "_get_encoder", lambda: None)
    yield


def test_estimate_empty_string():
    assert tokens.estimate_tokens("") == 0


def test_english_prose_is_about_four_characters_per_token(heuristic_only):
    sentence = "The quick brown fox jumps over the lazy dog and keeps running. " * 20

    ratio = len(sentence) / tokens.estimate_tokens(sentence)

    assert 3.0 <= ratio <= 5.5


def test_thai_text_is_about_one_token_per_character_not_four(heuristic_only):
    thai = "รายงานสรุปผลการตรวจประเมินระบบคุณภาพภายในประจำปี " * 20

    ratio = len(thai) / tokens.estimate_tokens(thai)

    assert 0.8 <= ratio <= 1.5, "chars/4 would give about 4"


def test_thai_is_estimated_far_above_the_old_chars_over_four(heuristic_only):
    thai = "การตรวจสอบเอกสารและบันทึกคุณภาพ" * 30

    assert tokens.estimate_tokens(thai) > 2.5 * (len(thai) / 4)


def test_estimate_is_never_zero_for_text_and_is_monotonic(heuristic_only):
    assert tokens.estimate_tokens("a") >= 1
    assert tokens.estimate_tokens("ab cd") <= tokens.estimate_tokens("ab cd ef gh")


def test_backend_name_reflects_availability(monkeypatch):
    monkeypatch.setattr(tokens, "_get_encoder", lambda: object())
    assert tokens.encoder_backend() == "tiktoken/cl100k_base"
    monkeypatch.setattr(tokens, "_get_encoder", lambda: None)
    assert tokens.encoder_backend() == tokens.HEURISTIC_BACKEND


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
    assert tokens.estimate_tokens("fallback please") == tokens._heuristic_tokens("fallback please")
