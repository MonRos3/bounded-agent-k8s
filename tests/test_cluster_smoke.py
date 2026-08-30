"""Light smoke tests against a seeded, live minikube cluster. Skips
gracefully (not a failure) when no cluster is reachable, so `pytest`
stays green in a cluster-less environment.
"""

from __future__ import annotations

import pytest
from kubernetes import client, config

from k8s_agent.cluster import ClusterClient
from k8s_agent.cluster_types import DeploymentState
from safety_core.types import Action

pytestmark = pytest.mark.integration

_NAMESPACE = "bounded-agent-demo"
_HEALTHY_DEPLOYMENT = "healthy-web"


def _first_pod_name(namespace: str, app_label: str) -> str:
    """A real, currently-live pod name for the given app label — same
    pattern tests/test_integration_m2.py already uses.
    """
    pods = client.CoreV1Api().list_namespaced_pod(namespace, label_selector=f"app={app_label}")
    return pods.items[0].metadata.name


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


def test_get_deployment_state_returns_sane_data(cluster: ClusterClient):
    state = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)

    assert isinstance(state, DeploymentState)
    assert state.namespace == _NAMESPACE
    assert state.healthy_replicas >= 0
    assert state.desired_replicas > 0
    assert isinstance(state.revisions, list) and state.revisions


def test_scale_deployment_is_observable(cluster: ClusterClient):
    before = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
    scaled_up = before.desired_replicas + 1

    try:
        result = cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, scaled_up)
        assert result.success

        after = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
        assert after.desired_replicas == scaled_up
    finally:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, before.desired_replicas)


def test_observe_outcome_returns_ready_count_after_settle(cluster: ClusterClient):
    before = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)

    observed = cluster.observe_outcome(_HEALTHY_DEPLOYMENT, _NAMESPACE, "healthy_replicas", timeout_seconds=10)

    assert observed == {"healthy_replicas": before.desired_replicas}


def test_observe_outcome_reports_below_target_on_unready(cluster: ClusterClient):
    """Scaling up guarantees brand-new pods that can't possibly be Ready
    within a couple seconds — a more deterministic way to force
    not-settled than racing a rolling restart, where old pods often stay
    Ready until the very last moment.
    """
    before = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
    scaled_up = before.desired_replicas + 2

    try:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, scaled_up)

        observed = cluster.observe_outcome(_HEALTHY_DEPLOYMENT, _NAMESPACE, "healthy_replicas", timeout_seconds=2)

        assert observed["healthy_replicas"] < scaled_up
    finally:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, before.desired_replicas)


def test_dry_run_diff_does_not_mutate_cluster(cluster: ClusterClient):
    """The critical property: a server-side dry run must persist nothing.
    Proves it by re-querying live state after the dry run and asserting
    it's unchanged — not just trusting the returned diff.
    """
    before = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
    requested = before.desired_replicas + 1
    action = Action(
        tool="scale_deployment",
        args={"namespace": _NAMESPACE, "deployment": _HEALTHY_DEPLOYMENT, "target_replicas": requested},
        rationale="",
    )

    try:
        diff = cluster.dry_run_diff(action)

        assert diff is not None
        assert diff.kind == "field_delta"
        assert diff.changes["replicas"] == (before.desired_replicas, requested)

        after = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
        assert after.desired_replicas == before.desired_replicas
    finally:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, before.desired_replicas)


def test_dry_run_diff_update_resource_limits_does_not_mutate_cluster(cluster: ClusterClient):
    """update_resource_limits is the one dry-run branch a real operator
    actually reaches through the live approval flow (APPROVE-tier in
    DEMO_POLICY, unlike scale/restart which are AUTO) — reads the
    container's limits directly via the raw client (ClusterClient has no
    getter for them) to prove the dry run left them untouched.
    """
    container = "web"
    requested_memory = "777Mi"

    def _current_memory_limit() -> str | None:
        deployment = client.AppsV1Api().read_namespaced_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE)
        for c in deployment.spec.template.spec.containers:
            if c.name == container:
                return (c.resources.limits or {}).get("memory") if c.resources else None
        return None

    before_memory = _current_memory_limit()
    action = Action(
        tool="update_resource_limits",
        args={
            "namespace": _NAMESPACE,
            "deployment": _HEALTHY_DEPLOYMENT,
            "container": container,
            "memory_limit": requested_memory,
        },
        rationale="",
    )

    diff = cluster.dry_run_diff(action)

    assert diff is not None
    assert diff.kind == "field_delta"
    assert diff.changes["limits"][1].get("memory") == requested_memory
    assert _current_memory_limit() == before_memory


def test_dry_run_diff_delete_pod_returns_removal_descriptor_without_deleting(cluster: ClusterClient):
    pod_name = _first_pod_name(_NAMESPACE, _HEALTHY_DEPLOYMENT)
    action = Action(tool="delete_pod", args={"namespace": _NAMESPACE, "pod": pod_name}, rationale="")

    diff = cluster.dry_run_diff(action)

    assert diff is not None
    assert diff.kind == "removal"
    assert pod_name in (diff.description or "")

    remaining = client.CoreV1Api().read_namespaced_pod(pod_name, _NAMESPACE)
    assert remaining.metadata.name == pod_name


def test_dry_run_diff_returns_none_for_read_only(cluster: ClusterClient):
    action = Action(tool="get_pod_logs", args={"namespace": _NAMESPACE, "pod": "irrelevant"}, rationale="")

    assert cluster.dry_run_diff(action) is None


def test_dry_run_diff_pvc_delete_stays_simulated(cluster: ClusterClient):
    action = Action(
        tool="delete_persistent_volume_claim", args={"namespace": _NAMESPACE, "pvc": "some-pvc"}, rationale=""
    )

    diff = cluster.dry_run_diff(action)

    assert diff is not None
    assert diff.kind == "simulated_removal"
    assert "simulated" in (diff.description or "").lower()


def test_dry_run_diff_returns_none_when_target_not_found(cluster: ClusterClient):
    action = Action(
        tool="scale_deployment",
        args={"namespace": _NAMESPACE, "deployment": "does-not-exist-deployment", "target_replicas": 1},
        rationale="",
    )

    assert cluster.dry_run_diff(action) is None
