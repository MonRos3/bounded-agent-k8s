"""Kubescape-backed compliance scanning: an operator capability, not the
agent — no LLM, no gate, no safety_core/ involvement anywhere in this
file. Skips gracefully (not a failure) when the cluster isn't reachable
or kubescape isn't on PATH, so `pytest` stays green without either.
Assumes bounded-agent-demo-insecure is already seeded (`make
seed-insecure`), consistent with every other integration test's
convention of never self-seeding.
"""

from __future__ import annotations

import shutil

import pytest
from kubernetes import client, config

from compliance.scan import scan_cluster
from compliance.types import Finding, ScanResult

pytestmark = pytest.mark.integration

_INSECURE_NAMESPACE = "bounded-agent-demo-insecure"


@pytest.fixture(scope="module")
def _kubescape_and_cluster() -> None:
    if shutil.which("kubescape") is None:
        pytest.skip("kubescape not found on PATH")

    try:
        config.load_kube_config()
    except Exception as exc:
        pytest.skip(f"no kubeconfig available: {exc}")

    try:
        core = client.CoreV1Api()
        core.list_namespace(limit=1, _request_timeout=5)
    except Exception as exc:
        pytest.skip(f"cluster not reachable: {exc}")

    try:
        core.read_namespace(_INSECURE_NAMESPACE)
    except Exception:
        pytest.skip(f"{_INSECURE_NAMESPACE} not seeded — run 'make seed-insecure' first")


def test_scan_cluster_returns_structured_result(_kubescape_and_cluster):
    result = scan_cluster(namespace=_INSECURE_NAMESPACE)

    assert isinstance(result, ScanResult)
    assert result.framework == "nsa"
    assert result.total_controls > 0
    assert result.passed + result.failed <= result.total_controls
    assert all(isinstance(f, Finding) for f in result.findings)


def test_scan_surfaces_planted_misconfigurations(_kubescape_and_cluster):
    """Assert on categories, not exact counts or control IDs — Kubescape's
    precise output shifts between versions.
    """
    result = scan_cluster(namespace=_INSECURE_NAMESPACE)

    assert result.failed > 0

    names = " ".join(f.control_name.lower() for f in result.findings)
    assert "privileged" in names
    assert "root" in names
    assert "limit" in names
    assert "privilege escalation" in names

    for finding in result.findings:
        assert finding.control_id
        assert finding.control_name
        assert finding.severity
        assert isinstance(finding.affected_resources, list)


def test_scan_is_read_only(_kubescape_and_cluster):
    core = client.AppsV1Api()

    def _snapshot() -> dict[str, str]:
        deployments = core.list_namespaced_deployment(_INSECURE_NAMESPACE)
        return {d.metadata.name: d.metadata.resource_version for d in deployments.items}

    before = _snapshot()
    scan_cluster(namespace=_INSECURE_NAMESPACE)
    after = _snapshot()

    assert after == before
