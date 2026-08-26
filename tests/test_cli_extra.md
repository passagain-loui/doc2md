# test_cli_extra.py

```python
import sys

from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


def test_directory_scan_with_mixed_files(tmp_path):
    source_dir = tmp_path / "docs_in"
    (source_dir / "nested").mkdir(parents=True)
    (source_dir / "a.txt").write_text("alpha", encoding="utf-8")
    (source_dir / "nested" / "b.log").write_text("beta log", encoding="utf-8")
    (source_dir / "skipme.bin").write_bytes(bytes(range(256)) * 4)

    out = tmp_path / "md_out"
    result = runner.invoke(app, ["convert", str(source_dir), "-o", str(out)])
    assert result.exit_code == 0
    names = {p.name for p in out.glob("*.md")}
    assert names == {"a.md", "b.md"}
    assert (out / "a.md").read_text(encoding="utf-8").strip() != ""


def test_glob_no_match_and_empty_dir_exit_two(tmp_path):
    result = runner.invoke(app, ["convert", str(tmp_path / "none*.xyz")])
    assert result.exit_code == 2

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    result2 = runner.invoke(app, ["convert", str(empty_dir)])
    assert result2.exit_code == 2
    assert "No input files found" in result2.output


def test_rich_importerror_falls_back_to_plain_progress(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "rich.progress", None)
    p = tmp_path / "plain.txt"
    p.write_text("no rich here", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "--stdout"])
    assert result.exit_code == 0
    assert "no rich here" in result.output


def test_mixed_batch_summary_yellow_and_ignore_errors(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("fine content", encoding="utf-8")
    bad = tmp_path / "bad.bin"
    bad.write_bytes(bytes(range(256)) * 8)
    result = runner.invoke(app, ["convert", str(good), str(bad)])
    assert result.exit_code == 1
    assert "1 failed" in result.output
    result_ok = runner.invoke(
        app, ["convert", str(good), str(bad), "--ignore-errors"]
    )
    assert result_ok.exit_code == 0
```
