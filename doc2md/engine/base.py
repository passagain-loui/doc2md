"""Abstract base class every doc2md engine must inherit from."""

from __future__ import annotations

import abc
from pathlib import Path

from doc2md.core.errors import ConversionError
from doc2md.core.quality import EngineOutput
from doc2md.core.router import FileKind


class BaseEngine(abc.ABC):
    """Contract for all converter engines.

    Engines receive a filesystem path plus an options dict of plain Python
    primitives (required for cross-process dispatch) and return Markdown text.
    Any failure MUST raise ConversionError (or a subclass) instead of returning
    partial garbage output.
    """

    name: str = "base"
    supported_kinds: tuple[FileKind, ...] = ()
    requires_process_isolation: bool = False

    @abc.abstractmethod
    def convert(self, source: Path, options: dict) -> str:
        """Convert the document at *source* into Markdown."""

    def convert_structured(self, source: Path, options: dict) -> EngineOutput:
        """Same conversion, with structured quality metrics attached.

        Default implementation just calls ``convert()`` and wraps its string
        with an empty ``QualityMetrics`` (every field ``None`` - "not
        measured"), so a plain string-returning engine needs no change to
        keep working through this path. Engines that can measure real
        extraction facts (pages, tables, rows, OCR outcome) override this.
        This is what ``Converter`` actually calls; ``convert()`` stays the
        stable, directly-testable, string-only contract it always was.
        """
        return EngineOutput(markdown=self.convert(source, options))

    def validate_source(self, source: Path) -> None:
        if not source.is_file():
            raise ConversionError(f"File not found or not a regular file: {source}")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{type(self).__name__} name={self.name!r}>"
