"""Pure translation from a typed DeploymentState into the facts dict
safety_core's Gate reads via State.facts. One-directional: this module
must never import from safety_core/ — it produces a plain dict, agnostic
of how (or whether) anything downstream consumes it.
"""

from __future__ import annotations

from typing import Any

from k8s_agent.cluster_types import DeploymentState


def build_facts(deployment_state: DeploymentState, protected_zones: set[str]) -> dict[str, Any]:
    """Build the facts dict the Gate reads out of a DeploymentState.

    `protected` and `has_rollback_target` are computed; `healthy_replicas`,
    `pdb_min_available`, and `mid_batch` pass through as-is; `revision` is
    the current one (`revisions[-1]` — a DeploymentState with no revisions
    at all is a caller-contract violation and raises IndexError rather than
    being silently handled).

    Two facts the Gate can read are never set here, deliberately:
    `dry_run_diff` has no source in this function's inputs (a real diff
    needs cluster I/O, which this pure function must not do), and
    `target_exists` doesn't apply — a DeploymentState describes an already
    -observed deployment, so existence is implicit; a "not found" outcome
    belongs to whatever lookup step tries to build one and comes up empty.
    Both are optional as far as the Gate is concerned, so omitting them
    here changes no behavior for the facts this function does produce.
    """
    return {
        "healthy_replicas": deployment_state.healthy_replicas,
        "pdb_min_available": deployment_state.pdb_min_available,
        "protected": deployment_state.namespace in protected_zones,
        "has_rollback_target": len(deployment_state.revisions) >= 2,
        "revision": deployment_state.revisions[-1],
        "mid_batch": deployment_state.mid_batch,
    }
