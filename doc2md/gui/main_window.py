"""Modern GUI dashboard for doc2md converter with drag-and-drop support."""

from __future__ import annotations

import gc
import logging
import os
import shlex
import subprocess
import sys
import threading
import traceback
from pathlib import Path
from typing import Optional

try:
    import customtkinter as ctk
    from tkinter import messagebox, filedialog
except ImportError:
    # Graceful fallback if CustomTkinter not available
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
    """Modern CustomTkinter-based GUI for doc2md converter."""

    def __init__(self, root):
        """Initialize the GUI window.

        Args:
            root: tk.Tk root window instance (or compatible)
        """
        self.root = root
        self.root.title("doc2md - Document to Markdown Converter")
        self.root.geometry("800x600")

        # Configure dark/light theme if using CustomTkinter
        try:
            if hasattr(ctk, 'set_appearance_mode'):
                ctk.set_appearance_mode("dark")
            if hasattr(ctk, 'set_default_color_theme'):
                ctk.set_default_color_theme("blue")
        except Exception as exc:
            logger.warning(f"Theme configuration failed (using fallback): {exc}")

        self.converter = Converter()
        self.is_converting = False
        self.conversion_thread: Optional[threading.Thread] = None

        self._setup_ui()
        self._setup_drag_drop()
        self._setup_cleanup()

    def _setup_ui(self) -> None:
        """Set up the main UI layout."""
        # Main frame
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Title label
        title_label = ctk.CTkLabel(
            main_frame,
            text="doc2md - Convert Documents to Markdown",
            font=("Arial", 18, "bold")
        )
        title_label.pack(pady=(0, 20))

        # Drop zone frame
        drop_frame = ctk.CTkFrame(main_frame, fg_color=("#e8e8e8", "#2a2a2a"), border_width=2)
        drop_frame.pack(fill="both", expand=True, padx=10, pady=10)

        drop_label = ctk.CTkLabel(
            drop_frame,
            text="📁 Drag & drop files here\nor click to browse",
            font=("Arial", 14),
            text_color=("gray50", "gray70")
        )
        drop_label.pack(expand=True)

        self.drop_zone = drop_frame
        self.drop_label = drop_label

        # Button frame
        button_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=10, pady=10)

        browse_button = ctk.CTkButton(
            button_frame,
            text="Browse Files",
            command=self._browse_files,
            width=120,
            height=40
        )
        browse_button.pack(side="left", padx=5)

        self.convert_button = ctk.CTkButton(
            button_frame,
            text="Convert",
            command=self._start_conversion,
            state="disabled",
            width=120,
            height=40
        )
        self.convert_button.pack(side="left", padx=5)

        # Status and log frame
        log_frame = ctk.CTkFrame(main_frame)
        log_frame.pack(fill="both", expand=True, padx=10, pady=10)

        log_label = ctk.CTkLabel(log_frame, text="Status Log:", font=("Arial", 12, "bold"))
        log_label.pack(anchor="w")

        # Text widget for logs (compatibility with both ctk and tk)
        try:
            self.log_text = ctk.CTkTextbox(log_frame, height=150)
        except AttributeError:
            # Fallback for older CustomTkinter or pure tkinter
            import tkinter as tk
            self.log_text = tk.Text(log_frame, height=10, width=50)

        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text.configure(state="disabled")

        # Store selected files
        self.selected_files: list[Path] = []

    def _setup_drag_drop(self) -> None:
        """Configure drag & drop handling with Unicode & space support."""
        if DND_FILES is None:
            logger.warning("TkinterDnD2 not available - drag & drop disabled")
            return

        try:
            self.drop_zone.drop_target_register(DND_FILES, DND_TEXT)
            self.drop_zone.dnd_bind('<<Drop>>', self._on_drop)
            self.drop_zone.dnd_bind('<<DragEnter>>', self._on_drag_enter)
            self.drop_zone.dnd_bind('<<DragLeave>>', self._on_drag_leave)
        except Exception as exc:
            logger.warning(f"Drag & drop setup failed: {exc}")

    def _on_drag_enter(self, event) -> str:
        """Handle drag enter event."""
        self.drop_zone.configure(fg_color=("#d8d8d8", "#333333"))
        return event.action

    def _on_drag_leave(self, event) -> str:
        """Handle drag leave event."""
        self.drop_zone.configure(fg_color=("#e8e8e8", "#2a2a2a"))
        return event.action

    def _on_drop(self, event) -> str:
        """Handle file drop with robust path parsing for Unicode & spaces.

        TkinterDnD2 wraps paths with spaces in curly braces `{}`.
        This handler safely extracts and validates all paths.
        """
        try:
            self.drop_zone.configure(fg_color=("#e8e8e8", "#2a2a2a"))

            # Parse event.data safely - handle Windows/Unix path formats
            raw_data = event.data if isinstance(event.data, str) else str(event.data)

            # First, try shlex.split() for standard shell-quoted paths
            try:
                paths = shlex.split(raw_data)
            except ValueError:
                # Fallback: split by spaces if shlex fails (malformed input)
                paths = raw_data.split()

            # Strip TkinterDnD2's curly braces wrapper
            cleaned_paths = []
            for path_str in paths:
                path_str = path_str.strip()
                # Remove curly braces that TkinterDnD2 adds
                path_str = path_str.strip('{}')
                if path_str:
                    cleaned_paths.append(path_str)

            if not cleaned_paths:
                self._log("❌ No valid files received")
                return "refuse"

            # Resolve and validate paths
            valid_paths = []
            for path_str in cleaned_paths:
                try:
                    path = Path(path_str).resolve()
                    if path.is_file():
                        valid_paths.append(path)
                        self._log(f"✓ Detected: {path.name}")
                    elif path.is_dir():
                        # Recursively add all supported files from directory
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
                    self._log(f"⚠️ Invalid path: {path_str} ({exc})")

            if valid_paths:
                self.selected_files = valid_paths
                self.convert_button.configure(state="normal")
                self._log(f"✅ Ready to convert {len(valid_paths)} file(s)")
            else:
                self._log("❌ No supported files found")
                return "refuse"

            return "copy"

        except Exception as exc:
            # Catch native/C-level exceptions and show friendly error
            error_msg = f"{type(exc).__name__}: {str(exc)}"
            logger.exception(f"Drop handler crashed: {error_msg}")
            self._show_error_dialog(
                "File Drop Error",
                f"Failed to process dropped files:\n{error_msg}\n\n"
                "Please try again or use the Browse button."
            )
            return "refuse"

    def _browse_files(self) -> None:
        """Browse and select files."""
        try:
            filetypes = [
                ("All Supported", "*.pdf *.docx *.xlsx *.pptx *.html *.eml *.mp3 *.wav *.mp4"),
                ("PDF", "*.pdf"),
                ("Word", "*.docx"),
                ("Excel", "*.xlsx"),
                ("PowerPoint", "*.pptx"),
                ("HTML", "*.html"),
                ("Audio", "*.mp3 *.wav *.m4a *.aac"),
                ("Video", "*.mp4 *.mkv *.avi"),
                ("All Files", "*.*"),
            ]

            files = filedialog.askopenfilenames(
                title="Select files to convert",
                filetypes=filetypes
            )

            if files:
                self.selected_files = [Path(f) for f in files]
                self.convert_button.configure(state="normal")
                self._log(f"✅ Selected {len(self.selected_files)} file(s)")
        except Exception as exc:
            self._show_error_dialog("Browse Error", f"Failed to open file dialog: {exc}")

    def _start_conversion(self) -> None:
        """Start conversion in a background thread."""
        if not self.selected_files:
            self._log("❌ No files selected")
            return

        if self.is_converting:
            self._log("⏳ Conversion already in progress")
            return

        self.is_converting = True
        self.convert_button.configure(state="disabled")
        self.conversion_thread = threading.Thread(target=self._conversion_worker, daemon=True)
        self.conversion_thread.start()

    def _conversion_worker(self) -> None:
        """Worker thread for file conversion."""
        try:
            self._log("🔄 Starting conversion...")

            results = []
            for file_path in self.selected_files:
                if self.is_converting is False:
                    break

                try:
                    self._log(f"Processing: {file_path.name}...")
                    result = self.converter.convert_file(file_path)

                    if result.success:
                        output_path = file_path.with_suffix(".md")
                        output_path.write_text(result.markdown, encoding="utf-8")
                        self._log(f"✅ {file_path.name} → {output_path.name}")
                        results.append((True, file_path.name))
                    else:
                        self._log(f"❌ {file_path.name}: {result.error}")
                        results.append((False, file_path.name))

                except ConversionError as exc:
                    self._log(f"❌ {file_path.name}: {str(exc)}")
                    results.append((False, file_path.name))
                except Exception as exc:
                    error_msg = f"{type(exc).__name__}: {str(exc)}"
                    self._log(f"❌ {file_path.name}: {error_msg}")
                    logger.exception(f"Conversion error: {error_msg}")
                    results.append((False, file_path.name))

            # Summary
            successes = sum(1 for ok, _ in results if ok)
            total = len(results)
            self._log(f"✅ Conversion complete: {successes}/{total} succeeded")

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {str(exc)}"
            self._log(f"❌ Fatal conversion error: {error_msg}")
            logger.exception(f"Worker error: {error_msg}")

        finally:
            self.is_converting = False
            self.convert_button.configure(state="normal")
            # Force garbage collection to release resources
            gc.collect()

    def _log(self, message: str) -> None:
        """Append message to log text widget (thread-safe)."""
        try:
            def update_log():
                self.log_text.configure(state="normal")
                self.log_text.insert("end", f"{message}\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")

            # Schedule on main thread if called from worker thread
            if threading.current_thread() is threading.main_thread():
                update_log()
            else:
                self.root.after(0, update_log)
        except Exception as exc:
            logger.warning(f"Failed to log message: {exc}")

    def _show_error_dialog(self, title: str, message: str) -> None:
        """Show error dialog (thread-safe)."""
        def show_dialog():
            messagebox.showerror(title, message)

        if threading.current_thread() is threading.main_thread():
            show_dialog()
        else:
            self.root.after(0, show_dialog)

    def _setup_cleanup(self) -> None:
        """Setup cleanup handlers for graceful shutdown."""
        def on_closing():
            if self.is_converting:
                if messagebox.askyesno("Confirm", "Conversion in progress. Cancel and exit?"):
                    self.is_converting = False
                    # Wait for thread to finish (with timeout)
                    if self.conversion_thread and self.conversion_thread.is_alive():
                        self.conversion_thread.join(timeout=5)
                else:
                    return

            # Cleanup: release resources
            try:
                from doc2md.engine.audio_engine import AudioEngine
                AudioEngine.kill_all_ffmpeg_processes()
                AudioEngine.cleanup_temp_audio_chunks()
            except Exception:
                pass

            gc.collect()
            self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", on_closing)
