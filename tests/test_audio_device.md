# test_audio_device.py

```python
"""Tests for audio-engine hardware detection.

Covers the defect where GPU acceleration silently never engaged: ``_has_gpu()``
probed ``torch.cuda.is_available()``, but faster-whisper runs on CTranslate2 and
torch is not a dependency of this project, so the probe raised
ModuleNotFoundError, was swallowed, and every transcription ran on CPU.
"""

from __future__ import annotations

import sys
import types

import pytest

from doc2md.engine import audio_engine
from doc2md.engine.audio_engine import AudioEngine


@pytest.fixture
def fake_ctranslate2(monkeypatch):
    """Install a stub ctranslate2 module and return it for configuration."""

    def _install(device_count: int, compute_types: set[str]):
        module = types.SimpleNamespace(
            get_cuda_device_count=lambda: device_count,
            get_supported_compute_types=lambda device: compute_types,
        )
        monkeypatch.setitem(sys.modules, "ctranslate2", module)
        # Detection registers DLL dirs first; keep that a no-op under test.
        monkeypatch.setattr(audio_engine, "_register_cuda_dll_dirs", lambda: [])
        return module

    return _install


def test_gpu_detected_when_cuda_device_and_float16_available(fake_ctranslate2):
    fake_ctranslate2(1, {"float16", "int8", "float32"})
    assert AudioEngine._has_gpu() is True


def test_no_gpu_when_device_count_is_zero(fake_ctranslate2):
    fake_ctranslate2(0, {"float16"})
    assert AudioEngine._has_gpu() is False


def test_no_gpu_when_cuda_runtime_missing(fake_ctranslate2):
    """A visible device with no loadable float16 backend must not claim GPU.

    This is the cuBLAS/cuDNN-missing case: the device query still reports 1,
    and blindly trusting it produces a hard failure at model construction.
    """
    fake_ctranslate2(1, {"float32"})
    assert AudioEngine._has_gpu() is False


def test_detection_failure_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(audio_engine, "_register_cuda_dll_dirs", lambda: [])
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    assert AudioEngine._has_gpu() is False


def test_detection_does_not_require_torch(monkeypatch, fake_ctranslate2):
    """Importing torch must never be part of the decision."""
    fake_ctranslate2(1, {"float16"})

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def guard(name, *args, **kwargs):
        assert name != "torch", "audio engine must not depend on torch"
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guard)
    assert AudioEngine._has_gpu() is True


def test_describe_device_reports_cpu_threads(fake_ctranslate2):
    fake_ctranslate2(0, set())
    description = AudioEngine.describe_device()
    assert description.startswith("CPU (")
    assert "int8" in description


def test_describe_device_reports_gpu(fake_ctranslate2):
    fake_ctranslate2(1, {"float16"})
    description = AudioEngine.describe_device()
    assert "GPU/CUDA" in description
    assert "float16" in description


def test_hint_is_empty_when_gpu_works(fake_ctranslate2):
    fake_ctranslate2(1, {"float16"})
    assert AudioEngine.acceleration_hint() == ""


def test_hint_offers_gpu_pack_when_runtime_missing(fake_ctranslate2):
    """NVIDIA card present, CUDA runtime absent -> installing the pack helps."""
    fake_ctranslate2(1, {"float32"})
    hint = AudioEngine.acceleration_hint()
    assert "GPU Pack" in hint


def test_hint_does_not_promise_gpu_on_amd(fake_ctranslate2):
    """No CUDA device at all -> must not tell the user to install anything."""
    fake_ctranslate2(0, set())
    hint = AudioEngine.acceleration_hint()
    assert "GPU Pack" not in hint
    assert "NVIDIA" in hint


def test_cuda_search_roots_prefers_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("DOC2MD_CUDA_DIR", str(tmp_path))
    assert audio_engine.cuda_search_roots()[0] == tmp_path


def test_register_cuda_dll_dirs_is_idempotent(monkeypatch):
    monkeypatch.setattr(audio_engine, "_CUDA_DLL_DIRS_REGISTERED", False)
    audio_engine._register_cuda_dll_dirs()
    # Second call short-circuits and reports nothing new.
    assert audio_engine._register_cuda_dll_dirs() == []
```
