"""Real-document regression check: convert a folder of real samples and compare
each result with the output a person has already approved.

The unit tests build their own synthetic fixtures; they cannot tell whether a
change made a *real* scan read worse. 1.3.2 is the example: a fix that helped a
brochure made a grey company certificate worse, and nobody noticed until that
certificate happened to be run again. This tool reruns every sample, every time.

The samples stay outside the repository (they are real, often confidential
documents). Layout of the samples folder::

    doc2md-samples/
        scans/certificate.pdf
        scans/certificate.pdf.expect.txt   phrases the output must contain
        .golden/scans/certificate.pdf.md   approved output    (written by `approve`)
        .golden/scans/certificate.pdf.json approved metrics   (written by `approve`)
        .runs/20261016-153000/...          each run's output, diffs and report.md

An ``.expect.txt`` file holds one phrase per line (``#`` starts a comment). A
phrase matches when it appears in the output with all whitespace ignored, so
OCR spacing differences do not count; a wrong letter (ข read as ย) does.

Usage::

    python tools/regress.py run                 # convert everything, compare
    python tools/regress.py run --only "scans/*"
    python tools/regress.py approve scans/certificate.pdf
    python tools/regress.py approve --all       # accept the latest run wholesale

``run`` exits 1 when anything regressed or failed, 0 otherwise. A regression is
only an objective loss: a worse status (Success -> Warning -> Error), an
expected phrase the approved output had and this run lost, or fewer pages with
content. Any other text difference is reported as "changed" for a person to
judge, with a diff next to the run's output.
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import fnmatch
import json
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_SAMPLES = REPO_ROOT.parent / "doc2md-samples"
GOLDEN_DIR = ".golden"
RUNS_DIR = ".runs"
EXPECT_SUFFIX = ".expect.txt"
DEFAULT_PRESET = "Balanced AI"
DEFAULT_TIMEOUT_S = 600.0

STATUS_RANK = {"Success": 0, "Warning": 1, "Error": 2}

SAME, CHANGED, FIXED, NEW, REGRESSED, ERROR = (
    "same", "changed", "fixed", "new", "REGRESSED", "ERROR",
)
FAILING = (REGRESSED, ERROR)


@dataclass
class Verdict:
    rel: str
    outcome: str
    similarity: float | None = None
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Discovery and expectations
# --------------------------------------------------------------------------- #
def discover(samples: Path, only: str | None = None) -> list[Path]:
    """Every convertible sample under *samples*, as paths relative to it."""
    from doc2md.core.router import RECURSIVE_SCAN_EXCLUDED_SUFFIXES, FileKind, detect

    found = []
    for path in sorted(samples.rglob("*")):
        rel = path.relative_to(samples)
        if not path.is_file() or any(part.startswith(".") for part in rel.parts):
            continue
        if path.name.endswith(EXPECT_SUFFIX):
            continue
        if path.suffix.lower() in RECURSIVE_SCAN_EXCLUDED_SUFFIXES:
            continue
        if only and not fnmatch.fnmatch(rel.as_posix(), only):
            continue
        kind = detect(path).kind
        if kind in (FileKind.UNKNOWN, FileKind.MEDIA):
            continue
        found.append(rel)
    return found


def load_expectations(path: Path) -> list[str]:
    if not path.is_file():
        return []
    phrases = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            phrases.append(line)
    return phrases


def _squash(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).split())


def missing_phrases(markdown: str, phrases: list[str]) -> list[str]:
    haystack = _squash(markdown)
    return [phrase for phrase in phrases if _squash(phrase) not in haystack]


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
def similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(
        None, a.splitlines(), b.splitlines(), autojunk=False
    ).ratio()


def compare(
    rel: str,
    golden_md: str | None,
    golden_meta: dict | None,
    current_md: str,
    current_meta: dict,
    phrases: list[str],
) -> Verdict:
    status = current_meta.get("status", "Error")
    missing_now = missing_phrases(current_md, phrases)

    if golden_md is None or golden_meta is None:
        verdict = Verdict(rel, ERROR if status == "Error" else NEW)
        if status == "Error":
            verdict.reasons.append(f"conversion failed: {current_meta.get('error')}")
        if missing_now:
            verdict.notes.append(f"{len(missing_now)} expected phrase(s) missing: {missing_now}")
        return verdict

    verdict = Verdict(rel, SAME, similarity(golden_md, current_md))
    old_status = golden_meta.get("status", "Error")

    if status == "Error":
        verdict.outcome = ERROR
        verdict.reasons.append(f"conversion failed: {current_meta.get('error')}")
    elif STATUS_RANK.get(status, 2) > STATUS_RANK.get(old_status, 2):
        verdict.reasons.append(f"status {old_status} -> {status}")

    missing_before = set(missing_phrases(golden_md, phrases))
    lost = [p for p in missing_now if p not in missing_before]
    gained = [p for p in missing_before if p not in missing_now]
    if lost:
        verdict.reasons.append(f"lost expected phrase(s): {lost}")
    if gained:
        verdict.notes.append(f"now finds expected phrase(s): {gained}")
    still = [p for p in missing_now if p in missing_before]
    if still:
        verdict.notes.append(f"still missing: {still}")

    old_q, new_q = golden_meta.get("quality") or {}, current_meta.get("quality") or {}
    old_pages, new_pages = old_q.get("pages_with_content"), new_q.get("pages_with_content")
    if old_pages is not None and new_pages is not None and new_pages < old_pages:
        verdict.reasons.append(f"pages with content {old_pages} -> {new_pages}")
    for key in ("tables_detected", "ocr_review_lines", "rows_exported"):
        if old_q.get(key) != new_q.get(key):
            verdict.notes.append(f"{key} {old_q.get(key)} -> {new_q.get(key)}")
    old_tokens, new_tokens = golden_meta.get("tokens"), current_meta.get("tokens")
    if old_tokens and new_tokens and abs(new_tokens - old_tokens) / old_tokens > 0.05:
        verdict.notes.append(f"tokens {old_tokens} -> {new_tokens}")

    if verdict.outcome == ERROR:
        return verdict
    if verdict.reasons:
        verdict.outcome = REGRESSED
    elif gained:
        verdict.outcome = FIXED
    elif golden_md != current_md or old_status != status:
        verdict.outcome = CHANGED
    return verdict


# --------------------------------------------------------------------------- #
# Running
# --------------------------------------------------------------------------- #
def _convert(path: Path, preset: str, timeout: float) -> tuple[str, dict]:
    from doc2md.core.converter import Converter
    from doc2md.core.presets import options_for

    converter = Converter(timeout=timeout, options=options_for(preset))
    result = converter.convert_file(path)
    if not result.success:
        status = "Error"
    elif result.warning:
        status = "Warning"
    else:
        status = "Success"
    meta = {
        "status": status,
        "warning": result.warning,
        "error": result.error,
        "engine": result.engine,
        "kind": result.kind,
        "duration_s": round(result.duration_s, 2),
        "tokens": result.token_estimate if result.markdown else 0,
        "quality": dataclasses.asdict(result.quality),
        "preset": preset,
    }
    return result.markdown, meta


def _golden_paths(samples: Path, rel: Path) -> tuple[Path, Path]:
    base = samples / GOLDEN_DIR / rel
    return base.with_name(base.name + ".md"), base.with_name(base.name + ".json")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def run(
    samples: Path,
    *,
    only: str | None = None,
    preset: str = DEFAULT_PRESET,
    timeout: float = DEFAULT_TIMEOUT_S,
    convert=None,
    out=print,
) -> tuple[Path, list[Verdict]]:
    convert = convert or _convert
    rels = discover(samples, only)
    run_dir = samples / RUNS_DIR / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    verdicts = []

    for index, rel in enumerate(rels, 1):
        out(f"[{index}/{len(rels)}] {rel.as_posix()}")
        source = samples / rel
        try:
            markdown, meta = convert(source, preset, timeout)
        except Exception as exc:  # a crash in one file must not stop the run
            markdown, meta = "", {"status": "Error", "error": f"{type(exc).__name__}: {exc}"}

        base = run_dir / rel
        current_md = base.with_name(base.name + ".md")
        _write(current_md, markdown)
        _write(base.with_name(base.name + ".json"), json.dumps(meta, ensure_ascii=False, indent=2))

        golden_md_path, golden_meta_path = _golden_paths(samples, rel)
        golden_md = golden_md_path.read_text(encoding="utf-8") if golden_md_path.is_file() else None
        golden_meta = (
            json.loads(golden_meta_path.read_text(encoding="utf-8"))
            if golden_meta_path.is_file()
            else None
        )
        phrases = load_expectations(source.with_name(source.name + EXPECT_SUFFIX))
        verdict = compare(rel.as_posix(), golden_md, golden_meta, markdown, meta, phrases)
        verdicts.append(verdict)

        if golden_md is not None and golden_md != markdown:
            diff = difflib.unified_diff(
                golden_md.splitlines(), markdown.splitlines(),
                "approved", "this run", lineterm="",
            )
            _write(base.with_name(base.name + ".diff"), "\n".join(diff) + "\n")

    _write(run_dir / "report.md", render_report(run_dir, preset, verdicts))
    return run_dir, verdicts


def render_report(run_dir: Path, preset: str, verdicts: list[Verdict]) -> str:
    counts = {}
    for verdict in verdicts:
        counts[verdict.outcome] = counts.get(verdict.outcome, 0) + 1
    order = (REGRESSED, ERROR, FIXED, CHANGED, NEW, SAME)
    lines = [
        f"# Regression run {run_dir.name}",
        "",
        f"Preset: {preset}. Files: {len(verdicts)}. "
        + ", ".join(f"{name}: {counts[name]}" for name in order if name in counts),
        "",
        "| File | Result | Similarity | Details |",
        "| --- | --- | --- | --- |",
    ]
    for verdict in sorted(verdicts, key=lambda v: (order.index(v.outcome), v.rel)):
        ratio = "" if verdict.similarity is None else f"{verdict.similarity:.1%}"
        details = "; ".join(verdict.reasons + verdict.notes).replace("|", "\\|")
        lines.append(f"| {verdict.rel} | {verdict.outcome} | {ratio} | {details} |")
    return "\n".join(lines) + "\n"


def latest_run(samples: Path) -> Path | None:
    runs_root = samples / RUNS_DIR
    if not runs_root.is_dir():
        return None
    runs = sorted(p for p in runs_root.iterdir() if (p / "report.md").is_file())
    return runs[-1] if runs else None


def approve(samples: Path, files: list[str], *, every: bool = False, run_dir: Path | None = None) -> list[str]:
    """Copy outputs from *run_dir* (default: the latest run) into the golden set."""
    run_dir = run_dir or latest_run(samples)
    if run_dir is None:
        raise SystemExit("no completed run to approve - use `run` first")
    if every:
        files = [
            p.relative_to(run_dir).as_posix()[: -len(".json")]
            for p in sorted(run_dir.rglob("*.json"))
        ]
    approved = []
    for name in files:
        rel = Path(name.replace("\\", "/"))
        base = run_dir / rel
        md, meta = base.with_name(base.name + ".md"), base.with_name(base.name + ".json")
        if not md.is_file() or not meta.is_file():
            raise SystemExit(f"{name}: not in run {run_dir.name}")
        golden_md, golden_meta = _golden_paths(samples, rel)
        golden_md.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(md, golden_md)
        shutil.copyfile(meta, golden_meta)
        approved.append(rel.as_posix())
    return approved


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES,
                        help=f"samples folder (default: {DEFAULT_SAMPLES})")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="convert every sample and compare with the approved output")
    run_cmd.add_argument("--only", help='glob on the relative path, e.g. "scans/*"')
    run_cmd.add_argument("--preset", default=DEFAULT_PRESET)
    run_cmd.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)

    approve_cmd = sub.add_parser("approve", help="accept the latest run's output as correct")
    approve_cmd.add_argument("files", nargs="*", help="relative sample paths, as the report lists them")
    approve_cmd.add_argument("--all", action="store_true", help="approve every file in the run")

    args = parser.parse_args(argv)
    samples = args.samples.resolve()
    if not samples.is_dir():
        print(f"samples folder not found: {samples}", file=sys.stderr)
        return 2

    if args.command == "approve":
        if not args.files and not args.all:
            print("name the files to approve, or pass --all", file=sys.stderr)
            return 2
        for rel in approve(samples, args.files, every=args.all):
            print(f"approved {rel}")
        return 0

    run_dir, verdicts = run(samples, only=args.only, preset=args.preset, timeout=args.timeout)
    print()
    print((run_dir / "report.md").read_text(encoding="utf-8"))
    print(f"Report: {run_dir / 'report.md'}")
    failing = [v for v in verdicts if v.outcome in FAILING]
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
