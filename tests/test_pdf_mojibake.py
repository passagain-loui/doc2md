"""A text layer whose Thai tone marks and vowels came out as Latin Extended letters.

A font with a wrong character map can send marks to code points like U+0113 or
U+0115, so a word that should end in a tone mark extracts with a stray ``ē`` or
``ĕ`` inside it. Such a page is read by OCR like any other mis-encoded page.

Every string here is made up; none is taken from a real document.
"""

from __future__ import annotations

import pymupdf
import pytest

from doc2md.core import pdf_text
from doc2md.core.pdf_text import (
    MOJIBAKE_MAX_THAI_PER_HIT,
    MOJIBAKE_MIN_HITS,
    latin_ext_in_thai_count,
    thai_text_is_corrupt,
)
from doc2md.engine import pdf_engine
from doc2md.engine.pdf_engine import PdfEngine

# A clean Thai sentence (about 70 Thai letters) used as the page's honest content.
CLEAN = "ขอรับรองว่าบริษัทนี้ได้จดทะเบียนเป็นนิติบุคคลตามประมวลกฎหมายแพ่งและพาณิชย์ "


def _page(*lines: str, clean_repeats: int = 2) -> str:
    return "\n".join([*lines, *([CLEAN] * clean_repeats)])


# Made-up words with the tone mark or vowel swapped for the stray letter.
MOJIBAKE_WORDS = {
    "tone mark in the middle": "ขēาวผัด",
    "tone mark before a final": "ห" + "Ē" + "องน" + "Ē" + "ำ",
    "two-letter run": "ตูēĒเย็น",
    "after another mark": "ก่ēอน",
    "capital letter": "สวยĖดี",
    "small c with dot": "เปċด",
    "d with stroke": "ไฟฟĐา",
    "breve letters": "ดĕานหนĕา",
    "Latin-1 letters": "พôเศษ นิùว",
}


@pytest.mark.parametrize("word", list(MOJIBAKE_WORDS.values()), ids=list(MOJIBAKE_WORDS))
def test_each_mojibake_pattern_is_detected(word):
    text = _page(*([word] * MOJIBAKE_MIN_HITS))

    assert latin_ext_in_thai_count(text) >= MOJIBAKE_MIN_HITS
    assert thai_text_is_corrupt(text)


def test_mojibake_is_found_even_with_little_other_thai_on_the_page():
    """Unlike the symbol heuristic, this one needs no 50-letter Thai baseline."""
    text = "ขēาว ผูēนำ ตูēเย็น"

    assert len(text) < 50
    assert thai_text_is_corrupt(text)


@pytest.mark.parametrize(
    "text",
    [
        "Café ร้าน Café ร้าน Café ร้าน Café ร้าน",
        "ร้าน Café และ Škoda และ Zürich และ São Paulo " * 6,
        "ไปที่ Köln แล้วต่อไป Málaga จากนั้นไป Łódź " * 6,
    ],
    ids=["cafe", "european-words-between-spaces", "european-words-in-thai-sentences"],
)
def test_european_words_next_to_thai_are_not_mojibake(text):
    assert latin_ext_in_thai_count(text) == 0
    assert not thai_text_is_corrupt(_page(text))


def test_a_latin_word_glued_to_thai_on_one_side_only_is_not_mojibake():
    text = _page(*(["รถŠkoda รุ่นใหม่ Ñandú"] * 10))

    assert latin_ext_in_thai_count(text) == 0
    assert not thai_text_is_corrupt(text)


@pytest.mark.parametrize(
    "text",
    [
        "ความสูง 360º ของตัวรถ " * 10,  # U+00BA ordinal indicator: not a letter
        "คำว่า “ตัวอย่าง” และ “ทดสอบ” " * 10,  # curly quotes
        "ราคา 5×ก÷ข บาท " * 10,  # multiplication and division signs
        "ก×ข ค÷ง ก×ข ค÷ง",  # between Thai letters, still not letters
        "กºkข ก”ข ก°ข ก±ข ก©ข",  # other punctuation and symbols
    ],
    ids=["degree-like-ordinal", "curly-quotes", "times-divide-by-digits", "times-divide-in-word", "symbols"],
)
def test_signs_and_quotes_are_not_latin_letters(text):
    assert latin_ext_in_thai_count(text) == 0
    assert not thai_text_is_corrupt(_page(text))


def test_a_thai_mark_counts_as_a_thai_neighbour():
    assert latin_ext_in_thai_count("ก่ēข") == 1  # tone mark, stray, letter
    assert latin_ext_in_thai_count("กē่") == 1  # letter, stray, tone mark


def test_a_run_longer_than_two_is_not_counted():
    assert latin_ext_in_thai_count("กēĒēข") == 0


# --- the thresholds


def _hits(count: int) -> str:
    return " ".join(["ขēาว"] * count)


def test_one_less_than_the_minimum_number_of_hits_is_not_flagged():
    text = _hits(MOJIBAKE_MIN_HITS - 1)

    assert latin_ext_in_thai_count(text) == MOJIBAKE_MIN_HITS - 1
    assert not thai_text_is_corrupt(text)


def test_the_minimum_number_of_hits_is_flagged():
    text = _hits(MOJIBAKE_MIN_HITS)

    assert latin_ext_in_thai_count(text) == MOJIBAKE_MIN_HITS
    assert thai_text_is_corrupt(text)


def _thai_letters(text: str) -> int:
    return len(pdf_text._THAI_LETTER.findall(text))


def _with_filler(hits: int, thai_total: int) -> str:
    """*hits* sandwiched letters on a page of exactly *thai_total* Thai letters."""
    text = _hits(hits)
    missing = thai_total - _thai_letters(text)
    assert missing >= 0
    # "ก" repeated: Thai letters that never touch a stray letter
    return text + " " + "ก" * missing


def test_the_share_boundary_is_one_hit_per_the_stated_number_of_thai_letters():
    hits = MOJIBAKE_MIN_HITS
    limit = hits * MOJIBAKE_MAX_THAI_PER_HIT

    on_the_limit = _with_filler(hits, limit)
    over_the_limit = _with_filler(hits, limit + 1)

    assert _thai_letters(on_the_limit) == limit
    assert latin_ext_in_thai_count(on_the_limit) == hits
    assert thai_text_is_corrupt(on_the_limit)
    assert _thai_letters(over_the_limit) == limit + 1
    assert latin_ext_in_thai_count(over_the_limit) == hits
    assert not thai_text_is_corrupt(over_the_limit)


def test_a_long_clean_page_with_a_few_oddities_is_not_condemned():
    text = CLEAN * 200 + _hits(MOJIBAKE_MIN_HITS + 2)

    assert latin_ext_in_thai_count(text) == MOJIBAKE_MIN_HITS + 2
    assert not thai_text_is_corrupt(text)


def test_more_hits_raise_the_allowed_amount_of_thai():
    hits = MOJIBAKE_MIN_HITS * 4
    text = _with_filler(hits, hits * MOJIBAKE_MAX_THAI_PER_HIT)

    assert _thai_letters(text) == hits * MOJIBAKE_MAX_THAI_PER_HIT
    assert thai_text_is_corrupt(text)
    assert not thai_text_is_corrupt(_with_filler(hits, hits * MOJIBAKE_MAX_THAI_PER_HIT + 1))


def test_the_existing_checks_still_fire_alongside():
    assert thai_text_is_corrupt("กรมพัฒนาธุรกิจการค้า\x1a\x1e\x1d " * 3)
    assert thai_text_is_corrupt("น้ำท!วมในเขตพื้นที่กรุงเทพฯและสมุทรปราการ ผ!านมา ต!อไป ท!วม " * 6)
    assert not thai_text_is_corrupt(CLEAN * 8)


# --- the page goes to OCR through the existing flow


def _pdf(path, thai_font, *pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        y = 80
        for chunk in [text[i:i + 55] for i in range(0, len(text), 55)]:
            page.insert_text((50, y), chunk, fontname="TH", fontfile=thai_font, fontsize=12)
            y += 18
    doc.save(str(path))
    doc.close()
    return path


def test_a_mojibake_page_is_read_by_ocr_and_a_clean_page_is_not(tmp_path, thai_font, monkeypatch):
    pytest.importorskip("pytesseract")
    mojibake = " ".join(["ขēาวผัด ตูēเย็น หĒอง"] * 4) + " " + CLEAN
    path = _pdf(tmp_path / "m.pdf", thai_font, mojibake, CLEAN * 3)
    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: None))
    monkeypatch.setattr(pdf_engine, "prepare_tesseract", lambda language: "tesseract")
    seen: list[str] = []

    def fake_recognize(image_path, language):
        seen.append(str(image_path))
        return "ข้อความจาก OCR"

    monkeypatch.setattr(pdf_engine, "recognize", fake_recognize)

    # Prove first that the extracted text layer carries the pattern, whatever the font did.
    doc = pymupdf.open(str(path))
    layer = doc[0].get_text("text")
    doc.close()
    assert thai_text_is_corrupt(layer), "the synthetic text layer lost the stray letters"

    output = PdfEngine().convert_structured(path, {})

    # one plain read as the reference for the repair, then the full read of the page
    # the map could not explain
    assert len(seen) == 2
    assert "ข้อความจาก OCR" in output.markdown
    assert "ขēาว" not in output.markdown
    assert "ขอรับรองว่าบริษัทนี้" in output.markdown  # the clean page keeps its own text
    assert output.metrics.ocr_pages_success == 1
