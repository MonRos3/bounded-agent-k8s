"""Domain-agnostic value types shared across the safety core.

These carry data only, no behavior beyond what a value type needs. Domain
layers (e.g. k8s_agent/) populate them; safety_core/ reads their shape but
assigns no domain meaning to the strings or dict keys they carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from safety_core.rollback import RollbackPlan
    from safety_core.success import SuccessCriterion


class Tier(Enum):
    """The three dispositions a Gate can assign to a proposed action."""

    AUTO = "auto"
    APPROVE = "approve"
    BLOCK = "block"


@dataclass(frozen=True)
class Action:
    """A structured action proposed by the model, before any safety review.

    `tool` names the operation in domain terms (e.g. "delete_pod"); `args`
    carries its parameters; `rationale` is the model's advisory justification
    and must never be trusted for safety decisions.
    """

    tool: str
    args: dict[str, Any]
    rationale: str


@dataclass(frozen=True)
class State:
    """A snapshot of live system state, opaque to safety_core.

    `facts` is a domain-supplied dict; safety_core reads keys out of it but
    assigns no domain meaning to them. A dry-run diff, when the caller has
    one, arrives as facts["dry_run_diff"] so the Gate can consume it without
    a signature change.
    """

    facts: dict[str, Any]


@dataclass(frozen=True)
class Decision:
    """The Gate's verdict on a proposed action.

    `rollback` and `success` are None when the collaborating RollbackPlanner
    / SuccessDefiner determined no plan or criterion applies to this action.
    """

    tier: Tier
    reason: str
    reversible: bool
    scope: str
    rollback: RollbackPlan | None
    success: SuccessCriterion | None
