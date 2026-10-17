"""A text PDF's image-only pages are read by OCR instead of vanishing.

A page that is only a picture has no text layer to extract; if the rest of the
document has text, the document-level text check never notices, and the page is
silently missing from the output (status Success).
"""

from __future__ import annotations

import io
import sys
import types

import pymupdf
import pytest
from PIL import Image

from doc2md.engine import pdf_engine
from doc2md.engine.pdf_engine import (
    IMAGE_ONLY_MIN_COVERAGE,
    MAX_IMAGE_ONLY_PAGES,
    PdfEngine,
    _page_ranges,
    _union_area,
)

BODY = "This page has an ordinary text layer with plenty of words on it."
GARBLED = "แจ งสถานการณ น้ำท!วมในเขตพื้นที่กรุงเทพฯ ผ!านมา ต!อไป ท!วมขัง " * 4
FOOTER = "19 | P a g e"  # 12 characters: under SCANNED_TEXT_THRESHOLD


def _png(width=400, height=600) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "lightgray").save(buffer, "PNG")
    return buffer.getvalue()


def _build(path, kinds, thai_font=None):
    """A PDF with one page per entry of *kinds*:

    ``text``    - ordinary text
    ``image``   - a full-page image plus a footer
    ``photo``   - a full-page image, no text at all
    ``small``   - text-less except a footer, with a small image (< 25% of the page)
    ``blank``   - nothing at all
    ``garbled`` - mis-encoded Thai text layer
    """
    doc = pymupdf.open()
    for number, kind in enumerate(kinds, start=1):
        page = doc.new_page()  # 595 x 842
        if kind == "text":
            page.insert_text((50, 80), BODY)
        elif kind in ("image", "photo"):
            page.insert_image(page.rect, stream=_png())
            if kind == "image":
                page.insert_text((250, 820), f"{number} | P a g e")
        elif kind == "small":
            page.insert_image(pymupdf.Rect(50, 50, 200, 200), stream=_png(100, 100))
            page.insert_text((250, 820), f"{number} | P a g e")
        elif kind == "garbled":
            y = 80
            for chunk in [GARBLED[i:i + 55] for i in range(0, len(GARBLED), 55)]:
                page.insert_text((50, y), chunk, fontname="TH", fontfile=thai_font, fontsize=12)
                y += 18
    doc.save(str(path))
    doc.close()
    return path


class Ocr:
    """Stub OCR: ``recognize`` answers per page number (from the PNG's name)."""

    def __init__(self, monkeypatch, answers=None, default="ข้อความจากภาพ", fail=()):
        self.answers = answers or {}
        self.default = default
        self.fail = set(fail)
        self.pages_read: list[int] = []
        monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: None))
        monkeypatch.setattr(pdf_engine, "prepare_tesseract", lambda language: "tesseract")
        monkeypatch.setattr(pdf_engine, "recognize", self.recognize)
        monkeypatch.setattr(pdf_engine, "_pdfplumber_available", lambda: False)

    def recognize(self, image_path, language):
        number = int(image_path.stem.split("_")[1])
        self.pages_read.append(number)
        if number in self.fail:
            raise RuntimeError("tesseract crashed")
        return self.answers.get(number, self.default)


def _convert(path, options=None):
    return PdfEngine().convert_structured(path, options or {})


def _warning(markdown):
    from doc2md.core.errors import split_warning

    return split_warning(markdown)[0]


# ---------------------------------------------------------------- the fix


def test_an_image_page_in_a_text_pdf_is_read_by_ocr_in_order_with_its_footer(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "image", "text"])
    ocr = Ocr(monkeypatch, {2: "ข้อกำหนดและเงื่อนไข"})

    output = _convert(path)

    md = output.markdown
    assert ocr.pages_read == [2]  # the text pages are not sent through OCR
    assert md.index("## Page 1") < md.index("## Page 2") < md.index("## Page 3")
    page2 = md[md.index("## Page 2"):md.index("## Page 3")]
    assert "2 | P a g e" in page2
    assert "> This page has no text layer (it is an image); it was read by OCR." in page2
    assert "ข้อกำหนดและเงื่อนไข" in page2
    assert page2.index("2 | P a g e") < page2.index("> This page has no text layer") < page2.index("ข้อกำหนด")
    assert _warning(md) is None


def test_metrics_for_an_image_page_read_by_ocr(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "image"])
    Ocr(monkeypatch)

    metrics = _convert(path).metrics

    assert metrics.pages_total == 2
    assert metrics.pages_with_content == 2
    assert metrics.ocr_pages_success == 1
    assert metrics.ocr_pages_empty == 0
    assert metrics.ocr_pages_failed == 0
    assert metrics.ocr_backend == "tesseract"
    assert metrics.ocr_language


def test_a_footer_only_image_page_does_not_count_as_content_unless_ocr_found_text(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "image"])
    Ocr(monkeypatch, {2: ""})

    metrics = _convert(path).metrics

    assert metrics.pages_with_content == 1


def test_a_photo_page_gets_a_note_and_is_counted_as_empty_without_a_warning(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "photo", "text"])
    Ocr(monkeypatch, {2: ""})

    output = _convert(path)

    md = output.markdown
    page2 = md[md.index("## Page 2"):md.index("## Page 3")]
    assert "> This page is an image; OCR found no text on it." in page2
    assert _warning(md) is None
    assert output.metrics.ocr_pages_empty == 1
    assert output.metrics.ocr_pages_success == 0
    assert output.metrics.pages_with_content == 2


def test_a_failing_ocr_on_an_image_page_is_a_warning_naming_the_page(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "image", "text"])
    Ocr(monkeypatch, fail={2})

    output = _convert(path)

    warning = _warning(output.markdown)
    assert warning and "page(s) 2" in warning and "OCR failed" in warning
    assert output.metrics.ocr_pages_failed == 1
    assert output.metrics.pages_with_content == 2
    assert "> This page is an image; OCR failed on it." in output.markdown


def test_a_small_image_is_not_an_image_page(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "small"])
    ocr = Ocr(monkeypatch)

    output = _convert(path)

    assert ocr.pages_read == []
    assert "it was read by OCR" not in output.markdown
    assert output.metrics.ocr_pages_success is None
    assert _warning(output.markdown) is None


def test_a_blank_page_is_not_an_image_page(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "blank"])
    ocr = Ocr(monkeypatch)

    _convert(path)

    assert ocr.pages_read == []


def test_a_text_page_with_a_big_image_is_not_sent_to_ocr(tmp_path, monkeypatch):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=_png())
    page.insert_text((50, 80), BODY)  # a real text layer on top of the picture
    path = tmp_path / "t.pdf"
    doc.save(str(path))
    doc.close()
    ocr = Ocr(monkeypatch)

    _convert(path)

    assert ocr.pages_read == []


def test_the_coverage_threshold_is_a_quarter_of_the_page(tmp_path):
    assert IMAGE_ONLY_MIN_COVERAGE == 0.25
    doc = pymupdf.open()
    page = doc.new_page()  # 595 x 842
    page.insert_image(pymupdf.Rect(0, 0, 595, 842 * 0.24), stream=_png(), keep_proportion=False)
    assert PdfEngine._image_coverage(page) < IMAGE_ONLY_MIN_COVERAGE
    page2 = doc.new_page()
    page2.insert_image(pymupdf.Rect(0, 0, 595, 842 * 0.26), stream=_png(), keep_proportion=False)
    assert PdfEngine._image_coverage(page2) >= IMAGE_ONLY_MIN_COVERAGE
    doc.close()


def test_overlapping_images_are_not_counted_twice():
    assert _union_area([(0, 0, 10, 10), (0, 0, 10, 10)]) == 100
    assert _union_area([(0, 0, 10, 10), (5, 5, 15, 15)]) == 175
    assert _union_area([(0, 0, 10, 10), (20, 0, 30, 10)]) == 200
    assert _union_area([]) == 0.0


# --------------------------------------------------- OCR off / unavailable


def test_ocr_unavailable_keeps_the_footer_and_warns_naming_the_page_range(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "image", "image", "image", "text", "image"])
    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: "Tesseract is not installed"))

    output = _convert(path)

    warning = _warning(output.markdown)
    assert warning is not None
    assert "Page(s) 2-4, 6 are images with no text layer and OCR is unavailable to read them" in warning
    assert "Tesseract is not installed" in warning
    assert "2 | P a g e" in output.markdown  # what text there is stays
    assert output.metrics.pages_with_content == 2  # the footer-only image pages are not content


def test_ocr_switched_off_warns_too(tmp_path):
    path = _build(tmp_path / "a.pdf", ["text", "image"])

    output = _convert(path, {"pdf_ocr_fallback": False})

    warning = _warning(output.markdown)
    assert warning and "Page(s) 2 are images" in warning and "OCR is switched off" in warning


def test_a_long_page_list_in_the_warning_is_capped(tmp_path, monkeypatch):
    # every other page is an image, so there are many separate runs
    kinds = ["text", "photo"] * 14
    path = _build(tmp_path / "a.pdf", kinds)
    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: "no OCR"))

    warning = _warning(_convert(path).markdown)

    assert "..." in warning
    assert "28" not in warning.split("are images")[0]


def test_page_ranges_compress_consecutive_runs():
    assert _page_ranges([18, 19, 20, 25]) == "19-21, 26"
    assert _page_ranges([0]) == "1"
    assert _page_ranges([3, 1, 2]) == "2-4"
    assert _page_ranges(range(0, 40, 2), limit=3) == "1, 3, 5..."


# ------------------------------------------------------------------ cap


def test_at_most_the_cap_of_image_pages_is_read_and_the_rest_are_reported(tmp_path, monkeypatch):
    extra = 3
    path = _build(tmp_path / "a.pdf", ["text"] + ["photo"] * (MAX_IMAGE_ONLY_PAGES + extra))
    ocr = Ocr(monkeypatch)

    output = _convert(path)

    assert len(ocr.pages_read) == MAX_IMAGE_ONLY_PAGES
    warning = _warning(output.markdown)
    assert warning and f"{extra} more page(s)" in warning
    assert f"{MAX_IMAGE_ONLY_PAGES + 2}-{MAX_IMAGE_ONLY_PAGES + 1 + extra}" in warning
    assert output.metrics.ocr_pages_success == MAX_IMAGE_ONLY_PAGES


# --------------------------------------------- with mis-encoded pages, progress


def test_image_and_mis_encoded_pages_share_one_pass_and_one_set_of_metrics(
    tmp_path, thai_font, monkeypatch
):
    path = _build(tmp_path / "a.pdf", ["text", "garbled", "image", "photo", "text"], thai_font)
    ocr = Ocr(monkeypatch, {2: "ข้อความที่ถูกต้อง", 3: "ข้อความจากภาพ", 4: ""})
    progress = []
    sender = types.SimpleNamespace(send=progress.append)

    output = _convert(path, {"_progress_sender": sender})

    md = output.markdown
    assert ocr.pages_read == [2, 3, 4]
    assert progress == [("progress", (1, 3)), ("progress", (2, 3)), ("progress", (3, 3))]
    assert "> The text layer of this page is mis-encoded Thai; it was read by OCR instead." in md
    assert "> This page has no text layer (it is an image); it was read by OCR." in md
    assert "> This page is an image; OCR found no text on it." in md
    assert "ท!วม" not in md
    assert _warning(md) is None
    m = output.metrics
    assert m.ocr_pages_success == 2  # the mis-encoded page plus the image page
    assert m.ocr_pages_empty == 1
    assert m.ocr_pages_failed == 0
    assert m.pages_with_content == 4  # the photo page has nothing but its note
    assert m.pages_total == 5


def test_review_lines_are_summed_over_both_kinds(tmp_path, thai_font, monkeypatch):
    from doc2md.core import review

    path = _build(tmp_path / "a.pdf", ["text", "garbled", "image"], thai_font)
    Ocr(monkeypatch, {2: review.encode("บรรทัดที่ไม่ชัด", 50), 3: review.encode("อีกบรรทัด", 40)})

    metrics = _convert(path).metrics

    assert metrics.ocr_review_lines == 2


def test_mis_encoded_page_ocr_failure_still_warns_as_before(tmp_path, thai_font, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "garbled", "image"], thai_font)
    Ocr(monkeypatch, fail={2})

    output = _convert(path)

    warning = _warning(output.markdown)
    assert warning and "mis-encoded Thai and OCR could not replace it" in warning
    assert output.metrics.ocr_pages_failed == 1
    assert output.metrics.ocr_pages_success == 1


def test_both_kinds_unavailable_gives_both_sentences(tmp_path, thai_font, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "garbled", "image"], thai_font)
    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: "no OCR"))

    warning = _warning(_convert(path).markdown)

    assert "is mis-encoded Thai" in warning
    assert "Page(s) 3 are images with no text layer" in warning


# ------------------------------------------------------- unchanged paths


def test_a_text_pdf_without_image_pages_never_runs_ocr(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["text", "text"])
    monkeypatch.setattr(
        pdf_engine, "recognize", lambda *args: pytest.fail("OCR must not run for a plain text PDF")
    )

    output = _convert(path)

    assert output.metrics.pages_with_content == 2
    assert output.metrics.ocr_pages_success is None
    assert _warning(output.markdown) is None


def test_a_fully_scanned_pdf_still_uses_the_scanned_path(tmp_path, monkeypatch):
    path = _build(tmp_path / "a.pdf", ["photo", "photo"])
    ocr = Ocr(monkeypatch)

    output = _convert(path)

    assert ocr.pages_read == [1, 2]
    assert "## Page 1 (OCR)" in output.markdown
    assert "it was read by OCR" not in output.markdown
    assert output.metrics.ocr_pages_success == 2
