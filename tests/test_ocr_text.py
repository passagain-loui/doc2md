"""Panel splitting and noise filtering around Tesseract."""

from __future__ import annotations

import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from doc2md.core import ocr_text  # noqa: E402


def _page(panels: int, width=2000, height=600, gap=14, background="white", ink="black"):
    """A page of text-like stripes in *panels* side-by-side columns."""
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    margin = 40
    usable = width - 2 * margin - gap * (panels - 1)
    panel_width = usable // panels
    for index in range(panels):
        left = margin + index * (panel_width + gap)
        for row in range(40, height - 60, 18):
            draw.rectangle((left + 5, row, left + panel_width - 5, row + 7), fill=ink)
    return image


def test_four_panels_separated_by_thin_gaps_are_found():
    image = _page(4)

    bands = ocr_text.split_into_bands(image)

    assert len(bands) == 4
    assert all(abs(band.size[0] - bands[0].size[0]) < 80 for band in bands)


def test_a_single_text_column_is_not_split():
    assert len(ocr_text.split_into_bands(_page(1))) == 1


def test_a_blank_page_is_not_split():
    assert len(ocr_text.split_into_bands(Image.new("RGB", (1500, 500), "white"))) == 1


def test_dark_pages_are_handled_like_light_ones():
    assert len(ocr_text.split_into_bands(_page(2, background="black", ink="white"))) == 2


def test_a_footer_strip_across_the_gutters_does_not_hide_them():
    image = _page(3)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, image.size[1] - 30, image.size[0] - 40, image.size[1] - 18), fill="black")

    assert len(ocr_text.split_into_bands(image)) == 3


def test_a_sliver_beside_a_gutter_is_merged_not_a_panel():
    image = _page(1, width=2000)
    draw = ImageDraw.Draw(image)
    draw.rectangle((1900, 40, 1960, 540), fill="black")  # a narrow column of page numbers

    assert len(ocr_text.split_into_bands(image)) == 1


def test_very_small_images_are_left_alone():
    assert len(ocr_text.split_into_bands(Image.new("RGB", (100, 50), "white"))) == 1


# ------------------------------------------------------------- noise filtering


def _data(lines):
    """Tesseract-style word data from ``[(block, par, line, [(word, conf), ...]), ...]``."""
    data = {"text": [], "conf": [], "block_num": [], "par_num": [], "line_num": []}
    for block, par, line, words in lines:
        for word, conf in words:
            data["text"].append(word)
            data["conf"].append(conf)
            data["block_num"].append(block)
            data["par_num"].append(par)
            data["line_num"].append(line)
    return data


def test_low_confidence_lines_are_identified_without_spaces_or_case_changes():
    data = _data([
        (1, 1, 1, [("ข้อความ", 91), ("จริง", 88)]),
        (1, 1, 2, [("@", 12), ("ee", 20), ("&", 15), ("ZB", 18)]),
        (1, 1, 3, [("ok", 40)]),  # a very short line needs 60
    ])

    assert ocr_text._low_confidence_lines(data) == {"@ee&ZB", "ok"}


def test_junk_lines_are_removed_and_blank_runs_collapsed():
    plain = "good line\n\n@ ee & ZB\n\nsecond good line\n"

    cleaned = ocr_text._without_junk(plain, {"@ee&ZB"})

    assert cleaned == "good line\n\nsecond good line"


def test_unreadable_confidence_values_do_not_crash():
    data = _data([(1, 1, 1, [("abc", "n/a")])])

    assert ocr_text._low_confidence_lines(data) == set()


# ------------------------------------------------------------------ recognize


class _FakeTesseract(types.ModuleType):
    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, plain, data):
        super().__init__("pytesseract")
        self.plain, self.data, self.calls = plain, data, []

    def image_to_string(self, target, lang="eng"):
        self.calls.append(("string", lang))
        return self.plain

    def image_to_data(self, target, lang="eng", output_type=None):
        self.calls.append(("data", lang))
        return self.data


def test_recognize_drops_noise_lines_but_keeps_tesseracts_own_spacing(tmp_path, monkeypatch):
    image_path = tmp_path / "p.png"
    Image.new("RGB", (800, 300), "white").save(image_path)
    fake = _FakeTesseract(
        "ความยาวช่วงล้อ มม. 2,750\n@ ee & ZB\n",
        _data([
            (1, 1, 1, [("ความยาว", 90), ("ช่วงล้อ", 92), ("มม.", 95), ("2,750", 96)]),
            (1, 1, 2, [("@", 10), ("ee", 11), ("&", 12), ("ZB", 9)]),
        ]),
    )
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert ocr_text.recognize(image_path, "tha+eng") == "ความยาวช่วงล้อ มม. 2,750"
    assert ("string", "tha+eng") in fake.calls


def test_recognize_reads_each_panel_separately_in_order(tmp_path, monkeypatch):
    image_path = tmp_path / "p.png"
    _page(2).save(image_path)
    outputs = iter(["left panel", "right panel"])

    class Fake(_FakeTesseract):
        def image_to_string(self, target, lang="eng"):
            return next(outputs)

    monkeypatch.setitem(sys.modules, "pytesseract", Fake("", _data([])))

    assert ocr_text.recognize(image_path, "eng") == "left panel\n\nright panel"


def test_recognize_falls_back_to_the_plain_call_without_word_data(tmp_path, monkeypatch):
    image_path = tmp_path / "p.png"
    Image.new("RGB", (400, 200), "white").save(image_path)
    fake = types.ModuleType("pytesseract")
    fake.image_to_string = lambda target, lang="eng": "plain only"
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert ocr_text.recognize(image_path, "eng") == "plain only"


def test_a_missing_language_error_still_reaches_the_callers_fallback(tmp_path, monkeypatch):
    image_path = tmp_path / "p.png"
    Image.new("RGB", (400, 200), "white").save(image_path)

    class Fake(_FakeTesseract):
        def image_to_data(self, target, lang="eng", output_type=None):
            raise RuntimeError("Failed loading language 'tha'")

    monkeypatch.setitem(sys.modules, "pytesseract", Fake("text", _data([])))

    with pytest.raises(RuntimeError, match="Failed loading language"):
        ocr_text.recognize(image_path, "tha+eng")


def test_other_data_errors_keep_the_unfiltered_text(tmp_path, monkeypatch):
    image_path = tmp_path / "p.png"
    Image.new("RGB", (400, 200), "white").save(image_path)

    class Fake(_FakeTesseract):
        def image_to_data(self, target, lang="eng", output_type=None):
            raise RuntimeError("some other failure")

    monkeypatch.setitem(sys.modules, "pytesseract", Fake("kept text", _data([])))

    assert ocr_text.recognize(image_path, "eng") == "kept text"
