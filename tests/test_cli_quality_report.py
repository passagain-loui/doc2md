"""CLI ``--report`` flag: writes a structured JSON quality report atomically,
never mixes it into ``--stdout``, and fails loudly (non-zero exit) if the
report itself cannot be written.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


def test_report_written_for_successful_conversion(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("plain content", encoding="utf-8")
    report_path = tmp_path / "report.json"

    result = runner.invoke(app, ["convert", str(src), "--report", str(report_path)])

    assert result.exit_code == 0, result.output
    assert report_path.exists()
    entries = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(entries) == 1
    entry = entries[0]
    assert entry["status"] == "Success"
    assert entry["source"] == str(src)
    assert entry["output"] == str(src.with_suffix(".md"))
    assert entry["error"] is None


def test_report_reflects_mixed_batch_results(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("hello", encoding="utf-8")
    bad = tmp_path / "bad.bin"
    bad.write_bytes(bytes(range(256)) * 8)
    report_path = tmp_path / "report.json"

    result = runner.invoke(
        app, ["convert", str(good), str(bad), "--report", str(report_path), "--ignore-errors"]
    )

    assert result.exit_code == 0, result.output
    entries = json.loads(report_path.read_text(encoding="utf-8"))
    statuses = {entry["source"]: entry["status"] for entry in entries}
    assert statuses[str(good)] == "Success"
    assert statuses[str(bad)] == "Error"


def test_report_output_is_null_in_stdout_mode(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("plain content", encoding="utf-8")
    report_path = tmp_path / "report.json"

    result = runner.invoke(
        app, ["convert", str(src), "--stdout", "--report", str(report_path)]
    )

    assert result.exit_code == 0, result.output
    entries = json.loads(report_path.read_text(encoding="utf-8"))
    assert entries[0]["output"] is None
    # the JSON report body must never leak into stdout alongside the markdown
    assert "\"status\"" not in result.output


def test_report_write_failure_is_a_hard_error(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("plain content", encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.mkdir()  # force the atomic write to fail

    result = runner.invoke(app, ["convert", str(src), "--report", str(report_path)])

    assert result.exit_code != 0
    assert "report" in result.output.lower()


def test_report_written_even_with_ignore_errors_still_reflects_failure(tmp_path):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(bytes(range(256)) * 8)
    report_path = tmp_path / "report.json"

    result = runner.invoke(
        app, ["convert", str(bad), "--report", str(report_path), "--ignore-errors"]
    )

    assert result.exit_code == 0
    entries = json.loads(report_path.read_text(encoding="utf-8"))
    assert entries[0]["status"] == "Error"
