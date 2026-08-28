"""The Gate: the single deterministic decision point between a proposed
action and execution. Classifies blast radius and assigns a Tier by
consulting injected collaborators — it holds no policy of its own and never
instantiates the collaborators it depends on.
"""

from __future__ import annotations

from safety_core.policy import Policy
from safety_core.rollback import RollbackPlanner
from safety_core.success import SuccessDefiner
from safety_core.types import Action, Decision, State


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
        raise NotImplementedError
