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
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QGuiApplication, QPixmap
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
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from doc2md import __version__
from doc2md.core.converter import ConversionResult, Converter
from doc2md.core.presets import CUSTOM, PRESET_NAMES, matching_preset, options_for
from doc2md.core.quality import build_report, write_report_atomic
from doc2md.core.router import RECURSIVE_SCAN_EXCLUDED_SUFFIXES, FileKind, detect
from doc2md.gui import theme
from doc2md.gui.ocr_dialog import OcrDiagnosticsDialog

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
STATUS_WARNING = "Warning"

_STATUS_KEYS = {
    STATUS_QUEUED: "queued",
    STATUS_CONVERTING: "converting",
    STATUS_SUCCESS: "success",
    STATUS_SKIPPED: "skipped",
    STATUS_ERROR: "error",
    STATUS_WARNING: "warning",
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

    A recursive folder walk excludes ``.md`` files: a dropped folder that
    already contains generated Markdown - this tool's own previous output -
    would otherwise be re-ingested as input on the next drop, and the
    destination collision resolver keeps appending another ``-1``,
    producing an unbounded ``file-1-1-1-...-1.md`` chain. Dropping a ``.md``
    file directly (not via a folder) still works.

    A folder whose ONLY files are the excluded ``.md`` ones is reported with
    the real reason ("these were skipped, not none exist") rather than the
    generic "folder is empty" - and any recursive scan that skips at least
    one ``.md`` file (even alongside real convertible files) says how many,
    so the count is visible instead of silently dropped.
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
            all_children = sorted(p for p in path.rglob("*") if p.is_file())
            md_skipped: list[Path] = []
            children: list[Path] = []
            for child in all_children:
                if child.suffix.lower() in RECURSIVE_SCAN_EXCLUDED_SUFFIXES:
                    md_skipped.append(child)
                else:
                    children.append(child)

            if not all_children:
                rejected.append((path, "folder is empty"))
            elif not children:
                rejected.append((
                    path,
                    f"folder contains only Markdown file(s) - {len(md_skipped)} "
                    "skipped (already-converted output is not re-ingested)",
                ))
            else:
                if md_skipped:
                    rejected.append((
                        path,
                        f"{len(md_skipped)} Markdown file(s) in this folder were "
                        "skipped (already-converted output is not re-ingested)",
                    ))
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


def _human_size(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "unknown"
    from doc2md.core.stats import human_size

    return human_size(num_bytes)


def _format_rows_detected(quality) -> str | None:
    """``"{count}"`` when the count is exact, ``"{count}+"`` when it is only
    a lower bound (``rows_detected_is_exact is False``) - never presents a
    lower bound as if it were the real row count."""
    if quality.rows_detected is None:
        return None
    suffix = "+" if quality.rows_detected_is_exact is False else ""
    return f"{quality.rows_detected:,}{suffix}"


class ScanWorker(QObject):
    """Walks dropped folders off the GUI thread so a huge tree cannot freeze it."""

    done = pyqtSignal(list, list)

    def __init__(self, paths: list[Path]) -> None:
        super().__init__()
        self._paths = paths

    def run(self) -> None:
        try:
            accepted, rejected = collect_files(self._paths)
        except Exception:  # pragma: no cover - collect_files is defensive
            logger.exception("folder scan failed")
            accepted = []
            rejected = [(path, "could not be scanned") for path in self._paths]
        self.done.emit(accepted, rejected)


# Scan threads whose window closed mid-scan: kept referenced until they finish,
# because destroying a running QThread aborts the process.
_ORPHANED_SCANS: list[tuple[QThread, ScanWorker]] = []


class ConversionWorker(QObject):
    """Runs the batch off the GUI thread and reports progress through signals."""

    file_started = pyqtSignal(int, str)
    # (index, ok, markdown, error, warning, result) - `result` is the full
    # ConversionResult (carrying `.quality`) on a normal outcome, None on an
    # unexpected exception the converter itself did not package.
    file_finished = pyqtSignal(int, bool, str, str, str, object)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, int, bool)

    def __init__(
        self, files: "list[Path] | dict[int, Path]", options: dict, timeout: float
    ) -> None:
        super().__init__()
        # A plain list is enumerated from 0 (the whole-batch case); a dict
        # lets a caller (retry) name the ORIGINAL row index for each file so
        # file_finished updates that exact row instead of a fresh one.
        self._files: dict[int, Path] = (
            dict(files) if isinstance(files, dict) else dict(enumerate(files))
        )
        self._options = dict(options)
        self._timeout = float(timeout)
        self._cancelled = False
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancelled = True
        self._cancel_event.set()

    def run(self) -> None:
        converter = Converter(
            timeout=self._timeout, options=self._options, cancel_event=self._cancel_event
        )
        total = len(self._files)
        succeeded = 0
        failed = 0
        for position, (index, path) in enumerate(self._files.items()):
            if self._cancelled:
                break
            self.file_started.emit(index, path.name)
            try:
                result = converter.convert_file(path)
            except Exception as exc:  # pragma: no cover - converter is defensive
                logger.exception("unexpected converter failure for %s", path)
                failed += 1
                self.file_finished.emit(
                    index, False, "", f"{type(exc).__name__}: {exc}", "", None
                )
            else:
                if result.success:
                    succeeded += 1
                    self.file_finished.emit(
                        index, True, result.markdown, "", result.warning or "", result
                    )
                else:
                    failed += 1
                    error = "Cancelled" if self._cancelled else (result.error or "conversion failed")
                    self.file_finished.emit(index, False, "", error, "", result)
            self.progress.emit(position + 1, total)
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

    def __init__(self, parent: QWidget | None = None, *, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("doc2md — Document to Markdown Converter")
        self.resize(1080, 760)
        self.setMinimumSize(880, 620)
        self.setWindowIcon(theme.make_icon("document"))
        self.setAcceptDrops(True)

        # Injectable so tests can supply an isolated (e.g. temp-file-backed)
        # QSettings instead of touching the real user profile / registry.
        self._settings = settings if settings is not None else QSettings(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, "doc2md", "doc2md"
        )

        self._files: list[Path] = []
        self._items: list[QTreeWidgetItem] = []
        self._markdown: dict[int, str] = {}
        self._results: dict[int, object] = {}
        self._output_paths: dict[int, Path] = {}
        self._warnings = 0
        self._thread: QThread | None = None
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None
        self._scan_queue: list[list[Path]] = []
        self._worker: ConversionWorker | None = None
        self._close_after_cancel = False
        self._ocr_dpi = 300
        self._syncing_preset = False
        self._current_index: int | None = None

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

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_file_list())
        splitter.addWidget(self._build_preview())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        root.addWidget(splitter, 1)

        root.addWidget(self._build_progress())
        root.addLayout(self._build_recovery_buttons())
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
            "Default folder for exporting converted results."
        )
        self.output_edit.textChanged.connect(self._on_output_edit_changed)
        grid.addWidget(self.output_edit, 1, 0, 1, 2)

        browse = QPushButton("Browse")
        browse.setIcon(theme.make_icon("folder"))
        browse.clicked.connect(self._browse_output_dir)
        grid.addWidget(browse, 1, 2)

        grid.addWidget(self._section_label("FORMAT"), 0, 3)
        self.format_combo = QComboBox()
        for label, _suffix in OUTPUT_FORMATS:
            self.format_combo.addItem(label)
        self.format_combo.currentIndexChanged.connect(lambda _i: self._refresh_destination_previews())
        grid.addWidget(self.format_combo, 1, 3)

        grid.addWidget(self._section_label("OCR LANGUAGE"), 0, 4)
        self.ocr_combo = QComboBox()
        for label, _code in OCR_LANGUAGES:
            self.ocr_combo.addItem(label)
        self.ocr_combo.setToolTip(
            "Language models used for scanned PDFs and images. Requires "
            "Tesseract OCR with the matching language data installed."
        )
        self.ocr_combo.currentIndexChanged.connect(self._on_ocr_setting_changed)
        grid.addWidget(self.ocr_combo, 1, 4)

        options = QHBoxLayout()
        self.ocr_check = QCheckBox("OCR scanned pages")
        self.ocr_check.setChecked(True)
        self.ocr_check.toggled.connect(self._on_ocr_setting_changed)
        self.tables_check = QCheckBox("Extract tables")
        self.tables_check.setChecked(True)
        self.tables_check.toggled.connect(self._on_ocr_setting_changed)
        self.hidden_sheets_check = QCheckBox("Hidden sheets")
        self.hidden_sheets_check.setToolTip(
            "Also convert worksheets that are hidden in the Excel file"
        )
        for widget in (
            self.ocr_check,
            self.tables_check,
        ):
            options.addWidget(widget)
        options.addStretch(1)

        # Told before any conversion starts, not discovered only after a scan
        # comes back as metadata-only: the user should never wonder why a
        # scanned document produced no text.
        self.ocr_backend_label = QLabel()
        self.ocr_backend_label.setObjectName("Muted")
        self._refresh_ocr_backend_status()
        options.addWidget(self.ocr_backend_label)

        grid.addLayout(options, 2, 0, 1, 6)

        grid.addWidget(self._section_label("PRESET"), 3, 0)
        self.preset_combo = QComboBox()
        for name in PRESET_NAMES:
            self.preset_combo.addItem(name)
        self.preset_combo.setToolTip(
            "A named bundle of OCR language / resolution / table-extraction "
            "settings. Changing any of those settings by hand switches this "
            "back to Custom automatically."
        )
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        grid.addWidget(self.preset_combo, 4, 0, 1, 2)
        grid.addWidget(self.hidden_sheets_check, 4, 2, 1, 2)

        self.ocr_diagnostics_button = QPushButton("OCR Diagnostics…")
        self.ocr_diagnostics_button.setIcon(theme.make_icon("document"))
        self.ocr_diagnostics_button.setToolTip(
            "Check whether Tesseract / RapidOCR are actually installed and "
            "ready - not just importable."
        )
        self.ocr_diagnostics_button.clicked.connect(self.show_ocr_diagnostics)
        grid.addWidget(self.ocr_diagnostics_button, 4, 4, 1, 2)

        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 1)
        self._sync_preset_combo()
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

        # Same panel does double duty: the empty state IS the drop target
        # (drag & drop or click to browse), and swaps for the tree the
        # moment there is anything to show - no separate drop zone box
        # above it competing for space.
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.add_paths)
        self.drop_zone.clicked.connect(self._browse_files)

        self.file_list_stack = QStackedWidget()
        self.file_list_stack.addWidget(self.drop_zone)
        self.file_list_stack.addWidget(self.file_tree)
        layout.addWidget(self.file_list_stack)
        return container

    def _build_preview(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._section_label("MARKDOWN PREVIEW"))

        # Single toolbar row: badge + quality metrics + action buttons
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.quality_badge = QLabel("")
        self.quality_badge.setObjectName("QualityBadge")
        self.quality_badge.hide()
        self.quality_detail = QLabel("Select a converted file to see its quality summary.")
        self.quality_detail.setObjectName("Muted")
        self.quality_detail.setWordWrap(False)
        toolbar.addWidget(self.quality_badge)
        toolbar.addWidget(self.quality_detail, 1)

        self.open_original_button = QPushButton("Open Original")
        self.open_original_button.clicked.connect(self.open_original)
        self.row_copy_button = QPushButton("Copy Selected")
        self.row_copy_button.setToolTip("Copy this file's Markdown to clipboard.")
        self.row_copy_button.clicked.connect(self.copy_selected_markdown)
        for button in (self.open_original_button, self.row_copy_button):
            button.setEnabled(False)
            toolbar.addWidget(button)
        layout.addLayout(toolbar)

        self.warning_banner = QLabel("")
        self.warning_banner.setObjectName("WarningBanner")
        self.warning_banner.setWordWrap(True)
        self.warning_banner.hide()
        layout.addWidget(self.warning_banner)

        # Thumbnail widget kept for internal logic but never shown in layout
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("Thumbnail")
        self.thumbnail_label.setFixedSize(140, 140)
        self.thumbnail_label.hide()

        # Last widget in the layout, same as file_tree is in its own column,
        # so both boxes' bottom edges land flush with each other - no dead
        # space left over below either one.
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(
            "Select a converted file to preview its Markdown here."
        )
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # Text edits accept drops by default, and a read-only one refuses them
        # without letting the window see the drag; opt out so it bubbles up.
        self.preview.setAcceptDrops(False)
        self.preview.viewport().setAcceptDrops(False)
        layout.addWidget(self.preview, 1)

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

    def _build_recovery_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.retry_failed_button = QPushButton("Retry Failed")
        self.retry_failed_button.setIcon(theme.make_icon("convert"))
        self.retry_failed_button.clicked.connect(self.retry_failed)

        self.retry_warnings_button = QPushButton("Retry Warnings")
        self.retry_warnings_button.setIcon(theme.make_icon("convert"))
        self.retry_warnings_button.clicked.connect(self.retry_warnings)

        self.clear_completed_button = QPushButton("Clear Completed")
        self.clear_completed_button.setIcon(theme.make_icon("clear"))
        self.clear_completed_button.clicked.connect(self.clear_completed)

        self.export_error_report_button = QPushButton("Export Error Report")
        self.export_error_report_button.setIcon(theme.make_icon("document"))
        self.export_error_report_button.clicked.connect(self.export_error_report)

        row.addWidget(self.retry_failed_button)
        row.addWidget(self.retry_warnings_button)
        row.addWidget(self.clear_completed_button)
        row.addStretch(1)
        row.addWidget(self.export_error_report_button)
        return row

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

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

        self.export_report_button = QPushButton("Export…")
        self.export_report_button.setIcon(theme.make_icon("document"))
        self.export_report_button.setToolTip(
            "Save converted results as Markdown (.md), plain text (.txt), "
            "or a JSON quality report."
        )
        self.export_report_button.clicked.connect(self.export_content)

        row.addWidget(self.clear_button)
        row.addStretch(1)
        row.addWidget(self.copy_button)
        row.addWidget(self.export_report_button)
        row.addWidget(self.cancel_button)
        row.addWidget(self.convert_button)
        return row

    # ----------------------------------------------------------- file intake

    def add_paths(self, paths) -> None:
        """Add dropped or browsed *paths* to the queue.

        Folders are walked on a background thread; plain files are added
        immediately.
        """
        paths = [Path(p) for p in paths]
        if any(p.is_dir() for p in paths):
            self._scan_queue.append(paths)
            if self._scan_thread is None:
                self._start_next_scan()
            return
        self._apply_scan(*collect_files(paths))

    def _start_next_scan(self) -> None:
        thread = QThread()
        worker = ScanWorker(self._scan_queue.pop(0))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_scan_done)
        self._scan_thread, self._scan_worker = thread, worker
        self.statusBar().showMessage("Scanning folder…")
        thread.start()

    def _on_scan_done(self, accepted: list, rejected: list) -> None:
        thread, worker = self._scan_thread, self._scan_worker
        self._scan_thread = self._scan_worker = None
        if thread is not None:
            thread.quit()
            thread.wait()
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
        self._apply_scan(accepted, rejected)
        if self._scan_queue:
            self._start_next_scan()

    def _apply_scan(self, accepted: list, rejected: list) -> None:
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
        self._output_paths.clear()
        self._warnings = 0
        self.file_tree.clear()
        self._reset_preview_panel()
        self.progress_bar.setValue(0)
        self.progress_label.setText("0 / 0")
        self.statusBar().showMessage("Cleared")
        self._update_actions()

    def clear_completed(self) -> None:
        """Remove rows that finished cleanly (Success) from the list.

        Warning and Error rows stay visible - they are exactly what Retry
        Failed / Retry Warnings act on, so clearing them here would remove
        the user's ability to retry them from this same list.
        """
        if self._is_running():
            return
        remove_positions = [
            i for i, item in enumerate(self._items) if item.text(COLUMN_STATUS) == STATUS_SUCCESS
        ]
        if not remove_positions:
            self.statusBar().showMessage("Nothing to clear")
            return

        keep_positions = [i for i in range(len(self._items)) if i not in set(remove_positions)]
        for pos in sorted(remove_positions, reverse=True):
            self.file_tree.takeTopLevelItem(pos)

        self._files = [self._files[i] for i in keep_positions]
        self._items = [self._items[i] for i in keep_positions]
        self._markdown = {
            new_i: self._markdown[old_i]
            for new_i, old_i in enumerate(keep_positions)
            if old_i in self._markdown
        }
        self._results = {
            new_i: self._results[old_i]
            for new_i, old_i in enumerate(keep_positions)
            if old_i in self._results
        }
        self._output_paths = {
            new_i: self._output_paths[old_i]
            for new_i, old_i in enumerate(keep_positions)
            if old_i in self._output_paths
        }

        self._reset_preview_panel()
        self.statusBar().showMessage(f"Cleared {len(remove_positions)} completed file(s)")
        self._update_actions()

    def _browse_files(self) -> None:
        files, _filter = QFileDialog.getOpenFileNames(
            self,
            "Select documents",
            str(Path.home()),
            "Documents (*.pdf *.docx *.doc *.xlsx *.xlsm *.xls *.csv *.pptx *.ppt *.html *.htm *.eml *.json *.txt *.md);;"
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

    def _on_output_edit_changed(self, _text: str) -> None:
        pass

    def _refresh_destination_previews(self) -> None:
        pass

    # ------------------------------------------------------------ conversion

    @staticmethod
    def _ocr_backend_status() -> tuple[bool, str]:
        """Check Tesseract/RapidOCR availability up front.

        Returns ``(available, message)`` so the caller can decide how to
        present it. Checked before any conversion runs, not discovered only
        after a scanned document comes back as metadata-only.
        """
        from doc2md.core.ocr_setup import find_tesseract

        if find_tesseract() is not None:
            return True, "Tesseract ready"
        try:
            import rapidocr_onnxruntime  # noqa: F401

            return True, "RapidOCR ready"
        except ImportError:
            return False, "OCR unavailable - click OCR Diagnostics to install it"

    def _refresh_ocr_backend_status(self) -> None:
        available, message = self._ocr_backend_status()
        prefix = "✓" if available else "⚠"
        self.ocr_backend_label.setText(f"{prefix} {message}")
        self.ocr_backend_label.setToolTip(
            message if available else
            "Scanned PDFs and images will convert to metadata only, marked "
            "Warning, until OCR is installed. OCR Diagnostics can install "
            "Tesseract with Thai language data for you."
        )

    def conversion_options(self) -> dict:
        return {
            **self._current_preset_options(),
            "inline_styles": True,
            "include_hidden_sheets": self.hidden_sheets_check.isChecked(),
        }

    def output_suffix(self) -> str:
        return OUTPUT_FORMATS[max(self.format_combo.currentIndex(), 0)][1]

    # ------------------------------------------------------------- presets

    def _current_preset_options(self) -> dict:
        return {
            "pdf_ocr_fallback": self.ocr_check.isChecked(),
            "pdf_tables": self.tables_check.isChecked(),
            "ocr_lang": OCR_LANGUAGES[max(self.ocr_combo.currentIndex(), 0)][1],
            "ocr_dpi": self._ocr_dpi,
        }

    @staticmethod
    def _ocr_lang_index(value: str) -> int:
        for i, (_label, code) in enumerate(OCR_LANGUAGES):
            if code == value:
                return i
        return 0

    def _on_ocr_setting_changed(self, *_args) -> None:
        if self._syncing_preset:
            return
        self._sync_preset_combo()

    def _sync_preset_combo(self) -> None:
        name = matching_preset(self._current_preset_options())
        self._syncing_preset = True
        try:
            self.preset_combo.setCurrentIndex(PRESET_NAMES.index(name))
        finally:
            self._syncing_preset = False

    def _on_preset_selected(self, _index: int) -> None:
        if self._syncing_preset:
            return
        name = self.preset_combo.currentText()
        if name == CUSTOM:
            return  # Custom has no fixed values to apply - it just means
            # "whatever is currently set", which is already the case.
        values = options_for(name)
        self._syncing_preset = True
        try:
            self.ocr_combo.setCurrentIndex(self._ocr_lang_index(values["ocr_lang"]))
            self.tables_check.setChecked(values["pdf_tables"])
            self.ocr_check.setChecked(values["pdf_ocr_fallback"])
            self._ocr_dpi = values["ocr_dpi"]
        finally:
            self._syncing_preset = False

    # --------------------------------------------------------- diagnostics

    def show_ocr_diagnostics(self) -> None:
        dialog = OcrDiagnosticsDialog(self)
        dialog.exec()
        self._refresh_ocr_backend_status()

    def start_conversion(self) -> None:
        if self._is_running() or not self._files:
            return

        for item in self._items:
            self._paint_status(item, STATUS_QUEUED)
            item.setText(COLUMN_DETAIL, "")
        self._markdown.clear()
        self._results.clear()
        self._output_paths.clear()
        self._reset_preview_panel()
        self._run_conversion(dict(enumerate(self._files)))

    def retry_failed(self) -> None:
        self._retry_by_status(STATUS_ERROR)

    def retry_warnings(self) -> None:
        self._retry_by_status(STATUS_WARNING)

    def _retry_by_status(self, status: str) -> None:
        if self._is_running():
            return
        indices = [
            i for i, item in enumerate(self._items) if item.text(COLUMN_STATUS) == status
        ]
        if not indices:
            self.statusBar().showMessage(f"Nothing to retry ({status.lower()})")
            return
        files_by_index = {i: self._files[i] for i in indices}
        for i in indices:
            # A retry must never leave a stale prior-round result reachable
            # to Copy Markdown / Send to Sandbox / Export Report while the
            # new attempt is in flight - and if this attempt fails outright,
            # it must stay gone rather than silently keep the old content.
            self._markdown.pop(i, None)
            self._results.pop(i, None)
            self._output_paths.pop(i, None)
            self._paint_status(self._items[i], STATUS_QUEUED)
            self._items[i].setText(COLUMN_DETAIL, "")
        self._reset_preview_panel()
        self._run_conversion(files_by_index)

    def _run_conversion(self, files_by_index: dict) -> None:
        """Shared worker/thread setup for a full batch or a retry subset.

        `files_by_index` maps ORIGINAL row index -> path, so file_finished
        always updates the same row a file already occupies - a retry never
        creates a new row, whether it ends in Success or Error again.
        """
        self._warnings = 0
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"0 / {len(files_by_index)}")

        self._thread = QThread(self)
        self._worker = ConversionWorker(files_by_index, self.conversion_options(), timeout=60.0)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.file_started.connect(self._on_file_started)
        self._worker.file_finished.connect(self._on_file_finished)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_batch_finished)
        self._thread.start()

        self.statusBar().showMessage(f"Converting {len(files_by_index)} file(s)…")
        self._update_actions()

    def cancel_conversion(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.statusBar().showMessage("Cancelling…")

    def _on_file_started(self, index: int, name: str) -> None:
        if 0 <= index < len(self._items):
            self._paint_status(self._items[index], STATUS_CONVERTING)
        self.statusBar().showMessage(f"Converting {name}…")

    def _on_file_finished(
        self, index: int, ok: bool, markdown: str, error: str, warning: str, result
    ) -> None:
        if not (0 <= index < len(self._items)):
            return
        item = self._items[index]
        if result is not None:
            self._results[index] = result
        if ok:
            self._markdown[index] = markdown
            if warning:
                self._warnings += 1
                self._paint_status(item, STATUS_WARNING)
                item.setText(COLUMN_DETAIL, warning)
                item.setToolTip(COLUMN_DETAIL, warning)
            else:
                self._paint_status(item, STATUS_SUCCESS)
                item.setText(COLUMN_DETAIL, "")
            if self.file_tree.currentItem() is None:
                self.file_tree.setCurrentItem(item)
        else:
            self._paint_status(item, STATUS_ERROR)
            item.setText(COLUMN_DETAIL, error)
            item.setToolTip(COLUMN_DETAIL, error)

        if self._items[index] is self.file_tree.currentItem():
            # Full refresh, not just the quality badge: a row selected while
            # still Queued/Converting shows an empty preview (no markdown
            # exists yet) - once it finishes, the preview must catch up too,
            # not just the quality summary.
            self._on_row_selected(self._items[index], None)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_bar.setValue(int(done * 100 / total) if total else 0)
        self.progress_label.setText(f"{done} / {total}")

    def _on_batch_finished(self, succeeded: int, failed: int, cancelled: bool) -> None:
        self._teardown_thread()
        warn_note = f", {self._warnings} with warnings" if self._warnings else ""
        verb = "Cancelled" if cancelled else "Done"
        message = f"{verb} — {succeeded} converted{warn_note}, {failed} failed"
        self.statusBar().showMessage(message)
        self._update_actions()

        if self._close_after_cancel:
            # run() has now genuinely returned and the thread/worker are
            # cleaned up; safe to finish the close the user asked for
            # in closeEvent().
            self._close_after_cancel = False
            self.close()

    def _teardown_thread(self) -> None:
        """Release the worker thread - called only after its `finished`
        signal has fired, i.e. after `ConversionWorker.run()` has already
        returned. `wait()` here is therefore just joining an already-stopped
        event loop, never a blocking wait on work that might still be
        running - deleting a QThread/worker while run() is still executing
        would let an in-flight signal emit into (or a slot run on) an object
        being destroyed.
        """
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    # ---------------------------------------------------------------- output

    def output_directory_for(self, source: Path) -> Path:
        return Path(self.output_edit.text().strip() or source.parent)

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

    def build_quality_report(self) -> list[dict]:
        """One report entry per row that has actually finished, in queue order."""
        entries: list[dict] = []
        for index in sorted(self._results):
            if index >= len(self._files):
                continue
            result = self._results[index]
            entries.append(
                build_report(result, output_path=self._output_paths.get(index))
            )
        return entries

    def export_content(self) -> bool:
        if not self._markdown and not self._results:
            self._warn("Nothing to export", "Convert at least one document first.")
            return False

        default_dir = self.output_edit.text().strip() or str(Path.home())
        path_str, _filter = QFileDialog.getSaveFileName(
            self,
            "Export",
            str(Path(default_dir) / "output.md"),
            "Markdown (*.md);;Plain text (*.txt);;JSON quality report (*.json)",
        )
        if not path_str:
            return False

        chosen = Path(path_str)
        suffix = chosen.suffix.lower()

        if suffix == ".json":
            entries = self.build_quality_report()
            if not entries:
                self._warn("Nothing to export", "Convert at least one document first.")
                return False
            try:
                write_report_atomic(entries, chosen)
            except OSError as exc:
                self._warn("Export failed", f"Could not write the report: {exc}")
                return False
        else:
            if not self._markdown:
                self._warn("Nothing to export", "Convert at least one document first.")
                return False
            try:
                chosen.write_text(self.collected_markdown(), encoding="utf-8")
            except OSError as exc:
                self._warn("Export failed", f"Could not write the file: {exc}")
                return False
        self.statusBar().showMessage(f"Exported to {path_str}")
        return True

    def build_error_report(self) -> list[dict]:
        """One report entry per row currently showing Error, in queue order.

        Falls back to a bare ``ConversionResult`` built from the row's own
        detail text for a row that never produced one (the worker's
        unexpected-exception path emits ``result=None``), so an error report
        always covers every Error row, not just the ones with a stored result.
        """
        entries: list[dict] = []
        for index, item in enumerate(self._items):
            if item.text(COLUMN_STATUS) != STATUS_ERROR:
                continue
            result = self._results.get(index)
            if result is None:
                result = ConversionResult(
                    source=self._files[index],
                    success=False,
                    error=item.text(COLUMN_DETAIL),
                )
            entries.append(build_report(result, output_path=self._output_paths.get(index)))
        return entries

    def export_error_report(self) -> bool:
        entries = self.build_error_report()
        if not entries:
            self._warn("Nothing to export", "There are no failed files right now.")
            return False

        default_name = str(
            Path(self.output_edit.text().strip() or str(Path.home())) / "error-report.json"
        )
        path_str, _filter = QFileDialog.getSaveFileName(
            self, "Export error report", default_name, "JSON (*.json)"
        )
        if not path_str:
            return False
        try:
            write_report_atomic(entries, Path(path_str))
        except OSError as exc:
            self._warn("Export failed", f"Could not write the report: {exc}")
            return False
        self.statusBar().showMessage(f"Error report written to {path_str}")
        return True

    def _on_row_selected(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            return
        try:
            index = self._items.index(current)
        except ValueError:
            index = None

        self._current_index = index
        self.preview.setPlainText(self._markdown.get(index, "") if index is not None else "")
        self._show_quality_summary(index)
        self._update_warning_banner(index)
        self._update_row_actions(index)
        self._update_thumbnail(index)

    def _reset_preview_panel(self) -> None:
        self._current_index = None
        self.preview.clear()
        self._show_quality_summary(None)
        self._update_warning_banner(None)
        self._update_row_actions(None)
        self._update_thumbnail(None)

    # ------------------------------------------------------- review extras

    def _update_warning_banner(self, index: int | None) -> None:
        if index is None or not (0 <= index < len(self._items)):
            self.warning_banner.hide()
            return
        item = self._items[index]
        if item.text(COLUMN_STATUS) != STATUS_WARNING:
            self.warning_banner.hide()
            return
        detail = item.text(COLUMN_DETAIL)
        self.warning_banner.setText(
            f"⚠ This is not a full read of the document. {detail}" if detail
            else "⚠ This is not a full read of the document."
        )
        self.warning_banner.show()

    def _update_row_actions(self, index: int | None) -> None:
        has_source = index is not None and 0 <= index < len(self._files)
        has_markdown = has_source and bool(self._markdown.get(index))
        self.open_original_button.setEnabled(has_source)
        self.row_copy_button.setEnabled(has_markdown)

    def open_original(self) -> None:
        index = self._current_index
        if index is None or not (0 <= index < len(self._files)):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._files[index])))

    def copy_selected_markdown(self) -> bool:
        index = self._current_index
        if index is None:
            return False
        markdown = self._markdown.get(index)
        if not markdown:
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:  # pragma: no cover - headless only
            return False
        clipboard.setText(markdown)
        self.statusBar().showMessage(f"Copied {len(markdown):,} character(s)")
        return True

    def _update_thumbnail(self, index: int | None) -> None:
        """First-page-only preview for PDFs and images, using only libraries
        already required (pymupdf, Qt's own image loader) - never a fake
        placeholder standing in for the real document."""
        self.thumbnail_label.hide()
        self.thumbnail_label.clear()
        if index is None or not (0 <= index < len(self._files)):
            return
        source = self._files[index]
        kind = _kind_of(source)
        pixmap: QPixmap | None = None

        if kind is FileKind.PDF:
            pixmap = self._render_pdf_thumbnail(source)
        elif kind is FileKind.IMAGE:
            candidate = QPixmap(str(source))
            pixmap = candidate if not candidate.isNull() else None

        if pixmap is None:
            return
        scaled = pixmap.scaled(
            self.thumbnail_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumbnail_label.setPixmap(scaled)
        self.thumbnail_label.setToolTip("Preview of page 1 only - not the full document.")
        self.thumbnail_label.show()

    @staticmethod
    def _render_pdf_thumbnail(source: Path) -> QPixmap | None:
        try:
            import pymupdf
        except ImportError:
            return None
        try:
            doc = pymupdf.open(filename=str(source))
        except Exception:
            return None
        try:
            if doc.page_count == 0:
                return None
            page = doc[0]
            pix = page.get_pixmap(dpi=96)
            image = QPixmap()
            if not image.loadFromData(pix.tobytes("png"), "PNG"):
                return None
            return image
        except Exception:
            return None
        finally:
            try:
                doc.close()
            except Exception:
                pass

    def _show_quality_summary(self, index: int | None) -> None:
        """Refresh the quality badge/detail row for the selected file.

        The badge reflects the row's *displayed* status (``item.text``),
        which already folds in a write failure that happened after a
        successful conversion - not ``status_of(result)`` alone, which would
        still read Success for a document whose Markdown never reached disk.
        """
        if index is None or index not in self._results:
            self.quality_badge.hide()
            self.quality_detail.setText("Select a converted file to see its quality summary.")
            return

        item = self._items[index]
        status_text = item.text(COLUMN_STATUS)
        result = self._results[index]

        self.quality_badge.setText(status_text)
        self.quality_badge.setProperty("status", _STATUS_KEYS.get(status_text, "queued"))
        self.quality_badge.style().unpolish(self.quality_badge)
        self.quality_badge.style().polish(self.quality_badge)
        self.quality_badge.show()

        facts: list[str] = []
        try:
            source_size = self._files[index].stat().st_size
        except (OSError, IndexError):
            source_size = None
        facts.append(f"source {_human_size(source_size)}")

        quality = getattr(result, "quality", None)
        if quality is not None:
            if quality.pages_total is not None:
                # Prefer "pages with content" - it is the only field that
                # honestly answers "how much of the document did we actually
                # capture". pages_read alone can be == pages_total for a
                # scanned PDF whose OCR was disabled/unavailable, which
                # would read as a false success if shown as "pages read N/N".
                if quality.pages_with_content is not None:
                    facts.append(f"pages with content {quality.pages_with_content}/{quality.pages_total}")
                elif quality.pages_read is not None:
                    facts.append(f"pages processed {quality.pages_read}/{quality.pages_total}")
                else:
                    facts.append(f"{quality.pages_total} page(s)")
                if quality.pages_failed:
                    facts.append(f"{quality.pages_failed} page(s) failed")
            if quality.tables_detected is not None:
                facts.append(f"{quality.tables_detected} table(s)")
            if quality.sheets_detected is not None:
                facts.append(f"{quality.sheets_detected} sheet(s)")
            rows_detected_text = _format_rows_detected(quality)
            if rows_detected_text is not None:
                exported = quality.rows_exported if quality.rows_exported is not None else "?"
                facts.append(f"rows {exported}/{rows_detected_text}")
            if quality.truncated:
                facts.append("truncated")
            if quality.ocr_backend is not None:
                facts.append(f"OCR: {quality.ocr_backend} ({quality.ocr_language or 'default'})")
                if quality.ocr_pages_failed:
                    facts.append(f"{quality.ocr_pages_failed} OCR page(s) failed")
            elif quality.ocr_pages_success is not None or quality.ocr_pages_empty is not None:
                facts.append("OCR: no backend available")

        self.quality_detail.setText(" · ".join(facts))

    def _update_actions(self) -> None:
        running = self._is_running()
        has_files = bool(self._files)
        has_output = bool(self._markdown)
        statuses = [item.text(COLUMN_STATUS) for item in self._items]
        has_errors = STATUS_ERROR in statuses
        has_warnings = STATUS_WARNING in statuses
        has_successes = STATUS_SUCCESS in statuses
        self.convert_button.setEnabled(has_files and not running)
        self.cancel_button.setEnabled(running)
        self.clear_button.setEnabled(has_files and not running)
        self.copy_button.setEnabled(has_output and not running)
        self.export_report_button.setEnabled(bool(self._markdown or self._results) and not running)
        self.retry_failed_button.setEnabled(has_errors and not running)
        self.retry_warnings_button.setEnabled(has_warnings and not running)
        self.clear_completed_button.setEnabled(has_successes and not running)
        self.export_error_report_button.setEnabled(has_errors and not running)
        # The FILES panel doubles as the drop target: show the drag & drop
        # invitation only while there is truly nothing to show, including
        # skipped-folder-content rows (which never touch self._files).
        self.file_list_stack.setCurrentWidget(
            self.file_tree if self.file_tree.topLevelItemCount() else self.drop_zone
        )

    def _warn(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        paths = DropZone.paths_from_urls(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self.add_paths(paths)
        else:
            event.ignore()

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
            # Never force-delete the QThread/worker here: run() may still be
            # partway through converter.convert_file() (a slow OCR page,
            # say), and worker.cancel() only flips a flag the run() loop
            # checks between files - it does not interrupt in-flight work.
            # Signal cancellation, keep the window open, and let
            # _on_batch_finished -> _teardown_thread do the real cleanup
            # once run() has genuinely returned; that handler also closes
            # the window for us via `_close_after_cancel`.
            self._close_after_cancel = True
            self.cancel_conversion()
            self.statusBar().showMessage(
                "Cancelling… closing once the current file finishes."
            )
            event.ignore()
            return
        self._scan_queue.clear()
        if self._scan_thread is not None and self._scan_worker is not None:
            thread, worker = self._scan_thread, self._scan_worker
            self._scan_thread = self._scan_worker = None
            worker.done.disconnect(self._on_scan_done)
            _ORPHANED_SCANS.append((thread, worker))
            thread.finished.connect(lambda: _ORPHANED_SCANS.remove((thread, worker)))
            thread.quit()
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
