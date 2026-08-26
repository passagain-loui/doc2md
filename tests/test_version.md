# test_version.py

```python
import re
from pathlib import Path

import doc2md


def test_version_matches_pyproject():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert match, "version key missing from pyproject.toml"
    assert doc2md.__version__ == match.group(1)


def test_version_is_semver_and_in_changelog():
    assert re.fullmatch(r"\d+\.\d+\.\d+", doc2md.__version__)
    changelog = (
        Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    ).read_text(encoding="utf-8")
    assert f"[{doc2md.__version__}]" in changelog
```
