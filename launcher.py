"""Thin frozen-entry launcher kept for the installer's alternate entry point."""

import multiprocessing

from doc2md.cli.main import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app()
