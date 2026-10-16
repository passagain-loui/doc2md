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
from concurrent.futures import wait as futures_wait
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path

from doc2md.core import cleaner, review
from doc2md.core.errors import (
    ConversionCancelledError,
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
    review_lines: list = field(default_factory=list)
    """:class:`~doc2md.core.review.ReviewLine` entries - lines of ``markdown``
    that OCR kept but was unsure about. ``markdown`` itself never carries a
    flag; see :mod:`doc2md.core.review`."""

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


def _isolated_convert_entry(payload: dict, sender, report_progress: bool = False) -> None:
    """Spawn-context entry point: never raises, reports over the pipe.

    When *report_progress* is set, the very same ``sender`` the final
    result is sent over is also handed to the engine (as
    ``options["_progress_sender"]``) so a page loop deep inside it (PDF OCR)
    can send ``("progress", (current, total))`` messages before the final
    ``("ok"|"error", ...)`` one. This mutation happens entirely inside the
    already-spawned child process - *payload* was already pickled across
    the process boundary by ``multiprocessing`` itself to get here, so
    adding a live Connection to it now never needs to survive a second
    pickling pass the way a value placed in it back in the parent would.
    """
    try:
        if report_progress:
            payload = dict(payload)
            payload["options"] = {**payload["options"], "_progress_sender": sender}
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


_CANCEL_POLL_S = 0.1


def _wait_for_worker(
    receiver, proc, source: str, timeout: float, cancel=None, on_progress=None
) -> str:
    deadline = time.monotonic() + max(0.05, timeout)
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise ConversionCancelledError(f"{source}: cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConversionTimeoutError(
                    f"{source}: conversion exceeded hard timeout "
                    f"of {timeout:.0f}s and the worker was terminated"
                )
            if not receiver.poll(min(remaining, _CANCEL_POLL_S)):
                continue
            try:
                status, value = receiver.recv()
            except (EOFError, OSError) as exc:
                raise ConversionError(
                    f"{source}: worker process died unexpectedly ({exc})"
                ) from exc
            if status == "progress":
                # Not the final word - keep waiting for "ok"/"error" after
                # relaying this to the caller. A callback that raises must
                # never take the whole conversion down with it.
                if on_progress is not None:
                    try:
                        on_progress(*value)
                    except Exception:
                        pass
                continue
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


def _run_in_process(payload: dict, timeout: float, cancel=None, on_progress=None) -> str:
    ctx = get_context("spawn")
    receiver, sender = ctx.Pipe(False)
    proc = ctx.Process(
        target=_isolated_convert_entry,
        args=(payload, sender, on_progress is not None),
        name=f"doc2md-{Path(payload['source']).stem}",
        daemon=True,
    )
    proc.start()
    sender.close()
    return _wait_for_worker(receiver, proc, payload["source"], timeout, cancel, on_progress)


def _run_in_thread(payload: dict, timeout: float, cancel=None) -> str:
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doc2md-worker")
    try:
        future = pool.submit(_execute_payload, payload)
        deadline = time.monotonic() + max(0.05, timeout)
        while True:
            if cancel is not None and cancel.is_set():
                raise ConversionCancelledError(f"{payload['source']}: cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConversionTimeoutError(
                    f"{payload['source']}: conversion exceeded hard timeout "
                    f"of {timeout:.0f}s (worker thread abandoned)"
                )
            done, _pending = futures_wait([future], timeout=min(remaining, _CANCEL_POLL_S))
            if done:
                return future.result()
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
        cancel_event=None,
        progress_callback=None,
    ) -> None:
        self.timeout = float(timeout)
        self.options: dict = dict(options or {})
        # A ``threading.Event``: set it from another thread to stop a conversion
        # in flight. Process-isolated engines are terminated; in-thread engines
        # stop at their next check.
        self.cancel_event = cancel_event
        # Called as ``progress_callback(source, current, total)`` from
        # whichever thread ``convert_file()`` runs on. Only PDF OCR paths
        # (scanned pages, mis-encoded pages re-read by OCR) currently report
        # through this - a single-image OCR has no page loop to hook into,
        # so callers must not assume every file reports progress.
        self.progress_callback = progress_callback

    def convert_file(self, path: Path | str, *, strict: bool = False) -> ConversionResult:
        started = time.perf_counter()
        source = Path(path)
        if self.cancel_event is not None and self.cancel_event.is_set():
            result = ConversionResult(
                source=source, success=False, error=f"{source}: cancelled",
                duration_s=time.perf_counter() - started,
            )
            if strict:
                raise ConversionCancelledError(result.error)
            return result
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
        elif self.cancel_event is not None:
            options["_cancel_event"] = self.cancel_event

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
                on_progress = None
                if self.progress_callback is not None:
                    def on_progress(current, total, _source=source):
                        self.progress_callback(_source, current, total)
                raw_result = _run_in_process(
                    payload, effective_timeout, self.cancel_event, on_progress
                )
            else:
                raw_result = _run_in_thread(payload, effective_timeout, self.cancel_event)
            if isinstance(raw_result, EngineOutput):
                raw_markdown = raw_result.markdown
                quality = raw_result.metrics
            else:
                raw_markdown = raw_result
                quality = QualityMetrics()
            warning, raw_markdown = split_warning(raw_markdown)
            optimized, review_lines = review.extract(cleaner.optimize(raw_markdown))
            if warning:
                # A warning is shown verbatim to the user; it must never carry
                # a stray review sentinel.
                warning = review.extract(warning)[0]
            if review_lines or quality.ocr_review_lines is not None:
                # The cleaner can drop duplicate lines, so the engine's own
                # count may be higher than what survives in the final text.
                quality.ocr_review_lines = len(review_lines)
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
                review_lines=review_lines,
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
