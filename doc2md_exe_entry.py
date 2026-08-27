import multiprocessing
import os
import sys
import traceback

# Inject bundled binary directory (ffmpeg.exe, ffprobe.exe) into PATH before
# any module (ffmpeg-python, faster-whisper) is imported, so subprocess/dll
# lookups resolve to the PyInstaller bundle instead of failing on a bare exe.
if getattr(sys, "frozen", False):
    _bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    os.environ["PATH"] = _bundle_dir + os.pathsep + os.environ.get("PATH", "")

# Enable Windows High-DPI Awareness for crisp text rendering on high-DPI displays
# SetProcessDpiAwareness(2) = Per-monitor DPI awareness (Windows 10+)
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        # Older Windows versions or if the call fails, continue without high-DPI awareness
        pass

from doc2md.cli.main import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        # Auto-launch GUI when exe is run with no arguments (e.g., double-click from desktop)
        if len(sys.argv) == 1:
            sys.argv.append("gui")
        app()
    except SystemExit:
        # Allow normal exit codes to pass through
        raise
    except Exception as exc:
        # Show error dialog for any uncaught exception in GUI mode
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            error_msg = f"Fatal Error in doc2md GUI:\n\n{str(exc)}\n\nPlease check the installation."
            messagebox.showerror("doc2md - Startup Error", error_msg)
            root.destroy()
        except Exception:
            # Fallback: print to stderr if GUI error dialog fails
            print(f"FATAL ERROR: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        sys.exit(1)
