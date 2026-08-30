"""PyQt6 desktop interface for doc2md.

Design notes that matter for correctness rather than looks:

* **Paths.** Dropped files arrive as ``QUrl`` objects and are read with
  ``QUrl.toLocalFile()``, which hands back a real Python ``str`` decoded from
  UTF-16. The previous Tk implementation received one flat string and had to
  re-tokenize it, which is where Thai names, spaces and backslash escapes went
  wrong. Nothing in this module parses a path out of text.
* **Threading.** Conversion runs in a ``QThread``; the worker only *emits*
  signals and never touches a widget. Qt queues those signals onto the GUI
  thread, so there is no equivalent of the Tk "call widgets from a worker and
  hope" hazard.
* **Reporting.** Every file ends in exactly one terminal state - Success,
  Skipped or Error - and the error text is shown in the row. A file can never
  silently disappear from the batch.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc2md import __version__
from doc2md.core.converter import Converter
from doc2md.core.router import FileKind, detect
from doc2md.gui import theme

logger = logging.getLogger(__name__)

# Kinds an engine can actually handle. MEDIA is excluded on purpose: audio and
# video are recognized so the user gets a specific "no longer supported"
# message, not routed to a converter that does not exist.
SUPPORTED_KINDS = frozenset(
    kind for kind in FileKind if kind not in (FileKind.UNKNOWN, FileKind.MEDIA)
)

OUTPUT_FORMATS = [("Markdown (.md)", ".md"), ("Plain text (.txt)", ".txt")]
OCR_LANGUAGES = [
    ("Thai + English", "tha+eng"),
    ("Thai only", "tha"),
    ("English only", "eng"),
]

STATUS_QUEUED = "Queued"
STATUS_CONVERTING = "Converting"
STATUS_SUCCESS = "Success"
STATUS_SKIPPED = "Skipped"
STATUS_ERROR = "Error"

_STATUS_KEYS = {
    STATUS_QUEUED: "queued",
    STATUS_CONVERTING: "converting",
    STATUS_SUCCESS: "success",
    STATUS_SKIPPED: "skipped",
    STATUS_ERROR: "error",
}

COLUMN_FILE = 0
COLUMN_KIND = 1
COLUMN_STATUS = 2
COLUMN_DETAIL = 3


def collect_files(paths, *, recurse: bool = True) -> tuple[list[Path], list[tuple[Path, str]]]:
    """Split *paths* into convertible files and rejected ``(path, reason)`` pairs.

    Directories are walked so a user can drop a whole folder. Duplicates are
    removed case-insensitively (the Windows filesystem is case-insensitive, and
    converting the same document twice writes the second result to a ``-1``
    file for no reason).
    """
    accepted: list[Path] = []
    rejected: list[tuple[Path, str]] = []
    seen: set[str] = set()

    def push(path: Path) -> None:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        if key in seen:
            return
        seen.add(key)
        kind = _kind_of(path)
        if kind in SUPPORTED_KINDS:
            accepted.append(path)
        elif kind is FileKind.MEDIA:
            rejected.append((path, "audio/video transcription was removed in 1.1.0"))
        else:
            rejected.append((path, "unsupported file type"))

    for raw in paths:
        path = Path(raw)
        if path.is_file():
            push(path)
        elif path.is_dir() and recurse:
            children = sorted(p for p in path.rglob("*") if p.is_file())
            if not children:
                rejected.append((path, "folder contains no files"))
            for child in children:
                if _kind_of(child) in SUPPORTED_KINDS:
                    push(child)
        else:
            rejected.append((path, "not found"))
    return accepted, rejected


def _kind_of(path: Path) -> FileKind:
    try:
        return detect(path).kind
    except Exception:
        return FileKind.UNKNOWN


class ConversionWorker(QObject):
    """Runs the batch off the GUI thread and reports progress through signals."""

    file_started = pyqtSignal(int, str)
    file_finished = pyqtSignal(int, bool, str, str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, int, bool)

    def __init__(self, files: list[Path], options: dict, timeout: float) -> None:
        super().__init__()
        self._files = list(files)
        self._options = dict(options)
        self._timeout = float(timeout)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        converter = Converter(timeout=self._timeout, options=self._options)
        total = len(self._files)
        succeeded = 0
        failed = 0
        for index, path in enumerate(self._files):
            if self._cancelled:
                break
            self.file_started.emit(index, path.name)
            try:
                result = converter.convert_file(path)
            except Exception as exc:  # pragma: no cover - converter is defensive
                logger.exception("unexpected converter failure for %s", path)
                failed += 1
                self.file_finished.emit(index, False, "", f"{type(exc).__name__}: {exc}")
            else:
                if result.success:
                    succeeded += 1
                    self.file_finished.emit(index, True, result.markdown, "")
                else:
                    failed += 1
                    self.file_finished.emit(index, False, "", result.error or "conversion failed")
            self.progress.emit(index + 1, total)
        self.finished.emit(succeeded, failed, self._cancelled)


class DropZone(QFrame):
    """Drop target for files and folders."""

    files_dropped = pyqtSignal(list)
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setProperty("hover", "false")
        self.setMinimumHeight(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        title = QLabel("Drag & drop documents here")
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel(
            "PDF · DOCX · XLSX · CSV · PPTX · HTML · EML · PNG/JPG · code  —  "
            "folders and multiple files welcome, or click to browse"
        )
        hint.setObjectName("DropHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addStretch(1)

    def _set_hover(self, active: bool) -> None:
        self.setProperty("hover", "true" if active else "false")
        # Property-driven QSS selectors only re-evaluate on an explicit
        # unpolish/polish cycle.
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hover(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._set_hover(False)
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._set_hover(False)
        paths = self.paths_from_urls(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    @staticmethod
    def paths_from_urls(urls) -> list[Path]:
        """Convert dropped ``QUrl``s into local paths, ignoring remote ones."""
        paths: list[Path] = []
        for url in urls:
            if not isinstance(url, QUrl) or not url.isLocalFile():
                continue
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))
        return paths


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("doc2md — Document to Markdown Converter")
        self.resize(1080, 760)
        self.setMinimumSize(880, 620)
        self.setWindowIcon(theme.make_icon("document"))

        self._files: list[Path] = []
        self._items: list[QTreeWidgetItem] = []
        self._markdown: dict[int, str] = {}
        self._results: list = []
        self._thread: QThread | None = None
        self._worker: ConversionWorker | None = None

        self._build_ui()
        self._update_actions()

    # --------------------------------------------------------------- UI setup

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addWidget(self._build_settings_card())

        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_paths)
        self.drop_zone.clicked.connect(self._browse_files)
        root.addWidget(self.drop_zone)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._build_file_list())
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        root.addWidget(self._build_progress())
        root.addLayout(self._build_buttons())

        self.statusBar().showMessage("Ready")

    def _build_header(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("doc2md — Clean Document Converter")
        title.setObjectName("Title")
        subtitle = QLabel(
            f"v{__version__}  ·  PDF · Word · Excel · PowerPoint · HTML · images → Markdown"
        )
        subtitle.setObjectName("Subtitle")
        box.addWidget(title)
        box.addWidget(subtitle)
        return box

    def _build_settings_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        grid = QGridLayout(card)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        grid.addWidget(self._section_label("OUTPUT FOLDER"), 0, 0)
        self.output_edit = QLineEdit(str(Path.home() / "Documents"))
        self.output_edit.setToolTip(
            "Where the .md files are written. Leave the 'next to source' box "
            "ticked to save each result beside its original file instead."
        )
        grid.addWidget(self.output_edit, 1, 0, 1, 2)

        browse = QPushButton("Browse")
        browse.setIcon(theme.make_icon("folder"))
        browse.clicked.connect(self._browse_output_dir)
        grid.addWidget(browse, 1, 2)

        grid.addWidget(self._section_label("FORMAT"), 0, 3)
        self.format_combo = QComboBox()
        for label, _suffix in OUTPUT_FORMATS:
            self.format_combo.addItem(label)
        grid.addWidget(self.format_combo, 1, 3)

        grid.addWidget(self._section_label("OCR LANGUAGE"), 0, 4)
        self.ocr_combo = QComboBox()
        for label, _code in OCR_LANGUAGES:
            self.ocr_combo.addItem(label)
        self.ocr_combo.setToolTip(
            "Language models used for scanned PDFs and images. Requires "
            "Tesseract OCR with the matching language data installed."
        )
        grid.addWidget(self.ocr_combo, 1, 4)

        options = QHBoxLayout()
        self.beside_source_check = QCheckBox("Save next to source file")
        self.beside_source_check.setChecked(True)
        self.beside_source_check.toggled.connect(self._on_beside_source_toggled)
        self.ocr_check = QCheckBox("OCR scanned pages")
        self.ocr_check.setChecked(True)
        self.tables_check = QCheckBox("Extract tables")
        self.tables_check.setChecked(True)
        self.clipboard_check = QCheckBox("Copy result to clipboard")
        for widget in (
            self.beside_source_check,
            self.ocr_check,
            self.tables_check,
            self.clipboard_check,
        ):
            options.addWidget(widget)
        options.addStretch(1)
        grid.addLayout(options, 2, 0, 1, 5)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)
        self._on_beside_source_toggled(True)
        return card

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionLabel")
        return label

    def _build_file_list(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._section_label("FILES"))

        self.file_tree = QTreeWidget()
        self.file_tree.setColumnCount(4)
        self.file_tree.setHeaderLabels(["File", "Type", "Status", "Details"])
        self.file_tree.setRootIsDecorated(False)
        self.file_tree.setAlternatingRowColors(False)
        self.file_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.file_tree.currentItemChanged.connect(self._on_row_selected)
        header = self.file_tree.header()
        header.setSectionResizeMode(COLUMN_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COLUMN_KIND, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COLUMN_DETAIL, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.file_tree)
        return container

    def _build_preview(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._section_label("MARKDOWN PREVIEW"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(
            "Select a converted file to preview its Markdown here."
        )
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.preview)
        return container

    def _build_progress(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("Subtitle")
        layout.addWidget(self.progress_bar, 1)
        layout.addWidget(self.progress_label)
        return container

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.add_button = QPushButton("Add files")
        self.add_button.setIcon(theme.make_icon("add"))
        self.add_button.clicked.connect(self._browse_files)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setIcon(theme.make_icon("clear"))
        self.clear_button.clicked.connect(self.clear_files)

        self.convert_button = QPushButton("Convert")
        self.convert_button.setObjectName("Primary")
        self.convert_button.setIcon(theme.make_icon("convert", color="#04212B"))
        self.convert_button.clicked.connect(self.start_conversion)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("Danger")
        self.cancel_button.setIcon(theme.make_icon("cancel", color=theme.DANGER))
        self.cancel_button.clicked.connect(self.cancel_conversion)

        self.copy_button = QPushButton("Copy Markdown")
        self.copy_button.setIcon(theme.make_icon("copy"))
        self.copy_button.clicked.connect(self.copy_markdown)

        self.bridge_button = QPushButton("Send to Sandbox")
        self.bridge_button.setIcon(theme.make_icon("bridge"))
        self.bridge_button.setToolTip(
            "Write the converted documents plus a manifest.json bundle into a "
            "folder the Mediplex AI Sandbox can ingest."
        )
        self.bridge_button.clicked.connect(self.send_to_bridge)

        row.addWidget(self.add_button)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        row.addWidget(self.copy_button)
        row.addWidget(self.bridge_button)
        row.addWidget(self.cancel_button)
        row.addWidget(self.convert_button)
        return row

    # ----------------------------------------------------------- file intake

    def add_paths(self, paths) -> None:
        """Add dropped or browsed *paths* to the queue."""
        accepted, rejected = collect_files(paths)
        known = {str(p).casefold() for p in self._files}
        added = 0
        for path in accepted:
            if str(path).casefold() in known:
                continue
            known.add(str(path).casefold())
            self._files.append(path)
            self._items.append(self._make_row(path))
            added += 1

        for path, reason in rejected:
            item = QTreeWidgetItem([path.name, "—", STATUS_SKIPPED, reason])
            item.setToolTip(COLUMN_FILE, str(path))
            self._paint_status(item, STATUS_SKIPPED)
            self.file_tree.addTopLevelItem(item)

        if added:
            self.statusBar().showMessage(f"Added {added} file(s) — {len(self._files)} queued")
        elif rejected:
            self.statusBar().showMessage(f"Nothing added — {len(rejected)} file(s) skipped")
        else:
            self.statusBar().showMessage("Nothing added — those files are already queued")
        self._update_actions()

    def _make_row(self, path: Path) -> QTreeWidgetItem:
        item = QTreeWidgetItem([path.name, _kind_of(path).value, STATUS_QUEUED, ""])
        item.setToolTip(COLUMN_FILE, str(path))
        self._paint_status(item, STATUS_QUEUED)
        self.file_tree.addTopLevelItem(item)
        return item

    @staticmethod
    def _paint_status(item: QTreeWidgetItem, status: str) -> None:
        item.setText(COLUMN_STATUS, status)
        key = _STATUS_KEYS.get(status, "queued")
        item.setForeground(COLUMN_STATUS, QColor(theme.STATUS_COLORS[key]))

    def clear_files(self) -> None:
        if self._is_running():
            return
        self._files.clear()
        self._items.clear()
        self._markdown.clear()
        self._results.clear()
        self.file_tree.clear()
        self.preview.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("0 / 0")
        self.statusBar().showMessage("Cleared")
        self._update_actions()

    def _browse_files(self) -> None:
        files, _filter = QFileDialog.getOpenFileNames(
            self,
            "Select documents",
            str(Path.home()),
            "Documents (*.pdf *.docx *.xlsx *.xlsm *.csv *.pptx *.html *.htm *.eml *.json *.txt *.md);;"
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.gif);;"
            "All files (*)",
        )
        if files:
            self.add_paths([Path(f) for f in files])

    def _browse_output_dir(self) -> None:
        current = self.output_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Select output folder", current)
        if chosen:
            self.output_edit.setText(chosen)
            self.beside_source_check.setChecked(False)

    def _on_beside_source_toggled(self, checked: bool) -> None:
        self.output_edit.setEnabled(not checked)

    # ------------------------------------------------------------ conversion

    def conversion_options(self) -> dict:
        return {
            "pdf_ocr_fallback": self.ocr_check.isChecked(),
            "pdf_tables": self.tables_check.isChecked(),
            "ocr_lang": OCR_LANGUAGES[max(self.ocr_combo.currentIndex(), 0)][1],
            "inline_styles": True,
        }

    def output_suffix(self) -> str:
        return OUTPUT_FORMATS[max(self.format_combo.currentIndex(), 0)][1]

    def start_conversion(self) -> None:
        if self._is_running() or not self._files:
            return

        for item in self._items:
            self._paint_status(item, STATUS_QUEUED)
            item.setText(COLUMN_DETAIL, "")
        self._markdown.clear()
        self._results.clear()
        self.preview.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"0 / {len(self._files)}")

        self._thread = QThread(self)
        self._worker = ConversionWorker(self._files, self.conversion_options(), timeout=60.0)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_batch_finished)
        self._thread.start()

        self.statusBar().showMessage(f"Converting {len(self._files)} file(s)…")
        self._update_actions()

    def cancel_conversion(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.statusBar().showMessage("Cancelling after the current file…")

    def _on_file_started(self, index: int, name: str) -> None:
        if 0 <= index < len(self._items):
            self._paint_status(self._items[index], STATUS_CONVERTING)
        self.statusBar().showMessage(f"Converting {name}…")

    def _on_file_finished(self, index: int, ok: bool, markdown: str, error: str) -> None:
        if not (0 <= index < len(self._items)):
            return
        item = self._items[index]
        if ok:
            self._markdown[index] = markdown
            self._paint_status(item, STATUS_SUCCESS)
            written = self._write_output(self._files[index], markdown)
            item.setText(COLUMN_DETAIL, written)
            if self.file_tree.currentItem() is None:
                self.file_tree.setCurrentItem(item)
        else:
            self._paint_status(item, STATUS_ERROR)
            item.setText(COLUMN_DETAIL, error)
            item.setToolTip(COLUMN_DETAIL, error)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_bar.setValue(int(done * 100 / total) if total else 0)
        self.progress_label.setText(f"{done} / {total}")

    def _on_batch_finished(self, succeeded: int, failed: int, cancelled: bool) -> None:
        self._teardown_thread()
        if cancelled:
            message = f"Cancelled — {succeeded} converted, {failed} failed"
        else:
            message = f"Done — {succeeded} converted, {failed} failed"
        self.statusBar().showMessage(message)

        if self.clipboard_check.isChecked() and self._markdown:
            self.copy_markdown(quiet=True)
        self._update_actions()

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    # ---------------------------------------------------------------- output

    def output_path_for(self, source: Path) -> Path:
        suffix = self.output_suffix()
        if self.beside_source_check.isChecked():
            directory = source.parent
        else:
            directory = Path(self.output_edit.text().strip() or source.parent)
        candidate = directory / f"{source.stem}{suffix}"
        counter = 1
        while candidate.exists():
            candidate = directory / f"{source.stem}-{counter}{suffix}"
            counter += 1
        return candidate

    def _write_output(self, source: Path, markdown: str) -> str:
        try:
            destination = self.output_path_for(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(markdown, encoding="utf-8", newline="\n")
        except OSError as exc:
            return f"saved nothing — {exc}"
        return f"saved to {destination}"

    def collected_markdown(self) -> str:
        """Concatenate every successful result in queue order."""
        return "\n\n---\n\n".join(
            self._markdown[index] for index in sorted(self._markdown)
        )

    def copy_markdown(self, *, quiet: bool = False) -> bool:
        payload = self.collected_markdown()
        if not payload.strip():
            if not quiet:
                self._warn("Nothing to copy", "Convert at least one document first.")
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:  # pragma: no cover - headless only
            if not quiet:
                self._warn("Clipboard unavailable", "No clipboard on this display.")
            return False
        clipboard.setText(payload)
        self.statusBar().showMessage(
            f"Copied {len(payload):,} characters from {len(self._markdown)} document(s)"
        )
        return True

    def build_bridge_payload(self):
        """Assemble the payload the integration bridge sends downstream."""
        from doc2md.core.bridge import BridgeDocument, BridgePayload

        documents = [
            BridgeDocument(
                name=self._files[index].stem,
                markdown=markdown,
                source=str(self._files[index]),
                kind=_kind_of(self._files[index]).value,
            )
            for index, markdown in sorted(self._markdown.items())
            if index < len(self._files)
        ]
        return BridgePayload(documents=documents)

    def send_to_bridge(self) -> bool:
        from doc2md.core.bridge import BridgeError, FileDropTransport

        payload = self.build_bridge_payload()
        if not payload.documents:
            self._warn("Nothing to send", "Convert at least one document first.")
            return False

        inbox = QFileDialog.getExistingDirectory(
            self, "Select the sandbox inbox folder", self.output_edit.text().strip() or str(Path.home())
        )
        if not inbox:
            return False
        try:
            message = FileDropTransport(inbox).send(payload)
        except BridgeError as exc:
            self._warn("Export failed", str(exc))
            return False
        self.statusBar().showMessage(message)
        return True

    def _on_row_selected(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            return
        try:
            index = self._items.index(current)
        except ValueError:
            self.preview.setPlainText("")
            return
        self.preview.setPlainText(self._markdown.get(index, ""))

    def _update_actions(self) -> None:
        running = self._is_running()
        has_files = bool(self._files)
        has_output = bool(self._markdown)
        self.convert_button.setEnabled(has_files and not running)
        self.cancel_button.setEnabled(running)
        self.add_button.setEnabled(not running)
        self.clear_button.setEnabled(has_files and not running)
        self.copy_button.setEnabled(has_output and not running)
        self.bridge_button.setEnabled(has_output and not running)

    def _warn(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._is_running():
            answer = QMessageBox.question(
                self,
                "Conversion in progress",
                "A conversion is still running. Cancel it and quit?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.cancel_conversion()
            self._teardown_thread()
        event.accept()


def run_gui(argv=None) -> int:
    """Create the ``QApplication``, show the window, and enter the event loop."""
    import sys

    from PyQt6.QtWidgets import QApplication

    args = list(argv if argv is not None else sys.argv[:1])
    app = QApplication.instance() or QApplication(args)
    app.setApplicationName("doc2md")
    app.setApplicationVersion(__version__)
    app.setStyleSheet(theme.STYLESHEET)

    window = MainWindow()
    window.show()
    return app.exec()
