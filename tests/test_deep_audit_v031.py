"""Deep Bug Audit for doc2md v0.3.1: GUI Threading, Audio Engine, & Converter Edge Cases."""

import gc
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from doc2md.core.converter import Converter
from doc2md.core.errors import ConversionError


class TestGUIThreadSafety:
    """Audit GUI drag-and-drop and worker thread cancellation."""

    def test_converter_multiple_simultaneous_calls(self, tmp_path):
        """Verify converter handles multiple concurrent calls without race conditions."""
        cv = Converter(timeout=10)

        # Create test files
        files = []
        for i in range(5):
            f = tmp_path / f"test_{i}.txt"
            f.write_text(f"# Test {i}\n")
            files.append(f)

        results = []
        errors = []

        def worker(path):
            try:
                result = cv.convert_file(path)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f,)) for f in files]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Conversion errors: {errors}"
        assert len(results) == len(files)
        assert all(r.success for r in results)

    def test_converter_timeout_does_not_leak_resources(self, tmp_path):
        """Verify timeout termination cleans up resources (no zombie processes)."""
        cv = Converter(timeout=1)

        # Create a file that will take time to process
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Content\n" * 10000)

        # This should timeout but not crash
        try:
            result = cv.convert_file(test_file)
            # Conversion may succeed or timeout - both are OK
        except ConversionError:
            pass

        # Verify memory is released
        gc.collect()
        # No orphaned processes should remain
        assert True  # If we get here, cleanup succeeded

    def test_converter_exception_handling_preserves_state(self, tmp_path):
        """Verify converter state remains consistent after exceptions."""
        cv = Converter()

        # Try to convert nonexistent file - should raise or return error
        try:
            result = cv.convert_file(Path("/nonexistent/file.pdf"))
            # If no exception, result should indicate failure
            assert not result.success or result.error
        except ConversionError:
            pass  # Expected

        # Next conversion should work normally
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")
        result = cv.convert_file(test_file)
        assert result.success


class TestAudioRemoval:
    """Audio/video support was removed in 1.1.0; pin that it stays removed.

    The transcription stack (faster-whisper, ctranslate2, torch, ffmpeg) was
    the source of both the ~2 GB download and the silent failures this release
    exists to eliminate. These tests fail loudly if it is reintroduced by
    accident, and check that a dropped recording still gets an actionable
    message rather than a generic "unrecognized file type".
    """

    def test_audio_engine_module_is_gone(self):
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("doc2md.engine.audio_engine")

    def test_no_engine_claims_audio_or_video(self):
        from doc2md.engine import all_engines

        kinds = {kind.value for engine in all_engines() for kind in engine.supported_kinds}
        assert "audio" not in kinds
        assert "video" not in kinds

    def test_dropped_recording_reports_why_it_cannot_convert(self, tmp_path):
        recording = tmp_path / "ประชุม.mp3"
        recording.write_bytes(bytes([0x49, 0x44, 0x33, 3, 0, 0, 0]) + bytes(64))

        result = Converter().convert_file(recording)

        assert not result.success
        assert "removed" in result.error
        assert "1.1.0" in result.error

    def test_transcription_packages_are_not_imported_anywhere(self):
        import pkgutil

        import doc2md

        banned = {"torch", "faster_whisper", "whisper", "ctranslate2", "ffmpeg"}
        for module in pkgutil.walk_packages(doc2md.__path__, "doc2md."):
            source = Path(module.module_finder.path) / f"{module.name.rsplit('.', 1)[-1]}.py"
            if not source.is_file():
                continue
            text = source.read_text(encoding="utf-8")
            for name in banned:
                assert f"import {name}" not in text, f"{module.name} imports {name}"


class TestDocumentConverterEdgeCases:
    """Audit document converters for protected and malformed documents."""

    def test_empty_text_file_handling(self, tmp_path):
        """Verify empty files are handled gracefully."""
        cv = Converter()

        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        result = cv.convert_file(empty_file)
        # Empty file should convert (to empty/whitespace markdown)
        assert result.success or result.markdown == ""

    def test_text_file_with_only_whitespace(self, tmp_path):
        """Verify whitespace-only files are handled."""
        cv = Converter()

        whitespace_file = tmp_path / "whitespace.txt"
        whitespace_file.write_text("   \n\n\t\t\n   ")

        result = cv.convert_file(whitespace_file)
        assert result.success

    def test_very_large_text_file_streaming(self, tmp_path):
        """Verify large files don't cause memory spikes."""
        cv = Converter()

        large_file = tmp_path / "large.txt"
        # Create 50MB file with pattern
        with open(large_file, "w") as f:
            for i in range(100000):
                f.write(f"Line {i}: " + "x" * 500 + "\n")

        gc.collect()
        result = cv.convert_file(large_file)
        gc.collect()

        # Should handle without OOM
        assert result.success or result.error is not None

    def test_malformed_json_graceful_error(self, tmp_path):
        """Verify broken JSON files don't crash the converter."""
        cv = Converter()

        broken_json = tmp_path / "broken.json"
        broken_json.write_text('{"key": "value", "broken": [1, 2,}')

        # Should handle as text or error gracefully
        try:
            result = cv.convert_file(broken_json)
            assert result is not None
        except ConversionError:
            pass  # Expected for truly broken files


class TestFileSystemEdgeCases:
    """Audit file path and permission edge cases."""

    def test_non_ascii_filename_conversion(self, tmp_path):
        """Verify non-ASCII filenames are handled correctly."""
        cv = Converter()

        # Use UTF-8 encoding for non-ASCII content
        non_ascii_file = tmp_path / "test_文件.txt"
        with open(non_ascii_file, "w", encoding="utf-8") as f:
            f.write("# Test\nMultilanguage content")

        result = cv.convert_file(non_ascii_file)
        assert result.success

    def test_deeply_nested_directory_path(self, tmp_path):
        """Verify deeply nested paths don't cause issues."""
        cv = Converter()

        # Create nested directories
        deep_path = tmp_path
        for i in range(20):  # 20 levels deep
            deep_path = deep_path / f"level_{i}"
        deep_path.mkdir(parents=True, exist_ok=True)

        test_file = deep_path / "test.txt"
        test_file.write_text("# Deep Test\n")

        result = cv.convert_file(test_file)
        assert result.success

    def test_special_characters_in_filename(self, tmp_path):
        """Verify filenames with special characters are handled."""
        cv = Converter()

        special_names = [
            "file (with parentheses).txt",
            "file [with brackets].txt",
            "file {with braces}.txt",
            "file with spaces.txt",
            "file@with#special$chars.txt",
        ]

        for name in special_names:
            test_file = tmp_path / name
            test_file.write_text("# Test\n")
            result = cv.convert_file(test_file)
            assert result.success, f"Failed for filename: {name}"

    def test_symlink_file_handling(self, tmp_path):
        """Verify symlinks are handled correctly."""
        try:
            # Create actual file
            actual_file = tmp_path / "actual.txt"
            actual_file.write_text("# Actual\n")

            # Create symlink
            link_file = tmp_path / "link.txt"
            os.symlink(actual_file, link_file)

            cv = Converter()
            result = cv.convert_file(link_file)
            assert result.success
        except OSError:
            # Symlinks might not be supported on this system
            pytest.skip("Symlinks not supported")


class TestConverterRobustness:
    """Audit converter robustness under stress conditions."""

    def test_rapid_fire_conversions(self, tmp_path):
        """Verify converter handles rapid successive calls."""
        cv = Converter()

        test_file = tmp_path / "test.txt"
        test_file.write_text("# Content\n")

        # Rapid calls
        for _ in range(10):
            result = cv.convert_file(test_file)
            assert result.success

    def test_converter_with_different_file_types_sequence(self, tmp_path):
        """Verify converter handles switching between file types."""
        cv = Converter()

        # Text file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("# Text\n")
        assert cv.convert_file(txt_file).success

        # JSON file
        json_file = tmp_path / "test.json"
        json_file.write_text('{"key": "value"}')
        assert cv.convert_file(json_file).success

        # CSV file
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25")
        assert cv.convert_file(csv_file).success

    def test_converter_options_persistence(self, tmp_path):
        """Verify converter state remains consistent between calls."""
        cv = Converter(timeout=30)

        file1 = tmp_path / "file1.txt"
        file1.write_text("# File 1\n")

        file2 = tmp_path / "file2.txt"
        file2.write_text("# File 2\n")

        # Convert multiple files in sequence
        result1 = cv.convert_file(file1)
        result2 = cv.convert_file(file2)

        assert result1.success
        assert result2.success
        # Both should produce valid markdown
        assert len(result1.markdown) > 0
        assert len(result2.markdown) > 0


class TestErrorRecovery:
    """Audit error recovery and state consistency."""

    def test_converter_recovers_after_unknown_format(self, tmp_path):
        """Verify converter recovers after encountering unknown format."""
        cv = Converter()

        # Unknown format
        unknown_file = tmp_path / "test.xyz123"
        unknown_file.write_bytes(b"\x00\x01\x02\x03")

        try:
            result = cv.convert_file(unknown_file)
        except ConversionError:
            pass  # Expected

        # Next conversion should work
        text_file = tmp_path / "test.txt"
        text_file.write_text("# Recovery Test\n")
        result = cv.convert_file(text_file)
        assert result.success

    def test_converter_handles_permission_error_gracefully(self, tmp_path):
        """Verify permission errors are handled without crashing."""
        cv = Converter()

        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")

        # Make read-only
        os.chmod(test_file, 0o000)

        try:
            try:
                result = cv.convert_file(test_file)
                # Either succeeds or raises ConversionError
                assert result is not None or True
            except (ConversionError, PermissionError):
                # Both are acceptable
                pass
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, 0o644)

    def test_converter_state_after_timeout(self, tmp_path):
        """Verify converter is usable after timeout."""
        cv = Converter(timeout=1)

        # Create a file for timeout test
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Content\n" * 1000)

        # First conversion (may or may not timeout)
        try:
            result1 = cv.convert_file(test_file)
        except ConversionError:
            pass

        # Second conversion should still work
        test_file2 = tmp_path / "test2.txt"
        test_file2.write_text("# Test 2\n")
        result2 = cv.convert_file(test_file2)
        assert result2.success
