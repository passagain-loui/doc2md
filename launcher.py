"""Frozen-entry launcher for the PyInstaller build (dist/doc2md.exe)."""

import multiprocessing
import os
import sys

if getattr(sys, "frozen", False):
    _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", os.path.join(_base, "tiktoken_cache"))

multiprocessing.freeze_support()

from doc2md.cli.main import app

if __name__ == "__main__":
    app()
