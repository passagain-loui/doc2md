"""Ticks and crosses set in a symbol font come out as symbols, not as private-use junk.

A checkbox or a "meal included" mark is a character of Wingdings / ZapfDingbats /
Webdings. PyMuPDF hands back the private-use code point (U+F0FB) or the bare byte
("3" for a ZapfDingbats tick), so the Markdown got an invisible character or a
digit. The mapping applies only to a character whose own font is a dingbat font.
"""

from __future__ import annotations

import types

import pymupdf
import pytest

from doc2md.core import pdf_text
from doc2md.core.pdf_text import (
    Char,
    dingbat_family,
    map_dingbat,
    page_has_dingbat_font,
    page_lines,
    text_in,
)
from doc2md.engine.pdf_engine import PdfEngine

CHECK, HEAVY_CHECK, CROSS, HEAVY_CROSS = chr(0x2713), chr(0x2714), chr(0x2717), chr(0x2718)


def _char(text, font):
    return Char(text, 0.0, 0.0, 5.0, 10.0, font)


# ------------------------------------------------------------------ the table


@pytest.mark.parametrize(
    ("font", "code", "expected"),
    [
        ("BCDJEE+Wingdings-Regular", 0xF0FB, chr(0x2717)),  # a cross, seen in a real meal table
        ("BCDJEE+Wingdings-Regular", 0xFB, chr(0x2717)),  # the bare byte
        ("Wingdings", 0xF0FC, chr(0x2713)),
        ("Wingdings", 0xF0FE, chr(0x2611)),
        ("Wingdings", 0xF0FD, chr(0x2612)),
        ("Wingdings", 0xF0A8, chr(0x2610)),
        ("Wingdings", 0xF06C, chr(0x25CF)),
        ("BCEDEE+Wingdings2", 0xF052, chr(0x2611)),  # seen: a check in a box
        ("Wingdings 2", 0xF054, chr(0x2612)),  # seen: a cross in a box
        ("BCEAEE+Webdings", 0xF0E3, chr(0x1F6CF)),  # seen: a bed
        ("ZapfDingbats", 0x33, CHECK),
        ("ZapfDingbats", 0x34, HEAVY_CHECK),
        ("ZapfDingbats", 0x37, CROSS),
        ("ZapfDingbats", 0x38, HEAVY_CROSS),
        ("ABCDEF+ITCZapfDingbats", 0xF033, CHECK),
    ],
)
def test_known_dingbat_codes_map_to_their_symbols(font, code, expected):
    assert map_dingbat(chr(code), font) == expected


def test_the_same_code_in_an_ordinary_font_is_never_mapped():
    for font in ("Arial", "TH SarabunPSK", "Helvetica", "BCDEEE+Calibri", "Symbol", ""):
        assert map_dingbat(chr(0xF0FB), font) == chr(0xF0FB)
        assert map_dingbat("3", font) == "3"
        assert map_dingbat(chr(0xFB), font) == chr(0xFB)


def test_codes_that_are_not_in_the_table_are_left_alone():
    assert map_dingbat(chr(0xF041), "Wingdings") == chr(0xF041)
    assert map_dingbat(chr(0xF04F), "Wingdings2") == chr(0xF04F)  # glyph not verified: deliberately absent
    assert map_dingbat("9", "ZapfDingbats") == "9"


def test_text_that_is_already_a_real_symbol_is_left_alone():
    assert map_dingbat(chr(0x2713), "Wingdings") == chr(0x2713)
    assert map_dingbat(chr(0x2756), "Wingdings") == chr(0x2756)


def test_only_single_characters_are_mapped():
    assert map_dingbat("33", "ZapfDingbats") == "33"
    assert map_dingbat("", "ZapfDingbats") == ""


def test_dingbat_family_recognizes_name_variants():
    assert dingbat_family("BCDJEE+Wingdings-Regular") == "wingdings"
    assert dingbat_family("Wingdings 2") == "wingdings2"
    assert dingbat_family("Wingdings2,Bold") == "wingdings2"
    assert dingbat_family("ZapfDingbats") == "zapfdingbats"
    assert dingbat_family("ITCZapfDingbats") == "zapfdingbats"
    assert dingbat_family("Webdings") == "webdings"
    assert dingbat_family("TH SarabunPSK") is None
    assert dingbat_family("Symbol") is None  # Greek letters, not ticks
    assert dingbat_family("") is None


def test_repair_maps_dingbats_by_the_font_of_each_character():
    chars = [_char("A", "Arial"), _char(chr(0xF0FB), "BCDJEE+Wingdings-Regular"), _char(chr(0xF0FB), "Arial")]

    repaired = pdf_text._repair(chars, frozenset())

    assert [char.text for char in repaired] == ["A", CROSS, chr(0xF0FB)]


def test_page_has_dingbat_font_reads_the_font_list():
    def page(*names):
        return types.SimpleNamespace(get_fonts=lambda: [(1, "n/a", "Type1", name, "F", "") for name in names])

    assert page_has_dingbat_font(page("Helvetica", "BCDJEE+Wingdings-Regular"))
    assert not page_has_dingbat_font(page("Helvetica", "TH SarabunPSK"))
    assert not page_has_dingbat_font(page())

    def broken():
        raise RuntimeError("no fonts")

    assert not page_has_dingbat_font(types.SimpleNamespace(get_fonts=broken))


# ------------------------------------------------------------- real documents


def _zapf_pdf(path, cell_table=False):
    """A page with ordinary text, the digits 3 4 7 8 in Helvetica, and the same
    four bytes in ZapfDingbats (the base-14 symbol font: no font file needed)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 80), "Item A 3 4 7 8 end", fontname="helv", fontsize=12)
    page.insert_text((50, 110), "3478", fontname="zadb", fontsize=12)
    if cell_table:
        for r, (label, mark) in enumerate([("Meals", "3"), ("Hotel", "7")]):
            for c, (cell, font) in enumerate([(label, "helv"), (mark, "zadb")]):
                x, y = 60 + c * 120, 300 + r * 26
                page.draw_rect(pymupdf.Rect(x, y, x + 120, y + 26), color=(0, 0, 0), width=0.8)
                page.insert_text((x + 5, y + 18), cell, fontname=font, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def test_the_synthetic_pdf_really_extracts_raw_digits_without_the_fix(tmp_path):
    """Guards the other tests: PyMuPDF itself hands back "3478" for the symbol font."""
    path = _zapf_pdf(tmp_path / "z.pdf")
    with pymupdf.open(str(path)) as doc:
        assert "3478" in doc[0].get_text("text")


def test_a_symbol_font_run_converts_to_symbols_and_other_text_is_untouched(tmp_path):
    path = _zapf_pdf(tmp_path / "z.pdf")

    markdown = PdfEngine().convert(path, {"pdf_tables": False})

    assert CHECK + HEAVY_CHECK + CROSS + HEAVY_CROSS in markdown
    assert "3478" not in markdown
    assert "Item A 3 4 7 8 end" in markdown  # the same digits in an ordinary font


def test_a_tick_in_a_table_cell_is_mapped_too(tmp_path):
    pytest.importorskip("pdfplumber")
    path = _zapf_pdf(tmp_path / "z.pdf", cell_table=True)

    markdown = PdfEngine().convert(path, {"pdf_tables": True})

    assert f"| Meals | {CHECK} |" in markdown
    assert f"| Hotel | {CROSS} |" in markdown


def test_a_page_without_a_symbol_font_still_uses_the_plain_text_path(monkeypatch):
    """No dingbat font, no per-character extraction: the common path is unchanged."""

    class Page:
        def get_fonts(self):
            return [(1, "n/a", "Type1", "Helvetica", "F", "")]

        def get_text(self, kind):
            assert kind == "text"
            return " plain text \n"

    from doc2md.engine import pdf_engine

    monkeypatch.setattr(
        pdf_engine, "page_lines", lambda *a, **k: pytest.fail("characters must not be read for this page")
    )

    pages, unreadable = PdfEngine._read_text_layer([Page()])

    assert pages == ["plain text"]
    assert unreadable == 0


def test_page_lines_gives_the_mapped_symbols(tmp_path):
    path = _zapf_pdf(tmp_path / "z.pdf")
    with pymupdf.open(str(path)) as doc:
        text = text_in(page_lines(doc[0]))

    assert CHECK + HEAVY_CHECK + CROSS + HEAVY_CROSS in text
