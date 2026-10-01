"""Milestone 4 - GUI OCR Setup Assistant: preset combo (with Custom
detection) and the OCR Diagnostics dialog.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from doc2md.core.presets import CUSTOM, PRESETS  # noqa: E402
from doc2md.gui import theme  # noqa: E402
from doc2md.gui.main_window import MainWindow  # noqa: E402
from doc2md.gui.ocr_dialog import OcrDiagnosticsDialog  # noqa: E402


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


def test_default_preset_is_balanced_ai(window):
    assert window.preset_combo.currentText() == "Balanced AI"
    assert window._current_preset_options() == PRESETS["Balanced AI"]


def test_selecting_a_preset_applies_its_options(window):
    index = window.preset_combo.findText("Thai Scanned Document")
    window.preset_combo.setCurrentIndex(index)

    assert window._current_preset_options() == PRESETS["Thai Scanned Document"]
    assert window.ocr_combo.currentText() == "Thai only"
    assert window.tables_check.isChecked() is True


def test_editing_ocr_language_by_hand_switches_to_custom(window):
    # Balanced AI is selected by default; English-only at 300 DPI with tables
    # matches no preset ("Thai only" now equals Thai Scanned Document).
    window.ocr_combo.setCurrentIndex(2)

    assert window.preset_combo.currentText() == CUSTOM


def test_editing_tables_checkbox_by_hand_switches_to_custom(window):
    window.tables_check.setChecked(not window.tables_check.isChecked())
    assert window.preset_combo.currentText() == CUSTOM


def test_editing_ocr_checkbox_by_hand_switches_to_custom(window):
    window.ocr_check.setChecked(not window.ocr_check.isChecked())
    assert window.preset_combo.currentText() == CUSTOM


def test_reselecting_a_matching_preset_after_a_hand_edit_is_not_custom(window):
    window.tables_check.setChecked(False)
    assert window.preset_combo.currentText() == CUSTOM

    fast_text_index = window.preset_combo.findText("Fast Text")
    window.preset_combo.setCurrentIndex(fast_text_index)

    assert window._current_preset_options() == PRESETS["Fast Text"]
    assert window.preset_combo.currentText() == "Fast Text"


def test_conversion_options_includes_the_preset_dpi(window):
    index = window.preset_combo.findText("High Fidelity")
    window.preset_combo.setCurrentIndex(index)

    assert window.conversion_options()["ocr_dpi"] == PRESETS["High Fidelity"]["ocr_dpi"]


# --- OCR diagnostics dialog ----------------------------------------------------
#
# diagnose() now always runs on a background QThread (Milestone 7 item 5) -
# never synchronously on the GUI thread, since constructing RapidOCR's
# engine can take real time. Every test here either checks the busy state
# BEFORE pumping the event loop, or pumps until the background run settles.


def _pump_until_settled(dialog, qapp, timeout_ms=10_000):
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(timeout_ms)
    while dialog._thread is not None and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    assert dialog._thread is None, "diagnostics did not finish within the timeout"


def test_show_ocr_diagnostics_opens_a_dialog_without_crashing(window, monkeypatch):
    from doc2md.gui import main_window as gui_main_window

    opened = {}

    class _FakeDialog:
        def __init__(self, parent=None):
            opened["created"] = True

        def exec(self):
            opened["executed"] = True

    monkeypatch.setattr(gui_main_window, "OcrDiagnosticsDialog", _FakeDialog)
    window.show_ocr_diagnostics()

    assert opened.get("created")
    assert opened.get("executed")


def test_dialog_shows_checking_state_immediately_not_frozen(qapp):
    """Right after construction (before the event loop is pumped at all),
    the dialog must show a busy state and have Refresh disabled - proving
    the diagnostic run did not happen synchronously in __init__."""
    dialog = OcrDiagnosticsDialog()
    try:
        from doc2md.gui.ocr_dialog import CHECKING_MESSAGE

        assert dialog.message_label.text() == CHECKING_MESSAGE
        assert dialog.refresh_button.isEnabled() is False
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_ocr_diagnostics_dialog_shows_the_real_readiness_message(qapp, monkeypatch):
    from doc2md.core import ocr_diagnostics as diag_module

    # Simulate an environment without RapidOCR for this test
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (False, None, None))

    dialog = OcrDiagnosticsDialog()
    try:
        _pump_until_settled(dialog, qapp)
        assert dialog.message_label.text()
        assert dialog.detail_view.toPlainText().strip() != ""
        # Simulated environment has no OCR backend.
        assert dialog.message_label.text() == "ยังไม่มี OCR backend"
        assert dialog.refresh_button.isEnabled() is True
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_ocr_diagnostics_dialog_refresh_rebuilds_the_report(qapp, monkeypatch):
    from doc2md.gui import ocr_dialog as ocr_dialog_module

    dialog = OcrDiagnosticsDialog()
    try:
        _pump_until_settled(dialog, qapp)

        calls = {"n": 0}
        real_diagnose = ocr_dialog_module.diagnose

        def counting_diagnose(*args, **kwargs):
            calls["n"] += 1
            return real_diagnose(*args, **kwargs)

        monkeypatch.setattr(ocr_dialog_module, "diagnose", counting_diagnose)
        dialog.refresh()
        _pump_until_settled(dialog, qapp)
        assert calls["n"] == 1
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_delayed_diagnostics_does_not_block_and_applies_when_ready(qapp, monkeypatch):
    """A slow diagnose() (e.g. RapidOCR loading real models) must not freeze
    anything - the busy state persists until the result genuinely arrives."""
    import time

    from doc2md.core import ocr_diagnostics as diag_module
    from doc2md.gui import ocr_dialog as ocr_dialog_module

    # Simulate an environment without RapidOCR for this test
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (False, None, None))

    real_diagnose = ocr_dialog_module.diagnose

    def slow_diagnose(*args, **kwargs):
        time.sleep(0.3)
        return real_diagnose(*args, **kwargs)

    monkeypatch.setattr(ocr_dialog_module, "diagnose", slow_diagnose)

    dialog = OcrDiagnosticsDialog()
    try:
        from doc2md.gui.ocr_dialog import CHECKING_MESSAGE

        # Immediately after construction the slow run has not returned yet.
        assert dialog.message_label.text() == CHECKING_MESSAGE
        _pump_until_settled(dialog, qapp)
        assert dialog.message_label.text() != CHECKING_MESSAGE
        assert dialog.message_label.text() == "ยังไม่มี OCR backend"
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_diagnostics_exception_is_reported_not_crashed(qapp, monkeypatch):
    from doc2md.gui import ocr_dialog as ocr_dialog_module

    def boom(*args, **kwargs):
        raise RuntimeError("simulated diagnostic crash")

    monkeypatch.setattr(ocr_dialog_module, "diagnose", boom)

    dialog = OcrDiagnosticsDialog()
    try:
        _pump_until_settled(dialog, qapp)
        assert "failed" in dialog.message_label.text().lower()
        assert "simulated diagnostic crash" in dialog.detail_view.toPlainText()
        assert dialog.refresh_button.isEnabled() is True
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_repeated_refresh_while_running_does_not_start_a_second_run(qapp, monkeypatch):
    import time

    from doc2md.gui import ocr_dialog as ocr_dialog_module

    real_diagnose = ocr_dialog_module.diagnose
    calls = {"n": 0}

    def counting_slow_diagnose(*args, **kwargs):
        calls["n"] += 1
        time.sleep(0.3)
        return real_diagnose(*args, **kwargs)

    monkeypatch.setattr(ocr_dialog_module, "diagnose", counting_slow_diagnose)

    dialog = OcrDiagnosticsDialog()
    try:
        # Fired immediately, before the background thread has necessarily
        # even started running diagnose() yet - these must still be no-ops
        # rather than queuing additional runs, since a thread is already
        # in flight (self._thread is not None) the moment __init__ set it up.
        dialog.refresh()
        dialog.refresh()
        dialog.refresh_button.click()  # also exercise the actual button path

        _pump_until_settled(dialog, qapp)
        assert calls["n"] == 1, "a run already in flight must not be duplicated"
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_late_result_ignored_after_dialog_closed(qapp, monkeypatch):
    """Closing the dialog while a diagnostic is still running must not
    crash when the result eventually arrives, and must not apply that
    result to widgets that are considered gone."""
    import time

    from doc2md.gui import ocr_dialog as ocr_dialog_module
    from doc2md.gui.ocr_dialog import CHECKING_MESSAGE

    real_diagnose = ocr_dialog_module.diagnose

    def slow_diagnose(*args, **kwargs):
        time.sleep(0.3)
        return real_diagnose(*args, **kwargs)

    monkeypatch.setattr(ocr_dialog_module, "diagnose", slow_diagnose)

    dialog = OcrDiagnosticsDialog()
    try:
        assert dialog.message_label.text() == CHECKING_MESSAGE
        dialog.reject()  # close while the background run is still in flight
        assert dialog._closed is True

        # Let the background thread genuinely finish and emit its signal.
        from PyQt6.QtCore import QDeadlineTimer, QEventLoop

        deadline = QDeadlineTimer(5_000)
        while dialog._thread is not None and not deadline.hasExpired():
            qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

        # The late result must have been ignored, not applied.
        assert dialog.message_label.text() == CHECKING_MESSAGE
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_unknown_language_state_shown_distinctly_in_dialog(qapp, monkeypatch):
    from doc2md.gui import ocr_dialog as ocr_dialog_module
    from doc2md.core.ocr_diagnostics import OcrDiagnostics

    crafted = OcrDiagnostics(
        tesseract_found=True,
        tesseract_path="C:/fake/tesseract.exe",
        pytesseract_installed=True,
        tesseract_languages=None,
        active_backend="tesseract",
        thai_ready=None,
        english_ready=None,
        readiness_message="พบ Tesseract แต่ไม่ทราบภาษาที่พร้อมใช้งาน",
        detail_lines=["พบ Tesseract binary ที่ C:/fake/tesseract.exe"],
    )
    monkeypatch.setattr(ocr_dialog_module, "diagnose", lambda *a, **k: crafted)

    dialog = OcrDiagnosticsDialog()
    try:
        _pump_until_settled(dialog, qapp)
        assert dialog.message_label.text() == "พบ Tesseract แต่ไม่ทราบภาษาที่พร้อมใช้งาน"
        assert "ยังไม่มี OCR backend" not in dialog.message_label.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


def test_copy_diagnostics_puts_the_report_on_the_clipboard(qapp):
    dialog = OcrDiagnosticsDialog()
    try:
        _pump_until_settled(dialog, qapp)
        assert dialog.copy_diagnostics() is True
        clipboard = QApplication.clipboard()
        assert dialog._diagnostics.readiness_message in clipboard.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()


# --- one-click OCR install --------------------------------------------------


def _wait(qapp, predicate, timeout_ms=10_000):
    from PyQt6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(timeout_ms)
    while not predicate() and not deadline.hasExpired():
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    assert predicate()


def test_install_button_runs_the_installer_then_rechecks_readiness(qapp, monkeypatch):
    from doc2md.core.ocr_diagnostics import OcrDiagnostics
    from doc2md.core.ocr_setup import SetupResult
    from doc2md.gui import ocr_dialog

    progress_seen = []
    diagnoses = []

    def fake_install(progress):
        progress("Installing Tesseract...")
        progress_seen.append(1)
        return SetupResult(ok=True, steps=["Installing Tesseract...", "Verified: ok"])

    def fake_diagnose(**_kwargs):
        diagnoses.append(1)
        return OcrDiagnostics(readiness_message="ready after install")

    monkeypatch.setattr(ocr_dialog, "install_ocr", fake_install)
    monkeypatch.setattr(ocr_dialog, "diagnose", fake_diagnose)
    dialog = OcrDiagnosticsDialog()
    _wait(qapp, lambda: dialog._thread is None)
    monkeypatch.setattr(dialog, "_confirm_install", lambda: True)
    before = len(diagnoses)

    assert dialog.install() is True
    assert not dialog.install_button.isEnabled()
    _wait(qapp, lambda: not dialog._installing and dialog._thread is None and len(diagnoses) > before)

    assert progress_seen
    assert dialog.message_label.text() == "ready after install"
    assert dialog.install_button.isEnabled()
    dialog.done(0)


def test_install_is_not_started_when_the_user_declines(qapp, monkeypatch):
    from doc2md.gui import ocr_dialog

    calls = []
    monkeypatch.setattr(ocr_dialog, "install_ocr", lambda progress: calls.append(1))
    dialog = OcrDiagnosticsDialog()
    _wait(qapp, lambda: dialog._thread is None)
    monkeypatch.setattr(dialog, "_confirm_install", lambda: False)

    assert dialog.install() is False
    assert calls == []
    dialog.done(0)


def test_a_failed_install_shows_the_reason(qapp, monkeypatch):
    from doc2md.core.ocr_setup import SetupResult
    from doc2md.gui import ocr_dialog

    monkeypatch.setattr(
        ocr_dialog, "install_ocr",
        lambda progress: SetupResult(ok=False, steps=["step one"], error="winget is not available"),
    )
    dialog = OcrDiagnosticsDialog()
    _wait(qapp, lambda: dialog._thread is None)
    monkeypatch.setattr(dialog, "_confirm_install", lambda: True)

    dialog.install()
    _wait(qapp, lambda: not dialog._installing)

    assert "did not complete" in dialog.message_label.text()
    assert "winget is not available" in dialog.detail_view.toPlainText()
    dialog.done(0)


def test_the_dialog_cannot_be_closed_while_installing(qapp, monkeypatch):
    import threading

    from doc2md.core.ocr_setup import SetupResult
    from doc2md.gui import ocr_dialog

    release = threading.Event()
    monkeypatch.setattr(
        ocr_dialog, "install_ocr", lambda progress: (release.wait(10), SetupResult(ok=True))[1]
    )
    dialog = OcrDiagnosticsDialog()
    _wait(qapp, lambda: dialog._thread is None)
    monkeypatch.setattr(dialog, "_confirm_install", lambda: True)
    dialog.install()

    dialog.done(0)
    assert not dialog._closed

    release.set()
    _wait(qapp, lambda: not dialog._installing)
    dialog.done(0)
    assert dialog._closed
