"""Real Kubernetes implementations of safety_core's injected planning
interfaces. Both operate purely on `state.facts` (the same information the
Gate itself reads) plus `action.args` — no cluster re-query — keeping them
simple, stateless, and consistent with how the M1 test doubles were
exercised.
"""

from __future__ import annotations

from safety_core.rollback import RollbackPlan, RollbackPlanner
from safety_core.success import SuccessCriterion, SuccessDefiner
from safety_core.types import Action, State


class K8sRollbackPlanner(RollbackPlanner):
    """Rollback = a rollout undo to the previous revision, whenever the
    target has one — except scale_deployment, where "undo" means scaling
    back to the prior replica count: a revision-based rollout undo never
    touches replica count at all (scaling doesn't create a new revision),
    so it can't actually reverse a scale. `has_rollback_target` is already
    computed by state_builder.build_facts (len(revisions) >= 2) — no
    re-derivation needed. Kubernetes revisions are sequential integers, so
    "the previous revision" is simply the current one minus one; no need
    to re-fetch the full history.
    """

    def plan(self, action: Action, state: State) -> RollbackPlan | None:
        if not state.facts.get("has_rollback_target"):
            return None

        if action.tool == "scale_deployment":
            prior_replicas = state.facts.get("desired_replicas")
            return RollbackPlan(
                method="scale_to",
                detail={
                    "namespace": action.args["namespace"],
                    "deployment": action.args["deployment"],
                    "replicas": prior_replicas,
                },
                target_state={"replicas": prior_replicas},
            )

        current_revision = state.facts.get("revision")
        target_revision = current_revision - 1 if current_revision is not None else None

        return RollbackPlan(
            method="rollout_undo",
            detail={**action.args, "target_revision": target_revision},
            target_state={"revision": target_revision},
        )


class K8sSuccessDefiner(SuccessDefiner):
    """For a scale, success means reaching the requested replica count. For
    every other tool, the generic bar is "at least as healthy as before" —
    a universal non-regression criterion when there's no tool-specific
    target to reach.
    """

    def define(self, action: Action, state: State) -> SuccessCriterion | None:
        healthy = state.facts.get("healthy_replicas")
        if healthy is None:
            return None

        if action.tool == "scale_deployment":
            target = action.args.get("target_replicas", healthy)
            return SuccessCriterion(metric="healthy_replicas", target=target, baseline=healthy, comparison="gte")

        return SuccessCriterion(metric="healthy_replicas", target=healthy, baseline=healthy, comparison="gte")
