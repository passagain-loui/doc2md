"""Milestone 2 - GUI output policy: dropdown, destination preview,
QSettings persistence, and the Converted-folder default.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import COLUMN_DETAIL, COLUMN_STATUS, STATUS_ERROR, STATUS_SUCCESS, MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    yield app


@pytest.fixture
def isolated_settings(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def window(qapp, isolated_settings):
    win = MainWindow(settings=isolated_settings)
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def run_batch(window: MainWindow, qapp, timeout_ms: int = 30_000) -> None:
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


def make_txt(directory, name, body="content"):
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_default_policy_is_converted_folder(window):
    assert window.selected_output_policy() == "converted-folder"


def test_default_policy_writes_into_a_converted_subfolder(window, qapp, tmp_path):
    source = make_txt(tmp_path, "note.txt")
    window.add_paths([source])
    window.beside_source_check.setChecked(True)

    run_batch(window, qapp)

    item = window.file_tree.topLevelItem(0)
    assert item.text(COLUMN_STATUS) == STATUS_SUCCESS
    assert (tmp_path / "Converted" / "note.md").is_file()
    assert not (tmp_path / "note.md").exists()


def test_destination_preview_shown_before_conversion(window, tmp_path):
    source = make_txt(tmp_path, "note.txt")
    window.add_paths([source])
    window.beside_source_check.setChecked(True)

    item = window.file_tree.topLevelItem(0)
    assert "Converted" in item.text(COLUMN_DETAIL)
    assert "note.md" in item.text(COLUMN_DETAIL)


def test_preview_updates_live_when_policy_changes(window, tmp_path):
    source = make_txt(tmp_path, "note.txt")
    window.add_paths([source])
    window.beside_source_check.setChecked(True)

    window.policy_combo.setCurrentIndex(window._policy_index("unique"))

    item = window.file_tree.topLevelItem(0)
    assert "Converted" not in item.text(COLUMN_DETAIL)
    assert str(tmp_path / "note.md") in item.text(COLUMN_DETAIL)


def test_policy_choice_persists_through_settings(qapp, isolated_settings, tmp_path):
    win1 = MainWindow(settings=isolated_settings)
    win1.policy_combo.setCurrentIndex(win1._policy_index("fail"))
    win1.close()
    win1.deleteLater()
    qapp.processEvents()

    win2 = MainWindow(settings=isolated_settings)
    try:
        assert win2.selected_output_policy() == "fail"
    finally:
        win2.close()
        win2.deleteLater()
        qapp.processEvents()


def test_fail_policy_reports_error_when_destination_exists(window, qapp, tmp_path):
    (tmp_path / "note.md").write_text("existing", encoding="utf-8")
    source = make_txt(tmp_path, "note.txt")
    window.add_paths([source])
    window.beside_source_check.setChecked(True)
    window.policy_combo.setCurrentIndex(window._policy_index("fail"))

    run_batch(window, qapp)

    item = window.file_tree.topLevelItem(0)
    assert item.text(COLUMN_STATUS) == STATUS_ERROR
    assert (tmp_path / "note.md").read_text(encoding="utf-8") == "existing"


def test_overwrite_policy_refuses_the_source_file_itself(window, qapp, tmp_path):
    source = tmp_path / "already.md"
    source.write_text("original", encoding="utf-8")
    window.add_paths([source])
    window.beside_source_check.setChecked(True)
    window.policy_combo.setCurrentIndex(window._policy_index("overwrite"))

    run_batch(window, qapp)

    item = window.file_tree.topLevelItem(0)
    assert item.text(COLUMN_STATUS) == STATUS_ERROR
    assert source.read_text(encoding="utf-8") == "original"
