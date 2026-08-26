import sys
from pathlib import Path

import pytest

from doc2md.core.config import DEFAULTS, find_config_file, load_config


def _write_toml(directory: Path, body: str) -> Path:
    path = directory / "doc2md.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_defaults_when_no_config(tmp_path):
    cfg = load_config([tmp_path])
    assert cfg == DEFAULTS
    assert find_config_file([tmp_path]) is None


def test_config_values_override_defaults(tmp_path):
    _write_toml(
        tmp_path,
        'default_copy = true\nstats = true\nchunk = 800\ntimeout = 30.5\nmax_rows = 500\nocr_enabled = false\n',
    )
    cfg = load_config([tmp_path])
    assert cfg["default_copy"] is True
    assert cfg["stats"] is True
    assert cfg["chunk"] == 800
    assert cfg["timeout"] == 30.5
    assert cfg["max_rows"] == 500
    assert cfg["ocr_enabled"] is False


def test_unknown_keys_and_nulls_ignored(tmp_path):
    _write_toml(tmp_path, 'unknown_key = "x"\nstats = true\nchunk = -5\ntimeout = "bad"\n')
    cfg = load_config([tmp_path])
    assert "unknown_key" not in cfg
    assert cfg["stats"] is True
    assert cfg["chunk"] == 1
    assert cfg["timeout"] == DEFAULTS["timeout"]


def test_malformed_toml_falls_back_to_defaults(tmp_path):
    _write_toml(tmp_path, "this is [ not valid toml {{{")
    cfg = load_config([tmp_path])
    assert cfg == DEFAULTS


def test_cwd_wins_over_home(tmp_path):
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    _write_toml(home, "default_copy = false\n")
    _write_toml(cwd, "default_copy = true\n")
    cfg = load_config([cwd, home])
    assert cfg["default_copy"] is True
    assert find_config_file([cwd, home]) == cwd / "doc2md.toml"


def test_real_tomllib_parses_types(tmp_path):
    pytest.importorskip("tomllib", minversion=None) if sys.version_info >= (3, 11) else None
    if sys.version_info < (3, 11):
        pytest.skip("tomllib requires Python 3.11+")
    _write_toml(tmp_path, "max_rows = 1234\ndefault_copy = true\n")
    cfg = load_config([tmp_path])
    assert cfg["max_rows"] == 1234 and cfg["default_copy"] is True
