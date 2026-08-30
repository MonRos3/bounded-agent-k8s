"""Operator-domain value types for a compliance scan. No relation to
safety_core.types.Action/Decision or any agent concept — a scan never
touches the Gate, a model, or the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    """One failed control from one scan.

    `affected_resources` are Kubescape's own resourceIDs (e.g.
    "apps/v1/bounded-agent-demo/Deployment/healthy-web") — already
    unambiguous and human-readable, not translated further.
    """

    control_id: str
    control_name: str
    severity: str
    affected_resources: list[str]
    detail: str


@dataclass(frozen=True)
class ScanResult:
    """A full scan's outcome: one framework, every control it evaluated,
    and the findings for whichever ones failed.
    """

    framework: str
    total_controls: int
    passed: int
    failed: int
    findings: list[Finding]
