"""Concrete AuditSink for the demo — a real implementation belongs in the
domain layer, same as K8sRollbackPlanner/K8sSuccessDefiner.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from safety_core.audit import AuditEvent, AuditSink


class StdoutAuditSink(AuditSink):
    """Prints each event as one JSON line. `default=str` handles the Tier
    enum (and anything else non-serializable) without a custom encoder —
    sufficient for a demo sink; a production sink (e.g. CloudWatch Logs)
    would replace this, not extend it.
    """

    def emit(self, event: AuditEvent) -> None:
        print(json.dumps(dataclasses.asdict(event), default=str))


class FileAuditSink(AuditSink):
    """Writes each event as one JSON line to `path` — same shape as
    StdoutAuditSink, but to a file meant to be watched with `tail -f`
    while the operator terminal (k8s_agent/cli.py) stays curated. Opens,
    appends, and closes on every emit rather than holding a handle open:
    event volume is a handful per operator request, and this guarantees
    every write is immediately visible to a concurrent `tail -f`.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: AuditEvent) -> None:
        with open(self._path, "a") as f:
            f.write(json.dumps(dataclasses.asdict(event), default=str) + "\n")
