"""Kubescape scan invocation and JSON parsing. Deterministic and
read-only: this only reads cluster state and reports on it, exactly like
`kubectl get` — it has no execute path of any kind. Kubescape is a Go
CLI, invoked as a subprocess with a fixed argument list — never a shell
string built from data (OWASP: no OS command constructed from
interpolated values). No LLM, no gate, no safety_core/ or k8s_agent/
import: this is a human-operator capability, not agent logic.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections import defaultdict
from typing import Any

from compliance.types import Finding, ScanResult

_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_SCAN_TIMEOUT_SECONDS = 180


class ScanError(Exception):
    """Raised when Kubescape's output can't be parsed as a scan report —
    a genuine invocation failure (bad flags, kubescape missing, cluster
    unreachable, timeout). Never raised just because the scan found
    failing controls — that's a normal, successful ScanResult.
    """


def scan_cluster(namespace: str | None = None, framework: str = "nsa") -> ScanResult:
    """Invoke Kubescape against the cluster (or one namespace), parse its
    JSON report, and return a structured ScanResult.

    Read-only: Kubescape's `scan` command only reads cluster state.
    Findings are a normal, successful outcome — confirmed empirically
    that Kubescape exits 0 even when controls fail — so success here is
    judged by whether the output parses as the expected report shape,
    never by the process's exit code alone.
    """
    if namespace is not None and not _NAMESPACE_PATTERN.fullmatch(namespace):
        raise ValueError(f"invalid namespace: {namespace!r}")

    fd, output_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        args = ["kubescape", "scan", "framework", framework]
        if namespace is not None:
            args += ["--include-namespaces", namespace]
        args += ["--format", "json", "--output", output_path]

        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=_SCAN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise ScanError(f"kubescape scan timed out after {_SCAN_TIMEOUT_SECONDS}s") from exc
        except FileNotFoundError as exc:
            raise ScanError("kubescape not found on PATH") from exc

        try:
            with open(output_path) as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ScanError(
                f"kubescape scan did not produce a parseable report (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            ) from exc
    finally:
        os.unlink(output_path)

    return _parse_scan_result(raw, framework)


def _parse_scan_result(raw: dict[str, Any], framework: str) -> ScanResult:
    try:
        controls: dict[str, Any] = raw["summaryDetails"]["controls"]
    except KeyError as exc:
        raise ScanError(f"unexpected kubescape report shape: missing {exc}") from exc

    resources_by_control: dict[str, list[str]] = defaultdict(list)
    for result in raw.get("results", []):
        resource_id = result.get("resourceID", "")
        for control in result.get("controls", []):
            status = control.get("status")
            if isinstance(status, dict) and status.get("status") == "failed":
                resources_by_control[control.get("controlID", "")].append(resource_id)

    passed = sum(1 for c in controls.values() if c.get("status") == "passed")
    failed = sum(1 for c in controls.values() if c.get("status") == "failed")

    findings = [
        Finding(
            control_id=control_id,
            control_name=control.get("name", control_id),
            severity=control.get("severity", "Unknown"),
            affected_resources=resources_by_control.get(control_id, []),
            detail=f"{control.get('name', control_id)} failed for "
            f"{len(resources_by_control.get(control_id, []))} resource(s)",
        )
        for control_id, control in controls.items()
        if control.get("status") == "failed"
    ]

    return ScanResult(
        framework=framework, total_controls=len(controls), passed=passed, failed=failed, findings=findings
    )
