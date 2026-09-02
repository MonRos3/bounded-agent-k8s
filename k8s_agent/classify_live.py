"""The integration function: wires I/O (ClusterClient) -> translation
(state_builder.build_facts, or a minimal not-found fallback) -> the Gate.
Does no classification itself — the Gate remains the sole authority; every
field on the returned Decision comes back from Gate.classify() untouched.
"""

from __future__ import annotations

from typing import Any

from k8s_agent.cluster import ClusterClient, DeploymentNotFoundError
from k8s_agent.planners import K8sRollbackPlanner, K8sSuccessDefiner
from k8s_agent.policy_config import DEMO_POLICY
from k8s_agent.state_builder import build_facts
from safety_core.gate import Gate
from safety_core.types import Action, Decision, State

# Tools whose target identifier is a pod name, not a Deployment name — the
# Gate always classifies Deployment-shaped facts, so these need resolving
# to their owning Deployment before lookup. Everything else's `name` is
# already a Deployment name.
_POD_SCOPED_TOOLS = {"get_pod_logs", "delete_pod"}


def classify_live(action: Action, name: str, namespace: str, cluster_client: ClusterClient) -> Decision:
    """Classify `action` against live cluster state. `name` identifies the
    target: a pod name for delete_pod/get_pod_logs (resolved to its owning
    Deployment below), already a Deployment name for everything else.

    Target found: fetch its DeploymentState and translate it via
    build_facts. Target not found: ClusterClient raises
    DeploymentNotFoundError — either resolving a pod to its owning
    Deployment, or looking up the Deployment itself, lands in the same
    except block here (there's deliberately only one not-found handler: a
    pod with no owning Deployment and a missing Deployment both mean
    target_exists: False to the gate, so they're handled identically, not
    as two separate lookups). Facts are then built directly (never via
    build_facts, since there's no DeploymentState to translate) carrying
    target_exists: False. Either way, the resulting State is handed to a
    real Gate; this function never decides a tier itself.
    """
    try:
        deployment_name = (
            cluster_client.resolve_pod_owner(name, namespace) if action.tool in _POD_SCOPED_TOOLS else name
        )
        deployment_state = cluster_client.get_deployment_state(deployment_name, namespace)
        facts = build_facts(deployment_state, DEMO_POLICY.protected_zones, action)
    except DeploymentNotFoundError:
        facts = _facts_for_missing_target()

    gate = Gate(DEMO_POLICY, K8sRollbackPlanner(), K8sSuccessDefiner())
    return gate.classify(action, State(facts=facts))


def _facts_for_missing_target() -> dict[str, Any]:
    """Minimal facts for a target that doesn't exist.

    Deliberately just one key: Gate.classify's target_exists check fires
    before the protected/reversibility/PDB cascade ever reads anything
    else, so nothing beyond target_exists can affect the outcome here.
    """
    return {"target_exists": False}
