"""Swapped Thai marks are put back with a map learned from the document itself.

The text layer has every letter right; the font's character map sent the marks
to other characters, consistently. OCR reads the same page correctly, so where
the two agree on the surrounding letters, the marks OCR has are what the stray
character stood for. A page whose strays are all explained keeps its own text
layer; any other page is read by OCR.

Every string here is made up; none is taken from a real document.
"""

from __future__ import annotations

import pymupdf
import pytest

from doc2md.core.pdf_text import (
    MOJIBAKE_MAP_MIN_AGREEMENT,
    MOJIBAKE_MAP_MIN_VOTES,
    learn_mojibake_map,
    mojibake_votes,
    repair_mojibake,
    thai_text_is_corrupt,
)
from doc2md.core import review
from doc2md.core.converter import Converter
from doc2md.core.review import (
    REPAIR_LOSS_CONFIDENCE,
    REVIEW_CLOSE,
    REVIEW_OPEN,
    ReviewLine,
    with_inline_flags,
)
from doc2md.engine import pdf_engine
from doc2md.engine.pdf_engine import (
    MOJIBAKE_REPAIRED_NOTE,
    PdfEngine,
    _OcrOutcome,
)

MAI_EK, MAI_THO, THANTHAKHAT = "่", "้", "์"
SARA_UEE_EK = "ื่"
# What this made-up font does: one stray character per mark, and one for a vowel plus a tone mark.
EK, THO, THAN, UEE_EK = "Ē", "ē", "Ė", "ë"
STRAYS = {SARA_UEE_EK: UEE_EK, MAI_EK: EK, MAI_THO: THO, THANTHAKHAT: THAN}
EXPECTED = {EK: MAI_EK, THO: MAI_THO, THAN: THANTHAKHAT, UEE_EK: SARA_UEE_EK}

SENTENCES = [
    "ผู้ใหญ่ใจดีเล่านิทานให้เด็กฟังทุกค่ำคืน",
    "พี่น้องช่วยกันปลูกต้นไม้ริมน้ำเขียวขจี",
    "ครูสอนเด็กนักเรียนเขียนหนังสือที่โรงเรียนใหม่",
    "เสื่อผืนใหม่วางอยู่ข้างเตาไฟในครัว",
    "เพื่อนเล่าเรื่องเมืองเหนือให้ฟังทุกวัน",
    "คอมพิวเตอร์เครื่องใหม่ราคาไม่แพงโทรศัพท์ก็ถูก",
    "นักร้องสาวขับร้องเพลงไพเราะที่เวทีใหญ่",
    "ช่างภาพถ่ายรูปนักท่องเที่ยวริมทะเลสาบ",
]
TRUTH = "\n".join(SENTENCES)


def swap(text: str, table: dict[str, str] = STRAYS) -> str:
    for mark, stray in table.items():  # the two-mark entry first
        text = text.replace(mark, stray)
    return text


LAYER = swap(TRUTH)


# --- learning


def test_the_map_is_learned_from_aligned_pairs():
    assert learn_mojibake_map(LAYER, TRUTH) == EXPECTED


def test_one_stray_character_can_stand_for_two_marks():
    assert learn_mojibake_map(LAYER, TRUTH)[UEE_EK] == SARA_UEE_EK


def test_word_final_marks_are_learned_too():
    """A stray after the last letter of a word has no letter after it to its right."""
    truth = "\n".join(["ที่นี่", "ที่นั่น", "ปีนี้ปีหน้า", "บ้านเมืองสงบสุขดี", "เด็กๆชอบเล่นของเล่น"] * 3)
    layer = swap(truth)

    assert learn_mojibake_map(layer, truth).get(EK) == MAI_EK


def test_nothing_is_learned_when_ocr_has_none_of_the_text():
    assert learn_mojibake_map(LAYER, "ข้อความอื่นทั้งหมดไม่เกี่ยวข้องกันเลย") == {}
    assert learn_mojibake_map(LAYER, "") == {}


def test_a_stray_with_conflicting_votes_is_not_mapped():
    """OCR says one thing in half the places and another in the rest."""
    base = ["ตัวน้อยกำลังวิ่ง", "ครูให้ดินสอเด็ก", "ลูกมาถึงบ้านเรา", "ปลาในน้ำสะอาด"]
    layer = swap("\n".join(base), {MAI_THO: THO})
    ocr = "\n".join([base[0], base[1], base[2].replace(MAI_THO, MAI_EK), base[3].replace(MAI_THO, MAI_EK)])

    votes = mojibake_votes(layer, ocr)

    assert sorted(votes[THO].values()) == [2, 2]
    assert THO not in learn_mojibake_map(layer, ocr)


def test_agreement_below_the_threshold_is_not_mapped_and_at_it_is():
    from collections import Counter

    from doc2md.core import pdf_text

    total = 20
    enough = int(total * MOJIBAKE_MAP_MIN_AGREEMENT)  # exactly at the threshold
    assert enough / total >= MOJIBAKE_MAP_MIN_AGREEMENT > (enough - 1) / total
    assert enough >= MOJIBAKE_MAP_MIN_VOTES

    def accepted(agreeing: int) -> dict[str, str]:
        return pdf_text._accepted({THO: Counter({MAI_THO: agreeing, MAI_EK: total - agreeing})})

    assert accepted(enough) == {THO: MAI_THO}
    assert accepted(enough - 1) == {}


def test_an_under_voted_stray_is_not_mapped_and_a_fully_voted_one_is():
    base = ["ตัวน้อยกำลังวิ่ง", "ครูให้ดินสอเด็ก", "แมวนอนบนหลังคาสูง", "ลูกมาถึงบ้านเรา"]
    chosen = base[:MOJIBAKE_MAP_MIN_VOTES]

    def learned(phrases: list[str]) -> dict[str, str]:
        text = "\n".join(phrases)
        return learn_mojibake_map(swap(text, {MAI_THO: THO}), text)

    assert learned(chosen) == {THO: MAI_THO}
    assert learned(chosen[: MOJIBAKE_MAP_MIN_VOTES - 1]) == {}


def test_a_mark_that_cannot_sit_on_the_letter_is_not_voted_for():
    """OCR's cluster must be possible Thai: never two tone marks on one letter."""
    layer = swap("ครูให้ดินสอเด็กเล็ก" * 3, {MAI_THO: THO}) + "\n" + "ครู" + "ให" + MAI_EK + MAI_THO + "ดินสอเด็กเล็ก"
    ocr = ("ครูให" + MAI_EK + MAI_THO + "ดินสอเด็กเล็ก\n") * 3

    assert THO not in learn_mojibake_map(layer, ocr)


# --- repair


MAPPING = {THO: MAI_THO, EK: MAI_EK, UEE_EK: SARA_UEE_EK}


def test_repair_puts_the_marks_back():
    assert repair_mojibake(swap(TRUTH), EXPECTED) == (TRUTH, 0)


def test_repair_counts_the_strays_it_has_no_mapping_for():
    text = "ผู" + THO + "ใหญ" + EK + "ใจดี" + "ฟ" + "ę" + "ง"  # the last stray is not in the map

    fixed, left = repair_mojibake(text, MAPPING)

    assert left == 1
    assert fixed == "ผู้ใหญ่ใจดีฟęง"


def test_unmapped_strays_can_be_left_out_instead():
    text = "ผู" + THO + "ใหญ" + EK + "ใจดีฟ" + "ę" + "ง"

    assert repair_mojibake(text, MAPPING, drop_unmapped=True) == ("ผู้ใหญ่ใจดีฟง", 1)


def test_repair_only_touches_characters_next_to_thai():
    text = "Café " + THO + " Škoda ร้านCafé Zürich ผู" + THO + "ใหญ่"
    mapping = {THO: MAI_THO, "é": MAI_EK, "Š": MAI_EK, "ü": MAI_EK}

    fixed, left = repair_mojibake(text, mapping)

    assert fixed == "Café " + THO + " Škoda ร้านCafé Zürich ผู้ใหญ่"
    assert left == 0


def test_a_stray_after_a_thai_letter_at_the_end_of_a_word_is_repaired():
    assert repair_mojibake("ที" + EK + " นี" + EK + "\nปี" + EK, MAPPING) == ("ที่ นี่\nปี่", 0)


def test_private_use_variants_are_handled_like_any_other_stray():
    assert repair_mojibake("ใหมปี", {"": MAI_EK}) == ("ใหม่ปี", 0)
    assert repair_mojibake("ใหมปี", {}) == ("ใหมปี", 1)


def test_repair_changes_nothing_in_text_without_strays():
    assert repair_mojibake(TRUTH, EXPECTED) == (TRUTH, 0)
    assert repair_mojibake("", EXPECTED) == ("", 0)


# --- through the engine


def _pdf_lines(path, thai_font, *pages):
    """One PDF page per list of lines, each line on its own row."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 80
        for line in lines:
            page.insert_text((50, y), line, fontname="TH", fontfile=thai_font, fontsize=12)
            y += 18
    doc.save(str(path))
    doc.close()
    return path


CLEAN_LINES = ["ขอรับรองว่าบริษัทนี้ได้จดทะเบียนเป็นนิติบุคคล", "ตามประมวลกฎหมายแพ่งและพาณิชย์ทุกประการ"] * 3


@pytest.fixture
def fake_ocr(monkeypatch):
    """OCR 'available' and reading the made-up page correctly; counts the pages it reads."""
    pytest.importorskip("pytesseract")
    monkeypatch.setattr(PdfEngine, "_ocr_unavailable_reason", staticmethod(lambda: None))
    monkeypatch.setattr(pdf_engine, "prepare_tesseract", lambda language: "tesseract")
    reads: list[str] = []

    def recognize(image_path, language):
        reads.append(str(image_path))
        return TRUTH

    monkeypatch.setattr(pdf_engine, "recognize", recognize)
    return reads


def test_a_fully_explained_page_keeps_its_text_layer_with_a_note(tmp_path, thai_font, fake_ocr):
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, swap(TRUTH).split("\n"), CLEAN_LINES)
    layer = pymupdf.open(str(path))[0].get_text("text")
    assert thai_text_is_corrupt(layer), "the synthetic text layer lost the stray characters"

    output = PdfEngine().convert_structured(path, {})

    assert len(fake_ocr) == 1  # OCR still runs: it is the reference
    assert MOJIBAKE_REPAIRED_NOTE in output.markdown
    assert "read by OCR" not in output.markdown
    for sentence in SENTENCES:
        assert sentence in output.markdown
    assert not any(stray in output.markdown for stray in EXPECTED)
    assert "ขอรับรองว่าบริษัทนี้" in output.markdown  # the clean page is untouched
    assert output.metrics.ocr_pages_success == 0


def test_the_unmapped_share_is_set_to_a_fifth():
    assert pdf_engine.MOJIBAKE_MAX_UNMAPPED_SHARE == 0.2


def test_a_page_with_an_unexplained_stray_is_read_by_ocr_when_none_may_be_left(
    tmp_path, thai_font, fake_ocr, monkeypatch
):
    monkeypatch.setattr(pdf_engine, "MOJIBAKE_MAX_UNMAPPED_SHARE", 0.0)
    # One stray that only occurs once, so it cannot gather MOJIBAKE_MAP_MIN_VOTES votes.
    lines = swap(TRUTH).split("\n")
    lines[6] = lines[6].replace(THO, "ŧ", 1)
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, lines, CLEAN_LINES)

    output = PdfEngine().convert_structured(path, {})

    assert "mis-encoded Thai; it was read by OCR instead" in output.markdown
    assert MOJIBAKE_REPAIRED_NOTE not in output.markdown
    assert output.metrics.ocr_pages_success == 1


def _with_unmapped(text: str, count: int) -> str:
    """*text* with its first *count* tone marks replaced by distinct strays seen once each."""
    pieces = text.split(THO)
    out = [pieces[0]]
    for position, piece in enumerate(pieces[1:]):
        out.append(chr(0x0180 + position) if position < count else THO)
        out.append(piece)
    return "".join(out)


def test_the_unmapped_share_boundary(monkeypatch):
    monkeypatch.setattr(pdf_engine, "MOJIBAKE_MAX_UNMAPPED_SHARE", 0.25)
    total = repair_mojibake(LAYER, {})[1]
    allowed = int(total * 0.25)
    assert allowed >= 2

    def settle(unmapped: int):
        pages = [_with_unmapped(LAYER, unmapped)]
        return PdfEngine._repair_swapped_pages(pages, {0}, {0: TRUTH}, lambda index: "full read"), pages[0]

    (repaired, mapping, ocr_replaced, _), page = settle(allowed)
    assert repaired == {0: allowed} and not ocr_replaced
    assert MOJIBAKE_REPAIRED_NOTE[:-1] in page and f"{allowed} character(s) could not be recovered" in page

    (repaired, _, ocr_replaced, _), page = settle(allowed + 1)
    assert not repaired and ocr_replaced == {0}
    assert page.endswith("full read")


def test_a_repaired_page_flags_exactly_the_lines_that_lost_characters(
    tmp_path, thai_font, fake_ocr
):
    lines = swap(TRUTH).split("\n")
    lines[1] = lines[1].replace(THO, "ƀ", 1)
    lines[5] = lines[5].replace(EK, "Ɓ", 1)
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, lines, CLEAN_LINES)

    output = PdfEngine().convert_structured(path, {})

    assert "were repaired; 2 character(s) could not be recovered (highlighted lines)." in output.markdown
    assert "read by OCR" not in output.markdown
    assert "ƀ" not in output.markdown and "Ɓ" not in output.markdown
    flagged = [line for line in output.markdown.split("\n") if REVIEW_OPEN in line]
    assert len(flagged) == 2
    assert all(line.endswith(f"{REVIEW_OPEN}{REPAIR_LOSS_CONFIDENCE}{REVIEW_CLOSE}") for line in flagged)
    assert SENTENCES[0] in output.markdown  # a line that lost nothing is not flagged


def test_a_page_with_lost_marks_is_still_read_by_ocr_as_before(tmp_path, thai_font, fake_ocr):
    symbols = [line.replace(MAI_EK, "!") for line in SENTENCES] * 3
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, symbols, CLEAN_LINES)

    output = PdfEngine().convert_structured(path, {})

    assert "read by OCR instead" in output.markdown
    assert MOJIBAKE_REPAIRED_NOTE not in output.markdown


def test_tables_and_text_outside_them_on_a_repaired_page_are_repaired_too():
    outcome = _OcrOutcome(repaired={0: 0}, mojibake_map=dict(EXPECTED))
    pages = ["page text"]
    tables = {1: ["| " + swap(SENTENCES[0]) + " |"]}
    outside = {1: swap(SENTENCES[1])}

    warning = PdfEngine._repair_swapped_tables(outcome, pages, tables, outside)

    assert warning is None
    assert tables[1] == ["| " + SENTENCES[0] + " |"]
    assert outside[1] == f"{MOJIBAKE_REPAIRED_NOTE}\n\n{SENTENCES[1]}"
    assert outcome.repaired == {0: 0} and not outcome.replaced


def test_a_table_the_map_cannot_explain_sends_the_page_to_ocr():
    outcome = _OcrOutcome(repaired={0: 0}, mojibake_map=dict(EXPECTED), read_page=lambda index: "ข้อความจาก ocr")
    pages = ["page text"]
    tables = {1: ["| ผูŧใหญ่ |"]}  # a stray the map has no entry for
    outside = {1: "x"}

    PdfEngine._repair_swapped_tables(outcome, pages, tables, outside)

    assert pages[0].endswith("ข้อความจาก ocr") and "read by OCR" in pages[0]
    assert outcome.replaced == {0} and not outcome.repaired


def test_a_table_the_map_cannot_explain_and_no_ocr_text_is_warned_about():
    outcome = _OcrOutcome(repaired={0: 0}, mojibake_map=dict(EXPECTED), read_page=lambda index: "")

    warning = PdfEngine._repair_swapped_tables(outcome, ["t"], {1: ["| ผูŧใหญ่ |"]}, {})

    assert warning and "could not be fully repaired" in warning


# --- through the Converter: clean Markdown, the flagged lines beside it


def _convert_in_process(monkeypatch, path, **options):
    """Converter over the real PdfEngine, run in this process so the OCR fake applies."""
    import doc2md.core.converter as conv_mod

    def run(payload, timeout, cancel=None, on_progress=None):
        return PdfEngine().convert_structured(path, payload["options"])

    monkeypatch.setattr(conv_mod, "_run_in_process", run)
    return Converter(options=options).convert_file(path)


def test_lines_that_lost_characters_become_review_lines_and_the_markdown_stays_clean(
    tmp_path, thai_font, fake_ocr, monkeypatch
):
    lines = swap(TRUTH).split("\n")
    lines[1] = lines[1].replace(THO, "\u0180", 1)
    lines[5] = lines[5].replace(EK, "\u0181", 1)
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, lines, CLEAN_LINES)

    result = _convert_in_process(monkeypatch, path)

    assert result.success, result.error
    assert REVIEW_OPEN not in result.markdown and REVIEW_CLOSE not in result.markdown
    assert "\u0180" not in result.markdown and "\u0181" not in result.markdown
    assert [entry.confidence for entry in result.review_lines] == [REPAIR_LOSS_CONFIDENCE] * 2
    markdown_lines = result.markdown.split("\n")
    for entry in result.review_lines:
        assert markdown_lines[entry.line].strip() == entry.text
        assert "\u0e01" <= entry.text[0] <= "\u0e5b"  # a Thai line, the one that lost a mark
    assert result.quality.ocr_review_lines == 2
    assert "2 character(s) could not be recovered (highlighted lines)." in result.markdown
    # the unflagged lines are intact
    assert SENTENCES[0] in result.markdown
    # and the visible flag, when asked for, is a bare mark on exactly those lines
    flagged = with_inline_flags(result.markdown, result.review_lines).split("\n")
    assert [line for line in flagged if line.endswith(" ⚠")] == [
        markdown_lines[entry.line] + " ⚠" for entry in result.review_lines
    ]


def test_a_flagged_table_row_survives_the_cleaner(monkeypatch, tmp_path):
    from doc2md.core.quality import EngineOutput, QualityMetrics

    import doc2md.core.converter as conv_mod
    from doc2md.core.router import Detection, FileKind

    class Stub:
        name = "stub"
        requires_process_isolation = False

    raw = "\n".join([
        "## Page 1",
        "",
        "> " + MOJIBAKE_REPAIRED_NOTE[2:],
        "",
        "| รายการ | จำนวน |",
        "| --- | --- |",
        review.encode("| ผู้ใหญ่ | 12 |", REPAIR_LOSS_CONFIDENCE),
        "| เด็ก | 7 |",
        "",
        review.encode("ข้อความนอกตาราง", REPAIR_LOSS_CONFIDENCE),
        "",
    ])
    output = EngineOutput(markdown=raw, metrics=QualityMetrics())
    source = tmp_path / "t.txt"
    source.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        conv_mod, "detect", lambda p: Detection(kind=FileKind.TEXT, mime="text/plain", confidence="high")
    )
    monkeypatch.setattr(conv_mod, "get_engine", lambda kind: Stub())
    monkeypatch.setattr(conv_mod, "_run_in_thread", lambda payload, timeout, cancel=None: output)

    result = Converter().convert_file(source)

    assert REVIEW_OPEN not in result.markdown and REVIEW_CLOSE not in result.markdown
    markdown_lines = result.markdown.split("\n")
    assert [markdown_lines[entry.line] for entry in result.review_lines] == [
        "| ผู้ใหญ่ | 12 |",
        "ข้อความนอกตาราง",
    ]
    assert "| เด็ก | 7 |" in markdown_lines  # the table is still one table
    assert with_inline_flags(result.markdown, result.review_lines).count("| ผู้ใหญ่ | 12 ⚠ |") == 1


# --- the reference read is cheap; the full read happens only for a page given up on


@pytest.fixture
def table_reads(monkeypatch):
    """Spy on the table-by-table page read; it returns a marked text so it can be recognised."""
    calls: list[int] = []

    def read(png_path, plumber_pages, index, scale, language):
        calls.append(index)
        return f"FULL READ OF PAGE {index + 1}"

    monkeypatch.setattr(PdfEngine, "_ocr_page_with_tables", staticmethod(read))
    return calls


def test_the_reference_for_a_repaired_page_is_one_plain_read_and_no_table_read(
    tmp_path, thai_font, fake_ocr, table_reads
):
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, swap(TRUTH).split("\n"), CLEAN_LINES)

    output = PdfEngine().convert_structured(path, {})

    assert len(fake_ocr) == 1  # the plain recognize(), once, for the one swapped page
    assert table_reads == []
    assert MOJIBAKE_REPAIRED_NOTE in output.markdown
    assert "FULL READ" not in output.markdown


def test_the_full_read_is_made_only_for_the_page_that_falls_back_to_ocr(
    tmp_path, thai_font, fake_ocr, table_reads, monkeypatch
):
    monkeypatch.setattr(pdf_engine, "MOJIBAKE_MAX_UNMAPPED_SHARE", 0.0)
    unexplained = swap(TRUTH).split("\n")
    unexplained[6] = unexplained[6].replace(THO, "\u0180", 1)  # seen once: cannot be mapped
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, swap(TRUTH).split("\n"), unexplained, CLEAN_LINES)

    output = PdfEngine().convert_structured(path, {})

    assert len(fake_ocr) == 2  # a plain reference read for each swapped page
    assert table_reads == [1]  # the full read, for the second page only (zero-based 1)
    assert "FULL READ OF PAGE 2" in output.markdown
    assert output.markdown.count(MOJIBAKE_REPAIRED_NOTE) == 1
    assert "mis-encoded Thai; it was read by OCR instead" in output.markdown


def test_a_page_with_lost_marks_still_gets_the_full_read(tmp_path, thai_font, fake_ocr, table_reads):
    symbols = [line.replace(MAI_EK, "!") for line in SENTENCES] * 3
    path = _pdf_lines(tmp_path / "m.pdf", thai_font, symbols, CLEAN_LINES)

    PdfEngine().convert_structured(path, {})

    assert table_reads == [0]
    assert fake_ocr == []  # no plain read: that is only for swapped pages


def test_a_failed_full_read_falls_back_to_the_plain_reference(monkeypatch):
    def broken(index):
        raise RuntimeError("tesseract died")

    pages = [_with_unmapped(LAYER, 30)]
    monkeypatch.setattr(pdf_engine, "MOJIBAKE_MAX_UNMAPPED_SHARE", 0.0)

    repaired, _, ocr_replaced, failed = PdfEngine._repair_swapped_pages(pages, {0}, {0: TRUTH}, broken)

    assert ocr_replaced == {0} and not repaired and failed == 0
    assert pages[0].endswith(TRUTH)


def test_no_reference_and_no_full_read_leaves_the_text_layer_and_counts_a_failure(monkeypatch):
    pages = [_with_unmapped(LAYER, 30)]
    monkeypatch.setattr(pdf_engine, "MOJIBAKE_MAX_UNMAPPED_SHARE", 0.0)

    repaired, _, ocr_replaced, failed = PdfEngine._repair_swapped_pages(pages, {0}, {0: ""}, lambda index: "")

    assert not repaired and not ocr_replaced and failed == 1


def test_the_table_fallback_reads_the_page_in_full_then(monkeypatch):
    reads: list[int] = []
    outcome = _OcrOutcome(
        repaired={0: 0},
        mojibake_map=dict(EXPECTED),
        read_page=lambda index: reads.append(index) or "full read",
    )
    pages = ["page text"]

    PdfEngine._repair_swapped_tables(outcome, pages, {1: ["| ผู\u0167ใหญ่ |"]}, {1: "x"})

    assert reads == [0] and pages[0].endswith("full read") and outcome.replaced == {0}


def test_a_table_that_is_fully_repaired_costs_no_full_read():
    outcome = _OcrOutcome(
        repaired={0: 0},
        mojibake_map=dict(EXPECTED),
        read_page=lambda index: pytest.fail("no full read is needed"),
    )

    PdfEngine._repair_swapped_tables(outcome, ["t"], {1: ["| " + swap(SENTENCES[0]) + " |"]}, {})
