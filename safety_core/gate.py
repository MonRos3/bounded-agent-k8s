"""The Gate: the single deterministic decision point between a proposed
action and execution. Classifies blast radius and assigns a Tier by
consulting injected collaborators — it holds no policy of its own and never
instantiates the collaborators it depends on.
"""

from __future__ import annotations

from typing import Any

from safety_core.policy import Policy
from safety_core.rollback import RollbackPlan, RollbackPlanner
from safety_core.success import SuccessCriterion, SuccessDefiner
from safety_core.types import Action, Decision, State, Tier

_TIER_ORDER = {Tier.AUTO: 0, Tier.APPROVE: 1, Tier.BLOCK: 2}

_AUTO_REASON = (
    "Reversible, read-only-or-narrow-scope action: has a rollback target "
    "and remains within PDB headroom — auto-approved."
)
_LIVE_WORKLOAD_REASON = (
    "Reversible but consequential: this is a live workload change with a "
    "visible diff, requiring human approval."
)
_NO_BREACH_REASON = (
    "Reversible but consequential: this action does not breach the PDB "
    "floor, but still requires human approval."
)
_MID_BATCH_REASON = (
    "Reversible but consequential: this touches a mid-batch workload, "
    "requiring human approval."
)
_PROTECTED_REASON = (
    "Blocked: the target is in a protected zone; no action may proceed "
    "here regardless of tool."
)
_IRREVERSIBLE_REASON = (
    "Blocked: this action has no rollback target, making it irreversible."
)
_PDB_BREACH_REASON = (
    "Blocked: this action would breach the PDB floor (no headroom remaining)."
)


class Gate:
    """Classifies a proposed Action against live State into a Decision.

    All safety-relevant collaborators are injected at construction: Policy
    for tier/allow-list rules, RollbackPlanner for whether (and how) the
    action can be undone, and SuccessDefiner for what "worked" means. The
    Gate composes these into one Decision — it never decides tier from the
    model's own rationale, and never constructs a Policy, RollbackPlanner, or
    SuccessDefiner itself.
    """

    def __init__(
        self,
        policy: Policy,
        rollback_planner: RollbackPlanner,
        success_definer: SuccessDefiner,
    ) -> None:
        self._policy = policy
        self._rollback_planner = rollback_planner
        self._success_definer = success_definer

    def classify(self, action: Action, state: State) -> Decision:
        """Classify `action` given `state` and return a Decision.

        Composition contract: look up the Rule for action.tool via
        self._policy — an unconfigured tool, or a protected zone in
        state.facts, forces BLOCK regardless of the rule's default tier.
        Call self._rollback_planner.plan(action, state); a None result means
        the action is irreversible and forces at least APPROVE tier
        regardless of the Rule's default reversibility. Call
        self._success_definer.define(action, state) to attach the
        SuccessCriterion the caller will later evaluate via
        success.check_regression. The Decision carries whichever tier this
        composition yields — never the model's own advisory risk note.
        """
        facts = state.facts

        if not self._policy.is_allowed(action.tool):
            return self._blocked(action, f"Blocked: '{action.tool}' is not an allowed action (default-deny).")

        if facts.get("protected", False):
            return self._blocked(action, _PROTECTED_REASON)

        rule = self._policy.rule_for(action.tool)
        rollback_plan = self._rollback_planner.plan(action, state)
        reversible = rollback_plan is not None
        success_criterion = self._success_definer.define(action, state)

        if not reversible:
            return self._decision(
                action, Tier.BLOCK, _IRREVERSIBLE_REASON, reversible=False, rollback=None, success=success_criterion
            )

        headroom = self._pdb_headroom(facts)
        if headroom is not None and headroom <= 0:
            return self._decision(
                action, Tier.BLOCK, _PDB_BREACH_REASON, reversible=True, rollback=rollback_plan, success=success_criterion
            )

        tier = rule.default_tier
        if facts.get("mid_batch", False):
            tier = self._escalate(tier, Tier.APPROVE)
            reason = _MID_BATCH_REASON
        elif tier == Tier.AUTO:
            reason = _AUTO_REASON
        elif facts.get("dry_run_diff") is not None:
            reason = _LIVE_WORKLOAD_REASON
        else:
            reason = _NO_BREACH_REASON

        return self._decision(action, tier, reason, reversible=True, rollback=rollback_plan, success=success_criterion)

    def _decision(
        self,
        action: Action,
        tier: Tier,
        reason: str,
        *,
        reversible: bool,
        rollback: RollbackPlan | None,
        success: SuccessCriterion | None,
    ) -> Decision:
        """Build a Decision scoped to `action.tool` — the one field every
        call site sets the same way.
        """
        return Decision(tier=tier, reason=reason, reversible=reversible, scope=action.tool, rollback=rollback, success=success)

    def _blocked(self, action: Action, reason: str) -> Decision:
        """A BLOCK decision reached before reversibility/success were ever
        consulted (allow-list miss, protected zone) — both are moot for an
        action that will never execute.
        """
        return self._decision(action, Tier.BLOCK, reason, reversible=False, rollback=None, success=None)

    def _pdb_headroom(self, facts: dict[str, Any]) -> int | None:
        """Replicas that could still be lost before breaching the PDB floor,
        or None if the facts needed to compute it aren't present.
        """
        healthy = facts.get("healthy_replicas")
        pdb_min = facts.get("pdb_min_available")
        if healthy is None or pdb_min is None:
            return None
        return healthy - pdb_min

    def _escalate(self, tier: Tier, floor: Tier) -> Tier:
        """Return whichever of `tier`/`floor` is more restrictive."""
        return tier if _TIER_ORDER[tier] >= _TIER_ORDER[floor] else floor
