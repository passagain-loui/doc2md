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
import datetime as _dt
import re
from pathlib import Path

from doc2md.core.errors import ConversionError, EngineUnavailableError
from doc2md.core.quality import EngineOutput, QualityMetrics
from doc2md.core.router import FileKind
from doc2md.core.tables import render_table
from doc2md.engine.base import BaseEngine

DEFAULT_MAX_ROWS = 10_000
DEFAULT_SAMPLE_ROWS = 25
BLANK_RUN_LIMIT = 1000
# A sheet's declared range can run to column XFC (16383); nothing real is wider.
MAX_COLUMNS = 1024
# Leading rows holding a single value are a title or caption, not a header.
MAX_TITLE_ROWS = 5
# A real header row has at least this many values; two-column rows stay as-is.
MIN_HEADER_VALUES = 3

_PERCENT_DECIMALS_RE = re.compile(r"\.(0+)")
_FIXED_DECIMALS_RE = re.compile(r"^[#,0]*\.(0+)$")


def format_cell_value(value, number_format: str = "General"):
    """Render one spreadsheet value the way a reader of the sheet sees it.

    Midnight datetimes become plain dates, percentages keep their percent form,
    floats lose binary noise, and strings lose the padding Excel users leave.
    """
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, _dt.datetime):
        if value.time() == _dt.time(0):
            return value.date().isoformat()
        return value.replace(microsecond=0).isoformat(sep=" ")
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, _dt.time):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, float):
        if value.is_integer() and "%" not in number_format:
            return str(int(value))
        if "%" in number_format:
            match = _PERCENT_DECIMALS_RE.search(number_format)
            decimals = len(match.group(1)) if match else 0
            return f"{value * 100:.{decimals}f}%"
        match = _FIXED_DECIMALS_RE.match(number_format)
        if match:
            return f"{value:.{len(match.group(1))}f}"
        return format(value, ".12g")
    return value


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
# Sheet XML larger than this (uncompressed) is not scanned for merged cells.
MAX_MERGE_SCAN_BYTES = 300 * 1024 * 1024
# A header block is looked for among a sheet's first rows only.
HEADER_SEARCH_ROWS = 15

Merge = tuple  # (min_row, min_col, max_row, max_col), 1-based


def sheet_xml_paths(source: Path) -> list[str]:
    """Part names of the workbook's sheets, in workbook order."""
    import xml.etree.ElementTree as ET
    import zipfile

    with zipfile.ZipFile(source) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {rel.get("Id"): rel.get("Target") for rel in rels.iter(f"{{{_PKG_REL_NS}}}Relationship")}
    paths = []
    for sheet in book.iter(f"{{{_MAIN_NS}}}sheet"):
        target = targets.get(sheet.get(f"{{{_REL_NS}}}id")) or ""
        paths.append(target.lstrip("/") if target.startswith("/") else "xl/" + target)
    return paths


def read_merged_ranges(source: Path, part: str) -> list[Merge]:
    """Merged cell ranges of one sheet, read straight from its XML.

    openpyxl's read-only mode (used so big sheets stream) does not expose
    merges, and loading the whole workbook would hold every cell in memory. The
    ``<mergeCell>`` entries are a few bytes each, so they are read on their own.
    Any failure returns no merges: the sheet then converts as before.
    """
    import xml.etree.ElementTree as ET
    import zipfile

    from openpyxl.utils.cell import range_boundaries

    merges: list[Merge] = []
    try:
        with zipfile.ZipFile(source) as archive:
            if archive.getinfo(part).file_size > MAX_MERGE_SCAN_BYTES:
                return []
            with archive.open(part) as handle:
                for _event, element in ET.iterparse(handle, events=("end",)):
                    tag = element.tag
                    if tag == f"{{{_MAIN_NS}}}mergeCell":
                        min_col, min_row, max_col, max_row = range_boundaries(element.get("ref"))
                        merges.append((min_row, min_col, max_row, min(max_col, MAX_COLUMNS)))
                    elif tag == f"{{{_MAIN_NS}}}mergeCells":
                        break
                    elif tag == f"{{{_MAIN_NS}}}row":
                        element.clear()
    except Exception:
        return []
    return merges


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
        include_hidden = bool(options.get("include_hidden_sheets", False))
        all_sheets = list(workbook.worksheets)
        visible = [sheet for sheet in all_sheets if sheet.sheet_state == "visible"]
        # A workbook whose every sheet is hidden still has to produce output.
        selected = all_sheets if include_hidden or not visible else visible
        skipped = [sheet.title.strip() for sheet in all_sheets if sheet not in selected]
        if skipped:
            parts.extend([
                f"> {len(skipped)} hidden sheet(s) were not converted: "
                + ", ".join(f"`{name}`" for name in skipped)
                + ". Enable hidden sheets to include them.",
                "",
            ])
        sheets_detected = 0
        rows_detected_total = 0
        rows_exported_total = 0
        any_truncated = False
        all_exact = True
        try:
            try:
                sheet_parts = sheet_xml_paths(source)
            except Exception:
                sheet_parts = []
            for sheet in selected:
                sheets_detected += 1
                position = all_sheets.index(sheet)
                merges = (
                    read_merged_ranges(source, sheet_parts[position])
                    if len(sheet_parts) == len(all_sheets)
                    else []
                )
                rows, total, sheet_exact = self._scan_rows(
                    self._formatted_rows(sheet), max_rows
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
                        sheet.title.strip(), rows, total_rows=total,
                        truncated=truncated, merges=merges,
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
    def _formatted_rows(sheet):
        """Yield each row as a list of display values, trailing blanks removed."""
        max_col = min(sheet.max_column or 1, MAX_COLUMNS)
        for cells in sheet.iter_rows(max_col=max_col):
            row = [format_cell_value(cell.value, cell.number_format) for cell in cells]
            while row and row[-1] is None:
                row.pop()
            yield row

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

    @staticmethod
    def _unfold_merged(rows: list[list], merges) -> "tuple[list[str], list[list]] | None":
        """Use merged cells to find the header block and label every column.

        A merged range taller than one row that starts near the top marks a
        multi-row header (``No.`` spanning four rows, ``Period`` spanning a month
        of day columns). Rows above it are titles; the header rows are folded into
        one row whose names join the labels top-down (``Period / Mon / 10``);
        vertical merges below it repeat their value on every row they cover so each
        row stands alone. Returns ``None`` when there is no such block, leaving the
        plain title/header heuristic to decide.
        """
        tall = [m for m in merges if m[2] > m[0] and m[0] <= HEADER_SEARCH_ROWS]
        if not tall or not rows:
            return None
        start = min(m[0] for m in tall) - 1
        if start >= len(rows):
            return None
        if sum(1 for v in rows[start] if v is not None) < MIN_HEADER_VALUES:
            return None

        bottom = start
        changed = True
        while changed:
            changed = False
            for m in merges:
                if start <= m[0] - 1 <= bottom and m[2] - 1 > bottom:
                    bottom = m[2] - 1
                    changed = True
        bottom = min(bottom, len(rows) - 1)

        def cell(r: int, c: int):
            row = rows[r]
            return row[c] if c < len(row) else None

        width = max(len(row) for row in rows[start:bottom + 1])
        for m in merges:
            if m[0] - 1 <= bottom and m[2] - 1 >= start:
                width = max(width, m[3])
        width = min(width, MAX_COLUMNS)

        block = [[cell(r, c) for c in range(width)] for r in range(start, bottom + 1)]
        for m in merges:
            if not (start <= m[0] - 1 <= bottom):
                continue
            value = cell(m[0] - 1, m[1] - 1)
            for r in range(m[0] - 1, min(m[2] - 1, bottom) + 1):
                for c in range(m[1] - 1, min(m[3], width)):
                    block[r - start][c] = value

        names: list[str] = []
        for c in range(width):
            parts: list[str] = []
            for row in block:
                text = "" if row[c] is None else " ".join(str(row[c]).split())
                if text and (not parts or parts[-1] != text):
                    parts.append(text)
            names.append(" / ".join(parts))

        titles = []
        for r in range(start):
            values = [" ".join(str(v).split()) for v in rows[r] if v is not None and str(v).strip()]
            if values:
                titles.append(" | ".join(values))

        data = [list(row) for row in rows[bottom + 1:]]
        offset = bottom + 1
        for m in merges:
            first = m[0] - 1
            if m[2] <= m[0] or first < offset or first >= len(rows):
                continue
            value = cell(first, m[1] - 1)
            if value is None:
                continue
            for r in range(first + 1, min(m[2], len(rows))):
                row = data[r - offset]
                if len(row) < m[3]:
                    row.extend([None] * (m[3] - len(row)))
                for c in range(m[1] - 1, m[3]):
                    if row[c] is None:
                        row[c] = value
        return titles, [names] + data

    def _split_titles(self, rows: list[list]) -> tuple[list[str], list[list]]:
        """Separate leading title rows from the table that follows them.

        A sheet usually opens with a report name (often one merged cell). Taken
        as the header it would push the real header row into the data and
        invent ``col2..colN`` names. Leading rows with at most one value, up to
        ``MAX_TITLE_ROWS``, become text lines when a row with at least
        ``MIN_HEADER_VALUES`` values follows; otherwise the rows are left alone.
        """
        titles: list[str] = []
        for index, row in enumerate(rows[:MAX_TITLE_ROWS + 1]):
            values = [str(v) for v in row if v is not None and str(v).strip()]
            if len(values) >= MIN_HEADER_VALUES:
                return titles, rows[index:]
            if len(values) >= 2 or index >= MAX_TITLE_ROWS:
                return [], rows
            if values:
                titles.append(" ".join(values[0].split()))
        return [], rows

    def _sheet_markdown(
        self, title: str, rows, *, total_rows: int, truncated: bool, merges=()
    ) -> str:
        lines = [f"## Sheet: {title}", ""]
        note_lines = []
        if truncated:
            note_lines.append(
                f"> **Truncated Summary:** sheet `{title}` exceeds the configured "
                f"row limit; only a preview of the first rows is shown "
                f"({total_rows:,} rows detected in total)."
            )

        rows = list(rows)
        unfolded = self._unfold_merged(rows, merges)
        if unfolded is not None:
            titles, rows = unfolded
        else:
            titles, rows = self._split_titles(rows)
        table = render_table(
            self._trim_trailing_blanks(rows), name_empty_headers=True
        )
        if not table:
            lines.extend(titles)
            lines.append("_(empty sheet)_" if not titles else "")
            lines.extend(note_lines)
            return "\n".join(lines)

        for title in titles:
            lines.extend([title, ""])
        lines.append(table)
        lines.append("")
        lines.extend(note_lines)
        return "\n".join(lines)
