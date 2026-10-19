"""Shrink an Office-written .doc/.ppt to the streams the engines read.

Word and PowerPoint add a thumbnail, summary properties (author, last-saved-by
- the machine owner's name) and other streams nothing here uses. This copies
only the named streams, byte for byte, into a fresh minimal OLE container (the
writer the test builders use). The fixture stays small and anonymous while the
record structure is exactly what Office produced.

Word also writes the author's name into the revision-author table inside the
``1Table`` stream; ``--scrub OLD=NEW`` swaps such a name for a made-up one of
the same length (both as UTF-16 and as 8-bit text) so nothing shifts.

Usage (from the repo root):
    python tests/fixtures/make_legacy_fixtures/repack_ole.py in.doc out.doc WordDocument 1Table --scrub "Real Name.=Test Author"
    python tests/fixtures/make_legacy_fixtures/repack_ole.py in.ppt out.ppt "Current User" "PowerPoint Document"
"""

from __future__ import annotations

import sys
from pathlib import Path

import olefile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.legacy_builders import build_cfb  # noqa: E402


def main(argv: list[str]) -> None:
    source, target, *rest = argv
    scrubs: list[tuple[str, str]] = []
    names: list[str] = []
    while rest:
        item = rest.pop(0)
        if item == "--scrub":
            old, new = rest.pop(0).split("=", 1)
            if len(old) != len(new):
                raise SystemExit("--scrub OLD=NEW needs two strings of the same length")
            scrubs.append((old, new))
        else:
            names.append(item)
    ole = olefile.OleFileIO(source)
    try:
        streams = {name: ole.openstream(name).read() for name in names}
    finally:
        ole.close()
    for name, data in streams.items():
        for old, new in scrubs:
            data = data.replace(old.encode("utf-16-le"), new.encode("utf-16-le"))
            data = data.replace(old.encode("cp1252"), new.encode("cp1252"))
        streams[name] = data
    Path(target).write_bytes(build_cfb(streams))


if __name__ == "__main__":
    main(sys.argv[1:])
