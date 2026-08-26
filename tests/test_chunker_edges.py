import sys

import pytest

from doc2md.core.chunker import chunk_markdown
from doc2md.core.tokens import estimate_tokens


def counter_len(text):
    return len(text)


def test_header_flush_without_blank_line():
    chunks = chunk_markdown("intro text here\n## Next Header\ntail body\n", 25,
                            counter=counter_len)
    assert chunks[0].startswith("intro")
    assert any(c.startswith("## Next Header") for c in chunks[1:])


def test_single_line_header_oversized_returned_intact():
    header = "#" + " x" * 100
    chunks = chunk_markdown(header, 10, counter=counter_len)
    assert len(chunks) == 1
    assert chunks[0] == header


def test_sentence_accumulator_flush_boundary():
    para = " ".join(f"S{i} end." for i in range(12))
    chunks = chunk_markdown(para, 30, counter=counter_len)
    assert len(chunks) >= 3
    for chunk in chunks:
        for sentence_part in chunk.split(". "):
            assert sentence_part.strip().startswith("S")


def test_fenced_block_split_keeps_pairs_balanced():
    body = "\n".join(f"value_{i} = {i}" for i in range(20))
    md = f"```python\n{body}\n```"
    chunks = chunk_markdown(md, 40, counter=counter_len)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.startswith("```python")
        assert chunk.rstrip().endswith("```")
        assert chunk.count("```python") == 1
