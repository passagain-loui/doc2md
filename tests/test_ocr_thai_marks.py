"""Thai OCR accuracy: marks cut off their line by layout analysis, and sara am spelling."""

from __future__ import annotations

import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from doc2md.core import ocr_text, review  # noqa: E402

NIKHAHIT = chr(0x0E4D)
SARA_AA = chr(0x0E32)
SARA_AM = chr(0x0E33)
MAI_EK = chr(0x0E48)
MAI_THO = chr(0x0E49)

BASE_NO_MARKS = "เรอง"  # the base row as Tesseract reads it: every mark missing
BASE_WITH_MARKS = "เรื่อง"  # what a single-line read of the two rows gives
JUNK_PLAIN = "Aza ๕"


# ------------------------------------------------------------------ helpers


def _words(rows):
    """Tesseract word data from ``(line_num, [(text, conf)], (left, top, width, height))``."""
    data = {k: [] for k in ("text", "conf", "block_num", "par_num", "line_num", "left", "top", "width", "height")}
    for line_num, words, (left, top, width, height) in rows:
        for text, conf in words:
            data["text"].append(text)
            data["conf"].append(conf)
            data["block_num"].append(1)
            data["par_num"].append(1)
            data["line_num"].append(line_num)
            data["left"].append(left)
            data["top"].append(top)
            data["width"].append(width)
            data["height"].append(height)
    return data


class _Fake(types.ModuleType):
    """pytesseract stand-in: ``plain`` for a page read, ``single_line`` for ``--psm 7``."""

    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, plain, data, single_line="", raises=None):
        super().__init__("pytesseract")
        self.plain, self.data, self.single_line, self.raises = plain, data, single_line, raises
        self.single_line_calls = 0

    def image_to_string(self, target, lang="eng", config=""):
        if "--psm 7" in config:
            self.single_line_calls += 1
            if self.raises is not None:
                raise self.raises
            return self.single_line
        return self.plain

    def image_to_data(self, target, lang="eng", config="", output_type=None):
        return self.data


def _page(tmp_path):
    path = tmp_path / "p.png"
    Image.new("RGB", (800, 400), "white").save(path)
    return path


def _run(tmp_path, monkeypatch, fake):
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    return ocr_text.recognize(_page(tmp_path), "tha")


# the junk row sits on top of the base row, as on a bold heading
def _heading_rows(junk_conf=61, base_conf=92):
    return [
        (1, [("Aza", junk_conf), ("๕", junk_conf)], (100, 20, 300, 40)),
        (2, [(BASE_NO_MARKS, base_conf)], (100, 30, 300, 70)),
        (3, [("ข้อความปกติ", 90)], (100, 250, 300, 40)),
    ]


def _plain():
    return f"{JUNK_PLAIN}\n{BASE_NO_MARKS}\n\nข้อความปกติ\n"


# ------------------------------------------------------------------ rejoin


def test_marks_row_is_rejoined_with_its_base_row(tmp_path, monkeypatch):
    fake = _Fake(_plain(), _words(_heading_rows()), single_line=BASE_WITH_MARKS)

    result = _run(tmp_path, monkeypatch, fake)

    assert result == f"{BASE_WITH_MARKS}\n\nข้อความปกติ"
    assert fake.single_line_calls == 1
    assert review.REVIEW_OPEN not in result  # neither the junk row nor the fixed row is flagged
    assert JUNK_PLAIN not in result


def test_rejoined_line_keeps_the_base_rows_review_status(tmp_path, monkeypatch):
    # a base row that is itself shaky is still worth a look after the repair
    rows = _heading_rows(junk_conf=50, base_conf=66)
    fake = _Fake(_plain(), _words(rows), single_line=BASE_WITH_MARKS)

    result = _run(tmp_path, monkeypatch, fake)

    first_line = result.split("\n")[0]
    assert first_line == review.encode(BASE_WITH_MARKS, 66)
    assert JUNK_PLAIN not in result


def test_reread_with_a_different_skeleton_is_rejected(tmp_path, monkeypatch):
    fake = _Fake(_plain(), _words(_heading_rows()), single_line="Seer ม a ๆ ้ ่")

    result = _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 1
    assert result == f"{review.encode(JUNK_PLAIN, 61)}\n{BASE_NO_MARKS}\n\nข้อความปกติ"


def test_reread_that_adds_no_marks_is_rejected(tmp_path, monkeypatch):
    fake = _Fake(_plain(), _words(_heading_rows()), single_line=BASE_NO_MARKS)

    result = _run(tmp_path, monkeypatch, fake)

    assert BASE_NO_MARKS in result.split("\n")
    assert review.encode(JUNK_PLAIN, 61) in result


def test_empty_reread_is_rejected(tmp_path, monkeypatch):
    fake = _Fake(_plain(), _words(_heading_rows()), single_line="  \n")

    result = _run(tmp_path, monkeypatch, fake)

    assert review.encode(JUNK_PLAIN, 61) in result
    assert BASE_NO_MARKS in result.split("\n")


def test_skeleton_ignores_spaces_bars_and_marks_when_comparing():
    assert ocr_text._skeleton("ก่ | ข ้") == "กข"


def test_no_base_row_leaves_the_junk_row_alone(tmp_path, monkeypatch):
    rows = [
        (1, [("Aza", 61), ("๕", 61)], (100, 20, 300, 40)),
        (2, [(BASE_NO_MARKS, 92)], (100, 250, 300, 40)),  # far below
        (3, [("ข้อความปกติ", 90)], (500, 20, 200, 40)),  # beside, no horizontal overlap
    ]
    fake = _Fake(_plain(), _words(rows), single_line=BASE_WITH_MARKS)

    result = _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 0
    assert result.split("\n")[0] == review.encode(JUNK_PLAIN, 61)


def test_base_row_must_be_at_least_as_confident(tmp_path, monkeypatch):
    rows = _heading_rows(junk_conf=65, base_conf=60)
    fake = _Fake(_plain(), _words(rows), single_line=BASE_WITH_MARKS)

    _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 0


def test_base_row_starting_above_the_mark_row_still_counts_when_it_contains_it(tmp_path, monkeypatch):
    rows = [
        (1, [("Aza", 61), ("๕", 61)], (100, 60, 300, 30)),  # y 60-90
        (2, [(BASE_NO_MARKS, 92)], (100, 20, 300, 100)),  # y 20-120: starts 40px higher
        (3, [("ข้อความปกติ", 90)], (100, 250, 300, 40)),
    ]
    fake = _Fake(_plain(), _words(rows), single_line=BASE_WITH_MARKS)

    result = _run(tmp_path, monkeypatch, fake)

    assert result == f"{BASE_WITH_MARKS}\n\nข้อความปกติ"


def test_base_row_starting_above_without_containing_the_mark_row_is_not_a_base(tmp_path, monkeypatch):
    rows = [
        (1, [("Aza", 61), ("๕", 61)], (100, 100, 300, 30)),  # y 100-130
        (2, [(BASE_NO_MARKS, 92)], (100, 20, 300, 90)),  # y 20-110: only 10px of overlap
    ]
    fake = _Fake(_plain(), _words(rows), single_line=BASE_WITH_MARKS)

    _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 0


def test_a_confident_sliver_over_a_much_taller_row_is_tried(tmp_path, monkeypatch):
    rows = [
        (1, [("ม", 84)], (110, 20, 14, 13)),  # a lone upper vowel read with confidence
        (2, [(BASE_NO_MARKS, 92)], (100, 30, 300, 70)),
        (3, [("ข้อความปกติ", 90)], (100, 250, 300, 40)),
    ]
    fake = _Fake("ม\n" + BASE_NO_MARKS + "\n\nข้อความปกติ\n", _words(rows), single_line=BASE_WITH_MARKS)

    result = _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 1
    assert result == f"{BASE_WITH_MARKS}\n\nข้อความปกติ"


def test_confident_rows_are_not_mark_row_candidates(tmp_path, monkeypatch):
    fake = _Fake(_plain(), _words(_heading_rows(junk_conf=85, base_conf=92)), single_line=BASE_WITH_MARKS)

    _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 0


def test_word_data_without_boxes_is_tolerated(tmp_path, monkeypatch):
    data = _words(_heading_rows())
    for key in ("left", "top", "width", "height"):
        del data[key]
    fake = _Fake(_plain(), data, single_line=BASE_WITH_MARKS)

    result = _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 0
    assert review.encode(JUNK_PLAIN, 61) in result


def test_an_error_in_the_reread_falls_back_to_the_plain_behaviour(tmp_path, monkeypatch):
    fake = _Fake(_plain(), _words(_heading_rows()), raises=RuntimeError("tesseract crashed"))

    result = _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 1
    assert result == f"{review.encode(JUNK_PLAIN, 61)}\n{BASE_NO_MARKS}\n\nข้อความปกติ"


def test_a_missing_language_in_the_reread_still_raises(tmp_path, monkeypatch):
    fake = _Fake(
        _plain(), _words(_heading_rows()),
        raises=RuntimeError("Failed loading language 'tha'"),
    )

    with pytest.raises(RuntimeError, match="Failed loading language"):
        _run(tmp_path, monkeypatch, fake)


def test_reread_count_per_band_is_capped(tmp_path, monkeypatch):
    rows = []
    for index in range(ocr_text.MAX_MARK_REREADS + 10):
        top = 5 + index * 6  # all overlap each other, so every junk row has a base row
        rows.append((index + 1, [(f"x{index}", 50)], (10, top, 200, 4)))
    rows.append((999, [(BASE_NO_MARKS, 95)], (10, 5, 200, 380)))
    fake = _Fake("x0\n", _words(rows), single_line="nothing similar")

    _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls <= ocr_text.MAX_MARK_REREADS


# ------------------------------------------------------------ cluster merge
#
# Letters come from the base read; marks from the re-read where the letters agree.


def test_merge_equal_run_takes_the_rereads_marks():
    assert ocr_text._merge_marks("เรอง", "เรื่อง") == "เรื่อง"


def test_merge_keeps_base_word_the_reread_turned_into_latin():
    # "(… 6 เดือน)": a re-read of "6 ow" must not replace the Thai word
    assert ocr_text._merge_marks("(อายุไม่เกิน 6 เดอน)", "(อายุไม่เกิน 6 ow)") == "(อายุไม่เกิน 6 เดอน)"
    assert ocr_text._merge_marks("เรอง 6 เดอน", "เรื่อง 6 ow") == "เรื่อง 6 เดอน"


def test_merge_keeps_base_word_the_reread_turned_into_symbols():
    assert ocr_text._merge_marks("Certificate ตางๆ", "Certificate 414%") == "Certificate ตางๆ"
    assert ocr_text._merge_marks("เรอง Certificate ตางๆ", "เรื่อง Certificate 414%") == "เรื่อง Certificate ตางๆ"


def test_merge_keeps_base_consonant_when_the_reread_swapped_it():
    # ก/ถ do not look alike: the re-read's letter is not trusted and its marks are not taken
    base = f"รายก{NIKHAHIT}า"
    assert ocr_text._merge_marks(base, f"รายถ{MAI_THO}า") == base
    assert ocr_text._merge_marks(f"เรอง {base}", f"เรื่อง รายถ{MAI_THO}า") == f"เรื่อง {base}"


def test_merge_takes_the_marks_over_a_lookalike_letter_but_keeps_the_base_letter():
    # QP 7: the base read ซ + ring + า (ซำ); the re-read saw ช + tone + า. ซ/ช differ by
    # a small stroke, so the marks are merged onto the base's ซ: ซ้ำ, not ซำ or ช้า
    merged = ocr_text._merge_marks(f"รายซ{NIKHAHIT}า", f"รายช{MAI_THO}า")

    assert merged == f"รายซ{MAI_THO}{NIKHAHIT}า"
    assert ocr_text.normalize_thai(merged) == f"รายซ{MAI_THO}{SARA_AM}"
    assert "ช" not in merged


def test_merge_lookalike_letters_align_inside_a_longer_line():
    merged = ocr_text._merge_marks(
        f"เรอง การคัดเลือก รายซ{NIKHAHIT}า", f"เรื่อง การคัดเลือก รายช{MAI_THO}า"
    )

    assert ocr_text.normalize_thai(merged) == f"เรื่อง การคัดเลือก รายซ{MAI_THO}{SARA_AM}"


@pytest.mark.parametrize("first,second", ["ซช", "ขฃ", "ดต", "บป", "พฟ", "ถภ"])
def test_merge_lookalike_pairs_work_in_both_directions(first, second):
    for base_letter, reread_letter in ((first, second), (second, first)):
        merged = ocr_text._merge_marks(f"ก{base_letter}", f"ก{reread_letter}{MAI_EK}")
        assert merged == f"ก{base_letter}{MAI_EK}"


def test_merge_prefers_the_exact_letter_over_its_lookalike_twin_beside_it():
    # base "เตดนทาง" has a stray ต before the ด; the re-read's ดิ belongs to the ด, not the ต
    assert ocr_text._merge_marks("เตดนทาง", "เดินทาง") == "เตดินทาง"


def test_merge_does_not_align_unrelated_letters_just_because_a_mark_follows():
    assert ocr_text._merge_marks("กาน", f"กาม{MAI_EK}") == "กาน"


def test_merged_marks_still_requires_a_skeleton_close_enough_with_lookalikes():
    # the look-alike swap alone passes the 0.8 skeleton guard ...
    assert ocr_text._merged_marks(f"เรื่องการ รายช{MAI_THO}า", f"เรองการ รายซ{NIKHAHIT}า") is not None
    # ... a re-read of something else does not
    assert ocr_text._merged_marks(f"เรื่องการ ปรับแก{MAI_EK}ไข", f"เรองการ รายซ{NIKHAHIT}า") is None


def test_merge_equal_run_takes_the_rereads_spacing_and_replaced_run_keeps_the_bases():
    assert ocr_text._merge_marks("ชอ ผู ทบทวน", "ชื่อผู้ทบทวน") == "ชื่อผู้ทบทวน"
    assert ocr_text._merge_marks("เรอง A x7 เดอน", "เรื่อง A y9 ow") == "เรื่อง A x7 เดอน"


def test_merge_inserts_a_thai_word_the_first_read_dropped():
    merged = ocr_text._merge_marks(
        "หมายเลขเอกสาร แก้ไขครั้งที่", "หมายเลขเอกสาร วันที่บังคับใช้ แก้ไขครั้งที่"
    )

    assert merged == "หมายเลขเอกสาร วันที่บังคับใช้ แก้ไขครั้งที่"


def test_merge_drops_a_latin_insert():
    assert ocr_text._merge_marks("ชื่อ นาย", "ชื่อ wu นาย") == "ชื่อ นาย"


def test_merge_inserts_digits_and_punctuation():
    assert ocr_text._merge_marks("ชื่อ นาย", "ชื่อ : 12 นาย") == "ชื่อ : 12 นาย"


def test_merge_never_removes_marks_the_base_read_already_had():
    assert ocr_text._merge_marks("ผู้ทบทวน เรอง", "ผูทบทวน เรื่อง") == "ผู้ทบทวน เรื่อง"


def test_merge_keeps_a_base_mark_the_reread_disagrees_with():
    # ปัญปิติ read right the first time; the re-read turned ิ into ี
    assert ocr_text._merge_marks("นายปัญปิติ", "นายปัญปีติ") == "นายปัญปิติ"


def test_merge_adds_a_missing_tone_mark_to_a_cluster_that_had_a_vowel():
    # base has "ที" (no tone); the re-read has "ที่": the base's mark is in it, so it wins
    assert ocr_text._merge_marks("ที", "ที่") == "ที่"


def test_merge_takes_the_reread_ring_where_the_base_mistook_it_for_a_tone_mark():
    merged = ocr_text._merge_marks(f"จ{MAI_THO}านวน", f"จ{NIKHAHIT}านวน")

    assert ocr_text.normalize_thai(merged) == f"จ{SARA_AM}นวน"


def test_merge_carries_a_base_nikhahit_over_a_reread_tone_mark():
    # base "ซํา" is sara am; the re-read saw the ring as a tone mark: ซ้า
    merged = ocr_text._merge_marks(f"ซ{NIKHAHIT}า", f"ซ{MAI_THO}า")

    assert ocr_text.normalize_thai(merged) == f"ซ{MAI_THO}{SARA_AM}"


def test_merge_keeps_leading_and_trailing_table_bars_of_the_base():
    assert ocr_text._merge_marks("| GM | เรอง |", "GM เรื่อง") == "| GM | เรื่อง |"


def test_merge_of_an_empty_reread_is_the_base():
    assert ocr_text._merge_marks("เรอง", "") == "เรอง"


def test_merged_marks_rejects_a_merge_that_gains_no_marks():
    # letters kept, nothing added: the line is not touched, junk row stays
    assert ocr_text._merged_marks("6 ow", "6 เดอน") is None
    assert ocr_text._merged_marks("", "เรอง") is None
    assert ocr_text._merged_marks("   ", "เรอง") is None
    assert ocr_text._merged_marks("ก่", "เรอง") is None  # skeletons differ


def test_merged_marks_accepts_a_gain_even_when_other_words_are_rejected():
    long_base = "เรองการคัดเลือกและประเมินผู้รับจ้างช่วง 6 เดอน"
    long_reread = "เรื่องการคัดเลือกและประเมินผู้รับจ้างช่วง 6 ow"

    assert ocr_text._merged_marks(long_reread, long_base) == "เรื่องการคัดเลือกและประเมินผู้รับจ้างช่วง 6 เดอน"


def test_recognize_keeps_a_correct_base_word_next_to_a_repaired_one(tmp_path, monkeypatch):
    line = "เรองการคัดเลือกและประเมินผู้รับจ้างช่วง 6 เดอน"
    plain = f"Aza ๕\n{line}\n\nข้อความปกติ\n"
    data = _words([
        (1, [("Aza", 61), ("๕", 61)], (100, 20, 300, 40)),
        (2, [(line.replace(" ", ""), 92)], (100, 30, 300, 70)),
        (3, [("ข้อความปกติ", 90)], (100, 250, 300, 40)),
    ])
    fake = _Fake(plain, data, single_line="เรื่องการคัดเลือกและประเมินผู้รับจ้างช่วง 6 ow")

    result = _run(tmp_path, monkeypatch, fake)

    assert result == "เรื่องการคัดเลือกและประเมินผู้รับจ้างช่วง 6 เดอน\n\nข้อความปกติ"


def test_recognize_skips_the_reread_when_the_base_line_is_not_in_the_plain_text(tmp_path, monkeypatch):
    fake = _Fake("something else entirely\n", _words(_heading_rows()), single_line=BASE_WITH_MARKS)

    _run(tmp_path, monkeypatch, fake)

    assert fake.single_line_calls == 0


# --------------------------------------------------------------- doubled marks


def test_tone_mark_twice_before_sara_aa_is_tone_plus_sara_am():
    assert ocr_text.normalize_thai(f"ซ{MAI_THO}{MAI_THO}า") == f"ซ{MAI_THO}{SARA_AM}"
    assert ocr_text.normalize_thai(f"ค{MAI_EK}{MAI_EK}า") == f"ค{MAI_EK}{SARA_AM}"


def test_a_doubled_combining_mark_collapses_to_one():
    mai_han_akat = chr(0x0E31)
    assert ocr_text.normalize_thai(f"ก{mai_han_akat}{mai_han_akat}บ") == f"ก{mai_han_akat}บ"
    assert ocr_text.normalize_thai(f"ผู{MAI_THO}{MAI_THO}") == f"ผู{MAI_THO}"
    assert ocr_text.normalize_thai(f"จ{NIKHAHIT}{NIKHAHIT}{SARA_AA}กัด") == f"จ{SARA_AM}กัด"


def test_different_adjacent_marks_are_left_alone():
    word = f"ก{MAI_EK}{MAI_THO}"  # not valid Thai either, but not a doubled mark
    assert ocr_text.normalize_thai(word) == word
    assert ocr_text.normalize_thai(f"ซ{MAI_THO}า") == f"ซ{MAI_THO}า"  # one tone mark + sara aa is a word


def test_repeated_letters_that_are_not_marks_are_left_alone():
    assert ocr_text.normalize_thai("ททท กก ๆๆ") == "ททท กก ๆๆ"
    assert ocr_text.normalize_thai(f"{SARA_AA}{SARA_AA}") == f"{SARA_AA}{SARA_AA}"


# --------------------------------------------------------------- sara am


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"จ{NIKHAHIT}{SARA_AA}กัด", f"จ{SARA_AM}กัด"),
        (f"ต{NIKHAHIT}{SARA_AA}แหน่ง", f"ต{SARA_AM}แหน่ง"),
        # tone mark after the nikhahit (as Tesseract orders it) moves before sara am
        (f"น{NIKHAHIT}{MAI_THO}{SARA_AA}", f"น{MAI_THO}{SARA_AM}"),
        # tone mark already before the nikhahit
        (f"น{MAI_THO}{NIKHAHIT}{SARA_AA}", f"น{MAI_THO}{SARA_AM}"),
        (f"ค{MAI_EK}{NIKHAHIT}{SARA_AA}", f"ค{MAI_EK}{SARA_AM}"),
        # already right
        (f"จ{SARA_AM}กัด", f"จ{SARA_AM}กัด"),
        (f"{NIKHAHIT}{SARA_AA}{NIKHAHIT}{SARA_AA}", f"{SARA_AM}{SARA_AM}"),
        ("plain ascii", "plain ascii"),
        ("", ""),
    ],
)
def test_normalize_thai_merges_nikhahit_and_sara_aa(raw, expected):
    assert ocr_text.normalize_thai(raw) == expected


def test_a_lone_nikhahit_is_left_alone():
    for text in (f"ก{NIKHAHIT}", f"ก{NIKHAHIT}ข", f"ก{NIKHAHIT}{MAI_THO}ข", f"สัญ{NIKHAHIT}"):
        assert ocr_text.normalize_thai(text) == text


def test_a_lone_sara_aa_is_left_alone():
    assert ocr_text.normalize_thai(f"กา{SARA_AA}") == f"กา{SARA_AA}"


def test_recognize_normalizes_sara_am(tmp_path, monkeypatch):
    data = _words([(1, [(f"จ{NIKHAHIT}{SARA_AA}กัด", 95)], (100, 20, 300, 40))])
    fake = _Fake(f"จ{NIKHAHIT}{SARA_AA}กัด\n", data)

    assert _run(tmp_path, monkeypatch, fake) == f"จ{SARA_AM}กัด"


def test_recognize_without_word_data_normalizes_sara_am(tmp_path, monkeypatch):
    class Plain(types.ModuleType):
        def image_to_string(self, target, lang="eng"):
            return f"ตำแหน่ง".replace(SARA_AM, NIKHAHIT + SARA_AA)

    monkeypatch.setitem(sys.modules, "pytesseract", Plain("pytesseract"))

    assert ocr_text.recognize(_page(tmp_path), "tha") == f"ตำแหน่ง"


def test_recognize_region_normalizes_sara_am(monkeypatch):
    fake = types.ModuleType("pytesseract")
    fake.image_to_string = lambda *a, **k: f" ร{NIKHAHIT}{SARA_AA}คา \n"
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert ocr_text.recognize_region(Image.new("RGB", (80, 40), "white"), "tha") == f"ร{SARA_AM}คา"


def test_recognize_image_normalizes_sara_am(tmp_path, monkeypatch):
    data = _words([(1, [(f"จ{NIKHAHIT}{SARA_AA}กัด", 95)], (100, 20, 300, 40))])
    fake = _Fake("", data)
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    result = ocr_text.recognize_image(_page(tmp_path), "tha")

    assert f"จ{SARA_AM}กัด" in result
    assert NIKHAHIT not in result
