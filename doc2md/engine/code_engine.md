# code_engine.py

````python
"""Code/JSON/text engine: wraps sources in language-tagged fenced blocks."""

from __future__ import annotations

import json
from pathlib import Path

from doc2md.core.encoding import read_text_smart
from doc2md.core.router import FileKind, guess_language
from doc2md.engine.base import BaseEngine

MAX_LINE_LENGTH = 10_000


class CodeEngine(BaseEngine):
    name = "code"
    supported_kinds = (FileKind.JSON, FileKind.CODE, FileKind.TEXT, FileKind.UNKNOWN)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        try:
            text = read_text_smart(source)
        except OSError as exc:
            from doc2md.core.errors import ConversionError

            raise ConversionError(f"Unreadable file: {source} ({exc})") from exc

        suffix = source.suffix.lower()
        if suffix == ".json" or (suffix == "" and text.lstrip()[:1] in ("{", "[")):
            return self._convert_json(source, text)
        return self._fence(source, text)

    def _convert_json(self, source: Path, text: str) -> str:
        header = f"# {Path(source).name}"
        try:
            parsed = json.loads(text)
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
        except (ValueError, RecursionError):
            pretty = text.strip()
            body = f"```json\n{self._clamp(pretty)}\n```"
            return f"{header}\n\n> Warning: invalid JSON returned verbatim.\n\n{body}\n"
        body = f"```json\n{self._clamp(pretty)}\n```"
        return f"{header}\n\n{body}\n"

    def _fence(self, source: Path, text: str) -> str:
        language = guess_language(source) or "text"
        title = Path(source).name
        fence = "```"
        while fence in text:
            fence += "`"
        return (
            f"# {title}\n\n"
            f"{fence}{language}\n{self._clamp(text.rstrip())}\n{fence}\n"
        )

    @staticmethod
    def _clamp(text: str) -> str:
        lines_out = []
        for line in text.splitlines():
            lines_out.append(line if len(line) <= MAX_LINE_LENGTH else line[:MAX_LINE_LENGTH])
        return "\n".join(lines_out)
````
