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

from PyQt6.QtWidgets import QApplication  # noqa: E402

from doc2md.core.bridge import MANIFEST_NAME  # noqa: E402
from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import (  # noqa: E402
    STATUS_ERROR,
    STATUS_QUEUED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
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
def window(qapp):
    win = MainWindow()
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
    assert not window.bridge_button.isEnabled()


def test_drop_zone_accepts_drops(window):
    assert window.drop_zone.acceptDrops()


def test_every_button_carries_an_icon(window):
    for button in (
        window.add_button,
        window.clear_button,
        window.convert_button,
        window.cancel_button,
        window.copy_button,
        window.bridge_button,
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


def test_batch_conversion_marks_every_row_and_writes_output(window, qapp, tmp_path):
    out_dir = tmp_path / "ผลลัพธ์"
    sources = [
        make_txt(tmp_path, "รายงาน หนึ่ง.txt", "บรรทัดแรก"),
        make_txt(tmp_path, "report two.txt", "second line"),
        make_txt(tmp_path, "สาม.txt", "บรรทัดที่สาม"),
    ]
    window.add_paths(sources)
    window.beside_source_check.setChecked(False)
    window.output_edit.setText(str(out_dir))

    run_batch(window, qapp)

    statuses = [
        window.file_tree.topLevelItem(i).text(COLUMN_STATUS) for i in range(len(sources))
    ]
    assert statuses == [STATUS_SUCCESS] * 3
    assert window.progress_bar.value() == 100
    assert window.progress_label.text() == "3 / 3"

    written = sorted(p.name for p in out_dir.glob("*.md"))
    assert written == ["report two.md", "รายงาน หนึ่ง.md", "สาม.md"]
    assert "บรรทัดแรก" in (out_dir / "รายงาน หนึ่ง.md").read_text(encoding="utf-8")


def test_output_is_written_next_to_the_source_when_requested(window, qapp, tmp_path):
    folder = tmp_path / "เอกสาร ไทย"
    folder.mkdir()
    source = make_txt(folder, "บันทึก.txt")
    window.add_paths([source])
    window.beside_source_check.setChecked(True)

    run_batch(window, qapp)

    assert (folder / "บันทึก.md").is_file()


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


def test_colliding_output_names_do_not_overwrite_each_other(window, qapp, tmp_path):
    out_dir = tmp_path / "out"
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    make_txt(first, "report.txt", "first body")
    make_txt(second, "report.txt", "second body")

    window.add_paths([first / "report.txt", second / "report.txt"])
    window.beside_source_check.setChecked(False)
    window.output_edit.setText(str(out_dir))

    run_batch(window, qapp)

    assert sorted(p.name for p in out_dir.glob("*.md")) == ["report-1.md", "report.md"]


def test_txt_output_format_is_honoured(window, qapp, tmp_path):
    """Writing .txt beside a .txt source must not overwrite the source."""
    source = make_txt(tmp_path, "plain.txt", "original body")
    window.add_paths([source])
    window.format_combo.setCurrentIndex(1)
    window.beside_source_check.setChecked(True)

    assert window.output_suffix() == ".txt"
    run_batch(window, qapp)

    assert source.read_text(encoding="utf-8") == "original body"
    assert (tmp_path / "plain-1.txt").is_file()


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


def test_output_folder_field_follows_the_beside_source_checkbox(window):
    window.beside_source_check.setChecked(True)
    assert not window.output_edit.isEnabled()

    window.beside_source_check.setChecked(False)
    assert window.output_edit.isEnabled()


# --- clipboard and bridge ----------------------------------------------------


def test_copy_markdown_puts_every_result_on_the_clipboard(window, qapp, tmp_path):
    window.add_paths(
        [make_txt(tmp_path, "หนึ่ง.txt", "อัลฟา"), make_txt(tmp_path, "song.txt", "beta")]
    )
    window.beside_source_check.setChecked(True)
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
    window.beside_source_check.setChecked(True)
    run_batch(window, qapp)

    payload = window.build_bridge_payload()

    assert [doc.name for doc in payload.documents] == ["รายงาน"]
    assert "เนื้อหา" in payload.documents[0].markdown
    assert payload.target == "mediplex-ai-sandbox"


def test_bridge_writes_a_bundle_the_sandbox_can_read(window, qapp, tmp_path, monkeypatch):
    inbox = tmp_path / "sandbox-inbox"
    window.add_paths([make_txt(tmp_path, "ใบเสร็จ.txt", "ยอดรวม 100")])
    window.beside_source_check.setChecked(True)
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
    window.beside_source_check.setChecked(True)
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


def test_run_gui_builds_and_shows_the_window(qapp, monkeypatch):
    """Exercise the real entry point, including stylesheet application."""
    from PyQt6.QtCore import QTimer

    from doc2md.gui import run_gui

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
