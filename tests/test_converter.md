# test_converter.py

```python
import pytest

from doc2md.core.converter import Converter, _run_in_process, _run_in_thread
from doc2md.core.errors import ConversionError, ConversionTimeoutError

PAYLOAD_TARGET = ("tests.helpers", "slow_worker")


def test_success_result_metadata(simple_pdf):
    result = Converter().convert_file(simple_pdf)
    assert result.success
    assert result.engine == "pdf"
    assert "Hello doc2md from PDF" in result.markdown
    assert result.token_estimate > 0
    assert result.duration_s >= 0


def test_missing_file_returns_failed_result(tmp_path):
    result = Converter().convert_file(tmp_path / "ghost.pdf")
    assert not result.success
    assert "File not found" in result.error


def test_unknown_type_returns_failed_result(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(bytes(range(256)) * 8)
    result = Converter().convert_file(p)
    assert not result.success
    assert "Unrecognized file type" in result.error


def test_strict_mode_raises(simple_pdf):
    with pytest.raises(ConversionError):
        Converter().convert_file("Z:/definitely/missing.pdf", strict=True)


def test_corrupted_pdf_isolated_failure(tmp_path):
    p = tmp_path / "corrupt.pdf"
    p.write_bytes(b"%PDF-1.7 broken beyond repair \x00\xff\xfe" * 64)
    result = Converter().convert_file(p)
    assert not result.success
    assert "Corrupted" in (result.error or "")


def test_thread_watchdog_times_out(tmp_path):
    payload = {
        "engine": "stub",
        "source": str(tmp_path / "x.txt"),
        "options": {"sleep": 30},
        "target": PAYLOAD_TARGET,
    }
    started = __import__("time").monotonic()
    with pytest.raises(ConversionTimeoutError):
        _run_in_thread(payload, timeout=0.4)
    assert __import__("time").monotonic() - started < 10


@pytest.mark.timeout(15)
def test_process_watchdog_terminates_hung_worker(tmp_path):
    payload = {
        "engine": "stub",
        "source": str(tmp_path / "x.txt"),
        "options": {"sleep": 60},
        "target": PAYLOAD_TARGET,
    }
    started = __import__("time").monotonic()
    with pytest.raises(ConversionTimeoutError):
        _run_in_process(payload, timeout=1.0)
    elapsed = __import__("time").monotonic() - started
    assert elapsed < 10


def test_batch_conversion_mixed_results(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("hello world", encoding="utf-8")
    bad = tmp_path / "bad.bin"
    bad.write_bytes(bytes(range(256)) * 8)
    results = Converter().convert_many([good, bad])
    assert [r.success for r in results] == [True, False]
    assert "hello world" in results[0].markdown
```
