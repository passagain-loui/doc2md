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


# ---------------------------------------------------------------- pale fills


def test_pale_coloured_fills_become_white_and_text_stays_dark():
    image = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 400, 40), fill=(158, 200, 220))  # pastel header bar
    draw.rectangle((20, 10, 120, 30), fill=(20, 20, 20))  # text on it
    draw.rectangle((20, 100, 120, 120), fill=(120, 120, 120))  # mid-grey text

    prepared = ocr_text.prepare_for_ocr(image)

    assert prepared.mode == "L"
    assert prepared.getpixel((300, 20)) >= 250
    assert prepared.getpixel((60, 20)) < 40
    assert prepared.getpixel((60, 110)) < 150


def test_light_grey_strokes_are_not_whitened_because_they_are_not_coloured():
    """Whitening every light pixel thinned strokes and turned ข into ย."""
    image = Image.new("RGB", (400, 200), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 120, 40), fill=(190, 190, 190))
    ImageDraw.Draw(image).rectangle((20, 100, 120, 120), fill=(10, 10, 10))

    prepared = ocr_text.prepare_for_ocr(image)

    assert prepared.getpixel((60, 30)) < 235


def test_small_pages_are_not_median_filtered():
    """A median filter erases thin strokes of small text."""
    image = Image.new("RGB", (800, 300), "white")
    ImageDraw.Draw(image).line((10, 150, 790, 150), fill=(0, 0, 0), width=1)

    prepared = ocr_text.prepare_for_ocr(image)

    assert prepared.getpixel((400, 150)) < 100


def test_dark_pages_are_returned_unchanged():
    image = Image.new("RGB", (400, 200), (10, 10, 20))

    assert ocr_text.prepare_for_ocr(image) is image


# ------------------------------------------------------------- poster readings


def _reading(text, conf, left, top, right, bottom):
    return ocr_text._Reading(text, conf, left, top, right, bottom)


def test_the_more_confident_reading_of_a_region_wins():
    merged = ocr_text.merge_readings([
        _reading("ลดน้ำตาลในเลือด", 60, 10, 10, 200, 30),
        _reading("สดุนําตาลในเล็จด", 30, 12, 11, 198, 31),
    ])

    assert merged == "ลดน้ำตาลในเลือด"


def test_readings_of_different_regions_are_all_kept_in_reading_order():
    merged = ocr_text.merge_readings([
        _reading("footer", 90, 10, 300, 100, 320),
        _reading("title", 90, 10, 10, 100, 30),
        _reading("right", 90, 150, 12, 220, 32),
    ])

    assert merged == "title right\nfooter"


def test_a_long_line_beats_a_fragment_of_itself():
    merged = ocr_text.merge_readings([
        _reading("ต้านแบคทีเรีย", 70, 10, 10, 200, 30),
        _reading("ต้าน", 80, 10, 10, 60, 30),
    ])

    assert merged == "ต้านแบคทีเรีย"


def test_nothing_readable_gives_an_empty_string():
    assert ocr_text.merge_readings([]) == ""


def test_wordlike_ratio_separates_text_from_symbols():
    assert ocr_text._wordlike_ratio("ช่วยการนอนหลับ") == 1.0
    assert ocr_text._wordlike_ratio("=) ”)") == 0.0
    assert ocr_text._wordlike_ratio("50 เท่า") == 1.0


def _poster_data(words):
    """``words``: ``(text, conf, left, top, width, height)`` as one line each."""
    data = {k: [] for k in ("text", "conf", "block_num", "par_num", "line_num", "left", "top", "width", "height")}
    for line, (text, conf, left, top, width, height) in enumerate(words, start=1):
        data["text"].append(text)
        data["conf"].append(conf)
        data["block_num"].append(1)
        data["par_num"].append(1)
        data["line_num"].append(line)
        data["left"].append(left)
        data["top"].append(top)
        data["width"].append(width)
        data["height"].append(height)
    return data


def test_readings_drop_low_confidence_and_symbol_lines():
    data = _poster_data([
        ("ช่วยการนอนหลับ", 88, 10, 10, 200, 20),
        ("ไม่แน่ใจ", 20, 10, 50, 100, 20),
        ("=)”)", 90, 10, 90, 40, 20),
    ])

    texts = [reading.text for reading in ocr_text._readings(data, 1.0)]

    assert texts == ["ช่วยการนอนหลับ"]


def test_readings_are_mapped_back_to_the_original_scale():
    data = _poster_data([("ข้อความ", 90, 200, 100, 400, 60)])

    (reading,) = ocr_text._readings(data, 2.0)

    assert (reading.left, reading.top, reading.right, reading.bottom) == (100, 50, 300, 80)


def test_recognize_image_pools_the_passes(tmp_path, monkeypatch):
    image_path = tmp_path / "poster.png"
    Image.new("RGB", (800, 800), "white").save(image_path)
    by_config = {
        "--psm 3": _poster_data([("ข้อความหนึ่ง", 90, 10, 10, 200, 20)]),
        "--psm 11": _poster_data([("ข้อความสอง", 90, 10, 100, 200, 20)]),
    }

    class Fake(_FakeTesseract):
        def image_to_data(self, target, lang="eng", config="", output_type=None):
            return by_config[config]

    monkeypatch.setitem(sys.modules, "pytesseract", Fake("", {}))

    text = ocr_text.recognize_image(image_path, "tha")

    assert "ข้อความหนึ่ง" in text
    assert "ข้อความสอง" in text


def test_recognize_image_without_word_data_uses_the_plain_reader(tmp_path, monkeypatch):
    image_path = tmp_path / "p.png"
    Image.new("RGB", (400, 200), "white").save(image_path)
    fake = types.ModuleType("pytesseract")
    fake.image_to_string = lambda target, lang="eng": "plain only"
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert ocr_text.recognize_image(image_path, "eng") == "plain only"


def test_recognize_image_still_reports_a_missing_language(tmp_path, monkeypatch):
    image_path = tmp_path / "p.png"
    Image.new("RGB", (400, 200), "white").save(image_path)

    class Fake(_FakeTesseract):
        def image_to_data(self, target, lang="eng", config="", output_type=None):
            raise RuntimeError("Failed loading language 'tha'")

    monkeypatch.setitem(sys.modules, "pytesseract", Fake("", {}))

    import pytest as _pytest

    with _pytest.raises(RuntimeError, match="Failed loading language"):
        ocr_text.recognize_image(image_path, "tha+eng")
