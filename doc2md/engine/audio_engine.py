"""Audio & Video transcription engine using faster-whisper (CTranslate2)."""

from __future__ import annotations

import gc
import logging
import os
import re
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
    """Resolve FFmpeg executable path with preference for bundled PyInstaller version."""
    # Priority 1: PyInstaller bundle (_MEIPASS) - HIGHEST PRIORITY FOR STANDALONE
    if getattr(sys, 'frozen', False):
        base_path = Path(sys._MEIPASS)
        ffmpeg_exe = base_path / "ffmpeg.exe"
        if ffmpeg_exe.exists():
            logger.info(f"✓ Using EMBEDDED FFmpeg from PyInstaller bundle: {ffmpeg_exe}")
            return str(ffmpeg_exe)

        # Tolerate a differently-named bundled binary. imageio_ffmpeg ships
        # "ffmpeg-win-x86_64-v7.1.exe" and PyInstaller preserves basenames, so a
        # build that forgets to stage it as ffmpeg.exe would otherwise fall all
        # the way through to a system lookup that may not exist on the target.
        for candidate in sorted(base_path.glob("ffmpeg*.exe")):
            logger.info(f"✓ Using EMBEDDED FFmpeg from PyInstaller bundle: {candidate}")
            return str(candidate)

        logger.warning(f"PyInstaller bundle path checked but FFmpeg not found: {base_path}")

    # Priority 2: Current execution directory (fallback for standalone)
    exec_dir = os.path.dirname(sys.executable)
    ffmpeg_exe = os.path.join(exec_dir, "ffmpeg.exe")
    if os.path.exists(ffmpeg_exe):
        logger.info(f"✓ Using bundled FFmpeg (execution dir): {ffmpeg_exe}")
        return ffmpeg_exe

    # Priority 3: Project root directory (local development)
    project_root = Path(__file__).parent.parent.parent
    ffmpeg_exe = str(project_root / "ffmpeg.exe")
    if os.path.exists(ffmpeg_exe):
        logger.info(f"✓ Using bundled FFmpeg (project root): {ffmpeg_exe}")
        return ffmpeg_exe

    # Priority 4: System PATH
    ffmpeg_in_path = shutil.which("ffmpeg")
    if ffmpeg_in_path:
        logger.info(f"✓ Using system FFmpeg: {ffmpeg_in_path}")
        return ffmpeg_in_path

    # Priority 5: Try imageio_ffmpeg as final fallback
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if os.path.exists(ffmpeg_exe):
            logger.info(f"✓ Using imageio_ffmpeg FFmpeg: {ffmpeg_exe}")
            return ffmpeg_exe
    except (ImportError, Exception):
        pass

    logger.error("CRITICAL: FFmpeg not found in any location (bundled, system PATH, or imageio_ffmpeg)")
    return "ffmpeg"  # Last resort - let ffmpeg-python try to find it


_CUDA_DLL_DIRS_REGISTERED = False

# Components the GPU pack ships, in the layout both the pack and the
# ``nvidia-*-cu12`` wheels use: <root>/<component>/bin/*.dll
CUDA_COMPONENTS = ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc")

GPU_PACK_HINT = (
    "GPU acceleration is available for NVIDIA cards but the CUDA runtime is not "
    "installed. Install the doc2md GPU Pack to enable it."
)


def cuda_search_roots() -> list[Path]:
    """Directories that may contain a CUDA runtime, most specific first.

    The runtime is deliberately not bundled in the main installer: it is ~2 GB
    and only benefits NVIDIA users, so it ships as a separate optional GPU pack
    that lands in one of these locations.
    """
    roots: list[Path] = []

    override = os.environ.get("DOC2MD_CUDA_DIR")
    if override:
        roots.append(Path(override))

    # GPU pack install location (per-user, matches the main app's install root).
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        roots.append(Path(local_appdata) / "doc2md" / "cuda")

    # Portable layout: a "cuda" folder sitting next to doc2md.exe.
    try:
        roots.append(Path(sys.executable).parent / "cuda")
    except Exception:
        pass

    # PyInstaller bundle, for builds that do embed the runtime.
    if getattr(sys, "frozen", False):
        roots.append(Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))) / "nvidia")

    # Development environment: the nvidia-*-cu12 wheels.
    try:
        import sysconfig

        roots.append(Path(sysconfig.get_paths()["purelib"]) / "nvidia")
    except Exception:
        pass

    return roots


def _register_cuda_dll_dirs() -> list[str]:
    """Make the NVIDIA CUDA runtime DLLs discoverable, returning the dirs used.

    CTranslate2's native library loads cuBLAS/cuDNN itself via the ordinary
    Windows DLL search order, which does not consult ``os.add_dll_directory``
    for such transitive loads - only PATH. Neither the GPU pack's install
    directory nor the ``nvidia-*-cu12`` wheel layout
    (``site-packages/nvidia/<component>/bin``) is on either list, so CUDA
    initialisation fails with "Library cublas64_12.dll is not found or cannot
    be loaded" even when the GPU and driver are perfectly healthy.

    Idempotent, and a no-op when no runtime is present (the caller then falls
    back to CPU).
    """
    global _CUDA_DLL_DIRS_REGISTERED
    if _CUDA_DLL_DIRS_REGISTERED or sys.platform != "win32":
        return []

    found: list[str] = []
    for root in cuda_search_roots():
        for component in CUDA_COMPONENTS:
            candidate = root / component / "bin"
            if candidate.is_dir():
                found.append(str(candidate))
        if found:
            # First root that supplies anything wins; mixing runtimes from
            # different sources risks version skew between cuBLAS and cuDNN.
            break

    if found:
        os.environ["PATH"] = os.pathsep.join(found) + os.pathsep + os.environ.get("PATH", "")
        for directory in found:
            try:
                os.add_dll_directory(directory)
            except (OSError, AttributeError):
                pass
        logger.info(f"Registered CUDA runtime from: {Path(found[0]).parent.parent}")
    else:
        logger.info("No CUDA runtime found; transcription will use CPU. %s", GPU_PACK_HINT)

    _CUDA_DLL_DIRS_REGISTERED = True
    return found


class AudioEngine(BaseEngine):
    """Transcribe audio/video using faster-whisper with on-demand model downloading."""

    name = "audio"
    supported_kinds = (FileKind.AUDIO, FileKind.VIDEO)

    _model_cache: dict[str, Any] = {}
    _model_size = "small"
    MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")
    # Models are cached by huggingface_hub in its own standard location
    # (~/.cache/huggingface/hub). doc2md deliberately does not override
    # download_root: a private cache would force a fresh multi-hundred-MB
    # download for every user who already has these models locally.

    # Language mapping from GUI labels to ISO 639-1 codes
    LANGUAGE_CODES = {
        "Auto-detect": None,  # None = auto-detect by Whisper
        "English": "en",
        "Thai": "th",
        "Spanish": "es",
        "French": "fr",
        "German": "de",
        "Chinese": "zh",
        "Japanese": "ja",
    }

    def convert(self, source: Path | str, options: dict, abort_event: Optional[threading.Event] = None) -> str:
        """Transcribe audio/video file and return structured Markdown.

        Args:
            source: Path to audio/video file
            options: Conversion options dict (can include 'abort_event' key)
            abort_event: Optional threading.Event to signal cancellation during transcription

        This method is synchronous and stateless per the BaseEngine contract
        (it is invoked from a worker thread/process by Converter, never from
        a caller's main thread). Callers that need non-blocking UI progress
        should not call this directly from a GUI main thread; instead run it
        from a background worker and supply options['progress_callback'] as
        a queue-pushing function, e.g. `lambda pct: result_queue.put(("PROGRESS", pct))`,
        so the worker never touches UI state directly.
        """
        try:
            try:
                source = Path(source)
                if not source.is_file():
                    raise ConversionError(f"Audio file not found: {source}")

                # Pre-flight validation guard: catch corrupt/unreadable files
                # before ever reaching FFmpeg decoding or Whisper inference.
                # The GUI also calls validate_audio_file() directly at staging
                # time for immediate feedback; this call is defense-in-depth
                # for CLI/API callers that bypass GUI staging entirely.
                is_valid, reason = self.validate_audio_file(source)
                if not is_valid:
                    raise ConversionError(f"Invalid or unreadable audio file: {reason}")

                # Extract abort_event from options if not provided directly
                if abort_event is None:
                    abort_event = options.get("abort_event")

                # Extract progress callback for fine-grained numeric progress updates
                progress_callback = options.get("progress_callback")

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

                # Report the media length before the slow part starts. A long
                # recording otherwise sits at "0%" for minutes - the progress
                # percentage alone cannot distinguish "27 minutes of audio,
                # working normally" from "hung", which is exactly how it reads
                # to a user watching the bar.
                duration_callback = options.get("duration_callback")
                if duration_callback and duration > 0:
                    try:
                        duration_callback(duration)
                    except Exception:
                        pass

                model = self._load_model(model_size, options.get("download_progress"))

                # Speed optimization: faster-whisper defaults beam_size to 5,
                # which is significantly slower for a negligible accuracy
                # gain in most transcription use cases. Default to 1 (greedy
                # decoding), overridable via options["beam_size"].
                beam_size = options.get("beam_size", 1)

                # Extract language from options (GUI language selection)
                language_gui = options.get("language", "Auto-detect")
                language_code = self.LANGUAGE_CODES.get(language_gui, None)
                logger.info(f"🎤 Transcription: GUI language='{language_gui}' → Whisper code='{language_code}'")

                try:
                    segments_gen, info = model.transcribe(
                        str(source), language=language_code, beam_size=beam_size
                    )
                    # faster-whisper returns a lazy generator; consume it fully here
                    # so downstream formatting can iterate plain segment objects
                    # instead of accidentally iterating the (generator, info) tuple.
                    segments = []
                    for segment in segments_gen:
                        # Check abort signal before processing each segment
                        if abort_event and abort_event.is_set():
                            raise ConversionError("Transcription cancelled by user")
                        segments.append(segment)
                        # Report fine-grained numeric progress based on transcribed
                        # audio position, so the UI can show a real percentage
                        # instead of a static "Processing..." placeholder.
                        if progress_callback and duration > 0:
                            try:
                                percent = min(99, int((segment.end / duration) * 100))
                                progress_callback(percent)
                            except Exception:
                                pass  # Progress reporting must never break transcription
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

                # Report the language actually used: the explicit GUI selection
                # when one was made, otherwise whatever Whisper auto-detected.
                detected = getattr(info, "language", None)
                return self._format_output(
                    source, duration, segments, model_size,
                    language=language_code or detected or "auto",
                )
            except ConversionError:
                raise
            except Exception as e:
                logger.exception(f"Audio conversion error: {e}")
                raise ConversionError(f"Audio processing failed: {type(e).__name__}: {str(e)}")
        except ConversionError:
            # Re-raise ConversionError as-is (already properly handled)
            raise
        except BaseException as e:
            # Bulletproof outer crash guard for CTranslate2/Whisper/FFmpeg
            # failures: pybind11 translates most C++ exceptions raised by
            # CTranslate2 into ordinary Python exceptions, which this guard
            # converts into a clean ConversionError instead of letting the
            # process die - this is what "returns an error instead of
            # terminating the process" means for the overwhelming majority
            # of real-world native failures (bad codec params, malformed
            # streams, driver errors, etc).
            #
            # Honest limitation: a genuine hard native crash (segfault/access
            # violation) is not a Python exception at all - it's an OS signal
            # that terminates the process unconditionally, and no amount of
            # try/except at any nesting level can catch it. True immunity to
            # that class of failure requires running the risky call in a
            # separate OS process. That tradeoff was evaluated for this
            # engine and rejected: it would force reloading the (multi-
            # hundred-MB) Whisper model from scratch on every single
            # conversion, since a loaded model instance cannot cross a
            # process boundary - directly undoing the model-caching
            # performance work from v1.0.8. validate_audio_file() is the
            # primary defense instead: it catches the corrupt/malformed
            # files that are the leading real-world cause of native crashes,
            # before the risky decode path is ever reached.
            logger.critical(f"BULLETPROOF AUDIO CRASH GUARD: {type(e).__name__}: {str(e)}", exc_info=True)
            raise ConversionError(
                f"Critical audio engine failure: {type(e).__name__}. "
                f"The audio engine encountered an unexpected error. Try again with a different audio file."
            )

    def validate_audio_file(self, source: Path | str) -> tuple[bool, str]:
        """Pre-flight validation of an audio/video file, run BEFORE FFmpeg
        decoding or Whisper model inference is ever attempted.

        Probes container integrity and audio stream presence with a single
        lightweight `ffmpeg -i <file>` call (header parse only - no frame
        decoding, so this stays fast even for large files) and inspects the
        printed stream info for known corruption/format-error markers and
        the presence of a readable audio stream.

        Returns (is_valid, reason) - reason is empty when valid. Fails OPEN
        (returns valid) when FFmpeg itself can't be located or the probe
        errors out for a reason unrelated to the file's own integrity, so a
        validator bug or missing binary never blocks a conversion attempt
        that might otherwise have succeeded.
        """
        try:
            source = Path(source)
            if not source.is_file():
                return False, f"File not found: {source.name}"
            if source.stat().st_size == 0:
                return False, "File is empty (0 bytes)."

            ffmpeg_path = _get_ffmpeg_path()
            if ffmpeg_path == "ffmpeg":
                # No bundled/system FFmpeg available to probe with; let the
                # normal conversion pipeline attempt it and surface its own error.
                return True, ""

            kwargs: dict = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                [ffmpeg_path, "-i", str(source)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                **kwargs,
            )
            output = result.stderr.decode("utf-8", errors="ignore")

            corruption_markers = (
                "Invalid data found when processing input",
                "could not find codec parameters",
                "moov atom not found",
                "Unsupported codec",
                "No such file or directory",
                "Format not recognized",
            )
            if any(marker in output for marker in corruption_markers):
                return False, "File appears to be corrupted or in an unsupported format."

            if "Audio:" not in output:
                return False, "No readable audio stream found in this file."

            return True, ""
        except subprocess.TimeoutExpired:
            return False, "File validation timed out (file may be corrupted or unreadable)."
        except Exception as exc:
            logger.warning(f"Audio pre-flight validation error (allowing conversion attempt): {exc}")
            return True, ""

    def _get_duration(self, source: Path) -> float:
        """Get audio/video duration in seconds using the bundled ffmpeg.exe
        directly (via `-i <file>` and parsing the "Duration: HH:MM:SS.ss"
        line from stderr).

        Deliberately does NOT use ffmpeg-python's `ffmpeg.probe()`: that
        function shells out to a bare `"ffprobe"` executable, which is never
        bundled (imageio_ffmpeg only ships ffmpeg.exe) and is not expected to
        be on a user's PATH, so probing always failed silently and returned
        0.0 - which meant `progress_callback` was never invoked (its guard
        requires duration > 0), leaving the GUI progress bar stuck at 0% for
        the entire transcription even though work was proceeding normally.
        """
        try:
            ffmpeg_path = _get_ffmpeg_path()
            if ffmpeg_path == "ffmpeg":
                return 0.0

            kwargs: dict = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            result = subprocess.run(
                [ffmpeg_path, "-i", str(source)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                **kwargs,
            )
            # ffmpeg -i with no output file exits non-zero by design; the
            # stream info (including Duration) is printed to stderr.
            output = result.stderr.decode("utf-8", errors="ignore")
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", output)
            if not match:
                return 0.0
            hours, minutes, seconds, centiseconds = (int(g) for g in match.groups())
            return hours * 3600 + minutes * 60 + seconds + centiseconds / 100
        except Exception as exc:
            logger.debug(f"Duration probe failed (progress bar will show 0% only): {exc}")
            return 0.0

    def _load_model(self, model_size: str, progress_callback=None):
        """Lazily load a Whisper model as a singleton instance: only ONE
        model is ever resident in memory at a time, keyed by model_size.

        Switching to a different model_size evicts the previously cached
        instance and runs gc.collect() to actually release its memory
        (Whisper models range from ~75MB to ~3GB) before loading the new
        one, instead of letting an instance for every size the user has
        ever selected accumulate in `_model_cache` indefinitely.
        """
        try:
            if model_size in self._model_cache:
                logger.debug(f"Reusing cached model instance: {model_size}")
                return self._model_cache[model_size]

            if self._model_cache:
                evicted = list(self._model_cache.keys())
                self._model_cache.clear()
                gc.collect()
                logger.info(f"Evicted cached model(s) {evicted} before loading '{model_size}'")

            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise ConversionError(
                    "faster-whisper is required. Install via: pip install 'doc2md[audio]'"
                )

            # Auto hardware detection: prefer CUDA (float16) when CTranslate2
            # reports a usable device, otherwise CPU (int8) across all cores.
            # Device availability and successful model construction are two
            # different things - a driver/cuDNN mismatch only surfaces when the
            # model is actually built - so a CUDA failure falls back to CPU
            # instead of failing the whole conversion.
            attempts: list[dict] = []
            if self._has_gpu():
                attempts.append({"device": "cuda", "compute_type": "float16"})
            attempts.append({
                "device": "cpu",
                "compute_type": "int8",
                "cpu_threads": self._cpu_threads(),
            })

            last_error: Exception | None = None
            for model_kwargs in attempts:
                try:
                    logger.info(f"Loading '{model_size}' model with {model_kwargs}")
                    model = WhisperModel(model_size, **model_kwargs)
                except Exception as exc:
                    last_error = exc
                    if model_kwargs["device"] == "cuda":
                        logger.warning(
                            f"CUDA model load failed ({type(exc).__name__}: {exc}); "
                            "falling back to CPU"
                        )
                        continue
                    raise

                if model_kwargs["device"] == "cuda":
                    logger.info("🚀 GPU/CUDA acceleration active (float16)")
                else:
                    logger.info(
                        f"🔧 Using CPU with {model_kwargs['cpu_threads']} threads (int8)"
                    )
                self._model_cache[model_size] = model
                return model

            raise last_error or RuntimeError("no model backend available")
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

    @staticmethod
    def kill_all_ffmpeg_processes() -> None:
        """Forcefully terminate any FFmpeg processes spawned during
        transcription. Used by the GUI's Hard Exit Protocol to prevent
        zombie ffmpeg.exe processes from lingering after a forced shutdown.

        stdin is explicitly set to DEVNULL and CREATE_NO_WINDOW is passed on
        Windows: a --windowed PyInstaller build has no console (sys.stdin is
        None), and spawning a subprocess that tries to inherit a
        nonexistent/invalid std handle can hang instead of raising - which
        would block this call on the GUI main thread (it runs synchronously
        from the WM_DELETE_WINDOW handler) and make the window impossible to
        close while a conversion is active.
        """
        if sys.platform != "win32":
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "ffmpeg.exe", "/T"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            logger.warning(f"Failed to kill FFmpeg processes: {exc}")

    @staticmethod
    def cleanup_temp_audio_chunks() -> None:
        """Delete leftover temporary .wav chunk files from the system Temp
        folder. Best-effort cleanup invoked during the GUI's Hard Exit
        Protocol; failures are swallowed since this runs during shutdown."""
        try:
            temp_dir = Path(tempfile.gettempdir())
            for wav_file in temp_dir.glob("*.wav"):
                try:
                    wav_file.unlink()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning(f"Failed to clean up temp audio chunks: {exc}")

    @staticmethod
    def _has_gpu() -> bool:
        """Report whether CTranslate2 can run this model on a CUDA device.

        Must be asked of CTranslate2, not PyTorch: faster-whisper runs on
        CTranslate2 and never imports torch. Earlier releases probed
        ``torch.cuda.is_available()``, but torch is not a dependency of this
        project and is not installed, so the probe raised ModuleNotFoundError,
        got swallowed, and pinned every transcription to CPU on machines with
        a perfectly usable GPU - which is why "GPU Acceleration enabled" never
        actually took effect.
        """
        try:
            _register_cuda_dll_dirs()
            import ctranslate2

            if ctranslate2.get_cuda_device_count() <= 0:
                return False
            # A visible device is not the same as a loadable backend: without
            # the cuBLAS/cuDNN runtime the device query still reports 1 and the
            # failure only appears later, at model construction.
            return "float16" in ctranslate2.get_supported_compute_types("cuda")
        except Exception as exc:
            # A present-but-broken CUDA driver can raise from the device query
            # itself; treat any failure as "no usable GPU".
            logger.debug(f"CUDA detection failed, using CPU: {exc}")
            return False

    @classmethod
    def describe_device(cls) -> str:
        """Human-readable acceleration status for the GUI status log."""
        if cls._has_gpu():
            try:
                import ctranslate2

                count = ctranslate2.get_cuda_device_count()
                return f"GPU/CUDA ({count} device{'s' if count != 1 else ''}, float16)"
            except Exception:
                return "GPU/CUDA (float16)"
        return f"CPU ({cls._cpu_threads()} threads, int8)"

    @staticmethod
    def _cpu_threads() -> int:
        return os.cpu_count() or 4

    @classmethod
    def acceleration_hint(cls) -> str:
        """Advice shown when transcription is about to run on CPU.

        Distinguishes the two very different CPU-only cases: an NVIDIA card
        that merely lacks the CUDA runtime (fixable by installing the GPU pack)
        versus hardware CTranslate2 cannot use at all. CTranslate2 4.x exposes
        only `cpu` and `cuda` devices - there is no ROCm, HIP, DirectML or
        Vulkan backend - so AMD and Intel GPUs are permanently CPU-only and
        telling those users to install anything would be misleading.
        """
        if cls._has_gpu():
            return ""

        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                # Driver and device are visible; only the runtime is missing.
                return GPU_PACK_HINT
        except Exception:
            pass

        return (
            "Running on CPU. GPU acceleration requires an NVIDIA card - "
            "AMD and Intel GPUs are not supported for transcription."
        )

    def _format_output(
        self, source: Path, duration: float, segments: list, model_size: str,
        language: str = "auto",
    ) -> str:
        """Format transcription output as Markdown with timestamps."""
        lines = [
            f"# Transcription: {source.name}",
            "",
            f"- **Duration:** {self._format_time(duration)}",
            f"- **Model:** faster-whisper ({model_size})",
            f"- **Language:** {language}",
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
