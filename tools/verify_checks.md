# verify_checks.py

```python
"""Static consistency checks invoked by tools/verify.ps1.

Kept as a real file rather than inline `python -c` here-strings: passing
multi-line Python through PowerShell mangles quoting and `$` expansion, which
previously made the checks fail with SyntaxError instead of testing anything.

Usage: python tools/verify_checks.py <check-name>
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# sys.path[0] is tools/ when this script runs, so the package next to it is not
# importable without help.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def check_version() -> int:
    """The version in pyproject.toml must match doc2md.__version__."""
    import doc2md

    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if not match:
        print("could not read version from pyproject.toml")
        return 1

    declared = match.group(1)
    if declared != doc2md.__version__:
        print(f"version mismatch: pyproject={declared} __init__={doc2md.__version__}")
        return 1

    print(f"doc2md {doc2md.__version__}")
    return 0


def check_imports() -> int:
    """Every module in the package must import cleanly."""
    import doc2md

    failed: list[str] = []
    for module in pkgutil.walk_packages(doc2md.__path__, "doc2md."):
        try:
            importlib.import_module(module.name)
        except Exception:
            failed.append(module.name)
            traceback.print_exc()

    if failed:
        print(f"failed to import: {failed}")
        return 1

    print("all modules imported cleanly")
    return 0


def check_docs() -> int:
    """CHANGELOG.md and HISTORY.md must carry an entry for the current version."""
    import doc2md

    marker = f"[{doc2md.__version__}]"
    missing = [
        name
        for name in ("CHANGELOG.md", "HISTORY.md")
        if marker not in (REPO_ROOT / name).read_text(encoding="utf-8")
    ]

    if missing:
        print(f"{marker} missing from: {', '.join(missing)}")
        return 1

    print(f"{marker} documented in CHANGELOG.md and HISTORY.md")
    return 0


CHECKS = {
    "version": check_version,
    "imports": check_imports,
    "docs": check_docs,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in CHECKS:
        print(f"usage: python tools/verify_checks.py [{'|'.join(CHECKS)}]")
        return 2
    return CHECKS[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
```
