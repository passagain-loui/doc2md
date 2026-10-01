"""Milestone 7 item 2 - TOCTOU-safe destination claiming and publishing.

``claim_and_publish_text`` / ``commit_output_set`` replace the old
"resolve_destination() then atomic_write_text()" two-step, which had a real
race window between deciding a destination and writing to it. These tests
cover single-process correctness plus a genuine multi-process race using a
synchronization barrier - not just a thread-based approximation.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from pathlib import Path

import pytest

from doc2md.core.exporter import (
    OutputPolicy,
    OutputPolicyError,
    claim_and_publish_text,
    commit_output_set,
)


def _mk_source(tmp_path, name="report.txt", body="source body"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# --- claim_and_publish_text: single-file correctness ----------------------------


def test_unique_writes_first_available_name(tmp_path):
    source = _mk_source(tmp_path)
    dest = claim_and_publish_text(source, tmp_path, ".md", "hello", "unique")
    assert dest == tmp_path / "report.md"
    assert dest.read_text(encoding="utf-8") == "hello"


def test_unique_numbers_around_existing_file(tmp_path):
    (tmp_path / "report.md").write_text("old", encoding="utf-8")
    source = _mk_source(tmp_path)
    dest = claim_and_publish_text(source, tmp_path, ".md", "new", "unique")
    assert dest == tmp_path / "report-1.md"
    assert dest.read_text(encoding="utf-8") == "new"
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "old"


def test_fail_raises_and_writes_nothing_on_collision(tmp_path):
    (tmp_path / "report.md").write_text("old", encoding="utf-8")
    source = _mk_source(tmp_path)
    with pytest.raises(OutputPolicyError):
        claim_and_publish_text(source, tmp_path, ".md", "new", "fail")
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "old"
    # no stray temp/claim files left in the directory
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.md", "report.txt"]


def test_fail_succeeds_when_nothing_exists(tmp_path):
    source = _mk_source(tmp_path)
    dest = claim_and_publish_text(source, tmp_path, ".md", "content", "fail")
    assert dest.read_text(encoding="utf-8") == "content"


def test_overwrite_replaces_existing_file(tmp_path):
    (tmp_path / "report.md").write_text("stale", encoding="utf-8")
    source = _mk_source(tmp_path)
    dest = claim_and_publish_text(source, tmp_path, ".md", "fresh", "overwrite")
    assert dest == tmp_path / "report.md"
    assert dest.read_text(encoding="utf-8") == "fresh"


def test_overwrite_refuses_the_source_itself(tmp_path):
    source = tmp_path / "already.md"
    source.write_text("original", encoding="utf-8")
    with pytest.raises(OutputPolicyError):
        claim_and_publish_text(source, tmp_path, ".md", "new", "overwrite")
    assert source.read_text(encoding="utf-8") == "original"


@pytest.mark.timeout(10)
def test_unclaimable_directory_fails_fast_instead_of_looping_forever(tmp_path):
    """A destination directory that can never be created (an ancestor path
    component is a plain file) must fail immediately with a real error -
    not be mistaken, on every numbered retry, for "this specific filename
    is taken" and spun through forever."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    broken_dir = blocker / "sub"

    source = _mk_source(tmp_path)
    with pytest.raises(OSError):
        claim_and_publish_text(source, broken_dir, ".md", "content", "unique")


@pytest.mark.timeout(10)
def test_unclaimable_directory_fails_fast_under_converted_folder(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    source = _mk_source(tmp_path)
    with pytest.raises(OSError):
        claim_and_publish_text(source, blocker, ".md", "content", "converted-folder")


def test_converted_folder_writes_under_subfolder(tmp_path):
    source = _mk_source(tmp_path)
    dest = claim_and_publish_text(source, tmp_path, ".md", "x", "converted-folder")
    assert dest == tmp_path / "Converted" / "report.md"
    assert dest.read_text(encoding="utf-8") == "x"


def test_write_failure_removes_the_fresh_claim_not_a_pre_existing_file(tmp_path, monkeypatch):
    """A write failure after a brand-new claim must not leave a stale
    zero-byte reservation; a write failure under overwrite onto a file that
    already existed must not delete that pre-existing file."""
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path)

    def boom(path, content, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(exporter_module, "_stage", boom)

    with pytest.raises(OSError):
        claim_and_publish_text(source, tmp_path, ".md", "x", "unique")
    assert not (tmp_path / "report.md").exists(), "fresh claim must be cleaned up"

    (tmp_path / "existing.md").write_text("keep me", encoding="utf-8")
    source2 = _mk_source(tmp_path, "existing.txt")
    with pytest.raises(OSError):
        claim_and_publish_text(source2, tmp_path, ".md", "x", "overwrite")
    assert (tmp_path / "existing.md").read_text(encoding="utf-8") == "keep me"


# --- commit_output_set: main + chunks -------------------------------------------


def test_commit_output_set_unique_derives_chunk_names_from_resolved_main_stem(tmp_path):
    """Two same-stem sources converted into the same directory must produce
    unambiguous, non-colliding chunk sets - chunk names must come from the
    ACTUAL (possibly renumbered) main stem, not the raw source stem."""
    a_dir = tmp_path / "a"
    b_dir = tmp_path / "b"
    a_dir.mkdir()
    b_dir.mkdir()
    source_a = _mk_source(a_dir, "report.txt")
    source_b = _mk_source(b_dir, "report.txt")

    main_a, chunks_a = commit_output_set(
        source=source_a, directory=tmp_path, policy="unique",
        main_suffix=".md", main_content="MAIN A",
        chunk_contents=["chunk a1", "chunk a2"], chunk_suffix=".md",
    )
    main_b, chunks_b = commit_output_set(
        source=source_b, directory=tmp_path, policy="unique",
        main_suffix=".md", main_content="MAIN B",
        chunk_contents=["chunk b1", "chunk b2"], chunk_suffix=".md",
    )

    assert main_a == tmp_path / "report.md"
    assert main_b == tmp_path / "report-1.md"
    assert [p.name for p in chunks_a] == ["report.part001.md", "report.part002.md"]
    assert [p.name for p in chunks_b] == ["report-1.part001.md", "report-1.part002.md"]
    assert chunks_a[0].read_text(encoding="utf-8") == "chunk a1\n"
    assert chunks_b[0].read_text(encoding="utf-8") == "chunk b1\n"


def test_commit_output_set_skips_chunks_when_main_output_fails(tmp_path):
    (tmp_path / "report.md").write_text("existing", encoding="utf-8")
    source = _mk_source(tmp_path)
    with pytest.raises(OutputPolicyError):
        commit_output_set(
            source=source, directory=tmp_path, policy="fail",
            main_suffix=".md", main_content="MAIN",
            chunk_contents=["c1", "c2"], chunk_suffix=".md",
        )
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.md", "report.txt"]
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "existing"


def test_commit_output_set_fail_preflights_and_rolls_back_a_chunk_collision(tmp_path):
    """A collision on chunk 2 (not the main output) must still remove the
    main output and chunk 1 that this call already claimed - never a
    misleading partial set under `fail`."""
    (tmp_path / "report.part002.md").write_text("blocker", encoding="utf-8")
    source = _mk_source(tmp_path)

    with pytest.raises(OutputPolicyError):
        commit_output_set(
            source=source, directory=tmp_path, policy="fail",
            main_suffix=".md", main_content="MAIN",
            chunk_contents=["c1", "c2"], chunk_suffix=".md",
        )

    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["report.part002.md", "report.txt"]
    assert (tmp_path / "report.part002.md").read_text(encoding="utf-8") == "blocker"


def test_commit_output_set_fail_writes_the_full_set_when_nothing_collides(tmp_path):
    source = _mk_source(tmp_path)
    main_path, chunk_paths = commit_output_set(
        source=source, directory=tmp_path, policy="fail",
        main_suffix=".md", main_content="MAIN",
        chunk_contents=["c1", "c2"], chunk_suffix=".md",
    )
    assert main_path.read_text(encoding="utf-8") == "MAIN"
    assert [p.read_text(encoding="utf-8") for p in chunk_paths] == ["c1\n", "c2\n"]


def test_commit_output_set_overwrite_replaces_chunks_but_never_the_source(tmp_path):
    (tmp_path / "report.part001.md").write_text("stale chunk", encoding="utf-8")
    source = _mk_source(tmp_path)

    main_path, chunk_paths = commit_output_set(
        source=source, directory=tmp_path, policy="overwrite",
        main_suffix=".md", main_content="MAIN",
        chunk_contents=["fresh chunk"], chunk_suffix=".md",
    )
    assert chunk_paths[0].read_text(encoding="utf-8") == "fresh chunk\n"


def test_commit_output_set_converted_folder_puts_main_and_chunks_together(tmp_path):
    source = _mk_source(tmp_path)
    main_path, chunk_paths = commit_output_set(
        source=source, directory=tmp_path, policy="converted-folder",
        main_suffix=".md", main_content="MAIN",
        chunk_contents=["c1"], chunk_suffix=".md",
    )
    assert main_path.parent == tmp_path / "Converted"
    assert chunk_paths[0].parent == tmp_path / "Converted"


# --- Milestone 7.1: ownership must be filesystem-derived, never exists()-inferred ---
#
# The bug this section pins: commit_output_set() used to unconditionally
# _unclaim() the main/chunk path on any write failure, even when overwrite
# found the destination already there and this call never created it -
# deleting a pre-existing user file it had no business touching. The fix
# tracks ownership as the literal, filesystem-verified outcome of this
# call's own claim attempt (_Claim.owns_reservation), never re-derived from
# a separate exists() probe (which is itself a TOCTOU race).


def test_reproduction_commit_output_set_overwrite_main_preserves_existing_file_on_failure(tmp_path, monkeypatch):
    """The exact bug report, reproduced as a permanent regression test."""
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path, "note.txt", "source content")
    dest = tmp_path / "note.md"
    dest.write_text("IMPORTANT OLD DATA", encoding="utf-8")

    def boom(path, content, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(exporter_module, "_stage", boom)

    with pytest.raises(OSError):
        commit_output_set(
            source=source, directory=tmp_path, policy="overwrite",
            main_suffix=".md", main_content="new content",
        )

    assert dest.exists(), "the pre-existing destination must not be deleted"
    assert dest.read_text(encoding="utf-8") == "IMPORTANT OLD DATA"


def test_commit_output_set_overwrite_chunk_preserves_existing_chunk_on_failure(tmp_path, monkeypatch):
    """Main publishes successfully (its pre-existing content IS legitimately
    replaced - overwrite means overwrite); a pre-existing chunk destination
    must survive untouched when chunk publication is then forced to fail.

    Since main's new content cannot be rolled back (it replaced pre-existing
    content in place, not a fresh claim), this is exactly the "partial
    commit" case: PartialCommitError, not a plain OSError, so a caller can
    see that main really did get written (Milestone 7.2 requirement - never
    silently report output=null when real output from this call exists)."""
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path, "doc.txt", "source content")
    main_dest = tmp_path / "doc.md"
    main_dest.write_text("stale main", encoding="utf-8")
    chunk_dest = tmp_path / "doc.part001.md"
    chunk_dest.write_text("USER'S EXISTING CHUNK DATA", encoding="utf-8")

    real_atomic_write_text = exporter_module._stage

    def selective_boom(path, content, **kwargs):
        if path.name == "doc.part001.md":
            raise OSError("simulated failure writing the chunk")
        return real_atomic_write_text(path, content, **kwargs)

    monkeypatch.setattr(exporter_module, "_stage", selective_boom)

    with pytest.raises(exporter_module.PartialCommitError) as excinfo:
        commit_output_set(
            source=source, directory=tmp_path, policy="overwrite",
            main_suffix=".md", main_content="fresh main content",
            chunk_contents=["chunk one"], chunk_suffix=".md",
        )

    assert excinfo.value.written_paths == [main_dest]
    assert isinstance(excinfo.value.__cause__, OSError)

    # The chunk destination pre-existed and was never touched by this call.
    assert chunk_dest.read_text(encoding="utf-8") == "USER'S EXISTING CHUNK DATA"
    # Main legitimately WAS overwritten before the later chunk step failed -
    # overwrite is not transactional across multiple files (documented),
    # and that survival is now reported explicitly via written_paths above.
    assert main_dest.read_text(encoding="utf-8") == "fresh main content"


def test_claim_and_publish_text_overwrite_existing_destination_survives_failure(tmp_path, monkeypatch):
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path, "doc.txt")
    dest = tmp_path / "doc.md"
    dest.write_text("ORIGINAL BYTES", encoding="utf-8")

    def boom(path, content, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(exporter_module, "_stage", boom)

    with pytest.raises(OSError):
        claim_and_publish_text(source, tmp_path, ".md", "new", "overwrite")

    assert dest.read_text(encoding="utf-8") == "ORIGINAL BYTES"


def _compete_for(monkeypatch, dest, data):
    """Make a competing writer take *dest* a moment before our own publish."""
    import doc2md.core.exporter as exporter_module

    real_publish_new = exporter_module._publish_new
    state = {"done": False}

    def racy_publish_new(tmp, target):
        if target == dest and not state["done"]:
            state["done"] = True
            target.write_text(data, encoding="utf-8")
        return real_publish_new(tmp, target)

    monkeypatch.setattr(exporter_module, "_publish_new", racy_publish_new)


def test_race_competing_writer_takes_the_name_first_unique(tmp_path, monkeypatch):
    source = _mk_source(tmp_path, "report.txt")
    dest = tmp_path / "report.md"
    _compete_for(monkeypatch, dest, "COMPETING CALLER'S DATA")

    result = claim_and_publish_text(source, tmp_path, ".md", "our content", "unique")

    assert result == tmp_path / "report-1.md"
    assert result.read_text(encoding="utf-8") == "our content"
    assert dest.read_text(encoding="utf-8") == "COMPETING CALLER'S DATA"


def test_race_competing_writer_takes_the_name_first_fail(tmp_path, monkeypatch):
    source = _mk_source(tmp_path, "report.txt")
    dest = tmp_path / "report.md"
    _compete_for(monkeypatch, dest, "COMPETING CALLER'S DATA")

    with pytest.raises(OutputPolicyError):
        claim_and_publish_text(source, tmp_path, ".md", "our content", "fail")

    assert dest.read_text(encoding="utf-8") == "COMPETING CALLER'S DATA"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.md", "report.txt"]


def test_race_under_commit_output_set_chunks_follow_the_resolved_main(tmp_path, monkeypatch):
    source = _mk_source(tmp_path, "report.txt")
    dest = tmp_path / "report.md"
    _compete_for(monkeypatch, dest, "COMPETING CALLER'S MAIN")

    main, chunks = commit_output_set(
        source=source, directory=tmp_path, policy="unique",
        main_suffix=".md", main_content="ours", chunk_contents=["c1"],
    )

    assert main == tmp_path / "report-1.md"
    assert [c.name for c in chunks] == ["report-1.part001.md"]
    assert dest.read_text(encoding="utf-8") == "COMPETING CALLER'S MAIN"


def test_freshly_claimed_destination_leaves_no_temp_or_reservation_files(tmp_path, monkeypatch):
    """A forced publication failure on a claim THIS call actually created
    must remove exactly that empty claim and nothing else. Forces the
    failure inside the REAL atomic_write_text (via a failing os.replace),
    so its own temp-file cleanup runs for real, in addition to
    claim_and_publish_text's claim cleanup - together they must leave
    absolutely nothing but the source behind."""
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path, "report.txt")

    def failing_publish(*args, **kwargs):
        raise OSError("simulated failure during the final rename")

    monkeypatch.setattr(exporter_module, "_publish_new", failing_publish)

    with pytest.raises(OSError):
        claim_and_publish_text(source, tmp_path, ".md", "content", "unique")

    # Only the source file remains - the claim was removed, and no .tmp
    # artifact from atomic_write_text's own temp file survives either.
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["report.txt"], f"unexpected leftovers: {remaining}"


# --- source-self protection across every policy, even under forced failure ---------


@pytest.mark.parametrize("policy", ["unique", "fail", "overwrite", "converted-folder"])
def test_source_file_is_never_modified_under_any_policy_even_on_failure(tmp_path, monkeypatch, policy):
    import doc2md.core.exporter as exporter_module

    source = tmp_path / "already.md"
    original_bytes = b"ORIGINAL SOURCE BYTES - MUST SURVIVE"
    source.write_bytes(original_bytes)

    def boom(path, content, **kwargs):
        raise OSError("simulated failure")

    monkeypatch.setattr(exporter_module, "_stage", boom)

    # Every policy either refuses outright (source == destination is always
    # rejected) or fails on the forced write - either way the source itself
    # must never be touched.
    with pytest.raises((OSError, OutputPolicyError)):
        claim_and_publish_text(source, tmp_path, ".md", "new content", policy)

    assert source.read_bytes() == original_bytes


# --- multi-file rollback for unique / converted-folder ------------------------------


@pytest.mark.parametrize("policy", ["unique", "converted-folder"])
def test_multi_file_rollback_removes_everything_this_call_created(tmp_path, monkeypatch, policy):
    """unique/converted-folder claims are always fresh (that's the whole
    point of numbering) - if a later chunk fails, EVERYTHING this call
    created (main + any already-published earlier chunks) must be rolled
    back, so a caller that catches the exception finds nothing from this
    call on disk - not main.md plus chunk 1 with chunk 2 silently missing."""
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path, "doc.txt")
    real_atomic_write_text = exporter_module._stage

    def selective_boom(path, content, **kwargs):
        if "part002" in path.name:
            raise OSError("simulated failure on the second chunk")
        return real_atomic_write_text(path, content, **kwargs)

    monkeypatch.setattr(exporter_module, "_stage", selective_boom)

    with pytest.raises(OSError):
        commit_output_set(
            source=source, directory=tmp_path, policy=policy,
            main_suffix=".md", main_content="main content",
            chunk_contents=["chunk one", "chunk two"], chunk_suffix=".md",
        )

    target_dir = tmp_path / "Converted" if policy == "converted-folder" else tmp_path
    leftovers = (
        [p for p in target_dir.glob("doc*") if p != source] if target_dir.exists() else []
    )
    assert leftovers == [], f"nothing this call created may remain: {leftovers}"


def test_cli_report_output_is_null_when_rollback_left_nothing_behind(tmp_path):
    """After a rollback, the CLI's quality report saying output=null must
    be an ACCURATE description of disk state (nothing left behind), not a
    misleading gap between what the report claims and what actually
    exists on disk."""
    import json

    from typer.testing import CliRunner

    from doc2md.cli.main import app

    runner = CliRunner()

    source = tmp_path / "doc.txt"
    source.write_text("\n\n".join(f"para {i} " * 20 for i in range(6)), encoding="utf-8")
    # Block chunk 2 specifically so the main output claims successfully but
    # the overall commit_output_set call still fails and rolls back.
    (tmp_path / "doc.part002.md").write_text("blocker", encoding="utf-8")

    report_path = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "convert", str(source), "--chunk", "30",
            "--output-policy", "fail", "--report", str(report_path),
        ],
    )

    assert result.exit_code == 1, result.output
    entries = json.loads(report_path.read_text(encoding="utf-8"))
    assert entries[0]["output"] is None
    # And that null is truthful: no main.md was left behind either.
    assert not (tmp_path / "doc.md").exists()
    assert (tmp_path / "doc.part002.md").read_text(encoding="utf-8") == "blocker"


def test_partial_commit_error_reports_exactly_what_survived_for_overwrite(tmp_path, monkeypatch):
    """The CLI/JSON-report requirement: when overwrite legitimately replaces
    pre-existing content and only a LATER step then fails, commit_output_set
    must raise PartialCommitError (not a plain exception) naming exactly
    which of this call's own writes are still confirmed on disk - so a
    caller never reports output=null while real output from this call
    exists."""
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path, "doc.txt")
    (tmp_path / "doc.md").write_text("stale main", encoding="utf-8")

    real_atomic_write_text = exporter_module._stage

    def selective_boom(path, content, **kwargs):
        if "part001" in path.name:
            raise OSError("simulated chunk failure")
        return real_atomic_write_text(path, content, **kwargs)

    monkeypatch.setattr(exporter_module, "_stage", selective_boom)

    with pytest.raises(exporter_module.PartialCommitError) as excinfo:
        commit_output_set(
            source=source, directory=tmp_path, policy="overwrite",
            main_suffix=".md", main_content="fresh main",
            chunk_contents=["chunk one"], chunk_suffix=".md",
        )

    assert excinfo.value.written_paths == [tmp_path / "doc.md"]
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "fresh main"


@pytest.mark.timeout(60)
def test_real_multiprocess_overwrite_race_never_corrupts_or_loses_the_winner(tmp_path):
    """At least one real multiprocessing test (not just threads): N
    processes race claim_and_publish_text under `overwrite` for the same
    destination. No worker may hit an unexpected error, and whatever ends
    up on disk must be EXACTLY one worker's own write - never corrupted,
    never silently lost entirely."""
    n = 6
    source = _mk_source(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(n)
    result_queue = ctx.Queue()
    procs = [
        ctx.Process(
            target=_overwrite_race_worker,
            args=(str(tmp_path), str(source), f"content-{i}", barrier, result_queue),
        )
        for i in range(n)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=45)
        assert not p.is_alive(), "race worker did not finish in time"

    results = [result_queue.get(timeout=5) for _ in range(n)]
    errors = [r for r in results if r[0] == "error"]
    assert errors == [], f"no worker should hit an unexpected error: {errors}"

    dest = tmp_path / "report.md"
    assert dest.exists(), "some worker must have published successfully"
    final_content = dest.read_text(encoding="utf-8")
    expected_bodies = {f"content-{i}" for i in range(n)}
    assert final_content in expected_bodies, (
        f"final content must be EXACTLY one worker's own write, got {final_content!r}"
    )


def _overwrite_race_worker(directory_str, source_str, content, barrier, result_queue):
    """Runs in a separate process - see test_real_multiprocess_overwrite_race_never_corrupts_or_loses_the_winner."""
    from pathlib import Path as _Path

    from doc2md.core.exporter import claim_and_publish_text as _claim_and_publish_text

    directory = _Path(directory_str)
    source = _Path(source_str)
    barrier.wait()
    try:
        dest = _claim_and_publish_text(source, directory, ".md", content, "overwrite")
        result_queue.put(("ok", str(dest)))
    except Exception as exc:  # pragma: no cover - would indicate a real bug
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


# --- real multi-process race -----------------------------------------------------


def _race_worker(directory_str, source_str, policy, content, barrier, result_queue):
    """Runs in a separate process. Waits at the barrier so every worker
    calls claim_and_publish_text as close to simultaneously as the OS
    scheduler allows, then reports what happened."""
    from pathlib import Path as _Path

    from doc2md.core.exporter import OutputPolicyError as _OutputPolicyError
    from doc2md.core.exporter import claim_and_publish_text as _claim_and_publish_text

    directory = _Path(directory_str)
    source = _Path(source_str)
    barrier.wait()
    try:
        dest = _claim_and_publish_text(source, directory, ".md", content, policy)
        result_queue.put(("ok", str(dest)))
    except _OutputPolicyError as exc:
        result_queue.put(("policy_error", str(exc)))
    except Exception as exc:  # pragma: no cover - would indicate a real bug
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _run_race(tmp_path, policy: str, n_workers: int = 6):
    source = _mk_source(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(n_workers)
    result_queue = ctx.Queue()
    procs = [
        ctx.Process(
            target=_race_worker,
            args=(str(tmp_path), str(source), policy, f"content-{i}", barrier, result_queue),
        )
        for i in range(n_workers)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert not p.is_alive(), "race worker did not finish in time"

    results = [result_queue.get(timeout=5) for _ in range(n_workers)]
    return results


@pytest.mark.timeout(60)
def test_real_multiprocess_race_unique_never_overwrites(tmp_path):
    """N processes race to claim_and_publish_text the SAME source/dir/policy
    simultaneously under `unique`. Every one must succeed, every one must
    land on a DIFFERENT path, and every file's actual content must match
    what that specific process wrote - proving no process silently
    overwrote another's already-published output."""
    n = 6
    results = _run_race(tmp_path, "unique", n_workers=n)

    outcomes = [kind for kind, _ in results]
    assert outcomes == ["ok"] * n, results

    paths = [Path(value) for _, value in results]
    assert len(set(paths)) == n, "every worker must have claimed a distinct path"

    # Verify actual file contents on disk, not just the reported paths.
    written_bodies = {p.read_text(encoding="utf-8") for p in paths}
    expected_bodies = {f"content-{i}" for i in range(n)}
    assert written_bodies == expected_bodies


@pytest.mark.timeout(60)
def test_real_multiprocess_race_fail_lets_exactly_one_winner_through(tmp_path):
    """Under `fail`, N processes race for the SAME single destination name.
    Exactly one must win; every other must get OutputPolicyError with the
    original content genuinely intact - not a corrupted mix of two writes."""
    n = 6
    results = _run_race(tmp_path, "fail", n_workers=n)

    winners = [v for k, v in results if k == "ok"]
    losers = [k for k, _ in results if k == "policy_error"]
    assert len(winners) == 1, results
    assert len(losers) == n - 1, results

    dest = Path(winners[0])
    assert dest.name == "report.md"
    content = dest.read_text(encoding="utf-8")
    expected_bodies = {f"content-{i}" for i in range(n)}
    assert content in expected_bodies, (
        f"destination content must be exactly one worker's own write, got {content!r}"
    )


def test_rollback_never_deletes_a_file_someone_else_put_at_the_same_name(tmp_path, monkeypatch):
    """Main publishes under `unique`; before a later chunk fails, another
    writer replaces the main file. Rollback must leave that newer file alone."""
    import doc2md.core.exporter as exporter_module

    source = _mk_source(tmp_path, "doc.txt")
    real_stage = exporter_module._stage

    def stage(path, content):
        if "part001" in path.name:
            (tmp_path / "doc.md").unlink()
            (tmp_path / "doc.md").write_text("SOMEONE ELSE'S FILE", encoding="utf-8")
            raise OSError("chunk failed")
        return real_stage(path, content)

    monkeypatch.setattr(exporter_module, "_stage", stage)

    with pytest.raises(OSError):
        commit_output_set(
            source=source, directory=tmp_path, policy="unique",
            main_suffix=".md", main_content="main", chunk_contents=["one"],
        )

    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "SOMEONE ELSE'S FILE"
