"""The full propose -> screen -> validate -> classify -> act -> audit loop.
Wires together every prior milestone: M1's safety_core (Guardrails, Auditor,
the Gate via classify_live), M2's ClusterClient, and M3.1's ModelClient —
with M3.2's own trust-boundary checkpoint (validate_and_convert) between
the untrusted model and the deterministic gate.

This module does no classification and no new execution logic: the Gate
(via classify_live) remains the sole authority on tier, and every mutation
reuses an existing ClusterClient method.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from k8s_agent.classify_live import classify_live
from k8s_agent.cluster import ClusterClient
from k8s_agent.model_client import ModelClient
from k8s_agent.policy_config import DEMO_POLICY
from k8s_agent.prompt import build_tool_schema
from k8s_agent.proposal_types import ProposedAction
from k8s_agent.validation import validate_and_convert
from safety_core.audit import Auditor
from safety_core.guardrails import Guardrails
from safety_core.types import Action, Decision, Tier

# tool -> which args key holds the identifier ClusterClient needs as `name`.
# Trusted without re-checking here: validate_and_convert already guaranteed
# these keys exist (per TOOL_ARG_HINTS) and are strings.
_NAME_ARG_KEY: dict[str, str] = {
    "get_pod_logs": "pod",
    "scale_deployment": "deployment",
    "restart_deployment": "deployment",
    "update_resource_limits": "deployment",
    "delete_pod": "pod",
    "delete_persistent_volume_claim": "pvc",
}

# tool -> how to execute it via ClusterClient. get_pod_logs has no entry —
# it's read-only, nothing to execute (not a gap: M2.2 never built one
# because there's nothing to mutate).
_EXECUTORS: dict[str, Any] = {
    "scale_deployment": lambda c, name, ns, args: c.scale_deployment(name, ns, args["target_replicas"]),
    "restart_deployment": lambda c, name, ns, args: c.restart_deployment(name, ns),
    "update_resource_limits": lambda c, name, ns, args: c.update_resource_limits(
        name, ns, args["container"], memory=args.get("memory_limit")
    ),
    "delete_pod": lambda c, name, ns, args: c.delete_pod(name, ns),
    "delete_persistent_volume_claim": lambda c, name, ns, args: c.delete_persistent_volume_claim(name, ns),
}

_NOT_A_GATE_DECISION_SCOPE = "audit"


class AgentOutcome(Enum):
    """Where a run of the loop stopped."""

    INPUT_REJECTED = "input_rejected"
    VALIDATION_REJECTED = "validation_rejected"
    DECIDED = "decided"


@dataclass(frozen=True)
class AgentResult:
    trace_id: str
    outcome: AgentOutcome
    proposed: ProposedAction | None
    action: Action | None
    decision: Decision | None
    surfaced_message: str


def run_agent_loop(
    operator_request: str,
    *,
    model_client: ModelClient,
    cluster_client: ClusterClient,
    guardrails: Guardrails,
    auditor: Auditor,
) -> AgentResult:
    """Run one operator request through the full loop. See module docstring
    for the pipeline; each stopping point records its own audit step so the
    trail distinguishes "rejected before the model saw it," "rejected at
    the trust boundary before the gate," and "the gate decided."
    """
    trace_id = auditor.new_trace()

    screen_result = guardrails.screen_input(operator_request)
    if not screen_result.passed:
        auditor.record(
            "input_rejected",
            trace_id=trace_id,
            action=_placeholder_action("", {}, ""),
            decision=_placeholder_decision(f"Input guardrail tripped: {', '.join(screen_result.flagged)}."),
            detail={"operator_request": guardrails.redact_output(operator_request)},
        )
        return AgentResult(trace_id, AgentOutcome.INPUT_REJECTED, None, None, None, "Request rejected by input guardrail.")

    schema = build_tool_schema(DEMO_POLICY)
    proposed = model_client.propose(operator_request, schema)
    auditor.record(
        "proposed",
        trace_id=trace_id,
        action=_placeholder_action(proposed.tool, proposed.args, guardrails.redact_output(proposed.advisory_note)),
        decision=_placeholder_decision("Model proposal recorded; not yet validated or classified."),
        detail={"raw_response": guardrails.redact_output(proposed.raw_response)},
    )

    action = validate_and_convert(proposed, DEMO_POLICY)
    if action is None:
        auditor.record(
            "validation_rejected",
            trace_id=trace_id,
            action=_placeholder_action(proposed.tool, proposed.args, guardrails.redact_output(proposed.advisory_note)),
            decision=_placeholder_decision(
                "Rejected at the validation trust boundary: unknown tool or malformed args — never reached the gate."
            ),
            detail={},
        )
        return AgentResult(
            trace_id,
            AgentOutcome.VALIDATION_REJECTED,
            proposed,
            None,
            None,
            "Proposal rejected: not a valid, allow-listed action.",
        )

    name = action.args[_NAME_ARG_KEY[action.tool]]
    namespace = action.args["namespace"]
    decision = classify_live(action, name, namespace, cluster_client)

    surfaced_message = guardrails.redact_output(_act(decision, action, name, namespace, cluster_client))

    auditor.record("classified", trace_id=trace_id, action=action, decision=decision, detail={})

    return AgentResult(trace_id, AgentOutcome.DECIDED, proposed, action, decision, surfaced_message)


def handle_code_push(
    commit_message: str,
    diff_summary: str,
    *,
    model_client: ModelClient,
    cluster_client: ClusterClient,
    guardrails: Guardrails,
    auditor: Auditor,
) -> AgentResult:
    """STUB — demonstrates that a code-push event could feed the same loop
    as an operator's natural-language request. NOT a real git hook: no git
    integration of any kind, just a translation of (commit_message,
    diff_summary) into an operator_request-shaped string, delegated to
    run_agent_loop unchanged.
    """
    operator_request = f"A commit was pushed: {commit_message!r}. Diff summary: {diff_summary}"
    return run_agent_loop(
        operator_request, model_client=model_client, cluster_client=cluster_client, guardrails=guardrails, auditor=auditor
    )


def _act(decision: Decision, action: Action, name: str, namespace: str, cluster_client: ClusterClient) -> str:
    """Act on the gate's tier: AUTO executes for real (via the matching
    ClusterClient method, or a no-op note for read-only tools with nothing
    to execute); APPROVE/BLOCK never mutate anything, they only surface a
    message for a human. Not redacted here — the caller applies
    guardrails.redact_output to whatever this returns.
    """
    if decision.tier == Tier.AUTO:
        executor = _EXECUTORS.get(action.tool)
        if executor is None:
            return f"Read-only action '{action.tool}' — no cluster mutation needed."
        result = executor(cluster_client, name, namespace, action.args)
        status = "succeeded" if result.success else "failed"
        return f"Executed '{action.tool}' ({status}): {result.detail}"

    if decision.tier == Tier.APPROVE:
        return f"Approval required for '{action.tool}' (args: {action.args}). Reason: {decision.reason}. No action taken — awaiting human sign-off."

    return f"Blocked and escalated: '{action.tool}'. Reason: {decision.reason}."


def _placeholder_action(tool: str, args: dict[str, Any], rationale: str) -> Action:
    return Action(tool=tool, args=args, rationale=rationale)


def _placeholder_decision(reason: str) -> Decision:
    """A structural placeholder for audit steps that happen before a real
    Gate verdict exists — NOT a real classification. Same pattern already
    used by safety_core.rollback.RollbackRegistry.invoke() for the same
    reason: AuditEvent requires both action and decision on every event.
    """
    return Decision(
        tier=Tier.AUTO,
        reason=reason,
        reversible=False,
        scope=_NOT_A_GATE_DECISION_SCOPE,
        rollback=None,
        success=None,
    )
