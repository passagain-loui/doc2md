"""Real OCR readiness diagnostics for the setup assistant.

Every field here is a directly-observed fact - a binary found on PATH, a
package that actually imported, a language list the Tesseract binary itself
reported - never a guess. In particular: a package importing successfully is
NOT the same as OCR being ready (RapidOCR must actually construct its
``RapidOCR()`` engine; Tesseract must actually report which language data
files are installed), and this module never reports Ready on the strength of
an import alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from doc2md.core.ocr_setup import find_tesseract, prepare_tesseract

REQUIRED_LANGUAGES = ("tha", "eng")


@dataclass
class OcrDiagnostics:
    tesseract_found: bool = False
    tesseract_path: str | None = None
    pytesseract_installed: bool = False
    tesseract_languages: list[str] | None = None
    """None means the language list could not be queried (binary missing,
    or the query itself failed) - not "zero languages installed"."""

    rapidocr_installed: bool = False
    rapidocr_initializes: bool | None = None
    """None when never attempted (no point trying if the package is not
    even installed). True/False only after an actual ``RapidOCR()``
    construction attempt."""
    rapidocr_error: str | None = None

    active_backend: str | None = None
    """Mirrors OcrEngine's own real selection order: Tesseract first if the
    binary is on PATH, else RapidOCR if it initializes, else None. A
    non-None value here means "this backend would be used", not "every
    language is ready" - check `thai_ready`/`english_ready` separately, and
    treat `None` there as genuinely unknown, not as False."""

    thai_ready: bool | None = False
    english_ready: bool | None = False
    """``True``/``False`` only once Tesseract's own language list was
    successfully queried (directly verified). ``None`` means unknown - e.g.
    Tesseract is on PATH and usable, but the language query itself failed,
    so readiness genuinely cannot be claimed either way. Never inferred as
    False just because it was not verified."""
    readiness_message: str = ""
    detail_lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tesseract_found": self.tesseract_found,
            "tesseract_path": self.tesseract_path,
            "pytesseract_installed": self.pytesseract_installed,
            "tesseract_languages": self.tesseract_languages,
            "rapidocr_installed": self.rapidocr_installed,
            "rapidocr_initializes": self.rapidocr_initializes,
            "rapidocr_error": self.rapidocr_error,
            "active_backend": self.active_backend,
            "thai_ready": self.thai_ready,
            "english_ready": self.english_ready,
            "readiness_message": self.readiness_message,
            "detail_lines": list(self.detail_lines),
        }

    def as_text(self) -> str:
        """Plain-text report for the Copy Diagnostics button."""
        lines = [self.readiness_message, ""]
        lines.extend(self.detail_lines)
        return "\n".join(lines)


def _check_tesseract_binary() -> tuple[bool, str | None]:
    path = find_tesseract()
    return path is not None, path


def _check_pytesseract_package() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def _query_tesseract_languages() -> list[str] | None:
    """Real language data files Tesseract itself reports - never guessed
    from the pytesseract package being importable."""
    try:
        import pytesseract
    except ImportError:
        return None
    prepare_tesseract("+".join(REQUIRED_LANGUAGES))
    try:
        languages = pytesseract.get_languages(config="")
    except Exception:
        return None
    return sorted(languages)


def _check_rapidocr() -> tuple[bool, bool | None, str | None]:
    """Returns ``(installed, initializes, error)``.

    ``initializes`` stays ``None`` if the package is not installed at all -
    there is nothing to attempt. Constructing ``RapidOCR()`` downloads/loads
    its bundled ONNX models on first use, so this is a real (not free)
    check, matching what the spec explicitly asks for: "initialize ได้หรือไม่".
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return False, None, None
    try:
        RapidOCR()
    except Exception as exc:
        return True, False, f"{type(exc).__name__}: {exc}"
    return True, True, None


def diagnose(*, check_rapidocr_init: bool = True) -> OcrDiagnostics:
    """Run every check for real and assemble a human-readable report.

    Set ``check_rapidocr_init=False`` to skip constructing ``RapidOCR()``
    (its model load can take real time) when only the cheaper facts are
    needed - the resulting diagnostics simply leaves ``rapidocr_initializes``
    as ``None`` (not measured), never guesses ``True``.
    """
    diag = OcrDiagnostics()

    diag.tesseract_found, diag.tesseract_path = _check_tesseract_binary()
    diag.pytesseract_installed = _check_pytesseract_package()

    if diag.tesseract_found and diag.pytesseract_installed:
        diag.tesseract_languages = _query_tesseract_languages()

    diag.rapidocr_installed, rapid_ok = False, None
    if check_rapidocr_init:
        diag.rapidocr_installed, diag.rapidocr_initializes, diag.rapidocr_error = _check_rapidocr()
    else:
        try:
            import rapidocr_onnxruntime  # noqa: F401

            diag.rapidocr_installed = True
        except ImportError:
            diag.rapidocr_installed = False

    tesseract_usable = diag.tesseract_found and diag.pytesseract_installed
    if not tesseract_usable:
        # Directly verified as not ready - there is no backend to check
        # languages against, so False here is a real fact, not a guess.
        diag.thai_ready = False
        diag.english_ready = False
    elif diag.tesseract_languages is None:
        # The binary is on PATH and pytesseract is installed, but the
        # language query itself failed - readiness is genuinely unknown,
        # not False. Never claim a language is (or is not) ready without
        # having actually queried Tesseract's installed language data.
        diag.thai_ready = None
        diag.english_ready = None
    else:
        diag.thai_ready = "tha" in diag.tesseract_languages
        diag.english_ready = "eng" in diag.tesseract_languages

    if tesseract_usable:
        # The backend that WOULD be used is still Tesseract even when its
        # language readiness is unknown - "backend found" and "language
        # readiness unknown" are two separate facts, never collapsed into
        # a false "no OCR backend" just because languages could not be read.
        diag.active_backend = "tesseract"
    elif diag.rapidocr_installed and diag.rapidocr_initializes:
        diag.active_backend = "rapidocr"
    else:
        diag.active_backend = None

    diag.readiness_message, diag.detail_lines = _build_message(diag)
    return diag


def _build_message(diag: OcrDiagnostics) -> tuple[str, list[str]]:
    details: list[str] = []

    if diag.tesseract_found:
        details.append(f"พบ Tesseract binary ที่ {diag.tesseract_path}")
    else:
        details.append("ไม่พบ Tesseract binary บน PATH")

    details.append(
        "พบ pytesseract package" if diag.pytesseract_installed else "ไม่พบ pytesseract package"
    )

    if diag.tesseract_languages is not None:
        details.append(f"ภาษาที่ Tesseract อ่านได้: {', '.join(diag.tesseract_languages) or '(ไม่มี)'}")
    elif diag.tesseract_found:
        details.append("ไม่สามารถอ่านรายการภาษาจาก Tesseract ได้")

    if diag.rapidocr_installed:
        if diag.rapidocr_initializes is True:
            details.append("พบ RapidOCR และ initialize สำเร็จ")
        elif diag.rapidocr_initializes is False:
            details.append(f"พบ RapidOCR แต่ initialize ไม่สำเร็จ: {diag.rapidocr_error}")
        else:
            details.append("พบ RapidOCR package (ยังไม่ได้ทดสอบ initialize)")
    else:
        details.append("ไม่พบ RapidOCR package")

    details.append(f"Backend ที่โปรแกรมจะเลือกใช้: {diag.active_backend or '(ไม่มี)'}")

    if diag.active_backend == "tesseract" and diag.thai_ready is None:
        # Backend found, but we could not directly verify which languages
        # it has - distinct from both "ready" and "no backend at all".
        message = "พบ Tesseract แต่ไม่ทราบภาษาที่พร้อมใช้งาน"
    elif diag.thai_ready and diag.english_ready:
        message = "พร้อมอ่านภาษาไทยและอังกฤษ"
    elif diag.english_ready and not diag.thai_ready:
        if diag.tesseract_found:
            message = "อ่านได้เฉพาะภาษาอังกฤษ (พบ Tesseract แต่ไม่มี Thai language data)"
        else:
            message = "อ่านได้เฉพาะภาษาอังกฤษ"
    elif diag.active_backend == "rapidocr":
        message = "มี OCR backend (RapidOCR) แต่ยังไม่ได้ตรวจสอบการรองรับภาษาไทยโดยเฉพาะ"
    else:
        message = "ยังไม่มี OCR backend"

    return message, details
