"""Export markdown content to multiple formats (.md, .txt, .docx).

Also the single shared home for *where* a conversion's output is allowed to
land (:class:`OutputPolicy`) and *how* it is written to disk - the CLI, the
GUI and chunked output all call these same functions, so the collision and
overwrite rules and the atomic-write guarantee are identical everywhere.

Two jobs are kept separate:

``resolve_destination()``
    A **non-committing preview** - "where would this land right now". It never
    creates anything on disk, so a live preview can call it on every change.

``claim_and_publish_text()`` / ``commit_output_set()``
    The **actual write path**. Content is first written to a hidden temp file
    in the destination directory, then published under its final name with a
    no-clobber rename, so two writers racing for one name can never both win
    and a reader never sees a half-written file at the final name:

    - Windows: ``os.rename`` raises ``FileExistsError`` if the target exists.
    - POSIX: ``os.link`` raises ``FileExistsError`` if the target exists, and
      the temp name is then removed.

    ``overwrite`` publishes with ``os.replace`` instead. A crash can leave only
    a hidden ``.<name>.<random>.tmp`` file - never a file at the final name.

``commit_output_set()`` publishes the main output and its chunk parts as one
unit. On failure every file this call created is removed. Under ``overwrite``
a destination that already existed has had its content replaced and cannot be
restored (there is no backup step), so :class:`PartialCommitError` reports
exactly which paths survived.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal


class OutputPolicy(str, Enum):
    """How to resolve a conversion's destination when a file may already
    be there.

    ``UNIQUE`` never overwrites: it appends ``-1``, ``-2``, ... instead.
    ``FAIL`` refuses outright. ``OVERWRITE`` replaces an existing file but
    never the source file itself. ``CONVERTED_FOLDER`` writes into a
    ``Converted`` subfolder (unique-numbered within it), the safe GUI default.
    """

    UNIQUE = "unique"
    FAIL = "fail"
    OVERWRITE = "overwrite"
    CONVERTED_FOLDER = "converted-folder"


class OutputPolicyError(Exception):
    """The chosen policy refuses to produce a destination (``fail`` hit an
    existing file, or the destination would be the source file itself)."""


class PartialCommitError(Exception):
    """:func:`commit_output_set` failed partway through and could not remove
    every file it wrote - possible only under ``overwrite``, where a
    destination that already existed has its content replaced immediately.

    ``written_paths`` lists the paths this call published that are still on
    disk, in write order. The original exception is ``__cause__``.
    """

    def __init__(self, message: str, *, written_paths: "list[Path]") -> None:
        super().__init__(message)
        self.written_paths = list(written_paths)


def _same_path(a: Path, b: Path) -> bool:
    """True when *a* and *b* name the same filesystem entry.

    Windows paths are case-insensitive, and neither path is required to
    exist yet (the destination usually does not), so this compares resolved
    path strings case-insensitively rather than using ``Path.samefile()``
    (which requires both paths to already exist).
    """
    return str(a.resolve()).casefold() == str(b.resolve()).casefold()


def resolve_destination(
    source: Path, directory: Path, suffix: str, policy: "OutputPolicy | str"
) -> Path:
    """**Preview only** - where *source* would currently land under *policy*.

    Does not create, reserve, or touch anything on disk; safe to call
    repeatedly (e.g. on every keystroke in an output-folder field). Because
    it is only a snapshot, the path it returns can go stale before a write
    actually happens - a real write MUST go through
    :func:`claim_and_publish_text` or :func:`commit_output_set` instead,
    which re-resolve and atomically claim the destination themselves rather
    than trusting a previously-computed path.

    Never returns a path equal to *source* itself - not even under
    ``overwrite`` - which is what stops a ``.md`` input file (destination
    suffix ``.md`` landing in the same directory as the source) from ever
    being told to overwrite itself.
    """
    policy = OutputPolicy(policy)
    target_dir = directory / "Converted" if policy is OutputPolicy.CONVERTED_FOLDER else directory

    if policy in (OutputPolicy.UNIQUE, OutputPolicy.CONVERTED_FOLDER):
        # resolve_output_path() already treats an existing file at the
        # candidate path - including the source itself, always present on
        # disk at this point - as a collision to number around.
        return resolve_output_path(target_dir, source.stem, suffix)

    candidate = target_dir / f"{source.stem}{suffix}"

    if policy is OutputPolicy.FAIL:
        if candidate.exists():
            raise OutputPolicyError(f"destination already exists: {candidate}")
        return candidate

    if policy is OutputPolicy.OVERWRITE:
        if _same_path(candidate, source):
            raise OutputPolicyError(
                f"refusing to overwrite the source file itself: {candidate}"
            )
        return candidate

    raise ValueError(f"unknown output policy: {policy!r}")  # pragma: no cover - Enum guards this


def _replace_with_retry(tmp: str, path: Path) -> None:
    """``os.replace`` with a few short retries: on Windows two writers replacing
    the same destination in the same instant can fail spuriously with
    "access is denied" and succeed a few milliseconds later."""
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if attempt == 4:
                raise
            time.sleep(0.02)


def _write_temp(target: Path, content: str, encoding: str, newline: str) -> str:
    """Write *content* to a hidden temp file beside *target*; return its path."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        handle = os.fdopen(fd, "w", encoding=encoding, newline=newline)
    except BaseException:
        os.close(fd)
        _discard(tmp)
        raise
    try:
        with handle:
            handle.write(content)
    except BaseException:
        _discard(tmp)
        raise
    return tmp


def _stage(target: Path, content: str) -> str:
    return _write_temp(target, content, "utf-8", "\n")


def _discard(tmp: str) -> None:
    try:
        os.remove(tmp)
    except OSError:
        pass


def _publish_new(tmp: str, dest: Path) -> None:
    """Move *tmp* to *dest* only if *dest* does not exist.

    Raises ``FileExistsError`` when the name is taken; the temp file is left
    for the caller to discard.
    """
    if os.name == "nt":
        os.rename(tmp, dest)
        return
    os.link(tmp, dest)
    _discard(tmp)


def atomic_write_text(
    path: Path, content: str, *, encoding: str = "utf-8", newline: str = "\n"
) -> None:
    """Write *content* to *path* atomically (temp file, then ``os.replace``).

    A failure partway through never leaves a partially-written file at *path*:
    either the previous content survives or the new content lands whole.
    """
    tmp = _write_temp(path, content, encoding, newline)
    try:
        _replace_with_retry(tmp, path)
    except BaseException:
        _discard(tmp)
        raise


@dataclass(frozen=True)
class _Published:
    path: Path
    identity: "tuple[int, int]"
    preexisted: bool


def _identity_matches(path: Path, identity: "tuple[int, int]") -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return False
    return (st.st_dev, st.st_ino) == identity


def _publish(
    directory: Path, stem: str, suffix: str, content: str, policy: OutputPolicy, *, source: Path
) -> _Published:
    """Write *content* to the destination chosen by *policy* and return it."""
    if policy is OutputPolicy.OVERWRITE:
        candidate = directory / f"{stem}{suffix}"
        if _same_path(candidate, source):
            raise OutputPolicyError(
                f"refusing to overwrite the source file itself: {candidate}"
            )

    tmp = _stage(directory / f"{stem}{suffix}", content)
    try:
        st = os.stat(tmp)
        identity = (st.st_dev, st.st_ino)

        if policy is OutputPolicy.OVERWRITE:
            existed = candidate.exists()
            _replace_with_retry(tmp, candidate)
            return _Published(candidate, identity, existed)

        if policy is OutputPolicy.FAIL:
            candidate = directory / f"{stem}{suffix}"
            try:
                _publish_new(tmp, candidate)
            except FileExistsError:
                raise OutputPolicyError(f"destination already exists: {candidate}") from None
            return _Published(candidate, identity, False)

        counter = 0
        while True:
            name = f"{stem}{suffix}" if counter == 0 else f"{stem}-{counter}{suffix}"
            candidate = directory / name
            try:
                _publish_new(tmp, candidate)
                return _Published(candidate, identity, False)
            except FileExistsError:
                counter += 1
    except BaseException:
        _discard(tmp)
        raise


def _rollback(published: "list[_Published]") -> "list[Path]":
    """Remove the files this call created; return paths that could not be undone.

    A path is removed only if it is still the very file this call published
    (device and inode match), so another writer's later file at the same name
    is never deleted. Overwritten pre-existing destinations cannot be restored
    and are returned as survivors.
    """
    survivors: list[Path] = []
    for entry in published:
        if not _identity_matches(entry.path, entry.identity):
            continue
        if entry.preexisted:
            survivors.append(entry.path)
            continue
        try:
            entry.path.unlink()
        except OSError:
            survivors.append(entry.path)
    return survivors


def claim_and_publish_text(
    source: Path, directory: Path, suffix: str, content: str, policy: "OutputPolicy | str"
) -> Path:
    """Write *content* for *source* under *policy* and return the final path.

    Unlike :func:`resolve_destination` followed by :func:`atomic_write_text`,
    the name is decided by the publish itself, so there is no check-then-write
    gap. Under ``overwrite``, the source file itself is never replaced.
    """
    policy = OutputPolicy(policy)
    target_dir = directory / "Converted" if policy is OutputPolicy.CONVERTED_FOLDER else directory
    return _publish(target_dir, source.stem, suffix, content, policy, source=source).path


def commit_output_set(
    *,
    source: Path,
    directory: Path,
    policy: "OutputPolicy | str",
    main_suffix: str,
    main_content: str,
    chunk_contents: "list[str] | None" = None,
    chunk_suffix: str = ".md",
) -> "tuple[Path, list[Path]]":
    """Publish a conversion's main output and its chunk parts as one unit.

    Chunk names derive from the *resolved* main stem (after any ``unique``
    numbering), so two same-stem sources never collide on their chunks. Chunks
    are never attempted if the main output failed. On any failure every file
    this call created is removed; under ``overwrite`` a pre-existing file whose
    content was already replaced cannot be restored, and
    :class:`PartialCommitError` names it.
    """
    policy = OutputPolicy(policy)
    target_dir = directory / "Converted" if policy is OutputPolicy.CONVERTED_FOLDER else directory
    published: list[_Published] = []
    chunk_paths: list[Path] = []
    try:
        main = _publish(target_dir, source.stem, main_suffix, main_content, policy, source=source)
        published.append(main)
        for index, piece in enumerate(chunk_contents or [], start=1):
            chunk = _publish(
                target_dir,
                f"{main.path.stem}.part{index:03d}",
                chunk_suffix,
                piece + "\n",
                policy,
                source=source,
            )
            published.append(chunk)
            chunk_paths.append(chunk.path)
    except BaseException as exc:
        survivors = _rollback(published)
        if survivors:
            raise PartialCommitError(
                "commit_output_set failed partway through and could not undo "
                f"{len(survivors)} file(s) this call published (overwritten "
                f"destinations cannot be restored): {survivors}",
                written_paths=survivors,
            ) from exc
        raise
    return main.path, chunk_paths


def resolve_output_path(directory: Path, stem: str, suffix: str) -> Path:
    """Pick a destination that will not collide with an existing file.

    Shared by the CLI, the GUI and chunked output so all three apply the same
    rule: if ``{stem}{suffix}`` already exists - including when it names the
    very source file being converted, which is always present on disk at this
    point - fall back to ``{stem}-1{suffix}``, ``{stem}-2{suffix}``, and so on.
    This is what stops ``report.md`` from being overwritten by its own
    conversion, and what keeps two same-stem files from different source
    folders (``a/report.pdf``, ``b/report.docx``) from colliding when they
    share one output directory.
    """
    candidate = directory / f"{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def export_markdown(content: str, output_path: Path, format_type: Literal["md", "txt", "docx"] = "md") -> tuple[bool, str]:
    """
    Export markdown content to specified format.

    Returns: (success: bool, message: str)
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if format_type == "md":
            atomic_write_text(output_path, content)
            return True, f"Exported to {output_path.name}"

        elif format_type == "txt":
            atomic_write_text(output_path, content)
            return True, f"Exported to {output_path.name}"

        elif format_type == "docx":
            try:
                from docx import Document
                from docx.shared import Pt, RGBColor
                from docx.enum.text import WD_PARAGRAPH_ALIGNMENT
            except ImportError:
                return False, "python-docx not installed. Install via: pip install 'doc2md[gui]'"

            doc = Document()

            for line in content.split("\n"):
                line = line.rstrip()
                if not line:
                    doc.add_paragraph()
                    continue

                if line.startswith("# "):
                    p = doc.add_heading(line[2:], level=1)
                elif line.startswith("## "):
                    p = doc.add_heading(line[3:], level=2)
                elif line.startswith("### "):
                    p = doc.add_heading(line[4:], level=3)
                elif line.startswith("#### "):
                    p = doc.add_heading(line[5:], level=4)
                elif line.startswith("- ") or line.startswith("* "):
                    p = doc.add_paragraph(line[2:], style="List Bullet")
                elif line.startswith("  "):
                    p = doc.add_paragraph(line.lstrip(), style="List Bullet 2")
                else:
                    p = doc.add_paragraph(line)

                if "**" in line:
                    for run in p.runs:
                        if "**" in run.text:
                            run.bold = True

            # docx has no text-mode "write this string" equivalent - save to
            # a same-directory temp file via python-docx's own writer, then
            # atomically replace the destination, matching every other
            # write in this application (same-filesystem os.replace, no
            # partial file ever visible at output_path).
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{output_path.name}.", suffix=".tmp", dir=str(output_path.parent)
            )
            os.close(fd)
            try:
                doc.save(tmp_name)
                os.replace(tmp_name, output_path)
            except BaseException:
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass
                raise
            return True, f"Exported to {output_path.name}"

        else:
            return False, f"Unknown format: {format_type}"

    except Exception as exc:
        return False, f"Export error: {exc}"
