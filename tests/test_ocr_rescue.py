"""Text a scan's plain read throws away: unread runs inside tables, sparse pages.

Everything here is a synthetic image or a synthetic ``image_to_data`` dict.
"""

from __future__ import annotations

import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from doc2md.core import ocr_text, review  # noqa: E402

BOX = (300, 350, 1500, 650)  # the ruled box of _boxed_page


# ------------------------------------------------------------------ helpers


def _stripes(draw, left, top, right, bottom, step=12, thickness=6):
    """Text-like rows: dashes 14 px long with 4 px between, about 40% ink: no
    gutter for the band splitter and no run long enough to be a rule."""
    for row in range(top, bottom, step):
        for x in range(left, right - 14, 18):
            draw.rectangle((x, row, x + 13, row + thickness - 1), fill="black")


def _boxed_page(width=1800, height=1200, cells=((340, 420, 700, 456), (1000, 420, 1460, 456))):
    """A light page: stripes of body text above, and a ruled box with a text
    cell at each of *cells*."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    _stripes(draw, 100, 60, width - 100, 300, step=18)  # the body text above the table
    draw.rectangle(BOX, outline="black", width=4)
    draw.line((850, BOX[1], 850, BOX[3]), fill="black", width=4)
    for left, top, right, bottom in cells:
        _stripes(draw, left, top, right, bottom)
    return image


def _word_data(words):
    """``image_to_data`` dict from ``(text, conf, left, top, width, height, line_num)``."""
    data = {k: [] for k in ("text", "conf", "block_num", "par_num", "line_num", "left", "top", "width", "height")}
    for text, conf, left, top, width, height, line_num in words:
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


def _heading():
    return [("หัวข้อ", 92, 95, 55, 1610, 250, 1)]  # one "line" over the whole block of body text


def _row(text, conf=90, line_num=1, top=10):
    """One re-read row of two words, as a psm 6 read of a crop gives it."""
    first, second = text.split()
    return [(first, conf, 10, top, 60, 30, line_num), (second, conf, 100, top, 60, 30, line_num)]


class _Tess(types.ModuleType):
    """pytesseract stand-in: page reads get *page_words*; the n-th ``--psm 6`` crop
    read gets ``runs[n]``, a list of words for ``_word_data``."""

    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, plain, page_words, runs=()):
        super().__init__("pytesseract")
        self.plain, self.page_data, self.runs = plain, _word_data(page_words), list(runs)
        self.run_reads = 0

    def image_to_string(self, target, lang="eng", config=""):
        return self.plain

    def image_to_data(self, target, lang="eng", config="", output_type=None):
        if "--psm 6" in config:
            words = self.runs[min(self.run_reads, len(self.runs) - 1)] if self.runs else []
            self.run_reads += 1
            return _word_data(words)
        return self.page_data


def _run(tmp_path, monkeypatch, image, fake, language="tha"):
    path = tmp_path / "p.png"
    image.save(path)
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    return ocr_text.recognize(path, language)


def _lines(result):
    return [line for line in review.extract(result)[0].splitlines() if line.strip()]


# ------------------------------------------------------------------ rules


def test_a_long_thin_line_is_a_rule():
    image = Image.new("L", (800, 400), 255)
    ImageDraw.Draw(image).line((50, 200, 750, 200), fill=0, width=4)

    mask = ocr_text._rule_mask(image)

    assert mask.getpixel((400, 200)) == 255
    assert mask.getpixel((400, 100)) == 0


def test_text_strokes_are_not_rules():
    image = Image.new("RGB", (800, 400), "white")
    _stripes(ImageDraw.Draw(image), 40, 40, 760, 360)

    assert ocr_text._rule_mask(image.convert("L")).getbbox() is None


def test_a_filled_bar_is_not_a_rule():
    image = Image.new("L", (800, 400), 255)
    ImageDraw.Draw(image).rectangle((50, 100, 750, 200), fill=30)  # a coloured table header

    assert ocr_text._rule_mask(image).getpixel((400, 150)) == 0


def test_erasing_rules_whitens_the_line_and_keeps_the_text():
    image = Image.new("L", (800, 400), 255)
    draw = ImageDraw.Draw(image)
    draw.line((50, 300, 750, 300), fill=0, width=4)
    draw.rectangle((100, 100, 112, 108), fill=0)  # a stroke

    erased = ocr_text._erase_rules(image)

    assert erased.getpixel((400, 300)) == 255
    assert erased.getpixel((105, 104)) == 0


def test_vertical_rules_are_found_too():
    image = Image.new("L", (800, 600), 255)
    ImageDraw.Draw(image).line((400, 50, 400, 550), fill=0, width=4)

    assert ocr_text._rule_mask(image).getpixel((400, 300)) == 255


def test_a_mask_at_a_smaller_scale_finds_the_same_line():
    image = Image.new("L", (1200, 600), 255)
    ImageDraw.Draw(image).line((100, 300, 1100, 300), fill=0, width=4)

    mask = ocr_text._rule_mask(image, 3)

    assert mask.size == (400, 200)
    assert mask.getpixel((200, 100)) == 255


# ------------------------------------------------------------------ unread runs


def _unread(words, image=None):
    gray = (image or _boxed_page()).convert("L")
    return ocr_text._unread_runs(gray, _word_data(words + _heading()))


def test_unread_text_in_a_box_makes_one_run_per_cell():
    runs = _unread([])

    assert len(runs) == 2
    (l1, t1, r1, b1), (l2, t2, r2, b2) = sorted(runs)
    assert l1 <= 360 and r1 >= 680 and l2 <= 1020 and r2 >= 1440
    assert 400 <= t1 <= 430 and 440 <= b1 <= 470


def test_a_cell_a_word_covers_is_read():
    runs = _unread([("ครบ", 90, 330, 410, 380, 60, 1)])

    assert len(runs) == 1
    assert runs[0][0] > 900


def test_a_shaky_word_does_not_count_as_reading_a_cell():
    assert len(_unread([("noise", 20, 330, 410, 380, 60, 1)])) == 2


def test_a_picture_sized_run_is_not_text():
    image = Image.new("RGB", (1800, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(BOX, outline="black", width=4)
    _stripes(draw, 340, 380, 700, 620)  # 240 px of rows: a logo or a photograph
    assert _unread([], image) == []


def test_a_speck_is_not_a_run():
    image = Image.new("RGB", (1800, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(BOX, outline="black", width=4)
    draw.rectangle((600, 500, 612, 508), fill="black")
    assert _unread([], image) == []


# ------------------------------------------------------------------ joining a row


def test_a_wide_gap_in_a_row_is_a_column_break():
    row = ocr_text._join_row([("ครบ", 100, 60, 30), ("10", 190, 30, 30), ("ปี", 250, 30, 30), ("30", 900, 40, 30), ("วัน", 970, 50, 30)])

    assert row == "ครบ 10 ปี   30 วัน"


# ------------------------------------------------------------------ in recognize()


def test_unread_cells_are_read_again_and_put_on_one_row(tmp_path, monkeypatch):
    fake = _Tess("หัวข้อ\n", _heading(), [_row("ครบ 120"), _row("30 วัน")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert fake.run_reads == 2
    assert _lines(result) == ["หัวข้อ", "ครบ 120   30 วัน"]


def test_a_cell_is_put_left_of_the_row_even_if_its_run_starts_a_little_lower(tmp_path, monkeypatch):
    # the right-hand cell's ink starts 4 px above the left-hand one's, so it is met first
    page = _boxed_page(cells=((340, 424, 700, 456), (1000, 420, 1460, 456)))
    fake = _Tess("หัวข้อ\n", _heading(), [_row("30 วัน"), _row("ครบ 120")])

    result = _run(tmp_path, monkeypatch, page, fake)

    assert _lines(result) == ["หัวข้อ", "ครบ 120   30 วัน"]


def test_a_run_beside_a_sure_line_goes_at_the_end_of_that_line(tmp_path, monkeypatch):
    page = _heading() + [("ครบ", 92, 335, 415, 200, 45, 2), ("120", 92, 540, 415, 160, 45, 2)]
    fake = _Tess("หัวข้อ\nครบ 120\n", page, [_row("30 วัน")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert fake.run_reads == 1  # the left cell was read the first time
    assert _lines(result) == ["หัวข้อ", "ครบ 120   30 วัน"]


def test_the_value_keeps_the_lines_review_flag(tmp_path, monkeypatch):
    page = _heading() + [("ครบ", 66, 335, 415, 200, 45, 2), ("120", 66, 540, 415, 160, 45, 2)]
    fake = _Tess("หัวข้อ\nครบ 120\n", page, [_row("30 วัน", conf=78)])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    clean, flagged = review.extract(result)
    assert [(line.text, line.confidence) for line in flagged] == [("ครบ 120   30 วัน", 66)]


def test_a_shaky_re_read_is_left_out(tmp_path, monkeypatch):
    fake = _Tess("หัวข้อ\n", _heading(), [_row("ครบ 120", conf=50), _row("30 วัน", conf=74)])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert fake.run_reads == 2
    assert _lines(result) == ["หัวข้อ"]


def test_a_re_read_with_no_word_or_number_is_left_out(tmp_path, monkeypatch):
    noise = [("a", 90, 10, 10, 20, 30, 1), ("y", 90, 60, 10, 20, 30, 1), ("¢", 90, 100, 10, 20, 30, 1)]
    fake = _Tess("หัวข้อ\n", _heading(), [noise])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert _lines(result) == ["หัวข้อ"]


def test_a_shaky_line_the_first_read_made_inside_a_run_is_replaced(tmp_path, monkeypatch):
    page = _heading() + [("aw", 30, 350, 420, 100, 40, 2), ("ot", 28, 480, 420, 100, 40, 2)]
    fake = _Tess("หัวข้อ\naw ot\n", page, [_row("ครบ 120"), _row("30 วัน")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert _lines(result) == ["หัวข้อ", "ครบ 120   30 วัน"]


def test_a_long_shaky_line_a_run_only_touches_is_kept(tmp_path, monkeypatch):
    # the line (715 px) has its centre in the left run, which covers only half of it
    page = _heading() + [
        ("Travel", 55, 335, 415, 300, 45, 2), ("Line", 55, 640, 415, 200, 45, 2), ("siam", 55, 850, 415, 200, 45, 2),
    ]
    fake = _Tess("หัวข้อ\nTravel Line siam\n", page, [_row("ครบ 120")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert "Travel Line siam" in _lines(result)
    assert any("ครบ 120" in line for line in _lines(result))


def test_the_rows_of_a_run_keep_their_order(tmp_path, monkeypatch):
    two_rows = _row("ครบ 120", line_num=1) + _row("ครบ 365", line_num=2, top=60)
    fake = _Tess("หัวข้อ\n", _heading(), [two_rows, _row("30 วัน")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    # the first row of the right-hand run joins the first row of the left-hand one
    assert _lines(result)[:3] == ["หัวข้อ", "ครบ 120   30 วัน", "ครบ 365"]


def test_a_failing_re_read_keeps_the_plain_text(tmp_path, monkeypatch):
    class Failing(_Tess):
        def image_to_data(self, target, lang="eng", config="", output_type=None):
            if "--psm 6" in config:
                raise RuntimeError("tesseract crashed")
            return self.page_data

    fake = Failing("หัวข้อ\n", _heading())

    assert _lines(_run(tmp_path, monkeypatch, _boxed_page(), fake)) == ["หัวข้อ"]


def test_a_missing_language_during_the_re_read_still_reaches_the_caller(tmp_path, monkeypatch):
    class Missing(_Tess):
        def image_to_data(self, target, lang="eng", config="", output_type=None):
            if "--psm 6" in config:
                raise RuntimeError("Failed loading language 'tha'")
            return self.page_data

    fake = Missing("หัวข้อ\n", _heading())

    with pytest.raises(RuntimeError, match="Failed loading language"):
        _run(tmp_path, monkeypatch, _boxed_page(), fake)


def test_only_a_limited_number_of_runs_are_read_again(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_text, "MAX_RUN_RESCUES", 1)
    fake = _Tess("หัวข้อ\n", _heading(), [_row("ครบ 120")])

    _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert fake.run_reads == 1


def test_a_band_is_given_up_after_a_streak_of_empty_re_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_text, "RESCUE_MAX_MISSES", 1)
    noise = [("a", 90, 10, 10, 20, 30, 1), ("y", 90, 60, 10, 20, 30, 1)]
    fake = _Tess("หัวข้อ\n", _heading(), [noise, _row("30 วัน")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert fake.run_reads == 1
    assert _lines(result) == ["หัวข้อ"]


def test_a_square_run_is_not_text():
    image = Image.new("RGB", (1800, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(BOX, outline="black", width=4)
    _stripes(draw, 340, 400, 420, 480)  # 80 x 80 px: a stamp or a logo, not a word

    assert _unread([], image) == []


def test_a_thin_run_is_not_text():
    image = Image.new("RGB", (1800, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle(BOX, outline="black", width=4)
    _stripes(draw, 340, 420, 700, 426)  # one row of dashes, 6 px high: what a rule leaves behind

    assert _unread([], image) == []


def test_a_page_without_a_ruled_box_makes_no_extra_read(tmp_path, monkeypatch):
    image = Image.new("RGB", (1800, 1200), "white")
    _stripes(ImageDraw.Draw(image), 100, 60, 1700, 1100)
    fake = _Tess("หัวข้อ\n", _heading(), [_row("ครบ 120")])

    result = _run(tmp_path, monkeypatch, image, fake)

    assert fake.run_reads == 0
    assert _lines(result) == ["หัวข้อ"]


# ------------------------------------------------------------------ panels


def _two_panels():
    image = Image.new("RGB", (2000, 700), "white")
    draw = ImageDraw.Draw(image)
    for row in range(60, 640, 18):  # solid rows, as in the panel tests of test_ocr_text
        draw.rectangle((100, row, 950, row + 7), fill="black")
        draw.rectangle((1050, row, 1900, row + 7), fill="black")
    return image


def test_two_wide_panels_are_still_two_bands():
    assert len(ocr_text.split_into_bands(_two_panels())) == 2


# ------------------------------------------------------------------ contrast on a sparse page


def test_a_sparse_page_may_clip_only_a_share_of_its_own_ink():
    sparse = Image.new("L", (1000, 1000), 255)
    ImageDraw.Draw(sparse).rectangle((100, 100, 899, 109), fill=40)  # 0.8% ink
    dense = Image.new("L", (1000, 1000), 255)
    ImageDraw.Draw(dense).rectangle((0, 0, 999, 299), fill=40)  # 30% ink

    assert ocr_text._dark_cutoff(sparse) == pytest.approx(0.08, abs=0.01)
    assert ocr_text._dark_cutoff(dense) == ocr_text.AUTOCONTRAST_CUTOFF


def _sparse_page():
    page = Image.new("RGB", (800, 2400), "white")
    draw = ImageDraw.Draw(page)
    for row in range(100, 2300, 400):  # about 0.7% ink: a core and two blurred edge rows
        draw.rectangle((100, row + 1, 700, row + 2), fill=(100, 100, 100))
        draw.line((100, row, 700, row), fill=(200, 200, 200))
        draw.line((100, row + 3, 700, row + 3), fill=(200, 200, 200))
    return page


def test_with_the_limit_a_sparse_page_is_still_stretched():
    prepared = ocr_text.prepare_for_ocr(_sparse_page(), limit_clipping=True)

    assert prepared.getpixel((400, 101)) == 0  # the core becomes black
    assert prepared.getpixel((400, 100)) < 190  # the edge is stretched with it
    assert prepared.getpixel((400, 50)) == 255


def test_without_the_limit_the_stretch_is_as_it_was():
    # 1% of the pixels is more than this page's ink, so the black point lands on the paper
    # and nothing is stretched; table cells keep this behaviour
    prepared = ocr_text.prepare_for_ocr(_sparse_page())

    assert prepared.getpixel((400, 100)) == 200


def test_a_page_whose_one_percent_black_point_is_on_ink_is_stretched_as_before():
    # 3% ink at gray 40: the 1% black point is on the ink, whatever the page's ink share
    page = Image.new("L", (1000, 1000), 255)
    ImageDraw.Draw(page).rectangle((100, 100, 899, 137), fill=40)

    assert ocr_text._dark_cutoff(page) == ocr_text.AUTOCONTRAST_CUTOFF


def test_light_grey_ink_on_a_sparse_page_still_counts_as_the_black_point_on_paper():
    # all the ink is pale (gray 180) and 0.5% of the page: a 1% clip would swallow it
    page = Image.new("L", (1000, 1000), 255)
    ImageDraw.Draw(page).rectangle((100, 100, 599, 109), fill=180)

    assert ocr_text._dark_cutoff(page) < ocr_text.AUTOCONTRAST_CUTOFF


# ------------------------------------------------------------------ what counts as a real row


@pytest.mark.parametrize("row", ["ครบ 120 วัน", "mediplex", "Pansook Medical", "1.5 เท่า", "01-10-2569", "INT-QP-PR-007", "30", "4.3.2", "Official:", "VietNam 200.-", "1.5เท่า", "400วัน", "ครบ3ปีแต่ไม่เกิน6ปี", "20ปีขึ้นไป", "ประเภท", "เอกสารส่วนตัว", "Coverage and Sum insured"])
def test_rows_with_a_word_a_number_or_a_code_are_real(row):
    assert ocr_text._is_real_row(row.split())


@pytest.mark.parametrize("row", ["๕๑", "Q", "ธั่อว3", "IVI", "ABS", "a y ¢", "| |", "ๆ ๆ", "๑๒ ๑", "เอะ[ตงล=", "ที่อยู่ปั", "ที่คิดต่อไเ", "ศาทมขาทช่า.เลือ", "พร้อบแป๊ลิเป ิวิกิจิวิฐิธงกิฤษ'"])
def test_rows_a_logo_or_a_stamp_could_read_as_are_not(row):
    assert not ocr_text._is_real_row(row.split())


# ------------------------------------------------------------------ the four switches


def test_the_contrast_limit_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(ocr_text, "LIMIT_CONTRAST", False)

    prepared = ocr_text.prepare_for_ocr(_sparse_page(), limit_clipping=True)

    assert prepared.getpixel((400, 100)) == 200  # as without the flag


def test_the_rescue_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_text, "RESCUE_UNREAD", False)
    fake = _Tess("หัวข้อ\n", _heading(), [_row("ครบ 120"), _row("30 วัน")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert fake.run_reads == 0
    assert _lines(result) == ["หัวข้อ"]


# ------------------------------------------------------------------ which runs are worth a re-read


def test_the_ink_of_a_run_is_the_share_of_dark_pixels_in_its_box():
    image = Image.new("L", (200, 100), 255)
    ImageDraw.Draw(image).rectangle((0, 0, 99, 99), fill=0)  # left half black

    assert ocr_text._run_ink(image, (0, 0, 200, 100)) == pytest.approx(0.5, abs=0.01)
    assert ocr_text._run_ink(image, (120, 0, 200, 100)) == 0.0


@pytest.mark.parametrize("ink", [0.9, 0.05])
def test_a_run_that_is_solid_or_a_smudge_is_not_read_again(tmp_path, monkeypatch, ink):
    page = _boxed_page()
    draw = ImageDraw.Draw(page)
    # repaint the left cell to the wanted share of ink, keeping the cell where the run is
    draw.rectangle((340, 420, 700, 456), fill="white")
    for x in range(340, 700, 6):
        if (x - 340) / 360 < ink:
            draw.rectangle((x, 420, x + 5, 456), fill="black")
    monkeypatch.setattr(ocr_text, "_unread_runs", lambda gray, data: [(340, 420, 700, 456)])
    fake = _Tess("หัวข้อ\n", _heading(), [_row("ครบ 120")])

    result = _run(tmp_path, monkeypatch, page, fake)

    assert fake.run_reads == 0
    assert _lines(result) == ["หัวข้อ"]


def test_a_text_like_run_is_still_read_again(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_text, "_unread_runs", lambda gray, data: [(340, 420, 700, 456)])
    fake = _Tess("หัวข้อ\n", _heading(), [_row("ครบ 120")])

    result = _run(tmp_path, monkeypatch, _boxed_page(), fake)

    assert fake.run_reads == 1
    assert "ครบ 120" in _lines(result)
