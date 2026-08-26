"""Optional `doc2md.toml` configuration discovery and merging."""

from __future__ import annotations

import sys
from pathlib import Path

CONFIG_NAME = "doc2md.toml"

DEFAULTS: dict = {
    "default_copy": False,
    "stats": False,
    "chunk": None,
    "timeout": 60.0,
    "max_rows": 10_000,
    "ocr_enabled": True,
}

_INT_KEYS = {"chunk", "max_rows"}
_FLOAT_KEYS = {"timeout"}
_BOOL_KEYS = {"default_copy", "stats", "ocr_enabled"}


class ConfigError(Exception):
    pass


def find_config_file(search_paths=None):
    paths = tuple(search_paths) if search_paths else (Path.cwd(), Path.home())
    for directory in paths:
        candidate = Path(directory) / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(search_paths=None, on_error=None) -> dict:
    """Merge defaults with the first doc2md.toml found (cwd, then home).

    *on_error* receives a message whenever a config file exists but cannot be
    parsed; defaults are used in that case.
    """
    config = dict(DEFAULTS)
    paths = tuple(search_paths) if search_paths else (Path.cwd(), Path.home())
    candidate = find_config_file(paths)
    if candidate is None:
        return _sanitize(config)
    try:
        data = _parse_toml(candidate.read_text(encoding="utf-8"))
    except ConfigError as exc:
        if on_error is not None:
            try:
                on_error(str(exc))
            except Exception:
                pass
        return _sanitize(config)
    for key, value in data.items():
        if key in DEFAULTS and value is not None:
            config[key] = value
    return _sanitize(config)


def _parse_toml(text: str) -> dict:
    if sys.version_info >= (3, 11):
        try:
            import tomllib
        except ImportError:
            tomllib = None
        if tomllib is not None:
            try:
                return tomllib.loads(text)
            except Exception as exc:
                raise ConfigError(f"TOML parse error: {exc}") from exc
    try:
        import tomli

        try:
            return tomli.loads(text)
        except Exception as exc:
            raise ConfigError(f"TOML parse error: {exc}") from exc
    except ImportError:
        pass
    raise RuntimeError("tomllib/tomli unavailable: cannot parse doc2md.toml")


def _sanitize(config: dict) -> dict:
    cleaned = dict(DEFAULTS)
    for key, value in config.items():
        if key not in DEFAULTS or value is None:
            continue
        try:
            if key in _INT_KEYS:
                cleaned[key] = max(1, int(value))
            elif key in _FLOAT_KEYS:
                cleaned[key] = max(0.1, float(value))
            elif key in _BOOL_KEYS:
                cleaned[key] = bool(value)
            else:
                continue
        except (TypeError, ValueError):
            continue
    return cleaned
