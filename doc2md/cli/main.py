"""Command-line interface for doc2md (typer)."""

from __future__ import annotations

import sys
from pathlib import Path
import os
from typing import List, Optional

import typer

from doc2md import __version__
from doc2md.core.chunker import chunk_markdown
from doc2md.core.config import load_config
from doc2md.core.converter import Converter, ConversionResult
from doc2md.core.exporter import (
    OutputPolicy,
    OutputPolicyError,
    PartialCommitError,
    commit_output_set,
)
from doc2md.core.quality import build_report, write_report_atomic
from doc2md.core.router import (
    CODE_EXTENSIONS,
    EXTENSION_KINDS,
    IMAGE_EXTENSIONS,
    RECURSIVE_SCAN_EXCLUDED_SUFFIXES,
)
from doc2md.core.stats import build_rows, render_table
from doc2md.engine.ocr_engine import DEFAULT_OCR_LANG

app = typer.Typer(
    name="doc2md",
    help="Convert documents (PDF/DOCX/XLSX/PPTX/HTML/EML/images/code) to clean Markdown.",
    no_args_is_help=False,
    add_completion=False,
)

SUPPORTED_SUFFIXES = frozenset(EXTENSION_KINDS) | frozenset(IMAGE_EXTENSIONS) | frozenset(CODE_EXTENSIONS)


def _effective_policy(
    requested: Optional[OutputPolicy], source: Path, directory: Path, written: set[str]
) -> OutputPolicy:
    """The policy for one document when ``--output-policy`` was not given.

    Re-running refreshes the existing output, so the default is ``overwrite``.
    It must never destroy another document of the same run, so a name this run
    already wrote - two ``report.*`` files from different folders sharing one
    ``--output`` - is numbered instead. A ``.md`` source converted beside
    itself would target its own path, which ``overwrite`` refuses, so that case
    is numbered too.
    """
    if requested is not None:
        return requested
    candidate = os.path.normcase(str((directory / f"{source.stem}.md").resolve()))
    if candidate in written:
        return OutputPolicy.UNIQUE
    if source.suffix.lower() == ".md" and directory.resolve() == source.parent.resolve():
        return OutputPolicy.UNIQUE
    return OutputPolicy.OVERWRITE


def _is_within(path: Path, ancestor: Path) -> bool:
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


def _validate_nonempty_inputs(raw_inputs: List[str]) -> List[Path]:
    """Reject empty/whitespace-only path arguments before they ever become a
    ``Path``. ``Path("")`` normalizes to ``Path(".")`` - the current directory
    - so an accidentally empty argument (e.g. an unset shell variable
    interpolated into the command line) silently turned into "recursively
    convert the entire repository" instead of a clear error. A user who
    genuinely types "." is unaffected: that string is not empty.
    """
    resolved: list[Path] = []
    for raw in raw_inputs:
        if not raw or not raw.strip():
            typer.secho(
                "Empty or whitespace-only path argument is not allowed.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=2)
        resolved.append(Path(raw))
    return resolved


def configure_stdio() -> None:
    """Force UTF-8 on stdout/stderr so Thai filenames can be printed.

    A Windows console defaults to a legacy code page (cp874/cp1252), and
    printing a Thai filename to it raises UnicodeEncodeError *from inside the
    progress line*, which aborted the whole run after the files had already
    been converted. Reconfiguring with errors="replace" means the worst case is
    a few replacement characters in the log rather than a failed command.

    Streams are None in a --windowed frozen build, and reconfigure() does not
    exist on a replaced stream (pytest's capture object), so both are guarded.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        if (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


configure_stdio()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"doc2md {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    pass


def _expand_targets(inputs: List[Path], *, output: Optional[Path] = None) -> List[Path]:
    """Resolve *inputs* (files, directories, globs) into concrete file paths.

    A recursive directory scan excludes ``.md`` files (see
    ``RECURSIVE_SCAN_EXCLUDED_SUFFIXES``) and, when *output* is given and
    resolves to somewhere inside a scanned directory, excludes that output
    subtree too - so pointing a recursive conversion at a folder that also
    holds this run's own destination cannot re-ingest what it just wrote.
    """
    targets: list[Path] = []
    seen: set[str] = set()
    output_root = output.resolve() if output else None

    def _push(path: Path) -> None:
        key = str(path.resolve()).lower()
        if key not in seen:
            seen.add(key)
            targets.append(path)

    for item in inputs:
        text = str(item)
        if any(ch in text for ch in "*?"):
            pattern_path = Path(text)
            base = pattern_path.parent if pattern_path.is_absolute() else Path()
            matches = sorted(base.glob(pattern_path.name if pattern_path.is_absolute() else text))
            if not matches:
                typer.secho(f"Pattern matched nothing: {text}", fg=typer.colors.RED)
            for match in matches:
                if match.is_file():
                    _push(match)
        elif item.is_dir():
            item_root = item.resolve()
            # Only exclude the output subtree when `output` is genuinely
            # NESTED INSIDE this specific directory being scanned - not when
            # output equals the directory itself, and not when output is an
            # ancestor of it (both of those previously made `_is_within`
            # trivially true for every candidate, excluding 100% of files:
            # `_expand_targets([Path("tests")], output=Path("tests"))`
            # returned zero targets). When output == input, the directory
            # must still be scanned normally - the separate .md-suffix
            # exclusion above is what actually prevents re-ingesting this
            # run's own output, regardless of where it lands.
            exclude_root = (
                output_root
                if output_root is not None
                and output_root != item_root
                and _is_within(output_root, item_root)
                else None
            )
            for candidate in sorted(item.rglob("*")):
                if not candidate.is_file():
                    continue
                suffix = candidate.suffix.lower()
                if suffix not in SUPPORTED_SUFFIXES or suffix in RECURSIVE_SCAN_EXCLUDED_SUFFIXES:
                    continue
                if exclude_root is not None and _is_within(candidate.resolve(), exclude_root):
                    continue
                _push(candidate)
        else:
            _push(item)
    return targets


@app.command()
def convert(
    inputs: List[str] = typer.Argument(..., help="Files, directories, or glob patterns."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output directory (default: next to each source file)."
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", "-t", min=0.1,
        help="Hard per-file conversion timeout in seconds.",
    ),
    max_rows: Optional[int] = typer.Option(
        None, "--max-rows", min=1,
        help="Row limit before spreadsheets switch to a truncated summary.",
    ),
    copy: Optional[bool] = typer.Option(
        None, "--copy", "-c",
        help="Copy the resulting Markdown to the Windows clipboard.",
    ),
    stats: Optional[bool] = typer.Option(
        None, "--stats", "-s", help="Print token metrics and size savings."
    ),
    chunk: Optional[int] = typer.Option(
        None, "--chunk", min=1,
        help="Split output into semantic chunks of at most this many tokens.",
    ),
    ocr_lang: Optional[str] = typer.Option(
        None, "--ocr-lang",
        help="Tesseract language string used for scanned PDFs and images "
             "(default: doc2md.toml's ocr_lang, else tha+eng).",
    ),
    no_tables: Optional[bool] = typer.Option(
        None, "--no-tables", help="Skip PDF table extraction (faster, text only). "
             "Overrides doc2md.toml's pdf_tables when given.",
    ),
    include_hidden: bool = typer.Option(
        False, "--include-hidden",
        help="Also convert worksheets that are hidden in an Excel file "
             "(skipped by default, with a note naming them).",
    ),
    stdout: bool = typer.Option(False, "--stdout", help="Print Markdown to stdout instead of writing files."),
    ignore_errors: bool = typer.Option(False, "--ignore-errors", help="Exit 0 even if some files fail."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output."),
    report: Optional[Path] = typer.Option(
        None, "--report",
        help="Write a structured JSON quality report (one entry per document, "
             "written atomically) to this path.",
    ),
    output_policy: Optional[OutputPolicy] = typer.Option(
        None, "--output-policy",
        help="How to resolve an output file that may already exist: "
             "overwrite (default: re-running refreshes <name>.md in place; a .md "
             "source is numbered instead, never overwritten), "
             "unique (never overwrites - appends -1, -2, ...), "
             "fail (error out instead of writing over anything), "
             "converted-folder (write into a Converted subfolder).",
    ),
):
    """Convert one or many documents into Markdown."""
    resolved_inputs = _validate_nonempty_inputs(inputs)

    config_warning = []

    def _warn(message: str) -> None:
        config_warning.append(message)

    cfg = load_config(on_error=_warn)
    if config_warning and not quiet:
        typer.secho(
            f"ignoring unreadable config ({config_warning[0]}); using defaults.",
            fg=typer.colors.YELLOW,
        )

    effective_timeout = timeout if timeout is not None else float(cfg["timeout"])
    effective_max_rows = max_rows if max_rows is not None else int(cfg["max_rows"])
    effective_copy = copy if copy is not None else bool(cfg["default_copy"])
    effective_stats = stats if stats is not None else bool(cfg["stats"])
    effective_chunk = chunk if chunk is not None else cfg["chunk"]
    # CLI > config > default: no_tables/ocr_lang default to None (not given)
    # so an unset flag falls through to doc2md.toml rather than silently
    # forcing the built-in default and ignoring the config file.
    effective_pdf_tables = (not no_tables) if no_tables is not None else bool(cfg["pdf_tables"])
    effective_ocr_lang = ocr_lang if ocr_lang else cfg["ocr_lang"]

    converter = Converter(
        timeout=effective_timeout,
        options={
            "max_rows": effective_max_rows,
            "pdf_ocr_fallback": bool(cfg["ocr_enabled"]),
            "pdf_tables": effective_pdf_tables,
            "ocr_lang": effective_ocr_lang,
            "include_hidden_sheets": include_hidden,
        },
    )
    targets = _expand_targets(resolved_inputs, output=output)
    if not targets:
        typer.secho("No input files found.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    if output is not None and not quiet:
        output_root = output.resolve()
        for item in resolved_inputs:
            if item.is_dir() and _is_within(output_root, item.resolve()):
                typer.secho(
                    f"Note: --output {output} is inside the input folder {item} "
                    "(already excluded from this run's own scan).",
                    fg=typer.colors.YELLOW,
                )
                break

    results: list[ConversionResult] = []
    total = len(targets)
    iterator = enumerate(targets, start=1)
    if not quiet:
        try:
            from rich.progress import track

            iterator = enumerate(track(targets, description="Converting..."), start=1)
        except ImportError:
            pass

    for index, target in iterator:
        result = converter.convert_file(target)
        results.append(result)
        if not quiet:
            if not result.success:
                status_word, detail = "FAIL", f" -> {result.error}"
            elif result.warning:
                # Technically produced output, but not a real read of the
                # document (OCR unavailable/disabled/no text) - must not
                # look identical to a genuine Success in the log.
                status_word, detail = "WARN", f" -> {result.warning}"
            else:
                status_word, detail = "OK ", ""
            typer.echo(f"[{index}/{total}] {status_word} {target.name}{detail}")

    failures = [r for r in results if r.success is False]
    successes = [r for r in results if r.success]

    if stdout:
        for result in successes:
            typer.echo(result.markdown)

    written = 0
    part_count = 0
    output_paths: dict[int, Path] = {}
    written_this_run: set[str] = set()
    if not stdout:
        for result in successes:
            directory = output if output else result.source.parent
            chunk_pieces = (
                chunk_markdown(result.markdown, int(effective_chunk))
                if effective_chunk else None
            )
            try:
                # One shared, policy-aware commit for the main output AND
                # its chunk parts (if any) - chunks are never attempted if
                # the main output itself fails to claim/write, and under
                # `fail` the whole set (main + every chunk) is preflighted
                # before any of it is written, so a chunk-name collision
                # can never leave a misleading partial conversion behind.
                destination, chunk_paths = commit_output_set(
                    source=result.source,
                    directory=directory,
                    policy=_effective_policy(
                        output_policy, result.source, directory, written_this_run
                    ),
                    main_suffix=".md",
                    main_content=result.markdown,
                    chunk_contents=chunk_pieces,
                    chunk_suffix=".md",
                )
                output_paths[id(result)] = destination
                for written_path in (destination, *chunk_paths):
                    written_this_run.add(os.path.normcase(str(written_path.resolve())))
            except PartialCommitError as exc:
                # The commit as a whole still failed (chunks are incomplete
                # or main claim/publish never finished), but rollback could
                # not undo everything this call itself wrote - typically an
                # `overwrite` destination that already existed and had its
                # content replaced in place before a later step failed.
                # Record that surviving path so the report's output field
                # is not falsely null for a result that has real, if
                # partial, output on disk.
                result.success = False
                result.error = f"partial output only - could not write full output set: {exc}"
                output_paths[id(result)] = exc.written_paths[0]
                if not quiet:
                    typer.secho(f"FAIL {result.source.name} -> {result.error}", fg=typer.colors.RED)
                continue
            except (OSError, OutputPolicyError) as exc:
                # Mutate the SAME ConversionResult object referenced in
                # `results` so every downstream consumer - stats, exit code,
                # clipboard, chunk output - reflects one final state instead
                # of each applying its own separate write-failure filter.
                # Previously `--stats` read the original `results` list
                # unfiltered and could show Success for a document that had
                # actually failed to reach disk.
                result.success = False
                result.error = f"could not write output: {exc}"
                if not quiet:
                    typer.secho(f"FAIL {result.source.name} -> {result.error}", fg=typer.colors.RED)
                continue
            written += 1
            part_count += len(chunk_paths)

        # Re-derive from `results` now that write failures have been folded
        # in - `successes`/`failures` must agree with what `results` (and
        # therefore --stats) actually says from this point on.
        failures = [r for r in results if r.success is False]
        successes = [r for r in results if r.success]

    chunk_note = f", {part_count} chunk file(s)" if effective_chunk else ""

    clipboard_note = ""
    if effective_copy:
        payload = "\n\n---\n\n".join(r.markdown for r in successes)
        if not successes or not payload.strip():
            typer.echo("Nothing to copy")
        else:
            from doc2md.core.clipboard import copy_text

            ok, message = copy_text(payload)
            if ok:
                suffix = " (concatenated)" if len(successes) > 1 else ""
                clipboard_note = " [clipboard]"
                if not quiet:
                    typer.echo(f"Copied Markdown to clipboard{suffix}.")
            else:
                typer.secho(f"Clipboard error: {message}", fg=typer.colors.RED)

    if effective_stats:
        table = render_table(build_rows(results))
        if table.strip():
            typer.echo(table)

    tokens_total = sum(r.token_estimate for r in successes)
    warned = [r for r in successes if r.warning]
    if quiet:
        summary = f"{len(successes)}/{len(results)}"
        if warned:
            summary += f" ({len(warned)} warn)"
        if effective_chunk:
            summary += f"+{part_count}"
    else:
        warn_note = f", {len(warned)} with warnings" if warned else ""
        summary = (
            f"Done: {len(successes)} converted{warn_note}, {len(failures)} failed, "
            f"{written} file(s) written{chunk_note}, ~{tokens_total:,} tokens produced."
        )
    typer.secho(
        summary + clipboard_note,
        fg=typer.colors.GREEN if not failures and not warned else typer.colors.YELLOW,
    )

    if report is not None:
        entries = [
            build_report(result, output_path=output_paths.get(id(result)))
            for result in results
        ]
        try:
            write_report_atomic(entries, report)
        except OSError as exc:
            typer.secho(
                f"Error: could not write quality report to {report}: {exc}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=1)
        if not quiet:
            typer.echo(f"Quality report written to {report}")

    if failures and not ignore_errors:
        raise typer.Exit(code=1)


@app.command("install-context-menu")
def install_context_menu_command() -> None:
    """Register 'Convert to Markdown' in the Windows right-click menu (HKCU only)."""
    from doc2md.core import contextmenu

    try:
        message = contextmenu.install()
    except contextmenu.ContextMenuError as exc:
        typer.secho(f"Failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    typer.secho(message, fg=typer.colors.GREEN)
    typer.echo(f"HKEY_CURRENT_USER\\{contextmenu.MENU_KEY_PATH}")
    typer.echo(contextmenu.get_command())


@app.command("uninstall-context-menu")
def uninstall_context_menu_command() -> None:
    """Remove the doc2md entries from the Windows right-click menu."""
    from doc2md.core import contextmenu

    try:
        message = contextmenu.uninstall()
    except contextmenu.ContextMenuError as exc:
        typer.secho(f"Failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    if "removed" in message.lower():
        typer.secho(message, fg=typer.colors.GREEN)
    else:
        typer.echo(message)


@app.command("context-menu-status")
def context_menu_status_command() -> None:
    """Show whether the Explorer context-menu entry is registered."""
    from doc2md.core import contextmenu

    typer.echo(contextmenu.status())


@app.command("gui")
def gui_command() -> None:
    """Launch the PyQt6 desktop interface for drag-and-drop conversion."""
    try:
        from doc2md.gui import run_gui
    except ImportError as exc:
        typer.secho(
            f"GUI dependencies missing: {exc}\n"
            "Install via: pip install -r requirements.txt (PyQt6)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    raise typer.Exit(code=run_gui())


@app.command("bridge")
def bridge_command(
    inputs: List[str] = typer.Argument(..., help="Files, directories, or glob patterns."),
    inbox: Path = typer.Option(
        ..., "--inbox", "-i",
        help="Folder the downstream tool watches; the bundle is written there.",
    ),
    endpoint: Optional[str] = typer.Option(
        None, "--endpoint",
        help="Optional HTTP(S) endpoint to POST the bundle to instead of writing it.",
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="Bearer token sent with --endpoint."
    ),
    ocr_lang: str = typer.Option(
        DEFAULT_OCR_LANG, "--ocr-lang", help="Tesseract language string for OCR."
    ),
    timeout: float = typer.Option(60.0, "--timeout", "-t", min=0.1),
    include_warnings: bool = typer.Option(
        False, "--include-warnings",
        help="Send documents whose conversion only produced a warning "
             "(OCR unavailable/disabled/no text found) anyway. Off by "
             "default: such a document is metadata, not a real read of the "
             "content, and the Sandbox would otherwise ingest it silently "
             "as if it were.",
    ),
) -> None:
    """Convert documents and hand the results to the integration bridge."""
    from doc2md.core.bridge import BridgeError, FileDropTransport, HttpTransport, payload_from_results

    resolved_inputs = _validate_nonempty_inputs(inputs)

    converter = Converter(timeout=timeout, options={"ocr_lang": ocr_lang})
    targets = _expand_targets(resolved_inputs, output=inbox)
    if not targets:
        typer.secho("No input files found.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

    results = [converter.convert_file(target) for target in targets]
    failures = [r for r in results if not r.success]
    for failure in failures:
        typer.secho(f"FAIL {failure.source.name} -> {failure.error}", fg=typer.colors.YELLOW)

    warned = [r for r in results if r.success and r.warning]
    if warned:
        for result in warned:
            if include_warnings:
                typer.secho(
                    f"WARN {result.source.name} -> sent to bridge anyway: {result.warning}",
                    fg=typer.colors.YELLOW,
                )
            else:
                typer.secho(
                    f"WARN {result.source.name} -> excluded from bridge: {result.warning}",
                    fg=typer.colors.YELLOW,
                )

    payload = payload_from_results(results, include_warnings=include_warnings)
    transport = HttpTransport(endpoint, timeout=timeout, token=token) if endpoint else FileDropTransport(inbox)
    try:
        message = transport.send(payload)
    except BridgeError as exc:
        typer.secho(f"Bridge failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    warn_note = f" ({len(warned)} with warnings)" if warned and include_warnings else ""
    typer.secho(
        message + warn_note,
        fg=typer.colors.GREEN if not failures and not warned else typer.colors.YELLOW,
    )
    if failures:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
