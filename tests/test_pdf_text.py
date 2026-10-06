"""Thai text repair for PDFs whose font maps sara aa to sara am."""

from __future__ import annotations

import types

from doc2md.core import pdf_text
from doc2md.core.pdf_text import (
    SARA_AA,
    SARA_AM,
    find_sara_bug_fonts,
    font_family,
    page_lines,
    text_in,
)

FONT = "AngsanaUPC"
BUGGY = frozenset({font_family(FONT)})


def _char(text, x0, width=4.0, font=FONT, y0=0.0, y1=10.0):
    return {"c": text, "bbox": (x0, y0, x0 + width, y1)}


def _page(*lines, font=FONT):
    """A fake PyMuPDF page; each line is a list of ``(text, x0, width)``."""
    blocks = [
        {
            "lines": [
                {"spans": [{"font": font, "chars": [_char(t, x, w) for t, x, w in line]}]}
            ]
        }
        for line in lines
    ]

    def get_text(kind="text"):
        if kind == "rawdict":
            return {"blocks": blocks}
        return "\n".join("".join(t for t, _x, _w in line) for line in lines)

    return types.SimpleNamespace(get_text=get_text, rotation=0)


def _doc(*pages):
    return list(pages)


# "ตำบล" in the broken font: ต, a zero-width space for nikhahit, then the aa glyph.
TAMBON = [("ต", 0, 4), (" ", 4, 0), (SARA_AM, 4, 3), ("บ", 7, 4), ("ล", 11, 4)]
# "บาง": the same aa glyph, with no zero-width space before it.
BANG = [("บ", 0, 4), (SARA_AM, 4, 3), ("ง", 7, 4)]
# "น้ำ": space, tone mark, glyph.
NAM = [("น", 0, 4), (" ", 4, 0), ("้", 4, 0), (SARA_AM, 4, 3)]


def test_a_font_is_flagged_only_when_a_true_sara_am_pattern_is_seen():
    assert find_sara_bug_fonts(_doc(_page(TAMBON))) == BUGGY
    assert find_sara_bug_fonts(_doc(_page(BANG))) == frozenset()


def test_the_pattern_is_found_through_a_tone_mark():
    assert find_sara_bug_fonts(_doc(_page(NAM))) == BUGGY


def test_detection_looks_across_pages():
    assert find_sara_bug_fonts(_doc(_page(BANG), _page(TAMBON))) == BUGGY


def test_bare_sara_am_becomes_sara_aa_and_the_real_one_is_kept():
    page = _page(TAMBON + [(" ", 15, 2)] + [("บ", 17, 4), (SARA_AM, 21, 3), ("ง", 24, 4)])

    text = text_in(page_lines(page, BUGGY))

    assert text == "ตำบล บาง"


def test_sara_am_after_a_tone_mark_is_kept():
    text = text_in(page_lines(_page(NAM), BUGGY))

    assert text == "น้" + SARA_AM


def test_a_correctly_encoded_font_is_left_alone():
    text = text_in(page_lines(_page(BANG), frozenset()))

    assert SARA_AM in text
    assert SARA_AA not in text


def test_zero_width_spaces_are_never_text():
    page = _page([("ก", 0, 4), (" ", 4, 0), ("ข", 4, 4)])

    assert text_in(page_lines(page)) == "กข"


def test_other_fonts_are_not_touched_by_a_flagged_font():
    page = _page(BANG, font="Other")

    assert SARA_AM in text_in(page_lines(page, BUGGY))


def test_text_in_a_box_and_outside_a_box():
    page = _page(
        [("A", 0, 4), ("B", 50, 4)],
    )
    lines = page_lines(page)

    assert text_in(lines, include=(40, 0, 60, 10)) == "B"
    assert text_in(lines, exclude=[(40, 0, 60, 10)]) == "A"


def test_fragments_on_one_visual_row_are_merged_for_table_cells():
    page = types.SimpleNamespace(
        rotation=0,
        get_text=lambda kind="text": {
            "blocks": [
                {"lines": [{"spans": [{"font": FONT, "chars": [_char("label", 0, 20)]}]}]},
                {"lines": [{"spans": [{"font": FONT, "chars": [_char("note", 60, 16)]}]}]},
                {"lines": [{"spans": [{"font": FONT, "chars": [
                    {"c": "next", "bbox": (0, 14.0, 20, 24.0)}]}]}]},
            ]
        },
    )
    lines = page_lines(page)

    assert text_in(lines, merge_lines=True) == "label note\nnext"
    assert text_in(lines) == "label\nnote\nnext"


def test_a_page_that_cannot_be_read_does_not_break_detection():
    broken = types.SimpleNamespace(get_text=lambda kind="text": 1 / 0)

    assert find_sara_bug_fonts(_doc(broken, _page(TAMBON))) == BUGGY


def test_detection_is_cheap_for_pages_without_sara_am(monkeypatch):
    calls = []
    page = _page([("ก", 0, 4)])
    original = page.get_text

    def counting(kind="text"):
        calls.append(kind)
        return original(kind)

    page.get_text = counting
    find_sara_bug_fonts(_doc(page))

    assert "rawdict" not in calls


def test_scan_is_limited_to_the_first_pages():
    pages = [_page([("ก", 0, 4)]) for _ in range(pdf_text._SCAN_PAGES)] + [_page(TAMBON)]

    assert find_sara_bug_fonts(_doc(*pages)) == frozenset()


def test_bold_and_regular_variants_are_one_family():
    assert font_family("Angsana New,Bold") == font_family("Angsana New")
    assert font_family("ABCDEE+AngsanaUPC-Bold") == font_family("AngsanaUPC")
    assert font_family("THSarabunNew-BoldItalic") == font_family("THSarabunNew")
    assert font_family("AngsanaUPC") != font_family("THSarabunNew")


def test_a_pattern_seen_in_the_bold_face_repairs_the_regular_face():
    bold = _page(TAMBON, font="Angsana New,Bold")
    regular = _page(BANG, font="Angsana New")
    flagged = find_sara_bug_fonts(_doc(bold))

    assert SARA_AA in text_in(page_lines(regular, flagged))


# --- text layers no rule can repair


def test_symbols_in_place_of_tone_marks_are_detected():
    garbled = "น้ำท!วมในเขตพื้นที่กรุงเทพฯและสมุทรปราการ ผ!านมา ต!อไป ท!วม " * 6

    assert pdf_text.thai_text_is_corrupt(garbled)


def test_control_characters_in_thai_text_are_detected():
    garbled = ("กรมพัฒนาธุรกิจการค้า\x1a กระทรวงพาณิชย์\x1e " * 5) + "บริษัทจำกัด" * 10

    assert pdf_text.thai_text_is_corrupt(garbled)


def test_control_character_soup_with_zero_thai_letters_is_still_detected():
    """A font whose character map is broken badly enough loses every Thai
    codepoint, not just the sara am/aa pair - the page extracts as near-total
    control-character noise with no Thai letters left to count at all. The
    control-character check must fire regardless, not bail out early because
    there happens to be no Thai left to measure against (seen on a real PDF:
    an Identity-H/Type0 embedded font, 1368 control chars, 0 Thai letters,
    in under 5000 characters of extracted text)."""
    garbled = "\x1d\x07\x1a\x0c\x19\x1e\x06\x0f\x18\x03\x81\x03" * 10

    assert pdf_text.thai_text_is_corrupt(garbled)


def test_clean_thai_text_and_short_text_are_not_flagged():
    clean = "ขอรับรองว่าบริษัทนี้ได้จดทะเบียนเป็นนิติบุคคลตามประมวลกฎหมายแพ่งและพาณิชย์ " * 8

    assert not pdf_text.thai_text_is_corrupt(clean)
    assert not pdf_text.thai_text_is_corrupt("ท!วม")


def test_a_year_after_a_thai_word_is_not_corruption():
    text = "บริษัทฯได้มีการติดตามสถานการณ์น้ำท่วมปี 2569 ตั้งแต่วันที่ 25 – 28 กันยายน พ.ศ.2569 " * 8

    assert not pdf_text.thai_text_is_corrupt(text)
