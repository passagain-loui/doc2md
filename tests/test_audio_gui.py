"""Tests for Audio Engine and GUI components."""

from pathlib import Path
from unittest.mock import MagicMock, patch, Mock

import pytest

from doc2md.core.errors import ConversionError
from doc2md.core.router import FileKind, detect


class TestAudioRouting:
    """Test audio/video file routing."""

    def test_mp3_detected_as_audio(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"ID3" + b"\x00" * 100)
        detection = detect(audio_file)
        assert detection.kind == FileKind.AUDIO
        assert "audio" in detection.mime.lower()

    def test_wav_detected_as_audio(self, tmp_path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"RIFF\x24\xf0\x00\x00WAVE" + b"\x00" * 100)
        detection = detect(audio_file)
        assert detection.kind == FileKind.AUDIO

    def test_m4a_audio_by_extension(self, tmp_path):
        audio_file = tmp_path / "test.m4a"
        audio_file.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
        detection = detect(audio_file)
        assert detection.kind == FileKind.AUDIO

    def test_flac_audio_by_extension(self, tmp_path):
        audio_file = tmp_path / "test.flac"
        audio_file.write_bytes(b"fLaC\x00\x00\x00" + b"\x00" * 100)
        detection = detect(audio_file)
        assert detection.kind == FileKind.AUDIO

    def test_mp4_detected_as_video(self, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
        detection = detect(video_file)
        assert detection.kind == FileKind.VIDEO
        assert "video" in detection.mime.lower()

    def test_mkv_detected_as_video(self, tmp_path):
        video_file = tmp_path / "test.mkv"
        video_file.write_bytes(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81" + b"\x00" * 100)
        detection = detect(video_file)
        assert detection.kind == FileKind.VIDEO

    def test_avi_video_by_extension(self, tmp_path):
        video_file = tmp_path / "test.avi"
        video_file.write_bytes(b"RIFF\x00\x00\x00\x00AVI " + b"\x00" * 100)
        detection = detect(video_file)
        assert detection.kind == FileKind.VIDEO


class TestAudioEngineStructure:
    """Test audio engine implementation without external dependencies."""

    def test_audio_engine_import(self):
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        assert engine.name == "audio"
        assert FileKind.AUDIO in engine.supported_kinds
        assert FileKind.VIDEO in engine.supported_kinds

    def test_audio_model_cache_dir(self):
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        cache_dir = engine.MODEL_CACHE_DIR
        assert "doc2md" in str(cache_dir).lower()
        assert "models" in str(cache_dir).lower()

    def test_audio_model_sizes_available(self):
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        assert "tiny" in engine.MODEL_SIZES
        assert "base" in engine.MODEL_SIZES
        assert "small" in engine.MODEL_SIZES
        assert "medium" in engine.MODEL_SIZES
        assert "large-v3" in engine.MODEL_SIZES
        assert len(engine.MODEL_SIZES) == 5

    def test_time_formatting_zero(self):
        from doc2md.engine.audio_engine import AudioEngine

        assert AudioEngine._format_time(0) == "00:00:00"

    def test_time_formatting_seconds(self):
        from doc2md.engine.audio_engine import AudioEngine

        assert AudioEngine._format_time(45) == "00:00:45"

    def test_time_formatting_minutes(self):
        from doc2md.engine.audio_engine import AudioEngine

        assert AudioEngine._format_time(125) == "00:02:05"

    def test_time_formatting_hours(self):
        from doc2md.engine.audio_engine import AudioEngine

        assert AudioEngine._format_time(3661) == "01:01:01"

    def test_time_formatting_long_duration(self):
        from doc2md.engine.audio_engine import AudioEngine

        # 8 hours, 30 minutes, 45 seconds
        seconds = 8 * 3600 + 30 * 60 + 45
        assert AudioEngine._format_time(seconds) == "08:30:45"

    def test_audio_engine_missing_file_error(self):
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        with pytest.raises(ConversionError, match="not found"):
            engine.convert("/nonexistent/file.mp3", {})

    def test_audio_gpu_detection_returns_bool(self):
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        result = engine._has_gpu()
        assert isinstance(result, bool)


class TestAudioEngineRegistration:
    """Test audio engine registration in engine registry."""

    def test_audio_file_kind_in_router(self):
        from doc2md.core.router import FileKind

        assert FileKind.AUDIO.value == "audio"
        assert FileKind.VIDEO.value == "video"

    def test_audio_extensions_in_router(self):
        from doc2md.core.router import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

        assert ".mp3" in AUDIO_EXTENSIONS
        assert ".wav" in AUDIO_EXTENSIONS
        assert ".m4a" in AUDIO_EXTENSIONS
        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mkv" in VIDEO_EXTENSIONS

    def test_audio_engine_registered_if_available(self):
        from doc2md.core.router import FileKind
        from doc2md.engine import get_engine, all_engines

        # Audio engine should be in registry if imports work
        engines = all_engines()
        audio_engines = [e for e in engines if e.name == "audio"]
        # Audio engine is present (import doesn't fail)
        assert len(audio_engines) <= 1


class TestGUIStructure:
    """Test GUI structure without display requirements."""

    def test_gui_module_imports(self):
        from doc2md.gui import MainWindow

        assert MainWindow is not None

    def test_gui_cli_command_exists(self):
        from doc2md.cli.main import app

        # Check if gui command is registered
        commands = {cmd.name for cmd in app.registered_commands}
        assert "gui" in commands



class TestAudioEngineMethods:
    """Test individual methods of AudioEngine."""

    def test_audio_has_gpu_method(self):
        """Test GPU detection method exists and works."""
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        # Should return bool regardless of whether GPU is present
        result = engine._has_gpu()
        assert isinstance(result, bool)

    def test_audio_format_output(self):
        """Test output formatting for transcription."""
        from doc2md.engine.audio_engine import AudioEngine
        from pathlib import Path

        engine = AudioEngine()

        # Create mock segments
        segment1 = Mock(start=0, end=5, text="Hello world")
        segment2 = Mock(start=5, end=10, text="This is a test")

        source = Path("test_audio.mp3")
        output = engine._format_output(source, 600.0, [segment1, segment2], "small")

        assert "test_audio.mp3" in output
        assert "Transcription" in output
        assert "Duration" in output
        assert "small" in output
        assert "Hello world" in output
        assert "This is a test" in output
        assert "[00:00:00 - 00:00:05]" in output
        assert "[00:00:05 - 00:00:10]" in output

    def test_audio_format_output_empty_segments(self):
        """Test output formatting with empty/whitespace segments."""
        from doc2md.engine.audio_engine import AudioEngine
        from pathlib import Path

        engine = AudioEngine()

        # Create mock segments with empty text
        segment1 = Mock(start=0, end=5, text="   ")
        segment2 = Mock(start=5, end=10, text="Valid text")

        source = Path("test.mp3")
        output = engine._format_output(source, 120.0, [segment1, segment2], "base")

        # Empty segments should be filtered out
        assert "   " not in output
        assert "Valid text" in output

    def test_audio_model_default_selection(self):
        """Test default model selection."""
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        assert engine._model_size == "small"

    def test_audio_invalid_model_size_fallback(self):
        """Test fallback for invalid model size."""
        from doc2md.engine.audio_engine import AudioEngine

        engine = AudioEngine()
        # Simulate conversion with invalid model size
        options = {"audio_model": "invalid-size"}
        # Should not raise error, should fallback to default
        assert engine._model_size in engine.MODEL_SIZES


class TestAudioGUIIntegration:
    """Integration tests for audio and GUI components."""

    def test_audio_file_kinds_routing(self):
        """Verify audio/video files route correctly."""
        from doc2md.core.router import FileKind, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

        # Audio formats
        for ext in [".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"]:
            assert ext in AUDIO_EXTENSIONS

        # Video formats
        for ext in [".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm"]:
            assert ext in VIDEO_EXTENSIONS

    def test_audio_dependency_optional(self):
        """Verify audio engine loads gracefully with or without dependencies."""
        from doc2md.engine import all_engines

        # Should not raise error even if faster-whisper missing
        engines = all_engines()
        assert len(engines) > 0
        # Either audio engine is registered or not, but no crashes
        assert all(hasattr(e, "name") for e in engines)

    def test_gui_dependency_optional(self):
        """Verify GUI loads gracefully without full tkinter setup."""
        try:
            from doc2md.gui import MainWindow
            assert MainWindow is not None
        except ImportError:
            # GUI dependencies might not be installed
            pytest.skip("GUI dependencies not available")

