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


def test_to_manifest_default_filenames_are_unique_for_duplicate_names():
    """Bug: calling to_manifest() directly (not through write_bundle()) with
    two same-named documents produced ['same.md', 'same.md'] - a manifest
    that cannot possibly match two distinct files on disk. The default path
    must dedupe exactly like write_bundle() does."""
    payload = BridgePayload(
        documents=[
            doc("same", "# first\n\nfirst body\n"),
            doc("same", "# second\n\nsecond body\n"),
        ]
    )

    manifest = payload.to_manifest()
    files = [entry["file"] for entry in manifest["documents"]]

    assert len(files) == len(set(files)), f"duplicate filenames in manifest: {files}"
    assert sorted(files) == ["same-1.md", "same.md"]


def test_to_manifest_default_filenames_have_correct_hashes_per_document():
    """Each manifest entry's sha256 must match ITS OWN document's markdown,
    not another document that happens to share a name."""
    payload = BridgePayload(
        documents=[
            doc("same", "# first\n\nfirst body\n"),
            doc("same", "# second\n\nsecond body\n"),
        ]
    )

    manifest = payload.to_manifest()
    by_file = {e["file"]: e for e in manifest["documents"]}

    assert hashlib.sha256("# first\n\nfirst body\n".encode("utf-8")).hexdigest() in {
        e["sha256"] for e in by_file.values()
    }
    assert hashlib.sha256("# second\n\nsecond body\n".encode("utf-8")).hexdigest() in {
        e["sha256"] for e in by_file.values()
    }
    # The two hashes must be distinct (they are different content).
    hashes = [e["sha256"] for e in by_file.values()]
    assert len(set(hashes)) == 2


def test_to_json_default_path_also_dedupes_duplicate_names():
    payload = BridgePayload(documents=[doc("same"), doc("same", "# other\n")])

    text = payload.to_json()
    parsed = json.loads(text)
    files = [entry["file"] for entry in parsed["documents"]]

    assert sorted(files) == ["same-1.md", "same.md"]


def test_to_manifest_rejects_mismatched_filenames_length():
    payload = BridgePayload(documents=[doc("a"), doc("b")])

    with pytest.raises(ValueError, match="entries but there are"):
        payload.to_manifest(filenames=["only-one.md"])


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


def test_warning_results_are_excluded_from_bridge_by_default():
    """Bug #5: OCR unavailable/disabled/no-text is metadata, not a genuine
    read of the document - it must not be silently forwarded to the Sandbox
    as if it were ordinary content."""
    results = [
        ConversionResult(source=Path("clean.pdf"), success=True, markdown="# clean\n\nreal text", kind="pdf"),
        ConversionResult(
            source=Path("scan.pdf"), success=True, markdown="# scan\n\n> no text",
            kind="pdf", warning="OCR unavailable: no backend",
        ),
    ]

    payload = payload_from_results(results)

    assert [d.name for d in payload.documents] == ["clean"]


def test_warning_results_can_be_explicitly_included_and_carry_the_warning():
    results = [
        ConversionResult(
            source=Path("scan.pdf"), success=True, markdown="# scan\n\n> no text",
            kind="pdf", warning="OCR unavailable: no backend",
        ),
    ]

    payload = payload_from_results(results, include_warnings=True)

    assert [d.name for d in payload.documents] == ["scan"]
    assert payload.documents[0].warning == "OCR unavailable: no backend"
    manifest_entry = payload.to_manifest()["documents"][0]
    assert manifest_entry["warning"] == "OCR unavailable: no backend"


def test_clean_result_manifest_entry_omits_warning_key_entirely():
    """Schema compatibility: a document without a warning must produce the
    exact same key set as the original 1.0 schema - the warning key must be
    ABSENT, not present-and-null, so SCHEMA_VERSION did not need to change
    for the common case."""
    results = [
        ConversionResult(source=Path("clean.pdf"), success=True, markdown="# clean\n\nreal text", kind="pdf"),
    ]

    payload = payload_from_results(results)
    entry = payload.to_manifest()["documents"][0]

    assert "warning" not in entry


def test_document_entry_shape_unchanged_for_documents_without_warnings():
    """The exact key set for a clean document must match the original
    (pre-warning-field) 1.0 shape - no unannounced schema drift."""
    original_1_0_keys = {
        "name", "file", "source", "engine", "kind",
        "sha256", "chars", "tokens", "duration_s",
    }
    payload = BridgePayload(documents=[doc()])
    entry = payload.to_manifest()["documents"][0]

    assert set(entry.keys()) == original_1_0_keys
    assert SCHEMA_VERSION == "1.1"


def test_warning_key_only_appears_on_documents_that_actually_carry_one():
    payload = BridgePayload(
        documents=[
            doc("clean", "# clean\n"),
            BridgeDocument(
                name="scan", markdown="# scan\n", source="scan.pdf",
                kind="pdf", warning="OCR unavailable: no backend",
            ),
        ]
    )
    manifest = payload.to_manifest()
    by_name = {e["name"]: e for e in manifest["documents"]}

    assert "warning" not in by_name["clean"]
    assert by_name["scan"]["warning"] == "OCR unavailable: no backend"


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


def test_duplicate_named_documents_each_get_a_correct_manifest_entry(tmp_path):
    """Bug: manifest filenames were built with a dict keyed by document.name,
    so two documents sharing a stem collapsed onto one manifest entry - the
    .md files on disk were correctly disambiguated (same.md, same-1.md) but
    the manifest reported the wrong filename (and thus the wrong hash lookup)
    for one of them. Every document's manifest entry must name its own real
    file and hash, regardless of name collisions."""
    payload = BridgePayload(
        documents=[
            doc("same", "# first document\n\nfirst body\n"),
            doc("same", "# second document\n\nsecond body\n"),
        ]
    )

    manifest_path = write_bundle(payload, tmp_path / "bundle")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["document_count"] == 2
    entries = manifest["documents"]
    assert len(entries) == 2
    assert {e["file"] for e in entries} == {"same.md", "same-1.md"}

    # Every entry's filename and hash must match the ACTUAL file on disk -
    # not another document's file that happens to share the same name.
    for entry in entries:
        written = (tmp_path / "bundle" / entry["file"]).read_bytes()
        assert hashlib.sha256(written).hexdigest() == entry["sha256"], (
            f"manifest hash for {entry['file']} does not match the file on disk"
        )

    # The two entries must correspond to genuinely different content.
    bodies = {
        (tmp_path / "bundle" / e["file"]).read_text(encoding="utf-8") for e in entries
    }
    assert len(bodies) == 2
    assert any("first body" in b for b in bodies)
    assert any("second body" in b for b in bodies)


def test_existing_manifest_is_never_overwritten(tmp_path):
    bundle_dir = tmp_path / "bundle"
    write_bundle(BridgePayload(documents=[doc("a", "# a\n")]), bundle_dir)
    original = (bundle_dir / MANIFEST_NAME).read_text(encoding="utf-8")

    with pytest.raises(BridgeError, match="refusing to overwrite"):
        write_bundle(BridgePayload(documents=[doc("b", "# b\n")]), bundle_dir)

    assert (bundle_dir / MANIFEST_NAME).read_text(encoding="utf-8") == original


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


def test_rapid_sends_within_the_same_second_get_separate_bundles(tmp_path):
    """Bug: the bundle directory name used second-resolution timestamps, so
    two sends inside the same wall-clock second produced the same directory
    and the second send silently overwrote the first bundle's manifest."""
    inbox = tmp_path / "inbox"
    transport = FileDropTransport(inbox)

    first = transport.send(BridgePayload(documents=[doc("first", "# first\n")]))
    second = transport.send(BridgePayload(documents=[doc("second", "# second\n")]))

    bundles = sorted(p for p in inbox.iterdir() if p.is_dir())
    assert len(bundles) == 2, "rapid sends must not collide on one bundle directory"

    manifests = [json.loads((b / MANIFEST_NAME).read_text(encoding="utf-8")) for b in bundles]
    names = {m["documents"][0]["file"] for m in manifests}
    assert names == {"first.md", "second.md"}, "both bundles must survive intact"
    assert first != second


def test_concurrent_sends_from_multiple_threads_never_collide(tmp_path):
    """Sends racing from different threads (as the GUI's worker thread and a
    hypothetical second trigger might) must still each get their own
    directory - no lost bundle, no torn manifest."""
    import threading

    inbox = tmp_path / "inbox"
    transport = FileDropTransport(inbox)
    errors: list[BaseException] = []

    def _send(index: int) -> None:
        try:
            transport.send(BridgePayload(documents=[doc(f"doc{index}", f"# doc {index}\n")]))
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_send, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent sends raised: {errors}"
    bundles = [p for p in inbox.iterdir() if p.is_dir()]
    assert len(bundles) == 8, "every concurrent send must produce its own bundle"
    for bundle in bundles:
        assert (bundle / MANIFEST_NAME).is_file()


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
    assert "รายงาน.md" in captured["body"]["contents"]
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


def test_to_manifest_rejects_a_dict_of_filenames():
    payload = BridgePayload(documents=[doc()])

    with pytest.raises(TypeError):
        payload.to_manifest({"a": "a.md"})
