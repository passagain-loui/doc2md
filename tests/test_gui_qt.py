"""Behavioural tests for the PyQt6 window.

Run against a real ``QApplication`` on the offscreen platform plugin, so the
widgets, signals and the worker thread are the actual ones that ship - not
stand-ins. The window is never ``show()``n, which keeps the suite headless.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from doc2md.core.bridge import MANIFEST_NAME  # noqa: E402
from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import (  # noqa: E402
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    STATUS_WARNING,
    ConversionWorker,
    MainWindow,
)

COLUMN_STATUS = 2
COLUMN_DETAIL = 3


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    yield app


@pytest.fixture
def window(qapp, tmp_path):
    # Isolated, temp-file-backed QSettings - a MainWindow constructed
    # without one falls back to the real %APPDATA%\doc2md\doc2md.ini, which
    # a test suite must never write to.
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def make_txt(directory: Path, name: str, body: str = "เนื้อหาทดสอบ") -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def run_batch(window: MainWindow, qapp, timeout_ms: int = 30_000) -> None:
    """Start the conversion and pump the event loop until it finishes."""
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    finished: list[tuple] = []
    original = window._on_batch_finished

    def spy(succeeded, failed, cancelled):
        original(succeeded, failed, cancelled)
        finished.append((succeeded, failed, cancelled))

    window._on_batch_finished = spy
    window.start_conversion()

    deadline = QDeadlineTimer(timeout_ms)
    while not finished and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    assert finished, "conversion did not finish within the timeout"


# --- construction ------------------------------------------------------------


def test_window_starts_with_actions_disabled(window):
    assert not window.convert_button.isEnabled()
    assert not window.cancel_button.isEnabled()
    assert not window.copy_button.isEnabled()


def test_drop_zone_accepts_drops(window):
    assert window.drop_zone.acceptDrops()


def test_every_button_carries_an_icon(window):
    for button in (
        window.clear_button,
        window.convert_button,
        window.cancel_button,
        window.copy_button,
    ):
        assert not button.icon().isNull(), button.text()


def test_stylesheet_paints_a_dark_surface(qapp):
    assert theme.BG in theme.STYLESHEET
    assert theme.ACCENT in theme.STYLESHEET
    assert "QProgressBar::chunk" in theme.STYLESHEET


# --- queue management --------------------------------------------------------


def test_adding_files_enables_conversion(window, tmp_path):
    window.add_paths([make_txt(tmp_path, "หนึ่ง.txt"), make_txt(tmp_path, "two.txt")])

    assert window.file_tree.topLevelItemCount() == 2
    assert window.convert_button.isEnabled()
    assert window.file_tree.topLevelItem(0).text(COLUMN_STATUS) == STATUS_QUEUED


def test_the_same_file_is_not_queued_twice(window, tmp_path):
    source = make_txt(tmp_path, "dup.txt")

    window.add_paths([source])
    window.add_paths([source])

    assert window.file_tree.topLevelItemCount() == 1


def test_the_same_file_is_not_queued_twice_via_a_differently_spelled_path(window, tmp_path):
    """The cross-drop dedup check must resolve paths, not compare raw
    strings - otherwise the same physical file queued through two
    differently-spelled (but equivalent) paths converts twice."""
    source = make_txt(tmp_path, "dup.txt")
    equivalent = tmp_path / "." / "dup.txt"

    window.add_paths([source])
    window.add_paths([equivalent])

    assert window.file_tree.topLevelItemCount() == 1


def test_unsupported_files_are_listed_as_skipped(window, tmp_path):
    media = tmp_path / "ประชุม.mp3"
    media.write_bytes(bytes([0x49, 0x44, 0x33, 3, 0, 0, 0]) + bytes(32))

    window.add_paths([media])

    item = window.file_tree.topLevelItem(0)
    assert item.text(COLUMN_STATUS) == STATUS_SKIPPED
    assert "removed" in item.text(COLUMN_DETAIL)
    assert not window.convert_button.isEnabled()


def test_clear_empties_the_queue(window, tmp_path):
    window.add_paths([make_txt(tmp_path, "a.txt")])

    window.clear_files()

    assert window.file_tree.topLevelItemCount() == 0
    assert not window.convert_button.isEnabled()


# --- batch conversion --------------------------------------------------------


def test_batch_conversion_marks_every_row_success(window, qapp, tmp_path):
    sources = [
        make_txt(tmp_path, "รายงาน หนึ่ง.txt", "บรรทัดแรก"),
        make_txt(tmp_path, "report two.txt", "second line"),
        make_txt(tmp_path, "สาม.txt", "บรรทัดที่สาม"),
    ]
    window.add_paths(sources)

    run_batch(window, qapp)

    statuses = [
        window.file_tree.topLevelItem(i).text(COLUMN_STATUS) for i in range(len(sources))
    ]
    assert statuses == [STATUS_SUCCESS] * 3
    assert window.progress_bar.value() == 100
    assert window.progress_label.text() == "3 / 3"
    assert "บรรทัดแรก" in window._markdown[0]


def test_a_failing_file_does_not_stop_the_batch(window, qapp, tmp_path):
    good = make_txt(tmp_path, "good.txt")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\n" + bytes(range(256)) * 4)
    window.add_paths([broken, good])

    run_batch(window, qapp)

    statuses = {
        window.file_tree.topLevelItem(i).text(COLUMN_STATUS) for i in range(2)
    }
    assert statuses == {STATUS_SUCCESS, STATUS_ERROR}
    error_row = next(
        window.file_tree.topLevelItem(i)
        for i in range(2)
        if window.file_tree.topLevelItem(i).text(COLUMN_STATUS) == STATUS_ERROR
    )
    assert error_row.text(COLUMN_DETAIL).strip(), "an error row must say why"


def test_ocr_backend_status_reflects_real_environment():
    """Bug B2: the GUI must know, before any conversion, whether an OCR
    backend is actually usable - not discover it only after a scan comes
    back empty."""
    import shutil

    from doc2md.gui.main_window import MainWindow as _MW

    available, message = _MW._ocr_backend_status()
    real_tesseract = shutil.which("tesseract") is not None
    try:
        import rapidocr_onnxruntime  # noqa: F401

        real_rapidocr = True
    except ImportError:
        real_rapidocr = False

    assert available == (real_tesseract or real_rapidocr)
    assert isinstance(message, str) and message


def test_ocr_backend_label_is_populated_on_window_creation(window):
    """The status must be visible before the user ever presses Convert."""
    text = window.ocr_backend_label.text()
    assert text.strip()
    assert text.startswith(("✓", "⚠"))


def test_warning_result_shows_warning_status_not_success(window, qapp, tmp_path, monkeypatch):
    """A file that converts with a warning (e.g. OCR unavailable) must be a
    distinct Warning row, not indistinguishable from Success, and must be
    called out in the batch summary (Bug B2)."""
    source = make_txt(tmp_path, "scan.txt", "placeholder")
    window.add_paths([source])

    class FakeResult:
        success = True
        markdown = "# scan.txt\n\n> OCR unavailable\n"
        error = ""
        warning = "OCR unavailable: neither Tesseract nor RapidOCR is available"

    class FakeConverter:
        def __init__(self, **kwargs):
            pass

        def convert_file(self, path):
            return FakeResult()

    monkeypatch.setattr("doc2md.gui.main_window.Converter", FakeConverter)

    run_batch(window, qapp)

    row = window.file_tree.topLevelItem(0)
    assert row.text(COLUMN_STATUS) == STATUS_WARNING
    assert "OCR unavailable" in row.text(COLUMN_DETAIL)
    assert window.statusBar().currentMessage().count("with warnings") == 1


def test_closing_window_during_conversion_does_not_force_delete_thread(
    window, qapp, tmp_path, monkeypatch
):
    """Bug B3: closeEvent must not blindly wait(5000) then deleteLater() the
    thread/worker regardless of whether run() actually finished. It must
    instead defer teardown until the worker's own `finished` signal proves
    run() has returned, and only close the window then."""
    import threading

    from PyQt6.QtWidgets import QMessageBox

    release = threading.Event()
    entered_conversion = threading.Event()

    class SlowResult:
        success = True
        markdown = "# slow\n"
        error = ""
        warning = None

    class SlowConverter:
        def __init__(self, **kwargs):
            pass

        def convert_file(self, path):
            entered_conversion.set()
            release.wait(timeout=10)
            return SlowResult()

    monkeypatch.setattr("doc2md.gui.main_window.Converter", SlowConverter)
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )

    source = make_txt(tmp_path, "slow.txt")
    window.add_paths([source])
    window.start_conversion()

    assert entered_conversion.wait(timeout=5), "conversion never started"
    assert window._is_running()

    from PyQt6.QtGui import QCloseEvent

    event = QCloseEvent()
    window.closeEvent(event)

    # The close must be deferred, not forced: the event is ignored, the
    # thread/worker are still alive, and cancellation was requested.
    assert not event.isAccepted()
    assert window._close_after_cancel is True
    assert window._thread is not None
    assert window._worker is not None
    assert window._worker._cancelled is True

    # Let the in-flight "conversion" finish; the batch's own completion path
    # must now perform the real teardown and close the window.
    release.set()
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(5000)
    while window._thread is not None and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    assert window._thread is None
    assert window._worker is None
    assert window._close_after_cancel is False


def test_txt_output_format_is_honoured(window, qapp, tmp_path):
    """Selecting .txt format should affect output_suffix and conversion still succeeds."""
    source = make_txt(tmp_path, "plain.txt", "original body")
    window.add_paths([source])
    window.format_combo.setCurrentIndex(1)

    assert window.output_suffix() == ".txt"
    run_batch(window, qapp)

    assert window.file_tree.topLevelItem(0).text(COLUMN_STATUS) == STATUS_SUCCESS
    assert source.read_text(encoding="utf-8") == "original body"


# --- options -----------------------------------------------------------------


def test_conversion_options_follow_the_controls(window):
    window.ocr_check.setChecked(False)
    window.tables_check.setChecked(False)
    window.ocr_combo.setCurrentIndex(2)

    options = window.conversion_options()

    assert options["pdf_ocr_fallback"] is False
    assert options["pdf_tables"] is False
    assert options["ocr_lang"] == "eng"


def test_default_ocr_language_is_thai_plus_english(window):
    assert window.conversion_options()["ocr_lang"] == "tha+eng"


# --- clipboard and bridge ----------------------------------------------------


def test_copy_markdown_puts_every_result_on_the_clipboard(window, qapp, tmp_path):
    window.add_paths(
        [make_txt(tmp_path, "หนึ่ง.txt", "อัลฟา"), make_txt(tmp_path, "song.txt", "beta")]
    )
    run_batch(window, qapp)

    assert window.copy_button.isEnabled()
    assert window.copy_markdown() is True

    clipboard_text = qapp.clipboard().text()
    assert "อัลฟา" in clipboard_text
    assert "beta" in clipboard_text
    assert "---" in clipboard_text


def test_copy_markdown_refuses_when_there_is_nothing_to_copy(window):
    assert window.collected_markdown() == ""
    assert window.copy_markdown(quiet=True) is False


def test_bridge_payload_carries_the_converted_documents(window, qapp, tmp_path):
    window.add_paths([make_txt(tmp_path, "รายงาน.txt", "เนื้อหา")])
    run_batch(window, qapp)

    payload = window.build_bridge_payload()

    assert [doc.name for doc in payload.documents] == ["รายงาน"]
    assert "เนื้อหา" in payload.documents[0].markdown
    assert payload.target == "mediplex-ai-sandbox"


def test_bridge_writes_a_bundle_the_sandbox_can_read(window, qapp, tmp_path, monkeypatch):
    inbox = tmp_path / "sandbox-inbox"
    window.add_paths([make_txt(tmp_path, "ใบเสร็จ.txt", "ยอดรวม 100")])
    run_batch(window, qapp)

    monkeypatch.setattr(
        "doc2md.gui.main_window.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(inbox),
    )

    assert window.send_to_bridge() is True

    bundles = list(inbox.iterdir())
    assert len(bundles) == 1
    manifest = json.loads((bundles[0] / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["document_count"] == 1
    assert manifest["producer"] == "doc2md"


def test_bridge_is_a_no_op_when_the_folder_dialog_is_cancelled(window, qapp, tmp_path, monkeypatch):
    window.add_paths([make_txt(tmp_path, "x.txt")])
    run_batch(window, qapp)

    monkeypatch.setattr(
        "doc2md.gui.main_window.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: "",
    )

    assert window.send_to_bridge() is False


# --- worker ------------------------------------------------------------------


def test_worker_reports_one_terminal_state_per_file(tmp_path):
    """Run the worker synchronously - no file may be silently dropped."""
    sources = [make_txt(tmp_path, f"f{i}.txt", f"body {i}") for i in range(4)]
    worker = ConversionWorker(sources, {}, timeout=30.0)

    started: list[int] = []
    finished: list[tuple[int, bool]] = []
    worker.file_started.connect(lambda index, _name: started.append(index))
    worker.file_finished.connect(lambda index, ok, _md, _err: finished.append((index, ok)))
    worker.run()

    assert started == [0, 1, 2, 3]
    assert [index for index, _ok in finished] == [0, 1, 2, 3]
    assert all(ok for _index, ok in finished)


def test_cancelled_worker_stops_early(tmp_path):
    sources = [make_txt(tmp_path, f"c{i}.txt") for i in range(3)]
    worker = ConversionWorker(sources, {}, timeout=30.0)
    worker.cancel()

    summary: list[tuple] = []
    worker.finished.connect(lambda *args: summary.append(args))
    worker.run()

    assert summary == [(0, 0, True)]


# --- entry point -------------------------------------------------------------


def test_run_gui_builds_and_shows_the_window(qapp, monkeypatch, tmp_path):
    """Exercise the real entry point, including stylesheet application.

    run_gui() constructs MainWindow() with no explicit `settings`, which
    would otherwise fall back to the real %APPDATA%\\doc2md\\doc2md.ini -
    the QSettings class itself is patched (not just an instance) so that
    fallback also lands on a temp file, not the user's real profile.
    """
    from PyQt6.QtCore import QSettings, QTimer

    from doc2md.gui import run_gui
    import doc2md.gui.main_window as gui_main_window

    isolated_settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    class _FakeSettingsFactory:
        # MainWindow.__init__ reads QSettings.Format.IniFormat /
        # QSettings.Scope.UserScope as class attributes before constructing
        # one - a plain lambda replacement would lose those, so this keeps
        # them while redirecting construction to the isolated instance.
        Format = QSettings.Format
        Scope = QSettings.Scope

        def __call__(self, *args, **kwargs):
            return isolated_settings

    monkeypatch.setattr(gui_main_window, "QSettings", _FakeSettingsFactory())

    shown: list[bool] = []

    original_show = MainWindow.show

    def spy_show(self):
        shown.append(True)
        original_show(self)
        QTimer.singleShot(0, qapp.quit)

    monkeypatch.setattr(MainWindow, "show", spy_show)

    assert run_gui([]) == 0
    assert shown == [True]
    assert theme.ACCENT in qapp.styleSheet()


# --- drag & drop anywhere on the window --------------------------------------


@pytest.mark.parametrize("target", ["window", "file_tree", "preview", "drop_zone"])
def test_files_dropped_anywhere_on_the_window_are_queued(window, qapp, tmp_path, target):
    from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PyQt6.QtGui import QDragEnterEvent, QDropEvent

    source = make_txt(tmp_path, "ลาก.txt")
    widget = {
        "window": window,
        "file_tree": window.file_tree,
        "preview": window.preview,
        "drop_zone": window.drop_zone,
    }[target]
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])

    enter = QDragEnterEvent(
        widget.rect().center(), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(widget, enter)
    assert enter.isAccepted() or widget is window.preview

    drop = QDropEvent(
        QPointF(widget.rect().center()), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    # Mirror Qt's dispatch: walk up to the first widget that accepts drops.
    receiver = widget
    while receiver is not None and not receiver.acceptDrops():
        receiver = receiver.parentWidget()
    assert receiver is not None, "no widget on the path accepts drops"
    qapp.sendEvent(receiver, drop)

    assert window.file_tree.topLevelItemCount() == 1


# --- folders are scanned off the GUI thread ------------------------------------


def test_dropped_folder_is_scanned_in_the_background_and_queued(window, qapp, tmp_path):
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    folder = tmp_path / "ชุดเอกสาร"
    (folder / "sub").mkdir(parents=True)
    make_txt(folder, "a.txt")
    make_txt(folder / "sub", "b.txt")
    (folder / "old.md").write_text("# already converted", encoding="utf-8")

    window.add_paths([folder])
    assert window.file_tree.topLevelItemCount() == 0, "the scan must not block the caller"

    deadline = QDeadlineTimer(10_000)
    while window._scan_thread is not None and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    names = sorted(path.name for path in window._files)
    assert names == ["a.txt", "b.txt"]


def test_two_folder_drops_in_a_row_are_both_scanned(window, qapp, tmp_path):
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    make_txt(first, "x.txt")
    make_txt(second, "y.txt")

    window.add_paths([first])
    window.add_paths([second])

    deadline = QDeadlineTimer(10_000)
    while (window._scan_thread is not None or window._scan_queue) and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    assert sorted(path.name for path in window._files) == ["x.txt", "y.txt"]


def test_hidden_sheets_checkbox_feeds_the_conversion_options(window):
    assert window.conversion_options()["include_hidden_sheets"] is False

    window.hidden_sheets_check.setChecked(True)

    assert window.conversion_options()["include_hidden_sheets"] is True
