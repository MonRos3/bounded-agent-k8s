"""k8s_agent's concrete AuditSink implementations. Domain-layer sinks, kept
separate from tests/test_audit.py (which tests safety_core.audit's
Auditor/AuditSink contract itself against an in-memory fake).
"""

from __future__ import annotations

import json

from k8s_agent.audit_sink import FileAuditSink
from safety_core.audit import AuditEvent
from safety_core.types import Action, Decision, Tier


def _event(trace_id: str, step: str) -> AuditEvent:
    return AuditEvent(
        trace_id=trace_id,
        timestamp="2026-08-30T00:00:00+00:00",
        step=step,
        action=Action(tool="scale_deployment", args={"target_replicas": 5}, rationale=""),
        decision=Decision(tier=Tier.AUTO, reason="ok", reversible=True, scope="scale_deployment", rollback=None, success=None),
        detail={},
    )


def test_file_audit_sink_writes_one_json_line_per_event(tmp_path):
    path = tmp_path / "run.jsonl"
    sink = FileAuditSink(path)

    sink.emit(_event("trace-1", "proposed"))
    sink.emit(_event("trace-1", "classified"))

    lines = path.read_text().splitlines()
    assert len(lines) == 2

    first, second = (json.loads(line) for line in lines)
    assert first["trace_id"] == "trace-1"
    assert first["step"] == "proposed"
    assert first["action"]["tool"] == "scale_deployment"
    assert first["decision"]["tier"] == "Tier.AUTO"
    assert second["step"] == "classified"


def test_file_audit_sink_creates_parent_directory(tmp_path):
    path = tmp_path / "audit_logs" / "run.jsonl"
    assert not path.parent.exists()

    FileAuditSink(path)

    assert path.parent.is_dir()
