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
