"""Milestone 4 - OCR Setup Assistant diagnostics.

Every fact must come from a real check - never Ready just because a package
imported. Tests monkeypatch the individual check functions (not shutil.which
globally) so each scenario is explicit about which real signal it simulates.
"""

from __future__ import annotations

import types

import pytest

import doc2md.core.ocr_diagnostics as diag_module
from doc2md.core.ocr_diagnostics import diagnose


def test_real_environment_has_no_backend_and_says_so(monkeypatch):
    """This test simulates an environment with Tesseract missing but no
    RapidOCR - the diagnostic must reflect that exactly, not guess Ready."""
    import doc2md.core.ocr_diagnostics as diag_module
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (False, None, None))

    result = diagnose()

    assert result.tesseract_found is False
    assert result.pytesseract_installed is True  # pytesseract IS in requirements.txt
    assert result.tesseract_languages is None
    assert result.rapidocr_installed is False
    assert result.rapidocr_initializes is None
    assert result.active_backend is None
    assert result.thai_ready is False
    assert result.english_ready is False
    assert result.readiness_message == "ยังไม่มี OCR backend"


def test_tesseract_with_thai_and_english_is_fully_ready(monkeypatch):
    monkeypatch.setattr(diag_module, "_check_tesseract_binary", lambda: (True, "/usr/bin/tesseract"))
    monkeypatch.setattr(diag_module, "_check_pytesseract_package", lambda: True)
    monkeypatch.setattr(diag_module, "_query_tesseract_languages", lambda: ["eng", "osd", "tha"])
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (False, None, None))

    result = diagnose()

    assert result.thai_ready is True
    assert result.english_ready is True
    assert result.active_backend == "tesseract"
    assert result.readiness_message == "พร้อมอ่านภาษาไทยและอังกฤษ"


def test_tesseract_with_only_english_reports_missing_thai_data(monkeypatch):
    monkeypatch.setattr(diag_module, "_check_tesseract_binary", lambda: (True, "/usr/bin/tesseract"))
    monkeypatch.setattr(diag_module, "_check_pytesseract_package", lambda: True)
    monkeypatch.setattr(diag_module, "_query_tesseract_languages", lambda: ["eng", "osd"])
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (False, None, None))

    result = diagnose()

    assert result.thai_ready is False
    assert result.english_ready is True
    assert "เฉพาะภาษาอังกฤษ" in result.readiness_message
    assert "Thai language data" in result.readiness_message


def test_no_tesseract_binary_never_reports_ready_even_if_package_importable(monkeypatch):
    """The exact prohibited case: pytesseract imports fine, but there is no
    binary to run it against - this must not read as Ready."""
    monkeypatch.setattr(diag_module, "_check_tesseract_binary", lambda: (False, None))
    monkeypatch.setattr(diag_module, "_check_pytesseract_package", lambda: True)
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (False, None, None))

    result = diagnose()

    assert result.thai_ready is False
    assert result.english_ready is False
    assert result.tesseract_languages is None
    assert result.active_backend is None
    assert result.readiness_message == "ยังไม่มี OCR backend"


def test_tesseract_usable_but_language_query_fails_is_unknown_not_false(monkeypatch):
    """Milestone 7 item 5's exact bug report: Tesseract IS the backend the
    program would use, but its language list could not be queried - this
    must report "backend found, language readiness unknown", never claim
    Thai/English are NOT ready (that would be an unverified guess) and
    never simultaneously show active_backend=tesseract alongside a "no OCR
    backend" message."""
    monkeypatch.setattr(diag_module, "_check_tesseract_binary", lambda: (True, "/usr/bin/tesseract"))
    monkeypatch.setattr(diag_module, "_check_pytesseract_package", lambda: True)
    monkeypatch.setattr(diag_module, "_query_tesseract_languages", lambda: None)
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (False, None, None))

    result = diagnose()

    assert result.active_backend == "tesseract"
    assert result.thai_ready is None
    assert result.english_ready is None
    assert result.readiness_message == "พบ Tesseract แต่ไม่ทราบภาษาที่พร้อมใช้งาน"
    assert "ยังไม่มี OCR backend" != result.readiness_message


def test_rapidocr_installed_and_initializes_becomes_the_active_backend(monkeypatch):
    monkeypatch.setattr(diag_module, "_check_tesseract_binary", lambda: (False, None))
    monkeypatch.setattr(diag_module, "_check_pytesseract_package", lambda: False)
    monkeypatch.setattr(diag_module, "_check_rapidocr", lambda: (True, True, None))

    result = diagnose()

    assert result.rapidocr_installed is True
    assert result.rapidocr_initializes is True
    assert result.active_backend == "rapidocr"
    assert result.readiness_message != "ยังไม่มี OCR backend"


def test_rapidocr_installed_but_fails_to_initialize_is_not_the_active_backend(monkeypatch):
    monkeypatch.setattr(diag_module, "_check_tesseract_binary", lambda: (False, None))
    monkeypatch.setattr(diag_module, "_check_pytesseract_package", lambda: False)
    monkeypatch.setattr(
        diag_module, "_check_rapidocr", lambda: (True, False, "RuntimeError: model load failed")
    )

    result = diagnose()

    assert result.rapidocr_installed is True
    assert result.rapidocr_initializes is False
    assert result.active_backend is None
    assert result.readiness_message == "ยังไม่มี OCR backend"
    assert any("model load failed" in line for line in result.detail_lines)


def test_check_rapidocr_init_false_skips_the_expensive_construction(monkeypatch):
    """A caller that only wants the cheap facts (e.g. a quick GUI refresh)
    can skip the real RapidOCR() construction - the result must say
    'not measured' (None), never guess True."""
    monkeypatch.setattr(diag_module, "_check_tesseract_binary", lambda: (False, None))
    monkeypatch.setattr(diag_module, "_check_pytesseract_package", lambda: False)

    fake_module = types.ModuleType("rapidocr_onnxruntime")
    fake_module.RapidOCR = object
    import sys

    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake_module)

    called = {"n": 0}

    def boom():
        called["n"] += 1
        return True, True, None

    monkeypatch.setattr(diag_module, "_check_rapidocr", boom)

    result = diagnose(check_rapidocr_init=False)

    assert called["n"] == 0, "the real init check must not run when skipped"
    assert result.rapidocr_installed is True
    assert result.rapidocr_initializes is None


def test_as_text_includes_message_and_details():
    result = diagnose()
    text = result.as_text()
    assert result.readiness_message in text
    assert "Tesseract" in text


def test_to_dict_is_json_serializable():
    import json

    result = diagnose()
    json.dumps(result.to_dict())  # must not raise
