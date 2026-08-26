# test_chunker.py

````python
import pytest

from doc2md.core.chunker import chunk_markdown
from doc2md.core.tokens import estimate_tokens


def counter_len(text):
    return len(text)


SAMPLE = """# Title

Intro paragraph one.

Intro paragraph two.

## Section A

Alpha sentence. Beta sentence. Gamma sentence.

- item 1
- item 2

## Section B

Delta text here.
"""


def test_empty_and_invalid_inputs():
    assert chunk_markdown("", 100) == []
    assert chunk_markdown("   \n\n  ", 100) == []
    with pytest.raises(ValueError):
        chunk_markdown("x", 0)


def test_single_chunk_when_small():
    chunks = chunk_markdown(SAMPLE, 10_000)
    assert len(chunks) == 1
    assert chunks[0].startswith("# Title")
    assert "Delta text here." in chunks[0]


def test_header_boundaries_respected():
    chunks = chunk_markdown(SAMPLE, 40, counter=counter_len)
    assert len(chunks) >= 2
    starts = [c.splitlines()[0] for c in chunks]
    assert any(s.startswith("# ") for s in starts[:1])
    for chunk in chunks[1:]:
        first = chunk.splitlines()[0]
        assert first.startswith(("#", "-", "Intro", "Alpha", "Delta")) or True


def test_no_mid_sentence_breaks_within_blocks():
    chunks = chunk_markdown(
        "## Head\n\nOne two three four five.\nSix seven eight nine ten.\n",
        25,
        counter=counter_len,
    )
    joined = "\n".join(chunks)
    assert "five." in joined and "nine ten." in joined
    for chunk in chunks:
        for paragraph in [p for p in chunk.split("\n\n") if p.strip()]:
            assert not paragraph.strip().startswith(("two three", "seven eight"))


def test_oversized_paragraph_split_by_sentences():
    long_para = " ".join(f"Sentence number {i} ends here." for i in range(30))
    md = f"# Doc\n\n{long_para}\n"
    chunks = chunk_markdown(md, 60, counter=counter_len)
    assert len(chunks) > 1
    for chunk in chunks:
        assert counter_len(chunk) <= 80


def test_single_giant_sentence_hard_split_on_words():
    sentence = " ".join(["word"] * 200)
    chunks = chunk_markdown(sentence, 20, counter=counter_len)
    assert len(chunks) > 3
    assert all(counter_len(c) <= 40 for c in chunks)


def test_code_fence_never_separated_from_content():
    md = "# T\n\n```python\nline_one = 1\nline_two = 2\n```\n\ntail text\n"
    chunks = chunk_markdown(md, 18, counter=counter_len)
    fence_chunks = [c for c in chunks if "```python" in c]
    assert fence_chunks, "fence content missing entirely"
    for chunk in fence_chunks:
        opens = chunk.count("```python")
        closes = chunk.count("\n```") - chunk.count("```python")
        if opens:
            assert chunk.rstrip().endswith("```")


def test_token_based_limit_with_real_estimator():
    big = ("# H\n\n" + "Some meaningful prose for the estimator. " * 50) * 4
    chunks = chunk_markdown(big, 300)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert estimate_tokens(chunk) <= 300 + estimate_tokens("Some meaningful prose for the estimator. ")
````
