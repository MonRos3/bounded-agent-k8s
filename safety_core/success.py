"""Success/regression definitions: given a proposed action and state, decide
what "it worked" means, and later check observed data against that
definition. The comparison itself is a pure function — no I/O, no domain
knowledge of the metric beyond the criterion's own fields.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from safety_core.types import Action, State


@dataclass(frozen=True)
class SuccessCriterion:
    """What must hold, after an action executes, for it to count as a success.

    `metric` names the observable in domain terms (e.g. "ready_replica_count");
    `target` is the value that counts as success; `baseline` is its value
    before the action ran; `comparison` names how target and an observed
    value relate (e.g. "gte", "eq") so check_regression can evaluate it
    without domain knowledge of what the metric measures.
    """

    metric: str
    target: Any
    baseline: Any
    comparison: str


class SuccessDefiner(ABC):
    """Domain interface: produces a SuccessCriterion for an action, if one
    applies.
    """

    @abstractmethod
    def define(self, action: Action, state: State) -> SuccessCriterion | None:
        """Return the SuccessCriterion that determines whether `action`
        succeeded, or None if success is not measurable for this action.
        """
        ...


def check_regression(criterion: SuccessCriterion, observed: dict[str, Any]) -> bool:
    """Pure function: return True if `observed` shows a regression against
    `criterion` (i.e. the success comparison fails), False otherwise.

    Takes only its arguments — no I/O, no globals, no live-cluster access.
    """
    raise NotImplementedError
