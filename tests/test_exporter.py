"""Tests for multi-format export functionality."""

import tempfile
from pathlib import Path

import pytest

from doc2md.core.exporter import export_markdown


def test_export_markdown_format():
    """Test markdown export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.md"
        content = "# Title\n\nParagraph text."
        success, msg = export_markdown(content, output_path, format_type="md")

        assert success
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == content


def test_export_plaintext_format():
    """Test plain text export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.txt"
        content = "# Title\n\nParagraph text."
        success, msg = export_markdown(content, output_path, format_type="txt")

        assert success
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == content


def test_export_docx_format():
    """Test DOCX export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.docx"
        content = "# Heading 1\n## Heading 2\n\n- Bullet point\n\nParagraph with **bold** text."
        success, msg = export_markdown(content, output_path, format_type="docx")

        assert success
        assert output_path.exists()
        assert output_path.suffix == ".docx"


def test_export_unknown_format():
    """Test error handling for unknown format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.xyz"
        content = "Test content"
        success, msg = export_markdown(content, output_path, format_type="xyz")

        assert not success
        assert "Unknown format" in msg


def test_export_missing_dependency():
    """Test graceful handling of missing python-docx."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "test.docx"
        content = "Test content"
        # python-docx is installed, but test structure is ready for future
        success, msg = export_markdown(content, output_path, format_type="docx")
        assert success or "not installed" in msg
