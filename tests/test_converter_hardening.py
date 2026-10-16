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
    assert "```text" in sender.sent[0][1].markdown


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


class _SequenceReceiver:
    """Like StubReceiver, but recv() walks through a fixed list of messages -
    for exercising the progress-then-final-result loop in _wait_for_worker."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.closed = False

    def poll(self, timeout=None):
        return bool(self._messages)

    def recv(self):
        return self._messages.pop(0)

    def close(self):
        self.closed = True


def test_wait_for_worker_relays_progress_then_returns_final_result():
    seen = []
    receiver = _SequenceReceiver(
        [("progress", (1, 3)), ("progress", (2, 3)), ("ok", "# done")]
    )
    result = _wait_for_worker(
        receiver, StubProc(False), "scan.pdf", 2, on_progress=lambda c, t: seen.append((c, t))
    )
    assert result == "# done"
    assert seen == [(1, 3), (2, 3)]


def test_wait_for_worker_progress_callback_errors_do_not_abort_conversion():
    receiver = _SequenceReceiver([("progress", (1, 2)), ("ok", "# done")])

    def boom(current, total):
        raise RuntimeError("gui callback exploded")

    assert _wait_for_worker(receiver, StubProc(False), "x.pdf", 2, on_progress=boom) == "# done"


def test_wait_for_worker_without_progress_callback_ignores_progress_messages():
    receiver = _SequenceReceiver([("progress", (1, 2)), ("ok", "# done")])

    assert _wait_for_worker(receiver, StubProc(False), "x.pdf", 2) == "# done"


_captured_progress_options: dict = {}


def _record_progress_sender(source, options):
    from doc2md.core.quality import EngineOutput

    _captured_progress_options["sender"] = options.get("_progress_sender")
    return EngineOutput(markdown="# ok")


def test_isolated_entry_injects_progress_sender_when_requested(tmp_path):
    _captured_progress_options.clear()
    sender = StubSender()
    payload = {
        # __name__ rather than a hardcoded "tests.test_converter_hardening":
        # pytest's default "prepend" import mode (no tests/__init__.py)
        # loads this file as plain "test_converter_hardening", and importing
        # it a second time under the "tests." prefix inside
        # _execute_payload's importlib call would create a second module
        # object with its own, separately-mutated module-global dict.
        "target": (__name__, "_record_progress_sender"),
        "source": str(tmp_path / "x"),
        "options": {},
    }

    _isolated_convert_entry(payload, sender, report_progress=True)

    assert _captured_progress_options["sender"] is sender
    assert sender.sent[0][0] == "ok"


def test_isolated_entry_omits_progress_sender_by_default(tmp_path):
    _captured_progress_options.clear()
    sender = StubSender()
    payload = {
        "target": (__name__, "_record_progress_sender"),
        "source": str(tmp_path / "x"),
        "options": {},
    }

    _isolated_convert_entry(payload, sender)

    assert _captured_progress_options["sender"] is None


class _IsolatedStubEngine:
    """A minimal process-isolated engine stand-in - real PdfEngine/OcrEngine
    would require a real spawned subprocess (and, for OCR, a real Tesseract
    install) to exercise end to end; this proves Converter's own progress
    wiring without either."""

    name = "stub"
    requires_process_isolation = True

    def convert(self, source, options):
        return "# stub"

    def convert_structured(self, source, options):
        from doc2md.core.quality import EngineOutput

        return EngineOutput(markdown="# stub")


def test_converter_progress_callback_receives_source_and_page_counts(monkeypatch, tmp_path):
    from doc2md.core.quality import EngineOutput
    from doc2md.core.router import Detection, FileKind

    source = tmp_path / "scan.pdf"
    source.write_bytes(b"irrelevant - detect() is stubbed out below")

    captured = {}

    def fake_run_in_process(payload, timeout, cancel=None, on_progress=None):
        captured["on_progress"] = on_progress
        if on_progress is not None:
            on_progress(1, 3)
            on_progress(2, 3)
        return EngineOutput(markdown="# done")

    monkeypatch.setattr(conv_mod, "_run_in_process", fake_run_in_process)
    monkeypatch.setattr(
        conv_mod, "detect", lambda path: Detection(kind=FileKind.PDF, mime="application/pdf", confidence="high")
    )
    monkeypatch.setattr(conv_mod, "get_engine", lambda kind: _IsolatedStubEngine())

    seen = []
    result = Converter(
        progress_callback=lambda src, current, total: seen.append((src, current, total))
    ).convert_file(source)

    assert result.success is True
    assert captured["on_progress"] is not None
    assert seen == [(source, 1, 3), (source, 2, 3)]


def test_converter_without_progress_callback_passes_none_through(monkeypatch, tmp_path):
    from doc2md.core.quality import EngineOutput
    from doc2md.core.router import Detection, FileKind

    source = tmp_path / "scan.pdf"
    source.write_bytes(b"irrelevant - detect() is stubbed out below")

    captured = {}

    def fake_run_in_process(payload, timeout, cancel=None, on_progress=None):
        captured["on_progress"] = on_progress
        return EngineOutput(markdown="# done")

    monkeypatch.setattr(conv_mod, "_run_in_process", fake_run_in_process)
    monkeypatch.setattr(
        conv_mod, "detect", lambda path: Detection(kind=FileKind.PDF, mime="application/pdf", confidence="high")
    )
    monkeypatch.setattr(conv_mod, "get_engine", lambda kind: _IsolatedStubEngine())

    Converter().convert_file(source)

    assert captured["on_progress"] is None


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
