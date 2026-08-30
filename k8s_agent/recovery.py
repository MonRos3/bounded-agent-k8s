"""The post-execution observe -> regress -> recover cycle. Wired in by
run_agent_loop's AUTO path and the CLI's post-approval path, both right
after execute_approved_action.

The model has ZERO involvement anywhere in this module: check_regression
is safety_core's pure function, the RollbackPlan/SuccessCriterion were
both fixed at classify time by the Gate's own collaborators, and rollback
execution is a deterministic ClusterClient action. This module never
imports ModelClient — the invariant is true by construction, not just by
convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from k8s_agent.cluster import ClusterClient, ExecutionResult
from safety_core.audit import Auditor
from safety_core.rollback import RollbackRegistry
from safety_core.success import check_regression
from safety_core.types import Action, Decision

# Tools whose Action doesn't directly name a Deployment -- resolved via
# ownerReferences instead. Deliberately narrower than classify_live's own
# _POD_SCOPED_TOOLS: get_pod_logs never reaches this module (read-only,
# filtered out by should_observe_and_recover before any resolution runs).
_POD_SCOPED_RECOVERY_TOOLS = {"delete_pod"}


class RecoveryOutcome(Enum):
    """Where one observe_and_recover call landed."""

    SKIPPED = "skipped"
    NO_REGRESSION = "no_regression"
    REGRESSED_AND_RECOVERED = "regressed_and_recovered"
    REGRESSED_ROLLBACK_FAILED = "regressed_rollback_failed"


@dataclass(frozen=True)
class RecoveryResult:
    outcome: RecoveryOutcome
    observed: dict[str, int] | None
    rollback_execution: ExecutionResult | None


def should_observe_and_recover(action: Action, decision: Decision) -> bool:
    """True only for a mutating action (excludes get_pod_logs, the one
    read-only tool) that classify time actually attached both a
    SuccessCriterion and a RollbackPlan to. Everything else — BLOCK,
    read-only, or a target with no rollback path — has nothing to
    observe or recover, and skips the cycle cleanly.
    """
    return action.tool != "get_pod_logs" and decision.success is not None and decision.rollback is not None


def resolve_recovery_target(action: Action, namespace: str, cluster_client: ClusterClient) -> str:
    """The Deployment name to observe/roll back. Must be called BEFORE
    execute_approved_action for delete_pod: its target pod won't exist to
    resolve an owner from afterward. Every other mutating tool already
    names its Deployment directly in action.args.
    """
    if action.tool in _POD_SCOPED_RECOVERY_TOOLS:
        return cluster_client.resolve_pod_owner(action.args["pod"], namespace)
    return action.args["deployment"]


def observe_and_recover(
    action: Action,
    decision: Decision,
    deployment: str,
    namespace: str,
    cluster_client: ClusterClient,
    auditor: Auditor,
    trace_id: str,
    *,
    observe: Callable[..., dict[str, int]] | None = None,
) -> RecoveryResult:
    """Observe the real post-execution outcome, check it for regression
    against the SuccessCriterion fixed at classify time, and — only on
    regression — invoke the RollbackPlan fixed at classify time. Every
    step is audited under `trace_id`.

    `observe` defaults to the real cluster_client.observe_outcome;
    production never passes anything else. Tests inject a stub returning
    a below-target value to trigger recovery deterministically, without
    depending on real rollout timing — the forced-regression mechanism is
    test-injection only, never a production code path that fakes
    regression.
    """
    if not should_observe_and_recover(action, decision):
        return RecoveryResult(RecoveryOutcome.SKIPPED, None, None)

    observe_fn = observe or cluster_client.observe_outcome
    criterion = decision.success
    assert criterion is not None  # should_observe_and_recover already guaranteed this

    observed = observe_fn(deployment, namespace, criterion.metric)
    auditor.record("observed", trace_id=trace_id, action=action, decision=decision, detail={"observed": observed})

    regressed = check_regression(criterion, observed)
    auditor.record(
        "regression_checked",
        trace_id=trace_id,
        action=action,
        decision=decision,
        detail={"regressed": regressed, "observed": observed, "target": criterion.target},
    )

    if not regressed:
        return RecoveryResult(RecoveryOutcome.NO_REGRESSION, observed, None)

    plan = decision.rollback
    assert plan is not None  # should_observe_and_recover already guaranteed this
    rollback_execution = cluster_client.execute_rollback(plan.method, plan.detail)

    registry = RollbackRegistry()
    registry.register(trace_id, plan)
    event = registry.invoke(trace_id)
    auditor.record(
        event.step,
        trace_id=trace_id,
        action=event.action,
        decision=event.decision,
        detail={**event.detail, "execution_success": rollback_execution.success},
    )

    outcome = (
        RecoveryOutcome.REGRESSED_AND_RECOVERED
        if rollback_execution.success
        else RecoveryOutcome.REGRESSED_ROLLBACK_FAILED
    )
    return RecoveryResult(outcome, observed, rollback_execution)
