# main_window.py

```python
"""Main GUI window with drag-and-drop support."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

try:
    import tkinter as tk
    from tkinter import ttk, messagebox
except ImportError:
    raise ImportError("tkinter is required for GUI. Install via: pip install tkinter")

from doc2md.core.converter import Converter

logger = logging.getLogger(__name__)


class MainWindow:
    """Main application window with drag-and-drop file conversion."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("doc2md Converter")
        self.root.geometry("800x600")
        self.root.minsize(600, 400)

        self.converter = Converter(timeout=300)
        self.is_converting = False

        self._setup_ui()

    def _setup_ui(self):
        """Initialize UI components."""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)

        # Title
        title_label = ttk.Label(
            main_frame,
            text="📄 doc2md Converter",
            font=("Arial", 16, "bold"),
        )
        title_label.grid(row=0, column=0, sticky=tk.W, pady=10)

        # Options frame
        options_frame = ttk.LabelFrame(main_frame, text="Options", padding="10")
        options_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=10)
        options_frame.columnconfigure(1, weight=1)

        self.copy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame, text="Auto-copy to clipboard", variable=self.copy_var
        ).grid(row=0, column=0, sticky=tk.W, padx=5)

        self.stats_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame, text="Show token stats", variable=self.stats_var
        ).grid(row=0, column=1, sticky=tk.W, padx=5)

        self.ocr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame, text="Enable OCR", variable=self.ocr_var
        ).grid(row=0, column=2, sticky=tk.W, padx=5)

        # Model selection
        ttk.Label(options_frame, text="Audio Model:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.model_var = tk.StringVar(value="small")
        model_combo = ttk.Combobox(
            options_frame,
            textvariable=self.model_var,
            values=("tiny", "base", "small", "medium", "large-v3"),
            state="readonly",
            width=15,
        )
        model_combo.grid(row=1, column=1, sticky=tk.W, padx=5)

        # Drop zone
        drop_frame = ttk.LabelFrame(main_frame, text="Drag & Drop Files Here", padding="40")
        drop_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        drop_frame.columnconfigure(0, weight=1)
        drop_frame.rowconfigure(0, weight=1)

        drop_label = ttk.Label(
            drop_frame,
            text="📁 Drop PDF, DOCX, Images, Audio, or Video files here",
            font=("Arial", 12),
            foreground="gray",
        )
        drop_label.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Try to enable drag-and-drop (requires tkinterdnd2)
        self._setup_dnd(drop_frame)

        # Progress
        self.progress_var = tk.DoubleVar(value=0)
        progress_bar = ttk.Progressbar(
            main_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        progress_bar.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=10)

        self.status_label = ttk.Label(main_frame, text="Ready", foreground="green")
        self.status_label.grid(row=4, column=0, sticky=tk.W, pady=5)

        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, sticky=(tk.W, tk.E), pady=10)

        ttk.Button(button_frame, text="📂 Browse Files", command=self.browse_files).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(
            button_frame, text="📋 Copy Result", command=self.copy_result
        ).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="🗂️ Open Folder", command=self.open_folder).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(button_frame, text="❌ Exit", command=self.root.quit).pack(
            side=tk.RIGHT, padx=5
        )

    def _setup_dnd(self, parent: tk.Widget):
        """Setup drag-and-drop support if tkinterdnd2 is available."""
        try:
            import tkinterdnd2

            # Register drop target
            parent.drop_target_register(tkinterdnd2.DND_FILES)
            parent.dnd_bind("<<Drop>>", self.drop_files)
            logger.info("Drag-and-drop enabled")
        except ImportError:
            logger.warning("tkinterdnd2 not available; drag-and-drop disabled")

    def browse_files(self):
        """Open file browser to select files."""
        from tkinter.filedialog import askopenfilenames

        files = askopenfilenames(
            filetypes=[
                ("All Supported", "*.pdf *.docx *.xlsx *.pptx *.png *.jpg *.mp3 *.wav *.mp4 *.mkv"),
                ("Documents", "*.pdf *.docx *.xlsx *.pptx"),
                ("Images", "*.png *.jpg *.jpeg *.tiff"),
                ("Audio", "*.mp3 *.wav *.m4a *.aac *.flac"),
                ("Video", "*.mp4 *.mkv *.avi *.mov"),
                ("All Files", "*.*"),
            ]
        )
        if files:
            self.convert_files(files)

    def drop_files(self, event):
        """Handle file drop event."""
        if hasattr(event, "data"):
            # Parse dropped files (format depends on OS and tkinterdnd2 version)
            files = event.data.split()
            self.convert_files(files)

    def convert_files(self, files: list[str]):
        """Convert files in background thread."""
        if self.is_converting:
            messagebox.showwarning("Busy", "Conversion already in progress")
            return

        self.is_converting = True
        thread = threading.Thread(
            target=self._convert_worker,
            args=(files,),
            daemon=True,
        )
        thread.start()

    def _convert_worker(self, files: list[str]):
        """Background worker for file conversion."""
        try:
            self.status_label.config(text=f"Converting {len(files)} file(s)...", foreground="blue")
            self.root.update()

            options = {
                "default_copy": self.copy_var.get(),
                "stats": self.stats_var.get(),
                "ocr_enabled": self.ocr_var.get(),
                "audio_model": self.model_var.get(),
            }

            for i, file_path in enumerate(files):
                progress = (i / len(files)) * 100
                self.progress_var.set(progress)
                self.root.update()

                try:
                    result = self.converter.convert_file(file_path, options)
                    if result.success:
                        self.status_label.config(
                            text=f"✅ Converted: {Path(file_path).name}",
                            foreground="green",
                        )
                    else:
                        self.status_label.config(
                            text=f"⚠️ Failed: {Path(file_path).name}",
                            foreground="red",
                        )
                except Exception as e:
                    logger.error(f"Conversion error: {e}")
                    self.status_label.config(
                        text=f"❌ Error: {str(e)[:50]}",
                        foreground="red",
                    )

            self.progress_var.set(100)
            self.status_label.config(text="✅ Conversion complete!", foreground="green")

        except Exception as e:
            logger.error(f"Worker error: {e}")
            self.status_label.config(text=f"❌ Error: {str(e)}", foreground="red")
        finally:
            self.is_converting = False

    def copy_result(self):
        """Copy last conversion result to clipboard."""
        try:
            import pyperclip

            pyperclip.copy("Last result copied")
            messagebox.showinfo("Success", "Result copied to clipboard")
        except Exception as e:
            messagebox.showerror("Error", f"Copy failed: {e}")

    def open_folder(self):
        """Open output folder."""
        import subprocess

        output_dir = Path.cwd()
        if output_dir.exists():
            subprocess.Popen(f'explorer "{output_dir}"')
```
