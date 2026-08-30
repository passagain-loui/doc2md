"""Engine registry mapping detected file kinds to converter engines."""

from __future__ import annotations

from doc2md.core.errors import ConversionError
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine
from doc2md.engine.code_engine import CodeEngine
from doc2md.engine.docx_engine import DocxEngine
from doc2md.engine.excel_engine import ExcelEngine
from doc2md.engine.ocr_engine import OcrEngine
from doc2md.engine.pdf_engine import PdfEngine
from doc2md.engine.pptx_engine import PptxEngine
from doc2md.engine.web_engine import WebEngine

_ENGINES: list[BaseEngine] = [
    PdfEngine(),
    DocxEngine(),
    ExcelEngine(),
    PptxEngine(),
    WebEngine(),
    OcrEngine(),
    CodeEngine(),
]

_REGISTRY: dict[FileKind, BaseEngine] = {}
_BY_NAME: dict[str, BaseEngine] = {}
for _engine in _ENGINES:
    _BY_NAME[_engine.name] = _engine
    for _kind in _engine.supported_kinds:
        _REGISTRY.setdefault(_kind, _engine)


def get_engine(kind: FileKind) -> BaseEngine | None:
    return _REGISTRY.get(kind)


def get_engine_by_name(name: str) -> BaseEngine | None:
    return _BY_NAME.get(name)


def all_engines() -> list[BaseEngine]:
    return list(_ENGINES)


def engine_for_path(path) -> tuple[BaseEngine, "Detection"]:
    from doc2md.core.router import detect

    detection = detect(path)
    engine = get_engine(detection.kind)
    if engine is None:
        raise ConversionError(
            f"No engine registered for kind {detection.kind.value!r} (file: {path})"
        )
    return engine, detection


__all__ = [
    "all_engines",
    "engine_for_path",
    "get_engine",
    "get_engine_by_name",
    "BaseEngine",
]
