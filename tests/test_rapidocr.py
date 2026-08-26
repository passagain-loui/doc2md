import sys
import types

import pytest

from doc2md.core.errors import ConversionError
from doc2md.core.router import FileKind
from doc2md.engine import get_engine
from doc2md.engine.ocr_engine import OcrEngine


@pytest.fixture(autouse=True)
def _reset_rapidocr_singleton():
    OcrEngine._rapidocr_engine = None
    yield
    OcrEngine._rapidocr_engine = None


def make_png(tmp_path, color="white", name="img.png"):
    from PIL import Image

    p = tmp_path / name
    Image.new("RGB", (60, 30), color).save(p)
    return p


def make_rapid_module(lines=None, call_error=None, init_error=None):
    module = types.ModuleType("rapidocr_onnxruntime")

    class RapidOCR:
        def __init__(self):
            if init_error is not None:
                raise init_error

        def __call__(self, image_path):
            if call_error is not None:
                raise call_error
            result = [(i, text, 0.9) for i, text in enumerate(lines or [])]
            return result, 0.05

    module.RapidOCR = RapidOCR
    return module


@pytest.fixture
def no_tesseract(monkeypatch):
    monkeypatch.setattr("doc2md.engine.ocr_engine.shutil.which", lambda name: None)


def test_rapidocr_returns_lines(tmp_path, monkeypatch, no_tesseract):
    monkeypatch.setitem(
        sys.modules, "rapidocr_onnxruntime", make_rapid_module(lines=["HELLO", "WORLD"])
    )
    p = make_png(tmp_path)
    out = get_engine(FileKind.IMAGE).convert(p, {})
    assert "HELLO" in out and "WORLD" in out
    assert "## Extracted text" in out


def test_rapidocr_empty_result_notes_no_text(tmp_path, monkeypatch, no_tesseract):
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", make_rapid_module(lines=[]))
    p = make_png(tmp_path)
    out = get_engine(FileKind.IMAGE).convert(p, {})
    assert "no readable text was found" in out


def test_rapidocr_init_failure_becomes_conversion_error(tmp_path, monkeypatch, no_tesseract):
    monkeypatch.setitem(
        sys.modules,
        "rapidocr_onnxruntime",
        make_rapid_module(init_error=RuntimeError("model files missing")),
    )
    p = make_png(tmp_path)
    with pytest.raises(ConversionError, match="RapidOCR failed"):
        get_engine(FileKind.IMAGE).convert(p, {})


def test_rapidocr_call_failure_becomes_conversion_error(tmp_path, monkeypatch, no_tesseract):
    monkeypatch.setitem(
        sys.modules,
        "rapidocr_onnxruntime",
        make_rapid_module(call_error=RuntimeError("onnx crashed")),
    )
    p = make_png(tmp_path)
    with pytest.raises(ConversionError, match="RapidOCR failed"):
        get_engine(FileKind.IMAGE).convert(p, {})


def test_rapidocr_missing_and_tesseract_missing_yields_hint(tmp_path, monkeypatch, no_tesseract):
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)
    p = make_png(tmp_path)
    out = get_engine(FileKind.IMAGE).convert(p, {})
    assert "neither Tesseract" in out and "RapidOCR" in out


def test_real_rapidocr_integration_if_available(tmp_path):
    pytest.importorskip("rapidocr_onnxruntime")
    p = make_png(tmp_path, color="white", name="blank.png")
    out = get_engine(FileKind.IMAGE).convert(p, {"pdf_ocr_fallback": False})
    assert "- **Dimensions:** 60 x 30" in out
