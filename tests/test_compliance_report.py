"""render_report / persist_evidence: fully stubbed, no live cluster — an
operator-domain rendering/persistence concern, no LLM, no gate, no agent
involvement anywhere in this file.
"""

from __future__ import annotations

import json

from rich.console import Console

from compliance.report import persist_evidence, render_report
from compliance.types import Finding, ScanResult


def _scan_result(findings: list[Finding] | None = None) -> ScanResult:
    return ScanResult(
        framework="soc2",
        total_controls=7,
        passed=4,
        failed=3,
        findings=findings if findings is not None else [],
    )


def _finding(**overrides) -> Finding:
    defaults = dict(
        control_id="C-0260",
        control_name="Firewall (CC6.1,CC6.6,CC7.2)",
        severity="Medium",
        affected_resources=["apps/v1/bounded-agent-demo-insecure/Deployment/insecure-privileged"],
        detail="Firewall failed for 1 resource(s)",
    )
    defaults.update(overrides)
    return Finding(**defaults)


def test_render_report_shows_framing_and_posture_summary():
    console = Console(record=True, width=120)

    render_report(_scan_result(), console)

    output = console.export_text()
    assert "SOC 2" in output
    assert "evidence toward SOC 2 compliance" in output
    assert "not a SOC 2 certification" in output
    assert "4 of 7 controls passed" in output
    assert "3 failed" in output


def test_render_report_shows_failing_findings():
    findings = [_finding(), _finding(control_id="C-0035", control_name="Access restriction to infrastructure", severity="High")]
    console = Console(record=True, width=120)

    render_report(_scan_result(findings), console)

    output = console.export_text()
    for finding in findings:
        assert finding.control_id in output
        assert finding.control_name in output
        assert finding.severity in output
        assert finding.affected_resources[0] in output


def test_render_report_shows_no_failing_controls_when_findings_empty():
    console = Console(record=True, width=120)

    render_report(_scan_result(findings=[]), console)

    output = console.export_text()
    assert "no failing controls" in output


def test_persist_evidence_writes_json_with_framing(tmp_path):
    findings = [_finding()]
    scan_result = _scan_result(findings)

    json_path, _ = persist_evidence(scan_result, output_dir=tmp_path)

    payload = json.loads(json_path.read_text())
    assert "evidence toward SOC 2 compliance" in payload["framing"]
    assert "generated_at" in payload
    assert payload["framework"] == "soc2"
    assert payload["passed"] == 4
    assert payload["failed"] == 3
    assert payload["findings"][0]["control_id"] == "C-0260"


def test_persist_evidence_writes_readable_text_with_framing(tmp_path):
    findings = [_finding()]
    scan_result = _scan_result(findings)

    _, md_path = persist_evidence(scan_result, output_dir=tmp_path)

    text = md_path.read_text()
    assert "evidence toward SOC 2" in text
    assert "not a SOC 2 certification" in text
    assert "C-0260" in text
