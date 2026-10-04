"""Milestone 3 - Retry and Batch Recovery.

Retry Failed / Retry Warnings must act only on rows in that status, update
the SAME row rather than appending a duplicate, and never leave a stale
prior-round result reachable through Copy Markdown / Send to Sandbox /
Export Report. Clear Completed removes only clean Success rows so Warning
and Error rows stay available to retry. Runs against a real offscreen
QApplication, same pattern as tests/test_gui_qt.py.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import (  # noqa: E402
    COLUMN_DETAIL,
    COLUMN_STATUS,
    STATUS_ERROR,
    STATUS_SUCCESS,
    STATUS_WARNING,
    ConversionWorker,
    MainWindow,
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
    """Install the completion spy BEFORE starting the run, then start it.

    The spy must be in place before ``action`` connects the worker's
    ``finished`` signal (inside start_conversion/retry_failed/retry_warnings)
    - PyQt captures whatever ``window._on_batch_finished`` currently is at
    ``.connect()`` time, so installing the spy after starting the run would
    silently connect the real method instead and this helper would hang.
    """
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
    return finished[-1]


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


def _write_broken_pdf(path):
    """A file the GUI actually queues (recognized as PDF by magic bytes /
    extension) but whose conversion genuinely fails - unlike a random
    unsupported-extension blob, which never reaches the converter at all
    (add_paths rejects it as Skipped before it is even queued)."""
    path.write_bytes(b"%PDF-1.4\n" + bytes(range(256)) * 4)
    return path


def _write_valid_pdf(path):
    """Overwrite *path* with a real, readable single-page PDF - used to
    prove a retry can turn a prior Error into a Success."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Now this is a valid, readable PDF")
    doc.save(str(path))
    doc.close()
    return path


# --- mixed batch setup --------------------------------------------------------


def _run_mixed_batch(window, qapp, tmp_path):
    """One Success, one Warning (scanned PDF, no OCR backend), one Error."""
    good = make_txt(tmp_path, "good.txt", "fine content")
    scanned = _make_scanned_pdf(tmp_path / "scan.pdf")
    bad = _write_broken_pdf(tmp_path / "bad.pdf")

    window.add_paths([good, scanned, bad])
    run_batch(window, qapp)
    return good, scanned, bad


def test_mixed_batch_produces_one_of_each_status(window, qapp, tmp_path):
    good, scanned, bad = _run_mixed_batch(window, qapp, tmp_path)

    statuses = [window.file_tree.topLevelItem(i).text(COLUMN_STATUS) for i in range(3)]
    assert STATUS_SUCCESS in statuses
    assert STATUS_WARNING in statuses
    assert STATUS_ERROR in statuses


# --- retry failed ---------------------------------------------------------------


def test_retry_failed_only_touches_error_rows(window, qapp, tmp_path):
    good, scanned, bad = _run_mixed_batch(window, qapp, tmp_path)
    good_index = window._files.index(good)
    scanned_index = window._files.index(scanned)
    bad_index = window._files.index(bad)

    good_markdown_before = window._markdown.get(good_index)
    warning_detail_before = window._items[scanned_index].text(COLUMN_DETAIL)

    # Fix the failing file in place so the retry can actually succeed.
    _write_valid_pdf(bad)

    run_batch(window, qapp, action=window.retry_failed)

    assert window._items[bad_index].text(COLUMN_STATUS) == STATUS_SUCCESS
    # Success and Warning rows from the first round must be untouched.
    assert window._markdown.get(good_index) == good_markdown_before
    assert window._items[scanned_index].text(COLUMN_DETAIL) == warning_detail_before
    assert window._items[good_index].text(COLUMN_STATUS) == STATUS_SUCCESS
    assert window._items[scanned_index].text(COLUMN_STATUS) == STATUS_WARNING


def test_retry_failed_updates_the_same_row_not_a_new_one(window, qapp, tmp_path):
    bad = _write_broken_pdf(tmp_path / "bad.pdf")
    window.add_paths([bad])
    run_batch(window, qapp)

    assert window.file_tree.topLevelItemCount() == 1
    assert window._items[0].text(COLUMN_STATUS) == STATUS_ERROR

    _write_valid_pdf(bad)
    run_batch(window, qapp, action=window.retry_failed)

    assert window.file_tree.topLevelItemCount() == 1, "retry must not add a duplicate row"
    assert window._items[0].text(COLUMN_STATUS) == STATUS_SUCCESS


def test_retry_failed_that_still_fails_stays_an_error(window, qapp, tmp_path):
    bad = _write_broken_pdf(tmp_path / "bad.pdf")
    window.add_paths([bad])
    run_batch(window, qapp)

    run_batch(window, qapp, action=window.retry_failed)  # still the same broken bytes

    assert window._items[0].text(COLUMN_STATUS) == STATUS_ERROR
    assert 0 not in window._markdown


def test_retry_failed_noop_when_nothing_failed(window, qapp, tmp_path):
    good = make_txt(tmp_path, "good.txt")
    window.add_paths([good])
    run_batch(window, qapp)

    assert not window.retry_failed_button.isEnabled()
    window.retry_failed()  # must be a safe no-op even if called directly
    assert window._items[0].text(COLUMN_STATUS) == STATUS_SUCCESS


# --- retry warnings --------------------------------------------------------------


def test_retry_warnings_only_touches_warning_rows(window, qapp, tmp_path):
    good, scanned, bad = _run_mixed_batch(window, qapp, tmp_path)
    good_index = window._files.index(good)
    bad_index = window._files.index(bad)
    bad_detail_before = window._items[bad_index].text(COLUMN_DETAIL)

    run_batch(window, qapp, action=window.retry_warnings)

    # Nothing about the OCR backend changed, so it is still a Warning - the
    # retry must update the same row's result without turning it into a
    # different status or duplicating it.
    assert window.file_tree.topLevelItemCount() == 3
    scanned_index = window._files.index(scanned)
    assert window._items[scanned_index].text(COLUMN_STATUS) == STATUS_WARNING
    assert window._items[good_index].text(COLUMN_STATUS) == STATUS_SUCCESS
    assert window._items[bad_index].text(COLUMN_DETAIL) == bad_detail_before


# --- clear completed ---------------------------------------------------------------


def test_clear_completed_removes_only_success_rows(window, qapp, tmp_path):
    good, scanned, bad = _run_mixed_batch(window, qapp, tmp_path)

    window.clear_completed()

    assert window.file_tree.topLevelItemCount() == 2
    remaining_status = {
        window.file_tree.topLevelItem(i).text(COLUMN_STATUS) for i in range(2)
    }
    assert remaining_status == {STATUS_WARNING, STATUS_ERROR}
    assert not window.clear_completed_button.isEnabled()


def test_clear_completed_reindexes_bookkeeping_correctly(window, qapp, tmp_path):
    good, scanned, bad = _run_mixed_batch(window, qapp, tmp_path)
    scanned_markdown_before = window._markdown.get(window._files.index(scanned))

    window.clear_completed()

    # After removing the Success row, retrying the remaining Error row must
    # still hit the right file - proves indices were remapped, not left stale.
    bad_new_index = window._files.index(bad)
    _write_valid_pdf(bad)
    run_batch(window, qapp, action=window.retry_failed)

    assert window._items[bad_new_index].text(COLUMN_STATUS) == STATUS_SUCCESS
    scanned_new_index = window._files.index(scanned)
    assert window._markdown.get(scanned_new_index) == scanned_markdown_before


def test_clear_completed_noop_when_nothing_succeeded(window, qapp, tmp_path):
    bad = _write_broken_pdf(tmp_path / "bad.pdf")
    window.add_paths([bad])
    run_batch(window, qapp)

    assert not window.clear_completed_button.isEnabled()
    window.clear_completed()
    assert window.file_tree.topLevelItemCount() == 1


def test_clear_completed_removes_the_right_rows_around_a_skipped_folder_row(
    window, qapp, tmp_path
):
    """A skipped-folder explanation row is added straight to file_tree and
    never tracked in window._items - if a Success row is added AFTER that
    skip row lands, self._items and the tree's own top-level-item order
    diverge. Clear Completed must still remove exactly the Success rows
    (by identity), not whatever happens to sit at the same numeric position
    in the tree."""
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    a = make_txt(tmp_path, "a.txt", "A")
    b = make_txt(tmp_path, "b.txt", "B")
    window.add_paths([a, b])
    run_batch(window, qapp)

    already_converted = tmp_path / "already_converted"
    already_converted.mkdir()
    (already_converted / "old.md").write_text("# old", encoding="utf-8")
    window.add_paths([already_converted])
    deadline = QDeadlineTimer(10_000)
    while window._scan_thread is not None and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    broken = _write_broken_pdf(tmp_path / "bad.pdf")
    window.add_paths([broken])
    run_batch(window, qapp)

    window.clear_completed()

    remaining = [
        window.file_tree.topLevelItem(i).text(0)
        for i in range(window.file_tree.topLevelItemCount())
    ]
    assert "bad.pdf" in remaining, "the Error row must survive"
    assert any("already_converted" in name for name in remaining), (
        "the skip-row explanation must survive - it must never be deleted "
        "in place of an actual Success row"
    )
    assert "a.txt" not in remaining
    assert "b.txt" not in remaining


# --- clipboard/bridge only reflect the latest valid round ------------------------


def test_clipboard_excludes_content_from_a_failed_retry(window, qapp, tmp_path):
    bad = _write_broken_pdf(tmp_path / "bad.pdf")
    window.add_paths([bad])
    run_batch(window, qapp)

    run_batch(window, qapp, action=window.retry_failed)  # still broken - fails again

    assert window.copy_markdown(quiet=True) is False  # nothing valid to copy


def test_bridge_payload_excludes_a_row_currently_in_error_after_retry(window, qapp, tmp_path):
    good = make_txt(tmp_path, "good.txt", "GOODMARKER")
    bad = _write_broken_pdf(tmp_path / "bad.pdf")
    window.add_paths([good, bad])
    run_batch(window, qapp)

    run_batch(window, qapp, action=window.retry_failed)  # bad.pdf is still broken

    payload = window.build_bridge_payload()
    names = [doc.name for doc in payload.documents]
    assert "good" in names
    assert "bad" not in names


# --- export error report ---------------------------------------------------------


def test_export_error_report_disabled_with_no_errors(window, qapp, tmp_path):
    good = make_txt(tmp_path, "good.txt")
    window.add_paths([good])
    run_batch(window, qapp)

    assert not window.export_error_report_button.isEnabled()
    assert window.build_error_report() == []


def test_export_error_report_covers_every_error_row(window, qapp, tmp_path):
    good, scanned, bad = _run_mixed_batch(window, qapp, tmp_path)

    entries = window.build_error_report()

    assert len(entries) == 1
    assert entries[0]["status"] == STATUS_ERROR
    assert entries[0]["source"] == str(bad)


def test_export_error_report_writes_valid_json(window, qapp, tmp_path):
    good, scanned, bad = _run_mixed_batch(window, qapp, tmp_path)

    from doc2md.core.quality import write_report_atomic
    import json

    report_path = tmp_path / "errors.json"
    write_report_atomic(window.build_error_report(), report_path)

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["source"] == str(bad)


# --- worker: partial (indexed) batches -------------------------------------------


def test_worker_accepts_an_index_to_path_mapping_and_preserves_indices(tmp_path):
    """A retry gives the worker {original_row_index: path}; file_started/
    file_finished must fire with that ORIGINAL index, not a 0-based
    position in the subset."""
    f0 = make_txt(tmp_path, "f0.txt")
    f2 = make_txt(tmp_path, "f2.txt")
    worker = ConversionWorker({0: f0, 2: f2}, {}, timeout=30.0)

    started: list[int] = []
    worker.file_started.connect(lambda index, _name: started.append(index))
    worker.run()

    assert started == [0, 2]


def test_worker_still_accepts_a_plain_list_and_enumerates_from_zero(tmp_path):
    sources = [make_txt(tmp_path, f"g{i}.txt") for i in range(3)]
    worker = ConversionWorker(sources, {}, timeout=30.0)

    started: list[int] = []
    worker.file_started.connect(lambda index, _name: started.append(index))
    worker.run()

    assert started == [0, 1, 2]
