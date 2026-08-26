"""Automate Inno Setup compilation of dist/doc2md_Setup_v<version>.exe.

Usage: python build_installer.py [--skip-winget]

Locates ISCC.exe in standard install locations, falls back to a silent
`winget install JRSoftware.InnoSetup` when missing, compiles
setup_builder.iss, and validates the produced installer artifact.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ISS_SCRIPT = ROOT / "setup_builder.iss"
PAYLOAD_EXE = ROOT / "dist" / "doc2md.exe"
PYPROJECT = ROOT / "pyproject.toml"

ISCC_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
    Path.home() / r"AppData\Local\Programs\Inno Setup 6\ISCC.exe",
    Path.home() / r"AppData\Local\Programs\Inno Setup 5\ISCC.exe",
]

WINGET_PACKAGE_ID = "JRSoftware.InnoSetup"


def read_version() -> str:
    try:
        if sys.version_info >= (3, 11):
            import tomllib

            with open(PYPROJECT, "rb") as fh:
                return str(tomllib.load(fh)["project"]["version"])
    except Exception:
        pass
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def find_iscc() -> Path | None:
    for candidate in ISCC_CANDIDATES:
        if candidate.is_file():
            return candidate
    located = shutil.which("ISCC.exe") or shutil.which("iscc")
    if located:
        return Path(located)
    return None


def winget_install_inno_setup() -> bool:
    winget = shutil.which("winget")
    if winget is None:
        print("[installer] winget is not available; cannot auto-install Inno Setup.")
        return False
    print(f"[installer] Installing Inno Setup via winget ({WINGET_PACKAGE_ID})...")
    result = subprocess.run(
        [
            winget,
            "install",
            "--id",
            WINGET_PACKAGE_ID,
            "-e",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        check=False,
    )
    return result.returncode == 0


def ensure_iscc(skip_winget: bool) -> Path | None:
    iscc = find_iscc()
    if iscc is not None:
        print(f"[installer] Found ISCC: {iscc}")
        return iscc
    if skip_winget:
        print("[installer] ISCC.exe not found (--skip-winget set).")
        return None
    print(
        "[installer] ISCC.exe not found in standard paths.\n"
        "[installer] Attempting automatic installation via winget...\n"
        f"[installer]   winget install --id {WINGET_PACKAGE_ID} -e --silent"
    )
    if not winget_install_inno_setup():
        print(
            "\n[installer] FAILED to provision Inno Setup automatically.\n"
            "[installer] Install it manually from https://jrsoftware.org/isdl.php\n"
            "[installer] or run:  winget install --id JRSoftware.InnoSetup -e"
        )
        return None
    refreshed = find_iscc()
    if refreshed is None:
        print(
            "[installer] winget reported success but ISCC.exe was still not found.\n"
            "[installer] If this machine needs a shell restart to refresh PATH, "
            "re-run build_installer.py in a new terminal."
        )
    return refreshed


def compile_installer(iscc: Path, version: str) -> int:
    cmd = [str(iscc), f"/DVersion={version}", str(ISS_SCRIPT)]
    print("[installer]", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile the doc2md Windows installer.")
    parser.add_argument(
        "--skip-winget",
        action="store_true",
        help="Do not attempt automatic Inno Setup installation.",
    )
    args = parser.parse_args()

    version = read_version()
    artifact = ROOT / "dist" / f"doc2md_Setup_v{version}.exe"

    if not PAYLOAD_EXE.is_file():
        print(
            f"[installer] Missing payload: {PAYLOAD_EXE}\n"
            "[installer] Build it first with:  python build_exe.py"
        )
        return 2

    iscc = ensure_iscc(args.skip_winget)
    if iscc is None:
        return 1

    code = compile_installer(iscc, version)
    if code != 0:
        print(f"[installer] ISCC compilation FAILED (exit {code}).")
        return code

    if not artifact.is_file() or artifact.stat().st_size == 0:
        print(f"[installer] Expected installer artifact missing or empty: {artifact}")
        return 3

    size_mb = artifact.stat().st_size / (1024 * 1024)
    print()
    print("=" * 62)
    print("Installer build complete")
    print(f"  Artifact : {artifact}")
    print(f"  Size     : {size_mb:.1f} MB")
    print(f"  Version  : {version}")
    print("-" * 62)
    print("Usage:")
    print("  1. Run the Setup exe (per-user, no admin required).")
    print("  2. Installs to %LOCALAPPDATA%\\doc2md and appends it to the user PATH.")
    print("  3. Right-click any file -> 'Convert to Token-Optimized Markdown'")
    print("     (runs: doc2md.exe \"<file>\" -c -s)")
    print("  4. Uninstall removes the app folder, PATH entry, and context menu.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
