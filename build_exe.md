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
]


def collect_tiktoken_resources() -> list[str]:
    args: list[str] = []
    try:
        from PyInstaller.utils.hooks import collect_all

        for package in ("tiktoken_ext",):
            datas, binaries, hiddenimports = collect_all(package)
            for source, target in datas:
                args.extend(["--add-data", f"{source}{Path(':') if sys.platform != 'win32' else ';'}{target}"])
            for binary in binaries:
                args.extend(["--add-binary", f"{binary[0]};{binary[1]}"])
            for hidden in hiddenimports:
                args.extend(["--hidden-import", hidden])
    except Exception as exc:
        print(f"[build_exe] tiktoken resource collection skipped: {exc}")
    return args


def build() -> int:
    if shutil.which("python") is None and sys.executable == "":
        print("[build_exe] python interpreter not found")
        return 2
    if not ENTRY.is_file():
        print(f"[build_exe] entry script missing: {ENTRY}")
        return 2

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        "doc2md",
        "--workpath",
        str(WORKPATH),
        "--distpath",
        str(ROOT / "dist"),
        "--specpath",
        str(BUILD_DIR),
    ]
    for hidden in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", hidden])
    cmd.extend(collect_tiktoken_resources())
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
