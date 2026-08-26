# stats.py

```python
"""Size/token metrics for conversion results and console table rendering."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from doc2md.core.converter import ConversionResult
from doc2md.core.tokens import estimate_tokens, saved_ratio


@dataclass(frozen=True)
class StatRow:
    name: str
    original_size: int
    markdown_size: int
    tokens: int
    saved_ratio: float


def human_size(num_bytes: int) -> str:
    value = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def build_rows(results) -> list[StatRow]:
    rows: list[StatRow] = []
    for result in results:
        if not result.success:
            continue
        try:
            original = Path(result.source).stat().st_size
        except OSError:
            original = 0
        output = len(result.markdown.encode("utf-8"))
        rows.append(
            StatRow(
                name=Path(result.source).name,
                original_size=original,
                markdown_size=output,
                tokens=estimate_tokens(result.markdown),
                saved_ratio=saved_ratio(original, output),
            )
        )
    return rows


def render_table(rows) -> str:
    if not rows:
        return "(no successful conversions)"
    header = (
        f"{'File':<28}{'Original':>12}{'Markdown':>12}{'~Tokens':>10}{'Saved':>8}"
    )
    separator = "-" * len(header)
    lines = [header, separator]
    for row in rows:
        lines.append(
            f"{row.name:<28}{human_size(row.original_size):>12}"
            f"{human_size(row.markdown_size):>12}"
            + f"{'~' + format(row.tokens, ','):>10}"
            + f"{f'{row.saved_ratio:.1f}%':>8}"
        )
    return "\n".join(lines)
```
