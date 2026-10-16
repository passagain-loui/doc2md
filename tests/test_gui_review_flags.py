"""Review flags in the GUI (1.5.0): clean Markdown, flags travel beside it.

Covers the preview highlights and hover tooltip, the Next/Previous navigator,
the "Flag uncertain OCR lines in output" toggle, and that every output path
(copy, combined export, per-file export) follows it while the bridge payload
never does. Real ``MainWindow`` on the offscreen platform, never ``show()``n;
the blocking ``QMessageBox`` / ``QFileDialog`` calls are always stubbed.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QEvent, QSettings  # noqa: E402
from PyQt6.QtGui import QGuiApplication, QHelpEvent, QTextCursor  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from doc2md.core.converter import ConversionResult  # noqa: E402
from doc2md.core.review import ReviewLine  # noqa: E402
from doc2md.gui import main_window as mw  # noqa: E402
from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import MainWindow  # noqa: E402

MARKDOWN = "# Invoice\n\nTotal 1,250\nDue date 31/12\n\nThanks"
#            0         1  2           3              4  5
REVIEW = [ReviewLine(2, 58, "Total 1,250"), ReviewLine(3, 71, "Due date 31/12")]
FLAGGED_MARKDOWN = "# Invoice\n\nTotal 1,250 ⚠58%\nDue date 31/12 ⚠71%\n\nThanks"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.STYLESHEET)
    yield app


@pytest.fixture
def settings_path(tmp_path):
    return str(tmp_path / "settings.ini")


@pytest.fixture
def window(qapp, tmp_path, settings_path, monkeypatch):
    # A refusal path must never block the headless run on a modal box.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    win = MainWindow(settings=QSettings(settings_path, QSettings.Format.IniFormat))
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def feed(window, tmp_path, name, markdown, review=(), warning="", quality_lines=None):
    """Add *name* to the queue and deliver a finished result for it."""
    path = tmp_path / name
    path.write_text("x", encoding="utf-8")
    window.add_paths([path])
    index = len(window._files) - 1
    result = ConversionResult(
        source=path,
        success=True,
        markdown=markdown,
        warning=warning or None,
        review_lines=list(review),
    )
    if quality_lines is not None:
        result.quality.ocr_backend = "tesseract"
        result.quality.ocr_review_lines = quality_lines
    window._on_file_finished(index, True, markdown, "", warning, result)
    return index


def select(window, index):
    window.file_tree.setCurrentItem(window._items[index])


def blocks_highlighted(window):
    return sorted(s.cursor.blockNumber() for s in window.preview.extraSelections())


# --- preview highlighting ----------------------------------------------------


def test_preview_highlights_exactly_the_review_lines(window, tmp_path):
    index = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    select(window, index)

    assert blocks_highlighted(window) == [2, 3]


def test_preview_text_stays_clean(window, tmp_path):
    index = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    select(window, index)

    assert window.preview.toPlainText() == MARKDOWN
    assert "⚠" not in window.preview.toPlainText()


def test_highlight_is_full_width_amber_from_the_theme(window, tmp_path):
    from PyQt6.QtGui import QTextFormat

    index = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    select(window, index)

    fmt = window.preview.extraSelections()[0].format
    assert fmt.property(QTextFormat.Property.FullWidthSelection) is True
    assert fmt.background().color().getRgb() == theme.REVIEW_HIGHLIGHT_RGBA


def test_no_highlights_for_a_row_without_review_lines(window, tmp_path):
    index = feed(window, tmp_path, "a.txt", MARKDOWN)
    select(window, index)

    assert window.preview.extraSelections() == []


def test_review_line_outside_the_text_is_ignored(window, tmp_path):
    review = [ReviewLine(2, 58, "Total"), ReviewLine(99, 40, "ghost")]
    index = feed(window, tmp_path, "a.txt", MARKDOWN, review)
    select(window, index)

    assert blocks_highlighted(window) == [2]
    assert window.review_chip.text() == "⚠ 1 line to review"


def test_highlights_follow_the_selected_row(window, tmp_path):
    flagged = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    plain = feed(window, tmp_path, "b.txt", "just text")

    select(window, flagged)
    assert blocks_highlighted(window) == [2, 3]
    select(window, plain)
    assert blocks_highlighted(window) == []
    select(window, flagged)
    assert blocks_highlighted(window) == [2, 3]


# --- tooltip -----------------------------------------------------------------


def test_tooltip_text_for_flagged_and_unflagged_blocks(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))

    assert window._review_tooltip_text(2) == (
        "OCR confidence 58% — check this line against the original"
    )
    assert window._review_tooltip_text(3) == (
        "OCR confidence 71% — check this line against the original"
    )
    assert window._review_tooltip_text(0) is None
    assert window._review_tooltip_text(5) is None


def _hover(window, block):
    """Deliver a real ToolTip QHelpEvent over *block* through the event filter."""
    viewport = window.preview.viewport()
    cursor = QTextCursor(window.preview.document().findBlockByNumber(block))
    point = window.preview.cursorRect(cursor).center()
    event = QHelpEvent(QEvent.Type.ToolTip, point, viewport.mapToGlobal(point))
    handled = window.eventFilter(viewport, event)
    return handled, event


def test_event_filter_shows_the_tooltip_over_a_flagged_line(window, tmp_path, monkeypatch):
    shown, hidden = [], []
    monkeypatch.setattr(
        mw,
        "QToolTip",
        SimpleNamespace(
            showText=lambda pos, text, widget=None: shown.append(text),
            hideText=lambda: hidden.append(True),
        ),
    )
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))

    handled, _event = _hover(window, 2)

    assert handled is True
    assert shown == ["OCR confidence 58% — check this line against the original"]
    assert not hidden


def test_event_filter_hides_the_tooltip_over_a_normal_line(window, tmp_path, monkeypatch):
    shown, hidden = [], []
    monkeypatch.setattr(
        mw,
        "QToolTip",
        SimpleNamespace(
            showText=lambda pos, text, widget=None: shown.append(text),
            hideText=lambda: hidden.append(True),
        ),
    )
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))

    handled, event = _hover(window, 0)

    assert handled is True
    assert not shown
    assert hidden
    assert not event.isAccepted()


def test_event_filter_ignores_other_widgets(window):
    event = QEvent(QEvent.Type.ToolTip)
    assert window.eventFilter(window.output_edit, event) is False


# --- navigator ---------------------------------------------------------------


def test_navigator_hidden_with_nothing_selected(window):
    assert window.review_nav.isHidden()


def test_navigator_hidden_for_a_row_without_review_lines(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN))

    assert window.review_nav.isHidden()


def test_navigator_shows_count_for_a_flagged_row(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))

    assert not window.review_nav.isHidden()
    assert window.review_chip.text() == "⚠ 2 lines to review"


def test_navigator_hides_again_when_selection_is_reset(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))
    window.clear_files()

    assert window.review_nav.isHidden()
    assert window._flagged_order == []


def test_next_walks_the_flagged_lines_and_wraps(window, tmp_path):
    review = REVIEW + [ReviewLine(5, 40, "Thanks")]
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, review))
    assert window.review_chip.text() == "⚠ 3 lines to review"

    seen = []
    for _ in range(4):
        window.review_next_button.click()
        seen.append((window.preview.textCursor().blockNumber(), window.review_chip.text()))

    assert seen == [(2, "⚠ 1 / 3"), (3, "⚠ 2 / 3"), (5, "⚠ 3 / 3"), (2, "⚠ 1 / 3")]


def test_next_selects_the_flagged_line(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))

    window.review_next_button.click()

    assert window.preview.textCursor().selectedText() == "Total 1,250"


def test_next_does_not_skip_a_flagged_first_line(window, tmp_path):
    review = [ReviewLine(0, 50, "# Invoice"), ReviewLine(3, 71, "Due")]
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, review))

    window.review_next_button.click()
    assert window.preview.textCursor().blockNumber() == 0
    window.review_next_button.click()
    assert window.preview.textCursor().blockNumber() == 3


def test_next_continues_after_the_cursor_the_user_placed(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))
    cursor = QTextCursor(window.preview.document().findBlockByNumber(4))
    window.preview.setTextCursor(cursor)

    window.review_next_button.click()

    # Nothing flagged after block 4: wraps to the first one.
    assert window.preview.textCursor().blockNumber() == 2


def test_previous_walks_backwards_and_wraps(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))

    window.review_prev_button.click()
    assert window.preview.textCursor().blockNumber() == 3
    window.review_prev_button.click()
    assert window.preview.textCursor().blockNumber() == 2
    window.review_prev_button.click()
    assert window.preview.textCursor().blockNumber() == 3


def test_goto_review_line_is_a_noop_without_flags(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN))

    assert window.goto_review_line(1) is False


def test_chip_reverts_to_the_count_when_cursor_leaves_a_flag(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW))
    window.review_next_button.click()
    assert window.review_chip.text() == "⚠ 1 / 2"

    window.preview.setTextCursor(QTextCursor(window.preview.document().findBlockByNumber(0)))

    assert window.review_chip.text() == "⚠ 2 lines to review"


# --- quality summary ---------------------------------------------------------


def test_quality_summary_says_lines_to_review(window, tmp_path):
    select(window, feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW, quality_lines=2))

    detail = window.quality_detail.text()
    assert "2 line(s) to review" in detail
    assert "⚠" not in detail


# --- output toggle -----------------------------------------------------------


def test_toggle_defaults_off_with_the_right_text(window):
    assert window.mark_uncertain_check.text() == "Flag uncertain OCR lines in output"
    assert window.mark_uncertain_check.isChecked() is False
    assert window.mark_uncertain_check.toolTip()


def test_toggle_is_persisted_across_windows(qapp, window, settings_path):
    window.mark_uncertain_check.setChecked(True)

    reopened = MainWindow(settings=QSettings(settings_path, QSettings.Format.IniFormat))
    try:
        assert reopened.mark_uncertain_check.isChecked() is True
        reopened.mark_uncertain_check.setChecked(False)
    finally:
        reopened.close()
        reopened.deleteLater()

    third = MainWindow(settings=QSettings(settings_path, QSettings.Format.IniFormat))
    try:
        assert third.mark_uncertain_check.isChecked() is False
    finally:
        third.close()
        third.deleteLater()


def test_toggle_is_stored_under_output_mark_uncertain(window, settings_path):
    window.mark_uncertain_check.setChecked(True)

    stored = QSettings(settings_path, QSettings.Format.IniFormat)
    assert stored.value("output/mark_uncertain", False, type=bool) is True


def test_collected_markdown_is_clean_by_default(window, tmp_path):
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    feed(window, tmp_path, "b.txt", "second")

    assert window.collected_markdown() == MARKDOWN + "\n\n---\n\n" + "second"


def test_collected_markdown_is_flagged_when_toggled_on(window, tmp_path):
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    feed(window, tmp_path, "b.txt", "second")
    window.mark_uncertain_check.setChecked(True)

    assert window.collected_markdown() == FLAGGED_MARKDOWN + "\n\n---\n\n" + "second"


def test_copy_markdown_follows_the_toggle(window, tmp_path):
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)

    assert window.copy_markdown(quiet=True)
    assert QGuiApplication.clipboard().text() == MARKDOWN
    window.mark_uncertain_check.setChecked(True)
    assert window.copy_markdown(quiet=True)
    assert QGuiApplication.clipboard().text() == FLAGGED_MARKDOWN


def test_copy_selected_follows_the_toggle(window, tmp_path):
    index = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    select(window, index)

    assert window.copy_selected_markdown()
    assert QGuiApplication.clipboard().text() == MARKDOWN
    window.mark_uncertain_check.setChecked(True)
    assert window.copy_selected_markdown()
    assert QGuiApplication.clipboard().text() == FLAGGED_MARKDOWN


def test_preview_stays_clean_whatever_the_toggle_says(window, tmp_path):
    index = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    window.mark_uncertain_check.setChecked(True)
    select(window, index)

    assert window.preview.toPlainText() == MARKDOWN
    assert blocks_highlighted(window) == [2, 3]


def test_export_each_file_follows_the_toggle(window, tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)

    assert window.export_each_file()
    assert (out / "a.md").read_text(encoding="utf-8") == MARKDOWN

    window.mark_uncertain_check.setChecked(True)
    assert window.export_each_file()
    written = sorted(p for p in out.glob("*.md") if p.name != "a.md")
    assert len(written) == 1
    assert written[0].read_text(encoding="utf-8") == FLAGGED_MARKDOWN


def test_combined_export_follows_the_toggle(window, tmp_path, monkeypatch):
    target = tmp_path / "combined.md"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), "Markdown (*.md)")
    )
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)

    assert window.export_content()
    assert target.read_text(encoding="utf-8") == MARKDOWN

    window.mark_uncertain_check.setChecked(True)
    assert window.export_content()
    assert target.read_text(encoding="utf-8") == FLAGGED_MARKDOWN


def test_bridge_payload_is_always_clean(window, tmp_path):
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)

    assert [d.markdown for d in window.build_bridge_payload().documents] == [MARKDOWN]
    window.mark_uncertain_check.setChecked(True)
    assert [d.markdown for d in window.build_bridge_payload().documents] == [MARKDOWN]


# --- review lines kept in lockstep with the Markdown -------------------------


def test_review_lines_are_stored_per_row(window, tmp_path):
    a = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)
    b = feed(window, tmp_path, "b.txt", "plain")

    assert window._review[a] == REVIEW
    assert window._review[b] == []


def test_failed_file_stores_no_review_lines(window, tmp_path):
    path = tmp_path / "bad.txt"
    path.write_text("x", encoding="utf-8")
    window.add_paths([path])

    window._on_file_finished(0, False, "", "boom", "", None)

    assert 0 not in window._review


def test_clear_files_drops_review_lines(window, tmp_path):
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)

    window.clear_files()

    assert window._review == {}


def test_clear_completed_remaps_review_lines(window, tmp_path):
    ok = feed(window, tmp_path, "ok.txt", MARKDOWN, REVIEW)  # Success: removed
    kept = feed(window, tmp_path, "warn.txt", MARKDOWN, [REVIEW[0]], warning="partial")
    assert (ok, kept) == (0, 1)

    window.clear_completed()

    assert list(window._markdown) == [0]
    assert window._review == {0: [REVIEW[0]]}
    window._on_row_selected(window._items[0], None)
    assert blocks_highlighted(window) == [2]


def test_retry_drops_the_stale_review_lines(window, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(window, "_run_conversion", lambda files: started.append(files))
    feed(window, tmp_path, "warn.txt", MARKDOWN, REVIEW, warning="partial")
    feed(window, tmp_path, "ok.txt", MARKDOWN, [REVIEW[1]])

    window.retry_warnings()

    assert started and list(started[0]) == [0]
    assert 0 not in window._review
    assert window._review[1] == [REVIEW[1]]


def test_start_conversion_drops_all_review_lines(window, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(window, "_run_conversion", lambda files: started.append(files))
    feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW)

    window.start_conversion()

    assert started
    assert window._review == {}
    assert window.review_nav.isHidden()
    assert window.preview.extraSelections() == []


def test_selected_row_refreshes_when_its_result_arrives(window, tmp_path):
    path = tmp_path / "late.txt"
    path.write_text("x", encoding="utf-8")
    window.add_paths([path])
    select(window, 0)
    assert window.review_nav.isHidden()

    result = ConversionResult(source=path, success=True, markdown=MARKDOWN, review_lines=REVIEW)
    window._on_file_finished(0, True, MARKDOWN, "", "", result)

    assert blocks_highlighted(window) == [2, 3]
    assert not window.review_nav.isHidden()


# --- theme -------------------------------------------------------------------


def test_stylesheet_styles_the_review_widgets(qapp):
    assert "QLabel#ReviewChip" in theme.STYLESHEET
    assert "QPushButton#ReviewNav" in theme.STYLESHEET


# --- preview toolbar layout --------------------------------------------------


def test_quality_detail_sits_on_its_own_line_under_the_toolbar(window):
    from PyQt6.QtWidgets import QHBoxLayout

    toolbar = window.quality_badge.parentWidget().layout().itemAt(1).layout()
    assert isinstance(toolbar, QHBoxLayout)
    members = [toolbar.itemAt(i).widget() for i in range(toolbar.count())]
    assert window.quality_detail not in members
    assert window.quality_badge in members
    assert window.review_nav in members
    assert window.quality_detail.parentWidget() is window.quality_badge.parentWidget()


def test_quality_detail_elides_when_narrow_but_keeps_full_text(window, tmp_path):
    index = feed(window, tmp_path, "a.txt", MARKDOWN, REVIEW, quality_lines=2)
    select(window, index)
    full = window.quality_detail.text()
    assert full.startswith("source ")

    window.quality_detail.resize(60, window.quality_detail.height())

    assert window.quality_detail.text() == full
    assert window.quality_detail.minimumSizeHint().width() == 0
    assert window.quality_detail.toolTip() == full


def test_review_nav_widgets_do_not_stretch(window):
    from PyQt6.QtWidgets import QSizePolicy

    for widget in (window.review_chip, window.review_prev_button, window.review_next_button):
        assert widget.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Fixed
