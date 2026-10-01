"""Structured, per-document quality metrics and the JSON quality report.

Engines that can measure real extraction facts (pages read, tables found,
rows exported, OCR outcome) override ``BaseEngine.convert_structured()`` to
return an :class:`EngineOutput` carrying a populated :class:`QualityMetrics`.
Engines that cannot get the default implementation for free: it wraps their
existing ``convert()`` string with an *empty* ``QualityMetrics`` (every field
``None``), so nothing about them has to change. ``Converter.convert_file()``
reads whichever shape came back and always attaches a ``QualityMetrics`` to
the resulting ``ConversionResult`` - CLI and GUI therefore read one identical
shape regardless of which engine produced it.

Every field defaults to ``None`` ("not measured"), never ``0`` - a null in
the JSON report cannot be misread as "read zero of anything", which a 0
could be.

Both dataclasses hold only JSON-primitive fields, so they cross the
``multiprocessing`` spawn-process pipe (pickle) and serialize to JSON
directly with no custom encoder.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class QualityMetrics:
    """Extraction facts for one conversion. ``None`` means "not measured"."""

    pages_total: int | None = None
    """Total pages in the document (set once it opens successfully)."""

    pages_read: int | None = None
    """Pages whose text-layer *extraction attempt* did not raise an
    exception. This is NOT the same as "pages with real content": a scanned
    page with no text layer at all still counts here if PyMuPDF returned
    (empty) text without error - it was successfully "read", it just had
    nothing to find. See ``pages_with_content`` for whether a page actually
    contributed text to the output; do not present ``pages_read`` alone as
    "pages read N/N" in UI copy, since that reads as a success claim this
    field does not make."""

    pages_failed: int | None = None
    """Pages whose text-layer extraction attempt raised an exception."""

    pages_with_content: int | None = None
    """Pages that actually ended up contributing extracted text to the
    output - via the text layer on the fast path, or via OCR on the scanned
    path (mirrors ``ocr_pages_success`` there). This is the field to show
    for "how much of the document did we actually capture": a scanned PDF
    whose OCR was disabled or unavailable has ``pages_read == pages_total``
    (nothing errored) but ``pages_with_content == 0`` (nothing was actually
    read)."""

    tables_detected: int | None = None
    sheets_detected: int | None = None
    rows_detected: int | None = None
    rows_detected_is_exact: bool | None = None
    """Whether ``rows_detected`` is the real row count (``True``) or only a
    lower bound (``False``) - never omit this alongside ``rows_detected``
    when ``truncated`` could be true. ``None`` means not measured."""
    rows_exported: int | None = None
    truncated: bool | None = None
    ocr_backend: str | None = None
    ocr_language: str | None = None
    ocr_pages_success: int | None = None
    ocr_pages_empty: int | None = None
    ocr_pages_failed: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EngineOutput:
    """What ``BaseEngine.convert_structured()`` returns.

    ``markdown`` is exactly what ``convert()`` would have returned - including
    the ``\\x00DOC2MD-WARNING\\x00`` envelope from :mod:`doc2md.core.errors`
    when the engine set one. ``Converter.convert_file()`` still runs
    ``split_warning()`` on it, unchanged from before this existed.
    """

    markdown: str
    metrics: QualityMetrics = field(default_factory=QualityMetrics)


# --- status classification ---------------------------------------------------

STATUS_SUCCESS = "Success"
STATUS_WARNING = "Warning"
STATUS_ERROR = "Error"
STATUS_SKIPPED = "Skipped"


def status_of(result) -> str:
    """Classify a :class:`~doc2md.core.converter.ConversionResult`.

    A Warning must never present as Success (OCR unavailable, disabled, or
    completed with no readable text is real output but not a real read of
    the document).
    """
    if not getattr(result, "success", False):
        return STATUS_ERROR
    if getattr(result, "warning", None):
        return STATUS_WARNING
    return STATUS_SUCCESS


def build_report(result, *, output_path: Path | str | None = None) -> dict:
    """Build one document's quality-report entry from a ``ConversionResult``.

    ``output_path`` is the destination the caller actually wrote the
    Markdown to (``None`` when nothing was written yet, e.g. ``--stdout`` or
    a failed conversion) - the report must reflect where the file really
    went, not a path derived after the fact from guesswork.
    """
    quality = getattr(result, "quality", None) or QualityMetrics()
    return {
        "source": str(getattr(result, "source", "")),
        "output": str(output_path) if output_path is not None else None,
        "kind": getattr(result, "kind", None),
        "engine": getattr(result, "engine", None),
        "status": status_of(result),
        "error": getattr(result, "error", None),
        "warning": getattr(result, "warning", None),
        "duration_s": round(float(getattr(result, "duration_s", 0.0) or 0.0), 4),
        "token_estimate": getattr(result, "token_estimate", None),
        **quality.to_dict(),
    }


def write_report_atomic(report: dict | list, path: Path | str) -> None:
    """Write *report* as JSON to *path* atomically.

    Shares :func:`doc2md.core.exporter.atomic_write_text` with every other
    file this application writes, so a write failure never leaves a partial
    or corrupt report at *path* - either the old content (if any) survives
    untouched, or the new content lands whole.
    """
    from doc2md.core.exporter import atomic_write_text

    atomic_write_text(Path(path), json.dumps(report, ensure_ascii=False, indent=2))
