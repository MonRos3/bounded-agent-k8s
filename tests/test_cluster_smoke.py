"""Light smoke tests against a seeded, live minikube cluster. Skips
gracefully (not a failure) when no cluster is reachable, so `pytest`
stays green in a cluster-less environment.
"""

from __future__ import annotations

import pytest
from kubernetes import client, config

from k8s_agent.cluster import ClusterClient
from k8s_agent.cluster_types import DeploymentState

pytestmark = pytest.mark.integration

_NAMESPACE = "bounded-agent-demo"
_HEALTHY_DEPLOYMENT = "healthy-web"


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
