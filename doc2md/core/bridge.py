"""Integration bridge: hand converted Markdown to downstream tools.

The immediate consumer is the Mediplex AI Sandbox, but nothing here is
Mediplex-specific: a *bundle* is a directory containing the ``.md`` files plus
a ``manifest.json`` describing them, and a *transport* is anything that can
accept that bundle.

Two transports ship with the tool:

``FileDropTransport``
    Writes the bundle into a directory the downstream tool watches. This is
    the default because it needs no credentials, no network, and no service to
    be running - the handoff is a file that either exists or does not.

``HttpTransport``
    POSTs the manifest to an endpoint. It is opt-in and never used unless the
    caller supplies an explicit URL, so converting a document can never make a
    network request as a side effect.

Every payload carries a SHA-256 of the Markdown so the receiving side can
detect truncation or a partially written file instead of ingesting it blindly.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from doc2md import __version__

SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "manifest.json"
PRODUCER = "doc2md"

_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_STEM = 120


class BridgeError(Exception):
    """Raised when a bundle cannot be written or delivered."""


@dataclass(frozen=True)
class BridgeDocument:
    """One converted document as the downstream tool sees it."""

    name: str
    markdown: str
    source: str = ""
    engine: str = ""
    kind: str = ""
    duration_s: float = 0.0

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.markdown.encode("utf-8")).hexdigest()

    @property
    def char_count(self) -> int:
        return len(self.markdown)

    @property
    def token_estimate(self) -> int:
        from doc2md.core.tokens import estimate_tokens

        return estimate_tokens(self.markdown)

    def to_dict(self, *, filename: str | None = None) -> dict:
        return {
            "name": self.name,
            "file": filename or f"{self.name}.md",
            "source": self.source,
            "engine": self.engine,
            "kind": self.kind,
            "sha256": self.sha256,
            "chars": self.char_count,
            "tokens": self.token_estimate,
            "duration_s": round(self.duration_s, 4),
        }


@dataclass
class BridgePayload:
    """A manifest plus the documents it describes."""

    documents: list[BridgeDocument] = field(default_factory=list)
    producer: str = PRODUCER
    target: str = "mediplex-ai-sandbox"
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_manifest(self, filenames: dict[str, str] | None = None) -> dict:
        names = filenames or {}
        return {
            "schema": SCHEMA_VERSION,
            "producer": self.producer,
            "producer_version": __version__,
            "target": self.target,
            "created_at": self.created_at,
            "document_count": len(self.documents),
            "total_tokens": sum(doc.token_estimate for doc in self.documents),
            "documents": [
                doc.to_dict(filename=names.get(doc.name)) for doc in self.documents
            ],
        }

    def to_json(self, filenames: dict[str, str] | None = None, *, indent: int = 2) -> str:
        return json.dumps(self.to_manifest(filenames), ensure_ascii=False, indent=indent)


def safe_stem(name: str) -> str:
    """Return *name* reduced to a filename that Windows will accept.

    Thai characters, spaces and dashes are kept - they are perfectly legal in
    NTFS filenames and mangling them makes the output unrecognizable to the
    person who dropped the file. Only genuinely reserved characters, control
    characters, and the reserved DOS device names are rewritten.
    """
    cleaned = _UNSAFE_NAME_RE.sub("_", unicodedata.normalize("NFC", name)).strip()
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        return "document"
    if cleaned.split(".")[0].upper() in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        cleaned = f"_{cleaned}"
    return cleaned[:_MAX_STEM]


def payload_from_results(results, *, target: str = "mediplex-ai-sandbox") -> BridgePayload:
    """Build a payload from :class:`~doc2md.core.converter.ConversionResult` objects.

    Failed conversions are skipped: the bridge exists to deliver documents, and
    forwarding an error placeholder as if it were content is precisely the
    silent-failure mode this rewrite removes.
    """
    documents = [
        BridgeDocument(
            name=Path(result.source).stem,
            markdown=result.markdown,
            source=str(result.source),
            engine=result.engine or "",
            kind=result.kind,
            duration_s=float(result.duration_s or 0.0),
        )
        for result in results
        if getattr(result, "success", False) and getattr(result, "markdown", "").strip()
    ]
    return BridgePayload(documents=documents, target=target)


def write_bundle(payload: BridgePayload, destination: Path | str) -> Path:
    """Write every document plus ``manifest.json`` into *destination*.

    The manifest is written **last**: a watcher that triggers on the manifest
    therefore never sees a bundle whose ``.md`` files are still being written.
    """
    if not payload.documents:
        raise BridgeError("nothing to export: no successful conversions in this batch")

    target_dir = Path(destination)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BridgeError(f"cannot create bundle directory {target_dir}: {exc}") from exc

    filenames: dict[str, str] = {}
    used: set[str] = set()
    try:
        for document in payload.documents:
            stem = safe_stem(document.name)
            candidate = f"{stem}.md"
            counter = 1
            while candidate.lower() in used:
                candidate = f"{stem}-{counter}.md"
                counter += 1
            used.add(candidate.lower())
            filenames[document.name] = candidate
            (target_dir / candidate).write_text(
                document.markdown, encoding="utf-8", newline="\n"
            )

        manifest_path = target_dir / MANIFEST_NAME
        manifest_path.write_text(
            payload.to_json(filenames), encoding="utf-8", newline="\n"
        )
    except OSError as exc:
        raise BridgeError(f"failed to write bundle into {target_dir}: {exc}") from exc
    return manifest_path


class FileDropTransport:
    """Deliver a bundle by writing it into a watched directory."""

    def __init__(self, inbox: Path | str) -> None:
        self.inbox = Path(inbox)

    def send(self, payload: BridgePayload) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        bundle_dir = self.inbox / f"doc2md-{stamp}"
        manifest = write_bundle(payload, bundle_dir)
        return f"delivered {len(payload.documents)} document(s) to {manifest.parent}"


class HttpTransport:
    """POST the manifest to *endpoint*. Opt-in; requires an explicit URL."""

    def __init__(self, endpoint: str, *, timeout: float = 15.0, token: str | None = None) -> None:
        if not endpoint or not endpoint.lower().startswith(("http://", "https://")):
            raise BridgeError(f"invalid bridge endpoint: {endpoint!r}")
        self.endpoint = endpoint
        self.timeout = float(timeout)
        self.token = token

    def send(self, payload: BridgePayload) -> str:
        import urllib.error
        import urllib.request

        if not payload.documents:
            raise BridgeError("nothing to send: no successful conversions in this batch")

        body = json.dumps(
            {
                **payload.to_manifest(),
                "contents": {
                    doc.name: doc.markdown for doc in payload.documents
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")

        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(
            self.endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = response.status
        except urllib.error.URLError as exc:
            raise BridgeError(f"bridge endpoint unreachable: {exc}") from exc
        except OSError as exc:
            raise BridgeError(f"bridge transport failed: {exc}") from exc
        return f"posted {len(payload.documents)} document(s) to {self.endpoint} (HTTP {status})"
