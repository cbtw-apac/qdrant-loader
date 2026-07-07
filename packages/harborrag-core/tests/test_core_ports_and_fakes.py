from __future__ import annotations

import pytest
from harborrag_core.contracts.capabilities import CapabilityProfile
from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord
from harborrag_core.execution.budgets import CapabilityBudget
from harborrag_core.execution.context import RequestContext
from harborrag_core.execution.deadlines import Deadline
from harborrag_core.testing.fakes import FakeConnector, FakeParser


def test_capabilities_context_budget_and_deadline():
    profile = CapabilityProfile(sync=True, batch=False)
    profile.require("sync")
    with pytest.raises(ValueError):
        profile.require("missing")
    with pytest.raises(NotImplementedError):
        profile.require("batch")
    context = RequestContext()
    assert context.child().trace_id == context.trace_id
    budget = CapabilityBudget(max_documents=1)
    budget.check_documents(1)
    with pytest.raises(ValueError):
        budget.check_documents(2)
    deadline = Deadline(None)
    assert deadline.remaining() is None
    deadline.check()
    expired = Deadline(0.0)
    with pytest.raises(Exception):
        expired.check()


def test_fake_connector_and_parser_contracts():
    raw = RawDocument("doc", "memory://doc", "hello", "text/plain")
    connector = FakeConnector(documents=[raw])
    record = next(iter(connector.discover()))
    assert isinstance(record, SourceRecord)
    assert connector.load(record).id == "doc"
    with pytest.raises(KeyError):
        connector.load(SourceRecord("missing", "kind", "locator"))
    parsed = FakeParser().parse(raw)
    assert parsed.text == "hello"
    assert parsed.elements[0].type == "paragraph"
