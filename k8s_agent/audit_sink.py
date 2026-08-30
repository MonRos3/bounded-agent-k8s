"""Concrete AuditSink for the demo — a real implementation belongs in the
domain layer, same as K8sRollbackPlanner/K8sSuccessDefiner.
"""

from __future__ import annotations

import dataclasses
import json

from safety_core.audit import AuditEvent, AuditSink


class StdoutAuditSink(AuditSink):
    """Prints each event as one JSON line. `default=str` handles the Tier
    enum (and anything else non-serializable) without a custom encoder —
    sufficient for a demo sink; a production sink (e.g. CloudWatch Logs)
    would replace this, not extend it.
    """

    def emit(self, event: AuditEvent) -> None:
        print(json.dumps(dataclasses.asdict(event), default=str))
