"""Milestone 1 - GUI Quality Summary panel and Export Report button.

Runs against a real offscreen QApplication (see tests/test_gui_qt.py for the
pattern this follows) so the worker thread, signals and widgets exercised are
the ones that actually ship.
"""

from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import COLUMN_STATUS, STATUS_ERROR, STATUS_SUCCESS, MainWindow  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    yield app


@pytest.fixture
def window(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    win = MainWindow(settings=settings)
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


def test_quality_panel_starts_with_placeholder(window):
    assert window.quality_badge.isHidden()
    assert "Select a converted file" in window.quality_detail.text()


def test_export_report_disabled_until_something_converts(window):
    assert not window.export_report_button.isEnabled()


def test_quality_panel_shows_pdf_metrics_after_conversion(window, qapp, simple_pdf, tmp_path):
    window.add_paths([simple_pdf])

    run_batch(window, qapp)

    item = window.file_tree.topLevelItem(0)
    window.file_tree.setCurrentItem(item)
    qapp.processEvents()

    assert item.text(COLUMN_STATUS) == STATUS_SUCCESS
    assert not window.quality_badge.isHidden()
    assert window.quality_badge.text() == STATUS_SUCCESS
    assert "pages with content 1/1" in window.quality_detail.text()


def test_export_report_writes_real_metrics(window, qapp, simple_pdf, tmp_path):
    window.add_paths([simple_pdf])

    run_batch(window, qapp)
    assert window.export_report_button.isEnabled()

    entries = window.build_quality_report()
    assert len(entries) == 1
    assert entries[0]["status"] == STATUS_SUCCESS
    assert entries[0]["pages_total"] == 1
    assert entries[0]["output"] is None

    report_path = tmp_path / "report.json"
    from doc2md.core.quality import write_report_atomic

    write_report_atomic(entries, report_path)
    assert json.loads(report_path.read_text(encoding="utf-8")) == entries
