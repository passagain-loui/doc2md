"""Locate, configure and install Tesseract OCR with Thai language data.

Three jobs, kept separate so each is testable without touching the machine:

* :func:`find_tesseract` / :func:`prepare_tesseract` - find the binary even when
  it is not on ``PATH`` (a fresh install is not on this process's ``PATH``) and
  point Tesseract at doc2md's own language-data folder when that holds the
  languages asked for.
* :func:`install_ocr` - install the Tesseract binary through ``winget`` (the
  Windows package manager, whose manifest carries the installer's hash) and
  download the English and Thai language files into a per-user folder, so no
  write access to ``Program Files`` is needed for them. Every external step is
  injectable.
* the self-test at the end of :func:`install_ocr`, which asks Tesseract itself
  which languages it can load. Success is that answer, not an exit code.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

WINGET_ID = "UB-Mannheim.TesseractOCR"
REQUIRED_LANGUAGES = ("eng", "tha")
# A fixed release tag, so the files cannot change underneath a URL.
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/4.1.0/{language}.traineddata"
MIN_TRAINEDDATA_BYTES = 50_000
MANUAL_INSTALL_URL = "https://github.com/UB-Mannheim/tesseract/wiki"
_INSTALL_TIMEOUT_S = 1800
_DOWNLOAD_TIMEOUT_S = 90

KNOWN_LOCATIONS: list[Path] = [
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR" / "tesseract.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
]


def user_tessdata_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "doc2md" / "tessdata"


def find_tesseract() -> str | None:
    """Path of the Tesseract binary: on ``PATH`` first, then the usual install folders."""
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    if os.environ.get("DOC2MD_NO_TESSERACT_SEARCH"):
        return None  # lets tests (and spawned workers) ignore a machine-wide install
    for candidate in KNOWN_LOCATIONS:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _has_language(folder: Path, language: str) -> bool:
    try:
        return (folder / f"{language}.traineddata").stat().st_size >= MIN_TRAINEDDATA_BYTES
    except OSError:
        return False


def prepare_tesseract(language: str = "") -> str | None:
    """Make ``pytesseract`` find the binary and, when possible, the language data.

    Returns the binary path, or ``None`` when Tesseract is not installed. When
    doc2md's own data folder holds every requested language, ``TESSDATA_PREFIX``
    points there; otherwise the system default is left alone.
    """
    binary = find_tesseract()
    if binary is None:
        return None
    try:
        import pytesseract

        if not shutil.which("tesseract"):
            pytesseract.pytesseract.tesseract_cmd = binary
    except ImportError:
        pass
    wanted = [part for part in language.split("+") if part]
    folder = user_tessdata_dir()
    if wanted and all(_has_language(folder, part) for part in wanted):
        os.environ["TESSDATA_PREFIX"] = str(folder)
    return binary


@dataclass
class SetupResult:
    ok: bool
    steps: list[str] = field(default_factory=list)
    error: str | None = None

    def summary(self) -> str:
        return "\n".join(self.steps + ([f"ERROR: {self.error}"] if self.error else []))


def _download(url: str, destination: Path) -> None:
    """Download *url* to *destination* atomically, checking the size received."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "doc2md-ocr-setup"})
    fd, tmp_name = tempfile.mkstemp(dir=str(destination.parent), suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle, urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT_S) as response:
            expected = int(response.headers.get("Content-Length") or 0)
            received = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
        if expected and received != expected:
            raise OSError(f"incomplete download ({received} of {expected} bytes)")
        if received < MIN_TRAINEDDATA_BYTES:
            raise OSError(f"downloaded file is too small to be language data ({received} bytes)")
        os.replace(tmp_name, destination)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def _run_winget(winget: str) -> subprocess.CompletedProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    return subprocess.run(
        [
            winget, "install", "--id", WINGET_ID, "--exact", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
        ],
        capture_output=True, text=True, errors="replace", timeout=_INSTALL_TIMEOUT_S,
        creationflags=flags,
    )


def available_languages() -> list[str] | None:
    """Languages Tesseract can load right now, or ``None`` if it cannot be asked."""
    if prepare_tesseract("+".join(REQUIRED_LANGUAGES)) is None:
        return None
    try:
        import pytesseract

        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return None


def install_ocr(
    progress: Callable[[str], None] = lambda message: None,
    *,
    winget_finder: Callable[[], str | None] = lambda: shutil.which("winget"),
    winget_runner: Callable[[str], subprocess.CompletedProcess] = _run_winget,
    downloader: Callable[[str, Path], None] = _download,
    language_check: Callable[[], list[str] | None] = available_languages,
) -> SetupResult:
    """Install Tesseract (if missing) and the Thai and English language data."""
    result = SetupResult(ok=False)

    def say(message: str) -> None:
        result.steps.append(message)
        progress(message)

    binary = find_tesseract()
    if binary:
        say(f"Tesseract already installed: {binary}")
    else:
        winget = winget_finder()
        if not winget:
            result.error = (
                "Tesseract is not installed and winget is not available on this PC. "
                f"Install it from {MANUAL_INSTALL_URL}, then run this again."
            )
            return result
        say("Installing Tesseract with winget - Windows may ask for administrator approval...")
        try:
            completed = winget_runner(winget)
        except subprocess.TimeoutExpired:
            result.error = "The Tesseract installation did not finish in time."
            return result
        except OSError as exc:
            result.error = f"Could not start winget: {exc}"
            return result
        binary = find_tesseract()
        if not binary:
            tail = ((completed.stdout or "") + (completed.stderr or "")).strip().splitlines()[-3:]
            result.error = (
                f"winget finished (exit code {completed.returncode}) but Tesseract was not found. "
                "Approving the administrator prompt is required. "
                + " ".join(tail)
            ).strip()
            return result
        say(f"Tesseract installed: {binary}")

    folder = user_tessdata_dir()
    for language in REQUIRED_LANGUAGES:
        if _has_language(folder, language):
            say(f"Language data present: {language}")
            continue
        say(f"Downloading language data: {language}...")
        try:
            downloader(TESSDATA_URL.format(language=language), folder / f"{language}.traineddata")
        except Exception as exc:
            result.error = f"Could not download {language} language data: {exc}"
            return result

    languages = language_check()
    missing = [name for name in REQUIRED_LANGUAGES if not languages or name not in languages]
    if missing:
        result.error = (
            "Tesseract is installed but cannot load: " + ", ".join(missing)
            + (f" (it reports: {', '.join(languages)})" if languages else "")
        )
        return result
    say("Verified: Tesseract loads Thai and English.")
    result.ok = True
    return result
