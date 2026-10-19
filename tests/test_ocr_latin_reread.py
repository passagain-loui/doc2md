"""Latin abbreviations read as Thai ("QM Manager" -> "อห Manager"), and the Pillow helper.

A short, shaky run of Thai letters right beside a Latin word is read again with
eng only; the result replaces the run only if it is a confident run of capitals.
Everything here uses synthetic word data and strings.
"""

from __future__ import annotations

import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from doc2md.core import ocr_text, review  # noqa: E402

ROW = {"top": 100, "height": 30}


def _tokens(rows):
    """Word data from ``[(text, conf, left, width), ...]`` all on one line."""
    data = {k: [] for k in ("text", "conf", "block_num", "par_num", "line_num", "left", "top", "width", "height")}
    for text, conf, left, width in rows:
        data["text"].append(text)
        data["conf"].append(conf)
        data["block_num"].append(1)
        data["par_num"].append(1)
        data["line_num"].append(1)
        data["left"].append(left)
        data["top"].append(ROW["top"])
        data["width"].append(width)
        data["height"].append(ROW["height"])
    return data


def _eng(*words):
    """What the eng-only, single-word read returns: ``[(text, conf), ...]``."""
    data = {"text": [], "conf": []}
    for text, conf in words:
        data["text"].append(text)
        data["conf"].append(conf)
    return data


# ตําแหน่ง : อห Manager - the two shaky Thai letters sit 15 px before the Latin word
def _qm_tokens(run_conf=(63, 75), word_conf=96, gap=15):
    return _tokens([
        ("ตําแหน่ง", 93, 20, 150),
        (":", 92, 180, 6),
        ("อ", run_conf[0], 200, 25),
        ("ห", run_conf[1], 230, 30),
        ("Manager", word_conf, 260 + gap, 120),
    ])


class _Fake(types.ModuleType):
    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, plain, data, eng=None, eng_raises=None):
        super().__init__("pytesseract")
        self.plain, self.data, self.eng, self.eng_raises = plain, data, eng, eng_raises
        self.eng_calls: list[tuple[str, str]] = []

    def image_to_string(self, target, lang="eng", config=""):
        return self.plain

    def image_to_data(self, target, lang="eng", config="", output_type=None):
        if lang == "eng":
            self.eng_calls.append((lang, config))
            if self.eng_raises is not None:
                raise self.eng_raises
            return self.eng if self.eng is not None else _eng()
        return self.data


def _run(tmp_path, monkeypatch, fake, language="tha+eng"):
    path = tmp_path / "p.png"
    Image.new("RGB", (800, 400), "white").save(path)
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    return ocr_text.recognize(path, language)


PLAIN = "ตําแหน่ง :อห Manager"


# ------------------------------------------------------------------ the swap


def test_a_shaky_thai_run_before_a_latin_word_is_swapped_for_a_confident_abbreviation(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _qm_tokens(), eng=_eng(("QM", 91)))

    result = _run(tmp_path, monkeypatch, fake)

    assert result == "ตำแหน่ง : QM Manager"
    assert fake.eng_calls == [("eng", "--psm 8")]


@pytest.mark.parametrize(
    "eng",
    [
        _eng(("ow", 95)),  # lowercase: a Thai glyph pair that looks like Latin noise
        _eng(("Q", 95)),  # one letter
        _eng(("QM", 70)),  # not sure enough
        _eng(("QM1", 95)),  # not letters only
        _eng(("QUALITY", 95)),  # not an abbreviation
        _eng(("QM", 95), ("XY", 95)),  # more than one word
        _eng(),  # nothing read
    ],
)
def test_an_eng_read_that_is_not_a_confident_abbreviation_leaves_the_text_alone(tmp_path, monkeypatch, eng):
    fake = _Fake(PLAIN, _qm_tokens(), eng=eng)

    result = _run(tmp_path, monkeypatch, fake)

    assert result == "ตำแหน่ง :อห Manager"
    assert len(fake.eng_calls) == 1


def test_a_confident_thai_run_beside_a_latin_word_is_not_reread(tmp_path, monkeypatch):
    fake = _Fake("งานบริการ Shipping", _tokens([("งานบริการ", 93, 20, 200), ("Shipping", 95, 235, 150)]), eng=_eng(("QM", 99)))

    result = _run(tmp_path, monkeypatch, fake)

    assert result == "งานบริการ Shipping"
    assert fake.eng_calls == []


def test_a_shaky_thai_run_far_from_any_latin_word_is_not_reread(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _qm_tokens(gap=200), eng=_eng(("QM", 99)))

    result = _run(tmp_path, monkeypatch, fake)

    assert result == "ตำแหน่ง :อห Manager"
    assert fake.eng_calls == []


def test_a_shaky_thai_run_with_no_latin_word_beside_it_is_not_reread(tmp_path, monkeypatch):
    data = _tokens([("อ", 60, 20, 25), ("ห", 62, 50, 30), ("ก", 90, 90, 20)])
    fake = _Fake("อหก", data, eng=_eng(("QM", 99)))

    _run(tmp_path, monkeypatch, fake)

    assert fake.eng_calls == []


def test_a_short_latin_neighbour_does_not_count(tmp_path, monkeypatch):
    data = _tokens([("อ", 60, 20, 25), ("ห", 62, 50, 30), ("of", 95, 95, 25)])
    fake = _Fake("อห of", data, eng=_eng(("QM", 99)))

    _run(tmp_path, monkeypatch, fake)

    assert fake.eng_calls == []


def test_a_run_after_the_latin_word_is_swapped_too(tmp_path, monkeypatch):
    data = _tokens([("Manager", 96, 20, 120), ("อ", 63, 155, 25), ("ห", 75, 185, 30)])
    fake = _Fake("Manager อห", data, eng=_eng(("QM", 91)))

    result = _run(tmp_path, monkeypatch, fake)

    assert result == "Manager QM"


def test_a_run_longer_than_a_few_pieces_is_not_reread(tmp_path, monkeypatch):
    pieces = [(ch, 60, 20 + 30 * i, 25) for i, ch in enumerate("กขคงจ")]
    data = _tokens(pieces + [("Manager", 96, 20 + 30 * 5 + 15, 120)])
    fake = _Fake("กขคงจ Manager", data, eng=_eng(("QM", 99)))

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == "กขคงจ Manager"
    assert fake.eng_calls == []


def test_thai_pieces_a_word_gap_apart_are_not_one_run(tmp_path, monkeypatch):
    # "ตําแหน่ง" is shaky too, but it is a different word from the "อห" beside the Latin word
    data = _tokens([
        ("ตําแหน่ง", 60, 20, 150), ("อ", 55, 200, 25), ("ห", 60, 230, 30), ("Manager", 70, 275, 120),
    ])
    fake = _Fake("ตําแหน่ง อห Manager", data, eng=_eng(("QM", 91)))

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == "ตำแหน่ง QM Manager"


def test_without_english_loaded_nothing_is_reread(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _qm_tokens(), eng=_eng(("QM", 99)))

    result = _run(tmp_path, monkeypatch, fake, language="tha")

    assert result == "ตำแหน่ง :อห Manager"
    assert fake.eng_calls == []


def test_a_swapped_line_keeps_its_review_flag(tmp_path, monkeypatch):
    data = _tokens([
        ("ตําแหน่ง", 60, 20, 150), ("อ", 55, 200, 25), ("ห", 60, 230, 30), ("Manager", 70, 275, 120),
    ])
    fake = _Fake("ตําแหน่ง อห Manager", data, eng=_eng(("QM", 91)))

    result = _run(tmp_path, monkeypatch, fake)

    clean, flagged = review.extract(result)
    assert clean == "ตำแหน่ง QM Manager"
    assert [(line.line, line.confidence) for line in flagged] == [(0, 61)]


def test_a_line_that_is_dropped_as_noise_is_not_rewritten(tmp_path, monkeypatch):
    data = _tokens([("อ", 20, 20, 25), ("ห", 25, 50, 30), ("Manager", 30, 95, 120)])
    fake = _Fake("อห Manager\nข้อความปกติ", data, eng=_eng(("QM", 99)))

    result = _run(tmp_path, monkeypatch, fake)

    assert "QM" not in result
    assert "Manager" not in result


def test_an_eng_read_that_fails_keeps_the_text(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _qm_tokens(), eng_raises=RuntimeError("tesseract crashed"))

    result = _run(tmp_path, monkeypatch, fake)

    assert result == "ตำแหน่ง :อห Manager"


def test_a_missing_eng_language_still_reaches_the_caller(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _qm_tokens(), eng_raises=RuntimeError("Failed loading language 'eng'"))

    with pytest.raises(RuntimeError, match="Failed loading language"):
        _run(tmp_path, monkeypatch, fake)


# ------------------------------------------------------------------ _swap_run


def test_swap_run_ignores_whitespace_inside_the_run_and_sets_the_abbreviation_off():
    assert ocr_text._swap_run("ตําแหน่ง :อ ห Manager", "อห", "Manager", "QM", True) == "ตําแหน่ง : QM Manager"


def test_swap_run_leaves_a_line_without_that_run_next_to_that_word():
    assert ocr_text._swap_run("อห Director", "อห", "Manager", "QM", True) is None
    assert ocr_text._swap_run("Manager กอห", "อห", "Manager", "QM", False) is None


# ------------------------------------------------------------------ Pillow


def test_pixel_values_prefers_the_non_deprecated_call():
    class Fresh:
        def get_flattened_data(self):
            return (1, 2, 3)

        def getdata(self):  # pragma: no cover - must not be used
            raise AssertionError("deprecated getdata() called")

    assert ocr_text._pixel_values(Fresh()) == [1, 2, 3]


def test_pixel_values_falls_back_to_getdata_on_older_pillow():
    class Old:
        def getdata(self):
            return iter((4, 5, 6))

    assert ocr_text._pixel_values(Old()) == [4, 5, 6]


def test_pixel_values_of_a_real_image_is_row_by_row():
    image = Image.new("L", (3, 2))
    image.putdata([0, 10, 20, 30, 40, 50])

    assert ocr_text._pixel_values(image) == [0, 10, 20, 30, 40, 50]


def test_the_gutter_and_brightness_checks_raise_no_pillow_deprecation_warning():
    import warnings

    page = Image.new("RGB", (800, 600), "white")
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        ocr_text.find_vertical_gutters(page)
        ocr_text.prepare_for_ocr(page)
