"""Milestone 4 - conversion presets.

Every preset maps to concrete options; editing an option away from a
preset's fixed values must be detected as Custom.
"""

from __future__ import annotations

import pytest

from doc2md.core.presets import CUSTOM, PRESET_NAMES, PRESETS, matching_preset, options_for


@pytest.mark.parametrize("name", list(PRESETS))
def test_options_for_returns_the_presets_own_values(name):
    values = options_for(name)
    assert values == PRESETS[name]
    # must be a copy, not a live reference to the module's dict
    values["ocr_lang"] = "mutated"
    assert PRESETS[name]["ocr_lang"] != "mutated"


def test_options_for_unknown_preset_raises_keyerror():
    with pytest.raises(KeyError):
        options_for("not-a-real-preset")


def test_options_for_custom_raises_keyerror():
    with pytest.raises(KeyError):
        options_for(CUSTOM)


@pytest.mark.parametrize("name", list(PRESETS))
def test_matching_preset_recognizes_its_own_exact_options(name):
    assert matching_preset(PRESETS[name]) == name


def test_matching_preset_ignores_unrelated_keys():
    values = dict(PRESETS["Balanced AI"])
    values["max_rows"] = 999999  # unrelated to which OCR/table preset is active
    assert matching_preset(values) == "Balanced AI"


def test_matching_preset_returns_custom_for_a_hand_edited_value():
    values = dict(PRESETS["Balanced AI"])
    values["ocr_dpi"] = 275  # not any preset's value
    assert matching_preset(values) == CUSTOM


def test_matching_preset_returns_custom_for_empty_options():
    assert matching_preset({}) == CUSTOM


def test_preset_names_lists_every_preset_plus_custom_last():
    assert PRESET_NAMES[-1] == CUSTOM
    assert set(PRESET_NAMES[:-1]) == set(PRESETS)
