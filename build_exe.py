"""PyInstaller packaging for a lightweight standalone doc2md.exe.

Usage:  python build_exe.py [--onedir]
Output: dist/doc2md.exe  (or dist/doc2md/ with --onedir)

Size and startup time are the two things this script optimizes for, and they
pull in opposite directions:

* ``--onefile`` produces a single tidy executable, but every launch unpacks the
  whole archive into a temp directory first - that is the "slow first start"
  users complained about. ``--onedir`` starts in well under a second because
  nothing is unpacked; it is offered here and is what the installer ships.
* The EXCLUDES list below is what keeps the build small. The heavy scientific
  stack (torch, CUDA, numpy/scipy/matplotlib) is no longer a dependency, but
  PyInstaller's import scanner still drags parts of it in through optional
  code paths in Pillow and pdfminer, and unused Qt modules add ~90 MB on their
  own. Excluding them explicitly is worth roughly two thirds of the output.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "doc2md_exe_entry.py"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
WORKPATH = BUILD_DIR / "pyinstaller"

HIDDEN_IMPORTS = [
    "doc2md.gui.main_window",
    "doc2md.gui.theme",
    "pymupdf",
    "pdfplumber",
    "docx",
    "openpyxl",
    "pptx",
    "bs4",
    "lxml.etree",
    "lxml._elementpath",
    "charset_normalizer",
    "charset_normalizer.md",
    "pyperclip",
    "pytesseract",
    "typer",
    "rich",
]

# Modules PyInstaller would otherwise pull in transitively. Removing them is
# safe because nothing in doc2md imports them; each entry was verified by
# running the frozen exe against the test corpus after exclusion.
EXCLUDES = [
    # Audio/video stack - removed from the product in 1.1.0.
    "torch",
    "torchaudio",
    "torchvision",
    "faster_whisper",
    "whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "ffmpeg",
    "imageio_ffmpeg",
    "sounddevice",
    "soundfile",
    # Scientific stack - not used by any engine.
    "scipy",
    "pandas",
    "matplotlib",
    "sympy",
    "numba",
    "IPython",
    "jupyter",
    "notebook",
    # Superseded GUI toolkits.
    "tkinter",
    "customtkinter",
    "tkinterdnd2",
    "PySide6",
    "PyQt5",
    # Qt modules the interface never touches.
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebChannel",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtQml",
    "PyQt6.QtQuick",
    "PyQt6.QtQuick3D",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtPositioning",
    "PyQt6.QtSerialPort",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.Qt3DCore",
    "PyQt6.QtCharts",
    "PyQt6.QtDataVisualization",
    # Dev-only tooling.
    "pytest",
    "_pytest",
    "setuptools",
    "pip",
]


def _clean_previous(onedir: bool) -> None:
    """Remove only this build's own outputs, never the whole dist/ tree."""
    stale = [
        DIST_DIR / ("doc2md" if onedir else "doc2md.exe"),
        WORKPATH,
        BUILD_DIR / "doc2md.spec",
    ]
    for path in stale:
        if path.is_dir():
            print(f"[build_exe] cleaning {path}")
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            print(f"[build_exe] removing {path}")
            path.unlink()


def _missing_requirements() -> list[str]:
    """Fail before PyInstaller runs if a runtime import is not installed.

    A missing package does not break the build - PyInstaller happily produces
    an exe that crashes on first use - which is exactly the class of silent
    failure this release exists to remove.
    """
    import importlib.util

    modules = {
        "PyQt6.QtWidgets": "PyQt6",
        "pymupdf": "pymupdf",
        "pdfplumber": "pdfplumber",
        "docx": "python-docx",
        "openpyxl": "openpyxl",
        "pptx": "python-pptx",
        "PIL": "pillow",
        "typer": "typer",
    }
    missing = []
    for module, package in modules.items():
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(package)
        except (ImportError, ValueError):
            missing.append(package)
    return missing


def build(onedir: bool = False) -> int:
    _clean_previous(onedir)

    if not ENTRY.is_file():
        print(f"[build_exe] entry script missing: {ENTRY}")
        return 2

    missing = _missing_requirements()
    if missing:
        print("[build_exe] missing runtime dependencies: " + ", ".join(missing))
        print("[build_exe] run: pip install -r requirements.txt")
        return 2

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if onedir else "--onefile",
        "--windowed",
        "--name",
        "doc2md",
        "--workpath",
        str(WORKPATH),
        "--distpath",
        str(DIST_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--optimize",
        "2",
    ]

    icon_path = ROOT / "assets" / "icon.ico"
    if icon_path.is_file():
        cmd.extend(["--icon", str(icon_path)])
    for hidden in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", hidden])
    for excluded in EXCLUDES:
        cmd.extend(["--exclude-module", excluded])
    cmd.append(str(ENTRY))

    print("[build_exe]", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def _report(onedir: bool) -> int:
    target = DIST_DIR / ("doc2md" if onedir else "doc2md.exe")
    if onedir:
        exe = target / "doc2md.exe"
        if not exe.is_file():
            print(f"[build_exe] expected output missing: {exe}")
            return 3
        size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
        print(f"[build_exe] OK -> {exe} (folder {size / (1024 * 1024):.1f} MB)")
        return 0

    if not target.is_file():
        print(f"[build_exe] expected output missing: {target}")
        return 3
    print(f"[build_exe] OK -> {target} ({target.stat().st_size / (1024 * 1024):.1f} MB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    onedir = "--onedir" in args
    code = build(onedir=onedir)
    if code != 0:
        print("[build_exe] PyInstaller FAILED")
        return code
    return _report(onedir)


if __name__ == "__main__":
    raise SystemExit(main())
