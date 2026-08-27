# main_window.py

```python
"""Main GUI window with CustomTkinter Modern Clean theme and native (windnd) drag-and-drop support."""

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

from doc2md import __version__
from doc2md.core.converter import Converter
from doc2md.core.exporter import export_markdown
from doc2md.engine.audio_engine import AudioEngine

logger = logging.getLogger(__name__)

# Modern Clean UI theme colors (Tailwind-inspired: slate + blue)
CTK_BG = "#f8fafc"  # slate-50 page background
CTK_CARD = "#ffffff"  # Crisp white card
CTK_ACCENT_BLUE = "#2563eb"  # blue-600 primary action
CTK_ACCENT_BLUE_HOVER = "#1d4ed8"  # blue-700 hover
CTK_ACCENT_CYAN = "#0d9488"  # teal-600 secondary action
CTK_ACCENT_CYAN_HOVER = "#0f766e"  # teal-700 hover
CTK_ACCENT_PINK = "#ef4444"  # red-500 destructive action
CTK_ACCENT_PINK_HOVER = "#dc2626"  # red-600 hover
CTK_TEXT = "#1e293b"  # slate-800 crisp primary text
CTK_BORDER = "#e2e8f0"  # slate-200 subtle border
CTK_SECONDARY_TEXT = "#64748b"  # slate-500 muted secondary text
CTK_TEAL_TEXT = "#0f766e"  # teal-700 readable accent text
CTK_SUCCESS = "#059669"  # emerald-600 success
CTK_ERROR = "#dc2626"  # red-600 error

# Shared font family for crisp, consistently-aligned icon+text rendering
UI_FONT = "Segoe UI"


class MainWindow:
    """Main application window with drag-and-drop file conversion."""

    def __init__(self, root: ctk.CTk):
        self.root = root
        self.root.title(f"doc2md Converter v{__version__}")
        self.root.geometry("900x700")
        self.root.minsize(700, 500)

        # Configure Modern Clean light theme
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.converter = Converter(timeout=300, options={"audio_model": "small"})
        self.audio_engine = AudioEngine()
        self.is_converting = False
        self.last_result = ""
        self.staged_files: list[str] = []

        self._setup_ui()
        self._setup_dnd()

        # Warm up the default audio model in the background so the first
        # conversion doesn't pay the (multi-second) model-load cost lazily.
        self._preload_model_async(self.model_var.get())

    def _setup_ui(self):
        """Initialize UI components with a Modern Clean (Tailwind-inspired) theme."""
        # Root container
        root_frame = ctk.CTkFrame(self.root, fg_color=CTK_BG)
        root_frame.pack(fill="both", expand=True)

        # Header Container with Title and Version Badge
        header_frame = ctk.CTkFrame(root_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=12)
        header_frame.grid_columnconfigure(0, weight=1)

        # Title Label
        title_label = ctk.CTkLabel(
            header_frame,
            text="📄 doc2md",
            font=(UI_FONT, 24, "bold"),
            text_color=CTK_TEXT,
            anchor="w",
            justify="left",
        )
        title_label.grid(row=0, column=0, sticky="w")

        # Version Badge (top-right)
        version_badge = ctk.CTkLabel(
            header_frame,
            text=f"v{__version__}",
            font=(UI_FONT, 10, "bold"),
            text_color="#ffffff",
            fg_color=CTK_ACCENT_BLUE,
            padx=8,
            pady=4,
            corner_radius=12,
            anchor="center",
        )
        version_badge.grid(row=0, column=1, sticky="e", padx=0)

        # Subtitle
        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="Convert documents to optimized Markdown with AI",
            font=(UI_FONT, 11),
            text_color=CTK_SECONDARY_TEXT,
            anchor="w",
            justify="left",
        )
        subtitle_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Main content frame (2 columns)
        content_frame = ctk.CTkFrame(root_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=12, pady=12)

        # Left Column: Drop Zone (using pack inside content_frame)
        drop_card = ctk.CTkFrame(
            content_frame, fg_color=CTK_CARD, corner_radius=12, border_width=2, border_color=CTK_BORDER
        )
        drop_card.pack(side="left", fill="both", expand=True, padx=(0, 6))
        # Hover effect: change border on interaction
        drop_card.bind("<Enter>", lambda e: drop_card.configure(border_color=CTK_ACCENT_BLUE))
        drop_card.bind("<Leave>", lambda e: drop_card.configure(border_color=CTK_BORDER))

        self.drop_label = ctk.CTkLabel(
            drop_card,
            text="📁 Click or Drag & Drop Files Here\n(PDF, DOCX, Images, Audio, Video)",
            font=(UI_FONT, 13),
            text_color=CTK_TEAL_TEXT,
            wraplength=350,
            anchor="center",
            justify="center",
        )
        self.drop_label.pack(fill="both", expand=True, padx=30, pady=30)
        self.drop_card = drop_card

        # Bind click event to drop card for fallback file browser
        drop_card.bind("<Button-1>", lambda e: self.browse_files())
        self.drop_label.bind("<Button-1>", lambda e: self.browse_files())

        # Staging status label
        self.staging_status_label = ctk.CTkLabel(
            content_frame,
            text="",
            text_color=CTK_SECONDARY_TEXT,
            font=(UI_FONT, 10),
            anchor="w",
        )
        self.staging_status_label.pack(side="left", fill="x", padx=12, pady=(4, 0))

        # Right Column: Options & Analytics
        right_frame = ctk.CTkScrollableFrame(content_frame, fg_color="transparent")
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        # Options Card
        options_card = ctk.CTkFrame(right_frame, fg_color=CTK_CARD, corner_radius=8)
        options_card.pack(fill="x", pady=(0, 10))
        options_card.grid_columnconfigure(1, weight=1)

        options_label = ctk.CTkLabel(
            options_card,
            text="⚙️ Options",
            font=(UI_FONT, 13, "bold"),
            text_color=CTK_TEXT,
            anchor="w",
        )
        options_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 10))

        checkbox_kwargs = dict(
            text_color=CTK_TEXT,
            fg_color=CTK_ACCENT_BLUE,
            hover_color=CTK_ACCENT_BLUE_HOVER,
            font=(UI_FONT, 12),
            checkbox_width=20,
            checkbox_height=20,
        )

        self.copy_var = ctk.BooleanVar(value=True)
        copy_check = ctk.CTkCheckBox(
            options_card,
            text="Auto-copy to clipboard",
            variable=self.copy_var,
            **checkbox_kwargs,
        )
        copy_check.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=4)

        self.stats_var = ctk.BooleanVar(value=True)
        stats_check = ctk.CTkCheckBox(
            options_card,
            text="Show token stats",
            variable=self.stats_var,
            **checkbox_kwargs,
        )
        stats_check.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=4)

        self.ocr_var = ctk.BooleanVar(value=True)
        ocr_check = ctk.CTkCheckBox(
            options_card,
            text="Enable OCR",
            variable=self.ocr_var,
            **checkbox_kwargs,
        )
        ocr_check.grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=4)

        model_label = ctk.CTkLabel(
            options_card,
            text="Audio Model:",
            text_color=CTK_TEXT,
            font=(UI_FONT, 11),
            anchor="w",
        )
        model_label.grid(row=4, column=0, sticky="w", padx=12, pady=(10, 3))

        self.model_var = ctk.StringVar(value="small")
        model_combo = ctk.CTkComboBox(
            options_card,
            values=["tiny", "base", "small", "medium", "large-v3"],
            variable=self.model_var,
            command=self._on_model_change,
            fg_color="#ffffff",
            border_color=CTK_BORDER,
            button_color=CTK_ACCENT_BLUE,
            button_hover_color=CTK_ACCENT_BLUE_HOVER,
            text_color=CTK_TEXT,
            font=(UI_FONT, 11),
            width=120,
            justify="center",
        )
        model_combo.grid(row=4, column=1, sticky="e", padx=12, pady=(10, 3))

        # Model warm-up status indicator
        self.model_status_label = ctk.CTkLabel(
            options_card,
            text="",
            text_color=CTK_SECONDARY_TEXT,
            font=(UI_FONT, 10),
            anchor="w",
        )
        self.model_status_label.grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

        # Analytics Card
        analytics_card = ctk.CTkFrame(right_frame, fg_color=CTK_CARD, corner_radius=8)
        analytics_card.pack(fill="x", pady=(0, 10))

        analytics_label = ctk.CTkLabel(
            analytics_card,
            text="📊 Analytics",
            font=(UI_FONT, 13, "bold"),
            text_color=CTK_TEXT,
            anchor="w",
        )
        analytics_label.pack(anchor="w", padx=12, pady=(8, 5))

        self.analytics_text = ctk.CTkLabel(
            analytics_card,
            text="No conversion yet",
            font=(UI_FONT, 10),
            text_color=CTK_SECONDARY_TEXT,
            anchor="w",
        )
        self.analytics_text.pack(anchor="w", padx=12, pady=(0, 8))

        # Progress Card with Embedded Percentage
        progress_card = ctk.CTkFrame(root_frame, fg_color=CTK_CARD, corner_radius=12)
        progress_card.pack(fill="x", padx=12, pady=(0, 12))
        progress_card.grid_columnconfigure(0, weight=1)

        # Progress bar container
        progress_container = ctk.CTkFrame(progress_card, fg_color=CTK_CARD, corner_radius=8)
        progress_container.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        progress_container.grid_columnconfigure(0, weight=1)

        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(
            progress_container,
            variable=self.progress_var,
            fg_color=CTK_BORDER,
            progress_color=CTK_ACCENT_BLUE,
            height=32,
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew")

        # Percentage text embedded on the progress bar
        self.progress_overlay = ctk.CTkLabel(
            progress_container,
            text="0%",
            font=(UI_FONT, 11, "bold"),
            text_color=CTK_TEXT,
            anchor="center",
        )
        self.progress_overlay.place(relx=0.5, rely=0.5, anchor="center")

        self.status_label = ctk.CTkLabel(
            progress_card,
            text="Ready",
            text_color=CTK_TEAL_TEXT,
            font=(UI_FONT, 10),
            anchor="w",
        )
        self.status_label.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        # Bottom Action Panel
        button_frame = ctk.CTkFrame(root_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=10, pady=(0, 10))
        button_frame.grid_columnconfigure(0, weight=1)

        btn_kwargs = dict(
            font=(UI_FONT, 12, "bold"),
            corner_radius=8,
            text_color="#ffffff",
            height=38,
            anchor="center",
        )

        browse_btn = ctk.CTkButton(
            button_frame,
            text="📂  Browse Files",
            command=self.browse_files,
            fg_color=CTK_ACCENT_BLUE,
            hover_color=CTK_ACCENT_BLUE_HOVER,
            **btn_kwargs,
        )
        browse_btn.pack(side="left", padx=3)

        self.convert_btn = ctk.CTkButton(
            button_frame,
            text="▶️  Start Conversion",
            command=self._start_conversion,
            fg_color="#059669",
            hover_color="#047857",
            **btn_kwargs,
        )
        self.convert_btn.pack(side="left", padx=3)

        copy_btn = ctk.CTkButton(
            button_frame,
            text="📋  Copy Result",
            command=self.copy_result,
            fg_color=CTK_ACCENT_BLUE,
            hover_color=CTK_ACCENT_BLUE_HOVER,
            **btn_kwargs,
        )
        copy_btn.pack(side="left", padx=3)

        save_btn = ctk.CTkButton(
            button_frame,
            text="💾  Save As...",
            command=self.save_result,
            fg_color=CTK_ACCENT_CYAN,
            hover_color=CTK_ACCENT_CYAN_HOVER,
            **btn_kwargs,
        )
        save_btn.pack(side="left", padx=3)

        folder_btn = ctk.CTkButton(
            button_frame,
            text="🗂️  Open Folder",
            command=self.open_folder,
            fg_color=CTK_ACCENT_BLUE,
            hover_color=CTK_ACCENT_BLUE_HOVER,
            **btn_kwargs,
        )
        folder_btn.pack(side="left", padx=3)

        exit_btn = ctk.CTkButton(
            button_frame,
            text="❌  Exit",
            command=self.root.quit,
            fg_color=CTK_ACCENT_PINK,
            hover_color=CTK_ACCENT_PINK_HOVER,
            **btn_kwargs,
        )
        exit_btn.pack(side="right", padx=3)

    def _on_model_change(self, selected_model: str):
        """Triggered when the user picks a different Whisper model size."""
        self.converter.options["audio_model"] = selected_model
        self._preload_model_async(selected_model)

    def _preload_model_async(self, model_size: str):
        """Warm up (load + cache) the given Whisper model in a background
        thread, updating a visual status indicator instead of blocking the UI
        or lazily paying the load cost during the first conversion."""
        self.model_status_label.configure(
            text=f"⏳ Warming up '{model_size}' model...", text_color=CTK_TEAL_TEXT
        )

        def worker():
            try:
                self.audio_engine.preload_model(model_size)
                self.root.after(
                    0,
                    lambda: self.model_status_label.configure(
                        text=f"✅ '{model_size}' model ready", text_color=CTK_SUCCESS
                    ),
                )
            except Exception as exc:
                logger.warning(f"Model preload failed: {exc}")
                self.root.after(
                    0,
                    lambda: self.model_status_label.configure(
                        text=f"⚠️ Model will load on first use", text_color=CTK_SECONDARY_TEXT
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _setup_dnd(self):
        """Setup native Windows drag-and-drop support (windnd) with fallback."""
        try:
            import windnd

            windnd.hook_dropfiles(self.root, func=self._on_windnd_drop)
            logger.info("Native drag-and-drop enabled (windnd)")
            self.drop_label.configure(text="📁 Drag & Drop Files Here\n(PDF, DOCX, Images, Audio, Video)")
        except Exception as exc:
            logger.warning(f"Drag-and-drop disabled: {exc}")
            self.drop_label.configure(text="📁 Click 'Browse Files' to select documents")

    def _on_windnd_drop(self, filenames):
        """Handle files dropped via windnd's native Windows drop hook."""
        try:
            decoded = [
                f.decode("utf-8", errors="ignore") if isinstance(f, bytes) else f
                for f in filenames
            ]
            if decoded:
                self._stage_files(decoded)
        except Exception as exc:
            logger.error(f"Error processing dropped files: {exc}")
            messagebox.showerror("Error", f"Error processing dropped files: {exc}")

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
            self._stage_files(list(files))

    def _stage_files(self, files: list[str]):
        """Stage files for conversion (store them but don't start conversion yet)."""
        if not files:
            return
        self.staged_files = files
        self._update_staging_status()

    def _update_staging_status(self):
        """Update the UI to show how many files are staged."""
        if self.staged_files:
            count = len(self.staged_files)
            status = f"✓ {count} file(s) ready for conversion. Click 'Start Conversion' to begin."
            self.staging_status_label.configure(
                text=status,
                text_color=CTK_SUCCESS,
            )
            self.convert_btn.configure(state="normal")
        else:
            self.staging_status_label.configure(text="")
            self.convert_btn.configure(state="disabled")

    def _start_conversion(self):
        """Start the conversion process using staged files."""
        if not self.staged_files:
            messagebox.showwarning("No Files", "Please select files to convert")
            return
        self.convert_files(self.staged_files)

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
            self.status_label.configure(text=f"Converting {total} file(s)...", text_color=CTK_TEAL_TEXT)
            # Set progress to indeterminate (pulsing between 0.3 and 0.7)
            self.progress_overlay.configure(text="Processing...")
            self.root.update()

            results = []
            errors = []
            pulse_direction = 1
            pulse_value = 0.3
            for i, file_path in enumerate(files):
                # Simulate indeterminate progress by pulsing
                pulse_value += 0.05 * pulse_direction
                if pulse_value >= 0.7:
                    pulse_direction = -1
                elif pulse_value <= 0.3:
                    pulse_direction = 1
                self.progress_var.set(pulse_value)
                self.root.update()

                try:
                    result = self.converter.convert_file(Path(file_path))
                    if result.success:
                        results.append(result.markdown)
                        logger.info(f"✅ Converted: {file_path}")
                    else:
                        error_msg = f"{Path(file_path).name}: {result.error}"
                        errors.append(error_msg)
                        logger.error(f"❌ Failed: {error_msg}")
                except Exception as exc:
                    error_msg = f"{Path(file_path).name}: {type(exc).__name__}: {str(exc)}"
                    errors.append(error_msg)
                    logger.error(f"❌ Error converting {file_path}: {exc}")

            # Mark completion with full progress bar
            self.progress_var.set(1.0)
            self.progress_overlay.configure(text="100%")

            if results:
                self.last_result = "\n\n---\n\n".join(results)
                status_msg = f"✅ Success: {len(results)} file(s) converted"
                if errors:
                    status_msg += f" ({len(errors)} failed)"
                self.status_label.configure(text=status_msg, text_color=CTK_SUCCESS)
                self.analytics_text.configure(text=f"Files: {len(results)} | Ready to export")

                # Show errors if any
                if errors:
                    error_summary = "\n".join(errors[:5])
                    if len(errors) > 5:
                        error_summary += f"\n... and {len(errors) - 5} more errors"
                    messagebox.showwarning("Partial Conversion", f"Some files failed to convert:\n\n{error_summary}")
            else:
                self.status_label.configure(text="❌ No files converted", text_color=CTK_ERROR)
                if errors:
                    error_summary = "\n".join(errors[:5])
                    if len(errors) > 5:
                        error_summary += f"\n... and {len(errors) - 5} more errors"
                    messagebox.showerror("Conversion Failed", f"All files failed to convert:\n\n{error_summary}")
                else:
                    messagebox.showerror("Conversion Failed", "No files were converted. Please check your files and try again.")

        except Exception as exc:
            logger.exception(f"Conversion error: {exc}")
            self.status_label.configure(text=f"❌ Error: {exc}", text_color=CTK_ERROR)
            messagebox.showerror("Conversion Error", f"An unexpected error occurred:\n\n{type(exc).__name__}: {str(exc)}")
        finally:
            self.is_converting = False
            self.staged_files.clear()
            self._update_staging_status()

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

    def save_result(self):
        """Save conversion result in selected format."""
        if not self.last_result:
            messagebox.showinfo("Info", "No conversion result to save. Convert files first.")
            return

        output_path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[
                ("Markdown", "*.md"),
                ("Word Document", "*.docx"),
                ("Plain Text", "*.txt"),
                ("All Files", "*.*"),
            ],
        )

        if not output_path:
            return

        try:
            path = Path(output_path)
            ext_map = {".md": "md", ".txt": "txt", ".docx": "docx"}
            format_type = ext_map.get(path.suffix, "md")

            success, msg = export_markdown(self.last_result, path, format_type=format_type)
            if success:
                messagebox.showinfo("Success", f"✅ {msg}")
                logger.info(f"Exported to {path}")
            else:
                messagebox.showerror("Error", f"❌ {msg}")
        except Exception as exc:
            messagebox.showerror("Error", f"Export failed: {exc}")

    def open_folder(self):
        """Open file browser to show converted files."""
        try:
            import subprocess
            import sys

            subprocess.Popen(f'explorer /select,"{Path.home()}"')
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to open folder: {exc}")
```
