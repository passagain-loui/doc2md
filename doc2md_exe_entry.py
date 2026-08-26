import multiprocessing
import sys

from doc2md.cli.main import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Auto-launch GUI when exe is run with no arguments (e.g., double-click from desktop)
    if len(sys.argv) == 1:
        sys.argv.append("gui")
    app()
