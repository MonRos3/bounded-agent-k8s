"""Auditor: trace generation and event recording via an injected AuditSink."""

from __future__ import annotations

from safety_core.audit import AuditEvent, AuditSink, Auditor
from safety_core.types import Action, Decision, Tier


class FakeAuditSink(AuditSink):
    """Collects emitted events in-memory for inspection."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _action() -> Action:
    return Action(tool="scale_deployment", args={"target_replicas": 5}, rationale="")


def _decision() -> Decision:
    return Decision(tier=Tier.AUTO, reason="ok", reversible=True, scope="scale_deployment", rollback=None, success=None)


def test_new_trace_returns_nonempty_id():
    auditor = Auditor(FakeAuditSink())
    assert auditor.new_trace()


def test_new_trace_returns_unique_id_per_call():
    auditor = Auditor(FakeAuditSink())
    assert auditor.new_trace() != auditor.new_trace()


def test_record_builds_and_emits_correctly_shaped_event():
    sink = FakeAuditSink()
    auditor = Auditor(sink)
    action = _action()
    decision = _decision()

    auditor.record("classified", trace_id="trace-1", action=action, decision=decision, detail={"note": "x"})

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.trace_id == "trace-1"
    assert event.step == "classified"
    assert event.action == action
    assert event.decision == decision
    assert event.detail == {"note": "x"}
    assert event.timestamp


def test_record_defaults_detail_to_empty_dict():
    sink = FakeAuditSink()
    auditor = Auditor(sink)

    auditor.record("classified", trace_id="trace-1", action=_action(), decision=_decision())

    assert sink.events[0].detail == {}


def test_multiple_records_under_one_trace_id_all_carry_it():
    sink = FakeAuditSink()
    auditor = Auditor(sink)
    trace_id = auditor.new_trace()

    auditor.record("proposed", trace_id=trace_id, action=_action(), decision=_decision())
    auditor.record("classified", trace_id=trace_id, action=_action(), decision=_decision())

    assert [e.trace_id for e in sink.events] == [trace_id, trace_id]
    assert [e.step for e in sink.events] == ["proposed", "classified"]
