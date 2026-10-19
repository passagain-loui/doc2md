"""One Tesseract read per table instead of one per cell (synthetic images, no Tesseract)."""

from __future__ import annotations

import sys
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from doc2md.engine import pdf_engine  # noqa: E402
from doc2md.engine.pdf_engine import PdfEngine  # noqa: E402

NIKHAHIT = chr(0x0E4D)
SARA_AA = chr(0x0E32)
SARA_AM = chr(0x0E33)


# ------------------------------------------------------------------ helpers


def _table(bbox, *rows):
    """A pdfplumber-like table: ``rows`` are lists of cell boxes (or None)."""
    return types.SimpleNamespace(
        bbox=bbox, rows=[types.SimpleNamespace(cells=list(cells)) for cells in rows]
    )


def _data(*words):
    """Tesseract word data from ``(text, left, top, width, height, conf[, line])``."""
    data = {k: [] for k in ("text", "conf", "block_num", "par_num", "line_num", "left", "top", "width", "height")}
    for number, word in enumerate(words, start=1):
        text, left, top, width, height, conf, *line = word
        data["text"].append(text)
        data["conf"].append(conf)
        data["block_num"].append(1)
        data["par_num"].append(1)
        data["line_num"].append(line[0] if line else number)
        data["left"].append(left)
        data["top"].append(top)
        data["width"].append(width)
        data["height"].append(height)
    return data


class FakeTesseract(types.ModuleType):
    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, data=None, error=None):
        super().__init__("pytesseract")
        self.data, self.error, self.calls = data, error, []

    def image_to_data(self, image, lang="eng", config="", output_type=None):
        self.calls.append({"size": image.size, "lang": lang, "config": config})
        if self.error is not None:
            raise self.error
        return self.data


@pytest.fixture
def tesseract(monkeypatch):
    def install(data=None, error=None):
        fake = FakeTesseract(data, error)
        monkeypatch.setitem(sys.modules, "pytesseract", fake)
        return fake

    return install


@pytest.fixture
def region(monkeypatch):
    """Replace the per-cell reader; records the size of every crop it is given."""
    crops: list[tuple[int, int]] = []

    def fake(image, language):
        crops.append(image.size)
        return "CELL"

    monkeypatch.setattr(pdf_engine, "recognize_region", fake)
    return crops


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    # tests that exercise the confidence re-read set it themselves
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", None)
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", None)
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_LATIN_MAX_CHARS", None)


def _page(width=400, height=300):
    return Image.new("RGB", (width, height), "white")


def _two_cells():
    """A 1 x 2 table at the page origin: cells 0-100 and 100-200, 100 high."""
    return _table((0, 0, 200, 100), [(0, 0, 100, 100), (100, 0, 200, 100)])


def _read(table, page=None, scale=1.0):
    return pdf_engine._grid_from_table_ocr(table, page or _page(), scale, "tha+eng")


# ---------------------------------------------------- assigning words to cells


def test_a_word_goes_to_the_cell_holding_its_centre(tesseract, region):
    tesseract(_data(
        ("left", 10, 40, 30, 20, 90),
        ("straddles", 80, 40, 40, 20, 90),  # box 80-120, centre 100: the right cell
        ("almost", 70, 70, 28, 10, 90),  # box 70-98, centre 84: the left cell
    ))

    grid = _read(_two_cells())

    assert grid == [["left\nalmost", "straddles"]]
    assert region == []


def test_a_word_outside_every_cell_is_dropped(tesseract, region):
    table = _table((0, 0, 200, 100), [(0, 0, 100, 50), (100, 0, 200, 50)])
    tesseract(_data(
        ("kept", 10, 10, 30, 20, 90),
        ("lost", 10, 70, 30, 20, 90),  # below both cells
        ("gone", 250, 10, 30, 20, 90),  # right of both cells
    ))

    assert _read(table) == [["kept", ""]]


def test_lines_in_a_cell_are_ordered_by_position_and_joined_with_a_newline(tesseract, region):
    tesseract(_data(
        ("second", 10, 60, 40, 15, 90, 7),
        ("world", 50, 20, 40, 15, 90, 3),
        ("Hello", 10, 20, 35, 15, 90, 3),  # same line, listed after "world"
    ))

    assert _read(_two_cells()) == [["Hello world\nsecond", ""]]


def test_latin_words_are_spaced_and_thai_pieces_are_joined(tesseract, region):
    tesseract(_data(
        ("เครื่อง", 10, 20, 40, 20, 90, 1),
        ("ยนต์", 50, 20, 30, 20, 90, 1),  # touching: one Thai word
        ("cc", 20, 60, 14, 20, 90, 2),
        ("Turbo", 36, 60, 30, 20, 90, 2),
        ("ซีซี", 120, 20, 20, 20, 90, 3),
        ("2,393", 170, 20, 25, 20, 90, 3),  # a wide gap after Thai: spaced
    ))

    assert _read(_two_cells()) == [["เครื่องยนต์\ncc Turbo", "ซีซี 2,393"]]


def test_the_text_is_normalized_thai(tesseract, region):
    tesseract(_data((f"จ{NIKHAHIT}{SARA_AA}กัด", 10, 20, 60, 20, 90)))

    assert _read(_two_cells()) == [[f"จ{SARA_AM}กัด", ""]]


def test_a_merged_away_cell_stays_empty(tesseract, region):
    table = _table((0, 0, 200, 100), [(0, 0, 200, 100), None])
    tesseract(_data(("wide", 80, 40, 30, 20, 90)))

    assert _read(table) == [["wide", ""]]


def test_the_table_is_cropped_from_its_own_position_and_scale(tesseract, region):
    # at scale 2 the table box (10,5)-(110,55) is pixels (20,10)-(220,110)
    table = _table((10, 5, 110, 55), [(10, 5, 60, 55), (60, 5, 110, 55)])
    fake = tesseract(_data(("here", 130, 40, 30, 20, 90)))  # crop x 130 is in the right cell (100-200)

    grid = _read(table, scale=2.0)

    assert grid == [["", "here"]]
    assert fake.calls[0]["size"] == (200, 100)
    assert fake.calls[0]["lang"] == "tha+eng"
    assert fake.calls[0]["config"] == pdf_engine.TABLE_OCR_CONFIG
    assert len(fake.calls) == 1  # one read for the whole table


# ------------------------------------------------------------ per-cell fallback


def _ink(page, box):
    ImageDraw.Draw(page).rectangle(box, fill="black")


def test_a_wordless_cell_with_ink_is_read_on_its_own(tesseract, region):
    page = _page()
    _ink(page, (120, 20, 180, 80))  # something in the right cell Tesseract skipped
    tesseract(_data(("left", 10, 40, 30, 20, 90)))

    grid = _read(_two_cells(), page)

    assert grid == [["left", "CELL"]]
    assert region == [(100, 100)]  # the cell's own crop


def test_an_empty_cell_without_ink_is_not_read(tesseract, region):
    tesseract(_data(("left", 10, 40, 30, 20, 90)))

    assert _read(_two_cells()) == [["left", ""]]
    assert region == []


def test_ink_only_on_the_border_margin_does_not_count_as_text(tesseract, region):
    page = _page()
    _ink(page, (98, 0, 102, 100))  # the ruling line between the two cells
    tesseract(_data(("left", 10, 40, 30, 20, 90)))

    assert _read(_two_cells(), page) == [["left", ""]]
    assert region == []


def test_a_low_confidence_cell_is_read_on_its_own(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 70)
    tesseract(_data(
        ("atin", 10, 40, 30, 20, 40),  # left cell: shaky
        ("2,393", 120, 40, 30, 20, 95),  # right cell: sure
    ))

    grid = _read(_two_cells())

    assert grid == [["CELL", "2,393"]]
    assert region == [(100, 100)]


def test_a_shaky_bullet_or_dash_cell_is_not_re_read(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 70)
    tesseract(_data(
        (".", 20, 40, 6, 6, 20),  # a bullet read with low confidence
        ("-", 120, 40, 10, 4, 15),  # a dash
    ))

    assert _read(_two_cells()) == [[".", "-"]]
    assert region == []


def test_a_shaky_number_cell_is_still_re_read(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 70)
    tesseract(_data(("2,3g3", 10, 40, 40, 20, 30)))

    assert _read(_two_cells()) == [["CELL", ""]]


def test_confidence_minus_one_is_not_counted(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 70)
    tesseract(_data(("a", 10, 40, 10, 20, 90, 1), ("b", 25, 40, 10, 20, -1, 1)))

    assert _read(_two_cells()) == [["a b", ""]]
    assert region == []


def test_a_cell_with_only_unmeasured_words_is_kept(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 70)
    tesseract(_data(("a", 10, 40, 10, 20, -1)))

    assert _read(_two_cells()) == [["a", ""]]
    assert region == []


def test_the_confidence_check_can_be_switched_off(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", None)
    tesseract(_data(("shaky", 10, 40, 30, 20, 5)))

    assert _read(_two_cells()) == [["shaky", ""]]
    assert region == []


def test_an_empty_lone_read_keeps_the_single_read_text(tesseract, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 70)
    monkeypatch.setattr(pdf_engine, "recognize_region", lambda image, language: "")
    tesseract(_data(("shaky", 10, 40, 30, 20, 30)))

    assert _read(_two_cells()) == [["shaky", ""]]


# ------------------------------------------------- falling back for the table


def test_a_failing_read_falls_back_to_per_cell_reading(tesseract, region):
    tesseract(error=RuntimeError("tesseract crashed"))

    assert _read(_two_cells()) == [["CELL", "CELL"]]
    assert region == [(100, 100), (100, 100)]


def test_a_read_that_finds_no_words_falls_back_to_per_cell_reading(tesseract, region):
    tesseract(_data(("", 0, 0, 0, 0, -1)))

    assert _read(_two_cells()) == [["CELL", "CELL"]]


def test_words_that_all_fall_outside_the_cells_fall_back_too(tesseract, region):
    tesseract(_data(("stray", 300, 250, 30, 20, 90)))

    assert _read(_two_cells()) == [["CELL", "CELL"]]


def test_a_table_with_no_text_anywhere_is_none(tesseract, monkeypatch):
    monkeypatch.setattr(pdf_engine, "recognize_region", lambda image, language: "")
    tesseract(_data(("", 0, 0, 0, 0, -1)))

    assert _read(_two_cells()) is None


def test_a_table_box_outside_the_page_gives_nothing(tesseract, region):
    table = _table((500, 500, 600, 600), [(500, 500, 600, 600)])  # outside the page image
    fake = tesseract(_data(("x", 1, 1, 5, 5, 90)))

    assert _read(table) is None
    assert fake.calls == []


# ------------------------------------------------------- preparing the crop


def test_dark_cells_are_inverted_and_light_ones_left_alone():
    image = Image.new("RGB", (200, 100), (215, 215, 215))
    ImageDraw.Draw(image).rectangle((0, 0, 99, 99), fill=(60, 60, 60))  # left half: a dark bar
    ImageDraw.Draw(image).rectangle((20, 40, 40, 50), fill=(255, 255, 255))  # white text on it

    inverted = pdf_engine._invert_dark_cells(image, [(0, 0, 100, 100), (100, 0, 200, 100)])

    assert inverted == 1
    assert min(image.getpixel((5, 5))) >= 250  # the fill is white now (stretched on its own)
    assert max(image.getpixel((30, 45))) <= 5  # the text is black now
    assert image.getpixel((150, 50)) == (215, 215, 215)  # the light cell is untouched


def test_a_cell_just_above_the_dark_level_is_not_inverted():
    image = Image.new("RGB", (50, 50), (pdf_engine.TABLE_DARK_CELL_LEVEL + 5,) * 3)

    assert pdf_engine._invert_dark_cells(image, [(0, 0, 50, 50)]) == 0
    assert image.getpixel((10, 10))[0] == pdf_engine.TABLE_DARK_CELL_LEVEL + 5


def test_empty_cell_boxes_are_skipped_when_inverting():
    image = Image.new("RGB", (50, 50), (0, 0, 0))

    assert pdf_engine._invert_dark_cells(image, [(10, 10, 10, 30), (20, 20, 10, 10)]) == 0


def test_cell_borders_are_painted_white_and_the_inside_is_left_alone():
    image = Image.new("RGB", (100, 100), (90, 90, 90))

    pdf_engine._whiten_cell_borders(image, [(10, 10, 60, 60)])

    for point in ((10, 30), (60, 30), (30, 10), (30, 60)):  # the four edges
        assert image.getpixel(point) == (255, 255, 255)
    assert image.getpixel((30, 30)) == (90, 90, 90)  # inside the cell
    assert image.getpixel((80, 80)) == (90, 90, 90)  # outside every cell
    assert image.getpixel((10 + pdf_engine.TABLE_BORDER_PX + 3, 30)) == (90, 90, 90)


def test_border_whitening_works_on_a_grayscale_image_too():
    image = Image.new("L", (50, 50), 100)

    pdf_engine._whiten_cell_borders(image, [(5, 5, 40, 40)])

    assert image.getpixel((5, 20)) == 255
    assert image.getpixel((20, 20)) == 100


def test_the_table_read_gets_borders_whitened_with_the_cells_in_crop_coordinates(
    tesseract, region, monkeypatch
):
    table = _table((20, 10, 220, 110), [(20, 10, 120, 110), (120, 10, 220, 110)])
    tesseract(_data(("x", 10, 40, 20, 20, 90)))
    seen = {}

    def record(image, boxes):
        seen["boxes"] = list(boxes)

    monkeypatch.setattr(pdf_engine, "_whiten_cell_borders", record)

    _read(table, _page(400, 300))

    assert seen["boxes"] == [(0, 0, 100, 100), (100, 0, 200, 100)]


def test_dark_cells_are_inverted_before_the_read(tesseract, region, monkeypatch):
    page = _page()
    ImageDraw.Draw(page).rectangle((0, 0, 99, 99), fill=(50, 50, 50))
    order = []
    real_invert = pdf_engine._invert_dark_cells
    monkeypatch.setattr(
        pdf_engine, "_invert_dark_cells", lambda image, boxes: order.append("invert") or real_invert(image, boxes)
    )
    real_whiten = pdf_engine._whiten_cell_borders
    monkeypatch.setattr(
        pdf_engine, "_whiten_cell_borders", lambda image, boxes: order.append("whiten") or real_whiten(image, boxes)
    )
    fake = tesseract(_data(("x", 10, 40, 20, 20, 90)))

    _read(_two_cells(), page)

    assert order == ["invert", "whiten"]  # borders last, so inverted borders are white again
    assert len(fake.calls) == 1


# ------------------------------------------------------------ the page level


def test_ocr_page_with_tables_reads_each_table_with_the_single_read(tmp_path, monkeypatch):
    png = tmp_path / "page_1.png"
    _page(300, 200).save(png)
    table = _two_cells()
    plumber_page = types.SimpleNamespace(find_tables=lambda: [table])
    used = []

    def single(t, image, scale, language):
        used.append(("single", t is table, scale, language))
        return [["A", "B"]]

    def per_cell(*args):
        raise AssertionError("the per-cell reader must not be used when the single read works")

    monkeypatch.setattr(pdf_engine, "_grid_from_table_ocr", single)
    monkeypatch.setattr(pdf_engine, "_grid_from_cell_ocr", per_cell)
    monkeypatch.setattr(pdf_engine, "recognize", lambda image_path, language: "prose")

    text = PdfEngine._ocr_page_with_tables(png, [plumber_page], 0, 1.5, "tha")

    assert used == [("single", True, 1.5, "tha")]
    assert "prose" in text
    assert "| A | B |" in text


def test_ocr_page_with_tables_without_tables_is_the_plain_page_read(tmp_path, monkeypatch):
    png = tmp_path / "page_1.png"
    _page(300, 200).save(png)
    monkeypatch.setattr(
        pdf_engine, "_grid_from_table_ocr", lambda *a: pytest.fail("no tables, no table read")
    )
    monkeypatch.setattr(pdf_engine, "recognize", lambda image_path, language: "whole page")

    plumber_page = types.SimpleNamespace(find_tables=lambda: [])

    assert PdfEngine._ocr_page_with_tables(png, [plumber_page], 0, 1.0, "tha") == "whole page"


def test_ocr_page_with_tables_falls_back_to_plain_when_every_table_is_empty(tmp_path, monkeypatch):
    png = tmp_path / "page_1.png"
    _page(300, 200).save(png)
    monkeypatch.setattr(pdf_engine, "_grid_from_table_ocr", lambda *a: None)
    reads = []
    monkeypatch.setattr(
        pdf_engine, "recognize", lambda image_path, language: reads.append(image_path.name) or "text"
    )
    plumber_page = types.SimpleNamespace(find_tables=lambda: [_two_cells()])

    assert PdfEngine._ocr_page_with_tables(png, [plumber_page], 0, 1.0, "tha") == "text"
    assert reads == ["page_1_masked.png", "page_1.png"]


# ------------------------------------------------------------- frame tables


def _box_table(*bbox):
    return types.SimpleNamespace(bbox=bbox, rows=[types.SimpleNamespace(cells=[bbox])])


def test_a_frame_table_containing_other_tables_is_dropped():
    frame = _box_table(0, 0, 1000, 600)
    left = _box_table(30, 30, 330, 570)
    right = _box_table(350, 30, 650, 570)

    assert pdf_engine._without_frame_tables([frame, left, right]) == [left, right]


def test_the_order_of_the_remaining_tables_is_kept():
    first = _box_table(500, 0, 600, 100)
    frame = _box_table(0, 0, 1000, 600)
    second = _box_table(10, 10, 100, 100)

    assert pdf_engine._without_frame_tables([first, frame, second]) == [first, second]


def test_non_nested_tables_are_all_kept():
    tables = [_box_table(0, 0, 100, 100), _box_table(120, 0, 220, 100), _box_table(0, 150, 220, 250)]

    assert pdf_engine._without_frame_tables(tables) == tables


def test_a_single_table_is_kept():
    only = _box_table(0, 0, 1000, 600)

    assert pdf_engine._without_frame_tables([only]) == [only]
    assert pdf_engine._without_frame_tables([]) == []


def test_partially_overlapping_tables_are_both_kept():
    a = _box_table(0, 0, 100, 100)
    b = _box_table(60, 40, 160, 140)  # overlaps a, contains nothing

    assert pdf_engine._without_frame_tables([a, b]) == [a, b]


def test_a_big_real_table_with_a_small_one_nested_in_it_is_not_a_frame():
    cells = [(i, 0, i + 1, 10) for i in range(0, 20)]
    big = types.SimpleNamespace(bbox=(0, 0, 20, 10), rows=[types.SimpleNamespace(cells=cells)])
    nested = _box_table(5, 2, 8, 8)

    assert pdf_engine._without_frame_tables([big, nested]) == [big, nested]


def test_a_frame_has_at_most_the_named_number_of_cells():
    def with_cells(count):
        cells = [(0, 0, 1000, 600)] * count
        return types.SimpleNamespace(bbox=(0, 0, 1000, 600), rows=[types.SimpleNamespace(cells=cells)])

    inner = _box_table(30, 30, 330, 570)
    few = with_cells(pdf_engine.FRAME_TABLE_MAX_CELLS)
    many = with_cells(pdf_engine.FRAME_TABLE_MAX_CELLS + 1)

    assert pdf_engine._without_frame_tables([few, inner]) == [inner]
    assert pdf_engine._without_frame_tables([many, inner]) == [many, inner]


def test_tables_with_the_same_box_are_not_frames_of_each_other():
    a, b = _box_table(0, 0, 100, 100), _box_table(0, 0, 100, 100)

    assert pdf_engine._without_frame_tables([a, b]) == [a, b]


def test_the_containment_tolerance_is_a_couple_of_points():
    frame = _box_table(0, 0, 100, 100)
    inside_by_hair = _box_table(-1.5, 10, 90, 100)  # pokes out by less than the tolerance
    sticks_out = _box_table(-6, 10, 90, 100)  # pokes out by more

    assert pdf_engine._without_frame_tables([frame, inside_by_hair]) == [inside_by_hair]
    assert pdf_engine._without_frame_tables([frame, sticks_out]) == [frame, sticks_out]


def test_a_frame_table_is_neither_masked_nor_read_as_a_table(tmp_path, monkeypatch):
    png = tmp_path / "page_1.png"
    _page(300, 200).save(png)
    frame = _box_table(0, 0, 300, 200)
    inner = _box_table(20, 20, 140, 120)
    masked, read, plain_reads = [], [], []
    monkeypatch.setattr(
        pdf_engine, "_mask_table_regions", lambda image, tables, scale: masked.append(list(tables)) or image
    )
    monkeypatch.setattr(
        pdf_engine, "_grid_from_table_ocr", lambda t, *a: read.append(t) or [["cell"]]
    )
    monkeypatch.setattr(
        pdf_engine, "recognize", lambda image_path, language: plain_reads.append(image_path.name) or "prose"
    )
    plumber_page = types.SimpleNamespace(find_tables=lambda: [frame, inner])

    text = PdfEngine._ocr_page_with_tables(png, [plumber_page], 0, 1.0, "tha")

    assert masked == [[inner]]  # the frame is not masked, so its other content stays readable as prose
    assert read == [inner]
    assert plain_reads == ["page_1_masked.png"]
    assert "prose" in text and "| cell |" in text


def test_a_page_with_only_a_frame_and_its_table_reads_the_inner_table(tmp_path, monkeypatch):
    png = tmp_path / "page_1.png"
    _page(300, 200).save(png)
    outer, inner = _box_table(0, 0, 300, 200), _box_table(10, 10, 290, 190)
    seen = []
    monkeypatch.setattr(pdf_engine, "_grid_from_table_ocr", lambda t, *a: seen.append(t) or [["x"]])
    monkeypatch.setattr(pdf_engine, "recognize", lambda image_path, language: "")
    plumber_page = types.SimpleNamespace(find_tables=lambda: [outer, inner])

    PdfEngine._ocr_page_with_tables(png, [plumber_page], 0, 1.0, "tha")

    assert seen == [inner]


# ------------------------------------------------------------------- stats


def test_stats_count_rereads_by_reason_and_time_the_big_read(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 70)
    table = _table((0, 0, 300, 100), [(0, 0, 100, 100), (100, 0, 200, 100), (200, 0, 300, 100)])
    page = _page(400, 300)
    _ink(page, (220, 20, 280, 80))  # right cell: ink, but no word
    tesseract(_data(
        ("sure", 10, 40, 30, 20, 95),  # left cell: fine
        ("shaky", 110, 40, 30, 20, 30),  # middle cell: doubtful
    ))
    stats: dict = {}

    grid = pdf_engine._grid_from_table_ocr(table, page, 1.0, "tha", stats)

    assert grid == [["sure", "CELL", "CELL"]]
    assert stats["reread_low_confidence"] == 1
    assert stats["reread_ink"] == 1
    assert stats["cells"] == 3
    assert stats["big_read_s"] >= 0.0


# ------------------------------------------------------- bullet / dash cells


def _mark(page, *boxes):
    """Black rectangles on *page*, one per ``(x0, y0, x1, y1)``."""
    draw = ImageDraw.Draw(page)
    for box in boxes:
        draw.rectangle(box, fill="black")


DOT = (48, 48, 51, 51)  # 4 x 4 px at the centre of the left cell (0-100 x 0-100)
DASH = (46, 50, 53, 50)  # 8 x 1 px


def test_a_cell_whose_only_ink_is_a_dot_is_a_bullet(tesseract, region):
    page = _page()
    _mark(page, DOT)
    tesseract(_data(("กศกกถา", 40, 40, 20, 20, 90), ("right", 120, 40, 40, 20, 95)))

    grid = _read(_two_cells(), page)

    assert grid == [[pdf_engine.BULLET, "right"]]  # the noise the big read made of it is replaced
    assert region == []


def test_a_cell_whose_only_ink_is_a_short_thin_stroke_is_a_dash(tesseract, region):
    page = _page()
    _mark(page, DASH)
    tesseract(_data(("--", 40, 40, 20, 20, 90), ("right", 120, 40, 40, 20, 95)))

    assert _read(_two_cells(), page) == [[pdf_engine.EN_DASH, "right"]]
    assert region == []


def test_the_symbols_are_a_bullet_and_an_en_dash():
    assert pdf_engine.BULLET == chr(0x2022)
    assert pdf_engine.EN_DASH == chr(0x2013)


def test_a_symbol_cell_is_never_re_read_however_unsure_the_read_was(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_CELL_MIN_CONFIDENCE", 90)
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", 3)
    page = _page()
    _mark(page, DOT)
    tesseract(_data(("5", 40, 40, 10, 20, 5)))

    assert _read(_two_cells(), page) == [[pdf_engine.BULLET, ""]]
    assert region == []


def test_a_symbol_without_any_word_from_the_big_read_is_still_found(tesseract, region):
    page = _page()
    _mark(page, DASH)
    tesseract(_data(("right", 120, 40, 40, 20, 95)))

    assert _read(_two_cells(), page) == [[pdf_engine.EN_DASH, "right"]]
    assert region == []  # decided from the image: no per-cell read for "ink but no word"


def test_a_decimal_number_is_not_a_bullet(tesseract, region):
    page = _page()
    _mark(page, (40, 40, 43, 48), (45, 47, 46, 48), (48, 40, 51, 48))  # "5" "." "8"
    tesseract(_data(("5.8", 38, 38, 16, 12, 95)))

    assert _read(_two_cells(), page) == [["5.8", ""]]
    assert region == []


def test_a_digit_one_is_not_a_dash_or_a_bullet(tesseract, region):
    page = _page()
    _mark(page, (50, 40, 51, 48))  # a thin vertical stroke
    tesseract(_data(("1", 46, 38, 8, 12, 95)))

    assert _read(_two_cells(), page) == [["1", ""]]


def test_two_marks_in_one_cell_are_not_a_bullet(tesseract, region):
    page = _page()
    _mark(page, (30, 48, 33, 51), (68, 48, 71, 51))
    tesseract(_data(("..", 28, 40, 45, 15, 90)))

    assert _read(_two_cells(), page)[0][0] == ".."


def test_a_large_blob_is_not_a_bullet(tesseract, region):
    page = _page()
    _mark(page, (40, 40, 60, 60))
    tesseract(_data(("right", 120, 40, 40, 20, 95)))

    assert _read(_two_cells(), page) == [["CELL", "right"]]  # wordless with ink: the usual per-cell read


def test_a_mark_low_in_the_corner_of_the_cell_is_not_a_symbol():
    gray = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(gray).rectangle((10, 85, 13, 88), fill=0)  # outside the middle band
    assert pdf_engine._symbol_in_cell(gray, (0, 0, 100, 100), 1.0) is None

    ImageDraw.Draw(gray).rectangle((10, 85, 13, 88), fill=255)
    ImageDraw.Draw(gray).rectangle((48, 48, 51, 51), fill=0)  # the same mark in the middle
    assert pdf_engine._symbol_in_cell(gray, (0, 0, 100, 100), 1.0) == pdf_engine.BULLET


def test_an_empty_cell_stays_empty(tesseract, region):
    tesseract(_data(("right", 120, 40, 40, 20, 95)))

    assert _read(_two_cells(), _page()) == [["", "right"]]
    assert region == []


def test_a_few_pixels_of_a_neighbours_ink_at_the_edge_do_not_hide_the_dot(tesseract, region):
    page = _page()
    _mark(page, DOT, (48, 4, 48, 4))  # one pixel of a neighbour's ink at the top edge of the inner area
    tesseract(_data(("noise", 40, 40, 20, 20, 90)))

    assert _read(_two_cells(), page) == [[pdf_engine.BULLET, ""]]


def test_a_big_text_touching_the_edge_is_not_a_symbol(tesseract, region):
    page = _page()
    _mark(page, DOT, (8, 4, 90, 30))  # a wide block touching the top edge, plus the dot
    tesseract(_data(("text", 40, 10, 40, 15, 90)))

    assert _read(_two_cells(), page) == [["text", ""]]


def test_symbol_sizes_hold_at_other_resolutions():
    scale = 300 / 72.0
    gray = Image.new("L", (200, 60), 255)
    ImageDraw.Draw(gray).rectangle((96, 28, 102, 34), fill=0)  # 7 px = 1.7 pt
    assert pdf_engine._symbol_in_cell(gray, (0, 0, 200, 60), scale) == pdf_engine.BULLET
    assert pdf_engine._symbol_in_cell(gray, (0, 0, 200, 60), 1.0) is None  # 7 pt across: not a dot at 72 dpi

    dash = Image.new("L", (200, 60), 255)
    ImageDraw.Draw(dash).rectangle((95, 30, 103, 31), fill=0)  # 9 x 2 px = 2.2 x 0.5 pt
    assert pdf_engine._symbol_in_cell(dash, (0, 0, 200, 60), scale) == pdf_engine.EN_DASH


def test_symbol_cells_can_be_switched_off(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_SYMBOL_CELLS", False)
    page = _page()
    _mark(page, DOT)
    tesseract(_data((".", 40, 40, 10, 10, 90)))

    assert _read(_two_cells(), page) == [[".", ""]]


# ------------------------------------------------------------- short labels


def test_the_short_label_rule_looks_at_what_the_read_returned(monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", 3)
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_LATIN_MAX_CHARS", 6)
    needs = pdf_engine._needs_short_reread

    assert needs("a")  # Thai "สี" read as one Latin letter
    assert needs("atin")  # "หน้า" read as Latin letters
    assert needs("ans")
    assert needs("มม.")  # three characters
    assert needs("Light")  # a real Latin word this short is re-read too: cheap, and the re-read agrees
    assert not needs("ลิตร")  # four Thai characters: not "short" and not Latin
    assert not needs("Welcome")  # seven letters
    assert not needs("42")  # digits are never a misread label
    assert not needs("2.4")
    assert not needs("a1")
    assert not needs("")
    assert not needs("   ")


def test_the_short_label_rule_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", None)
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_LATIN_MAX_CHARS", None)

    assert not pdf_engine._needs_short_reread("a")
    assert not pdf_engine._needs_short_reread("atin")


def test_a_short_misread_label_is_re_read_on_its_own(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", 3)
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_LATIN_MAX_CHARS", 6)
    tesseract(_data(("atin", 10, 40, 40, 20, 96), ("2,393", 120, 40, 40, 20, 96)))  # sure, but wrong

    grid = _read(_two_cells())

    assert grid == [["CELL", "2,393"]]  # the number is left alone
    assert region == [(100, 100)]


def test_a_longer_label_is_not_re_read(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", 3)
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_LATIN_MAX_CHARS", 6)
    tesseract(_data(("ความยาวช่วงล้อ", 10, 40, 80, 20, 96)))

    assert _read(_two_cells()) == [["ความยาวช่วงล้อ", ""]]
    assert region == []


def test_the_short_rule_and_symbols_are_counted_in_the_stats(tesseract, region, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", 3)
    page = _page()
    _mark(page, (148, 48, 151, 51))
    tesseract(_data(("a", 10, 40, 10, 20, 96)))
    stats: dict = {}

    pdf_engine._grid_from_table_ocr(_two_cells(), page, 1.0, "tha", stats)

    assert stats["reread_short"] == 1
    assert stats["symbols"] == 1


# ------------------------------------------------------------ ticks and crosses

_S = 300 / 72.0  # the resolution the engine renders at: marks are 5-8 pt = 20-35 px


def _shape(*draw_calls, size=(240, 60)):
    """A grayscale cell with the given ``(kind, coords, width)`` strokes drawn in black."""
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    for kind, coords, width in draw_calls:
        if kind == "line":
            draw.line(coords, fill=0, width=width)
        else:
            draw.rectangle(coords, fill=0)
    return image


def _classify(image):
    return pdf_engine._symbol_in_cell(image, (0, 0) + image.size, _S)


def _tick(width=4, dx=0):
    return _shape(("line", [(105 + dx, 32), (113 + dx, 42), (132 + dx, 16)], width))


def _cross(width=4):
    return _shape(("line", [(108, 16), (130, 40)], width), ("line", [(108, 40), (130, 16)], width))


def test_a_drawn_tick_is_a_check_mark_at_several_stroke_widths():
    for width in (2, 3, 4, 6):
        assert _classify(_tick(width)) == pdf_engine.CHECK, width


def test_a_drawn_cross_is_a_cross_at_several_stroke_widths():
    for width in (2, 4, 6):
        assert _classify(_cross(width)) == pdf_engine.CROSS, width


def test_the_check_and_cross_symbols():
    assert pdf_engine.CHECK == chr(0x2713)
    assert pdf_engine.CROSS == chr(0x2717)


def test_a_tick_off_to_one_side_of_the_cell_is_still_found():
    assert _classify(_tick(dx=-40)) == pdf_engine.CHECK


@pytest.mark.parametrize(
    "name, image",
    [
        ("V", _shape(("line", [(108, 16), (119, 42), (130, 16)], 4))),
        ("slash", _shape(("line", [(110, 42), (130, 16)], 4))),
        ("thin slash", _shape(("line", [(110, 42), (130, 16)], 2))),
        ("steep slash", _shape(("line", [(112, 44), (124, 12)], 4))),
        ("backslash", _shape(("line", [(110, 16), (130, 42)], 4))),
        ("plus", _shape(("line", [(119, 16), (119, 42)], 4), ("line", [(106, 29), (132, 29)], 4))),
        ("mirrored tick", _shape(("line", [(132, 32), (124, 42), (105, 16)], 4))),
        ("L", _shape(("line", [(110, 16), (110, 42)], 4), ("line", [(110, 42), (130, 42)], 4))),
        (
            "x in 4 x 4",
            _shape(
                ("rect", (70, 16, 82, 42), 0),
                ("line", [(95, 22), (110, 38)], 3), ("line", [(95, 38), (110, 22)], 3),
                ("rect", (128, 16, 140, 42), 0),
            ),
        ),
        (
            "X inside a word",
            _shape(
                ("rect", (60, 20, 70, 40), 0),
                ("line", [(80, 16), (100, 40)], 3), ("line", [(80, 40), (100, 16)], 3),
                ("rect", (110, 20, 120, 40), 0),
            ),
        ),
        ("two ticks", _shape(("line", [(60, 32), (68, 42), (87, 16)], 4), ("line", [(150, 32), (158, 42), (177, 16)], 4))),
    ],
)
def test_lookalikes_are_not_ticks_or_crosses(name, image):
    assert _classify(image) is None, name


def test_a_tick_or_cross_too_small_or_too_big_is_not_one():
    tiny = _shape(("line", [(118, 30), (120, 33), (124, 27)], 1))
    huge = _shape(("line", [(20, 10), (50, 50), (200, 5)], 8), size=(240, 60))
    assert _classify(tiny) is None
    assert _classify(huge) is None


def test_a_tick_is_not_a_bullet_or_a_dash():
    assert _classify(_tick()) not in (pdf_engine.BULLET, pdf_engine.EN_DASH)
    assert _classify(_shape(("rect", (116, 27, 122, 33), 0))) == pdf_engine.BULLET  # a solid dot is still a dot


def test_a_tick_and_a_cross_cell_in_a_table_read_as_symbols(tesseract, region):
    page = _page()
    draw = ImageDraw.Draw(page)
    draw.line([(42, 50), (46, 56), (54, 44)], fill="black", width=2)  # a tick (13 px, so 13 pt at scale 1) in the left cell
    draw.line([(146, 46), (156, 56)], fill="black", width=2)  # and a cross in the right cell
    draw.line([(146, 56), (156, 46)], fill="black", width=2)
    tesseract(_data(("v", 40, 40, 20, 20, 90), ("x", 140, 40, 20, 20, 90)))

    grid = _read(_two_cells(), page)

    assert grid == [[pdf_engine.CHECK, pdf_engine.CROSS]]
    assert region == []  # decided from the image, never re-read


def test_a_letter_x_in_a_word_cell_is_not_turned_into_a_cross(tesseract, region):
    page = _page()
    _mark(page, (30, 45, 34, 58), (60, 45, 64, 58))  # two stems of other letters
    draw = ImageDraw.Draw(page)
    draw.line([(40, 46), (54, 58)], fill="black", width=2)
    draw.line([(40, 58), (54, 46)], fill="black", width=2)
    tesseract(_data(("Maxi", 28, 40, 40, 20, 95)))

    assert _read(_two_cells(), page) == [["Maxi", ""]]


# ------------------------------------------------------------ dark bands in a cell


def test_a_dark_bar_inside_a_tall_light_cell_is_inverted_on_its_own():
    image = Image.new("RGB", (100, 120), (215, 215, 215))
    ImageDraw.Draw(image).rectangle((0, 0, 99, 19), fill=(60, 60, 60))  # a bar across the top
    ImageDraw.Draw(image).rectangle((20, 6, 60, 13), fill=(255, 255, 255))  # its white text
    ImageDraw.Draw(image).rectangle((20, 70, 60, 78), fill=(0, 0, 0))  # dark text on the light part

    inverted = pdf_engine._invert_dark_cells(image, [(0, 0, 100, 120)])

    assert inverted == 1
    assert min(image.getpixel((5, 5))) >= 250  # the bar is white now
    assert max(image.getpixel((40, 10))) <= 5  # its text is black
    assert image.getpixel((5, 100)) == (215, 215, 215)  # the light part is untouched
    assert image.getpixel((40, 74)) == (0, 0, 0)


def test_dark_text_rows_in_a_light_cell_are_not_a_band():
    image = Image.new("L", (100, 40), 215)
    for x in range(0, 100, 5):  # 40 % ink across a 14-row line of heavy text
        ImageDraw.Draw(image).rectangle((x, 10, x + 1, 24), fill=0)
    before = list(image.getdata())

    assert pdf_engine._invert_dark_bands(image, (0, 0, 100, 40)) == 0
    assert list(image.getdata()) == before


def test_a_dark_stripe_thinner_than_the_minimum_is_not_a_band():
    image = Image.new("L", (100, 40), 215)
    ImageDraw.Draw(image).rectangle((0, 10, 99, 10 + pdf_engine.TABLE_DARK_BAND_MIN_PX - 2), fill=40)

    assert pdf_engine._invert_dark_bands(image, (0, 0, 100, 40)) == 0


def test_a_fully_dark_cell_is_still_inverted_whole():
    image = Image.new("RGB", (100, 30), (100, 100, 100))

    assert pdf_engine._invert_dark_cells(image, [(0, 0, 100, 30)]) == 1


# --------------------------------------------------- re-reading short Thai labels


class _ShortRead(types.ModuleType):
    """pytesseract stand-in for the one-word re-read: records what it was given."""

    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, text="สี", conf=80.0):
        super().__init__("pytesseract")
        self.text, self.conf, self.calls = text, conf, []

    def image_to_data(self, image, lang="eng", config="", output_type=None):
        self.calls.append({"size": image.size, "lang": lang, "config": config})
        words = [self.text] if self.text else []
        return {
            "text": words, "conf": [self.conf] * len(words), "block_num": [1] * len(words),
            "par_num": [1] * len(words), "line_num": [1] * len(words),
            "left": [10] * len(words), "top": [10] * len(words), "width": [30] * len(words),
            "height": [20] * len(words),
        }


def _label_crop():
    """A wide cell with one small mark of ink at its left (a short label)."""
    crop = Image.new("RGB", (214, 28), (215, 215, 215))
    ImageDraw.Draw(crop).rectangle((6, 8, 18, 20), fill=(0, 0, 0))
    return crop


def test_a_short_label_is_read_with_thai_only_after_cropping_to_its_ink(monkeypatch, region):
    fake = _ShortRead("สี")
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert pdf_engine._reread_short_cell(_label_crop(), "tha+eng", _S) == "สี"

    call = fake.calls[0]
    assert call["lang"] == "tha"  # no eng: with it a tiny Thai word reads as "a"
    assert call["config"] == "--psm 7"
    assert call["size"][0] < 214 * pdf_engine.TABLE_SHORT_REREAD_MAX_FACTOR  # cropped, not the whole cell
    assert call["size"][1] > 28  # and enlarged
    assert region == [(214, 28)]  # the plain per-cell read goes first and found no Thai


def test_the_thai_only_read_is_not_used_without_a_thai_letter(monkeypatch, region):
    monkeypatch.setitem(sys.modules, "pytesseract", _ShortRead("LED"))

    assert pdf_engine._reread_short_cell(_label_crop(), "tha+eng", _S) == "CELL"
    assert region == [(214, 28)]  # fell back to the plain per-cell read


def test_an_unsure_thai_only_read_is_not_used(monkeypatch, region):
    monkeypatch.setitem(sys.modules, "pytesseract", _ShortRead("สี", conf=pdf_engine.TABLE_SHORT_REREAD_MIN_CONF - 1))

    assert pdf_engine._reread_short_cell(_label_crop(), "tha+eng", _S) == "CELL"


def test_without_thai_in_the_languages_the_plain_read_is_used(monkeypatch, region):
    fake = _ShortRead("สี")
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert pdf_engine._reread_short_cell(_label_crop(), "eng", _S) == "CELL"
    assert fake.calls == []


def test_a_cell_without_ink_uses_the_plain_read(monkeypatch, region):
    fake = _ShortRead("สี")
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert pdf_engine._reread_short_cell(Image.new("RGB", (100, 30), "white"), "tha+eng", _S) == "CELL"
    assert fake.calls == []


def test_a_misread_label_goes_through_the_short_reader(tesseract, monkeypatch):
    monkeypatch.setattr(pdf_engine, "TABLE_SHORT_TEXT_MAX_CHARS", 3)
    seen = []
    monkeypatch.setattr(
        pdf_engine, "_reread_short_cell", lambda crop, language, scale: seen.append((crop.size, language, scale)) or "สี"
    )
    tesseract(_data(("a", 10, 40, 10, 20, 96)))

    assert _read(_two_cells()) == [["สี", ""]]
    assert seen == [((100, 100), "tha+eng", 1.0)]


def test_a_dash_or_dot_is_not_a_short_label():
    for text in ("-", "--", ".", "..", "•", "- -"):
        assert not pdf_engine._needs_short_reread(text), text


def test_a_short_label_read_in_pieces_is_joined_without_inventing_spaces():
    join = pdf_engine._join_label_words
    key = (1, 1, 1)

    assert join([(key, "มม", 10, 0, 20, 20, 90.0), (key, ".", 32, 0, 4, 20, 90.0)]) == "มม."
    assert join([(key, "ป", 50, 0, 10, 20, 90.0), (key, "ม", 5, 0, 10, 20, 90.0)]) == "มป"  # left to right
    assert join([(key, "Light", 5, 0, 30, 20, 90.0), (key, "2", 40, 0, 8, 20, 90.0)]) == "Light 2"


def test_a_plain_read_that_found_thai_is_kept_and_the_thai_only_read_is_not_run(monkeypatch):
    fake = _ShortRead("ลิตธร")  # what the Thai-only read would garble it into
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(pdf_engine, "recognize_region", lambda image, language: "ลิตร")

    assert pdf_engine._reread_short_cell(_label_crop(), "tha+eng", _S) == "ลิตร"
    assert fake.calls == []


def test_a_latin_only_plain_read_is_replaced_by_the_thai_only_read(monkeypatch):
    fake = _ShortRead("สี")
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setattr(pdf_engine, "recognize_region", lambda image, language: "a")

    assert pdf_engine._reread_short_cell(_label_crop(), "tha+eng", _S) == "สี"
