"""PPTX engine: slide-by-slide Markdown preserving hierarchy and emphasis.

Structure that survives the conversion:

* the slide title becomes an ``##`` heading;
* body placeholders become bullet lists whose nesting follows the paragraph's
  outline level, so a three-level agenda slide stays three levels deep;
* bold/italic runs keep their emphasis markers;
* tables go through :mod:`doc2md.core.tables`;
* speaker notes are appended as a blockquote.

Shapes are visited in the order python-pptx reports them, and shapes nested
inside groups are visited recursively - grouped text boxes are common in decks
built from templates and were previously dropped entirely.
"""

from __future__ import annotations

import re
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.core.tables import render_table
from doc2md.engine.base import BaseEngine

_MAX_BULLET_DEPTH = 4
_BULLET_CHARS = "•●▪‣⁃-"


class PptxEngine(BaseEngine):
    name = "pptx"
    supported_kinds = (FileKind.PPTX,)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        try:
            from pptx import Presentation
        except ImportError as exc:
            raise EngineUnavailableError(
                "PPTX backend missing: pip install -r requirements.txt (python-pptx)"
            ) from exc

        try:
            presentation = Presentation(str(source))
        except Exception as exc:
            raise ConversionError(
                f"Corrupted or unreadable PPTX: {source} ({exc})"
            ) from exc

        emphasis = bool(options.get("inline_styles", True))
        parts: list[str] = [f"# {source.name}", ""]
        try:
            for index, slide in enumerate(presentation.slides, start=1):
                parts.append(self._slide_markdown(index, slide, emphasis=emphasis))
                parts.append("")
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"PPTX conversion failed: {source} ({exc})") from exc
        return "\n".join(parts).strip() + "\n"

    # ----------------------------------------------------------------- slides

    def _slide_markdown(self, index: int, slide, *, emphasis: bool) -> str:
        title = ""
        body: list[str] = []
        tables: list[str] = []

        try:
            for shape in self._iter_shapes(slide.shapes):
                if getattr(shape, "has_table", False) and shape.has_table:
                    table_md = render_table(
                        [[cell.text for cell in row.cells] for row in shape.table.rows]
                    )
                    if table_md:
                        tables.append(table_md)
                    continue

                if not getattr(shape, "has_text_frame", False):
                    continue

                lines = self._text_frame_lines(shape.text_frame, emphasis=emphasis)
                if not lines:
                    continue

                if not title and self._is_title_shape(shape):
                    title = lines[0][1]
                    lines = lines[1:]
                elif not title and not body:
                    # Decks built without placeholders have no title shape at
                    # all; the first line of the first text box stands in.
                    title = lines[0][1]
                    lines = lines[1:]

                for level, text in lines:
                    body.append(f"{'  ' * level}- {text}")
        except Exception as exc:
            raise ConversionError(f"Failed to parse slide {index}: {exc}") from exc

        heading = f"## Slide {index}: {title}" if title else f"## Slide {index}"
        out = [heading, ""]
        out.extend(body)
        for table in tables:
            out.extend(["", table])
        notes = self._notes_text(slide)
        if notes:
            out.extend(["", f"> Speaker notes: {notes}"])
        return "\n".join(out).rstrip()

    @classmethod
    def _iter_shapes(cls, shapes):
        """Yield shapes depth-first, descending into group shapes."""
        for shape in shapes:
            nested = getattr(shape, "shapes", None)
            if nested is not None and not getattr(shape, "has_text_frame", False):
                yield from cls._iter_shapes(nested)
            else:
                yield shape

    @classmethod
    def _text_frame_lines(cls, text_frame, *, emphasis: bool) -> list[tuple[int, str]]:
        lines: list[tuple[int, str]] = []
        for paragraph in text_frame.paragraphs:
            text = cls._paragraph_text(paragraph, emphasis=emphasis)
            if not text:
                continue
            try:
                level = int(paragraph.level or 0)
            except (TypeError, ValueError):
                level = 0
            lines.append((min(max(level, 0), _MAX_BULLET_DEPTH), text))
        return lines

    @staticmethod
    def _paragraph_text(paragraph, *, emphasis: bool) -> str:
        plain = " ".join(paragraph.text.split()).strip(_BULLET_CHARS).strip()
        if not emphasis or not plain:
            return plain

        spans: list[tuple[bool, bool, str]] = []
        try:
            for run in paragraph.runs:
                if not run.text:
                    continue
                key = (bool(run.font.bold), bool(run.font.italic))
                if spans and (spans[-1][0], spans[-1][1]) == key:
                    spans[-1] = (key[0], key[1], spans[-1][2] + run.text)
                else:
                    spans.append((key[0], key[1], run.text))
        except Exception:
            return plain
        if not spans:
            return plain

        out: list[str] = []
        for bold, italic, chunk in spans:
            body = " ".join(chunk.split())
            if not body:
                out.append(" ")
                continue
            if bold and italic:
                body = f"***{body}***"
            elif bold:
                body = f"**{body}**"
            elif italic:
                body = f"*{body}*"
            out.append(body)

        merged = re.sub(r"[ \t]{2,}", " ", " ".join(out)).strip()
        merged = merged.strip(_BULLET_CHARS).strip()
        return merged or plain

    @staticmethod
    def _is_title_shape(shape) -> bool:
        try:
            if not shape.is_placeholder or not shape.has_text_frame:
                return False
            # 0 = centre title, 13 = title on most content layouts.
            return shape.placeholder_format.idx in (0, 13)
        except Exception:
            return False

    @staticmethod
    def _notes_text(slide) -> str:
        try:
            if not slide.has_notes_slide:
                return ""
            notes_slide = slide.notes_slide
        except Exception:
            return ""
        if notes_slide is None or notes_slide.notes_text_frame is None:
            return ""
        return " ".join(notes_slide.notes_text_frame.text.split())
