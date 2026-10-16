"""Review flags end to end: Converter lifts them out, the CLI shows them only on request."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

import doc2md.cli.main as cli_mod
import doc2md.core.converter as conv_mod
from doc2md.cli.main import app
from doc2md.core import review
from doc2md.core.converter import ConversionResult, Converter
from doc2md.core.quality import EngineOutput, QualityMetrics
from doc2md.core.review import REVIEW_CLOSE, REVIEW_OPEN, ReviewLine

runner = CliRunner()


# ------------------------------------------------------------------ Converter


class _OcrStubEngine:
    """An in-thread engine whose raw output carries encoded review lines."""

    name = "ocr-stub"
    requires_process_isolation = False

    def __init__(self, output):
        self._output = output

    def convert(self, source, options):
        return self._output if isinstance(self._output, str) else self._output.markdown

    def convert_structured(self, source, options):
        return self._output


def _convert_with_engine_output(monkeypatch, tmp_path, output):
    from doc2md.core.router import Detection, FileKind

    source = tmp_path / "scan.txt"
    source.write_text("irrelevant - the engine is stubbed", encoding="utf-8")
    monkeypatch.setattr(
        conv_mod, "detect",
        lambda path: Detection(kind=FileKind.TEXT, mime="text/plain", confidence="high"),
    )
    monkeypatch.setattr(conv_mod, "get_engine", lambda kind: _OcrStubEngine(output))
    monkeypatch.setattr(conv_mod, "_run_in_thread", lambda payload, timeout, cancel=None: output)
    return Converter().convert_file(source)


def _raw_with_two_flags() -> str:
    return "\n".join([
        "## Page 1 (OCR)",
        "",
        "good line",
        review.encode("shaky line", 55),
        "",
        "ข้อความชัดเจน",
        review.encode("ข้อความไม่ชัด", 41),
        "",
    ])


def test_converter_returns_clean_markdown_and_review_lines(monkeypatch, tmp_path):
    output = EngineOutput(
        markdown=_raw_with_two_flags(), metrics=QualityMetrics(ocr_review_lines=2)
    )

    result = _convert_with_engine_output(monkeypatch, tmp_path, output)

    assert result.success is True
    assert "⚠" not in result.markdown
    assert REVIEW_OPEN not in result.markdown and REVIEW_CLOSE not in result.markdown
    assert [(r.confidence, r.text) for r in result.review_lines] == [
        (55, "shaky line"),
        (41, "ข้อความไม่ชัด"),
    ]
    lines = result.markdown.split("\n")
    for entry in result.review_lines:
        assert lines[entry.line] == entry.text
    assert result.quality.ocr_review_lines == 2


def test_converter_recounts_review_lines_after_the_cleaner_dedupes(monkeypatch, tmp_path):
    # the engine counted 3, but two identical consecutive lines collapse to one
    raw = "\n".join([review.encode("same shaky", 50)] * 2 + [review.encode("other", 40)])
    output = EngineOutput(markdown=raw, metrics=QualityMetrics(ocr_review_lines=3))

    result = _convert_with_engine_output(monkeypatch, tmp_path, output)

    assert len(result.review_lines) == 2
    assert result.quality.ocr_review_lines == 2
    assert REVIEW_OPEN not in result.markdown


def test_converter_leaves_unmeasured_review_count_alone_without_flags(monkeypatch, tmp_path):
    output = EngineOutput(markdown="# plain\n\nno flags here\n")

    result = _convert_with_engine_output(monkeypatch, tmp_path, output)

    assert result.review_lines == []
    assert result.quality.ocr_review_lines is None


def test_converter_reports_zero_when_engine_measured_but_nothing_survives(monkeypatch, tmp_path):
    output = EngineOutput(markdown="# clean\n", metrics=QualityMetrics(ocr_review_lines=4))

    result = _convert_with_engine_output(monkeypatch, tmp_path, output)

    assert result.review_lines == []
    assert result.quality.ocr_review_lines == 0


def test_converter_accepts_a_plain_string_engine_result_with_flags(monkeypatch, tmp_path):
    result = _convert_with_engine_output(monkeypatch, tmp_path, _raw_with_two_flags())

    assert len(result.review_lines) == 2
    assert "⚠" not in result.markdown and REVIEW_OPEN not in result.markdown
    assert result.quality.ocr_review_lines == 2


def test_converter_warning_never_carries_a_sentinel(monkeypatch, tmp_path):
    from doc2md.core.errors import wrap_warning

    raw = wrap_warning(
        _raw_with_two_flags(), f"OCR partly failed{REVIEW_OPEN}7{REVIEW_CLOSE} on 1 page"
    )

    result = _convert_with_engine_output(monkeypatch, tmp_path, EngineOutput(markdown=raw))

    assert result.warning is not None
    assert REVIEW_OPEN not in result.warning and REVIEW_CLOSE not in result.warning
    assert "OCR partly failed" in result.warning
    assert len(result.review_lines) == 2


def test_converter_failure_results_have_no_review_lines(tmp_path):
    result = Converter().convert_file(tmp_path / "missing.pdf")

    assert result.success is False
    assert result.review_lines == []


# ------------------------------------------------------------------------ CLI


class _FlaggedConverter:
    """Stands in for Converter: one successful result with a flagged line."""

    def __init__(self, **kwargs):
        pass

    def convert_file(self, target):
        return ConversionResult(
            source=target,
            success=True,
            markdown="# scan\n\nfine line\nshaky line\nlast line\n",
            review_lines=[ReviewLine(3, 58, "shaky line")],
        )


@pytest.fixture
def flagged_cli(monkeypatch, tmp_path):
    """A scan.png to convert, a stubbed Converter, and an isolated config dir."""
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    monkeypatch.setattr(cli_mod, "Converter", _FlaggedConverter)
    source = work / "scan.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return work, source


def test_cli_default_output_has_no_flags(flagged_cli):
    _work, source = flagged_cli

    result = runner.invoke(app, ["convert", str(source), "--stdout"])

    assert result.exit_code == 0, result.output
    assert "shaky line" in result.output
    assert "⚠" not in result.output
    assert "58%" not in result.output


def test_cli_mark_uncertain_flags_the_right_line_on_stdout(flagged_cli):
    _work, source = flagged_cli

    result = runner.invoke(app, ["convert", str(source), "--stdout", "--mark-uncertain"])

    assert result.exit_code == 0, result.output
    assert "shaky line ⚠58%" in result.output
    assert result.output.count("⚠") == 1
    assert "fine line ⚠" not in result.output


def test_cli_default_written_file_is_clean(flagged_cli):
    work, source = flagged_cli

    result = runner.invoke(app, ["convert", str(source)])

    assert result.exit_code == 0, result.output
    written = (work / "scan.md").read_text(encoding="utf-8")
    assert "⚠" not in written and REVIEW_OPEN not in written


def test_cli_mark_uncertain_written_file_carries_the_flag(flagged_cli):
    work, source = flagged_cli

    result = runner.invoke(app, ["convert", str(source), "--mark-uncertain"])

    assert result.exit_code == 0, result.output
    lines = (work / "scan.md").read_text(encoding="utf-8").split("\n")
    assert lines[3] == "shaky line ⚠58%"
    assert sum("⚠" in line for line in lines) == 1


def test_cli_mark_uncertain_applies_to_chunk_files(flagged_cli):
    work, source = flagged_cli

    result = runner.invoke(
        app, ["convert", str(source), "--mark-uncertain", "--chunk", "1000", "-o", str(work / "out")]
    )

    assert result.exit_code == 0, result.output
    produced = "".join(p.read_text(encoding="utf-8") for p in (work / "out").glob("*.md"))
    assert "shaky line ⚠58%" in produced


def test_cli_mark_uncertain_applies_to_the_clipboard_copy(flagged_cli, monkeypatch):
    _work, source = flagged_cli
    copied = {}

    import doc2md.core.clipboard as clipboard_mod

    def fake_copy(text):
        copied["text"] = text
        return True, ""

    monkeypatch.setattr(clipboard_mod, "copy_text", fake_copy)

    result = runner.invoke(app, ["convert", str(source), "--stdout", "--copy", "--mark-uncertain"])

    assert result.exit_code == 0, result.output
    assert "shaky line ⚠58%" in copied["text"]

    copied.clear()
    runner.invoke(app, ["convert", str(source), "--stdout", "--copy"])
    assert "⚠" not in copied["text"]


def test_cli_config_mark_uncertain_enables_the_flags(flagged_cli):
    work, source = flagged_cli
    (work / "doc2md.toml").write_text("mark_uncertain = true\n", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--stdout"])

    assert result.exit_code == 0, result.output
    assert "shaky line ⚠58%" in result.output


def test_cli_no_mark_uncertain_overrides_config_true(flagged_cli):
    work, source = flagged_cli
    (work / "doc2md.toml").write_text("mark_uncertain = true\n", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--stdout", "--no-mark-uncertain"])

    assert result.exit_code == 0, result.output
    assert "shaky line" in result.output
    assert "⚠" not in result.output


def test_cli_config_false_keeps_output_clean(flagged_cli):
    work, source = flagged_cli
    (work / "doc2md.toml").write_text("mark_uncertain = false\n", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--stdout"])

    assert result.exit_code == 0, result.output
    assert "⚠" not in result.output


def test_cli_flag_does_not_touch_files_without_review_lines(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "note.txt"
    source.write_text("plain note", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source), "--stdout", "--mark-uncertain"])

    assert result.exit_code == 0, result.output
    assert "plain note" in result.output
    assert "⚠" not in result.output


def test_config_default_for_mark_uncertain_is_off():
    from doc2md.core.config import DEFAULTS, load_config

    assert DEFAULTS["mark_uncertain"] is False
    assert load_config([]) ["mark_uncertain"] is False


# --------------------------------------------------------------------- bridge


def test_bridge_has_no_mark_uncertain_option(flagged_cli, tmp_path):
    _work, source = flagged_cli

    result = runner.invoke(
        app, ["bridge", str(source), "--inbox", str(tmp_path / "inbox"), "--mark-uncertain"]
    )

    assert result.exit_code == 2


def test_bridge_bundle_is_always_clean_even_when_config_asks_for_flags(flagged_cli, tmp_path):
    work, source = flagged_cli
    (work / "doc2md.toml").write_text("mark_uncertain = true\n", encoding="utf-8")
    inbox = tmp_path / "inbox"

    result = runner.invoke(app, ["bridge", str(source), "--inbox", str(inbox)])

    assert result.exit_code == 0, result.output
    bundle = "".join(
        p.read_text(encoding="utf-8", errors="replace") for p in inbox.rglob("*") if p.is_file()
    )
    assert "shaky line" in bundle
    assert "⚠" not in bundle
    assert REVIEW_OPEN not in bundle
