"""Token-optimization pipeline: deduplicate, compress whitespace, strip styles."""

from __future__ import annotations

import re

_STYLE_BLOCK_RE = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(r'\s+(?:style|class|id)="[^"]*"', re.IGNORECASE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_CSS_BLOCK_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def optimize(
    markdown: str,
    *,
    dedupe: bool = True,
    compress_spaces: bool = True,
    strip_styles: bool = True,
    max_blank_lines: int = 1,
) -> str:
    """Run the token-optimization pipeline over a Markdown document.

    Fenced code blocks are protected from all transforms except newline
    normalization so code semantics are never altered.
    """
    if not markdown:
        return ""
    text = strip_zero_width(markdown.replace("\r\n", "\n").replace("\r", "\n"))
    segments = _split_code_fences(text)
    cleaned = []
    for is_code, chunk in segments:
        if is_code:
            cleaned.append(chunk.rstrip("\n"))
        else:
            cleaned.append(_clean_prose(
                chunk,
                dedupe=dedupe,
                compress_spaces=compress_spaces,
                strip_styles=strip_styles,
                max_blank_lines=max_blank_lines,
            ))
    return ("\n".join(cleaned)).strip() + "\n"


def strip_zero_width(text: str) -> str:
    for ch in ("\ufeff", "\u200b", "\u200e", "\u200f"):
        text = text.replace(ch, "")
    return text


def token_estimate(text: str) -> int:
    return max(0, len(text) // 4)


def _split_code_fences(markup: str) -> list[tuple[bool, str]]:
    parts: list[tuple[bool, str]] = []
    prose: list[str] = []
    fence: list[str] | None = None
    for line in markup.split("\n"):
        stripped = line.lstrip()
        opens = stripped.startswith("```") or stripped.startswith("~~~")
        if opens and fence is None:
            if prose:
                parts.append((False, "\n".join(prose)))
                prose = []
            fence = [line]
        elif opens and fence is not None:
            fence.append(line)
            parts.append((True, "\n".join(fence)))
            fence = None
        elif fence is not None:
            fence.append(line)
        else:
            prose.append(line)
    if fence is not None:
        parts.append((True, "\n".join(fence)))
    if prose:
        parts.append((False, "\n".join(prose)))
    return parts


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

    out_lines: list[str] = []
    last_nonempty: str | None = None
    for line in text.split("\n"):
        if compress_spaces:
            line = _MULTI_SPACE_RE.sub(" ", line)
        line = _TRAILING_SPACE_RE.sub("", line)
        if line.strip():
            if dedupe and line == last_nonempty:
                continue
            last_nonempty = line
        out_lines.append(line)

    result = "\n".join(out_lines)
    limit = max(1, max_blank_lines)
    result = _MULTI_BLANK_RE.sub("\n" * (limit + 1), result)
    return result
