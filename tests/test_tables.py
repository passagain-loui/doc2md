"""Unit tests for the shared Markdown table builder.

These pin the three ways a table used to break: a cell that terminates its own
column, rows with mismatched widths, and cleanup passes that treat table rows
as prose.
"""

from __future__ import annotations

import re

import pytest

from doc2md.core import cleaner
from doc2md.core.tables import (
    display_width,
    escape_cell,
    is_table_line,
    normalize_rows,
    render_table,
)


def rows_of(markdown: str) -> list[list[str]]:
    """Split rendered Markdown back into a grid of cells.

    Splits on *unescaped* pipes only - the same rule a Markdown renderer
    applies - so an escaped ``\\|`` inside a cell stays part of that cell.
    """
    return [
        [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip().strip("|"))]
        for line in markdown.splitlines()
    ]


# --- escaping ----------------------------------------------------------------


def test_pipe_inside_a_cell_is_escaped_not_column_breaking():
    markdown = render_table([["a|b", "c"], ["d", "e"]])

    grid = rows_of(markdown)
    assert all(len(row) == 2 for row in grid), markdown
    assert grid[0][0] == r"a\|b"


def test_multiline_cell_becomes_one_row_with_line_breaks():
    markdown = render_table([["head", "x"], ["line one\nline two", "y"]])

    assert len(markdown.splitlines()) == 3
    assert "line one<br>line two" in markdown


def test_backslash_is_escaped_before_the_pipe_escape():
    """``a\\`` must not turn the escape we add into a literal backslash-pipe."""
    assert escape_cell("a\\") == "a\\\\"
    assert escape_cell("a\\|b") == r"a\\\|b"


def test_none_and_booleans_render_predictably():
    assert escape_cell(None) == ""
    assert escape_cell(True) == "true"
    assert escape_cell(False) == "false"
    assert escape_cell(0) == "0"


def test_control_characters_are_removed():
    assert escape_cell("a\x00b\x07c") == "abc"


def test_thai_text_is_untouched():
    text = "เครื่องวัดความดันโลหิต"
    assert escape_cell(text) == text


# --- normalization -----------------------------------------------------------


def test_ragged_rows_are_padded_to_one_width():
    grid = normalize_rows([["a"], ["b", "c", "d"], ["e", "f"]])

    assert [len(row) for row in grid] == [3, 3, 3]
    assert grid[0] == ["a", "", ""]


def test_entirely_empty_rows_are_dropped():
    assert normalize_rows([["", ""], [None, None]]) == []


def test_render_returns_empty_string_for_an_empty_grid():
    assert render_table([]) == ""
    assert render_table([[None, ""]]) == ""


def test_every_rendered_row_has_the_same_pipe_count():
    markdown = render_table(
        [
            ["รายการ", "จำนวน", "ราคา"],
            ["เครื่องวัดความดันโลหิต", "12"],
            ["ชุดตรวจ", "300", "9,900", "เพิ่ม"],
        ]
    )

    counts = {line.count("|") for line in markdown.splitlines()}
    assert len(counts) == 1


def test_duplicate_data_rows_are_both_kept():
    markdown = render_table([["h1", "h2"], ["0", "0"], ["0", "0"]])

    assert markdown.count("| 0 | 0 |") == 2


# --- headers -----------------------------------------------------------------


def test_empty_headers_stay_empty_by_default():
    markdown = render_table([["h1", ""], ["a", "b"]])

    assert markdown.splitlines()[0] == "| h1 |  |"


def test_empty_headers_can_be_named_for_spreadsheets():
    markdown = render_table([["h1", ""], ["a", "b"]], name_empty_headers=True)

    assert markdown.splitlines()[0] == "| h1 | col2 |"


def test_header_false_generates_a_synthetic_header():
    markdown = render_table([["a", "b"], ["c", "d"]], header=False)

    lines = markdown.splitlines()
    assert lines[0] == "| col1 | col2 |"
    assert lines[2] == "| a | b |"
    assert lines[3] == "| c | d |"


def test_alignments_are_rendered_in_the_separator():
    markdown = render_table(
        [["a", "b", "c"], ["1", "2", "3"]],
        alignments=["left", "right", "center"],
    )

    assert markdown.splitlines()[1] == "| :--- | ---: | :---: |"


# --- width helper ------------------------------------------------------------


def test_thai_combining_marks_do_not_add_display_width():
    """``กิ`` is two codepoints but one visual cell.

    Padding by ``len()`` is why Thai tables looked crooked; this is the
    measurement that would be correct if padding were ever reintroduced.
    """
    assert len("กิ") == 2
    assert display_width("กิ") == 1


def test_cjk_characters_count_double():
    assert display_width("日本") == 4


# --- interaction with the output sanitizer -----------------------------------


@pytest.mark.parametrize(
    "line, expected",
    [
        ("| a | b |", True),
        ("|---|---|", True),
        ("  | a |  ", True),
        ("not a table", False),
        ("| unterminated", False),
    ],
)
def test_is_table_line(line, expected):
    assert is_table_line(line) is expected


def test_sanitizer_keeps_repeated_table_rows():
    """The prose pass drops consecutive duplicate lines; tables must not."""
    document = "# T\n\n| a | b |\n| --- | --- |\n| 0 | 0 |\n| 0 | 0 |\n"

    assert cleaner.optimize(document).count("| 0 | 0 |") == 2


def test_sanitizer_keeps_braces_inside_a_table_cell():
    """The CSS-residue regex eats ``{...}``; a cell may legitimately contain it."""
    document = "| key | value |\n| --- | --- |\n| a | {ok} |\n"

    assert "{ok}" in cleaner.optimize(document)


def test_sanitizer_still_collapses_duplicate_prose_lines():
    document = "same line\nsame line\nother\n"

    assert cleaner.optimize(document).count("same line") == 1


# --- CSS residue vs legitimate braces ----------------------------------------


@pytest.mark.parametrize(
    "prose",
    [
        "a cell containing `{...}`",
        'config {"a": 1, "b": 2}',
        "the set {1,2,3}",
        "ใช้ตัวแปร {ชื่อผู้ป่วย} ในเทมเพลต",
        "format string {name} stays",
        "หมายเหตุ {ผู้ป่วย: สมชาย} คงอยู่",
    ],
)
def test_sanitizer_keeps_braces_that_are_not_css(prose):
    """Braces in prose are content.

    The stripper used to match any `{...}` run, which silently deleted JSON
    snippets, set notation, Thai template placeholders and quoted identifiers
    from otherwise ordinary documents.
    """
    assert cleaner.optimize(prose).strip() == prose


@pytest.mark.parametrize(
    "css, expected",
    [
        ("p { color: red; font-size: 12px; }", "p"),
        (".card{margin:0;padding:8px}", ".card"),
        ("body { background: #fff; }", "body"),
        ("Text { font: bold }", "Text"),
    ],
)
def test_sanitizer_still_strips_real_css_blocks(css, expected):
    assert cleaner.optimize(css).strip() == expected
