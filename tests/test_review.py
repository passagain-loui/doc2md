"""doc2md.core.review: OCR review flags carried beside the Markdown, not in it."""

from __future__ import annotations

import pytest

from doc2md.core import cleaner, review
from doc2md.core.review import (
    REVIEW_CLOSE,
    REVIEW_OPEN,
    VISIBLE_MARK,
    ReviewLine,
    count_marked,
    encode,
    extract,
    with_inline_flags,
)


def _no_sentinels(text: str) -> bool:
    return REVIEW_OPEN not in text and REVIEW_CLOSE not in text


# ------------------------------------------------------------------ encode


def test_sentinels_are_private_use_characters_never_visible_text():
    for char in (REVIEW_OPEN, REVIEW_CLOSE):
        assert len(char) == 1
        assert 0xE000 <= ord(char) <= 0xF8FF
    assert REVIEW_OPEN != REVIEW_CLOSE
    assert VISIBLE_MARK == "⚠"


def test_encode_appends_marker_and_rounds_confidence():
    assert encode("shaky line", 55.4) == f"shaky line{REVIEW_OPEN}55{REVIEW_CLOSE}"
    assert encode("shaky line", 55.6) == f"shaky line{REVIEW_OPEN}56{REVIEW_CLOSE}"


def test_encode_drops_trailing_whitespace_before_the_marker():
    assert encode("shaky line   \t", 40) == f"shaky line{REVIEW_OPEN}40{REVIEW_CLOSE}"


def test_encode_has_no_visible_flag():
    assert VISIBLE_MARK not in encode("x", 50)
    assert "%" not in encode("x", 50)


def test_count_marked_counts_lines_not_words():
    text = "\n".join([encode("a", 10), "plain ⚠ 50% text", encode("b", 20), ""])
    assert count_marked(text) == 2
    assert count_marked("nothing here") == 0
    assert count_marked("") == 0


# ------------------------------------------------------------------ extract


def test_round_trip_single_line():
    clean, flagged = extract(encode("shaky line", 52))

    assert clean == "shaky line"
    assert flagged == [ReviewLine(0, 52, "shaky line")]


def test_round_trip_keeps_the_clean_text_exactly():
    raw = "# Title\n\ngood line\n" + encode("shaky line", 61) + "\nlast line\n"

    clean, flagged = extract(raw)

    assert clean == "# Title\n\ngood line\nshaky line\nlast line\n"
    assert _no_sentinels(clean)
    assert VISIBLE_MARK not in clean
    assert flagged == [ReviewLine(3, 61, "shaky line")]
    # the index addresses the clean text split the way a text editor numbers it
    assert clean.split("\n")[flagged[0].line] == "shaky line"


def test_line_indices_survive_blank_lines_and_multiple_flags():
    raw = "\n".join([
        "## Page 1 (OCR)",
        "",
        encode("first shaky", 45),
        "",
        "",
        "fine",
        encode("second shaky", 69),
        encode("third shaky", 12),
        "",
        "tail",
    ])

    clean, flagged = extract(raw)
    lines = clean.split("\n")

    assert [(entry.line, entry.confidence) for entry in flagged] == [(2, 45), (6, 69), (7, 12)]
    for entry in flagged:
        assert lines[entry.line] == entry.text
    assert len(lines) == len(raw.split("\n"))
    assert _no_sentinels(clean)


def test_thai_text_round_trips():
    raw = "ข้อความชัดเจน\n" + encode("ข้อความไม่ชัด", 52) + "\nบรรทัด ๓"

    clean, flagged = extract(raw)

    assert clean == "ข้อความชัดเจน\nข้อความไม่ชัด\nบรรทัด ๓"
    assert flagged == [ReviewLine(1, 52, "ข้อความไม่ชัด")]


def test_flag_entry_text_is_stripped_of_surrounding_space():
    clean, flagged = extract(f"  indented{REVIEW_OPEN}50{REVIEW_CLOSE}")

    assert flagged[0].text == "indented"
    assert clean == "  indented"


def test_text_without_markers_comes_back_unchanged():
    text = "# Plain\n\nNothing was flagged here ⚠ 58% (a literal warning sign).\n"

    clean, flagged = extract(text)

    assert clean is text
    assert flagged == []


def test_empty_text():
    assert extract("") == ("", [])


def test_stray_sentinels_are_removed_without_inventing_a_flag():
    raw = f"alpha{REVIEW_OPEN}beta\ngamma{REVIEW_CLOSE}delta\n{REVIEW_OPEN}{REVIEW_CLOSE}epsilon"

    clean, flagged = extract(raw)

    assert clean == "alphabeta\ngammadelta\nepsilon"
    assert flagged == []
    assert _no_sentinels(clean)


def test_stray_sentinel_beside_a_real_marker():
    raw = f"stray{REVIEW_CLOSE} text{REVIEW_OPEN}77{REVIEW_CLOSE}"

    clean, flagged = extract(raw)

    assert clean == "stray text"
    assert flagged == [ReviewLine(0, 77, "stray text")]


def test_marker_with_non_numeric_body_is_just_stray():
    clean, flagged = extract(f"line{REVIEW_OPEN}abc{REVIEW_CLOSE}")

    assert flagged == []
    assert clean == "lineabc"


def test_extract_never_leaves_sentinels_whatever_it_is_given():
    nasty = REVIEW_OPEN * 3 + "12" + REVIEW_CLOSE * 2 + "\n" + encode("ok", 5) + REVIEW_OPEN
    clean, _flagged = extract(nasty)

    assert _no_sentinels(clean)


# ------------------------------------------------------------ inline flags


def test_with_inline_flags_appends_visible_mark_on_the_right_lines():
    clean, flagged = extract("good\n" + encode("shaky", 58) + "\nalso good\n" + encode("bad", 31))

    flagged_text = with_inline_flags(clean, flagged)

    assert flagged_text == f"good\nshaky {VISIBLE_MARK}58%\nalso good\nbad {VISIBLE_MARK}31%"
    assert _no_sentinels(flagged_text)


def test_with_inline_flags_with_no_review_lines_is_a_no_op():
    text = "a\nb\n"

    assert with_inline_flags(text, []) is text


def test_with_inline_flags_ignores_out_of_range_entries():
    text = "one\ntwo"
    entries = [ReviewLine(-1, 10, "x"), ReviewLine(2, 20, "y"), ReviewLine(99, 30, "z"), ReviewLine(1, 40, "two")]

    assert with_inline_flags(text, entries) == f"one\ntwo {VISIBLE_MARK}40%"


def test_with_inline_flags_does_not_double_space_a_line_with_trailing_whitespace():
    assert with_inline_flags("line   ", [ReviewLine(0, 50, "line")]) == f"line {VISIBLE_MARK}50%"


def test_with_inline_flags_puts_the_flag_inside_the_last_cell_of_a_table_row():
    text = "| a | b |\n|---|---|\n| x | shaky |"

    flagged = with_inline_flags(text, [ReviewLine(2, 58, "| x | shaky |")])

    assert flagged == f"| a | b |\n|---|---|\n| x | shaky {VISIBLE_MARK}58% |"


def test_with_inline_flags_table_row_keeps_indent_and_handles_trailing_space():
    flagged = with_inline_flags("  | a | b |   ", [ReviewLine(0, 40, "x")])

    assert flagged == f"  | a | b {VISIBLE_MARK}40% |"


def test_with_inline_flags_line_only_ending_with_a_pipe_is_not_a_table_row():
    flagged = with_inline_flags("cmd a | b |", [ReviewLine(0, 50, "x")])

    assert flagged == f"cmd a | b | {VISIBLE_MARK}50%"


def test_with_inline_flags_line_only_starting_with_a_pipe_keeps_the_suffix():
    assert with_inline_flags("| a | b", [ReviewLine(0, 50, "x")]) == f"| a | b {VISIBLE_MARK}50%"


def test_with_inline_flags_lone_pipe_is_not_a_table_row():
    assert with_inline_flags("|", [ReviewLine(0, 50, "x")]) == f"| {VISIBLE_MARK}50%"


def test_with_inline_flags_plain_line_keeps_the_suffix():
    assert with_inline_flags("plain text", [ReviewLine(0, 61, "x")]) == f"plain text {VISIBLE_MARK}61%"


def test_with_inline_flags_does_not_mutate_the_entries():
    entry = ReviewLine(0, 50, "line")
    with_inline_flags("line", [entry])

    assert entry == ReviewLine(0, 50, "line")


def test_review_line_is_frozen():
    with pytest.raises(Exception):
        ReviewLine(0, 50, "x").line = 3  # type: ignore[misc]


# ----------------------------------------------------------------- cleaner


def test_cleaner_optimize_preserves_markers():
    raw = "## Page 1 (OCR)\n\ngood   line\n" + encode("shaky   line", 55) + "\n\n\n\nlast\n"

    optimized = cleaner.optimize(raw)

    assert count_marked(optimized) == 1
    clean, flagged = extract(optimized)
    assert _no_sentinels(clean)
    assert len(flagged) == 1
    assert flagged[0].confidence == 55
    assert clean.split("\n")[flagged[0].line] == "shaky line"


def test_cleaner_optimize_preserves_markers_in_thai_text():
    optimized = cleaner.optimize("หัวข้อ\n" + encode("ข้อความไม่ชัด", 48) + "\n")

    clean, flagged = extract(optimized)

    assert [(f.confidence, f.text) for f in flagged] == [(48, "ข้อความไม่ชัด")]
    assert clean.split("\n")[flagged[0].line] == "ข้อความไม่ชัด"


def test_flag_indices_refer_to_the_text_after_the_cleaner_not_before():
    # the cleaner collapses blank-line runs, so indices must be taken after it
    raw = "a\n\n\n\n\n" + encode("shaky", 50)

    clean, flagged = extract(cleaner.optimize(raw))

    assert clean.split("\n")[flagged[0].line] == "shaky"
    assert flagged[0].line == 2
