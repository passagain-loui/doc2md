"""CLI ``--output-policy`` flag: overwrite (default), unique, fail,
converted-folder - all routed through the shared resolver in
``doc2md.core.exporter``.
"""

from __future__ import annotations

from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


def test_default_policy_refreshes_the_previous_output_in_place(tmp_path):
    """Re-running must not accumulate -1, -2 copies."""
    source = tmp_path / "note.txt"
    source.write_text("first", encoding="utf-8")
    assert runner.invoke(app, ["convert", str(source)]).exit_code == 0
    source.write_text("second", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source)])

    assert result.exit_code == 0, result.output
    assert "second" in (tmp_path / "note.md").read_text(encoding="utf-8")
    assert not (tmp_path / "note-1.md").exists()


def test_default_policy_numbers_a_markdown_source_instead_of_overwriting_it(tmp_path):
    source = tmp_path / "note.md"
    source.write_text("# my own notes", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source)])

    assert result.exit_code == 0, result.output
    assert source.read_text(encoding="utf-8") == "# my own notes"
    assert (tmp_path / "note-1.md").exists()


def test_explicit_unique_numbers_around_an_existing_file(tmp_path):
    (tmp_path / "note.md").write_text("pre-existing", encoding="utf-8")
    source = tmp_path / "note.txt"
    source.write_text("new content", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--output-policy", "unique"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "note-1.md").exists()
    assert (tmp_path / "note.md").read_text(encoding="utf-8") == "pre-existing"


def test_fail_policy_errors_out_instead_of_numbering(tmp_path):
    (tmp_path / "note.md").write_text("pre-existing", encoding="utf-8")
    source = tmp_path / "note.txt"
    source.write_text("new content", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--output-policy", "fail"])

    assert result.exit_code == 1, result.output
    assert not (tmp_path / "note-1.md").exists()
    assert (tmp_path / "note.md").read_text(encoding="utf-8") == "pre-existing"


def test_overwrite_policy_replaces_the_existing_file(tmp_path):
    (tmp_path / "note.md").write_text("stale", encoding="utf-8")
    source = tmp_path / "note.txt"
    source.write_text("new content", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--output-policy", "overwrite"])

    assert result.exit_code == 0, result.output
    assert "new content" in (tmp_path / "note.md").read_text(encoding="utf-8")


def test_overwrite_policy_refuses_to_overwrite_an_md_source(tmp_path):
    source = tmp_path / "already.md"
    source.write_text("original markdown", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--output-policy", "overwrite"])

    assert result.exit_code == 1, result.output
    assert source.read_text(encoding="utf-8") == "original markdown"


def test_converted_folder_policy_writes_into_a_subfolder(tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("content", encoding="utf-8")

    result = runner.invoke(
        app, ["convert", str(source), "--output-policy", "converted-folder"]
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "Converted" / "note.md").exists()
    assert not (tmp_path / "note.md").exists()


def test_output_inside_input_folder_prints_a_note(tmp_path):
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("alpha", encoding="utf-8")
    out = source_dir / "out"

    result = runner.invoke(app, ["convert", str(source_dir), "-o", str(out)])

    assert result.exit_code == 0, result.output
    assert "inside the input folder" in result.output
