# main_window.py

```python
"""Main GUI window with CustomTkinter dark theme and drag-and-drop support."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

try:
    import customtkinter as ctk
    from tkinter import messagebox, filedialog
except ImportError:
    raise ImportError("customtkinter is required for GUI. Install via: pip install 'doc2md[gui]'")

from doc2md.core.converter import Converter

logger = logging.getLogger(__name__)

# Dark theme colors
CTK_BG = "#0F172A"  # Dark slate
CTK_CARD = "#1E293B"  # Slate 800
CTK_ACCENT = "#06B6D4"  # Cyan
CTK_TEXT = "#F8FAFC"  # Light slate


class MainWindow:
    """Main application window with drag-and-drop file conversion."""

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title("doc2md Converter")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)

        # Configure dark theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.converter = Converter(timeout=300)
        self.is_converting = False
        self.last_result = ""

        self._setup_ui()
        self._setup_dnd()

    def _setup_ui(self):
        """Initialize UI components with CustomTkinter."""
        # Main frame
        main_frame = ctk.CTkScrollableFrame(self.root, fg_color=CTK_BG)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        main_frame.grid_columnconfigure(0, weight=1)

        # Title
        title_label = ctk.CTkLabel(
            main_frame,
            text="📄 doc2md Converter",
            font=("Arial", 24, "bold"),
            text_color=CTK_TEXT,
        )
        title_label.grid(row=0, column=0, sticky="w", pady=(0, 20))

        # Options Card
        options_card = ctk.CTkFrame(main_frame, fg_color=CTK_CARD, corner_radius=8)
        options_card.grid(row=1, column=0, sticky="ew", pady=10)
        options_card.grid_columnconfigure(1, weight=1)

        options_label = ctk.CTkLabel(
            options_card, text="Options", font=("Arial", 14, "bold"), text_color=CTK_TEXT
        )
        options_label.grid(row=0, column=0, columnspan=4, sticky="w", padx=15, pady=(10, 10))

        # Checkboxes
        self.copy_var = ctk.BooleanVar(value=True)
        copy_check = ctk.CTkCheckBox(
            options_card,
            text="Auto-copy to clipboard",
            variable=self.copy_var,
            text_color=CTK_TEXT,
            fg_color=CTK_ACCENT,
        )
        copy_check.grid(row=1, column=0, sticky="w", padx=15, pady=5)

        self.stats_var = ctk.BooleanVar(value=True)
        stats_check = ctk.CTkCheckBox(
            options_card,
            text="Show token stats",
            variable=self.stats_var,
            text_color=CTK_TEXT,
            fg_color=CTK_ACCENT,
        )
        stats_check.grid(row=1, column=1, sticky="w", padx=15, pady=5)

        self.ocr_var = ctk.BooleanVar(value=True)
        ocr_check = ctk.CTkCheckBox(
            options_card,
            text="Enable OCR",
            variable=self.ocr_var,
            text_color=CTK_TEXT,
            fg_color=CTK_ACCENT,
        )
        ocr_check.grid(row=1, column=2, sticky="w", padx=15, pady=5)

        # Model selection
        model_label = ctk.CTkLabel(
            options_card, text="Audio Model:", text_color=CTK_TEXT, font=("Arial", 12)
        )
        model_label.grid(row=2, column=0, sticky="w", padx=15, pady=5)

        self.model_var = ctk.StringVar(value="small")
        model_combo = ctk.CTkComboBox(
            options_card,
            values=["tiny", "base", "small", "medium", "large-v3"],
            variable=self.model_var,
            fg_color=CTK_ACCENT,
            button_color=CTK_ACCENT,
            text_color="black",
            width=100,
        )
        model_combo.grid(row=2, column=1, sticky="w", padx=15, pady=5)

        # Drop Zone Card
        drop_card = ctk.CTkFrame(main_frame, fg_color=CTK_CARD, corner_radius=8, border_width=2, border_color=CTK_ACCENT)
        drop_card.grid(row=2, column=0, sticky="ew", pady=20)
        drop_card.grid_columnconfigure(0, weight=1)
        drop_card.grid_rowconfigure(0, weight=1)

        self.drop_label = ctk.CTkLabel(
            drop_card,
            text="📁 Drag & Drop Files Here\n(PDF, DOCX, Images, Audio, Video)",
            font=("Arial", 14),
            text_color=CTK_ACCENT,
            wraplength=400,
        )
        self.drop_label.grid(row=0, column=0, sticky="nsew", padx=40, pady=40)

        # Store drop card for DND setup
        self.drop_card = drop_card

        # Progress Card
        progress_card = ctk.CTkFrame(main_frame, fg_color=CTK_CARD, corner_radius=8)
        progress_card.grid(row=3, column=0, sticky="ew", pady=10)
        progress_card.grid_columnconfigure(0, weight=1)

        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(
            progress_card,
            variable=self.progress_var,
            fg_color=CTK_BG,
            progress_color=CTK_ACCENT,
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 0))

        self.status_label = ctk.CTkLabel(
            progress_card, text="Ready", text_color=CTK_ACCENT, font=("Arial", 11)
        )
        self.status_label.grid(row=1, column=0, sticky="w", padx=15, pady=(5, 10))

        # Button Frame
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.grid(row=4, column=0, sticky="ew", pady=10)
        button_frame.grid_columnconfigure(0, weight=1)

        browse_btn = ctk.CTkButton(
            button_frame,
            text="📂 Browse Files",
            command=self.browse_files,
            fg_color=CTK_ACCENT,
            hover_color="#0891B2",
            text_color="black",
            font=("Arial", 12, "bold"),
        )
        browse_btn.pack(side="left", padx=5)

        copy_btn = ctk.CTkButton(
            button_frame,
            text="📋 Copy Result",
            command=self.copy_result,
            fg_color=CTK_ACCENT,
            hover_color="#0891B2",
            text_color="black",
            font=("Arial", 12, "bold"),
        )
        copy_btn.pack(side="left", padx=5)

        folder_btn = ctk.CTkButton(
            button_frame,
            text="🗂️ Open Folder",
            command=self.open_folder,
            fg_color=CTK_ACCENT,
            hover_color="#0891B2",
            text_color="black",
            font=("Arial", 12, "bold"),
        )
        folder_btn.pack(side="left", padx=5)

        exit_btn = ctk.CTkButton(
            button_frame,
            text="❌ Exit",
            command=self.root.quit,
            fg_color="#DC2626",
            hover_color="#B91C1C",
            text_color="white",
            font=("Arial", 12, "bold"),
        )
        exit_btn.pack(side="right", padx=5)

    def _setup_dnd(self):
        """Setup drag-and-drop support with fallback."""
        try:
            import tkinterdnd2

            self.drop_card.drop_target_register(tkinterdnd2.DND_FILES)
            self.drop_card.dnd_bind("<<Drop>>", self.drop_files)
            logger.info("Drag-and-drop enabled")
            self.drop_label.configure(text="📁 Drag & Drop Files Here\n(PDF, DOCX, Images, Audio, Video)")
        except Exception as exc:
            logger.warning(f"Drag-and-drop disabled: {exc}")
            self.drop_label.configure(text="📁 Click 'Browse Files' to select documents")

    def browse_files(self):
        """Open file browser to select files."""
        files = filedialog.askopenfilenames(
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
            self.convert_files(list(files))

    def drop_files(self, event):
        """Handle file drop event."""
        try:
            if hasattr(event, "data"):
                # Parse dropped files
                files = event.data.replace("{", "").replace("}", "").split()
                if files:
                    self.convert_files(files)
        except Exception as exc:
            logger.error(f"Error processing dropped files: {exc}")
            messagebox.showerror("Error", f"Error processing dropped files: {exc}")

    def convert_files(self, files: list[str]):
        """Convert files in background thread."""
        if self.is_converting:
            messagebox.showwarning("Busy", "Conversion already in progress")
            return

        if not files:
            messagebox.showwarning("No Files", "Please select files to convert")
            return

        self.is_converting = True
        thread = threading.Thread(target=self._convert_worker, args=(files,), daemon=True)
        thread.start()

    def _convert_worker(self, files: list[str]):
        """Background worker for file conversion."""
        try:
            total = len(files)
            self.status_label.configure(text=f"Converting {total} file(s)...", text_color=CTK_ACCENT)
            self.root.update()

            results = []
            for i, file_path in enumerate(files):
                progress = ((i + 1) / total) * 100
                self.progress_var.set(progress)
                self.root.update()

                try:
                    result = self.converter.convert_file(Path(file_path))
                    if result.success:
                        results.append(result.markdown)
                        logger.info(f"✅ Converted: {file_path}")
                    else:
                        logger.error(f"❌ Failed: {file_path} - {result.error}")
                except Exception as exc:
                    logger.error(f"❌ Error converting {file_path}: {exc}")

            self.progress_var.set(100)

            if results:
                self.last_result = "\n\n---\n\n".join(results)
                self.status_label.configure(
                    text=f"✅ Success: {len(results)} file(s) converted", text_color="#10B981"
                )
            else:
                self.status_label.configure(text="❌ No files converted", text_color="#DC2626")

        except Exception as exc:
            logger.exception(f"Conversion error: {exc}")
            self.status_label.configure(text=f"❌ Error: {exc}", text_color="#DC2626")
        finally:
            self.is_converting = False

    def copy_result(self):
        """Copy last conversion result to clipboard."""
        if not self.last_result:
            messagebox.showinfo("Info", "No conversion result to copy. Convert files first.")
            return

        try:
            from doc2md.core.clipboard import copy_text

            ok, msg = copy_text(self.last_result)
            if ok:
                messagebox.showinfo("Success", "Conversion result copied to clipboard!")
            else:
                messagebox.showerror("Error", f"Clipboard error: {msg}")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to copy: {exc}")

    def open_folder(self):
        """Open file browser to show converted files."""
        try:
            import subprocess
            import sys

            subprocess.Popen(f'explorer /select,"{Path.home()}"')
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to open folder: {exc}")
```
