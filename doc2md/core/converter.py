"""Conversion orchestration: routing, hard watchdog timeouts, process isolation.

Resilience model
----------------
* Engines flagged ``requires_process_isolation`` (pdf, ocr) run in a dedicated
  **spawned worker process**. If the worker exceeds the deadline it is
  ``terminate()``d (then ``kill()``ed), so native crashes/hangs cannot take down
  the CLI.
* All other engines run in a daemon-thread executor with the same wall-clock
  deadline enforced from the caller side.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path

from doc2md.core import cleaner
from doc2md.core.errors import (
    ConversionError,
    ConversionTimeoutError,
    EngineUnavailableError,
    split_warning,
)
from doc2md.core.quality import EngineOutput, QualityMetrics
from doc2md.core.router import Detection, FileKind, detect
from doc2md.engine import get_engine, get_engine_by_name

DEFAULT_TIMEOUT_S = 60.0

# A scanned PDF rendered page-by-page through OCR is the only genuinely slow
# path left, and it is opt-in. Everything else finishes in well under a second.
OCR_TIMEOUT_S = 600.0

MEDIA_REMOVED_HINT = (
    "audio and video transcription was removed in doc2md 1.1.0; "
    "this build is a document converter only "
    "(PDF, DOCX, XLSX, CSV, PPTX, HTML, EML, images, code)"
)


@dataclass
class ConversionResult:
    source: Path
    success: bool = False
    markdown: str = ""
    error: str | None = None
    engine: str | None = None
    kind: str = FileKind.UNKNOWN.value
    duration_s: float = 0.0
    meta: dict = field(default_factory=dict)
    warning: str | None = None
    """Set when the conversion technically succeeded (there is output) but it
    does not represent the document's actual content - OCR unavailable, OCR
    switched off, or OCR completed with no readable text. Callers must treat
    this as distinct from a full Success, not fold it into the same status."""
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    """Structured extraction facts (pages, tables, rows, OCR outcome). Every
    field is ``None`` ("not measured") for engines that have not been
    migrated to :meth:`~doc2md.engine.base.BaseEngine.convert_structured`."""

    @property
    def token_estimate(self) -> int:
        from doc2md.core.tokens import estimate_tokens

        return estimate_tokens(self.markdown)


def _execute_payload(payload: dict) -> "str | EngineOutput":
    """Runs inside worker process OR worker thread."""
    target = payload.get("target")
    if target is not None:
        import importlib

        module_name, func_name = target
        func = getattr(importlib.import_module(module_name), func_name)
        return func(Path(payload["source"]), dict(payload["options"]))
    engine = get_engine_by_name(payload["engine"])
    if engine is None:
        raise EngineUnavailableError(f"Unknown engine {payload['engine']!r}")
    return engine.convert_structured(Path(payload["source"]), dict(payload["options"]))


def _isolated_convert_entry(payload: dict, sender) -> None:
    """Spawn-context entry point: never raises, reports over the pipe."""
    try:
        sender.send(("ok", _execute_payload(payload)))
    except BaseException as exc:
        try:
            sender.send(("error", f"{type(exc).__name__}: {exc}"))
        except Exception:
            pass
    finally:
        try:
            sender.close()
        except Exception:
            pass


def _wait_for_worker(receiver, proc, source: str, timeout: float) -> str:
    deadline = time.monotonic() + max(0.05, timeout)
    try:
        remaining = deadline - time.monotonic()
        if not receiver.poll(max(remaining, 0.05)):
            raise ConversionTimeoutError(
                f"{source}: conversion exceeded hard timeout "
                f"of {timeout:.0f}s and the worker was terminated"
            )
        try:
            status, value = receiver.recv()
        except (EOFError, OSError) as exc:
            raise ConversionError(
                f"{source}: worker process died unexpectedly ({exc})"
            ) from exc
        if status == "error":
            raise ConversionError(value)
        return value
    finally:
        if proc.is_alive():
            proc.terminate()
            proc.join(2)
            if proc.is_alive():
                proc.kill()
                proc.join(1)
        receiver.close()


def _run_in_process(payload: dict, timeout: float) -> str:
    ctx = get_context("spawn")
    receiver, sender = ctx.Pipe(False)
    proc = ctx.Process(
        target=_isolated_convert_entry,
        args=(payload, sender),
        name=f"doc2md-{Path(payload['source']).stem}",
        daemon=True,
    )
    proc.start()
    sender.close()
    return _wait_for_worker(receiver, proc, payload["source"], timeout)


def _run_in_thread(payload: dict, timeout: float) -> str:
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doc2md-worker")
    try:
        future = pool.submit(_execute_payload, payload)
        try:
            return future.result(timeout=max(0.05, timeout))
        except FuturesTimeoutError as exc:
            raise ConversionTimeoutError(
                f"{payload['source']}: conversion exceeded hard timeout "
                f"of {timeout:.0f}s (worker thread abandoned)"
            ) from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _picklable_options(options: dict) -> dict:
    """Drop option values that cannot cross a spawn boundary.

    Uses a real ``pickle.dumps`` probe rather than a type allowlist so any
    unpicklable value (bound methods, threading primitives, Tk widgets, open
    handles) is filtered regardless of how it was introduced.
    """
    import pickle

    safe: dict = {}
    for key, value in options.items():
        try:
            pickle.dumps(value)
        except Exception:
            continue
        safe[key] = value
    return safe


class Converter:
    """High-level facade: path in, clean Markdown out."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        options: dict | None = None,
    ) -> None:
        self.timeout = float(timeout)
        self.options: dict = dict(options or {})

    def convert_file(self, path: Path | str, *, strict: bool = False) -> ConversionResult:
        started = time.perf_counter()
        source = Path(path)
        detection: Detection = detect(source)

        if not source.is_file():
            result = ConversionResult(
                source=source,
                success=False,
                error=f"File not found: {source}",
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
            )
            if strict:
                raise ConversionError(result.error)
            return result

        if not detection.is_known:
            result = ConversionResult(
                source=source,
                success=False,
                error=(
                    f"Unrecognized file type for {source} "
                    "(no magic bytes, content heuristic, or known extension matched)"
                ),
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
            )
            if strict:
                raise ConversionError(result.error)
            return result

        if detection.kind is FileKind.MEDIA:
            result = ConversionResult(
                source=source,
                success=False,
                error=f"{source.name}: {MEDIA_REMOVED_HINT}",
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
            )
            if strict:
                raise ConversionError(result.error)
            return result

        engine = get_engine(detection.kind)
        if engine is None:
            result = ConversionResult(
                source=source,
                success=False,
                error=f"No engine registered for {detection.kind.value}",
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
            )
            if strict:
                raise ConversionError(result.error)
            return result

        # Options crossing a process boundary must survive pickling. GUI callers
        # legitimately put live objects in options (a bound progress_callback, a
        # threading.Event for cancellation); those are meaningless in a spawned
        # worker and raise at Process.start(), which previously made every
        # process-isolated conversion (PDF, OCR) fail outright when launched
        # from the GUI. Strip them for isolated engines and keep them for
        # in-thread engines, which share the caller's address space.
        options = dict(self.options)
        if engine.requires_process_isolation:
            options = _picklable_options(options)

        payload = {
            "engine": engine.name,
            "source": str(source),
            "options": options,
        }

        try:
            # A scanned PDF or a large image can legitimately spend minutes in
            # Tesseract; the default 60s ceiling would kill it mid-page.
            effective_timeout = self.timeout
            if engine.requires_process_isolation and options.get("pdf_ocr_fallback", True):
                effective_timeout = max(self.timeout, OCR_TIMEOUT_S)

            if engine.requires_process_isolation:
                raw_result = _run_in_process(payload, effective_timeout)
            else:
                raw_result = _run_in_thread(payload, effective_timeout)
            if isinstance(raw_result, EngineOutput):
                raw_markdown = raw_result.markdown
                quality = raw_result.metrics
            else:
                raw_markdown = raw_result
                quality = QualityMetrics()
            warning, raw_markdown = split_warning(raw_markdown)
            optimized = cleaner.optimize(raw_markdown)
            return ConversionResult(
                source=source,
                success=True,
                markdown=optimized,
                engine=engine.name,
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
                meta={"mime": detection.mime, "confidence": detection.confidence},
                warning=warning,
                quality=quality,
            )
        except ConversionTimeoutError as exc:
            if strict:
                raise
            return ConversionResult(
                source=source,
                success=False,
                error=str(exc),
                engine=engine.name,
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
            )
        except ConversionError as exc:
            if strict:
                raise
            return ConversionResult(
                source=source,
                success=False,
                error=str(exc),
                engine=engine.name,
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            if strict:
                raise
            return ConversionResult(
                source=source,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                engine=engine.name,
                kind=detection.kind.value,
                duration_s=time.perf_counter() - started,
            )

    def convert_many(self, paths) -> "list[ConversionResult]":
        return [self.convert_file(p) for p in paths]
