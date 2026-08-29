"""End-to-end classify_live() tests against a seeded, live minikube
cluster: same action, different tier from live state. Skips gracefully
when no cluster is reachable, so `pytest` stays green cluster-less.
"""

from __future__ import annotations

import pytest
from kubernetes import client, config

from k8s_agent.classify_live import classify_live
from k8s_agent.cluster import ClusterClient
from safety_core.types import Action, Tier

pytestmark = pytest.mark.integration

_DEMO_NAMESPACE = "bounded-agent-demo"
_PROTECTED_NAMESPACE = "bounded-agent-demo-protected"


@pytest.fixture(scope="module")
def cluster() -> ClusterClient:
    try:
        config.load_kube_config()
    except Exception as exc:
        pytest.skip(f"no kubeconfig available: {exc}")

    try:
        client.CoreV1Api().list_namespace(limit=1, _request_timeout=5)
    except Exception as exc:
        pytest.skip(f"cluster not reachable: {exc}")

    return ClusterClient()


def _delete_pod_action(pod: str, namespace: str) -> Action:
    return Action(tool="delete_pod", args={"namespace": namespace, "pod": pod}, rationale="Recycling a stuck pod.")


def test_safe_delete_pod_on_healthy_deployment_yields_approve(cluster: ClusterClient):
    action = _delete_pod_action("healthy-web-some-pod", _DEMO_NAMESPACE)

    decision = classify_live(action, "healthy-web", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.APPROVE


def test_same_action_on_degraded_deployment_blocked_by_pdb_breach(cluster: ClusterClient):
    action = _delete_pod_action("degraded-checkout-some-pod", _DEMO_NAMESPACE)

    decision = classify_live(action, "degraded-checkout", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "PDB" in decision.reason


def test_delete_pod_on_solo_replica_deployment_blocked_by_pdb_breach(cluster: ClusterClient):
    """Scenario A: the visceral "delete the only pod" case — healthy_replicas: 1,
    pdb_min_available: 1 read from the real cluster, headroom 0, gate BLOCKs.
    """
    action = _delete_pod_action("solo-replica-web-some-pod", _DEMO_NAMESPACE)

    decision = classify_live(action, "solo-replica-web", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "PDB" in decision.reason


def test_action_in_protected_namespace_blocked(cluster: ClusterClient):
    action = _delete_pod_action("payments-core-some-pod", _PROTECTED_NAMESPACE)

    decision = classify_live(action, "payments-core", _PROTECTED_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "protected" in decision.reason


def test_mutation_with_no_rollback_target_blocked(cluster: ClusterClient):
    action = Action(
        tool="update_resource_limits",
        args={"namespace": _DEMO_NAMESPACE, "deployment": "no-rollback-web", "container": "web", "memory_limit": "64Mi"},
        rationale="Raising the memory ceiling.",
    )

    decision = classify_live(action, "no-rollback-web", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "no rollback target" in decision.reason


def test_nonexistent_target_blocked_via_gate_validity_branch(cluster: ClusterClient):
    """Scenario B: a real 404 from the Kubernetes API routes through
    classify_live's DeploymentNotFoundError handling into the Gate's own
    M1.4 validity branch — not a shortcut in classify_live, which never
    constructs a Decision or reason string itself. A Gate-shaped reason
    (this exact substring, defined in safety_core/gate.py) is structural
    proof the BLOCK came from the Gate, not from classify_live.
    """
    action = _delete_pod_action("ghost-pod", _DEMO_NAMESPACE)

    decision = classify_live(action, "does-not-exist-web", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "target not found" in decision.reason
