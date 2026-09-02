"""End-to-end classify_live() tests against a seeded, live minikube
cluster: same action, different tier from live state. Skips gracefully
when no cluster is reachable, so `pytest` stays green cluster-less.
"""

from __future__ import annotations

import pytest
from kubernetes import client, config

from k8s_agent.classify_live import classify_live
from k8s_agent.cluster import ClusterClient, DeploymentNotFoundError
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


def _first_pod_name(namespace: str, app_label: str) -> str:
    """A real, currently-live pod name for the given app label — needed
    now that classify_live resolves delete_pod's target via a genuine
    ownerReferences lookup rather than accepting a deployment name
    directly.
    """
    pods = client.CoreV1Api().list_namespaced_pod(namespace, label_selector=f"app={app_label}")
    return pods.items[0].metadata.name


def test_safe_delete_pod_on_healthy_deployment_yields_approve(cluster: ClusterClient):
    pod = _first_pod_name(_DEMO_NAMESPACE, "healthy-web")
    action = _delete_pod_action(pod, _DEMO_NAMESPACE)

    decision = classify_live(action, pod, _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.APPROVE


def test_same_action_on_degraded_deployment_blocked_by_pdb_breach(cluster: ClusterClient):
    pod = _first_pod_name(_DEMO_NAMESPACE, "degraded-checkout")
    action = _delete_pod_action(pod, _DEMO_NAMESPACE)

    decision = classify_live(action, pod, _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "PDB" in decision.reason


def test_delete_pod_on_solo_replica_deployment_blocked_by_pdb_breach(cluster: ClusterClient):
    """Scenario A: the visceral "delete the only pod" case — healthy_replicas: 1,
    pdb_min_available: 1 read from the real cluster, headroom 0, gate BLOCKs.
    """
    pod = _first_pod_name(_DEMO_NAMESPACE, "solo-replica-web")
    action = _delete_pod_action(pod, _DEMO_NAMESPACE)

    decision = classify_live(action, pod, _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "PDB" in decision.reason


def test_scale_up_on_solo_replica_deployment_not_blocked_by_pdb(cluster: ClusterClient):
    """PA-1: scaling UP a zero-headroom deployment can never breach its PDB
    floor, so it must reach its normal tier instead of being blocked — the
    direction-aware counterpart to the delete-still-blocks case above.
    """
    action = Action(
        tool="scale_deployment",
        args={"namespace": _DEMO_NAMESPACE, "deployment": "solo-replica-web", "target_replicas": 3},
        rationale="Scaling out ahead of load.",
    )

    decision = classify_live(action, "solo-replica-web", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.AUTO


def test_scale_down_on_solo_replica_deployment_still_blocked_by_pdb(cluster: ClusterClient):
    """PA-1 guard: scaling DOWN a zero-headroom deployment is the dangerous
    direction and must still BLOCK, at the scale level as well as delete.
    """
    action = Action(
        tool="scale_deployment",
        args={"namespace": _DEMO_NAMESPACE, "deployment": "solo-replica-web", "target_replicas": 0},
        rationale="Decommissioning this workload.",
    )

    decision = classify_live(action, "solo-replica-web", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "PDB" in decision.reason


def test_action_in_protected_namespace_blocked(cluster: ClusterClient):
    pod = _first_pod_name(_PROTECTED_NAMESPACE, "payments-core")
    action = _delete_pod_action(pod, _PROTECTED_NAMESPACE)

    decision = classify_live(action, pod, _PROTECTED_NAMESPACE, cluster)

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
    proof the BLOCK came from the Gate, not from classify_live. Uses a
    deployment-scoped tool — `name` passes straight through unresolved for
    these, so this is purely a missing-Deployment 404, distinct from the
    pod-resolution case below.
    """
    action = Action(
        tool="scale_deployment",
        args={"namespace": _DEMO_NAMESPACE, "deployment": "does-not-exist-web", "target_replicas": 3},
        rationale="Scaling a deployment that isn't there.",
    )

    decision = classify_live(action, "does-not-exist-web", _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "target not found" in decision.reason


def test_delete_pod_on_nonexistent_pod_blocks_for_target_not_found(cluster: ClusterClient):
    """The genuine not-found case for a pod-scoped tool — distinct from the
    resolution-mismatch bug this task fixes. resolve_pod_owner itself
    raises DeploymentNotFoundError for a pod that doesn't exist, and that
    propagates into classify_live's single not-found handler (same one the
    deployment-404 case above lands in) rather than a second lookup.
    """
    ghost_pod = "ghost-pod-does-not-exist"
    with pytest.raises(DeploymentNotFoundError):
        cluster.resolve_pod_owner(ghost_pod, _DEMO_NAMESPACE)

    action = _delete_pod_action(ghost_pod, _DEMO_NAMESPACE)
    decision = classify_live(action, ghost_pod, _DEMO_NAMESPACE, cluster)

    assert decision.tier == Tier.BLOCK
    assert "target not found" in decision.reason
