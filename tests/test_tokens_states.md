# test_tokens_states.py

```python
import sys

import pytest

from doc2md.core import tokens


class FakeEncoder:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def encode(self, text, disallowed_special=()):
        self.calls += 1
        return [0] * max(1, len(text) // 2)


def test_encoder_ready_state_cached(monkeypatch):
    tokens.reset_encoder_cache()
    enc = FakeEncoder("cl100k_base")

    class FakeModule:
        @staticmethod
        def get_encoding(name):
            return enc

    monkeypatch.setitem(sys.modules, "tiktoken", FakeModule())
    first = tokens.estimate_tokens("abcd")
    second = tokens.estimate_tokens("abcdefgh")
    assert first == 2 and second == 4
    assert tokens._ENCODER_STATE == "ready"
    assert enc.calls == 2


def test_encoder_failure_marks_failed(monkeypatch):
    tokens.reset_encoder_cache()

    class BrokenModule:
        @staticmethod
        def get_encoding(name):
            raise OSError("network down")

    monkeypatch.setitem(sys.modules, "tiktoken", BrokenModule())
    assert tokens.estimate_tokens("offline text") > 0
    assert tokens._ENCODER_STATE == "failed"
    assert tokens._get_encoder() is None


def test_ready_short_circuit_skips_reinit(monkeypatch):
    calls = []

    class CountingModule:
        @staticmethod
        def get_encoding(name):
            calls.append(name)
            return FakeEncoder(name)

    monkeypatch.setitem(sys.modules, "tiktoken", CountingModule())
    tokens.reset_encoder_cache()
    tokens.estimate_tokens("a")
    tokens.estimate_tokens("b")
    tokens._get_encoder()
    tokens._get_encoder()
    assert len(calls) == 1
```
