"""Rollback planning: given a proposed action and state, decide how (if at
all) the action could be undone. Domain layers supply the concrete strategy;
safety_core only defines the contract and tracks which plan belongs to which
trace.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from safety_core.audit import AuditEvent
from safety_core.types import Action, Decision, State, Tier


@dataclass(frozen=True)
class RollbackPlan:
    """A concrete, executable undo for one action.

    `method` names the rollback mechanism in domain terms (e.g.
    "rollout_undo"); `detail` carries whatever the mechanism needs;
    `target_state` records what "undone" means so success/regression checks
    can verify the rollback actually landed.
    """

    method: str
    detail: dict[str, Any]
    target_state: dict[str, Any]


class RollbackPlanner(ABC):
    """Domain interface: produces a RollbackPlan for an action, if one exists."""

    @abstractmethod
    def plan(self, action: Action, state: State) -> RollbackPlan | None:
        """Return a RollbackPlan reversing `action` from `state`, or None if
        the action has no rollback path.
        """
        ...


class RollbackRegistry:
    """Tracks the rollback plan associated with each in-flight trace and
    invokes it on demand.

    Not domain-specific: it stores whatever RollbackPlan a RollbackPlanner
    produced, keyed by trace_id, and treats invocation as an audited step.
    Execution mechanics belong to the domain layer; this registry only
    manages the association and the invocation contract.
    """

    def __init__(self) -> None:
        self._plans: dict[str, RollbackPlan] = {}

    def register(self, trace_id: str, plan: RollbackPlan) -> None:
        """Associate `plan` with `trace_id` for later invocation."""
        self._plans[trace_id] = plan

    def invoke(self, trace_id: str) -> AuditEvent:
        """Execute the rollback plan registered for `trace_id` and return the
        resulting audit event.

        The audited Action/Decision describe the rollback invocation itself
        (register/invoke never receive one for the original proposal) — the
        event's `detail` carries the plan's target_state.
        """
        plan = self._plans[trace_id]
        action = Action(
            tool="rollback",
            args=dict(plan.detail),
            rationale=f"Automated rollback via {plan.method} for trace {trace_id}.",
        )
        decision = Decision(
            tier=Tier.AUTO,
            reason="Rollback executed to restore target_state.",
            reversible=False,
            scope=trace_id,
            rollback=None,
            success=None,
        )
        return AuditEvent(
            trace_id=trace_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            step="rollback_invoked",
            action=action,
            decision=decision,
            detail=dict(plan.target_state),
        )
