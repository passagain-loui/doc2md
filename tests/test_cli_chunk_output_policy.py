"""Milestone 7 item 1 - chunk output must honor --output-policy through the
same shared commit path as the main output, for every policy, including
collisions and two same-stem source files.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


def _long_body(n_sections=4):
    return "\n\n".join(
        f"## Section {i}\n\n{'lorem ipsum dolor sit amet ' * 20}" for i in range(n_sections)
    )


def _write_long_source(directory, name="doc.txt", prefix=""):
    path = directory / name
    path.write_text(prefix + _long_body(), encoding="utf-8")
    return path


# --- converted-folder --------------------------------------------------------------


def test_converted_folder_puts_main_and_every_chunk_together(tmp_path):
    source = _write_long_source(tmp_path)

    result = runner.invoke(
        app, ["convert", str(source), "--chunk", "120", "--output-policy", "converted-folder"]
    )

    assert result.exit_code == 0, result.output
    converted = tmp_path / "Converted"
    assert (converted / "doc.md").exists()
    parts = sorted(p.name for p in converted.glob("doc.part*.md"))
    assert len(parts) >= 2
    assert not (tmp_path / "doc.md").exists()
    for name in ("doc.md", *parts):
        assert not (tmp_path / name).exists()


# --- fail: collisions must preflight the whole set ----------------------------------


def test_fail_policy_refuses_when_main_destination_exists_and_writes_no_chunks(tmp_path):
    (tmp_path / "doc.md").write_text("pre-existing", encoding="utf-8")
    source = _write_long_source(tmp_path)

    result = runner.invoke(
        app, ["convert", str(source), "--chunk", "120", "--output-policy", "fail"]
    )

    assert result.exit_code == 1, result.output
    assert list(tmp_path.glob("doc.part*.md")) == []
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "pre-existing"


def test_fail_policy_chunk_collision_removes_the_main_output_too(tmp_path):
    """A collision on chunk 1 (main destination is free) must not leave the
    main output sitting on disk as a misleading partial conversion."""
    (tmp_path / "doc.part001.md").write_text("blocker", encoding="utf-8")
    source = _write_long_source(tmp_path)

    result = runner.invoke(
        app, ["convert", str(source), "--chunk", "120", "--output-policy", "fail"]
    )

    assert result.exit_code == 1, result.output
    assert not (tmp_path / "doc.md").exists(), (
        "main output must be rolled back when a later chunk collides under fail"
    )
    assert (tmp_path / "doc.part001.md").read_text(encoding="utf-8") == "blocker"
    assert list(tmp_path.glob("doc.part00[2-9].md")) == []


def test_fail_policy_writes_the_full_set_when_nothing_collides(tmp_path):
    source = _write_long_source(tmp_path)

    result = runner.invoke(
        app, ["convert", str(source), "--chunk", "120", "--output-policy", "fail"]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "doc.md").exists()
    assert len(list(tmp_path.glob("doc.part*.md"))) >= 2


# --- overwrite: replaces existing main/chunks, never the source --------------------


def test_overwrite_policy_replaces_existing_main_and_chunk_names(tmp_path):
    (tmp_path / "doc.md").write_text("stale main", encoding="utf-8")
    (tmp_path / "doc.part001.md").write_text("stale chunk", encoding="utf-8")
    source = _write_long_source(tmp_path)

    result = runner.invoke(
        app, ["convert", str(source), "--chunk", "120", "--output-policy", "overwrite"]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") != "stale main"
    assert (tmp_path / "doc.part001.md").read_text(encoding="utf-8") != "stale chunk"


def test_overwrite_policy_never_overwrites_the_source_itself(tmp_path):
    source = tmp_path / "already.md"
    source.write_text(_long_body(), encoding="utf-8")

    result = runner.invoke(
        app, ["convert", str(source), "--chunk", "120", "--output-policy", "overwrite"]
    )

    assert result.exit_code == 1, result.output
    assert source.read_text(encoding="utf-8") == _long_body()


# --- unique: preserved default behavior, chunk names from the ACTUAL main stem -----


def test_unique_policy_never_overwrites(tmp_path):
    (tmp_path / "doc.md").write_text("pre-existing", encoding="utf-8")
    source = _write_long_source(tmp_path)

    result = runner.invoke(
        app, ["convert", str(source), "--chunk", "120", "--output-policy", "unique"]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "pre-existing"
    assert (tmp_path / "doc-1.md").exists()
    assert list((tmp_path).glob("doc-1.part*.md"))


def test_unique_policy_two_same_stem_sources_get_unambiguous_chunk_sets(tmp_path):
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    source_a = _write_long_source(folder_a, prefix="FROM A: ")
    source_b = _write_long_source(folder_b, prefix="FROM B: ")

    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["convert", str(source_a), str(source_b), "--chunk", "120", "-o", str(out)],
    )

    assert result.exit_code == 0, result.output
    assert (out / "doc.md").exists()
    assert (out / "doc-1.md").exists()

    parts = sorted(p.name for p in out.glob("*.part*.md"))
    assert len(parts) == len(set(parts)), "no two chunk files may share a name"
    assert any(name.startswith("doc.part001") for name in parts)
    assert any(name.startswith("doc-1.part001") for name in parts)

    # Content is genuinely separated per source, not interleaved/overwritten.
    doc_first_part = next(p for p in out.glob("doc.part001*.md"))
    doc1_first_part = next(p for p in out.glob("doc-1.part001*.md"))
    assert "FROM A" in doc_first_part.read_text(encoding="utf-8")
    assert "FROM B" in doc1_first_part.read_text(encoding="utf-8")


# --- chunks never created for a result whose main output failed --------------------


def test_no_chunks_created_when_main_output_write_fails(tmp_path, monkeypatch):
    import doc2md.core.exporter as exporter_module

    source = _write_long_source(tmp_path)
    real_atomic_write_text = exporter_module._stage

    def flaky(path, *args, **kwargs):
        if path.name == "doc.md":
            raise OSError("simulated disk full")
        return real_atomic_write_text(path, *args, **kwargs)

    monkeypatch.setattr(exporter_module, "_stage", flaky)

    result = runner.invoke(app, ["convert", str(source), "--chunk", "120"])

    assert result.exit_code == 1, result.output
    assert list(tmp_path.glob("doc.part*.md")) == []


# --- quality report records the ACTUAL output path written -------------------------


def test_report_output_path_reflects_the_actually_resolved_main_stem(tmp_path):
    (tmp_path / "doc.md").write_text("pre-existing", encoding="utf-8")
    source = _write_long_source(tmp_path)
    report_path = tmp_path / "report.json"

    result = runner.invoke(
        app,
        ["convert", str(source), "--report", str(report_path), "--output-policy", "unique"],
    )

    assert result.exit_code == 0, result.output
    entries = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["output"] == str(tmp_path / "doc-1.md")
