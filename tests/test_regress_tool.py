"""tools/regress.py - the real-document regression check."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "regress", Path(__file__).resolve().parent.parent / "tools" / "regress.py"
)
regress = importlib.util.module_from_spec(_SPEC)
sys.modules["regress"] = regress  # dataclasses look their module up here
_SPEC.loader.exec_module(regress)


def _meta(status="Success", **quality):
    return {"status": status, "tokens": 100, "quality": quality}


# --------------------------------------------------------------------------- #
# compare()
# --------------------------------------------------------------------------- #
def test_identical_output_is_same():
    verdict = regress.compare("a.pdf", "ข้อความ", _meta(), "ข้อความ", _meta(), [])
    assert verdict.outcome == regress.SAME
    assert verdict.similarity == 1.0


def test_no_approved_output_is_new():
    verdict = regress.compare("a.pdf", None, None, "text", _meta(), [])
    assert verdict.outcome == regress.NEW


def test_text_difference_alone_is_changed_not_regressed():
    verdict = regress.compare("a.pdf", "one\ntwo", _meta(), "one\nthree", _meta(), [])
    assert verdict.outcome == regress.CHANGED
    assert 0 < verdict.similarity < 1


def test_losing_an_expected_phrase_is_a_regression():
    # ข read as ย: the very error the tool exists to catch.
    verdict = regress.compare(
        "cert.pdf", "ขอรับรองว่า", _meta(), "ยอรับรองว่า", _meta(), ["ขอรับรองว่า"]
    )
    assert verdict.outcome == regress.REGRESSED
    assert "ขอรับรองว่า" in verdict.reasons[0]


def test_expected_phrases_ignore_whitespace_only():
    verdict = regress.compare(
        "cert.pdf", "ขอรับรองว่า", _meta(), "ขอ รับรอง\nว่า", _meta(), ["ขอรับรองว่า"]
    )
    assert verdict.outcome == regress.CHANGED


def test_finding_a_previously_missing_phrase_is_fixed():
    verdict = regress.compare(
        "cert.pdf", "ยอรับรอง", _meta(), "ขอรับรอง", _meta(), ["ขอรับรอง"]
    )
    assert verdict.outcome == regress.FIXED


def test_a_phrase_missing_in_both_is_noted_but_not_a_regression():
    verdict = regress.compare("a.pdf", "x", _meta(), "y", _meta(), ["absent"])
    assert verdict.outcome == regress.CHANGED
    assert any("still missing" in note for note in verdict.notes)


def test_a_worse_status_is_a_regression():
    verdict = regress.compare("a.pdf", "x", _meta("Success"), "x", _meta("Warning"), [])
    assert verdict.outcome == regress.REGRESSED


def test_a_better_status_is_only_a_change():
    verdict = regress.compare("a.pdf", "x", _meta("Warning"), "x", _meta("Success"), [])
    assert verdict.outcome == regress.CHANGED


def test_a_failed_conversion_is_an_error():
    current = {"status": "Error", "error": "boom"}
    verdict = regress.compare("a.pdf", "x", _meta(), "", current, [])
    assert verdict.outcome == regress.ERROR


def test_fewer_pages_with_content_is_a_regression():
    verdict = regress.compare(
        "a.pdf", "x", _meta(pages_with_content=3), "x", _meta(pages_with_content=2), []
    )
    assert verdict.outcome == regress.REGRESSED


def test_review_flag_count_changes_are_reported():
    verdict = regress.compare(
        "a.pdf", "x", _meta(ocr_review_lines=2), "x", _meta(ocr_review_lines=9), []
    )
    assert any("ocr_review_lines 2 -> 9" in note for note in verdict.notes)


# --------------------------------------------------------------------------- #
# discover() / expectations
# --------------------------------------------------------------------------- #
def test_discover_skips_hidden_folders_expectations_and_markdown(tmp_path):
    (tmp_path / "scans").mkdir()
    (tmp_path / "scans" / "a.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / "scans" / "a.csv.expect.txt").write_text("a\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# n\n", encoding="utf-8")
    (tmp_path / ".golden").mkdir()
    (tmp_path / ".golden" / "b.csv").write_text("x\n", encoding="utf-8")

    assert regress.discover(tmp_path) == [Path("scans/a.csv")]


def test_discover_only_filters_by_relative_path(tmp_path):
    for name in ("one.csv", "two.csv"):
        (tmp_path / name).write_text("a\n", encoding="utf-8")
    assert regress.discover(tmp_path, "two*") == [Path("two.csv")]


def test_expectation_file_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / "a.pdf.expect.txt"
    path.write_text("﻿# header\n\nขอรับรอง\n  บริษัท  \n", encoding="utf-8")
    assert regress.load_expectations(path) == ["ขอรับรอง", "บริษัท"]


# --------------------------------------------------------------------------- #
# run() / approve() end to end, with the real converter on small files
# --------------------------------------------------------------------------- #
def test_run_then_approve_then_detect_a_regression(tmp_path):
    samples = tmp_path / "samples"
    samples.mkdir()
    (samples / "price.csv").write_text("item,price\nข้าว,10\n", encoding="utf-8")
    (samples / "price.csv.expect.txt").write_text("ข้าว\n", encoding="utf-8")
    quiet = lambda *_: None

    run_dir, verdicts = regress.run(samples, out=quiet)
    assert [v.outcome for v in verdicts] == [regress.NEW]
    assert (run_dir / "price.csv.md").read_text(encoding="utf-8").count("ข้าว") == 1
    assert json.loads((run_dir / "price.csv.json").read_text(encoding="utf-8"))["status"] == "Success"
    assert "price.csv" in (run_dir / "report.md").read_text(encoding="utf-8")

    assert regress.approve(samples, ["price.csv"]) == ["price.csv"]
    _, verdicts = regress.run(samples, out=quiet)
    assert [v.outcome for v in verdicts] == [regress.SAME]

    def broken(path, preset, timeout):  # a future change reads ข as ย
        markdown, meta = regress._convert(path, preset, timeout)
        return markdown.replace("ข", "ย"), meta

    run_dir, verdicts = regress.run(samples, convert=broken, out=quiet)
    assert [v.outcome for v in verdicts] == [regress.REGRESSED]
    assert (run_dir / "price.csv.diff").is_file()


def test_a_crashing_conversion_is_reported_and_the_run_continues(tmp_path):
    for name in ("a.csv", "b.csv"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")

    def flaky(path, preset, timeout):
        if path.name == "a.csv":
            raise RuntimeError("engine crashed")
        return "x", {"status": "Success", "quality": {}}

    _, verdicts = regress.run(tmp_path, convert=flaky, out=lambda *_: None)
    assert [v.outcome for v in verdicts] == [regress.ERROR, regress.NEW]


def test_approve_all_takes_every_file_of_the_latest_run(tmp_path):
    for name in ("a.csv", "b.csv"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    stub = lambda path, preset, timeout: ("x", {"status": "Success", "quality": {}})
    regress.run(tmp_path, convert=stub, out=lambda *_: None)

    assert regress.approve(tmp_path, [], every=True) == ["a.csv", "b.csv"]
    assert (tmp_path / ".golden" / "a.csv.md").is_file()


def test_approve_refuses_a_file_that_is_not_in_the_run(tmp_path):
    (tmp_path / "a.csv").write_text("x\n", encoding="utf-8")
    stub = lambda path, preset, timeout: ("x", {"status": "Success", "quality": {}})
    regress.run(tmp_path, convert=stub, out=lambda *_: None)

    with pytest.raises(SystemExit):
        regress.approve(tmp_path, ["missing.pdf"])


def test_main_exit_codes(tmp_path, monkeypatch):
    assert regress.main(["--samples", str(tmp_path / "nope"), "run"]) == 2
    assert regress.main(["--samples", str(tmp_path), "approve"]) == 2

    (tmp_path / "a.csv").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(regress, "_convert", lambda p, s, t: ("", {"status": "Error", "error": "x"}))
    assert regress.main(["--samples", str(tmp_path), "run"]) == 1
