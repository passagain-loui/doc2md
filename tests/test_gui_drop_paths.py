"""Drag-and-drop path handling for the PyQt6 interface.

The Tk implementation received one flat, brace-delimited string and had to
re-tokenize it; that parser ate backslashes and mangled Thai names, so every
drop reported "No supported files". Qt hands over a list of ``QUrl`` objects
instead, so these tests pin the property that matters now: whatever the file
is called - Thai, spaces, ``#``/``&``/``%``, a very long name - the path that
comes back out of the drop handler is byte-for-byte the path that went in.
"""

from __future__ import annotations

import pickle
import threading
from pathlib import Path

import pytest

from doc2md.core.converter import _picklable_options

pytest.importorskip("PyQt6.QtCore")

from PyQt6.QtCore import QUrl  # noqa: E402

from doc2md.gui.main_window import DropZone, collect_files  # noqa: E402


AWKWARD_NAMES = [
    "รายงานประจำปี 2567.pdf",
    "report with spaces.pdf",
    "budget#1 &final (100%).pdf",
    "ใบเสนอราคา - ฉบับแก้ไข.pdf",
    "a'quote-mix (v2).pdf",
    "ผลตรวจ_ผู้ป่วย+เพิ่มเติม.pdf",
]


def _make(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4\n%stub\n")
    return path


@pytest.mark.parametrize("name", AWKWARD_NAMES)
def test_qurl_round_trip_preserves_exact_path(tmp_path, name):
    source = _make(tmp_path, name)
    url = QUrl.fromLocalFile(str(source))

    recovered = DropZone.paths_from_urls([url])

    assert recovered == [source]
    assert recovered[0].name == name
    assert recovered[0].is_file()


def test_backslashes_survive_a_windows_style_path(tmp_path):
    """``C:\\a\\one.pdf`` must not become ``C:\\x07ne.pdf``.

    Both splitters the Tk version tried applied escape processing: shlex ate
    the backslashes outright, and Tcl's ``splitlist`` expanded ``\\a`` into the
    bell character. Qt performs no escape processing at all.
    """
    nested = tmp_path / "a" / "one.pdf"
    nested.parent.mkdir()
    nested.write_bytes(b"%PDF-1.4\n")

    recovered = DropZone.paths_from_urls([QUrl.fromLocalFile(str(nested))])

    assert recovered == [nested]
    assert "\a" not in str(recovered[0])
    assert recovered[0].read_bytes().startswith(b"%PDF")


def test_multiple_files_dropped_together_are_all_kept(tmp_path):
    sources = [_make(tmp_path, name) for name in AWKWARD_NAMES]
    urls = [QUrl.fromLocalFile(str(p)) for p in sources]

    recovered = DropZone.paths_from_urls(urls)

    assert recovered == sources


def test_remote_urls_are_ignored(tmp_path):
    local = _make(tmp_path, "local.pdf")
    urls = [
        QUrl("https://example.invalid/remote.pdf"),
        QUrl.fromLocalFile(str(local)),
    ]

    assert DropZone.paths_from_urls(urls) == [local]


def test_collect_files_walks_folders_and_reports_rejects(tmp_path):
    folder = tmp_path / "เอกสาร"
    folder.mkdir()
    good = _make(folder, "งบประมาณ.pdf")
    (folder / "recording.mp3").write_bytes(b"ID3\x03\x00\x00\x00")

    accepted, rejected = collect_files([folder])

    assert accepted == [good]
    assert rejected == []  # unsupported children are filtered, not reported


def test_collect_files_reports_dropped_media_explicitly(tmp_path):
    media = tmp_path / "meeting.mp3"
    media.write_bytes(b"ID3\x03\x00\x00\x00")

    accepted, rejected = collect_files([media])

    assert accepted == []
    assert len(rejected) == 1
    path, reason = rejected[0]
    assert path == media
    assert "removed" in reason


def test_collect_files_deduplicates_the_same_file(tmp_path):
    source = _make(tmp_path, "same.pdf")

    accepted, _rejected = collect_files([source, source, tmp_path / "same.pdf"])

    assert accepted == [source]


def test_collect_files_reports_missing_paths(tmp_path):
    ghost = tmp_path / "ไม่มีจริง.pdf"

    accepted, rejected = collect_files([ghost])

    assert accepted == []
    assert rejected == [(ghost, "not found")]


# --- converter option safety -------------------------------------------------


def test_unpicklable_options_are_stripped_for_isolated_engines():
    """Options crossing a spawn boundary must survive pickling.

    The GUI legitimately holds live objects; anything that cannot cross a
    process boundary has to be filtered before Process.start(), or every
    PDF/OCR conversion started from the GUI dies at launch.
    """
    options = {
        "max_rows": 10,
        "ocr_lang": "tha+eng",
        "event": threading.Event(),
        "callback": (lambda value: value),
    }

    safe = _picklable_options(options)

    assert safe == {"max_rows": 10, "ocr_lang": "tha+eng"}
    pickle.dumps(safe)
