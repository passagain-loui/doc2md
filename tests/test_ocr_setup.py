"""Finding Tesseract and installing it with Thai data - with every external step faked."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from doc2md.core import ocr_setup
from doc2md.core.ocr_setup import (
    MIN_TRAINEDDATA_BYTES,
    SetupResult,
    find_tesseract,
    install_ocr,
    prepare_tesseract,
)


def _fake_binary(tmp_path) -> Path:
    binary = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    binary.parent.mkdir()
    binary.write_bytes(b"MZ")
    return binary


# --------------------------------------------------------------------- finding


def test_find_tesseract_prefers_path(monkeypatch):
    monkeypatch.setattr(ocr_setup.shutil, "which", lambda name: "C:/on/path/tesseract.exe")

    assert find_tesseract() == "C:/on/path/tesseract.exe"


def test_find_tesseract_falls_back_to_the_usual_install_folder(monkeypatch, tmp_path):
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(ocr_setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(ocr_setup, "KNOWN_LOCATIONS", [tmp_path / "missing.exe", binary])

    assert find_tesseract() == str(binary)


def test_find_tesseract_returns_none_when_it_is_nowhere(monkeypatch):
    monkeypatch.setattr(ocr_setup.shutil, "which", lambda name: None)

    assert find_tesseract() is None


def test_prepare_tesseract_does_nothing_when_not_installed(monkeypatch):
    monkeypatch.setattr(ocr_setup.shutil, "which", lambda name: None)

    assert prepare_tesseract("tha+eng") is None
    assert "TESSDATA_PREFIX" not in os.environ


def test_prepare_points_pytesseract_at_a_binary_off_the_path(monkeypatch, tmp_path):
    pytesseract = pytest.importorskip("pytesseract")
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(ocr_setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(ocr_setup, "KNOWN_LOCATIONS", [binary])
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")

    assert prepare_tesseract("eng") == str(binary)
    assert pytesseract.pytesseract.tesseract_cmd == str(binary)


def test_prepare_uses_the_user_data_folder_only_when_it_holds_every_language(monkeypatch, tmp_path):
    binary = _fake_binary(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    (data / "eng.traineddata").write_bytes(bytes(MIN_TRAINEDDATA_BYTES))
    monkeypatch.setattr(ocr_setup, "KNOWN_LOCATIONS", [binary])
    monkeypatch.setattr(ocr_setup, "user_tessdata_dir", lambda: data)
    monkeypatch.setattr(ocr_setup.shutil, "which", lambda name: None)

    prepare_tesseract("tha+eng")
    assert "TESSDATA_PREFIX" not in os.environ  # tha is missing

    (data / "tha.traineddata").write_bytes(bytes(MIN_TRAINEDDATA_BYTES))
    prepare_tesseract("tha+eng")
    assert os.environ["TESSDATA_PREFIX"] == str(data)


# ------------------------------------------------------------------- installing


class _Recorder:
    def __init__(self):
        self.downloads: list[tuple[str, Path]] = []
        self.winget_calls = 0

    def downloader(self, url: str, destination: Path) -> None:
        self.downloads.append((url, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(bytes(MIN_TRAINEDDATA_BYTES))

    def winget(self, _exe: str) -> subprocess.CompletedProcess:
        self.winget_calls += 1
        return subprocess.CompletedProcess([], 0, "ok", "")


@pytest.fixture
def data_dir(monkeypatch, tmp_path):
    folder = tmp_path / "userdata"
    monkeypatch.setattr(ocr_setup, "user_tessdata_dir", lambda: folder)
    return folder


def test_install_runs_winget_then_downloads_both_languages(monkeypatch, tmp_path, data_dir):
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(ocr_setup.shutil, "which", lambda name: None)
    state = {"installed": False}
    monkeypatch.setattr(ocr_setup, "KNOWN_LOCATIONS", [])
    monkeypatch.setattr(
        ocr_setup, "find_tesseract", lambda: str(binary) if state["installed"] else None
    )
    recorder = _Recorder()

    def winget(exe):
        state["installed"] = True
        return recorder.winget(exe)

    messages: list[str] = []
    result = install_ocr(
        messages.append,
        winget_finder=lambda: "winget.exe",
        winget_runner=winget,
        downloader=recorder.downloader,
        language_check=lambda: ["eng", "osd", "tha"],
    )

    assert result.ok, result.summary()
    assert recorder.winget_calls == 1
    assert [Path(dest).name for _url, dest in recorder.downloads] == ["eng.traineddata", "tha.traineddata"]
    assert all("tessdata_fast/raw/4.1.0/" in url for url, _dest in recorder.downloads)
    assert any("administrator" in message for message in messages)
    assert result.steps[-1].startswith("Verified")


def test_install_skips_winget_and_data_that_are_already_there(monkeypatch, tmp_path, data_dir):
    binary = _fake_binary(tmp_path)
    monkeypatch.setattr(ocr_setup, "find_tesseract", lambda: str(binary))
    data_dir.mkdir()
    for language in ("eng", "tha"):
        (data_dir / f"{language}.traineddata").write_bytes(bytes(MIN_TRAINEDDATA_BYTES))
    recorder = _Recorder()

    result = install_ocr(
        winget_runner=recorder.winget,
        downloader=recorder.downloader,
        language_check=lambda: ["eng", "tha"],
    )

    assert result.ok
    assert recorder.winget_calls == 0
    assert recorder.downloads == []


def test_install_explains_when_winget_is_missing(monkeypatch, data_dir):
    monkeypatch.setattr(ocr_setup, "find_tesseract", lambda: None)

    result = install_ocr(winget_finder=lambda: None)

    assert not result.ok
    assert "winget is not available" in result.error
    assert ocr_setup.MANUAL_INSTALL_URL in result.error


def test_install_reports_a_declined_administrator_prompt(monkeypatch, data_dir):
    monkeypatch.setattr(ocr_setup, "find_tesseract", lambda: None)

    def declined(_exe):
        return subprocess.CompletedProcess([], 1223, "", "The operation was cancelled by the user.")

    result = install_ocr(winget_finder=lambda: "winget.exe", winget_runner=declined)

    assert not result.ok
    assert "exit code 1223" in result.error
    assert "cancelled by the user" in result.error


def test_install_reports_a_failed_download(monkeypatch, tmp_path, data_dir):
    monkeypatch.setattr(ocr_setup, "find_tesseract", lambda: str(_fake_binary(tmp_path)))

    def offline(_url, _destination):
        raise OSError("network unreachable")

    result = install_ocr(downloader=offline, language_check=lambda: ["eng", "tha"])

    assert not result.ok
    assert "Could not download eng language data" in result.error
    assert "network unreachable" in result.error


def test_install_fails_when_tesseract_cannot_load_thai(monkeypatch, tmp_path, data_dir):
    monkeypatch.setattr(ocr_setup, "find_tesseract", lambda: str(_fake_binary(tmp_path)))
    recorder = _Recorder()

    result = install_ocr(downloader=recorder.downloader, language_check=lambda: ["eng", "osd"])

    assert not result.ok
    assert "cannot load: tha" in result.error


def test_install_fails_when_tesseract_cannot_be_asked(monkeypatch, tmp_path, data_dir):
    monkeypatch.setattr(ocr_setup, "find_tesseract", lambda: str(_fake_binary(tmp_path)))

    result = install_ocr(downloader=_Recorder().downloader, language_check=lambda: None)

    assert not result.ok
    assert "cannot load: eng, tha" in result.error


def test_winget_timeout_is_reported(monkeypatch, data_dir):
    monkeypatch.setattr(ocr_setup, "find_tesseract", lambda: None)

    def slow(_exe):
        raise subprocess.TimeoutExpired("winget", 1)

    result = install_ocr(winget_finder=lambda: "winget.exe", winget_runner=slow)

    assert not result.ok
    assert "did not finish in time" in result.error


def test_setup_result_summary_lists_steps_and_the_error():
    result = SetupResult(ok=False, steps=["one", "two"], error="boom")

    assert result.summary() == "one\ntwo\nERROR: boom"


# --------------------------------------------------------------------- download


def test_download_writes_atomically_and_checks_size(monkeypatch, tmp_path):
    payload = bytes(MIN_TRAINEDDATA_BYTES + 10)

    class Response:
        headers = {"Content-Length": str(len(payload))}

        def __init__(self):
            self._data = payload

        def read(self, n):
            chunk, self._data = self._data[:n], self._data[n:]
            return chunk

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ocr_setup.urllib.request, "urlopen", lambda request, timeout: Response())
    target = tmp_path / "out" / "tha.traineddata"

    ocr_setup._download("https://example.invalid/tha.traineddata", target)

    assert target.read_bytes() == payload
    assert [p.name for p in target.parent.iterdir()] == ["tha.traineddata"]


def test_download_rejects_a_truncated_file_and_leaves_nothing(monkeypatch, tmp_path):
    class Response:
        headers = {"Content-Length": "999999"}

        def __init__(self):
            self._sent = False

        def read(self, n):
            if self._sent:
                return b""
            self._sent = True
            return bytes(100_000)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ocr_setup.urllib.request, "urlopen", lambda request, timeout: Response())
    target = tmp_path / "tha.traineddata"

    with pytest.raises(OSError, match="incomplete download"):
        ocr_setup._download("https://example.invalid/x", target)

    assert list(tmp_path.iterdir()) == []
