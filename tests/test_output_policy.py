"""Milestone 2 - Safe Output Policy.

``resolve_destination`` is the single resolver shared by the CLI, the GUI and
chunked output; ``atomic_write_text`` is the single write path all three use.
Test-first coverage for every policy's collision/overwrite/self-write rules.
"""

from __future__ import annotations

import pytest

from doc2md.core.exporter import (
    OutputPolicy,
    OutputPolicyError,
    atomic_write_text,
    resolve_destination,
)


# --- unique (existing default behaviour, must not change) --------------------


def test_unique_policy_numbers_around_an_existing_file(tmp_path):
    (tmp_path / "report.md").write_text("old", encoding="utf-8")
    source = tmp_path / "report.pdf"
    source.write_text("pdf bytes", encoding="utf-8")

    dest = resolve_destination(source, tmp_path, ".md", OutputPolicy.UNIQUE)

    assert dest == tmp_path / "report-1.md"


def test_unique_policy_never_targets_the_source_itself(tmp_path):
    """A .md input converting to .md output in the same directory must not
    resolve to the source path - resolve_output_path already treats the
    source (present on disk) as a collision to number around."""
    source = tmp_path / "already.md"
    source.write_text("original", encoding="utf-8")

    dest = resolve_destination(source, tmp_path, ".md", "unique")

    assert dest != source
    assert dest == tmp_path / "already-1.md"


def test_unique_policy_accepts_plain_string(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")
    assert resolve_destination(source, tmp_path, ".md", "unique") == tmp_path / "a.md"


# --- fail ----------------------------------------------------------------------


def test_fail_policy_returns_candidate_when_nothing_exists(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")
    dest = resolve_destination(source, tmp_path, ".md", OutputPolicy.FAIL)
    assert dest == tmp_path / "a.md"


def test_fail_policy_raises_when_destination_exists(tmp_path):
    (tmp_path / "a.md").write_text("existing", encoding="utf-8")
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")

    with pytest.raises(OutputPolicyError):
        resolve_destination(source, tmp_path, ".md", OutputPolicy.FAIL)


def test_fail_policy_raises_for_md_input_targeting_itself(tmp_path):
    source = tmp_path / "already.md"
    source.write_text("original", encoding="utf-8")

    with pytest.raises(OutputPolicyError):
        resolve_destination(source, tmp_path, ".md", OutputPolicy.FAIL)


# --- overwrite -------------------------------------------------------------------


def test_overwrite_policy_returns_candidate_over_an_existing_file(tmp_path):
    (tmp_path / "a.md").write_text("stale", encoding="utf-8")
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")

    dest = resolve_destination(source, tmp_path, ".md", OutputPolicy.OVERWRITE)
    assert dest == tmp_path / "a.md"


def test_overwrite_policy_always_refuses_to_target_the_source(tmp_path):
    source = tmp_path / "already.md"
    source.write_text("original", encoding="utf-8")

    with pytest.raises(OutputPolicyError):
        resolve_destination(source, tmp_path, ".md", OutputPolicy.OVERWRITE)


def test_overwrite_policy_source_check_is_case_insensitive_on_windows(tmp_path):
    source = tmp_path / "Already.MD"
    source.write_text("original", encoding="utf-8")
    lookalike_source = tmp_path / "already.md"  # same file, different case

    with pytest.raises(OutputPolicyError):
        resolve_destination(lookalike_source, tmp_path, ".MD", OutputPolicy.OVERWRITE)


# --- converted-folder --------------------------------------------------------------


def test_converted_folder_policy_writes_under_a_converted_subfolder(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")

    dest = resolve_destination(source, tmp_path, ".md", OutputPolicy.CONVERTED_FOLDER)

    assert dest == tmp_path / "Converted" / "a.md"


def test_converted_folder_policy_numbers_around_collisions_within_it(tmp_path):
    converted = tmp_path / "Converted"
    converted.mkdir()
    (converted / "a.md").write_text("existing", encoding="utf-8")
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")

    dest = resolve_destination(source, tmp_path, ".md", OutputPolicy.CONVERTED_FOLDER)

    assert dest == converted / "a-1.md"


# --- invalid policy --------------------------------------------------------------


def test_unknown_policy_string_raises_value_error(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_destination(source, tmp_path, ".md", "not-a-real-policy")


# --- atomic writes -----------------------------------------------------------------


def test_atomic_write_text_creates_parent_dirs_and_writes(tmp_path):
    dest = tmp_path / "nested" / "deep" / "out.md"
    atomic_write_text(dest, "# hello\n")
    assert dest.read_text(encoding="utf-8") == "# hello\n"


def test_atomic_write_text_overwrites_cleanly(tmp_path):
    dest = tmp_path / "out.md"
    atomic_write_text(dest, "first")
    atomic_write_text(dest, "second")
    assert dest.read_text(encoding="utf-8") == "second"


def test_atomic_write_text_leaves_no_partial_or_temp_file_on_failure(tmp_path):
    dest = tmp_path / "out.md"
    dest.mkdir()  # force os.replace() to fail

    with pytest.raises(OSError):
        atomic_write_text(dest, "content")

    leftovers = [p for p in tmp_path.iterdir() if p != dest]
    assert leftovers == []


def test_atomic_write_text_never_leaves_partial_content_visible(tmp_path):
    """A reader can never observe a half-written file: the destination is
    either the previous complete content or the new complete content."""
    dest = tmp_path / "out.md"
    atomic_write_text(dest, "A" * 10_000)
    atomic_write_text(dest, "B" * 5_000)
    content = dest.read_text(encoding="utf-8")
    assert content == "B" * 5_000
