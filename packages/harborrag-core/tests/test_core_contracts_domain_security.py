from __future__ import annotations

import pytest
from harborrag_core.contracts.events import HarborEvent
from harborrag_core.contracts.ids import HarborId, stable_hash_id
from harborrag_core.contracts.result import Result
from harborrag_core.domain.document import HarborDocument
from harborrag_core.domain.element import DocumentElement
from harborrag_core.domain.graph import GraphHint
from harborrag_core.domain.metadata import DocumentMetadata
from harborrag_core.domain.parsed_document import ParsedDocument, ParseQuality
from harborrag_core.domain.provenance import DocumentProvenance
from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.retrieval import RetrievalQuery, RetrievalResult
from harborrag_core.domain.source import SourceRecord
from harborrag_core.observability.events import InMemoryEventBus
from harborrag_core.observability.metrics import InMemoryMetrics
from harborrag_core.security.redaction import redact_secrets
from harborrag_core.security.url_policy import UrlPolicy


def test_ids_and_result_success_failure_edges():
    hid = HarborId("harbor://unit/doc")
    assert str(hid) == "harbor://unit/doc"
    assert stable_hash_id("/unit/", "doc", 1) == stable_hash_id("unit", "doc", 1)
    with pytest.raises(ValueError):
        HarborId("bad://unit/doc")
    with pytest.raises(ValueError):
        HarborId("harbor://unit/bad id")
    ok = Result.success("value")
    assert ok.ok is True
    assert ok.unwrap() == "value"
    fail = Result.failure(RuntimeError("boom"))
    assert fail.ok is False
    with pytest.raises(RuntimeError):
        fail.unwrap()
    with pytest.raises(ValueError):
        Result.success(None).unwrap()


def test_domain_helpers_and_dataclasses():
    element = DocumentElement("e1", "paragraph", markdown="**hello**")
    assert element.display_text() == "**hello**"
    assert DocumentElement("e2", "paragraph").display_text() == ""
    quality = ParseQuality(0.5, warnings=["warn"])
    assert quality.acceptable is True
    assert ParseQuality(0.49).acceptable is False
    parsed = ParsedDocument("text", [element], "mock", raw={"x": 1})
    assert parsed.raw["x"] == 1
    metadata = DocumentMetadata("source-1", "mock", author="alice", project="HARBOR")
    assert metadata.graph_properties()["project"] == "HARBOR"
    hint = GraphHint("doc", "mentions", "user:alice", "Document", "User")
    assert hint.as_edge()["relation"] == "mentions"
    doc = HarborDocument(
        id="doc",
        source="memory://doc",
        source_type="mock",
        content_type="text/plain",
        title="Doc",
        text="hello",
        metadata=metadata,
        provenance=DocumentProvenance("mock_connector", "mock_parser"),
        elements=[element],
        graph_hints=[hint],
    )
    assert doc.vector_payload()["title"] == "Doc"
    raw = RawDocument("raw", "memory://raw", b"hello", "text/plain")
    assert raw.text() == "hello"
    assert RawDocument("raw2", "memory://raw2", "hi", "text/plain").text() == "hi"
    assert SourceRecord("src", "kind", "locator").id == "src"
    assert RetrievalQuery("q", top_k=2).top_k == 2
    assert RetrievalResult("id", "text", 1.0).score == 1.0


def test_security_observability_helpers():
    redacted = redact_secrets("api_key=abc token:xyz password=hunter2")
    assert "abc" not in redacted and "xyz" not in redacted and "hunter2" not in redacted
    UrlPolicy().validate("https://example.com")
    with pytest.raises(Exception):
        UrlPolicy().validate("ftp://example.com")
    with pytest.raises(Exception):
        UrlPolicy(denied_hosts={"blocked.local"}).validate("https://blocked.local/a")
    bus = InMemoryEventBus()
    bus.publish(HarborEvent(name="event", trace_id="trace-1", payload={"x": 1}))
    assert bus.events[0].name == "event"
    metrics = InMemoryMetrics()
    metrics.increment("items", provider="mock")
    metrics.observe("latency", 1.25)
    assert metrics.counters["items{provider=mock}"] == 1
    assert metrics.observations["latency"] == [1.25]
