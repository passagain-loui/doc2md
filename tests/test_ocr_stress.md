# test_ocr_stress.py

```python
import concurrent.futures
import gc
import sys
import tempfile
import threading
import types
from pathlib import Path

import pytest

from doc2md.core.errors import ConversionError
from doc2md.core.router import FileKind
from doc2md.engine import get_engine
from doc2md.engine.ocr_engine import OcrEngine
from tests.helpers import make_fake_pytesseract

pytest.importorskip("PIL")

from PIL import Image, ImageDraw  # noqa: E402

ENGINE = lambda: get_engine(FileKind.IMAGE)  # noqa: E731


@pytest.fixture(autouse=True)
def _reset_singleton():
    OcrEngine._rapidocr_engine = None
    yield
    OcrEngine._rapidocr_engine = None


@pytest.fixture
def no_backends(monkeypatch):
    monkeypatch.setattr("doc2md.engine.ocr_engine.shutil.which", lambda name: None)
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", None)


def make_png(path, color="white"):
    Image.new("RGB", (60, 30), color).save(path)
    return path


def make_noise_image(path):
    img = Image.effect_noise((256, 128), 64).convert("RGB")
    draw = ImageDraw.Draw(img)
    for x in range(0, 256, 16):
        draw.line([(x, 0), (x, 128)], fill=(255 - x, x % 255, 128), width=1)
    img.save(path)
    return path


def make_palette_png(path):
    gradient = Image.new("RGB", (80, 40))
    gradient.putdata([(i * 3 % 256, i * 5 % 256, i * 7 % 256) for i in range(80 * 40)])
    palette_img = gradient.quantize(colors=64)
    palette_img.save(path, format="PNG")
    return path


def make_16bit_tiff(path):
    raw = [(x * 257) % 65536 for x in range(50 * 20)]
    img = Image.new("I;16", (50, 20))
    img.putdata(raw)
    img.save(path, format="TIFF")
    return path


def make_transparent_webp(path):
    img = Image.new("RGBA", (70, 35), (0, 255, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([10, 5, 60, 30], fill=(200, 30, 30, 230))
    img.save(path, format="WEBP")
    return path


def make_exif_jpeg(path, orientation=6):
    img = Image.new("RGB", (120, 60), (10, 120, 220))
    exif = Image.Exif()
    exif[274] = orientation
    img.save(path, format="JPEG", exif=exif)
    return path


class TestBlankNoiseImages:
    def test_pure_black_and_white_clean_result(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "pytesseract", make_fake_pytesseract(text="   "))
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: "C:/fake/tesseract.exe"
        )
        for color in ("black", "white"):
            p = make_png(tmp_path / f"{color}.png", color)
            out = ENGINE().convert(p, {})
            assert result_is_clean(out)

    def test_random_noise_no_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "pytesseract", make_fake_pytesseract(text=""))
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: "C:/fake/tesseract.exe"
        )
        p = make_noise_image(tmp_path / "noise.png")
        out = ENGINE().convert(p, {})
        assert result_is_clean(out)


class TestUltraHighResolution:
    def test_8k_image_memory_stability(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "pytesseract", make_fake_pytesseract(text="8K TEXT"))
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: "C:/fake/tesseract.exe"
        )
        temp_root = Path(tempfile.gettempdir())
        before = set(temp_root.glob("doc2md_ocr_*"))

        huge = tmp_path / "huge_8k.png"
        Image.new("RGB", (7680, 4320), (250, 250, 245)).save(huge, format="PNG")
        assert huge.stat().st_size > 0

        out = ENGINE().convert(huge, {"pdf_ocr_fallback": False})
        assert "8K TEXT" in out
        assert "- **Dimensions:** 7680 x 4320" in out

        gc.collect()
        after = set(temp_root.glob("doc2md_ocr_*"))
        assert not (after - before)


class TestNonStandardFormats:
    def test_palette_png(self, tmp_path, no_backends):
        out = ENGINE().convert(make_palette_png(tmp_path / "palette.png"), {})
        assert "- **Type:** image (png)" in out

    def test_16bit_tiff(self, tmp_path, no_backends):
        out = ENGINE().convert(make_16bit_tiff(tmp_path / "deep.tiff"), {})
        assert "- **Dimensions:** 50 x 20" in out

    def test_transparent_webp(self, tmp_path, no_backends):
        out = ENGINE().convert(make_transparent_webp(tmp_path / "alpha.webp"), {})
        assert "- **Dimensions:** 70 x 35" in out

    def test_exif_rotated_jpeg_normalized(self, tmp_path):
        pytest.importorskip("PIL")
        src = make_exif_jpeg(tmp_path / "rot.jpg", orientation=6)
        workdir = tmp_path / "work"
        workdir.mkdir()
        normalized = OcrEngine._normalized_rgb(src, workdir)
        with Image.open(normalized) as upright:
            assert upright.mode == "RGB"
            assert upright.size == (60, 120)

    def test_exif_unrotated_unchanged(self, tmp_path):
        src = make_exif_jpeg(tmp_path / "straight.jpg", orientation=1)
        normalized = OcrEngine._normalized_rgb(src, tmp_path)
        with Image.open(normalized) as img:
            assert img.size == (120, 60)


class TestMissingEngineSafety:
    def test_rapidocr_dll_failure_wrapped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: None
        )

        def boom():
            raise OSError("OnnxRuntime.dll not found (0x8007007E)")

        module = types.ModuleType("rapidocr_onnxruntime")
        module.RapidOCR = boom
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)

        p = make_png(tmp_path / "dll.png")
        with pytest.raises(ConversionError, match="RapidOCR failed to initialize"):
            ENGINE().convert(p, {})

    def test_corrupt_onnx_model_inference_wrapped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: None
        )

        class RapidOCR:
            def __init__(self):
                pass

            def __call__(self, image_path):
                raise RuntimeError("ONNX model file is corrupt: model.onnx.bad")

        module = types.ModuleType("rapidocr_onnxruntime")
        module.RapidOCR = RapidOCR
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)

        p = make_png(tmp_path / "corrupt.png")
        with pytest.raises(ConversionError, match="failed during inference"):
            ENGINE().convert(p, {})

    def test_tesseract_without_pytesseract_package_no_nameerror(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: "C:/fake/tesseract.exe"
        )
        monkeypatch.setitem(sys.modules, "pytesseract", None)
        p = make_png(tmp_path / "nopkg.png")
        with pytest.raises(ConversionError) as caught:
            ENGINE().convert(p, {})
        assert "NameError" not in type(caught.value).__name__
        assert "pytesseract package is missing" in str(caught.value)


class TestConcurrency:
    def test_ten_parallel_threads_tesseract_stub(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "pytesseract", make_fake_pytesseract(text="PARALLEL OCR"))
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: "C:/fake/tesseract.exe"
        )
        images = [make_png(tmp_path / f"p{i}.png") for i in range(10)]

        temp_root = Path(tempfile.gettempdir())
        before = set(temp_root.glob("doc2md_ocr_*"))
        errors = []
        results = {}

        def worker(idx):
            try:
                results[idx] = ENGINE().convert(images[idx], {})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors
        assert len(results) == 10
        assert all("PARALLEL OCR" in r for r in results.values())
        after = set(temp_root.glob("doc2md_ocr_*"))
        assert not (after - before)

    def test_ten_parallel_threads_rapidocr_serialized(self, tmp_path, monkeypatch):
        calls = []
        lock = threading.Lock()

        class RapidOCR:
            def __init__(self):
                pass

            def __call__(self, image_path):
                with lock:
                    calls.append(image_path)
                return [(0, "LINE A"), (1, "LINE B")], 0.01

        module = types.ModuleType("rapidocr_onnxruntime")
        module.RapidOCR = RapidOCR
        monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", module)
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: None
        )

        images = [make_png(tmp_path / f"r{i}.png") for i in range(10)]
        outputs = []
        init_count = []

        original_get = OcrEngine._get_rapidocr

        def counting_get(self):
            engine = original_get(self)
            if id(engine) not in init_count:
                init_count.append(id(engine))
            return engine

        monkeypatch.setattr(OcrEngine, "_get_rapidocr", counting_get)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(ENGINE().convert, img, {}) for img in images]
            outputs = [f.result(timeout=60) for f in futures]

        assert all("LINE A" in o and "LINE B" in o for o in outputs)
        assert len(init_count) == 1

    def test_zero_temp_leaks_after_batch_run(self, tmp_path, monkeypatch):
        monkeypatch.setitem(sys.modules, "pytesseract", make_fake_pytesseract(text="BATCH"))
        monkeypatch.setattr(
            "doc2md.engine.ocr_engine.shutil.which", lambda n: "C:/fake/tesseract.exe"
        )
        temp_root = Path(tempfile.gettempdir())
        before = set(temp_root.glob("doc2md_ocr_*"))
        images = [make_noise_image(tmp_path / f"n{i}.png") for i in range(6)]
        for img in images:
            ENGINE().convert(img, {"ocr_lang": "eng"})
        after = set(temp_root.glob("doc2md_ocr_*"))
        assert after == before or not (after - before)


def result_is_clean(markdown: str) -> bool:
    assert "Traceback" not in markdown
    assert "- **Dimensions:**" in markdown
    return True
```
