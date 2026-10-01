r"""Guard against the documentation-mirror corruption bug (requirement #9).

README.md, CHANGELOG.md, HISTORY.md and CLAUDE.md were each found wrapped as
"# {filename}" followed by a fenced text block containing the original
content - the exact shape produced by doc2md's own code engine fencing an
already-Markdown file. A "documentation mirror" tool re-scanning its own .md
output as input then compounded this every run, nesting arbitrarily deep. The
real fix is in doc2md/engine/code_engine.py (.md is now passed through
unchanged); this test is the regression guard so a reappearance of the
wrapper - from any source - fails CI immediately instead of silently
corrupting the repo again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

ROOT_DOCS = ["README.md", "CHANGELOG.md", "HISTORY.md", "CLAUDE.md"]

# The exact corruption shape: a synthetic "# filename" heading immediately
# followed by an opening fence, i.e. the file's own content was fenced and
# given a duplicate title.
_WRAPPER_HEAD_RE = re.compile(r"^#\s+\S+\.md\s*\n\s*\n`{3,}")


@pytest.mark.parametrize("name", ROOT_DOCS)
def test_root_doc_does_not_start_with_a_filename_heading_and_fence(name):
    path = REPO_ROOT / name
    text = path.read_text(encoding="utf-8")

    assert not _WRAPPER_HEAD_RE.match(text), (
        f"{name} starts with a '# filename' heading followed by a code fence - "
        "this is the documentation-mirror wrapper bug. The file should start "
        "with its own real heading, not be fenced as generic text."
    )


@pytest.mark.parametrize("name", ROOT_DOCS)
def test_root_doc_does_not_end_with_a_closing_fence(name):
    path = REPO_ROOT / name
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines, f"{name} is empty"
    last_nonblank = next((ln for ln in reversed(lines) if ln.strip()), "")
    assert not last_nonblank.strip().startswith("```"), (
        f"{name} ends with a closing code fence - the whole file is wrapped, "
        "which is the documentation-mirror bug."
    )


@pytest.mark.parametrize("name", ROOT_DOCS)
def test_root_doc_first_line_is_a_real_heading_not_the_filename(name):
    path = REPO_ROOT / name
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line != f"# {name}", (
        f"{name}'s first line is a literal '# {name}' filename heading, "
        "which is what the mirror tool synthesizes - not real content."
    )