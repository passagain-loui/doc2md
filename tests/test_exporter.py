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


# --- Milestone 7 item 6: forced write failures must not touch an existing ---------
# --- destination, and must go through the same atomic writer as everything --------
# --- else in the application. -----------------------------------------------------


def test_md_export_failure_leaves_existing_file_intact(tmp_path, monkeypatch):
    import doc2md.core.exporter as exporter_module

    output_path = tmp_path / "existing.md"
    output_path.write_text("ORIGINAL CONTENT", encoding="utf-8")

    def boom(path, content, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(exporter_module, "atomic_write_text", boom)

    success, msg = export_markdown("NEW CONTENT", output_path, format_type="md")

    assert success is False
    assert "Export error" in msg
    assert output_path.read_text(encoding="utf-8") == "ORIGINAL CONTENT"
    # no stray temp file left behind in the directory
    assert sorted(p.name for p in tmp_path.iterdir()) == ["existing.md"]


def test_txt_export_failure_leaves_existing_file_intact(tmp_path, monkeypatch):
    import doc2md.core.exporter as exporter_module

    output_path = tmp_path / "existing.txt"
    output_path.write_text("ORIGINAL", encoding="utf-8")

    def boom(path, content, **kwargs):
        raise OSError("simulated permission denied")

    monkeypatch.setattr(exporter_module, "atomic_write_text", boom)

    success, msg = export_markdown("NEW", output_path, format_type="txt")

    assert success is False
    assert output_path.read_text(encoding="utf-8") == "ORIGINAL"


def test_docx_export_failure_leaves_existing_file_intact_and_no_temp_remains(tmp_path, monkeypatch):
    from docx import Document

    output_path = tmp_path / "existing.docx"
    original_doc = Document()
    original_doc.add_paragraph("original body")
    original_doc.save(str(output_path))
    original_bytes = output_path.read_bytes()

    def boom_replace(*args, **kwargs):
        raise OSError("simulated failure during publish")

    import doc2md.core.exporter as exporter_module

    monkeypatch.setattr(exporter_module.os, "replace", boom_replace)

    success, msg = export_markdown("# New heading\n\nNew body", output_path, format_type="docx")

    assert success is False
    assert "Export error" in msg
    assert output_path.read_bytes() == original_bytes, "existing docx must be untouched"
    # no stray .existing.docx.*.tmp file left behind
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "existing.docx"]
    assert leftovers == []


def test_docx_export_actually_uses_a_temp_file_then_replace(tmp_path, monkeypatch):
    """Confirms the docx path really goes through the same
    temp-file-then-os.replace pattern as every other writer, not a direct
    Document.save(output_path)."""
    import doc2md.core.exporter as exporter_module

    output_path = tmp_path / "fresh.docx"
    replace_calls = []
    real_replace = exporter_module.os.replace

    def spy_replace(src, dst):
        # at the moment of replace, the final destination must not exist yet
        # (this call is what creates it) - proves save() targeted a temp path.
        replace_calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(exporter_module.os, "replace", spy_replace)

    success, _msg = export_markdown("# Heading\n\nBody text", output_path, format_type="docx")

    assert success is True
    assert len(replace_calls) == 1
    src, dst = replace_calls[0]
    assert Path(dst) == output_path
    assert Path(src) != output_path
    assert output_path.exists()
