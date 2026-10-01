"""Excel/CSV engine with a hard row limit that emits a Truncated Summary.

Spreadsheets exceeding `max_rows` (default 10,000) never *retain* more than
`max_rows` rows in memory: openpyxl runs in read_only streaming mode and CSV
is consumed line by line, and only the rows up to the limit are kept. Row
*counting*, however, continues past the limit to the real end of the
sheet/file - `rows_detected` in the quality metrics is always the true row
count, never a guessed lower bound frozen at `max_rows + 1`. This costs
nothing extra for CSV (the whole decoded text is already in memory before
counting starts) and stays streaming/bounded-memory for XLSX (openpyxl's
read-only iterator yields one row at a time regardless of how many are
counted).

Grid rendering is delegated to :mod:`doc2md.core.tables`, so a sheet whose rows
have different lengths - the normal result of trailing empty cells or merged
regions - still produces a table with one consistent column count instead of
rows that slide sideways.
"""

from __future__ import annotations

import csv
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.quality import EngineOutput, QualityMetrics
from doc2md.core.router import FileKind
from doc2md.core.tables import render_table
from doc2md.engine.base import BaseEngine

DEFAULT_MAX_ROWS = 10_000
DEFAULT_SAMPLE_ROWS = 25
BLANK_RUN_LIMIT = 1000


class ExcelEngine(BaseEngine):
    name = "excel"
    supported_kinds = (FileKind.XLSX, FileKind.CSV)
    requires_process_isolation = False

    def convert(self, source: Path, options: dict) -> str:
        markdown, _metrics = self._convert_dispatch(source, options)
        return markdown

    def convert_structured(self, source: Path, options: dict) -> EngineOutput:
        markdown, metrics = self._convert_dispatch(source, options)
        return EngineOutput(markdown=markdown, metrics=metrics)

    def _convert_dispatch(self, source: Path, options: dict) -> tuple[str, QualityMetrics]:
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

    def _convert_csv(self, source: Path, options: dict) -> tuple[str, QualityMetrics]:
        max_rows, sample_rows = self._limits(options)
        encoding_pref = options.get("encodings", ("utf-8-sig", "utf-8"))
        raw = source.read_bytes()
        from doc2md.core.encoding import decode_bytes

        text = decode_bytes(raw, prefer_encodings=tuple(encoding_pref))
        reader = csv.reader(text.splitlines())
        try:
            rows, total, exact = self._scan_rows(reader, max_rows)
            del text
            truncated = total > max_rows
            if truncated:
                rows = rows[:sample_rows]
            markdown = self._sheet_markdown(
                source.stem, rows, total_rows=total, truncated=truncated
            )
            metrics = QualityMetrics(
                sheets_detected=1,
                rows_detected=total,
                rows_detected_is_exact=exact,
                rows_exported=len(rows),
                truncated=truncated,
            )
            return markdown, metrics
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"CSV conversion failed: {source} ({exc})") from exc

    def _convert_xlsx(self, source: Path, options: dict) -> tuple[str, QualityMetrics]:
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
        sheets_detected = 0
        rows_detected_total = 0
        rows_exported_total = 0
        any_truncated = False
        all_exact = True
        try:
            for sheet in workbook.worksheets:
                sheets_detected += 1
                rows, total, sheet_exact = self._scan_rows(
                    sheet.iter_rows(values_only=True), max_rows
                )
                all_exact = all_exact and sheet_exact
                truncated = total > max_rows
                if truncated:
                    rows = rows[:sample_rows]
                rows_detected_total += total
                rows_exported_total += len(rows)
                any_truncated = any_truncated or truncated
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
        markdown = "\n".join(parts).rstrip() + "\n"
        metrics = QualityMetrics(
            sheets_detected=sheets_detected,
            rows_detected=rows_detected_total,
            rows_detected_is_exact=all_exact,
            rows_exported=rows_exported_total,
            truncated=any_truncated,
        )
        return markdown, metrics

    @staticmethod
    def _row_is_blank(row) -> bool:
        return all(value is None or not str(value).strip() for value in row)

    def _scan_rows(self, iterator, max_rows: int) -> tuple[list[list], int, bool]:
        """Walk *iterator* keeping at most ``max_rows`` rows.

        Returns ``(rows, total, exact)`` where *total* is the position of the
        last non-blank row. Blank rows after it are not counted: a sheet whose
        declared range runs to row 1,048,576 would otherwise be walked to the
        end and report a million phantom rows. After ``BLANK_RUN_LIMIT``
        consecutive blank rows the walk stops and *exact* is False.
        """
        rows: list[list] = []
        seen = 0
        total = 0
        blank_run = 0
        exact = True
        for row in iterator:
            seen += 1
            if self._row_is_blank(row):
                blank_run += 1
                if blank_run >= BLANK_RUN_LIMIT:
                    exact = False
                    break
            else:
                blank_run = 0
                total = seen
            if seen <= max_rows:
                rows.append(list(row))
        return rows[:total], total, exact

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
                f"({total_rows:,} rows detected in total)."
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
