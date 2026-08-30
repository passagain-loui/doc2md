"""Excel/CSV engine with a hard row limit that emits a Truncated Summary.

Spreadsheets exceeding `max_rows` (default 10,000) never materialize fully in
memory: openpyxl runs in read_only streaming mode and CSV is consumed line by
line, stopping as soon as the limit is exceeded.

Grid rendering is delegated to :mod:`doc2md.core.tables`, so a sheet whose rows
have different lengths - the normal result of trailing empty cells or merged
regions - still produces a table with one consistent column count instead of
rows that slide sideways.
"""

from __future__ import annotations

import csv
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.router import FileKind
from doc2md.core.tables import render_table
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

    @staticmethod
    def _limits(options: dict) -> tuple[int, int]:
        try:
            max_rows = max(1, int(options.get("max_rows", DEFAULT_MAX_ROWS)))
        except (TypeError, ValueError):
            max_rows = DEFAULT_MAX_ROWS
        try:
            sample_rows = max(1, int(options.get("sample_rows", DEFAULT_SAMPLE_ROWS)))
        except (TypeError, ValueError):
            sample_rows = DEFAULT_SAMPLE_ROWS
        return max_rows, sample_rows

    def _convert_csv(self, source: Path, options: dict) -> str:
        max_rows, sample_rows = self._limits(options)
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
                source.stem, rows, total_rows=total, truncated=total > max_rows
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
                "XLSX backend missing: pip install -r requirements.txt (openpyxl)"
            ) from exc

        max_rows, sample_rows = self._limits(options)
        try:
            workbook = openpyxl.load_workbook(
                str(source), read_only=True, data_only=True
            )
        except Exception as exc:
            raise ConversionError(
                f"Corrupted or unreadable XLSX: {source} ({exc})"
            ) from exc

        parts: list[str] = [f"# {source.name}", ""]
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
                parts.append(
                    self._sheet_markdown(
                        sheet.title, rows, total_rows=total, truncated=truncated
                    )
                )
                parts.append("")
        finally:
            try:
                workbook.close()
            except Exception:
                pass
        return "\n".join(parts).rstrip() + "\n"

    @staticmethod
    def _trim_trailing_blanks(rows: list[list]) -> list[list]:
        """Drop columns that are empty in every sampled row.

        Excel reports a sheet's used range generously; a two-column table often
        arrives as eight columns with six empty ones, which turns into six
        phantom ``col3..col8`` headers in the Markdown.
        """
        if not rows:
            return rows
        width = max(len(row) for row in rows)
        last_used = 0
        for row in rows:
            for index in range(len(row) - 1, -1, -1):
                value = row[index]
                if value is not None and str(value).strip():
                    last_used = max(last_used, index + 1)
                    break
        if last_used == 0:
            return []
        if last_used >= width:
            return rows
        return [row[:last_used] for row in rows]

    def _sheet_markdown(
        self, title: str, rows, *, total_rows: int, truncated: bool
    ) -> str:
        lines = [f"## Sheet: {title}", ""]
        note_lines = []
        if truncated:
            note_lines.append(
                f"> **Truncated Summary:** sheet `{title}` exceeds the configured "
                f"row limit; only a preview of the first rows is shown "
                f"(detected rows >= {total_rows:,})."
            )

        table = render_table(
            self._trim_trailing_blanks(list(rows)), name_empty_headers=True
        )
        if not table:
            lines.append("_(empty sheet)_")
            lines.extend(note_lines)
            return "\n".join(lines)

        lines.append(table)
        lines.append("")
        lines.extend(note_lines)
        return "\n".join(lines)
