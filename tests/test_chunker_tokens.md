# test_chunker_tokens.py

```python
import sys
import types

import pytest

from doc2md.core.chunker import chunk_markdown
from doc2md.core.tokens import estimate_tokens, encoder_backend


@pytest.fixture(autouse=True)
def _heuristic_tokenizer(monkeypatch):
    import doc2md.core.tokens as tokens_mod

    monkeypatch.setattr(tokens_mod, "_get_encoder", lambda: None)


from doc2md.core import tokens as _tokens_module_at_import

_REAL_GET_ENCODER = _tokens_module_at_import._get_encoder


def test_empty_input_returns_no_chunks():
    assert chunk_markdown("", 100) == []
    assert chunk_markdown("   \n\n  ", 100) == []


def test_invalid_max_tokens_rejected():
    with pytest.raises(ValueError):
        chunk_markdown("# x", 0)


def test_small_document_single_chunk():
    md = "# Title\n\nhello world"
    chunks = chunk_markdown(md, 500)
    assert len(chunks) == 1
    assert "Title" in chunks[0]


def test_headers_drive_splitting():
    sections = [f"## S{i}\n\n{'word ' * 30}" for i in range(4)]
    md = "# Root\n\nintro line\n\n" + "\n\n".join(sections)
    budget = estimate_tokens(sections[0]) + 10
    chunks = chunk_markdown(md, budget)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert estimate_tokens(chunk) <= budget
    assert "# Root" in chunks[0]


def test_budget_never_exceeded_with_counter():
    big = f"## Big\n\n{'lorem ipsum dolor ' * 60}"
    small = "## Small\n\ntiny"
    counter = lambda text: len(text)  # noqa: E731
    budget = counter(big) // 2
    chunks = chunk_markdown(big + "\n\n" + small, budget, counter=counter)
    assert all(counter(c) <= budget + 20 for c in chunks)
    assert any("Small" in c or "tiny" in c for c in chunks)


def test_giant_single_line_hard_split_by_words():
    blob = " ".join(["word"] * 200)
    chunks = chunk_markdown(blob, 20, counter=lambda t: len(t))
    assert len(chunks) > 3
    assert all(len(c) <= 40 for c in chunks)
    assert "".join(chunks).count("word") == 200


def test_saved_ratio_bounds_and_backend_string():
    from doc2md.core.tokens import saved_ratio

    assert saved_ratio(0, 10) == 0.0
    assert saved_ratio(100, 25) == 75.0
    assert saved_ratio(100, 250) == 0.0
    assert encoder_backend() in ("tiktoken/cl100k_base", "heuristic/chars4")


def test_tiktoken_module_injection(monkeypatch):
    import doc2md.core.tokens as tokens_mod

    tokens_mod.reset_encoder_cache()
    monkeypatch.setattr(tokens_mod, "_get_encoder", _REAL_GET_ENCODER)

    class FakeEncoder:
        def encode(self, text, disallowed_special=()):
            return [0] * (len(text) // 10 or 1)

    fake = types.ModuleType("tiktoken")
    fake.get_encoding = lambda name: FakeEncoder()
    monkeypatch.setitem(sys.modules, "tiktoken", fake)
    assert tokens_mod.estimate_tokens("a" * 100) == 10
    tokens_mod.reset_encoder_cache()
```
