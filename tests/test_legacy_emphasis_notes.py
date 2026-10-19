"""Legacy .doc bold/italic and legacy .ppt speaker notes.

Two kinds of input: real files written by Microsoft Word / PowerPoint (small,
made-up text, in ``tests/fixtures``, produced by ``tests/fixtures/make_legacy_fixtures``)
and structures crafted byte by byte by ``tests/legacy_builders`` for the cases
Office will not produce on demand - an incremental save that leaves stale notes
behind, damaged formatting tables, producers that wire notes differently.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from doc2md.core.converter import Converter
from doc2md.engine import doc_engine, ppt_engine
from doc2md.engine.doc_engine import DocEngine, _emphasize
from doc2md.engine.ppt_engine import PptEngine
from tests.legacy_builders import BOLD, CISTD, ITALIC, NO_STYLE, build_doc, build_ppt

pytest.importorskip("olefile")

FIXTURES = Path(__file__).parent / "fixtures"


def _convert_doc(tmp_path, paragraphs, **kwargs):
    path = tmp_path / "t.doc"
    path.write_bytes(build_doc(paragraphs, **kwargs))
    return DocEngine().convert(path, {})


def _convert_ppt(tmp_path, slides, **kwargs):
    path = tmp_path / "t.ppt"
    path.write_bytes(build_ppt(slides, **kwargs))
    return PptEngine().convert(path, {})


def _runs(text, *marks):
    """chp entries from ``(needle, ops)`` pairs, located in *text*."""
    return [(text.index(needle), len(needle), ops) for needle, ops in marks]


B, I, BI = {BOLD: 1}, {ITALIC: 1}, {BOLD: 1, ITALIC: 1}


# ============================================================ .doc: real Word files


def test_real_word_file_bold_italic_thai_tables_and_styles():
    output = DocEngine().convert(FIXTURES / "legacy_bold_italic.doc", {})

    assert "ข้อความปกติ **ตัวหนา** และ *ตัวเอียง* และ ***ตัวหนาเอียง*** จบประโยค" in output
    assert "Plain, **bold words here**, *italic words here* and ***both together*** then plain." in output
    assert "\n**ทั้งย่อหน้านี้เป็นตัวหนา**\n" in output
    # a run that ends mid-sentence in Thai, with no space to hide the join
    assert "บางส่วนของคำ**ไทยที่ถูกเน้น**ต่อท้ายทันทีโดยไม่เว้นวรรค" in output
    # Strong / Emphasis character styles, resolved through the style sheet
    assert "Style based: **strong style** and *emphasis style*" in output
    # a bold paragraph style with a run switched off: 0x81 inverts the style
    assert "**ย่อหน้าสไตล์หนา** ส่วนที่ปิดตัวหนา **แล้วหนาต่อ**" in output
    assert "รายการ **ตัวหนา** ในลิสต์" in output
    # the heading is bold already, the table header row too
    assert "# รายงานทดสอบ Test Report\n" in output
    assert "| ชื่อ | จำนวน |" in output
    assert "| น้ำ | **สิบ** |" in output
    assert "| *ข้าว* | 5 |" in output
    assert "หลังตาราง ข้อความปกติ\n" in output


def test_real_word_file_with_8_bit_text_pieces():
    output = DocEngine().convert(FIXTURES / "legacy_latin_emphasis.doc", {})

    assert "Plain start, **bold words** and *italic* then ***both***." in output
    assert "| **one** | two |" in output


def test_the_legacy_doc_note_no_longer_says_emphasis_is_lost():
    output = DocEngine().convert(FIXTURES / "legacy_latin_emphasis.doc", {})

    assert "bold/italic were not" not in output
    assert "bold/italic were recovered" in output
    assert "headers/footers, footnotes and text boxes were not" in output


def test_an_rtf_saved_as_doc_does_not_claim_emphasis_it_cannot_recover(tmp_path):
    path = tmp_path / "r.doc"
    path.write_bytes(b"{\\rtf1\\ansi {\\b bold} plain\\par}")

    output = DocEngine().convert(path, {})

    assert "bold/italic, headers/footers" in output and "were not" in output
    assert "bold/italic were recovered" not in output


def test_real_word_file_through_the_converter():
    result = Converter(timeout=30).convert_file(FIXTURES / "legacy_bold_italic.doc")

    assert result.success, result.error
    assert "**ตัวหนา**" in result.markdown


# =========================================================== .doc: crafted structures


def test_bold_italic_and_both_around_thai_words(tmp_path):
    text = "ปกติ ตัวหนา และ ตัวเอียง และ หนาเอียง จบ"
    output = _convert_doc(
        tmp_path,
        [(text, "para", {"chp": _runs(text, ("ตัวหนา", B), ("ตัวเอียง", I), ("หนาเอียง", BI))})],
    )

    assert "ปกติ **ตัวหนา** และ *ตัวเอียง* และ ***หนาเอียง*** จบ" in output


def test_8_bit_text_pieces_carry_formatting_too(tmp_path):
    text = "plain bold plain"
    output = _convert_doc(tmp_path, [(text, "para", {"chp": _runs(text, ("bold", B))})], compressed=True)

    assert "plain **bold** plain" in output


def test_surrounding_spaces_stay_outside_the_markers(tmp_path):
    text = "a  bold  b"
    output = _convert_doc(tmp_path, [(text, "para", {"chp": [(1, 8, B)]})])  # "  bold  " is bold

    assert "a  **bold**  b" in output


def test_a_plain_space_between_two_bold_runs_joins_them(tmp_path):
    text = "x bold word y"
    output = _convert_doc(
        tmp_path, [(text, "para", {"chp": _runs(text, ("bold", B), ("word", B))})]
    )

    assert "x **bold word** y" in output


def test_a_bold_space_alone_is_not_marked(tmp_path):
    text = "one two"
    output = _convert_doc(tmp_path, [(text, "para", {"chp": [(3, 1, B)]})])

    assert "one two" in output
    assert "*" not in output.split("\n", 4)[-1]


def test_overlapping_bold_and_italic_close_and_reopen_around_the_space(tmp_path):
    text = "AA BB CC"
    # "AA BB" is bold, "BB CC" is italic: only "BB" is both
    output = _convert_doc(tmp_path, [(text, "para", {"chp": [(0, 3, B), (3, 2, BI), (5, 3, I)]})])

    assert "**AA *BB*** *CC*" in output


def test_headings_and_table_header_cells_get_no_markers_but_body_cells_do(tmp_path):
    head = "Heading text"
    cells = [
        ("Name", "cell", {"chp": [(0, 4, B)]}), ("Qty", "cell", {"chp": [(0, 3, B)]}), ("", "rowend", {}),
        ("tea", "cell", {"chp": [(0, 3, B)]}), ("two", "cell", {}), ("", "rowend", {}),
    ]
    output = _convert_doc(
        tmp_path, [(head, "para", {"istd": 1, "chp": [(0, 7, B)]}), *cells]
    )

    assert "# Heading text\n" in output
    assert "| Name | Qty |" in output
    assert "| **tea** | two |" in output


def test_markers_never_cross_a_cell_separator(tmp_path):
    cells = [
        ("A", "cell", {}), ("B", "cell", {}), ("", "rowend", {}),
        ("bold", "cell", {"chp": [(0, 4, B)]}), ("bold", "cell", {"chp": [(0, 4, B)]}), ("", "rowend", {}),
    ]
    output = _convert_doc(tmp_path, cells)

    assert "| **bold** | **bold** |" in output


def test_list_items_keep_their_emphasis(tmp_path):
    text = "item bold"
    output = _convert_doc(
        tmp_path, [(text, "para", {"ilfo": 1, "chp": _runs(text, ("bold", B))})]
    )

    assert "- item **bold**" in output


def test_a_paragraph_without_formatting_comes_out_exactly_as_before(tmp_path):
    output = _convert_doc(tmp_path, [("nothing special", "para", {}), ("second", "para", {})])

    assert "*" not in output.split("\n", 4)[-1]
    assert "nothing special\n\nsecond" in output


# --- the style sheet


# Paragraph styles start above 9 so they are not read as Heading 1..9.
PARA_BOLD, PARA_INHERIT, PARA_INVERT, PARA_ITALIC, CHAR_STRONG, CHAR_BASED = 11, 12, 13, 14, 15, 16
STYLES = {
    0: (1, NO_STYLE, {}),
    PARA_BOLD: (1, 0, {BOLD: 1}),
    PARA_INHERIT: (1, PARA_BOLD, {}),
    PARA_INVERT: (1, PARA_BOLD, {BOLD: 0x81}),
    PARA_ITALIC: (1, 0, {ITALIC: 1}),
    CHAR_STRONG: (2, NO_STYLE, {BOLD: 0x81}),
    CHAR_BASED: (2, CHAR_STRONG, {ITALIC: 0x81}),
}


def test_a_bold_paragraph_style_makes_the_whole_paragraph_bold(tmp_path):
    output = _convert_doc(tmp_path, [("styled text", "para", {"istd": PARA_BOLD, "chp": [(0, 1, {})]})], styles=STYLES)

    assert "**styled text**" in output


def test_a_style_based_on_a_bold_style_inherits_it(tmp_path):
    output = _convert_doc(tmp_path, [("styled text", "para", {"istd": PARA_INHERIT, "chp": [(0, 1, {})]})], styles=STYLES)

    assert "**styled text**" in output


def test_a_toggle_in_a_style_inverts_its_parent(tmp_path):
    output = _convert_doc(tmp_path, [("styled text", "para", {"istd": PARA_INVERT, "chp": [(0, 1, {})]})], styles=STYLES)

    assert "styled text" in output
    assert "*" not in output.split("\n", 4)[-1]


def test_direct_toggles_0x80_keeps_and_0x81_inverts_the_style(tmp_path):
    text = "keep flip zero"
    runs = _runs(text, ("keep", {BOLD: 0x80}), ("flip", {BOLD: 0x81}), ("zero", {BOLD: 0}))

    output = _convert_doc(tmp_path, [(text, "para", {"istd": PARA_BOLD, "chp": runs})], styles=STYLES)

    # bold style: 0x80 stays bold, 0x81 and 0 switch it off
    assert "**keep** flip zero" in output


def test_a_character_style_applies_over_the_paragraph(tmp_path):
    text = "plain strong based plain"
    runs = _runs(text, ("strong", {CISTD: CHAR_STRONG}), ("based", {CISTD: CHAR_BASED}))

    output = _convert_doc(tmp_path, [(text, "para", {"chp": runs})], styles=STYLES)

    # "based" inherits bold from Strong and adds italic; the space between the
    # two bold runs is bridged, so one bold span holds an italic one
    assert "plain **strong *based*** plain" in output


def test_a_character_style_based_on_another_inherits_its_bold(tmp_path):
    text = "plain based plain"
    runs = _runs(text, ("based", {CISTD: CHAR_BASED}))

    output = _convert_doc(tmp_path, [(text, "para", {"chp": runs})], styles=STYLES)

    assert "plain ***based*** plain" in output


def test_a_character_style_toggle_is_relative_to_the_paragraph_style(tmp_path):
    text = "all bold"
    # "Strong" flips bold; on a bold paragraph that turns it off for the run
    runs = _runs(text, ("bold", {CISTD: CHAR_STRONG}))

    output = _convert_doc(tmp_path, [(text, "para", {"istd": PARA_BOLD, "chp": runs})], styles=STYLES)

    assert "**all** bold" in output


def test_a_cyclic_style_chain_does_not_hang(tmp_path):
    cyclic = {0: (1, NO_STYLE, {}), 11: (1, 12, {BOLD: 0x81}), 12: (1, 11, {BOLD: 0x81})}

    output = _convert_doc(tmp_path, [("loop", "para", {"istd": 11, "chp": [(0, 1, {})]})], styles=cyclic)

    assert "loop" in output


# --- Thai clusters


@pytest.mark.parametrize(
    ("text", "span", "expected"),
    [
        # a vowel sign / tone mark stays with its consonant
        ("ที่นี่", (0, 1), "**ที่**นี่"),
        # SARA AM stays with the consonant before it
        ("กำลังไป", (0, 1), "**กำ**ลังไป"),
        # a following vowel stays with its consonant
        ("เกาะ", (0, 2), "**เกาะ**"),
        # a leading vowel is not bold alone: it follows the consonant it precedes
        ("เกาะ", (0, 1), "เกาะ"),
        # the repetition mark stays with the word it repeats
        ("ดีๆ", (0, 2), "**ดีๆ**"),
    ],
)
def test_no_marker_splits_a_thai_syllable(tmp_path, text, span, expected):
    output = _convert_doc(tmp_path, [(text, "para", {"chp": [(span[0], span[1], B)]})])

    assert expected in output


def test_emphasis_in_the_middle_of_thai_text_keeps_whole_words(tmp_path):
    text = "การทดสอบระบบ"
    output = _convert_doc(tmp_path, [(text, "para", {"chp": _runs(text, ("ทดสอบ", B))})])

    assert "การ**ทดสอบ**ระบบ" in output


# --- nothing may make a conversion fail


@pytest.mark.parametrize("damage", ["fkp", "plc"])
def test_damaged_character_property_tables_fall_back_to_plain_text(tmp_path, damage):
    text = "plain bold plain"
    output = _convert_doc(
        tmp_path, [(text, "para", {"chp": _runs(text, ("bold", B))}), ("second paragraph", "para", {})], damage=damage
    )

    assert "plain bold plain" in output
    assert "second paragraph" in output
    assert "**" not in output


def test_a_damaged_style_sheet_keeps_direct_formatting(tmp_path):
    text = "plain bold plain"
    output = _convert_doc(
        tmp_path,
        [(text, "para", {"chp": _runs(text, ("bold", B))})],
        styles=STYLES,
        damage="stsh",
    )

    assert "plain **bold** plain" in output


def test_an_fkp_page_beyond_the_end_of_the_file_is_ignored(tmp_path):
    text = "plain bold plain"
    output = _convert_doc(tmp_path, [(text, "para", {"chp": _runs(text, ("bold", B))})], damage="plc")

    assert "plain bold plain" in output


def test_an_exception_while_marking_up_a_paragraph_yields_plain_text(tmp_path, monkeypatch):
    def boom(*_args):
        raise RuntimeError("formatting exploded")

    monkeypatch.setattr(doc_engine, "_emphasize", boom)
    text = "plain bold plain"

    output = _convert_doc(tmp_path, [(text, "para", {"chp": _runs(text, ("bold", B))})])

    assert "plain bold plain" in output
    assert "**" not in output


def test_a_failure_reading_formatting_never_fails_the_document(tmp_path, monkeypatch):
    def boom(self):
        raise RuntimeError("no formatting for you")

    monkeypatch.setattr(doc_engine._WordBinary, "_read_chpx", boom)
    text = "plain bold plain"

    output = _convert_doc(tmp_path, [(text, "para", {"chp": _runs(text, ("bold", B))})])

    assert "plain bold plain" in output


# --- the marker writer on its own


def _chars(text, bold=(), italic=()):
    chars = list(text)
    flags = [(1 if i in bold else 0) | (2 if i in italic else 0) for i in range(len(chars))]
    return chars, flags


def test_emphasize_nests_italic_inside_bold_and_back():
    chars, flags = _chars("AB CD EF", bold=range(0, 8), italic=range(3, 5))

    assert _emphasize(chars, flags) == "**AB *CD* EF**"


def test_emphasize_keeps_the_text_and_balances_the_markers_when_runs_overlap_without_a_gap():
    chars, flags = _chars("aXbc", bold=(1, 2), italic=(2, 3))

    result = _emphasize(chars, flags)

    assert result.replace("*", "") == "aXbc"
    assert result.count("*") % 2 == 0


def test_emphasize_reopens_after_the_space_not_before_it():
    chars, flags = _chars("AA BB CC", bold=range(0, 5), italic=range(3, 8))

    assert _emphasize(chars, flags) == "**AA *BB*** *CC*"


def test_emphasize_never_wraps_whitespace_or_a_line_break():
    chars, flags = _chars("one\ntwo three", bold=range(0, 13))

    assert _emphasize(chars, flags) == "**one**\n**two three**"


def test_emphasize_leaves_unmarked_text_alone():
    chars, flags = _chars("plain text")

    assert _emphasize(chars, flags) == "plain text"


# ======================================================= .ppt: real PowerPoint file


def test_real_powerpoint_file_notes_under_the_right_slides():
    output = PptEngine().convert(FIXTURES / "legacy_notes.ppt", {})

    slide1 = output[output.index("## Slide 1"):output.index("## Slide 2")]
    slide2 = output[output.index("## Slide 2"):output.index("## Slide 3")]
    slide3 = output[output.index("## Slide 3"):]
    assert "> Speaker notes: บันทึกผู้พูดสำหรับสไลด์แรก บรรทัดที่สองของบันทึก\n" in slide1
    assert "Speaker notes" not in slide2
    assert "> Speaker notes: Notes for slide three, with English too.\n" in slide3
    # nothing from the notes page leaks in: the slide-number "*" or its text boxes
    assert "\n- *" not in output
    assert "stray" not in output


def test_real_powerpoint_file_keeps_slide_text_and_updates_the_note():
    output = PptEngine().convert(FIXTURES / "legacy_notes.ppt", {})

    assert "## Slide 1: สไลด์แรก" in output
    assert "- ข้อหนึ่ง\n- ข้อสอง\n\n> Speaker notes:" in output
    assert "slide text and speaker notes were recovered" in output
    assert "speaker notes, table layout" not in output


def test_real_powerpoint_file_through_the_converter():
    result = Converter(timeout=30).convert_file(FIXTURES / "legacy_notes.ppt")

    assert result.success, result.error
    assert "> Speaker notes: Notes for slide three" in result.markdown


# ====================================================== .ppt: crafted structures


THREE = [
    ("หนึ่ง", ["ข้อ ก"], [], ["note one", "line  two"]),
    ("สอง", [], [], []),
    ("สาม", ["ข้อ ข"], [], ["บันทึกสาม"]),
]


@pytest.mark.parametrize("mode", ["id", "persist", "no_atom", "list_text"])
def test_notes_resolve_however_the_producer_wired_them(tmp_path, mode):
    output = _convert_ppt(tmp_path, THREE, notes_mode=mode)

    slide1 = output[output.index("## Slide 1"):output.index("## Slide 2")]
    slide2 = output[output.index("## Slide 2"):output.index("## Slide 3")]
    slide3 = output[output.index("## Slide 3"):]
    assert "> Speaker notes: note one line two\n" in slide1
    assert "Speaker notes" not in slide2
    assert "> Speaker notes: บันทึกสาม\n" in slide3


def test_the_notes_line_has_the_same_shape_as_the_pptx_engine(tmp_path):
    pptx = pytest.importorskip("pptx")
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "T"
    slide.notes_slide.notes_text_frame.text = "note one\nline  two"
    path = tmp_path / "n.pptx"
    deck.save(path)
    from doc2md.engine.pptx_engine import PptxEngine

    pptx_line = next(
        line for line in PptxEngine().convert(path, {}).splitlines() if line.startswith("> Speaker notes:")
    )
    ppt_line = next(
        line
        for line in _convert_ppt(tmp_path, [("T", [], [], ["note one", "line  two"])]).splitlines()
        if line.startswith("> Speaker notes:")
    )

    assert ppt_line == pptx_line


def test_notes_come_after_the_slide_body_and_before_the_next_heading(tmp_path):
    output = _convert_ppt(tmp_path, THREE)

    assert "- ข้อ ก\n\n> Speaker notes: note one line two\n\n## Slide 2" in output


def test_a_slide_without_notes_atom_data_is_unchanged_from_before(tmp_path):
    output = _convert_ppt(tmp_path, [("Only", ["point"], ["box"])])

    assert "Speaker notes" not in output
    assert "## Slide 1: Only\n\n- point\n- box\n" in output


def test_stale_notes_from_an_older_save_are_not_emitted(tmp_path):
    slides = [("One", [], ["box one"], ["first note v1"]), ("Two", [], ["box two"], ["second note v1"])]

    output = _convert_ppt(
        tmp_path,
        slides,
        edits=[(1, ["box two v2"], ["second note v2"]), (1, ["box two v3"], ["second note v3"])],
    )

    assert "> Speaker notes: second note v3" in output
    assert "second note v1" not in output
    assert "second note v2" not in output
    assert "box two v3" in output
    assert "box two v2" not in output
    assert "> Speaker notes: first note v1" in output  # slide 1 was never edited


def test_a_notes_only_save_replaces_the_note_but_keeps_the_slide(tmp_path):
    slides = [("One", [], ["box one"], ["old note"])]

    output = _convert_ppt(tmp_path, slides, edits=[(0, None, ["new note"])])

    assert "> Speaker notes: new note" in output
    assert "old note" not in output
    assert "box one" in output


def test_notes_deleted_in_a_later_save_do_not_come_back(tmp_path):
    slides = [("One", [], ["box one"], ["doomed note"]), ("Two", [], [], ["kept note"])]

    output = _convert_ppt(tmp_path, slides, edits=[(0, ["box one"], [])])

    assert "doomed note" not in output
    assert "> Speaker notes: kept note" in output


def test_an_incremental_save_of_a_deck_without_notes_still_works(tmp_path):
    output = _convert_ppt(
        tmp_path,
        [("One", [], ["old text"]), ("Two", [], ["also old"])],
        edit_slide=(1, ["replacement text"]),
    )

    assert "replacement text" in output
    assert "also old" not in output
    assert "Speaker notes" not in output


def test_the_legacy_ppt_note_no_longer_says_notes_are_lost(tmp_path):
    output = _convert_ppt(tmp_path, THREE)

    assert "speaker notes were not" not in output
    assert "slide text and speaker notes were recovered" in output
    assert "table layout, bullet levels and pictures were not" in output


def test_a_damaged_notes_page_never_fails_the_slide(tmp_path, monkeypatch):
    def boom(*_args):
        raise ValueError("notes page unreadable")

    monkeypatch.setattr(ppt_engine, "_notes_page_text", boom)

    output = _convert_ppt(tmp_path, THREE)

    assert "## Slide 1: หนึ่ง" in output
    assert "## Slide 3: สาม" in output
    assert "Speaker notes" not in output


def test_a_notes_ref_pointing_nowhere_is_no_notes(tmp_path):
    import olefile

    path = tmp_path / "x.ppt"
    path.write_bytes(build_ppt([("One", [], [], ["note"])]))
    ole = olefile.OleFileIO(str(path))
    try:
        stream = bytearray(ole.openstream("PowerPoint Document").read())
        current_user = ole.openstream("Current User").read()
    finally:
        ole.close()
    header = struct.pack("<HHI", 0, 0x03EF, 24)  # the SlideAtom record header
    at = bytes(stream).index(header)
    stream[at + 8 + 16:at + 8 + 20] = (9999).to_bytes(4, "little")  # notesIdRef nobody lists

    slides = ppt_engine.slides_from_stream(bytes(stream), current_user)

    assert slides
    assert not any("Speaker notes" in line for line in slides[0])
