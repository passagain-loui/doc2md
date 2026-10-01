"""A failure while claiming a chunk file must undo the main output too."""

from __future__ import annotations

import pytest

from doc2md.core import exporter


def test_chunk_claim_failure_rolls_back_main_and_earlier_chunks(tmp_path, monkeypatch):
    source = tmp_path / "report.txt"
    source.write_text("x", encoding="utf-8")
    real_stage = exporter._stage

    def flaky_stage(path, content):
        if "part002" in path.name:
            raise OSError("No space left on device")
        return real_stage(path, content)

    monkeypatch.setattr(exporter, "_stage", flaky_stage)

    with pytest.raises(OSError):
        exporter.commit_output_set(
            source=source,
            directory=tmp_path / "out",
            policy="unique",
            main_suffix=".md",
            main_content="main",
            chunk_contents=["one", "two"],
        )

    assert list((tmp_path / "out").glob("*")) == []


def test_failed_staging_write_leaves_no_temp_file(tmp_path, monkeypatch):
    target = tmp_path / "x.md"

    def boom(fd, mode, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(exporter.os, "fdopen", boom)

    with pytest.raises(OSError):
        exporter._stage(target, "content")

    assert list(tmp_path.iterdir()) == []
