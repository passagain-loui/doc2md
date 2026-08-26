# docx_engine.py

```python
"""DOCX engine built on python-docx with order-aware block iteration."""

from __future__ import annotations

from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine


class DocxEngine(BaseEngine):
    name = "docx"
    supported_kinds = (FileKind.DOCX,)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        try:
            import docx
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph
        except ImportError as exc:
            raise EngineUnavailableError(
                "DOCX backend missing: pip install 'doc2md[docs]' (python-docx)"
            ) from exc

        try:
            document = docx.Document(str(source))
        except Exception as exc:
            raise ConversionError(f"Corrupted or unreadable DOCX: {source} ({exc})") from exc

        def iter_blocks():
            for child in document.element.body.iterchildren():
                if child.tag == qn("w:p"):
                    yield Paragraph(child, document)
                elif child.tag == qn("w:tbl"):
                    yield Table(child, document)

        parts: list[str] = [f"# {Path(source).name}", ""]
        try:
            for block in iter_blocks():
                if isinstance(block, Paragraph):
                    line = self._paragraph_to_markdown(block)
                    if line:
                        parts.append(line)
                        if line.startswith("#"):
                            parts.append("")
                else:
                    table_md = self._table_to_markdown(block)
                    if table_md:
                        parts.append(table_md)
                        parts.append("")
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"DOCX conversion failed: {source} ({exc})") from exc

        return "\n".join(parts).strip() + "\n"

    @staticmethod
    def _paragraph_to_markdown(paragraph) -> str:
        style_name = ""
        try:
            style_name = (paragraph.style.name or "").lower()
        except Exception:
            pass
        text = " ".join(paragraph.text.split())
        if not text:
            return ""
        if style_name.startswith("heading"):
            digits = "".join(ch for ch in style_name if ch.isdigit())
            level = min(max(int(digits) if digits else 1, 1), 6)
            return f"{'#' * level} {text}"
        if "title" in style_name:
            return f"# {text}"
        if "list bullet" in style_name:
            return f"- {text}"
        if "list number" in style_name:
            return f"1. {text}"
        if "quote" in style_name:
            return f"> {text}"
        return text

    @staticmethod
    def _table_to_markdown(table) -> str:
        rows = []
        for row in table.rows:
            cells = [" ".join(cell.text.split()) for cell in row.cells]
            if any(cells):
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = [
            "| " + " | ".join(rows[0]) + " |",
            "| " + " | ".join(["---"] * width) + " |",
        ]
        lines.extend("| " + " | ".join(r) + " |" for r in rows[1:])
        return "\n".join(lines)
```
