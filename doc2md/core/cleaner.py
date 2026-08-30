"""Output sanitizer: strip leftover markup, collapse whitespace, deduplicate.

The document is first split into three kinds of block, because the cleanup that
is correct for prose is destructive everywhere else:

* **code fences** - passed through untouched apart from newline normalization;
* **pipe tables** - passed through with only trailing-whitespace trimming. The
  prose pass collapses consecutive identical lines, and a table legitimately
  repeats rows (``| 0 | 0 |`` twice in a row is data, not duplication); it also
  strips ``{...}`` groups, which would eat a cell containing braces;
* **prose** - the full pipeline: HTML/CSS residue removal, whitespace
  compression, duplicate-line removal, blank-line capping.
"""

from __future__ import annotations

import re

from doc2md.core.tables import is_table_line

_STYLE_BLOCK_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(r'\s+(?:style|class|id)="[^"]*"', re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
# A CSS declaration block, not "any braces". The previous pattern was
# `\{[^{}]*\}`, which deleted every braced run in the document: JSON snippets,
# set notation, `{placeholder}` tokens, Thai template fields, and any braced
# identifier a technical document happened to mention.
#
# The block must now open with an ASCII CSS property name followed by a colon,
# and must contain no quote characters. That is what separates real style
# residue from the two things it kept destroying:
#   {"a": 1, "b": 2}   - JSON: keys are quoted, so it never matches
#   {หมายเหตุ: สำคัญ}      - a Thai field: the property name is not ASCII
_CSS_BLOCK_RE = re.compile(
    r"\{\s*[a-zA-Z-][a-zA-Z0-9-]*\s*:[^{}\"']*\}", re.DOTALL
)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")

# Empty inline wrappers left behind after attributes are stripped. <br> is
# deliberately preserved: it is how multi-line table cells stay in their column.
_EMPTY_TAG_RE = re.compile(
    r"</?(?:span|div|font|o:p|w:[a-z]+)\b[^>]*>", re.IGNORECASE
)

CODE = "code"
TABLE = "table"
PROSE = "prose"


def optimize(
    markdown: str,
    *,
    dedupe: bool = True,
    compress_spaces: bool = True,
    strip_styles: bool = True,
    max_blank_lines: int = 1,
) -> str:
    """Run the output-sanitizer pipeline over a Markdown document."""
    if not markdown:
        return ""
    text = strip_zero_width(markdown.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned = []
    for kind, chunk in split_blocks(text):
        if kind == CODE:
            cleaned.append(chunk.rstrip("\n"))
        elif kind == TABLE:
            cleaned.append(_clean_table(chunk))
        else:
            cleaned.append(
                _clean_prose(
                    chunk,
                    dedupe=dedupe,
                    compress_spaces=compress_spaces,
                    strip_styles=strip_styles,
                    max_blank_lines=max_blank_lines,
                )
            )
    result = "\n".join(cleaned)
    result = _MULTI_BLANK_RE.sub("\n" * (max(1, max_blank_lines) + 1), result)
    return result.strip() + "\n"


def strip_zero_width(text: str) -> str:
    """Remove invisible characters that inflate token counts and break diffs.

    U+200B/U+200E/U+200F only: Thai text relies on U+0E31-U+0E4E combining
    marks, which are also zero-width but carry meaning and must survive.
    """
    for ch in ("﻿", "​", "‎", "‏"):
        text = text.replace(ch, "")
    return text


def token_estimate(text: str) -> int:
    return max(0, len(text) // 4)


def split_blocks(markup: str) -> list[tuple[str, str]]:
    """Split *markup* into ``(kind, chunk)`` pairs of code / table / prose."""
    parts: list[tuple[str, str]] = []
    buffer: list[str] = []
    current = PROSE
    fence: list[str] | None = None

    def flush() -> None:
        nonlocal buffer
        if buffer:
            parts.append((current, "\n".join(buffer)))
            buffer = []

    for line in markup.split("\n"):
        stripped = line.lstrip()
        opens = stripped.startswith("```") or stripped.startswith("~~~")

        if fence is not None:
            fence.append(line)
            if opens:
                parts.append((CODE, "\n".join(fence)))
                fence = None
            continue

        if opens:
            flush()
            current = PROSE
            fence = [line]
            continue

        kind = TABLE if is_table_line(line) else PROSE
        if kind != current:
            flush()
            current = kind
        buffer.append(line)

    if fence is not None:
        parts.append((CODE, "\n".join(fence)))
    flush()
    return parts


def _clean_table(text: str) -> str:
    """Trim each table row without touching its cell contents."""
    return "\n".join(_TRAILING_SPACE_RE.sub("", line.strip()) for line in text.split("\n"))


def _clean_prose(
    text: str,
    *,
    dedupe: bool,
    compress_spaces: bool,
    strip_styles: bool,
    max_blank_lines: int,
) -> str:
    if strip_styles:
        text = _STYLE_BLOCK_RE.sub("", text)
        text = _HTML_COMMENT_RE.sub("", text)
        text = _STYLE_ATTR_RE.sub("", text)
        text = _CSS_BLOCK_RE.sub("", text)
        text = _EMPTY_TAG_RE.sub("", text)

    out_lines: list[str] = []
    last_nonempty: str | None = None
    for line in text.split("\n"):
        if compress_spaces:
            # Leading whitespace is structure, not padding: it is what makes a
            # nested list nested. Collapsing it flattened every sub-bullet
            # extracted from DOCX and PPTX into a single level.
            indent = line[: len(line) - len(line.lstrip(" \t"))]
            line = indent + _MULTI_SPACE_RE.sub(" ", line[len(indent) :])
        line = _TRAILING_SPACE_RE.sub("", line)
        if line.strip():
            if dedupe and line == last_nonempty:
                continue
            last_nonempty = line
        out_lines.append(line)

    result = "\n".join(out_lines)
    limit = max(1, max_blank_lines)
    return _MULTI_BLANK_RE.sub("\n" * (limit + 1), result)


# Retained for callers that imported the old private helper.
def _split_code_fences(markup: str) -> list[tuple[bool, str]]:
    return [(kind == CODE, chunk) for kind, chunk in split_blocks(markup)]
