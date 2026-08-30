# main_window.py

```python
"""Modern GUI dashboard for doc2md converter with full control set."""

from __future__ import annotations

import gc
import logging
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

try:
    import customtkinter as ctk
    from tkinter import messagebox, filedialog
except ImportError:
    import tkinter as ctk
    from tkinter import messagebox, filedialog

try:
    from tkinterdnd2 import DND_FILES, DND_TEXT
except ImportError:
    DND_FILES = None
    DND_TEXT = None

from doc2md.core.converter import Converter
from doc2md.core.errors import ConversionError
from doc2md.core.router import detect, FileKind

logger = logging.getLogger(__name__)


class MainWindow:
    """Full-featured CustomTkinter GUI for doc2md converter."""

    AUDIO_MODELS = ["tiny", "base", "small", "medium", "large-v3"]
    LANGUAGES = ["Auto-detect", "English", "Thai", "Spanish", "French", "German", "Chinese", "Japanese"]
    OUTPUT_FORMATS = ["Markdown (.md)", "Plain Text (.txt)"]

    def __init__(self, root):
        """Initialize the GUI window."""
        self.root = root
        self.root.title("doc2md - Document to Markdown Converter")
        self.root.geometry("950x800")

        # Theme setup
        try:
            if hasattr(ctk, 'set_appearance_mode'):
                ctk.set_appearance_mode("dark")
            if hasattr(ctk, 'set_default_color_theme'):
                ctk.set_default_color_theme("blue")
        except Exception as exc:
            logger.warning(f"Theme setup failed: {exc}")

        self.converter = Converter()
        self.is_converting = False
        self.cancel_event = threading.Event()
        self.conversion_thread: Optional[threading.Thread] = None
        self.selected_files: list[Path] = []

        # UI variables
        self.audio_model_var = ctk.StringVar(value="small")
        self.language_var = ctk.StringVar(value="Auto-detect")
        self.output_format_var = ctk.StringVar(value="Markdown (.md)")
        self.ocr_enabled_var = ctk.BooleanVar(value=False)
        self.copy_clipboard_var = ctk.BooleanVar(value=True)
        self.output_dir_var = ctk.StringVar(value=str(Path.home() / "Documents"))

        self._setup_ui()
        self._setup_drag_drop()
        self._setup_cleanup()

    def _setup_ui(self) -> None:
        """Set up complete UI layout with all controls."""
        # Main container
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)

        # Title
        title = ctk.CTkLabel(main_frame, text="doc2md - Document to Markdown Converter",
                            font=("Arial", 22, "bold"))
        title.pack(pady=(0, 20))

        # Settings panel - Grid-based layout to prevent text overlap
        settings_frame = ctk.CTkFrame(main_frame, fg_color=("#f5f5f5", "#2a2a2a"))
        settings_frame.pack(fill="x", padx=5, pady=(0, 15))

        # Row 1: Model, Language, Format
        row1_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        row1_frame.pack(fill="x", padx=10, pady=(10, 5))

        model_label = ctk.CTkLabel(row1_frame, text="Audio Model:", font=("Arial", 11, "bold"))
        model_label.pack(side="left", padx=5)

        model_combo = ctk.CTkComboBox(row1_frame, values=self.AUDIO_MODELS,
                                      variable=self.audio_model_var, width=100, state="readonly")
        model_combo.pack(side="left", padx=5)

        self.model_status_label = ctk.CTkLabel(row1_frame, text="Ready",
                                              text_color=("#10b981", "#34d399"), font=("Arial", 10))
        self.model_status_label.pack(side="left", padx=15)

        lang_label = ctk.CTkLabel(row1_frame, text="Language:", font=("Arial", 11, "bold"))
        lang_label.pack(side="left", padx=5)

        lang_combo = ctk.CTkComboBox(row1_frame, values=self.LANGUAGES,
                                     variable=self.language_var, width=120, state="readonly")
        lang_combo.pack(side="left", padx=5)

        format_label = ctk.CTkLabel(row1_frame, text="Format:", font=("Arial", 11, "bold"))
        format_label.pack(side="left", padx=5)

        format_combo = ctk.CTkComboBox(row1_frame, values=self.OUTPUT_FORMATS,
                                       variable=self.output_format_var, width=120, state="readonly")
        format_combo.pack(side="left", padx=5)

        # Row 2: Output Directory
        row2_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        row2_frame.pack(fill="x", padx=10, pady=(5, 10))

        output_label = ctk.CTkLabel(row2_frame, text="Output Folder:", font=("Arial", 11, "bold"))
        output_label.pack(side="left", padx=5)

        self.output_dir_entry = ctk.CTkEntry(row2_frame, textvariable=self.output_dir_var, width=350)
        self.output_dir_entry.pack(side="left", padx=5, fill="x", expand=True)

        browse_output_btn = ctk.CTkButton(row2_frame, text="Browse", command=self._browse_output_dir, width=80)
        browse_output_btn.pack(side="left", padx=5)

        # Advanced settings frame
        adv_frame = ctk.CTkFrame(main_frame, fg_color=("#f5f5f5", "#2a2a2a"))
        adv_frame.pack(fill="x", padx=5, pady=(0, 15))

        ocr_check = ctk.CTkCheckBox(adv_frame, text="Enable PDF OCR (Slower)",
                                   variable=self.ocr_enabled_var, font=("Arial", 10))
        ocr_check.pack(side="left", padx=10, pady=10)

        clip_check = ctk.CTkCheckBox(adv_frame, text="Copy to Clipboard",
                                    variable=self.copy_clipboard_var, font=("Arial", 10))
        clip_check.pack(side="left", padx=15)

        # Drop zone with rounded corners
        drop_frame = ctk.CTkFrame(main_frame, fg_color=("#e8e8e8", "#2a2a2a"), border_width=2)
        drop_frame.pack(fill="both", expand=True, padx=5, pady=(0, 15))

        drop_label = ctk.CTkLabel(drop_frame, text="📁 Drag & drop files here\nor click to browse",
                                 font=("Arial", 16, "bold"), text_color=("gray50", "gray70"))
        drop_label.pack(expand=True, pady=30)

        self.drop_zone = drop_frame
        self.drop_label = drop_label

        # Progress bar
        progress_frame = ctk.CTkFrame(main_frame)
        progress_frame.pack(fill="x", padx=5, pady=(0, 10))

        progress_label = ctk.CTkLabel(progress_frame, text="Progress:", font=("Arial", 10))
        progress_label.pack(anchor="w")

        self.progress_bar = ctk.CTkProgressBar(progress_frame, height=24, corner_radius=8)
        self.progress_bar.pack(fill="x", padx=0, pady=5)
        self.progress_bar.set(0)

        # Button frame
        button_frame = ctk.CTkFrame(main_frame)
        button_frame.pack(fill="x", padx=5, pady=(0, 15))

        browse_btn = ctk.CTkButton(button_frame, text="Browse Files",
                                  command=self._browse_files, width=120, height=38, font=("Arial", 11, "bold"))
        browse_btn.pack(side="left", padx=5)

        self.convert_button = ctk.CTkButton(button_frame, text="Convert",
                                           command=self._start_conversion, state="disabled",
                                           width=120, height=38, font=("Arial", 11, "bold"))
        self.convert_button.pack(side="left", padx=5)

        # Cancel button (hidden by default, red)
        self.cancel_button = ctk.CTkButton(button_frame, text="Cancel",
                                          command=self._cancel_conversion, state="disabled",
                                          width=120, height=38, fg_color="#DC2626", hover_color="#991b1b",
                                          font=("Arial", 11, "bold"))
        self.cancel_button.pack(side="left", padx=5)

        # Status log
        log_frame = ctk.CTkFrame(main_frame)
        log_frame.pack(fill="both", expand=True, padx=5)

        log_label = ctk.CTkLabel(log_frame, text="Status Log:", font=("Arial", 12, "bold"))
        log_label.pack(anchor="w", padx=10, pady=(10, 5))

        try:
            self.log_text = ctk.CTkTextbox(log_frame, height=150)
        except AttributeError:
            import tkinter as tk
            self.log_text = tk.Text(log_frame, height=8, width=60, wrap="word")

        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_text.configure(state="disabled")

    def _setup_drag_drop(self) -> None:
        """Setup DnD with robust event handling on entire drop frame and label."""
        if DND_FILES is None:
            logger.warning("TkinterDnD2 not available")
            return

        try:
            # Register on the main drop frame and its label for complete coverage
            self.drop_zone.drop_target_register(DND_FILES, DND_TEXT)
            self.drop_zone.dnd_bind('<<Drop>>', self._on_drop)
            self.drop_zone.dnd_bind('<<DragEnter>>', self._on_drag_enter)
            self.drop_zone.dnd_bind('<<DragLeave>>', self._on_drag_leave)

            # Also bind to the label to catch drops on the label itself
            self.drop_label.drop_target_register(DND_FILES, DND_TEXT)
            self.drop_label.dnd_bind('<<Drop>>', self._on_drop)
            self.drop_label.dnd_bind('<<DragEnter>>', self._on_drag_enter)
            self.drop_label.dnd_bind('<<DragLeave>>', self._on_drag_leave)

            logger.info("DnD registered successfully on drop_zone frame and label")
        except Exception as exc:
            logger.warning(f"DnD setup failed: {exc}")

    def _on_drag_enter(self, event) -> str:
        """Visual feedback on drag enter."""
        try:
            self.drop_zone.configure(fg_color=("#d0d0d0", "#404040"))
            self.drop_label.configure(text_color=("gray30", "gray90"))
        except Exception:
            pass
        return "copy"

    def _on_drag_leave(self, event) -> str:
        """Restore color on drag leave."""
        try:
            self.drop_zone.configure(fg_color=("#e8e8e8", "#2a2a2a"))
            self.drop_label.configure(text_color=("gray50", "gray70"))
        except Exception:
            pass
        return "refuse"

    def _on_drop(self, event) -> str:
        """Handle dropped files with robust parsing."""
        try:
            self.drop_zone.configure(fg_color=("#e8e8e8", "#2a2a2a"))
            self.drop_label.configure(text_color=("gray50", "gray70"))

            raw_data = event.data if isinstance(event.data, str) else str(event.data)
            logger.info(f"Drop event received: {raw_data[:100]}")

            # Parse paths robustly
            try:
                paths = shlex.split(raw_data)
            except ValueError:
                paths = raw_data.split()

            cleaned_paths = []
            for path_str in paths:
                path_str = path_str.strip().strip('{}')
                if path_str:
                    cleaned_paths.append(path_str)

            if not cleaned_paths:
                self._log("❌ No files received")
                return "refuse"

            # Validate paths
            valid_paths = []
            for path_str in cleaned_paths:
                try:
                    path = Path(path_str).resolve()
                    if path.is_file():
                        valid_paths.append(path)
                        self._log(f"✓ {path.name}")
                    elif path.is_dir():
                        for subfile in path.rglob("*"):
                            if subfile.is_file():
                                try:
                                    detection = detect(subfile)
                                    if detection.kind in [
                                        FileKind.PDF, FileKind.DOCX, FileKind.XLSX,
                                        FileKind.PPTX, FileKind.HTML, FileKind.IMAGE,
                                        FileKind.AUDIO, FileKind.VIDEO, FileKind.CODE
                                    ]:
                                        valid_paths.append(subfile)
                                except Exception:
                                    pass
                except Exception as exc:
                    self._log(f"⚠️ {path_str}: {exc}")

            if valid_paths:
                self.selected_files = valid_paths
                self.convert_button.configure(state="normal")
                self._log(f"✅ Ready: {len(valid_paths)} file(s)")
                return "copy"
            else:
                self._log("❌ No supported files")
                return "refuse"

        except Exception as exc:
            logger.exception(f"Drop error: {exc}")
            self._show_error_dialog("Drop Error", f"Error processing files:\n{exc}")
            return "refuse"

    def _browse_files(self) -> None:
        """File browser dialog."""
        try:
            filetypes = [
                ("All Supported", "*.pdf *.docx *.xlsx *.pptx *.html *.mp3 *.wav *.mp4"),
                ("Documents", "*.pdf *.docx *.xlsx *.pptx *.html"),
                ("Audio/Video", "*.mp3 *.wav *.m4a *.mp4 *.mkv"),
                ("All Files", "*.*"),
            ]
            files = filedialog.askopenfilenames(title="Select files", filetypes=filetypes)
            if files:
                self.selected_files = [Path(f) for f in files]
                self.convert_button.configure(state="normal")
                self._log(f"✅ Selected {len(self.selected_files)} file(s)")
        except Exception as exc:
            self._show_error_dialog("Browse Error", str(exc))

    def _browse_output_dir(self) -> None:
        """Browse for output directory."""
        try:
            current_dir = self.output_dir_var.get()
            selected_dir = filedialog.askdirectory(title="Select Output Folder", initialdir=current_dir)
            if selected_dir:
                self.output_dir_var.set(selected_dir)
                self._log(f"📁 Output folder: {selected_dir}")
        except Exception as exc:
            self._show_error_dialog("Browse Error", str(exc))

    def _start_conversion(self) -> None:
        """Start conversion in background thread."""
        if not self.selected_files or self.is_converting:
            return

        self.is_converting = True
        self.cancel_event.clear()
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress_bar.set(0)

        self.conversion_thread = threading.Thread(target=self._conversion_worker, daemon=True)
        self.conversion_thread.start()

    def _cancel_conversion(self) -> None:
        """Cancel the running conversion."""
        self._log("⏹️ Cancellation requested...")
        self.cancel_event.set()
        self.is_converting = False

    def _conversion_worker(self) -> None:
        """Background conversion worker."""
        try:
            self._log("🔄 Starting conversion...")

            # Update converter options
            self.converter.options.update({
                "audio_model": self.audio_model_var.get(),
                "pdf_ocr_fallback": self.ocr_enabled_var.get(),
            })

            for idx, file_path in enumerate(self.selected_files):
                if self.cancel_event.is_set():
                    self._log("⏹️ Conversion cancelled by user")
                    break

                try:
                    self._log(f"Processing: {file_path.name}...")

                    # Update progress
                    progress = (idx + 1) / len(self.selected_files)
                    self.progress_bar.set(progress)

                    # Call convert_file with correct signature (no options argument)
                    result = self.converter.convert_file(file_path)

                    if result.success:
                        # Determine output format and directory
                        output_dir = Path(self.output_dir_var.get())
                        output_dir.mkdir(parents=True, exist_ok=True)

                        if self.output_format_var.get() == "Plain Text (.txt)":
                            output_path = output_dir / file_path.with_suffix(".txt").name
                        else:
                            output_path = output_dir / file_path.with_suffix(".md").name

                        output_path.write_text(result.markdown, encoding="utf-8")
                        self._log(f"✅ {file_path.name} → {output_path.name}")

                        # Copy to clipboard if enabled
                        if self.copy_clipboard_var.get():
                            try:
                                from doc2md.core.clipboard import copy_text
                                copy_text(result.markdown)
                                self._log(f"📋 Copied to clipboard")
                            except Exception:
                                pass
                    else:
                        self._log(f"❌ {file_path.name}: {result.error}")

                except ConversionError as exc:
                    self._log(f"❌ {file_path.name}: {str(exc)}")
                except Exception as exc:
                    self._log(f"❌ {file_path.name}: {type(exc).__name__}: {str(exc)}")
                    logger.exception(f"Conversion error: {exc}")

            if not self.cancel_event.is_set():
                self._log("✅ All conversions complete")
                self.progress_bar.set(1.0)

        except Exception as exc:
            self._log(f"❌ Fatal error: {exc}")
            logger.exception(f"Worker error: {exc}")

        finally:
            self.is_converting = False
            self.convert_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            gc.collect()

    def _log(self, message: str) -> None:
        """Thread-safe logging."""
        try:
            def update():
                self.log_text.configure(state="normal")
                self.log_text.insert("end", f"{message}\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")

            if threading.current_thread() is threading.main_thread():
                update()
            else:
                self.root.after(0, update)
        except Exception as exc:
            logger.warning(f"Log error: {exc}")

    def _show_error_dialog(self, title: str, message: str) -> None:
        """Thread-safe error dialog."""
        def show():
            messagebox.showerror(title, message)

        if threading.current_thread() is threading.main_thread():
            show()
        else:
            self.root.after(0, show)

    def _setup_cleanup(self) -> None:
        """Setup shutdown cleanup."""
        def on_closing():
            if self.is_converting:
                if not messagebox.askyesno("Confirm", "Conversion in progress. Cancel and exit?"):
                    return
                self.cancel_event.set()
                self.is_converting = False
                if self.conversion_thread and self.conversion_thread.is_alive():
                    self.conversion_thread.join(timeout=5)

            try:
                from doc2md.engine.audio_engine import AudioEngine
                AudioEngine.kill_all_ffmpeg_processes()
                AudioEngine.cleanup_temp_audio_chunks()
            except Exception:
                pass

            gc.collect()
            self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", on_closing)
```
