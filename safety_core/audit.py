"""Audit: every gate decision and safety-relevant step is recorded through an
injected sink. Domain code never writes audit records directly.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from safety_core.types import Action, Decision


@dataclass(frozen=True)
class AuditEvent:
    """One recorded step in a trace.

    `action` and `decision` are the proposal and the Gate's verdict on it;
    `detail` carries step-specific data. Callers are expected to have run
    anything untrusted through Guardrails.redact_output before it reaches
    here — the sink assumes what it's handed is already safe to persist.
    """

    trace_id: str
    timestamp: str
    step: str
    action: Action
    decision: Decision
    detail: dict[str, Any]


class AuditSink(ABC):
    """Domain interface: durable destination for AuditEvents (e.g. CloudWatch
    Logs, stdout, a file). Decides only where an event goes, never whether or
    what to log.
    """

    @abstractmethod
    def emit(self, event: AuditEvent) -> None:
        """Persist `event`. Must not raise on already-redacted data and must
        not itself introduce secrets/PII into the destination.
        """
        ...


class Auditor:
    """Front door for recording a trace's steps through an injected AuditSink.

    Callers use new_trace()/record() rather than constructing AuditEvent or
    talking to the sink directly, keeping trace_id generation and event shape
    in one place.
    """

    def __init__(self, sink: AuditSink) -> None:
        self._sink = sink

    def new_trace(self) -> str:
        """Start a new trace and return its trace_id."""
        return str(uuid.uuid4())

    def record(self, step: str, **kwargs: Any) -> None:
        """Build an AuditEvent for `step` from `kwargs` and emit it via the
        injected sink.

        `kwargs` must supply `trace_id`, `action`, and `decision`; `detail`
        is optional (defaults to empty). Placeholder `action`/`decision`
        values for steps that don't yet have a real one (e.g. a proposal
        not yet classified) are the caller's responsibility — this method
        only assembles what it's given, it doesn't invent domain meaning.
        """
        event = AuditEvent(
            trace_id=kwargs["trace_id"],
            timestamp=datetime.now(timezone.utc).isoformat(),
            step=step,
            action=kwargs["action"],
            decision=kwargs["decision"],
            detail=kwargs.get("detail", {}),
        )
        self._sink.emit(event)
