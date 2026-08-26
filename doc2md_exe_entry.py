import multiprocessing
import sys
import traceback

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
