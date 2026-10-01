"""Cancelling a conversion that is already running."""

from __future__ import annotations

import threading
import time

import pytest

from doc2md.core import converter as converter_module
from doc2md.core.converter import Converter
from doc2md.core.errors import ConversionCancelledError


class _Receiver:
    def poll(self, timeout=0):
        time.sleep(min(timeout, 0.02))
        return False

    def close(self):
        pass


class _Process:
    def __init__(self):
        self.terminated = False
        self._alive = True

    def is_alive(self):
        return self._alive

    def terminate(self):
        self.terminated = True
        self._alive = False

    def join(self, _timeout=None):
        pass

    def kill(self):
        self._alive = False


def test_a_worker_process_is_terminated_when_the_event_is_set():
    cancel = threading.Event()
    process = _Process()
    threading.Timer(0.2, cancel.set).start()
    started = time.monotonic()

    with pytest.raises(ConversionCancelledError):
        converter_module._wait_for_worker(_Receiver(), process, "big.pdf", 600.0, cancel)

    assert time.monotonic() - started < 3
    assert process.terminated


def test_a_thread_conversion_stops_waiting_when_the_event_is_set(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(converter_module, "_execute_payload", lambda payload: release.wait(10))
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    started = time.monotonic()

    try:
        with pytest.raises(ConversionCancelledError):
            converter_module._run_in_thread({"source": "x.xlsx"}, 600.0, cancel)
    finally:
        release.set()

    assert time.monotonic() - started < 3


def test_a_thread_engine_error_is_not_mistaken_for_still_running(monkeypatch):
    def fail(_payload):
        raise TimeoutError("engine's own timeout")

    monkeypatch.setattr(converter_module, "_execute_payload", fail)
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        converter_module._run_in_thread({"source": "x"}, 30.0, threading.Event())

    assert time.monotonic() - started < 3


def test_convert_file_reports_a_cancelled_result_without_starting_work(tmp_path):
    source = tmp_path / "a.txt"
    source.write_text("text", encoding="utf-8")
    cancel = threading.Event()
    cancel.set()

    result = Converter(timeout=30, cancel_event=cancel).convert_file(source)

    assert not result.success
    assert "cancelled" in result.error


def test_cancelling_a_real_pdf_conversion_returns_quickly(simple_pdf):
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    started = time.monotonic()

    result = Converter(timeout=120, cancel_event=cancel).convert_file(simple_pdf)

    assert not result.success
    assert "cancelled" in result.error
    assert time.monotonic() - started < 15


def test_a_large_spreadsheet_scan_checks_the_event(tmp_path):
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in range(3000):
        sheet.append([row, "x", "y"])
    path = tmp_path / "big.xlsx"
    workbook.save(path)
    cancel = threading.Event()
    cancel.set()

    from doc2md.engine.excel_engine import ExcelEngine

    with pytest.raises(ConversionCancelledError):
        ExcelEngine().convert(path, {"_cancel_event": cancel})
