"""Rollback planning: given a proposed action and state, decide how (if at
all) the action could be undone. Domain layers supply the concrete strategy;
safety_core only defines the contract and tracks which plan belongs to which
trace.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from safety_core.audit import AuditEvent
from safety_core.types import Action, State


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

    def register(self, trace_id: str, plan: RollbackPlan) -> None:
        """Associate `plan` with `trace_id` for later invocation."""
        raise NotImplementedError

    def invoke(self, trace_id: str) -> AuditEvent:
        """Execute the rollback plan registered for `trace_id` and return the
        resulting audit event.
        """
        raise NotImplementedError
