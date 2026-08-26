import subprocess
import sys
from pathlib import Path

import pytest

import doc2md.core.converter as conv_mod
from doc2md.core.converter import (
    Converter,
    _execute_payload,
    _isolated_convert_entry,
    _wait_for_worker,
)
from doc2md.core.errors import ConversionError, ConversionTimeoutError, EngineUnavailableError
from doc2md.engine import all_engines, engine_for_path, get_engine_by_name
from doc2md.engine.base import BaseEngine
from doc2md.engine.pdf_engine import PdfEngine
from tests.helpers import FakeEngine, StubProc, StubReceiver, StubSender

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_execute_payload_unknown_engine_raises():
    with pytest.raises(EngineUnavailableError):
        _execute_payload({"engine": "does-not-exist", "source": "x", "options": {}})


def test_isolated_entry_reports_ok_and_closes(tmp_path):
    p = tmp_path / "ok.txt"
    p.write_text("payload ok", encoding="utf-8")
    sender = StubSender()
    _isolated_convert_entry({"engine": "code", "source": str(p), "options": {}}, sender)
    assert sender.closed
    assert sender.sent[0][0] == "ok"
    assert "```text" in sender.sent[0][1]


def test_isolated_entry_reports_error_without_raising(tmp_path):
    sender = StubSender()
    _isolated_convert_entry(
        {"engine": "code", "source": str(tmp_path / "ghost.txt"), "options": {}}, sender
    )
    assert sender.sent[0][0] == "error"


def test_isolated_entry_survives_send_failure_but_still_closes(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x", encoding="utf-8")
    sender = StubSender(fail_send=True)
    _isolated_convert_entry({"engine": "code", "source": str(p), "options": {}}, sender)
    assert sender.closed


def test_isolated_entry_survives_close_failure():
    sender = StubSender(fail_send=True, fail_close=True)
    _isolated_convert_entry({"engine": "nope", "source": "x", "options": {}}, sender)
    assert not sender.closed


def test_wait_for_worker_timeout_then_kill_escalation(monkeypatch):
    proc = StubProc(alive=True, immortal=True)
    receiver = StubReceiver(poll_result=False)
    with pytest.raises(ConversionTimeoutError):
        _wait_for_worker(receiver, proc, "slow.bin", timeout=0.15)
    assert proc.terminated
    assert proc.killed
    assert receiver.closed


@pytest.mark.parametrize("exc", [EOFError("pipe gone"), OSError("broken pipe")])
def test_wait_for_worker_dead_pipe_becomes_conversion_error(exc):
    proc = StubProc(alive=False)
    receiver = StubReceiver(poll_result=True, recv_exc=exc)
    with pytest.raises(ConversionError) as caught:
        _wait_for_worker(receiver, proc, "crash.bin", timeout=2)
    assert "died unexpectedly" in str(caught.value)


def test_wait_for_worker_error_status_reraises_conversion_error():
    receiver = StubReceiver(value=("error", "ConversionError: inner failure"))
    out_exc = pytest.raises(ConversionError, _wait_for_worker,
                            receiver, StubProc(False), "e.bin", 2)
    assert "inner failure" in str(out_exc.value)


def test_wait_for_worker_ok_passthrough():
    receiver = StubReceiver(value=("ok", "# fine"))
    assert _wait_for_worker(receiver, StubProc(False), "ok.bin", 2) == "# fine"


def test_strict_mode_raises_on_unknown_type(tmp_path):
    blob = tmp_path / "blob.bin"
    blob.write_bytes(bytes(range(256)) * 8)
    with pytest.raises(ConversionError):
        Converter().convert_file(blob, strict=True)


def test_no_engine_registered_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(conv_mod, "get_engine", lambda kind: None)
    p = tmp_path / "note.txt"
    p.write_text("hi", encoding="utf-8")
    result = Converter().convert_file(p)
    assert not result.success
    assert "No engine registered" in result.error
    with pytest.raises(ConversionError):
        Converter().convert_file(p, strict=True)


def _install_fake_engine(monkeypatch, engine: FakeEngine):
    from doc2md.core.router import FileKind

    monkeypatch.setattr(conv_mod, "get_engine", lambda kind: engine)
    monkeypatch.setattr(conv_mod, "get_engine_by_name", lambda name: engine)


def test_strict_timeout_propagates(monkeypatch, tmp_path):
    _install_fake_engine(monkeypatch, FakeEngine("slow"))
    p = tmp_path / "slow.txt"
    p.write_text("s", encoding="utf-8")
    with pytest.raises(ConversionTimeoutError):
        Converter(timeout=0.3).convert_file(p, strict=True)


def test_nonstrict_timeout_packages_result(monkeypatch, tmp_path):
    _install_fake_engine(monkeypatch, FakeEngine("slow"))
    p = tmp_path / "slow.txt"
    p.write_text("s", encoding="utf-8")
    result = Converter(timeout=0.3).convert_file(p)
    assert not result.success
    assert "hard timeout" in result.error
    assert result.engine == "fake"


def test_keyboard_interrupt_always_propagates(monkeypatch, tmp_path):
    _install_fake_engine(monkeypatch, FakeEngine("keyboard"))
    p = tmp_path / "k.txt"
    p.write_text("k", encoding="utf-8")
    with pytest.raises(KeyboardInterrupt):
        Converter().convert_file(p)


def test_generic_exception_packaged_and_strict_raise(monkeypatch, tmp_path):
    _install_fake_engine(monkeypatch, FakeEngine("boom"))
    p = tmp_path / "b.txt"
    p.write_text("b", encoding="utf-8")
    result = Converter().convert_file(p)
    assert not result.success
    assert "RuntimeError: boom" == result.error
    with pytest.raises(RuntimeError):
        Converter().convert_file(p, strict=True)


def test_missing_file_strict_raises(tmp_path):
    with pytest.raises(ConversionError):
        Converter().convert_file(tmp_path / "missing.txt", strict=True)


def test_registry_helpers():
    assert len(all_engines()) >= 7
    assert get_engine_by_name("pdf").name == "pdf"
    assert get_engine_by_name("nope") is None
    assert isinstance(PdfEngine(), BaseEngine)


def test_engine_for_path_success_and_fallback(simple_pdf, tmp_path):
    engine, detection = engine_for_path(simple_pdf)
    assert engine.name == "pdf" and detection.kind.value == "pdf"
    blob = tmp_path / "mystery.bin"
    blob.write_bytes(bytes(range(256)) * 4)
    fallback_engine, fallback_detection = engine_for_path(blob)
    assert fallback_engine.name == "code"
    assert fallback_detection.kind.value == "unknown"


def test_engine_for_path_raises_when_kind_unregistered(monkeypatch, simple_pdf):
    from doc2md.core.router import FileKind
    import doc2md.engine as engine_pkg

    monkeypatch.setitem(engine_pkg._REGISTRY, FileKind.PDF, None)
    with pytest.raises(ConversionError):
        engine_for_path(simple_pdf)


def test_base_engine_repr():
    assert "pdf" in repr(PdfEngine())


def test_python_dash_m_entrypoints():
    for module in ("doc2md", "doc2md.cli.main"):
        proc = subprocess.run(
            [sys.executable, "-m", module, "--version"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0
        import re

        assert re.search(r"doc2md \d+\.\d+\.\d+", proc.stdout)
