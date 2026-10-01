"""OCR Setup Assistant dialog: real readiness diagnostics, not a guess.

Every fact shown here comes from :func:`doc2md.core.ocr_diagnostics.diagnose`
- a package import succeeding is never presented as "Ready". Running it can
take real time (constructing RapidOCR's engine loads its bundled ONNX
models), so it always runs on a background ``QThread`` - never synchronously
on the GUI thread, which would freeze the whole application while it runs.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from doc2md.core.ocr_diagnostics import OcrDiagnostics, diagnose
from doc2md.core.ocr_setup import SetupResult, install_ocr

CHECKING_MESSAGE = "Checking OCR backends…"


class _DiagnosticsWorker(QObject):
    """Runs `diagnose()` off the GUI thread. Touches no Qt widgets itself -
    only ever reports back through signals, which Qt queues onto the
    receiver's own thread."""

    succeeded = pyqtSignal(object)  # OcrDiagnostics
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            result = diagnose()
        except Exception as exc:  # pragma: no cover - diagnose() is defensive
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(result)


class _InstallWorker(QObject):
    """Runs :func:`install_ocr` off the GUI thread, reporting through signals."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)  # SetupResult

    def run(self) -> None:
        try:
            result = install_ocr(self.progress.emit)
        except Exception as exc:  # pragma: no cover - install_ocr reports its own errors
            result = SetupResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        self.finished.emit(result)


INSTALL_CONFIRMATION = (
    "doc2md will install Tesseract OCR with the winget package manager (about 70 MB) "
    "and download the Thai and English language data (a few MB) from GitHub.\n\n"
    "Windows may ask you to approve the installation as administrator.\n\nContinue?"
)


class OcrDiagnosticsDialog(QDialog):
    """Modal dialog showing Tesseract/RapidOCR readiness with Refresh and
    Copy Diagnostics actions.

    Crash/lifecycle semantics: each `refresh()` call is tagged with a
    monotonically increasing request id. A background run's result is only
    applied to the UI if (a) the dialog has not been closed since the run
    started, and (b) no newer `refresh()` has superseded it - so a slow,
    late-arriving result from a stale request can never clobber what a
    faster, more recent one already showed.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OCR Diagnostics")
        self.resize(560, 420)

        self._diagnostics: OcrDiagnostics | None = None
        self._thread: QThread | None = None
        self._worker: _DiagnosticsWorker | None = None
        self._request_id = 0
        self._closed = False
        self._installing = False
        self._install_thread: QThread | None = None
        self._install_worker: _InstallWorker | None = None

        layout = QVBoxLayout(self)
        self.message_label = QLabel()
        self.message_label.setObjectName("Title")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.detail_view = QPlainTextEdit()
        self.detail_view.setReadOnly(True)
        layout.addWidget(self.detail_view, 1)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.copy_button = QPushButton("Copy Diagnostics")
        self.copy_button.clicked.connect(self.copy_diagnostics)
        self.install_button = QPushButton("Install OCR (Thai + English)…")
        self.install_button.setToolTip(
            "Install Tesseract OCR and the Thai/English language data for you"
        )
        self.install_button.clicked.connect(self.install)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.install_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.refresh()

    # ------------------------------------------------------------- running

    def refresh(self) -> None:
        if self._thread is not None:
            return  # a run is already in flight - the button is disabled
            # anyway, but this guards direct calls (e.g. from tests) too.

        self._request_id += 1
        my_request = self._request_id

        self.message_label.setText(CHECKING_MESSAGE)
        self.detail_view.setPlainText("")
        self.refresh_button.setEnabled(False)

        self._thread = QThread()
        self._worker = _DiagnosticsWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.succeeded.connect(lambda diag: self._on_succeeded(my_request, diag))
        self._worker.failed.connect(lambda msg: self._on_failed(my_request, msg))
        self._worker.succeeded.connect(self._teardown_thread)
        self._worker.failed.connect(self._teardown_thread)
        self._thread.start()

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None
        if not self._closed:
            try:
                self.refresh_button.setEnabled(True)
            except RuntimeError:
                # the underlying Qt widget was already destroyed between the
                # closed-check above and this call - never fatal here.
                pass

    def _on_succeeded(self, request_id: int, diagnostics: OcrDiagnostics) -> None:
        if request_id != self._request_id or self._closed:
            return  # stale result, or the dialog is gone - ignore silently
        self._diagnostics = diagnostics
        self.message_label.setText(diagnostics.readiness_message)
        self.detail_view.setPlainText("\n".join(diagnostics.detail_lines))

    def _on_failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id or self._closed:
            return
        self.message_label.setText("OCR diagnostics failed to run.")
        self.detail_view.setPlainText(message)

    # ------------------------------------------------------------- install

    def _confirm_install(self) -> bool:
        answer = QMessageBox.question(self, "Install OCR", INSTALL_CONFIRMATION)
        return answer == QMessageBox.StandardButton.Yes

    def install(self) -> bool:
        """Install Tesseract and the language data; returns False if it did not start."""
        if self._installing or self._thread is not None:
            return False
        if not self._confirm_install():
            return False
        self._installing = True
        for button in (self.install_button, self.refresh_button, self.copy_button):
            button.setEnabled(False)
        self.message_label.setText("Installing OCR - please wait…")
        self.detail_view.setPlainText("")

        self._install_thread = QThread()
        self._install_worker = _InstallWorker()
        self._install_worker.moveToThread(self._install_thread)
        self._install_thread.started.connect(self._install_worker.run)
        self._install_worker.progress.connect(self._on_install_progress)
        self._install_worker.finished.connect(self._on_install_finished)
        self._install_thread.start()
        return True

    def _on_install_progress(self, message: str) -> None:
        if not self._closed:
            self.detail_view.appendPlainText(message)

    def _on_install_finished(self, result: SetupResult) -> None:
        if self._install_thread is not None:
            self._install_thread.quit()
            self._install_thread.wait()
            self._install_thread.deleteLater()
        if self._install_worker is not None:
            self._install_worker.deleteLater()
        self._install_thread = None
        self._install_worker = None
        self._installing = False
        if self._closed:
            return
        for button in (self.install_button, self.refresh_button, self.copy_button):
            button.setEnabled(True)
        self.message_label.setText(
            "OCR is installed and ready." if result.ok else "OCR installation did not complete."
        )
        self.detail_view.setPlainText(result.summary())
        if result.ok:
            self.refresh()

    # -------------------------------------------------------------- other

    def copy_diagnostics(self) -> bool:
        if self._diagnostics is None:
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:  # pragma: no cover - headless only
            return False
        clipboard.setText(self._diagnostics.as_text())
        return True

    def done(self, result: int) -> None:  # noqa: N802 - Qt naming
        # Single override point for accept()/reject()/the window's close
        # button (QDialog routes all three through done()): marks the
        # dialog closed so any diagnostics result still in flight is
        # ignored rather than touching widgets that may no longer exist.
        # The background thread, if still running, is left to finish
        # naturally - diagnose() touches no Qt objects, so there is nothing
        # unsafe about letting it complete after the dialog is gone; only
        # its result is discarded.
        if self._installing:
            self.message_label.setText("Installing OCR - please wait until it finishes…")
            return
        self._closed = True
        super().done(result)
