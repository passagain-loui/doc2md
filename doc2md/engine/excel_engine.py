"""Excel/CSV engine with a hard row limit that emits a Truncated Summary.

Spreadsheets exceeding `max_rows` (default 10,000) never materialize fully in
memory: openpyxl runs in read_only streaming mode and CSV is consumed line by
line, stopping as soon as the limit is exceeded.
"""

from __future__ import annotations

import csv
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.engine.base import BaseEngine

DEFAULT_MAX_ROWS = 10_000
DEFAULT_SAMPLE_ROWS = 25


class ExcelEngine(BaseEngine):
    name = "excel"
    supported_kinds = (FileKind.XLSX, FileKind.CSV)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        self.validate_source(source)
        suffix = source.suffix.lower()
        if suffix == ".csv":
            return self._convert_csv(source, options)
        if suffix in (".xlsx", ".xlsm"):
            return self._convert_xlsx(source, options)
        raise ConversionError(
            f"Legacy .xls format is not supported; re-save as .xlsx: {source}"
        )

    def _convert_csv(self, source: Path, options: dict) -> str:
        max_rows = int(options.get("max_rows", DEFAULT_MAX_ROWS))
        sample_rows = int(options.get("sample_rows", DEFAULT_SAMPLE_ROWS))
        encoding_pref = options.get("encodings", ("utf-8-sig", "utf-8"))
        raw = source.read_bytes()
        from doc2md.core.encoding import decode_bytes

        text = decode_bytes(raw, prefer_encodings=tuple(encoding_pref))
        reader = csv.reader(text.splitlines())
        try:
            rows = []
            total = 0
            for row in reader:
                total += 1
                if len(rows) <= min(sample_rows, max_rows):
                    rows.append(row)
                elif total > max_rows:
                    break
            del text
            return self._sheet_markdown(
                Path(source).stem, rows, total_rows=total, truncated=total > max_rows
            )
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"CSV conversion failed: {source} ({exc})") from exc

    def _convert_xlsx(self, source: Path, options: dict) -> str:
        try:
            import openpyxl
        except ImportError as exc:
            raise EngineUnavailableError(
                "XLSX backend missing: pip install 'doc2md[docs]' (openpyxl)"
            ) from exc

        max_rows = int(options.get("max_rows", DEFAULT_MAX_ROWS))
        sample_rows = int(options.get("sample_rows", DEFAULT_SAMPLE_ROWS))
        try:
            workbook = openpyxl.load_workbook(
                str(source), read_only=True, data_only=True
            )
        except Exception as exc:
            raise ConversionError(f"Corrupted or unreadable XLSX: {source} ({exc})") from exc

        parts: list[str] = [f"# {Path(source).name}", ""]
        try:
            for sheet in workbook.worksheets:
                rows: list[list] = []
                total = 0
                truncated = False
                for row in sheet.iter_rows(values_only=True):
                    total += 1
                    if len(rows) <= min(sample_rows, max_rows):
                        rows.append(list(row))
                    elif total > max_rows:
                        truncated = True
                        break
                parts.append(self._sheet_markdown(sheet.title, rows,
                                                  total_rows=total, truncated=truncated))
                parts.append("")
        finally:
            try:
                workbook.close()
            except Exception:
                pass
        return "\n".join(parts)

    @staticmethod
    def _escape_cell(value) -> str:
        if value is None:
            return ""
        text = str(value).replace("\r\n", " ").replace("\n", " ").replace("|", "\\|")
        return " ".join(text.split())

    def _sheet_markdown(self, title: str, rows, *, total_rows: int, truncated: bool) -> str:
        lines = [f"## Sheet: {title}", ""]
        note_lines = []
        if truncated:
            note_lines.append(
                f"> **Truncated Summary:** sheet `{title}` exceeds the configured "
                f"row limit; only a preview of the first rows is shown "
                f"(detected rows >= {total_rows:,})."
            )
        if not rows:
            lines.append("_(empty sheet)_")
            lines.extend(note_lines)
            return "\n".join(lines)
        width = max(len(r) for r in rows)
        header = [self._escape_cell(c) or f"col{i + 1}" for i, c in enumerate(rows[0])]
        header += [f"col{i + 1}" for i in range(len(rows[0]), width)]
        body = [
            [self._escape_cell(row[i]) if i < len(row) else "" for i in range(width)]
            for row in rows
        ]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * width) + " |")
        lines.extend("| " + " | ".join(r) + " |" for r in body[1:])
        lines.append("")
        lines.extend(note_lines)
        return "\n".join(lines)
