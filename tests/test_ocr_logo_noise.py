"""Logo noise rows: a logo or emblem read as a row of stray marks.

The rule drops a row only when Tesseract is unsure (< 75), it has at least two
tokens, none is a word, a number or a list marker, and most tokens are a single
letter or symbol. Everything here is synthetic text and word data.
"""

from __future__ import annotations

import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from doc2md.core import ocr_text, review  # noqa: E402

# ------------------------------------------------------------------ the rule


@pytest.mark.parametrize(
    "row",
    [
        "AY ¢ AY ๐ ๑",
        "ae ;",
        "เณ ล te",  # a Thai word-like pair, but nothing of 3 letters
        "a y an a ๑ a",
        "> # ~ ว wy = ซ่ T",
        ". - ะ as - » - = - *",
        "@ @",
        "ม ง",
        "ae     ;       a",  # Tesseract pads a wide gap with spaces
        "ซ่ ฉั้ ขั",  # bare tone marks and mai han-akat are no Thai words
        "wa Ya ห a ะ ay ๑",
    ],
)
def test_a_shaky_row_of_stray_marks_is_logo_noise(row):
    assert ocr_text._is_logo_noise(row, 60.0)


@pytest.mark.parametrize(
    "row",
    [
        "1.",
        "ก.",
        "QM",
        "4",
        "10",
        "ae",  # one token: the drop floor's business
        "01-10-2569",
        "ae 4",  # a digit is a number
        "เขต 10 ก",
        "1,540 % 1570",
        "ก. ข. ค.",  # list markers
        "(ก) (ข)",
        "a) b)",
        "i. ii.",
        "ใน ที่ ซึ่ง",  # short Thai words, not single marks
        "ไม่ ใช่",
        "No. 5",
        "| 2 =",  # a digit always protects: "- 2 -" is a page number
        "- 2 -",
        "ที่ :",  # one-letter Thai words
        "ณ :",
        "ณ ที่ นี้",
        "ดี ๆ",
        "ปี ,",
        "ก็ ,",
        "an of",  # short English words
        "to be",
        "QM HR",  # abbreviations are capitals
        "Mr Dr",
        "id pc",
        "Page of",
        "mediplex ae ;",  # one word is enough to keep the row
        "Pansook ae",
        "ลงชื่อ ae",
        "๒๕๖๙ ae",  # two Thai digits in a row are a number
    ],
)
def test_real_short_rows_are_never_logo_noise(row):
    assert not ocr_text._is_logo_noise(row, 60.0)


@pytest.mark.parametrize("token", ["a", "y", ";", "¢", "๑", "ม", "ง", "ซ่", "ฉั้", "ขั", "ซ์", "ae", "te", "wl"])
def test_stray_tokens(token):
    assert ocr_text._is_stray_token(token)


@pytest.mark.parametrize("token", ["ที่", "นี้", "ดี", "ปี", "ผู้", "ก็", "ณ", "ๆ", "ใน", "ไม่", "of", "an", "QM", "Yu", "mediplex", "10"])
def test_tokens_that_are_not_stray(token):
    assert not ocr_text._is_stray_token(token)


def test_a_lone_thai_digit_is_a_stray_mark_not_a_number():
    assert ocr_text._is_logo_noise("ae ๑ ๐", 60.0)
    assert not ocr_text._is_logo_noise("ae ๑๐", 60.0)


def test_a_row_tesseract_is_sure_of_is_kept():
    row = "AY ¢ AY ๐ ๑"
    assert ocr_text._is_logo_noise(row, 74.9)
    assert not ocr_text._is_logo_noise(row, ocr_text.LOGO_NOISE_MAX_CONFIDENCE)
    assert not ocr_text._is_logo_noise(row, 92.0)


def test_a_row_without_a_confidence_is_kept():
    assert not ocr_text._is_logo_noise("AY ¢ AY ๐ ๑", None)


def test_half_single_letter_tokens_is_not_enough():
    # 2 of 4 tokens are stray: 0.5 < 0.6
    assert not ocr_text._is_logo_noise("Yu we a '", 50.0)
    # 3 of 5: exactly 0.6
    assert ocr_text._is_logo_noise("Yu we a ' y", 50.0)


def test_a_three_letter_word_of_one_script_is_a_word():
    assert not ocr_text._is_logo_noise("a y Yo7 ' '", 50.0)  # digit
    assert not ocr_text._is_logo_noise("a y wow ' '", 50.0)  # word
    assert ocr_text._is_logo_noise("a y wo ' '", 50.0)  # only two letters


def test_letters_of_two_scripts_in_one_token_are_not_a_word():
    assert ocr_text._is_logo_noise("a y กaa ' '", 50.0)


def test_thai_marks_do_not_count_as_letters():
    # ซื่อ = 2 letters (ซ, อ) with two marks: not a 3-letter word
    assert ocr_text._is_logo_noise("a y ซื่อ ' '", 50.0)
    assert not ocr_text._is_logo_noise("a y ชื่อผู้ ' '", 50.0)


def test_logo_noise_keys_are_space_free_and_need_a_confidence():
    text = "AY ¢ AY ๐ ๑\nชื่อผู้จัดทำ : นาย\nae ;"
    means = {"AY¢AY๐๑": 64.0, "ชื่อผู้จัดทำ:นาย": 64.0}  # the last row has no confidence

    assert ocr_text._logo_noise_keys(text, means) == {"AY¢AY๐๑"}


# ------------------------------------------------------------------ in recognize()


class _Fake(types.ModuleType):
    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, plain, data):
        super().__init__("pytesseract")
        self.plain, self.data = plain, data

    def image_to_string(self, target, lang="eng", config=""):
        return self.plain

    def image_to_data(self, target, lang="eng", config="", output_type=None):
        return self.data


def _data(rows):
    """``image_to_data`` dict from ``(line_num, [(text, conf)])`` rows, left to right, top to bottom."""
    data = {k: [] for k in ("text", "conf", "block_num", "par_num", "line_num", "left", "top", "width", "height")}
    for line_num, words in rows:
        for index, (text, conf) in enumerate(words):
            data["text"].append(text)
            data["conf"].append(conf)
            data["block_num"].append(1)
            data["par_num"].append(1)
            data["line_num"].append(line_num)
            data["left"].append(20 + 60 * index)
            data["top"].append(40 * line_num)
            data["width"].append(40)
            data["height"].append(30)
    return data


def _run(tmp_path, monkeypatch, plain, data, language="tha+eng"):
    path = tmp_path / "p.png"
    Image.new("RGB", (800, 400), "white").save(path)
    monkeypatch.setitem(sys.modules, "pytesseract", _Fake(plain, data))
    return ocr_text.recognize(path, language)


def test_a_logo_noise_row_is_dropped_between_real_rows(tmp_path, monkeypatch):
    data = _data([
        (1, [("AY", 66), ("¢", 62), ("AY", 66), ("๐", 60), ("๑", 66)]),
        (2, [("Quality", 93), ("Procedure", 91)]),
        (3, [("ae", 70), (";", 60)]),
    ])
    plain = "AY ¢ AY ๐ ๑\nQuality Procedure\nae ;\n"

    result = _run(tmp_path, monkeypatch, plain, data)

    assert result == "Quality Procedure"


def test_a_real_row_read_just_as_shakily_is_kept_and_flagged(tmp_path, monkeypatch):
    data = _data([
        (1, [("a", 66), ("¢", 62), ("y", 66), ("๑", 60)]),
        (2, [("Quality", 66), ("Procedure", 60)]),
    ])
    plain = "a ¢ y ๑\nQuality Procedure\n"

    result = _run(tmp_path, monkeypatch, plain, data)

    clean, flagged = review.extract(result)
    assert clean == "Quality Procedure"
    assert [(line.line, line.confidence) for line in flagged] == [(0, 63)]


@pytest.mark.parametrize("row", ["1.", "ก.", "QM", "4", "01-10-2569", "ก. ข."])
def test_short_real_rows_survive_recognize_at_a_shaky_confidence(tmp_path, monkeypatch, row):
    words = [(token, 66) for token in row.split()]
    data = _data([(1, [("Heading", 93), ("text", 93)]), (2, words)])
    plain = f"Heading text\n{row}\n"

    result = _run(tmp_path, monkeypatch, plain, data)

    assert row in review.extract(result)[0].splitlines()


def test_the_dropped_row_does_not_leave_a_blank_line_run(tmp_path, monkeypatch):
    data = _data([
        (1, [("First", 93), ("line", 93)]),
        (2, [("ae", 70), (";", 60)]),
        (3, [("Last", 93), ("line", 93)]),
    ])
    plain = "First line\n\nae ;\n\nLast line\n"

    result = _run(tmp_path, monkeypatch, plain, data)

    assert result == "First line\n\nLast line"
