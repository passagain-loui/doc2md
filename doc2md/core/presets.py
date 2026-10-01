"""Named conversion-option presets for the GUI.

Each preset maps to a concrete, testable set of engine options. The GUI's
job is only to apply/detect these - the mapping itself lives here so it can
be tested without Qt. "Custom" is not a real preset entry: it is what the
GUI falls back to display whenever the current option values do not match
any named preset exactly (the user edited something by hand).
"""

from __future__ import annotations

CUSTOM = "Custom"

PRESETS: dict[str, dict] = {
    "Balanced AI": {
        "ocr_lang": "tha+eng",
        "ocr_dpi": 300,
        "pdf_tables": True,
        "pdf_ocr_fallback": True,
    },
    "High Fidelity": {
        "ocr_lang": "tha+eng",
        "ocr_dpi": 400,
        "pdf_tables": True,
        "pdf_ocr_fallback": True,
    },
    "Fast Text": {
        "ocr_lang": "eng",
        "ocr_dpi": 150,
        "pdf_tables": False,
        "pdf_ocr_fallback": True,
    },
    "Thai Scanned Document": {
        "ocr_lang": "tha",
        "ocr_dpi": 300,
        "pdf_tables": True,
        "pdf_ocr_fallback": True,
    },
}

PRESET_NAMES: tuple[str, ...] = tuple(PRESETS) + (CUSTOM,)

# The keys every preset (and therefore every "current options" probe) is
# compared on. Anything else in an options dict (max_rows, inline_styles,
# ...) is irrelevant to which OCR/table preset is active.
_PRESET_KEYS = ("ocr_lang", "ocr_dpi", "pdf_tables", "pdf_ocr_fallback")


def options_for(preset_name: str) -> dict:
    """Return a copy of the option values for *preset_name*.

    Raises ``KeyError`` for ``CUSTOM`` (it has no fixed values by
    definition) or an unrecognized name.
    """
    return dict(PRESETS[preset_name])


def matching_preset(options: dict) -> str:
    """Return the preset name whose values *options* exactly matches, or
    ``CUSTOM`` if none do (including when a value was edited by hand)."""
    current = {key: options.get(key) for key in _PRESET_KEYS}
    for name, values in PRESETS.items():
        if current == values:
            return name
    return CUSTOM
