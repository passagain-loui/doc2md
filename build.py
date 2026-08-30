"""Produce the full release set: both executables plus the installer.

Two executables are built on purpose:

* ``dist/doc2md/`` - the folder build. Starts in ~0.15 s because nothing is
  unpacked at launch. This is what the installer ships.
* ``dist/doc2md.exe`` - the single-file build, for people who want one portable
  file and can accept the ~1.7 s unpack on every launch.
"""

import subprocess
import sys


def run(*args: str) -> int:
    print(f"[build] {' '.join(args)}")
    return subprocess.run([sys.executable, *args]).returncode


def main() -> int:
    for step in (
        ("build_exe.py", "--onedir"),
        ("build_exe.py",),
        ("build_installer.py",),
    ):
        code = run(*step)
        if code != 0:
            print(f"[build] FAILED at {step[0]} (exit {code})")
            return code
    print("[build] release artifacts complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
