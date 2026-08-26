"""MIME / magic-byte file detection that routes input files to converter engines."""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

MAGIC_LIMIT = 8192


class FileKind(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    PPTX = "pptx"
    HTML = "html"
    EML = "eml"
    IMAGE = "image"
    JSON = "json"
    CODE = "code"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Detection:
    kind: FileKind
    mime: str
    confidence: str

    @property
    def is_known(self) -> bool:
        return self.kind != FileKind.UNKNOWN


EXTENSION_KINDS: dict[str, FileKind] = {
    ".pdf": FileKind.PDF,
    ".docx": FileKind.DOCX,
    ".xlsx": FileKind.XLSX,
    ".xlsm": FileKind.XLSX,
    ".xls": FileKind.XLSX,
    ".csv": FileKind.CSV,
    ".pptx": FileKind.PPTX,
    ".html": FileKind.HTML,
    ".htm": FileKind.HTML,
    ".xhtml": FileKind.HTML,
    ".eml": FileKind.EML,
    ".json": FileKind.JSON,
    ".txt": FileKind.TEXT,
    ".md": FileKind.TEXT,
    ".log": FileKind.TEXT,
}

IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}

CODE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "bash",
    ".bat": "batch",
    ".ps1": "powershell",
    ".sql": "sql",
    ".r": "r",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".xml": "xml",
    ".css": "css",
}

MIME_BY_KIND: dict[FileKind, str] = {
    FileKind.PDF: "application/pdf",
    FileKind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    FileKind.CSV: "text/csv",
    FileKind.PPTX: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    FileKind.HTML: "text/html",
    FileKind.EML: "message/rfc822",
    FileKind.IMAGE: "application/octet-stream",
    FileKind.JSON: "application/json",
    FileKind.CODE: "text/x-code",
    FileKind.TEXT: "text/plain",
    FileKind.UNKNOWN: "application/octet-stream",
}

_RFC822_HEADERS = ("from:", "to:", "subject:", "date:", "message-id:", "mime-version:")


def detect(path: Path | str) -> Detection:
    """Detect the file kind using magic bytes, then content heuristics, then extension."""
    p = Path(path)
    if not p.is_file():
        return Detection(FileKind.UNKNOWN, MIME_BY_KIND[FileKind.UNKNOWN], "missing")

    with open(p, "rb") as fh:
        head = fh.read(MAGIC_LIMIT)

    magic = _detect_magic(p, head)
    if magic is not None:
        return magic

    heuristic = _detect_content(head)
    if heuristic is not None:
        return heuristic

    by_ext = _detect_extension(p)
    if by_ext is not None:
        return by_ext

    return Detection(FileKind.UNKNOWN, MIME_BY_KIND[FileKind.UNKNOWN], "fallback")


def _detect_magic(p: Path, head: bytes) -> Detection | None:
    if head.startswith(b"%PDF-"):
        return Detection(FileKind.PDF, MIME_BY_KIND[FileKind.PDF], "magic")
    if head.startswith(b"PK\x03\x04"):
        kind = _sniff_ooxml_zip(p)
        if kind is not None:
            return Detection(kind, MIME_BY_KIND[kind], "magic-zip")
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Detection(FileKind.IMAGE, "image/png", "magic")
    if head.startswith(b"\xff\xd8\xff"):
        return Detection(FileKind.IMAGE, "image/jpeg", "magic")
    if head.startswith((b"GIF87a", b"GIF89a")):
        return Detection(FileKind.IMAGE, "image/gif", "magic")
    if head.startswith(b"BM"):
        return Detection(FileKind.IMAGE, "image/bmp", "magic")
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return Detection(FileKind.IMAGE, "image/tiff", "magic")
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Detection(FileKind.IMAGE, "image/webp", "magic")
    return None


def _sniff_ooxml_zip(p: Path) -> FileKind | None:
    try:
        with zipfile.ZipFile(p) as zf:
            names = zf.namelist()
    except Exception:
        return None
    if any(n.startswith("word/") for n in names):
        return FileKind.DOCX
    if any(n.startswith("xl/") for n in names):
        return FileKind.XLSX
    if any(n.startswith("ppt/") for n in names):
        return FileKind.PPTX
    return None


def _detect_content(head: bytes) -> Detection | None:
    text = _try_decode_head(head)
    if text is None:
        return None
    lowered = text.lstrip().lower()
    if "<!doctype html" in lowered or "<html" in lowered:
        return Detection(FileKind.HTML, MIME_BY_KIND[FileKind.HTML], "heuristic")
    probe_lines = [ln.strip().lower() for ln in text.splitlines()[:40]]
    header_hits = sum(1 for ln in probe_lines if ln.startswith(_RFC822_HEADERS))
    if header_hits >= 2:
        return Detection(FileKind.EML, MIME_BY_KIND[FileKind.EML], "heuristic")
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped[:1] in ("{", "["):
        try:
            json.loads(stripped)
            return Detection(FileKind.JSON, MIME_BY_KIND[FileKind.JSON], "heuristic")
        except (ValueError, RecursionError):
            pass
    if text.startswith("#!"):
        return Detection(FileKind.CODE, MIME_BY_KIND[FileKind.CODE], "heuristic")
    return None


def _try_decode_head(head: bytes) -> str | None:
    try:
        return head.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(head).best()
        return str(best) if best is not None else None
    except ImportError:
        try:
            return head.decode("latin-1")
        except UnicodeDecodeError:
            return None


def _detect_extension(p: Path) -> Detection | None:
    suffix = p.suffix.lower()
    if suffix in EXTENSION_KINDS:
        kind = EXTENSION_KINDS[suffix]
        return Detection(kind, MIME_BY_KIND[kind], "extension")
    if suffix in IMAGE_EXTENSIONS:
        return Detection(FileKind.IMAGE, IMAGE_EXTENSIONS[suffix], "extension")
    if suffix in CODE_EXTENSIONS:
        return Detection(FileKind.CODE, MIME_BY_KIND[FileKind.CODE], "extension")
    return None


def guess_language(path: Path | str) -> str:
    """Best-effort programming-language guess used by the code engine."""
    suffix = Path(path).suffix.lower()
    return CODE_EXTENSIONS.get(suffix, "")
