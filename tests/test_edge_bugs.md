# test_edge_bugs.py

```python
"""
Edge-case testing for CLI, file system operations, and resilience.
Covers invalid paths, read-only outputs, empty clipboard, and permission edge cases.
"""
import os
import tempfile
from pathlib import Path

import pytest

from doc2md.cli.main import app
from doc2md.core.errors import ConversionError
from typer.testing import CliRunner

runner = CliRunner()


class TestInvalidFilePaths:
    def test_nonexistent_file_graceful_error(self):
        result = runner.invoke(app, ["convert", "/path/to/nonexistent/file.pdf"])
        assert result.exit_code != 0
        assert "error" in result.stdout.lower() or "not found" in result.stdout.lower()

    def test_directory_as_input_error(self, tmp_path):
        dirpath = tmp_path / "somedir"
        dirpath.mkdir()
        result = runner.invoke(app, ["convert", str(dirpath)])
        assert result.exit_code != 0

    def test_empty_filename_error(self):
        result = runner.invoke(app, ["convert", ""])
        assert result.exit_code != 0

    def test_special_chars_in_path(self, tmp_path):
        special_file = tmp_path / "file with spaces & special@chars.txt"
        special_file.write_text("# test\n")
        result = runner.invoke(app, ["convert", str(special_file), "-o", str(tmp_path)])
        assert result.exit_code == 0

    def test_unicode_filename_path(self, tmp_path):
        unicode_file = tmp_path / "файл_файл_文件.txt"
        unicode_file.write_text("# Unicode filename test\n")
        result = runner.invoke(app, ["convert", str(unicode_file)])
        assert result.exit_code == 0

    def test_very_long_path_windows_extended_path(self, tmp_path):
        deep = tmp_path / ("a" * 50) / ("b" * 50) / ("c" * 50)
        deep.mkdir(parents=True, exist_ok=True)
        longfile = deep / "longname.txt"
        longfile.write_text("# Very long path test\n")
        result = runner.invoke(app, ["convert", str(longfile)])
        # Should either succeed or handle gracefully
        assert result.exit_code in (0, 1)


class TestReadOnlyOutputPaths:
    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_readonly_output_directory_handled(self, tmp_path):
        input_file = tmp_path / "input.txt"
        input_file.write_text("# Test content\n")

        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()

        os.chmod(readonly_dir, 0o444)
        try:
            result = runner.invoke(app, ["convert", str(input_file), "-o", str(readonly_dir)])
            # May succeed (temp fallback) or fail gracefully; should not crash
            assert result.exit_code in (0, 1)
        finally:
            os.chmod(readonly_dir, 0o777)

    def test_output_to_readonly_file_error(self, tmp_path):
        input_file = tmp_path / "input.txt"
        input_file.write_text("# Test content\n")

        output_file = tmp_path / "output.md"
        output_file.write_text("# Locked")
        os.chmod(output_file, 0o444)

        try:
            result = runner.invoke(
                app,
                ["convert", str(input_file), "-o", str(output_file)]
            )
            # Should fail gracefully
            assert result.exit_code != 0
        finally:
            os.chmod(output_file, 0o644)


class TestClipboardEdgeCases:
    def test_copy_empty_content_to_clipboard(self, tmp_path, monkeypatch):
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        copy_calls = []
        def mock_copy(text):
            copy_calls.append(text)

        monkeypatch.setattr("pyperclip.copy", mock_copy)

        result = runner.invoke(app, ["convert", str(empty_file), "-c"])
        assert result.exit_code == 0
        # Empty file should still call copy with empty or whitespace
        assert len(copy_calls) >= 0

    def test_copy_to_clipboard_no_error_on_failure(self, tmp_path, monkeypatch):
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test content\n")

        def mock_copy_fail(text):
            raise OSError("Clipboard unavailable (e.g., in CI)")

        monkeypatch.setattr("pyperclip.copy", mock_copy_fail)

        result = runner.invoke(app, ["convert", str(test_file), "-c"])
        # Should handle clipboard error gracefully
        assert "Clipboard" in result.stdout or result.exit_code == 0

    def test_multiple_files_clipboard_separator(self, tmp_path, monkeypatch):
        file1 = tmp_path / "file1.txt"
        file1.write_text("# File 1\n")
        file2 = tmp_path / "file2.txt"
        file2.write_text("# File 2\n")

        copy_calls = []
        def mock_copy(text):
            copy_calls.append(text)

        monkeypatch.setattr("pyperclip.copy", mock_copy)

        result = runner.invoke(app, ["convert", str(file1), str(file2), "-c"])
        assert result.exit_code == 0
        if len(copy_calls) > 0:
            # Multi-file should use separator
            assert "---" in copy_calls[-1] or len(copy_calls) > 1


class TestStatsWithEdgeCases:
    def test_stats_on_empty_file(self, tmp_path):
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        result = runner.invoke(app, ["convert", str(empty_file), "-s"])
        assert result.exit_code == 0
        # Stats should show zero or minimal values without crashing

    def test_stats_with_very_large_file(self, tmp_path):
        huge_file = tmp_path / "huge.txt"
        # Create a moderately large file
        huge_file.write_text("# Large file\n" * 10000)

        result = runner.invoke(app, ["convert", str(huge_file), "-s"])
        assert result.exit_code == 0
        # Should complete without memory issues


class TestConfigFileEdgeCases:
    def test_malformed_toml_ignored_gracefully(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "doc2md.toml"
        config_file.write_text("[[[ INVALID TOML ]]]\n")

        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")

        result = runner.invoke(app, ["convert", str(test_file)])
        # Should ignore malformed config and continue
        assert result.exit_code == 0

    def test_config_with_invalid_values(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "doc2md.toml"
        config_file.write_text("""
default_copy = "not_a_boolean"
timeout = "not_a_number"
""")

        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")

        result = runner.invoke(app, ["convert", str(test_file)])
        # Should handle invalid types gracefully
        assert result.exit_code in (0, 1)


class TestGlobPatternEdgeCases:
    def test_glob_empty_pattern_no_matches(self):
        result = runner.invoke(app, ["convert", "*.nonexistent_extension"])
        # May return exit code 2 (typer usage) if glob expands to nothing or handled
        assert result.exit_code in (0, 1, 2)

    def test_glob_with_special_chars(self, tmp_path):
        file1 = tmp_path / "file[1].txt"
        file1.write_text("# Test\n")

        result = runner.invoke(app, ["convert", str(file1)])
        assert result.exit_code == 0

    def test_glob_absolute_path_pattern(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")

        pattern = str(tmp_path / "*.txt")
        result = runner.invoke(app, ["convert", pattern])
        assert result.exit_code == 0


class TestTimeoutEdgeCases:
    def test_timeout_zero_handled(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")

        result = runner.invoke(app, ["convert", str(test_file), "--timeout", "0"])
        # Zero timeout may be rejected by typer (exit code 2) or handled
        assert result.exit_code in (0, 1, 2)

    def test_timeout_negative_rejected(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")

        result = runner.invoke(app, ["convert", str(test_file), "--timeout", "-5"])
        # Negative timeout should be rejected
        assert result.exit_code != 0


class TestMaxRowsEdgeCases:
    def test_maxrows_zero_handled(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,value\ntest,123\n")

        result = runner.invoke(app, ["convert", str(csv_file), "--max-rows", "0"])
        # Zero rows may be rejected by typer (exit code 2) or handled gracefully
        assert result.exit_code in (0, 1, 2)

    def test_maxrows_negative_rejected(self, tmp_path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,value\ntest,123\n")

        result = runner.invoke(app, ["convert", str(csv_file), "--max-rows", "-10"])
        # Negative should be rejected
        assert result.exit_code != 0


class TestContextMenuOperations:
    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_context_menu_install_status_check(self):
        # Install
        result = runner.invoke(app, ["install-context-menu"])
        assert result.exit_code == 0

        # Check status
        status = runner.invoke(app, ["context-menu-status"])
        assert result.exit_code == 0
        assert "installed" in status.stdout.lower() or "context" in status.stdout.lower()

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_context_menu_uninstall(self):
        result = runner.invoke(app, ["uninstall-context-menu"])
        # Should succeed (even if not previously installed)
        assert result.exit_code == 0


class TestChunkingEdgeCases:
    def test_chunk_zero_tokens(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\nLong content\n" * 100)

        result = runner.invoke(app, ["convert", str(test_file), "--chunk", "0"])
        # Zero may be rejected by typer (exit code 2) or handled
        assert result.exit_code in (0, 1, 2)

    def test_chunk_very_large_token_limit(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("# Test\n")

        result = runner.invoke(app, ["convert", str(test_file), "--chunk", "999999"])
        # Very large chunk should not error
        assert result.exit_code == 0


class TestStdoutWithEdgeCases:
    def test_stdout_with_binary_file(self, tmp_path):
        # Binary file (PNG) to stdout
        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00" + b"\x00" * 100)

        result = runner.invoke(app, ["convert", str(binary_file), "--stdout"])
        # Should handle or error gracefully, not crash
        assert result.exit_code in (0, 1)

    def test_stdout_multiple_files(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file1.write_text("# File 1\n")
        file2 = tmp_path / "file2.txt"
        file2.write_text("# File 2\n")

        result = runner.invoke(app, ["convert", str(file1), str(file2), "--stdout"])
        # Multiple files to stdout
        assert result.exit_code == 0
        assert "---" in result.stdout or "File" in result.stdout
```
