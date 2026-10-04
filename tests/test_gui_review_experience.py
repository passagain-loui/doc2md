"""Milestone 5 - Review Experience.

Warning banner, Open Original/Output, per-row Copy Markdown, Compare
Metadata, and first-page-only thumbnails for PDF/image - all built from
libraries already required (pymupdf, Qt's own image loader), never a fake
stand-in for the real document.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import (  # noqa: E402
    COLUMN_STATUS,
    STATUS_SUCCESS,
    STATUS_WARNING,
    MainWindow,
    collect_files,
)


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


def run_batch(window: MainWindow, qapp, action=None, timeout_ms: int = 30_000) -> None:
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    finished: list[tuple] = []
    original = window._on_batch_finished

    def spy(succeeded, failed, cancelled):
        original(succeeded, failed, cancelled)
        finished.append((succeeded, failed, cancelled))

    window._on_batch_finished = spy
    (action or window.start_conversion)()

    deadline = QDeadlineTimer(timeout_ms)
    while not finished and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    assert finished, "conversion did not finish within the timeout"


def make_txt(directory, name, body="content"):
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _make_scanned_pdf(path):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def _make_text_pdf(path, text="Real readable PDF content"):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


# --- warning banner --------------------------------------------------------------


def test_warning_banner_hidden_for_a_clean_success(window, qapp, tmp_path):
    source = make_txt(tmp_path, "good.txt")
    window.add_paths([source])
    run_batch(window, qapp)

    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()

    assert window.warning_banner.isHidden()


def test_warning_banner_shown_for_a_warning_row(window, qapp, tmp_path):
    scanned = _make_scanned_pdf(tmp_path / "scan.pdf")
    window.add_paths([scanned])
    run_batch(window, qapp)

    item = window.file_tree.topLevelItem(0)
    assert item.text(COLUMN_STATUS) == STATUS_WARNING
    window.file_tree.setCurrentItem(item)
    qapp.processEvents()

    assert not window.warning_banner.isHidden()
    assert window.warning_banner.text() != ""


# --- open original -----------------------------------------------------------------


def test_row_actions_disabled_before_any_selection(window):
    assert not window.open_original_button.isEnabled()
    assert not window.row_copy_button.isEnabled()


def test_open_original_enabled_after_selecting_a_converted_row(window, qapp, tmp_path):
    source = make_txt(tmp_path, "good.txt")
    window.add_paths([source])
    run_batch(window, qapp)

    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()

    assert window.open_original_button.isEnabled()
    assert window.row_copy_button.isEnabled()


def test_open_original_calls_desktop_services_with_the_source_path(window, qapp, tmp_path, monkeypatch):
    source = make_txt(tmp_path, "good.txt")
    window.add_paths([source])
    run_batch(window, qapp)
    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()

    opened = []
    from doc2md.gui import main_window as gui_main_window

    monkeypatch.setattr(
        gui_main_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile())
    )

    window.open_original()
    assert [Path(p) for p in opened] == [source]


# --- per-row copy markdown ---------------------------------------------------------


def test_copy_selected_markdown_copies_only_the_selected_row(window, qapp, tmp_path):
    a = make_txt(tmp_path, "a.txt", "AAAA marker")
    b = make_txt(tmp_path, "b.txt", "BBBB marker")
    window.add_paths([a, b])
    run_batch(window, qapp)

    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()
    assert window.copy_selected_markdown() is True

    clipboard = QApplication.clipboard()
    assert "AAAA marker" in clipboard.text()
    assert "BBBB marker" not in clipboard.text()


# --- compare metadata ---------------------------------------------------------------


def test_compare_metadata_shows_source_and_output_size(window, qapp, tmp_path):
    source = make_txt(tmp_path, "good.txt", "hello world")
    window.add_paths([source])
    run_batch(window, qapp)

    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()

    text = window.compare_metadata.text()
    assert "Source" in text
    assert "Output" in text
    assert "Warning: none" in text


def test_compare_metadata_shows_pdf_page_count(window, qapp, tmp_path):
    pdf = _make_text_pdf(tmp_path / "doc.pdf")
    window.add_paths([pdf])
    run_batch(window, qapp)

    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()

    assert "Pages: 1" in window.compare_metadata.text()


def test_compare_metadata_placeholder_when_nothing_selected(window):
    assert window.compare_metadata.text() == ""


# --- thumbnails ----------------------------------------------------------------------


def test_pdf_thumbnail_is_shown_for_a_text_pdf(window, qapp, tmp_path):
    pdf = _make_text_pdf(tmp_path / "doc.pdf")
    window.add_paths([pdf])
    run_batch(window, qapp)

    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()

    assert not window.thumbnail_label.isHidden()
    assert not window.thumbnail_label.pixmap().isNull()


def test_thumbnail_hidden_for_a_text_file(window, qapp, tmp_path):
    source = make_txt(tmp_path, "good.txt")
    window.add_paths([source])
    run_batch(window, qapp)

    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()

    assert window.thumbnail_label.isHidden()


def test_thumbnail_cleared_when_selection_is_cleared(window, qapp, tmp_path):
    pdf = _make_text_pdf(tmp_path / "doc.pdf")
    window.add_paths([pdf])
    run_batch(window, qapp)
    window.file_tree.setCurrentItem(window.file_tree.topLevelItem(0))
    qapp.processEvents()
    assert not window.thumbnail_label.isHidden()

    window.clear_files()
    assert window.thumbnail_label.isHidden()


# --- folder skip UX: collect_files reasons -------------------------------------------


def test_folder_with_only_markdown_files_reports_a_real_reason(tmp_path):
    folder = tmp_path / "already_converted"
    folder.mkdir()
    (folder / "a.md").write_text("# a", encoding="utf-8")
    (folder / "b.md").write_text("# b", encoding="utf-8")

    accepted, rejected = collect_files([folder])

    assert accepted == []
    assert len(rejected) == 1
    _path, reason = rejected[0]
    assert "empty" not in reason.lower()
    assert "2" in reason
    assert "markdown" in reason.lower()


def test_truly_empty_folder_says_empty(tmp_path):
    folder = tmp_path / "nothing_here"
    folder.mkdir()

    accepted, rejected = collect_files([folder])

    assert accepted == []
    assert rejected == [(folder, "folder is empty")]


def test_folder_with_real_files_and_markdown_reports_the_skip_count(tmp_path):
    folder = tmp_path / "mixed"
    folder.mkdir()
    good = folder / "report.txt"
    good.write_text("hello", encoding="utf-8")
    (folder / "old-output.md").write_text("# old", encoding="utf-8")

    accepted, rejected = collect_files([folder])

    assert accepted == [good]
    assert len(rejected) == 1
    _path, reason = rejected[0]
    assert "1" in reason
    assert "markdown" in reason.lower()


def test_folder_with_no_markdown_at_all_reports_nothing_extra(tmp_path):
    folder = tmp_path / "clean"
    folder.mkdir()
    good = folder / "report.txt"
    good.write_text("hello", encoding="utf-8")

    accepted, rejected = collect_files([folder])

    assert accepted == [good]
    assert rejected == []
