import hashlib
import subprocess
import sys
import time
from pathlib import Path

from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


def test_directory_scan_with_mixed_files(tmp_path):
    source_dir = tmp_path / "docs_in"
    (source_dir / "nested").mkdir(parents=True)
    (source_dir / "a.txt").write_text("alpha", encoding="utf-8")
    (source_dir / "nested" / "b.log").write_text("beta log", encoding="utf-8")
    (source_dir / "skipme.bin").write_bytes(bytes(range(256)) * 4)

    out = tmp_path / "md_out"
    result = runner.invoke(app, ["convert", str(source_dir), "-o", str(out)])
    assert result.exit_code == 0
    names = {p.name for p in out.glob("*.md")}
    assert names == {"a.md", "b.md"}
    assert (out / "a.md").read_text(encoding="utf-8").strip() != ""


def test_glob_no_match_and_empty_dir_exit_two(tmp_path):
    result = runner.invoke(app, ["convert", str(tmp_path / "none*.xyz")])
    assert result.exit_code == 2

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result2 = runner.invoke(app, ["convert", str(empty_dir)])
    assert result2.exit_code == 2
    assert "No input files found" in result2.output


def test_rich_importerror_falls_back_to_plain_progress(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "rich.progress", None)
    p = tmp_path / "plain.txt"
    p.write_text("no rich here", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "--stdout"])
    assert result.exit_code == 0
    assert "no rich here" in result.output


def test_warning_result_shown_as_warn_not_ok_and_counted_separately(tmp_path, monkeypatch):
    """A conversion that succeeds but carries a warning (Bug B2, e.g. OCR
    unavailable) must show WARN in the per-file log and be called out in the
    summary - never look identical to a plain OK."""
    p = tmp_path / "scan.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

    class SpyConverter:
        def __init__(self, **kwargs):
            pass

        def convert_file(self, target):
            from doc2md.core.converter import ConversionResult

            return ConversionResult(
                source=target, success=True, markdown="# scan.png\n",
                warning="OCR unavailable: neither Tesseract nor RapidOCR is available",
            )

    import doc2md.cli.main as cli_mod

    original = cli_mod.Converter
    cli_mod.Converter = SpyConverter
    try:
        result = runner.invoke(app, ["convert", str(p)])
    finally:
        cli_mod.Converter = original

    assert result.exit_code == 0, result.output
    assert "WARN" in result.output
    assert "OCR unavailable" in result.output
    assert "with warnings" in result.output
    assert "OK " not in result.output.replace("WARN ", "")


def test_mixed_batch_summary_yellow_and_ignore_errors(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("fine content", encoding="utf-8")
    bad = tmp_path / "bad.bin"
    bad.write_bytes(bytes(range(256)) * 8)
    result = runner.invoke(app, ["convert", str(good), str(bad)])
    assert result.exit_code == 1
    assert "1 failed" in result.output
    result_ok = runner.invoke(
        app, ["convert", str(good), str(bad), "--ignore-errors"]
    )
    assert result_ok.exit_code == 0


# --- output must never overwrite the source (Bug A1) ------------------------


def test_converting_a_dot_md_file_does_not_overwrite_the_source(tmp_path):
    """A .md source and its .md output share a suffix; the CLI must not clobber it.

    This is the exact mechanism that corrupted this project's own README.md,
    CHANGELOG.md and HISTORY.md: `source.with_suffix(".md")` on a file already
    named `*.md` resolves to the source path itself.
    """
    source = tmp_path / "notes.md"
    original = "# Original heading\n\nOriginal body text.\n"
    source.write_text(original, encoding="utf-8", newline="")
    original_bytes = source.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()

    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 0, result.output

    assert source.read_bytes() == original_bytes
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash

    sibling_outputs = sorted(p.name for p in tmp_path.glob("notes*.md") if p.name != "notes.md")
    assert sibling_outputs == ["notes-1.md"], sibling_outputs


def test_converting_the_same_dot_md_file_twice_creates_dash_2_not_a_wrapped_copy(tmp_path):
    """Running convert repeatedly (e.g. a mirror/watch process) must keep
    appending -1, -2, ... rather than re-wrapping an already-produced output."""
    source = tmp_path / "doc.md"
    source.write_text("# doc\n\nbody\n", encoding="utf-8")

    runner.invoke(app, ["convert", str(source)])
    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 0, result.output

    produced = sorted(p.name for p in tmp_path.glob("doc*.md") if p.name != "doc.md")
    assert produced == ["doc-1.md", "doc-2.md"], produced
    # Neither generated file re-wraps the other in a fence.
    for name in produced:
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert text.count("```") <= 2


def test_batch_same_stem_different_folders_all_written_to_shared_output(tmp_path):
    """Two source files with the same stem but different parent folders must
    both survive when funneled into one --output directory."""
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    (folder_a / "report.txt").write_text("report from a", encoding="utf-8")
    (folder_b / "report.txt").write_text("report from b", encoding="utf-8")

    out = tmp_path / "out"
    result = runner.invoke(
        app,
        ["convert", str(folder_a / "report.txt"), str(folder_b / "report.txt"), "-o", str(out)],
    )
    assert result.exit_code == 0, result.output

    written = sorted(p.name for p in out.glob("*.md"))
    assert written == ["report-1.md", "report.md"]
    contents = {p.read_text(encoding="utf-8") for p in out.glob("*.md")}
    assert any("report from a" in c for c in contents)
    assert any("report from b" in c for c in contents)


def test_write_failure_is_reported_as_a_failure_and_exits_nonzero(tmp_path, monkeypatch):
    """If the converted markdown cannot be written to disk, the run must not
    report success for that file or exit 0."""
    source = tmp_path / "ok.txt"
    source.write_text("fine content", encoding="utf-8")

    import doc2md.core.exporter as exporter_module
    original_atomic_write_text = exporter_module._stage

    def flaky_atomic_write_text(path, *args, **kwargs):
        if path.name == "ok.md":
            raise OSError("simulated disk full")
        return original_atomic_write_text(path, *args, **kwargs)

    monkeypatch.setattr(exporter_module, "_stage", flaky_atomic_write_text)

    result = runner.invoke(app, ["convert", str(source)])
    assert result.exit_code == 1, result.output
    assert "could not write output" in result.output
    assert "0 converted" not in result.output or "1 failed" in result.output


def test_stats_after_write_failure_does_not_show_the_failed_file_as_success(
    tmp_path, monkeypatch
):
    """Bug #7: --stats built its table from the original conversion results,
    unfiltered by write outcome, so a document that failed to reach disk
    could still show up as a successful row with size/token metrics."""
    good = tmp_path / "good.txt"
    good.write_text("fine content", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("also converts fine, but writing it will fail", encoding="utf-8")

    import doc2md.core.exporter as exporter_module
    original_atomic_write_text = exporter_module._stage

    def flaky_atomic_write_text(path, *args, **kwargs):
        if path.name == "bad.md":
            raise OSError("simulated disk full")
        return original_atomic_write_text(path, *args, **kwargs)

    monkeypatch.setattr(exporter_module, "_stage", flaky_atomic_write_text)

    result = runner.invoke(app, ["convert", str(good), str(bad), "--stats"])
    assert result.exit_code == 1, result.output

    # "bad.txt" legitimately appears in the per-file progress/FAIL log lines
    # ("[2/2] OK bad.txt", "FAIL bad.txt -> could not write output..."); what
    # must NOT happen is a *stats table row* for it, since that table only
    # exists to describe documents that actually reached disk.
    lines = result.output.splitlines()
    header_idx = next(
        i for i, line in enumerate(lines) if line.startswith("File") and "Original" in line
    )
    table_rows = []
    for line in lines[header_idx + 2:]:
        if not line.strip() or line.startswith(("Done:", "Cancelled")):
            break
        table_rows.append(line)

    assert any(row.startswith("good.txt") for row in table_rows)
    assert not any(row.startswith("bad.txt") for row in table_rows), (
        f"a file that failed to write must not appear as a stats row: {table_rows}"
    )
    assert "1 converted" in result.output
    assert "1 failed" in result.output


def test_clipboard_after_write_failure_excludes_the_failed_document(tmp_path, monkeypatch):
    """The clipboard payload must reflect the same final state as --stats
    and the exit code - a write-failed document's content must not be
    copied as if it were a successful result."""
    good = tmp_path / "good.txt"
    good.write_text("fine content", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("BADCONTENTMARKER", encoding="utf-8")

    import doc2md.core.exporter as exporter_module
    original_atomic_write_text = exporter_module._stage

    def flaky_atomic_write_text(path, *args, **kwargs):
        if path.name == "bad.md":
            raise OSError("simulated disk full")
        return original_atomic_write_text(path, *args, **kwargs)

    monkeypatch.setattr(exporter_module, "_stage", flaky_atomic_write_text)

    import sys
    import types

    copied = {}

    def fake_copy(text):
        copied["text"] = text

    monkeypatch.setitem(sys.modules, "pyperclip", types.SimpleNamespace(copy=fake_copy))

    result = runner.invoke(app, ["convert", str(good), str(bad), "--copy"])

    assert result.exit_code == 1, result.output
    assert "BADCONTENTMARKER" not in copied.get("text", "")


def test_chunk_output_avoids_collisions_across_same_stem_batch(tmp_path):
    """Chunk parts must be named from the ACTUAL resolved main-output stem
    (which the second same-stem source bumps to "doc-1" under `unique`), not
    from the raw source stem shared by both - so two same-stem sources
    funneled into one --output dir get two unambiguous, non-colliding chunk
    sets rather than one chunk set with a same-directory numbering suffix
    tacked onto individual part filenames."""
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    folder_a.mkdir()
    folder_b.mkdir()
    body = "\n\n".join(f"## Section {i}\n\n{'lorem ipsum dolor sit amet ' * 20}" for i in range(4))
    (folder_a / "doc.txt").write_text("A: " + body, encoding="utf-8")
    (folder_b / "doc.txt").write_text("B: " + body, encoding="utf-8")

    out = tmp_path / "chunks"
    result = runner.invoke(
        app,
        [
            "convert",
            str(folder_a / "doc.txt"),
            str(folder_b / "doc.txt"),
            "--chunk", "120",
            "-o", str(out),
        ],
    )
    assert result.exit_code == 0, result.output

    parts = sorted(p.name for p in out.glob("*.part*.md"))
    # No two parts share a filename; both sources' chunks are all present.
    assert len(parts) == len(set(parts))
    assert any(name == "doc.part001.md" for name in parts)
    # The second same-stem source's main output was renumbered to "doc-1.md"
    # (same `unique` resolver as any other collision), so its chunks are
    # named from THAT stem - never colliding with the first source's chunks.
    assert any(name.startswith("doc-1.part001") for name in parts)
    assert (out / "doc.md").exists()
    assert (out / "doc-1.md").exists()


# --- empty-input hang (reviewer bug #1) --------------------------------------


def test_empty_string_input_is_rejected_not_treated_as_current_directory(tmp_path):
    """Path("") normalizes to Path("."), which previously made an empty CLI
    argument silently mean "recursively scan the whole current directory" -
    this test only proves it's REJECTED, not that it scans fast (the
    subprocess test below is the real hang guard)."""
    result = runner.invoke(app, ["convert", ""])
    assert result.exit_code != 0
    assert "empty" in result.output.lower()


def test_whitespace_only_input_is_rejected(tmp_path):
    result = runner.invoke(app, ["convert", "   "])
    assert result.exit_code != 0


def test_dot_is_still_a_valid_explicit_current_directory(tmp_path, monkeypatch):
    """An intentional "." must keep working - only emptiness is rejected."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["convert", "."])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "a.md").is_file()


def test_empty_input_via_real_subprocess_exits_fast_with_no_output(tmp_path):
    """Real hang guard: runs doc2md as an actual subprocess (not in-process
    CliRunner) from inside a large real directory tree (this repository),
    with a hard timeout. Before the fix, Path("") -> Path(".") made
    _expand_targets() recursively rglob the entire repo (tens of thousands of
    files after the mirror-duplication bug), which could take long enough to
    look hung in CI. subprocess.run's own timeout turns a regression into a
    clean test failure instead of hanging the whole suite."""
    repo_root = Path(__file__).resolve().parent.parent

    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "doc2md", "convert", ""],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=20,
    )
    elapsed = time.monotonic() - start

    assert result.returncode != 0
    assert elapsed < 10, f"empty input took {elapsed:.1f}s - should reject instantly"
    assert not list(tmp_path.glob("*.md")), "empty input must not produce any output"


# --- recursive folder scan must not re-ingest generated Markdown (bug #2) ---


def test_recursive_folder_scan_excludes_md_files(tmp_path):
    """A stray .md file sitting in a recursively-scanned folder (e.g. this
    tool's own previous output) must not be picked up as input."""
    source_dir = tmp_path / "docs_in"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("alpha", encoding="utf-8")
    (source_dir / "existing.md").write_text("# already markdown\n", encoding="utf-8")

    out = tmp_path / "md_out"
    result = runner.invoke(app, ["convert", str(source_dir), "-o", str(out)])
    assert result.exit_code == 0, result.output

    written = {p.name for p in out.glob("*.md")}
    assert written == {"a.md"}, f"existing.md must not be re-ingested, got {written}"
    # The source folder itself must be untouched - no new .md appeared there.
    assert sorted(p.name for p in source_dir.iterdir()) == ["a.txt", "existing.md"]


def test_repeated_recursive_folder_conversion_does_not_grow_a_chain(tmp_path):
    """Running the exact same folder conversion multiple times (simulating a
    mirror/watch process re-triggering) must never create file-1-1.md style
    chains in the SOURCE tree - the defining symptom of the original bug."""
    source_dir = tmp_path / "watched"
    source_dir.mkdir()
    (source_dir / "doc.txt").write_text("content", encoding="utf-8")

    out = tmp_path / "out"
    for _ in range(4):
        result = runner.invoke(app, ["convert", str(source_dir), "-o", str(out)])
        assert result.exit_code == 0, result.output

    source_names = sorted(p.name for p in source_dir.iterdir())
    assert source_names == ["doc.txt"], (
        f"source tree must never accumulate .md files, got {source_names}"
    )
    # No chain like doc-1-1.md, doc-1-1-1.md anywhere.
    chain_pattern_hits = [
        p.name for p in tmp_path.rglob("*.md") if p.name.count("-1") > 1
    ]
    assert not chain_pattern_hits, f"found a growing chain: {chain_pattern_hits}"


def test_explicit_md_file_argument_still_converts(tmp_path):
    """An explicitly-named .md file (not discovered via folder recursion)
    must still be accepted as input - only the implicit recursive-scan path
    excludes .md."""
    source = tmp_path / "explicit.md"
    source.write_text("# Explicit\n\nbody\n", encoding="utf-8")

    out = tmp_path / "out"
    result = runner.invoke(app, ["convert", str(source), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "explicit.md").read_text(encoding="utf-8") == "# Explicit\n\nbody\n"


# --- bridge command must not silently forward OCR-warning results (bug #5) -


def _spy_convert_with_warning(warning):
    class SpyConverter:
        def __init__(self, **kwargs):
            pass

        def convert_file(self, target):
            from doc2md.core.converter import ConversionResult

            return ConversionResult(
                source=target,
                success=True,
                markdown="# scan\n\n> no text",
                warning=warning,
            )

    return SpyConverter


def test_bridge_excludes_warning_result_by_default_and_reports_it(tmp_path):
    p = tmp_path / "scan.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    inbox = tmp_path / "inbox"

    import doc2md.cli.main as cli_mod

    original = cli_mod.Converter
    cli_mod.Converter = _spy_convert_with_warning("OCR unavailable: no backend")
    try:
        result = runner.invoke(app, ["bridge", str(p), "--inbox", str(inbox)])
    finally:
        cli_mod.Converter = original

    assert "WARN" in result.output
    assert "excluded from bridge" in result.output
    # The only document was excluded, so there is nothing to send - no
    # manifest.json (i.e. no completed bundle) may exist anywhere in inbox.
    assert result.exit_code == 1
    assert not list(inbox.rglob("manifest.json"))


def test_bridge_include_warnings_flag_sends_and_carries_the_warning(tmp_path):
    p = tmp_path / "scan.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    inbox = tmp_path / "inbox"

    import doc2md.cli.main as cli_mod

    original = cli_mod.Converter
    cli_mod.Converter = _spy_convert_with_warning("OCR unavailable: no backend")
    try:
        result = runner.invoke(
            app, ["bridge", str(p), "--inbox", str(inbox), "--include-warnings"]
        )
    finally:
        cli_mod.Converter = original

    assert result.exit_code == 0, result.output
    assert "sent to bridge anyway" in result.output

    import json

    manifest_path = next(inbox.glob("doc2md-*/manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["documents"][0]["warning"] == "OCR unavailable: no backend"


def test_output_subtree_inside_input_directory_is_excluded_from_rescan(tmp_path):
    """When --output is a subdirectory of the folder being recursively
    converted, that output subtree must not be scanned as input even for
    non-.md file types the resolver might place there."""
    source_dir = tmp_path / "project"
    source_dir.mkdir()
    (source_dir / "doc.txt").write_text("content", encoding="utf-8")
    nested_out = source_dir / "generated"

    for _ in range(3):
        result = runner.invoke(app, ["convert", str(source_dir), "-o", str(nested_out)])
        assert result.exit_code == 0, result.output

    # Only the original doc.txt lives directly under source_dir (besides the
    # output subfolder); nothing was re-ingested from `generated/`.
    top_level = sorted(p.name for p in source_dir.iterdir())
    assert top_level == ["doc.txt", "generated"]


# --- output-subtree exclusion must not over-exclude (regression) -----------
#
# `_expand_targets([Path("tests")], output=Path("tests"))` previously
# returned zero targets: `_is_within(candidate, output_root)` is trivially
# true for every candidate whenever output_root equals (or is an ancestor
# of) the directory being scanned, since every candidate found under that
# directory is "within" it by definition. The subtree exclusion must only
# fire when output is a genuine descendant of the specific directory being
# recursively scanned.


def test_expand_targets_output_equal_to_input_still_scans_normally():
    from doc2md.cli.main import _expand_targets

    targets = _expand_targets([Path("tests")], output=Path("tests"))
    assert len(targets) > 0, "output == input must not exclude every file"
    assert any(p.name == "test_cli.py" for p in targets)


def test_expand_targets_output_as_child_of_input_excludes_only_that_subtree(tmp_path):
    from doc2md.cli.main import _expand_targets

    source_dir = tmp_path / "project"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("alpha", encoding="utf-8")
    nested_out = source_dir / "generated"
    nested_out.mkdir()
    (nested_out / "b.txt").write_text("beta", encoding="utf-8")

    targets = _expand_targets([source_dir], output=nested_out)
    names = {p.name for p in targets}
    assert names == {"a.txt"}, f"expected only a.txt, got {names}"


def test_expand_targets_output_outside_input_excludes_nothing(tmp_path):
    from doc2md.cli.main import _expand_targets

    source_dir = tmp_path / "project"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("alpha", encoding="utf-8")
    unrelated_out = tmp_path / "elsewhere"

    targets = _expand_targets([source_dir], output=unrelated_out)
    names = {p.name for p in targets}
    assert names == {"a.txt"}


def test_expand_targets_multiple_inputs_output_equal_to_one_of_them(tmp_path):
    """Converting two directories together where --output happens to equal
    one of the input directories must still scan both directories fully -
    output==input is a no-op for exclusion purposes (the .md-suffix
    exclusion is what actually prevents re-ingesting generated output)."""
    from doc2md.cli.main import _expand_targets

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "a.txt").write_text("alpha", encoding="utf-8")
    (dir_b / "b.txt").write_text("beta", encoding="utf-8")

    targets = _expand_targets([dir_a, dir_b], output=dir_b)
    names = {p.name for p in targets}
    assert names == {"a.txt", "b.txt"}, f"expected both files, got {names}"


def test_output_equal_to_input_directory_end_to_end(tmp_path):
    """CLI-level: `doc2md convert <dir> -o <dir>` must still convert the
    directory's files, not silently produce zero output."""
    source_dir = tmp_path / "project"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("alpha content", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source_dir), "-o", str(source_dir)])
    assert result.exit_code == 0, result.output
    assert (source_dir / "a.md").is_file()
