"""Regression tests for the GUI drop-path parser and converter option safety.

These cover the two defects that made v1.0.20-v1.0.24 unusable in practice:

* ``shlex.split`` silently ate every backslash in a Windows path, so every
  drag & drop reported "No supported files".
* The GUI put a bound method (``progress_callback``) into converter options,
  which cannot be pickled, so every process-isolated conversion (PDF, OCR)
  failed at ``Process.start()``.
"""

from __future__ import annotations

import pickle
import threading

import pytest

from doc2md.core.converter import _picklable_options
from doc2md.gui.main_window import MainWindow


parse = MainWindow._parse_drop_paths


def test_windows_backslash_path_survives_parsing():
    raw = r"C:\Users\Passagain\Documents\test.mp3"
    assert parse(raw) == [raw]


def test_path_with_spaces_stays_one_entry():
    raw = r"{C:\Users\Passagain\Documents\my recording.mp3}"
    assert parse(raw) == [r"C:\Users\Passagain\Documents\my recording.mp3"]


def test_thai_filename_survives_parsing():
    raw = "C:\\Users\\Passagain\\Documents\\ประชุม.mp3"
    assert parse(raw) == [raw]


def test_multiple_paths_split_correctly():
    raw = r"C:\a\one.pdf {C:\b\two file.docx} C:\c\three.mp3"
    assert parse(raw) == [
        r"C:\a\one.pdf",
        r"C:\b\two file.docx",
        r"C:\c\three.mp3",
    ]


@pytest.mark.parametrize(
    "raw",
    [
        r"C:\a\one.pdf",          # \a would become the bell character
        r"C:\b\two.pdf",          # \b would become backspace
        r"C:\temp\notes.pdf",     # \t would become a tab
        r"C:\new\report.pdf",     # \n would become a newline
        r"C:\report\v1.pdf",      # \v would become a vertical tab
    ],
)
def test_escape_like_sequences_are_not_substituted(raw):
    """Backslash sequences that Tcl/shlex would substitute must stay literal."""
    assert parse(raw) == [raw]


def test_unbraced_path_with_spaces_is_kept_whole(tmp_path):
    target = tmp_path / "meeting notes 2026.mp3"
    target.write_bytes(b"")
    assert parse(str(target)) == [str(target)]


def test_empty_payload_yields_nothing():
    assert parse("") == []
    assert parse("   ") == []


def test_unique_output_path_avoids_collision(tmp_path):
    (tmp_path / "report.md").write_text("first", encoding="utf-8")

    second = MainWindow._unique_output_path(tmp_path, "report", ".md")

    assert second == tmp_path / "report-1.md"
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == "first"


def test_picklable_options_strips_unpicklable_values():
    def callback(percent):  # a local function is unpicklable, like a bound method
        return percent

    options = {
        "audio_model": "small",
        "language": "Thai",
        "pdf_ocr_fallback": True,
        "progress_callback": callback,
        "abort_event": threading.Event(),
    }

    safe = _picklable_options(options)

    assert safe == {
        "audio_model": "small",
        "language": "Thai",
        "pdf_ocr_fallback": True,
    }
    pickle.dumps(safe)  # must not raise


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0:00"),
        (5, "0:05"),
        (65, "1:05"),
        (1621.7, "27:01"),
        (3600, "1:00:00"),
        (3725, "1:02:05"),
        (-10, "0:00"),
    ],
)
def test_format_clock(seconds, expected):
    """Long recordings must read as time, not a percentage that barely moves."""
    assert MainWindow._format_clock(seconds) == expected
