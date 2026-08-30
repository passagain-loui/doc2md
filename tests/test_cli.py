from typer.testing import CliRunner

from doc2md.cli.main import app

runner = CliRunner()


def test_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "doc2md" in result.output


def test_convert_single_file_stdout(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("just a note", encoding="utf-8")
    result = runner.invoke(app, ["convert", str(p), "--stdout"])
    assert result.exit_code == 0
    assert "```text" in result.output
    assert "just a note" in result.output


def test_convert_batch_to_outdir(tmp_path):
    out = tmp_path / "md_out"
    files = []
    for i in range(3):
        f = tmp_path / f"f{i}.txt"
        f.write_text(f"content {i}", encoding="utf-8")
        files.append(str(f))
    result = runner.invoke(app, ["convert", *files, "-o", str(out)])
    assert result.exit_code == 0
    written = sorted(p.name for p in out.glob("*.md"))
    assert written == ["f0.md", "f1.md", "f2.md"]
    assert "3 converted, 0 failed" in result.output


def test_convert_failure_exit_code(tmp_path):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(bytes(range(256)) * 8)
    result = runner.invoke(app, ["convert", str(bad)])
    assert result.exit_code == 1
    result2 = runner.invoke(app, ["convert", str(bad), "--ignore-errors"])
    assert result2.exit_code == 0


def test_glob_pattern(tmp_path):
    for i in range(2):
        (tmp_path / f"g{i}.log").write_text(f"log line {i}", encoding="utf-8")
    result = runner.invoke(
        app, ["convert", str(tmp_path / "g*.log"), "--stdout", "-q"]
    )
    assert result.exit_code == 0


# --- console encoding --------------------------------------------------------


def test_thai_filename_does_not_crash_a_legacy_codepage_console(tmp_path, monkeypatch):
    """Printing a Thai filename must never abort the run.

    On a stock Windows console stdout is cp874/cp1252, and echoing the progress
    line for a Thai filename raised UnicodeEncodeError *after* the files had
    already been converted - the command failed having done all the work.
    """
    import io
    import sys

    from doc2md.cli.main import configure_stdio

    source = tmp_path / "รายงาน ทดสอบ.txt"
    source.write_text("เนื้อหา", encoding="utf-8")

    legacy = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", legacy)
    configure_stdio()

    print(f"[1/1] OK {source.name}")  # would raise before the reconfigure
    legacy.flush()

    assert legacy.encoding.lower().replace("-", "") == "utf8"


def test_configure_stdio_tolerates_missing_streams(monkeypatch):
    import sys

    from doc2md.cli.main import configure_stdio

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    configure_stdio()  # a --windowed frozen build has no streams at all


def test_cli_converts_a_thai_path_end_to_end(tmp_path):
    folder = tmp_path / "เอกสาร ทดสอบ"
    folder.mkdir()
    source = folder / "รายงาน ประจำปี.txt"
    source.write_text("เนื้อหาภาษาไทย", encoding="utf-8")

    result = runner.invoke(app, ["convert", str(source)])

    assert result.exit_code == 0, result.output
    assert (folder / "รายงาน ประจำปี.md").read_text(encoding="utf-8").count("เนื้อหาภาษาไทย")
