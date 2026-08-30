"""Tests for the integration bridge (export bundles and transports)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from doc2md.core.bridge import (
    MANIFEST_NAME,
    SCHEMA_VERSION,
    BridgeDocument,
    BridgeError,
    BridgePayload,
    FileDropTransport,
    HttpTransport,
    payload_from_results,
    safe_stem,
    write_bundle,
)
from doc2md.core.converter import ConversionResult


def doc(name="รายงาน", markdown="# รายงาน\n\nเนื้อหา\n") -> BridgeDocument:
    return BridgeDocument(name=name, markdown=markdown, source=f"C:/tmp/{name}.pdf", kind="pdf")


# --- documents ---------------------------------------------------------------


def test_document_hash_matches_the_markdown_bytes():
    document = doc()

    assert document.sha256 == hashlib.sha256(document.markdown.encode("utf-8")).hexdigest()


def test_document_dict_carries_everything_the_receiver_needs():
    payload = doc().to_dict()

    assert payload["file"] == "รายงาน.md"
    assert payload["kind"] == "pdf"
    assert payload["chars"] > 0
    assert len(payload["sha256"]) == 64


# --- manifests ---------------------------------------------------------------


def test_manifest_declares_schema_producer_and_counts():
    manifest = BridgePayload(documents=[doc("a"), doc("b")]).to_manifest()

    assert manifest["schema"] == SCHEMA_VERSION
    assert manifest["producer"] == "doc2md"
    assert manifest["target"] == "mediplex-ai-sandbox"
    assert manifest["document_count"] == 2
    assert len(manifest["documents"]) == 2


def test_manifest_json_keeps_thai_readable():
    text = BridgePayload(documents=[doc()]).to_json()

    assert "รายงาน" in text
    assert json.loads(text)["document_count"] == 1


def test_created_at_is_filled_in_automatically():
    assert BridgePayload().created_at


# --- building from conversion results ----------------------------------------


def test_failed_conversions_are_not_forwarded():
    results = [
        ConversionResult(source=Path("ok.pdf"), success=True, markdown="# ok", engine="pdf", kind="pdf"),
        ConversionResult(source=Path("bad.pdf"), success=False, error="boom", kind="pdf"),
        ConversionResult(source=Path("empty.pdf"), success=True, markdown="   ", kind="pdf"),
    ]

    payload = payload_from_results(results)

    assert [d.name for d in payload.documents] == ["ok"]


# --- filenames ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("รายงานประจำปี", "รายงานประจำปี"),
        ("a/b\\c", "a_b_c"),
        ('bad:name?"', "bad_name__"),
        ("   ", "document"),
        ("trailing...", "trailing"),
    ],
)
def test_safe_stem(raw, expected):
    assert safe_stem(raw) == expected


def test_reserved_device_names_are_prefixed():
    assert safe_stem("CON") == "_CON"
    assert safe_stem("com1.txt") == "_com1.txt"


def test_very_long_names_are_truncated():
    assert len(safe_stem("ก" * 400)) == 120


# --- bundles -----------------------------------------------------------------


def test_write_bundle_writes_files_and_a_manifest(tmp_path):
    payload = BridgePayload(documents=[doc("รายงาน"), doc("summary", "# Summary\n")])

    manifest_path = write_bundle(payload, tmp_path / "bundle")

    assert manifest_path.name == MANIFEST_NAME
    assert (tmp_path / "bundle" / "รายงาน.md").read_text(encoding="utf-8").startswith("# รายงาน")
    assert (tmp_path / "bundle" / "summary.md").is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {entry["file"] for entry in manifest["documents"]} == {"รายงาน.md", "summary.md"}


def test_bundle_filenames_never_collide(tmp_path):
    payload = BridgePayload(documents=[doc("same"), doc("same", "# other\n")])

    write_bundle(payload, tmp_path / "bundle")

    written = sorted(p.name for p in (tmp_path / "bundle").glob("*.md"))
    assert written == ["same-1.md", "same.md"]


def test_manifest_hash_matches_the_written_file(tmp_path):
    payload = BridgePayload(documents=[doc()])

    manifest_path = write_bundle(payload, tmp_path / "bundle")

    entry = json.loads(manifest_path.read_text(encoding="utf-8"))["documents"][0]
    written = (tmp_path / "bundle" / entry["file"]).read_bytes()
    assert hashlib.sha256(written).hexdigest() == entry["sha256"]


def test_empty_payload_is_refused(tmp_path):
    with pytest.raises(BridgeError, match="nothing to export"):
        write_bundle(BridgePayload(), tmp_path / "bundle")


# --- transports --------------------------------------------------------------


def test_file_drop_transport_creates_a_timestamped_bundle(tmp_path):
    inbox = tmp_path / "inbox"

    message = FileDropTransport(inbox).send(BridgePayload(documents=[doc()]))

    bundles = list(inbox.iterdir())
    assert len(bundles) == 1
    assert bundles[0].name.startswith("doc2md-")
    assert (bundles[0] / MANIFEST_NAME).is_file()
    assert "1 document" in message


def test_http_transport_rejects_a_non_http_endpoint():
    for endpoint in ("", "ftp://host/x", "file:///c:/x", "not a url"):
        with pytest.raises(BridgeError, match="invalid bridge endpoint"):
            HttpTransport(endpoint)


def test_http_transport_posts_json_with_the_bearer_token(monkeypatch):
    import urllib.request

    captured = {}

    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["headers"] = dict(request.header_items())
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    transport = HttpTransport("https://sandbox.invalid/ingest", token="secret")

    message = transport.send(BridgePayload(documents=[doc()]))

    assert captured["url"] == "https://sandbox.invalid/ingest"
    assert captured["body"]["document_count"] == 1
    assert "รายงาน" in captured["body"]["contents"]
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert "HTTP 202" in message


def test_http_transport_wraps_network_errors(monkeypatch):
    import urllib.error
    import urllib.request

    def fail(_request, timeout=None):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(urllib.request, "urlopen", fail)

    with pytest.raises(BridgeError, match="unreachable"):
        HttpTransport("https://sandbox.invalid/ingest").send(
            BridgePayload(documents=[doc()])
        )


def test_http_transport_refuses_an_empty_payload():
    with pytest.raises(BridgeError, match="nothing to send"):
        HttpTransport("https://sandbox.invalid/ingest").send(BridgePayload())
