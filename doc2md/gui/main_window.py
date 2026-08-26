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
from doc2md.core.exporter import export_markdown

logger = logging.getLogger(__name__)

# Soft dark theme colors
CTK_BG = "#1B222C"  # Dark soft slate
CTK_CARD = "#242D3C"  # Card soft slate
CTK_ACCENT_BLUE = "#3B82F6"  # Primary blue
CTK_ACCENT_CYAN = "#06B6D4"  # Cyan accent
CTK_TEXT = "#F1F5F9"  # Soft light text


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
        """Initialize UI components with 2-column soft dark theme."""
        # Root container
        root_frame = ctk.CTkFrame(self.root, fg_color=CTK_BG)
        root_frame.pack(fill="both", expand=True)

        # Header Card
        header_card = ctk.CTkFrame(root_frame, fg_color=CTK_CARD, corner_radius=8)
        header_card.pack(fill="x", padx=10, pady=10)

        title_label = ctk.CTkLabel(
            header_card,
            text="📄 doc2md Converter",
            font=("Arial", 20, "bold"),
            text_color=CTK_TEXT,
        )
        title_label.pack(padx=15, pady=10)

        # Main content frame (2 columns)
        content_frame = ctk.CTkFrame(root_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Left Column: Drop Zone (using pack inside content_frame)
        drop_card = ctk.CTkFrame(
            content_frame, fg_color=CTK_CARD, corner_radius=8, border_width=2, border_color=CTK_ACCENT_CYAN
        )
        drop_card.pack(side="left", fill="both", expand=True, padx=(0, 5))

        self.drop_label = ctk.CTkLabel(
            drop_card,
            text="📁 Drag & Drop Files Here\n(PDF, DOCX, Images, Audio, Video)",
            font=("Arial", 13),
            text_color=CTK_ACCENT_CYAN,
            wraplength=350,
        )
        self.drop_label.pack(fill="both", expand=True, padx=30, pady=30)
        self.drop_card = drop_card

        # Right Column: Options & Analytics
        right_frame = ctk.CTkScrollableFrame(content_frame, fg_color="transparent")
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))

        # Options Card
        options_card = ctk.CTkFrame(right_frame, fg_color=CTK_CARD, corner_radius=8)
        options_card.pack(fill="x", pady=(0, 10))
        options_card.grid_columnconfigure(1, weight=1)

        options_label = ctk.CTkLabel(
            options_card, text="⚙️ Options", font=("Arial", 13, "bold"), text_color=CTK_TEXT
        )
        options_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 10))

        self.copy_var = ctk.BooleanVar(value=True)
        copy_check = ctk.CTkCheckBox(
            options_card,
            text="Auto-copy to clipboard",
            variable=self.copy_var,
            text_color=CTK_TEXT,
            fg_color=CTK_ACCENT_BLUE,
        )
        copy_check.grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=3)

        self.stats_var = ctk.BooleanVar(value=True)
        stats_check = ctk.CTkCheckBox(
            options_card,
            text="Show token stats",
            variable=self.stats_var,
            text_color=CTK_TEXT,
            fg_color=CTK_ACCENT_BLUE,
        )
        stats_check.grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=3)

        self.ocr_var = ctk.BooleanVar(value=True)
        ocr_check = ctk.CTkCheckBox(
            options_card,
            text="Enable OCR",
            variable=self.ocr_var,
            text_color=CTK_TEXT,
            fg_color=CTK_ACCENT_BLUE,
        )
        ocr_check.grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=3)

        model_label = ctk.CTkLabel(
            options_card, text="Audio Model:", text_color=CTK_TEXT, font=("Arial", 11)
        )
        model_label.grid(row=4, column=0, sticky="w", padx=12, pady=(10, 3))

        self.model_var = ctk.StringVar(value="small")
        model_combo = ctk.CTkComboBox(
            options_card,
            values=["tiny", "base", "small", "medium", "large-v3"],
            variable=self.model_var,
            fg_color=CTK_ACCENT_BLUE,
            button_color=CTK_ACCENT_BLUE,
            text_color="white",
            width=120,
        )
        model_combo.grid(row=4, column=1, sticky="e", padx=12, pady=(10, 3))

        # Analytics Card
        analytics_card = ctk.CTkFrame(right_frame, fg_color=CTK_CARD, corner_radius=8)
        analytics_card.pack(fill="x", pady=(0, 10))

        analytics_label = ctk.CTkLabel(
            analytics_card, text="📊 Analytics", font=("Arial", 13, "bold"), text_color=CTK_TEXT
        )
        analytics_label.pack(anchor="w", padx=12, pady=(8, 5))

        self.analytics_text = ctk.CTkLabel(
            analytics_card, text="No conversion yet", font=("Arial", 10), text_color="#9CA3AF"
        )
        self.analytics_text.pack(anchor="w", padx=12, pady=(0, 8))

        # Progress Card with Overlay
        progress_card = ctk.CTkFrame(root_frame, fg_color=CTK_CARD, corner_radius=8)
        progress_card.pack(fill="x", padx=10, pady=(0, 10))
        progress_card.grid_columnconfigure(0, weight=1)

        self.progress_var = ctk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(
            progress_card,
            variable=self.progress_var,
            fg_color=CTK_BG,
            progress_color=CTK_ACCENT_BLUE,
            height=28,
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=12, pady=10)

        self.progress_overlay = ctk.CTkLabel(
            progress_card, text="0%", font=("Arial", 10, "bold"), text_color="white"
        )
        self.progress_overlay.place(relx=0.5, rely=0.5, anchor="center")

        self.status_label = ctk.CTkLabel(
            progress_card, text="Ready", text_color=CTK_ACCENT_CYAN, font=("Arial", 10)
        )
        self.status_label.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))

        # Bottom Action Panel
        button_frame = ctk.CTkFrame(root_frame, fg_color="transparent")
        button_frame.pack(fill="x", padx=10, pady=(0, 10))
        button_frame.grid_columnconfigure(0, weight=1)

        browse_btn = ctk.CTkButton(
            button_frame,
            text="📂 Browse Files",
            command=self.browse_files,
            fg_color=CTK_ACCENT_BLUE,
            hover_color="#2563EB",
            text_color="white",
            font=("Arial", 11, "bold"),
        )
        browse_btn.pack(side="left", padx=3)

        copy_btn = ctk.CTkButton(
            button_frame,
            text="📋 Copy Result",
            command=self.copy_result,
            fg_color=CTK_ACCENT_BLUE,
            hover_color="#2563EB",
            text_color="white",
            font=("Arial", 11, "bold"),
        )
        copy_btn.pack(side="left", padx=3)

        save_btn = ctk.CTkButton(
            button_frame,
            text="💾 Save As...",
            command=self.save_result,
            fg_color=CTK_ACCENT_CYAN,
            hover_color="#0891B2",
            text_color="black",
            font=("Arial", 11, "bold"),
        )
        save_btn.pack(side="left", padx=3)

        folder_btn = ctk.CTkButton(
            button_frame,
            text="🗂️ Open Folder",
            command=self.open_folder,
            fg_color=CTK_ACCENT_BLUE,
            hover_color="#2563EB",
            text_color="white",
            font=("Arial", 11, "bold"),
        )
        folder_btn.pack(side="left", padx=3)

        exit_btn = ctk.CTkButton(
            button_frame,
            text="❌ Exit",
            command=self.root.quit,
            fg_color="#DC2626",
            hover_color="#B91C1C",
            text_color="white",
            font=("Arial", 11, "bold"),
        )
        exit_btn.pack(side="right", padx=3)

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
            self.status_label.configure(text=f"Converting {total} file(s)...", text_color=CTK_ACCENT_CYAN)
            self.root.update()

            results = []
            for i, file_path in enumerate(files):
                progress = ((i + 1) / total) * 100
                self.progress_var.set(progress / 100)
                self.progress_overlay.configure(text=f"{int(progress)}%")
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

            self.progress_var.set(1.0)
            self.progress_overlay.configure(text="100%")

            if results:
                self.last_result = "\n\n---\n\n".join(results)
                self.status_label.configure(
                    text=f"✅ Success: {len(results)} file(s) converted", text_color="#10B981"
                )
                self.analytics_text.configure(text=f"Files: {len(results)} | Ready to export")
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
