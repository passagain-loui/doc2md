"""Frozen entry point for dist/doc2md.exe.

Double-clicking the executable opens the GUI; passing arguments runs the CLI.
"""

import multiprocessing
import sys


def _enable_high_dpi() -> None:
    """Opt into per-monitor DPI awareness before Qt creates any window.

    Qt6 scales correctly on its own once the process is DPI-aware, but a
    frozen exe starts out DPI-unaware, which makes Windows bitmap-stretch the
    whole UI and renders Thai text as a blur.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError, NameError):
            pass


def main() -> int:
    _enable_high_dpi()
    # Imported here, not at module scope: the CLI must not pay for loading Qt,
    # and freeze_support() has to run before anything spawns a subprocess.
    from doc2md.cli.main import app

    if len(sys.argv) == 1:
        sys.argv.append("gui")
    app()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - last-resort dialog
        import traceback

        traceback.print_exc(file=sys.stderr)
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            qt_app = QApplication.instance() or QApplication([])
            QMessageBox.critical(
                None,
                "doc2md - Startup Error",
                f"doc2md could not start:\n\n{type(exc).__name__}: {exc}",
            )
            del qt_app
        except Exception:
            print(f"FATAL ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
