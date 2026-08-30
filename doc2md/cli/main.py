"""Command-line interface for doc2md (typer)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import typer

from doc2md import __version__
from doc2md.core.chunker import chunk_markdown
from doc2md.core.config import load_config
from doc2md.core.converter import Converter, ConversionResult
from doc2md.core.router import CODE_EXTENSIONS, EXTENSION_KINDS, IMAGE_EXTENSIONS
from doc2md.core.stats import build_rows, render_table

app = typer.Typer(
    name="doc2md",
    help="Convert documents (PDF/DOCX/XLSX/PPTX/HTML/EML/images/code) to token-optimized Markdown.",
    no_args_is_help=False,
    add_completion=False,
)

SUPPORTED_SUFFIXES = frozenset(EXTENSION_KINDS) | frozenset(IMAGE_EXTENSIONS) | frozenset(CODE_EXTENSIONS)


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


def _expand_targets(inputs: List[Path]) -> List[Path]:
    targets: list[Path] = []
    seen: set[str] = set()

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
            for candidate in sorted(item.rglob("*")):
                if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_SUFFIXES:
                    _push(candidate)
        else:
            _push(item)
    return targets


def _chunk_outputs(
    results: list[ConversionResult], max_tokens: int, output: Optional[Path]
) -> int:
    written_parts = 0
    for result in results:
        pieces = chunk_markdown(result.markdown, max_tokens)
        base_dir = output if output else result.source.parent
        base_dir.mkdir(parents=True, exist_ok=True)
        stem = result.source.stem
        for index, piece in enumerate(pieces, start=1):
            part_path = base_dir / f"{stem}.part{index:03d}.md"
            part_path.write_text(piece + "\n", encoding="utf-8")
            written_parts += 1
    return written_parts


@app.command()
def convert(
    inputs: List[Path] = typer.Argument(..., help="Files, directories, or glob patterns."),
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
    stdout: bool = typer.Option(False, "--stdout", help="Print Markdown to stdout instead of writing files."),
    ignore_errors: bool = typer.Option(False, "--ignore-errors", help="Exit 0 even if some files fail."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress progress output."),
):
    """Convert one or many documents into Markdown."""
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

    converter = Converter(
        timeout=effective_timeout,
        options={"max_rows": effective_max_rows, "pdf_ocr_fallback": bool(cfg["ocr_enabled"])},
    )
    targets = _expand_targets(inputs)
    if not targets:
        typer.secho("No input files found.", fg=typer.colors.RED)
        raise typer.Exit(code=2)

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
            status_word = "OK " if result.success else "FAIL"
            typer.echo(f"[{index}/{total}] {status_word} {target.name}"
                       + ("" if result.success else f" -> {result.error}"))

    failures = [r for r in results if r.success is False]
    successes = [r for r in results if r.success]

    if stdout:
        for result in successes:
            typer.echo(result.markdown)

    written = 0
    if not stdout:
        for result in successes:
            destination = (
                output / f"{result.source.stem}.md" if output else result.source.with_suffix(".md")
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(result.markdown, encoding="utf-8")
            written += 1

    chunk_note = ""
    part_count = 0
    if effective_chunk:
        part_count = _chunk_outputs(successes, int(effective_chunk), output)
        chunk_note = f", {part_count} chunk file(s)"

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
    if quiet:
        summary = f"{len(successes)}/{len(results)}"
        if effective_chunk:
            summary += f"+{part_count}"
    else:
        summary = (
            f"Done: {len(successes)} converted, {len(failures)} failed, "
            f"{written} file(s) written{chunk_note}, ~{tokens_total:,} tokens produced."
        )
    typer.secho(summary + clipboard_note,
                fg=typer.colors.GREEN if not failures else typer.colors.YELLOW)
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
    """Launch the interactive GUI dashboard for drag-and-drop file conversion."""
    try:
        import tkinter as tk
        from doc2md.gui import MainWindow

        try:
            from tkinterdnd2 import Tk
            root = Tk()
        except ImportError:
            root = tk.Tk()

        app_window = MainWindow(root)
        root.mainloop()
    except ImportError as e:
        typer.secho(
            f"GUI dependencies missing: {e}\n"
            "Install via: pip install 'doc2md[gui]'",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
