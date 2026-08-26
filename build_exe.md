# build_exe.py

```python
"""Automated PyInstaller packaging for a standalone doc2md.exe.

Usage: python build_exe.py
Output: dist/doc2md.exe

OCR backends remain runtime-optional: if Tesseract or rapidocr-onnxruntime is
present on the target machine they are used, otherwise the tool degrades to
metadata-only output with an explanatory hint (verified by the test suite).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "doc2md_exe_entry.py"
DIST_EXE = ROOT / "dist" / "doc2md.exe"
BUILD_DIR = ROOT / "build"
WORKPATH = ROOT / "build" / "pyinstaller"

HIDDEN_IMPORTS = [
    "pymupdf",
    "docx",
    "openpyxl",
    "pptx",
    "bs4",
    "lxml.etree",
    "lxml._elementpath",
    "charset_normalizer",
    "charset_normalizer.md",
    "pyperclip",
    "tiktoken",
    "tiktoken_ext",
    "tiktoken_ext.openai_public",
    "typer",
    "rich",
    "customtkinter",
    "windnd",
    "ffmpeg",
    "faster_whisper",
]


def collect_tkinter_resources() -> list[str]:
    """Collect data files for tiktoken and other bundled resources."""
    args: list[str] = []
    try:
        from PyInstaller.utils.hooks import collect_all

        # Collect tiktoken resources
        for package in ("tiktoken_ext",):
            datas, binaries, hiddenimports = collect_all(package)
            for source, target in datas:
                args.extend(["--add-data", f"{source}{Path(':') if sys.platform != 'win32' else ';'}{target}"])
            for binary in binaries:
                args.extend(["--add-binary", f"{binary[0]};{binary[1]}"])
            for hidden in hiddenimports:
                args.extend(["--hidden-import", hidden])

    except Exception as exc:
        print(f"[build_exe] resource collection skipped: {exc}")
    return args


def bundle_ffmpeg_binaries() -> list[str]:
    """Bundle FFmpeg binaries if available on system PATH."""
    args: list[str] = []
    try:
        ffmpeg_path = shutil.which("ffmpeg")
        ffprobe_path = shutil.which("ffprobe")

        if ffmpeg_path and ffprobe_path:
            # Bundle both ffmpeg and ffprobe executables
            args.extend(["--add-binary", f"{ffmpeg_path};."])
            args.extend(["--add-binary", f"{ffprobe_path};."])
            print(f"[build_exe] FFmpeg binaries bundled: {ffmpeg_path}")
        else:
            print("[build_exe] FFmpeg not found on PATH - audio conversion will require system FFmpeg")
    except Exception as exc:
        print(f"[build_exe] FFmpeg bundling skipped: {exc}")
    return args


def build() -> int:
    if shutil.which("python") is None and sys.executable == "":
        print("[build_exe] python interpreter not found")
        return 2
    if not ENTRY.is_file():
        print(f"[build_exe] entry script missing: {ENTRY}")
        return 2

    # Determine if we need icon file
    icon_path = ROOT / "assets" / "icon.ico"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "doc2md",
        "--workpath",
        str(WORKPATH),
        "--distpath",
        str(ROOT / "dist"),
        "--specpath",
        str(BUILD_DIR),
    ]

    if icon_path.is_file():
        cmd.extend(["--icon", str(icon_path)])
    for hidden in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", hidden])
    cmd.extend(collect_tkinter_resources())
    cmd.extend(bundle_ffmpeg_binaries())
    cmd.append(str(ENTRY))

    print("[build_exe]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def main() -> int:
    code = build()
    if code != 0:
        print("[build_exe] PyInstaller FAILED")
        return code
    if not DIST_EXE.is_file():
        print(f"[build_exe] expected output missing: {DIST_EXE}")
        return 3
    size_mb = DIST_EXE.stat().st_size / (1024 * 1024)
    print(f"[build_exe] OK -> {DIST_EXE} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
