"""Pure translation from a typed DeploymentState into the facts dict
safety_core's Gate reads via State.facts. One-directional: this module
must never import from safety_core/ — it produces a plain dict, agnostic
of how (or whether) anything downstream consumes it.
"""

from __future__ import annotations

from typing import Any

from k8s_agent.cluster_types import DeploymentState
from safety_core.types import Action

# Tools that read state without changing replica counts. Anything not
# listed here (including tools not otherwise recognized) defaults to
# reducing availability -- see _reduces_availability's fail-safe default.
_READ_ONLY_TOOLS = {"get_pod_logs"}


def build_facts(
    deployment_state: DeploymentState,
    protected_zones: set[str],
    action: Action | None = None,
) -> dict[str, Any]:
    """Build the facts dict the Gate reads out of a DeploymentState.

    `protected` and `has_rollback_target` are computed; `healthy_replicas`,
    `desired_replicas`, `pdb_min_available`, and `mid_batch` pass through
    as-is; `revision` is the current one (`revisions[-1]` — a
    DeploymentState with no revisions at all is a caller-contract
    violation and raises IndexError rather than being silently handled).
    `desired_replicas` isn't read by the Gate itself — it exists so a
    RollbackPlanner can build a scale-type rollback plan that carries the
    prior replica count as its target, not just a revision number.

    `action`, when supplied, adds `reduces_availability` — whether `action`
    could reduce the target's availability, per _reduces_availability. When
    omitted (the default), the key is left out entirely; the Gate treats an
    absent fact as potentially reducing, so callers that don't have an
    action to hand (or existing callers written before this fact existed)
    see no behavior change.

    Two facts the Gate can read are never set here, deliberately:
    `dry_run_diff` has no source in this function's inputs (a real diff
    needs cluster I/O, which this pure function must not do), and
    `target_exists` doesn't apply — a DeploymentState describes an already
    -observed deployment, so existence is implicit; a "not found" outcome
    belongs to whatever lookup step tries to build one and comes up empty.
    Both are optional as far as the Gate is concerned, so omitting them
    here changes no behavior for the facts this function does produce.
    """
    facts = {
        "healthy_replicas": deployment_state.healthy_replicas,
        "desired_replicas": deployment_state.desired_replicas,
        "pdb_min_available": deployment_state.pdb_min_available,
        "protected": deployment_state.namespace in protected_zones,
        "has_rollback_target": len(deployment_state.revisions) >= 2,
        "revision": deployment_state.revisions[-1],
        "mid_batch": deployment_state.mid_batch,
    }
    if action is not None:
        facts["reduces_availability"] = _reduces_availability(action, deployment_state)
    return facts


def _reduces_availability(action: Action, deployment_state: DeploymentState) -> bool:
    """Whether `action` could reduce the deployment's available replica
    count, relative to its current desired count.

    Fail-safe: anything not positively known to hold-or-increase
    availability defaults to True, including a scale action with no
    `target_replicas` and every tool this function doesn't recognize (e.g.
    a rolling restart, which transiently drops one replica at a time, is
    correctly conservative here rather than unhandled).
    """
    if action.tool == "scale_deployment":
        target = action.args.get("target_replicas")
        if target is None:
            return True
        return target < deployment_state.desired_replicas
    if action.tool in _READ_ONLY_TOOLS:
        return False
    return True
