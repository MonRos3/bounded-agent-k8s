"""Render a ScanResult as a legible operator posture report, and persist
it as durable, honestly-framed evidence. No LLM, no gate, no agent
involvement — a human runs this and reads/keeps the result.
"""

from __future__ import annotations

import dataclasses
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from compliance.types import ScanResult

_FRAMING = (
    "Kubernetes security posture against the SOC 2 framework. This is "
    "evidence toward SOC 2 compliance for the Kubernetes infrastructure "
    "layer — not a SOC 2 certification. SOC 2 is an organizational audit "
    "performed by a licensed auditor covering controls beyond Kubernetes "
    "configuration."
)

_SEVERITY_STYLE = {"Critical": "bold red", "High": "red", "Medium": "yellow", "Low": "cyan"}
_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "compliance_reports"


def render_report(scan_result: ScanResult, console: Console) -> None:
    """The posture report: framework, overall pass/fail, failing findings
    by severity, and the honest framing baked into the header — not a
    disclaimer bolted on afterward. Curated compliance evidence, not a
    raw dump of scan_result.
    """
    console.print(
        Panel(_FRAMING, title=f"Compliance Posture — {scan_result.framework.upper()}", border_style="blue")
    )
    console.print(
        f"[bold]posture[/bold]  {scan_result.passed} of {scan_result.total_controls} controls passed "
        f"({scan_result.failed} failed)"
    )

    if not scan_result.findings:
        console.print("[green]no failing controls[/green]")
        return

    by_severity: dict[str, int] = {}
    for finding in scan_result.findings:
        by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
    breakdown = ", ".join(
        f"{severity}: {count}" for severity, count in sorted(by_severity.items(), key=lambda kv: _SEVERITY_ORDER.get(kv[0], 99))
    )
    console.print(f"[bold]failed by severity[/bold]  {breakdown}")

    console.rule("failing findings", style="dim")
    for finding in sorted(scan_result.findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 99)):
        style = _SEVERITY_STYLE.get(finding.severity, "white")
        console.print(
            f"[{style}][{finding.control_id}][/{style}] {finding.control_name}  [{style}]{finding.severity}[/{style}]"
        )
        console.print(f"  affected: {', '.join(finding.affected_resources) or 'none listed'}")
        console.print(f"  {finding.detail}")


def persist_evidence(scan_result: ScanResult, output_dir: Path = _REPORTS_DIR) -> tuple[Path, Path]:
    """Write the scan as durable evidence: a structured .json (the
    ScanResult, plus the same honest framing line and a generated_at
    timestamp) and a human-readable .md rendered by the exact same
    render_report used for the terminal — one source of truth for the
    report's content, two destinations. Returns (json_path, md_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    json_path = output_dir / f"{stamp}.json"
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "framing": _FRAMING,
        **dataclasses.asdict(scan_result),
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))

    md_path = output_dir / f"{stamp}.md"
    # file=io.StringIO() -- a throwaway sink -- keeps this from also
    # printing a second copy of the report to the real terminal; record=True
    # captures it independently of wherever `file` points.
    capture = Console(record=True, width=100, no_color=True, file=io.StringIO())
    render_report(scan_result, capture)
    md_path.write_text(capture.export_text())

    return json_path, md_path
