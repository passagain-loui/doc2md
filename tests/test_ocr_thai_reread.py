"""Thai words read as Latin ("119 วัน" -> "119 Tu"): a short shaky Latin token beside a
number is read again with Thai alone and swapped if that read is a sure Thai word.

Everything here is synthetic word data and strings.
"""

from __future__ import annotations

import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from doc2md.core import ocr_text, review  # noqa: E402

ROW = {"top": 100, "height": 40}


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


def _thai(*pieces):
    """What the Thai-only single-word read returns: ``[(piece, conf), ...]``, a piece per letter or mark."""
    return {"text": [piece for piece, _ in pieces], "conf": [conf for _, conf in pieces]}


WAN = _thai(("ว", 93), ("ั", 92), ("น", 96))


def _line(token="Tu", conf=67, gap=17):
    # ไม่เกิน 119 Tu - the Latin token sits `gap` px after the number
    return _tokens([
        ("ไม่เกิน", 93, 20, 160),
        ("119", 95, 200, 70),
        (token, conf, 270 + gap, 50),
    ])


class _Fake(types.ModuleType):
    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, plain, data, thai=None, thai_raises=None):
        super().__init__("pytesseract")
        self.plain, self.data, self.thai, self.thai_raises = plain, data, thai, thai_raises
        self.thai_calls: list[str] = []

    def image_to_string(self, target, lang="eng", config=""):
        return self.plain

    def image_to_data(self, target, lang="eng", config="", output_type=None):
        if lang == "tha":
            self.thai_calls.append(config)
            if self.thai_raises is not None:
                raise self.thai_raises
            return self.thai if self.thai is not None else _thai()
        if lang == "eng":
            return _thai()  # nothing for the abbreviation re-read
        return self.data


def _run(tmp_path, monkeypatch, fake, language="tha+eng"):
    path = tmp_path / "p.png"
    Image.new("RGB", (800, 400), "white").save(path)
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    return ocr_text.recognize(path, language)


PLAIN = "ไม่เกิน 119 Tu"


# ------------------------------------------------------------------ the swap


def test_a_shaky_latin_token_after_a_number_is_swapped_for_the_thai_word(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _line(), thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == "ไม่เกิน 119 วัน"
    assert fake.thai_calls == ["--psm 8"]


@pytest.mark.parametrize("token", ["Tu", "Iu", "Ju", "tu"])
def test_the_usual_misreadings_of_wan_are_swapped(tmp_path, monkeypatch, token):
    fake = _Fake(f"ไม่เกิน 119 {token}", _line(token), thai=WAN)

    assert review.extract(_run(tmp_path, monkeypatch, fake))[0] == "ไม่เกิน 119 วัน"


def test_a_thai_word_before_a_number_with_a_latin_token_between_them(tmp_path, monkeypatch):
    # ... ภายใน Tu 5 ...
    data = _tokens([("ภายใน", 93, 20, 120), ("Tu", 70, 155, 50), ("5", 95, 220, 30)])
    fake = _Fake("ภายใน Tu 5", data, thai=WAN)

    assert review.extract(_run(tmp_path, monkeypatch, fake))[0] == "ภายใน วัน 5"


def test_the_thai_word_may_come_in_pieces(tmp_path, monkeypatch):
    krang = _thai(("ค", 97), ("ร", 92), ("ั", 93), ("้", 93), ("ง", 89))
    data = _tokens([("ปีละ", 93, 20, 120), ("1", 95, 160, 30), ("ase", 62, 235, 90)])
    fake = _Fake("ปีละ 1 ase", data, thai=krang)

    assert review.extract(_run(tmp_path, monkeypatch, fake))[0] == "ปีละ 1 ครั้ง"


# ------------------------------------------------------------------ what must stay


def test_a_latin_token_the_model_is_sure_of_is_not_reread(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _line(conf=92), thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == PLAIN
    assert fake.thai_calls == []


@pytest.mark.parametrize("token", ["QM", "PM", "LED", "GR", "SM"])
def test_capital_abbreviations_are_not_reread(tmp_path, monkeypatch, token):
    fake = _Fake(f"ไม่เกิน 119 {token}", _line(token), thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == f"ไม่เกิน 119 {token}"
    assert fake.thai_calls == []


@pytest.mark.parametrize("thai", [
    _thai(("ก", 30)),  # a unit the Thai model has no word for
    _thai(("ก", 95)),  # one sure letter is not a word
    _thai(("ก", 95), ("ท", 40)),  # a shaky read
    _thai(("ก", 95), ("t", 95)),  # not Thai through and through
    _thai(),  # nothing read
])
def test_a_real_unit_whose_thai_read_is_not_a_sure_word_is_kept(tmp_path, monkeypatch, thai):
    fake = _Fake("ไม่เกิน 119 km", _line("km", conf=60), thai=thai)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == "ไม่เกิน 119 km"
    assert len(fake.thai_calls) == 1


def test_a_token_far_from_the_number_is_not_reread(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _line(gap=120), thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == PLAIN
    assert fake.thai_calls == []


def test_a_token_with_no_number_beside_it_is_not_reread(tmp_path, monkeypatch):
    data = _tokens([("ไม่เกิน", 93, 20, 160), ("Tu", 67, 195, 50), ("ไม่", 93, 260, 80)])
    fake = _Fake("ไม่เกิน Tu ไม่", data, thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == "ไม่เกิน Tu ไม่"
    assert fake.thai_calls == []


@pytest.mark.parametrize("token", ["Time", "a", "Tuesday"])
def test_only_two_or_three_letter_tokens_are_reread(tmp_path, monkeypatch, token):
    fake = _Fake(f"ไม่เกิน 119 {token}", _line(token), thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == f"ไม่เกิน 119 {token}"
    assert fake.thai_calls == []


def test_without_thai_loaded_nothing_is_reread(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _line(), thai=WAN)

    result = _run(tmp_path, monkeypatch, fake, language="eng")

    assert review.extract(result)[0] == PLAIN
    assert fake.thai_calls == []


def test_a_thai_read_that_fails_keeps_the_text(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _line(), thai_raises=RuntimeError("tesseract crashed"))

    assert review.extract(_run(tmp_path, monkeypatch, fake))[0] == PLAIN


def test_a_missing_thai_language_still_reaches_the_caller(tmp_path, monkeypatch):
    fake = _Fake(PLAIN, _line(), thai_raises=RuntimeError("Failed loading language 'tha'"))

    with pytest.raises(RuntimeError, match="Failed loading language"):
        _run(tmp_path, monkeypatch, fake)


def test_a_swapped_line_keeps_its_review_flag(tmp_path, monkeypatch):
    data = _tokens([("ไม่เกิน", 60, 20, 160), ("119", 62, 200, 70), ("Tu", 55, 287, 50)])
    fake = _Fake(PLAIN, data, thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    clean, flagged = review.extract(result)
    assert clean == "ไม่เกิน 119 วัน"
    assert [(line.line, line.confidence) for line in flagged] == [(0, 59)]


def test_only_a_limited_number_of_tokens_are_reread(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_text, "MAX_THAI_REREADS", 2)
    tokens = []
    for index in range(5):
        tokens += [("7", 95, 20 + 200 * index, 30), ("Tu", 60, 70 + 200 * index, 50)]
    data = _tokens(tokens)
    fake = _Fake("7 Tu 7 Tu 7 Tu 7 Tu 7 Tu", data, thai=_thai(("ก", 10)))

    _run(tmp_path, monkeypatch, fake)

    assert len(fake.thai_calls) == 2


# ------------------------------------------------------------------ helpers


@pytest.mark.parametrize("text", ["119", "2.5", "1,000", "10-12", "3/4", "09:30"])
def test_digit_tokens(text):
    assert ocr_text._is_digit_token(text)


@pytest.mark.parametrize("text", ["", "ab", "a1", "1a", "วัน"])
def test_tokens_that_are_not_digit_tokens(text):
    assert not ocr_text._is_digit_token(text)


def test_the_thai_re_read_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_text, "THAI_REREAD", False)
    fake = _Fake(PLAIN, _line(), thai=WAN)

    result = _run(tmp_path, monkeypatch, fake)

    assert review.extract(result)[0] == PLAIN
    assert fake.thai_calls == []
