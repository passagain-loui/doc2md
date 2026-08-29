# audio_engine.py

```python
"""Audio & Video transcription engine using faster-whisper (CTranslate2)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from doc2md.core.errors import ConversionError
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine

logger = logging.getLogger(__name__)


def _get_ffmpeg_path() -> str:
    """Resolve FFmpeg executable path from bundled or system location."""
    # Priority 1: PyInstaller bundle (_MEIPASS)
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
        ffmpeg_exe = os.path.join(base_path, "ffmpeg.exe")
        if os.path.exists(ffmpeg_exe):
            logger.debug(f"Using bundled FFmpeg (PyInstaller): {ffmpeg_exe}")
            return ffmpeg_exe

    # Priority 2: Bundled next to Python executable (local development or portable)
    python_dir = os.path.dirname(sys.executable)
    ffmpeg_exe = os.path.join(python_dir, "ffmpeg.exe")
    if os.path.exists(ffmpeg_exe):
        logger.debug(f"Using bundled FFmpeg (Python dir): {ffmpeg_exe}")
        return ffmpeg_exe

    # Priority 3: Project root directory (local development)
    project_root = Path(__file__).parent.parent.parent
    ffmpeg_exe = str(project_root / "ffmpeg.exe")
    if os.path.exists(ffmpeg_exe):
        logger.debug(f"Using bundled FFmpeg (project root): {ffmpeg_exe}")
        return ffmpeg_exe

    # Priority 4: System PATH
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        logger.debug(f"Using system FFmpeg: {ffmpeg_in_path}")
        return ffmpeg_in_path

    # Priority 5: Try imageio_ffmpeg as fallback
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(ffmpeg_exe):
            logger.debug(f"Using imageio_ffmpeg FFmpeg: {ffmpeg_exe}")
            return ffmpeg_exe
    except (ImportError, Exception):
        pass

    logger.warning("FFmpeg not found in bundled locations or system PATH")
    return "ffmpeg"  # Let ffmpeg-python handle the lookup


class AudioEngine(BaseEngine):
    """Transcribe audio/video using faster-whisper with on-demand model downloading."""

    name = "audio"
    supported_kinds = (FileKind.AUDIO, FileKind.VIDEO)

    _model_cache: dict[str, Any] = {}
    _model_size = "small"
    MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")
    MODEL_CACHE_DIR = Path.home() / ".cache" / "doc2md" / "models"

    def convert(self, source: Path | str, options: dict, abort_event: Optional[threading.Event] = None) -> str:
        """Transcribe audio/video file and return structured Markdown.

        Args:
            source: Path to audio/video file
            options: Conversion options dict (can include 'abort_event' key)
            abort_event: Optional threading.Event to signal cancellation during transcription
        """
        try:
            source = Path(source)
            if not source.is_file():
                raise ConversionError(f"Audio file not found: {source}")

            # Extract abort_event from options if not provided directly
            if abort_event is None:
                abort_event = options.get("abort_event")

            # Check abort signal early
            if abort_event and abort_event.is_set():
                raise ConversionError("Transcription cancelled by user")

            try:
                import ffmpeg
            except ImportError:
                raise ConversionError(
                    "ffmpeg-python is required for audio processing. "
                    "Install via: pip install 'doc2md[audio]'"
                )

            # Ensure bundled FFmpeg is available for both ffmpeg-python and faster-whisper
            ffmpeg_path = _get_ffmpeg_path()
            if ffmpeg_path == "ffmpeg":
                raise ConversionError(
                    "FFmpeg not found. Please install it via: pip install 'doc2md[audio]' "
                    "or download from https://ffmpeg.org/download.html"
                )
            ffmpeg_dir = os.path.dirname(ffmpeg_path)
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

            model_size = options.get("audio_model", self._model_size)
            if model_size not in self.MODEL_SIZES:
                model_size = self._model_size

            duration = self._get_duration(source)
            model = self._load_model(model_size, options.get("download_progress"))

            try:
                segments_gen, info = model.transcribe(str(source), language="en")
                # faster-whisper returns a lazy generator; consume it fully here
                # so downstream formatting can iterate plain segment objects
                # instead of accidentally iterating the (generator, info) tuple.
                segments = []
                for segment in segments_gen:
                    # Check abort signal before processing each segment
                    if abort_event and abort_event.is_set():
                        raise ConversionError("Transcription cancelled by user")
                    segments.append(segment)
            except ConversionError:
                raise
            except RuntimeError as e:
                error_msg = str(e)
                if "CUDA" in error_msg or "GPU" in error_msg:
                    raise ConversionError(
                        "GPU/CUDA error detected. Falling back to CPU mode. "
                        f"Details: {error_msg}"
                    )
                elif "corrupt" in error_msg.lower() or "invalid" in error_msg.lower():
                    raise ConversionError(
                        f"Audio file may be corrupted or in an unsupported format: {source.name}. "
                        "Try converting to MP3 or WAV format first."
                    )
                else:
                    raise ConversionError(f"Transcription failed: {error_msg}")
            except Exception as e:
                error_msg = str(e)
                if "No such file" in error_msg or "cannot find" in error_msg.lower():
                    raise ConversionError(
                        f"Audio file not found or inaccessible: {source.name}"
                    )
                raise ConversionError(f"Transcription failed: {type(e).__name__}: {error_msg}")

            return self._format_output(source, duration, segments, model_size)
        except ConversionError:
            raise
        except Exception as e:
            logger.exception(f"Audio conversion error: {e}")
            raise ConversionError(f"Audio processing failed: {type(e).__name__}: {str(e)}")

    def _get_duration(self, source: Path) -> float:
        """Get audio/video duration in seconds."""
        try:
            import ffmpeg

            # Ensure bundled FFmpeg is in PATH for ffmpeg-python
            ffmpeg_path = _get_ffmpeg_path()
            if ffmpeg_path != "ffmpeg":
                # Prepend bundled FFmpeg directory to PATH
                ffmpeg_dir = os.path.dirname(ffmpeg_path)
                os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

            probe = ffmpeg.probe(str(source))
            return float(probe["format"]["duration"])
        except Exception:
            return 0.0

    def _load_model(self, model_size: str, progress_callback=None):
        """Load or download faster-whisper model, reusing a cached instance
        (e.g. one warmed up via `preload_model`) when available."""
        try:
            if model_size in self._model_cache:
                logger.debug(f"Reusing preloaded model: {model_size}")
                return self._model_cache[model_size]

            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ConversionError(
                    "faster-whisper is required. Install via: pip install 'doc2md[audio]'"
                )

            self.MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

            model_path = self.MODEL_CACHE_DIR / model_size
            device = "cuda" if self._has_gpu() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"

            if not model_path.exists():
                logger.info(f"Downloading {model_size} model to {model_path}...")
                # WhisperModel auto-downloads to cache_dir
                model = WhisperModel(model_size, device=device, compute_type=compute_type)
            else:
                model = WhisperModel(model_size, device=device, compute_type=compute_type)

            self._model_cache[model_size] = model
            return model
        except ConversionError:
            raise
        except Exception as e:
            logger.exception(f"Model loading failed: {e}")
            raise ConversionError(f"Failed to load {model_size} model: {type(e).__name__}: {str(e)}")

    def preload_model(self, model_size: str) -> None:
        """Eagerly load (and cache) a Whisper model ahead of any conversion,
        so the GUI can warm up the model on startup / model-selection change
        instead of paying the load cost lazily during the first conversion."""
        if model_size not in self.MODEL_SIZES:
            model_size = self._model_size
        self._load_model(model_size)

    def _has_gpu(self) -> bool:
        """Check if NVIDIA GPU is available."""
        try:
            import torch

            return torch.cuda.is_available()
        except ImportError:
            return False

    def _format_output(
        self, source: Path, duration: float, segments: list, model_size: str
    ) -> str:
        """Format transcription output as Markdown with timestamps."""
        lines = [
            f"# Transcription: {source.name}",
            "",
            f"- **Duration:** {self._format_time(duration)}",
            f"- **Model:** faster-whisper ({model_size})",
            f"- **Language:** English",
            "",
            "## Transcript",
            "",
        ]

        for segment in segments:
            start = self._format_time(segment.start)
            end = self._format_time(segment.end)
            text = segment.text.strip()
            if text:
                lines.append(f"**[{start} - {end}]** {text}")

        return "\n".join(lines)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Convert seconds to HH:MM:SS format."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
```
