"""The interactive operator console: a REPL that is the sole home for
human interaction in this project. run_agent_loop (M3.2) stays
non-interactive — it classifies and returns; this module prompts for a
request, renders the curated decision path, and on APPROVE-tier runs the
approval prompt and calls execute_approved_action (M-HITL.1) only when a
human approves. BLOCK is terminal: there is no call site that could
override it.

The operator terminal is curated — the decision path, not every sub-step.
Full detail (every AuditEvent) goes to a separate, tail-able file via
FileAuditSink so the two audiences (a human deciding in the moment, and a
full audit trail) get two destinations.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt

from k8s_agent.agent import AgentOutcome, AgentResult, execute_approved_action, run_agent_loop
from k8s_agent.audit_sink import FileAuditSink
from k8s_agent.cluster import ClusterClient
from k8s_agent.cluster_types import DryRunDiff
from k8s_agent.model_client import ModelClient
from k8s_agent.recovery import observe_and_recover, resolve_recovery_target, should_observe_and_recover
from safety_core.audit import Auditor
from safety_core.guardrails import Guardrails
from safety_core.types import Tier

_TIER_STYLE = {Tier.AUTO: "green", Tier.APPROVE: "yellow", Tier.BLOCK: "red"}
_AUDIT_LOG_DIR = Path(__file__).resolve().parent.parent / "audit_logs"


def _format_args(args: dict[str, Any], guardrails: Guardrails) -> str:
    """Render an args dict for display: each value redacted (it may
    ultimately trace back to untrusted model or operator text) and
    markup-escaped (so a value containing literal "[...]" can't be
    misread as rich markup).
    """
    parts = [f"{key}={escape(guardrails.redact_output(str(value)))}" for key, value in args.items()]
    return ", ".join(parts)


def render_decision_path(console: Console, operator_request: str, result: AgentResult, guardrails: Guardrails) -> None:
    """The curated decision view: trace id, then screened -> proposed ->
    validated -> classified -> action as labeled, tier-colored lines.
    Stops early at whichever stage the loop stopped at. This is the
    operator's decision view — curated, not a log dump; the full trail is
    in the audit stream.
    """
    console.rule(f"trace {result.trace_id}")
    console.print(f"[bold]request[/bold]     {escape(operator_request)}")

    if result.outcome == AgentOutcome.INPUT_REJECTED:
        console.print("[red]screened[/red]    rejected by the input guardrail")
        console.print(f"             {escape(result.surfaced_message)}")
        return
    console.print("[green]screened[/green]    passed")

    if result.proposed is not None:
        console.print(f"[bold]proposed[/bold]    {result.proposed.tool}({_format_args(result.proposed.args, guardrails)})")
        note = guardrails.redact_output(result.proposed.advisory_note)
        if note:
            console.print(f"             advisory: {escape(note)}")

    if result.outcome == AgentOutcome.VALIDATION_REJECTED:
        console.print("[red]validated[/red]   rejected — not a valid, allow-listed action")
        return
    console.print("[green]validated[/green]   passed")

    decision = result.decision
    assert decision is not None, "DECIDED outcome always carries a Decision"
    style = _TIER_STYLE[decision.tier]
    console.print(f"[bold]classified[/bold]  [{style}]{decision.tier.value.upper()}[/{style}]  {escape(decision.reason)}")
    console.print(f"[bold]action[/bold]      [{style}]{escape(result.surfaced_message)}[/{style}]")


def _render_dry_run_diff(diff: DryRunDiff, guardrails: Guardrails) -> str:
    """Render a real dry-run result for the approval prompt. Labeled
    honestly per `diff.kind`: "field_delta"/"removal" mean a real
    server-side dry run happened; "simulated_removal" (the PVC-delete
    path) never touched the real dry-run API and must never claim to.
    """
    if diff.kind == "field_delta":
        parts = [
            f"{field}: {escape(guardrails.redact_output(str(old)))} -> {escape(guardrails.redact_output(str(new)))}"
            for field, (old, new) in diff.changes.items()
        ]
        return f"[bold]predicted effect (server-side dry-run)[/bold] {', '.join(parts)}"
    if diff.kind == "removal":
        return f"[bold]predicted effect (server-side dry-run)[/bold] {escape(guardrails.redact_output(diff.description or ''))}"
    return (
        "[bold]predicted effect (simulated — no real dry-run performed)[/bold] "
        f"{escape(guardrails.redact_output(diff.description or ''))}"
    )


def render_approval_prompt(
    console: Console, operator_request: str, result: AgentResult, guardrails: Guardrails, cluster_client: ClusterClient
) -> None:
    """Everything a human needs before deciding, shown once more as one
    contained unit right before the prompt: request, proposed action +
    advisory note, tier + reason, scope, the predicted effect, and the
    rollback plan. The predicted effect is a real Kubernetes server-side
    dry run when one is available; falls back to echoing the requested
    change (the M-HITL.2 placeholder) for read-only tools or when the
    dry run itself fails — the prompt is always populated, richer when a
    real preview exists, honest when it doesn't.
    """
    action = result.action
    decision = result.decision
    assert action is not None and decision is not None, "APPROVE tier always carries an Action and a Decision"

    lines = [
        f"[bold]request[/bold]  {escape(operator_request)}",
        f"[bold]proposed[/bold] {action.tool}({_format_args(action.args, guardrails)})",
    ]
    if result.proposed is not None:
        note = guardrails.redact_output(result.proposed.advisory_note)
        if note:
            lines.append(f"[bold]advisory[/bold] {escape(note)}")
    lines.append(f"[bold]tier[/bold]     [yellow]{decision.tier.value.upper()}[/yellow] — {escape(decision.reason)}")
    lines.append(f"[bold]scope[/bold]    {escape(decision.scope)}")

    diff = cluster_client.dry_run_diff(action)
    if diff is not None:
        lines.append(_render_dry_run_diff(diff, guardrails))
    else:
        lines.append(
            "[bold]requested change[/bold] (no dry-run preview available — "
            f"showing the proposed change itself): {_format_args(action.args, guardrails)}"
        )

    if decision.rollback is not None:
        rollback = decision.rollback
        lines.append(
            f"[bold]rollback[/bold] method={escape(rollback.method)}, "
            f"target_state={_format_args(rollback.target_state, guardrails)}"
        )
    else:
        lines.append("[bold]rollback[/bold] none")

    console.print(Panel("\n".join(lines), title="Approval required", border_style="yellow"))


def prompt_approval(*, ask: Callable[..., str] = Prompt.ask) -> bool:
    """Pure decision logic: read a response via the injected `ask` and
    return True for approve. No console, no cluster access — the one
    function this task's tests target directly.
    """
    response = ask("Approve this action? [approve/reject]", default="reject")
    return response.strip().lower() in {"approve", "a", "yes", "y"}


def handle_approve_tier(
    operator_request: str,
    result: AgentResult,
    cluster_client: ClusterClient,
    console: Console,
    guardrails: Guardrails,
    auditor: Auditor,
    *,
    ask: Callable[..., str] = Prompt.ask,
) -> None:
    """Show the approval prompt, read the decision, and act on it: approve
    calls execute_approved_action (the only call site outside the AUTO
    path — never reimplemented here), then — for a reversible action with
    a success criterion — runs the same observe/regress/recover cycle the
    AUTO path runs, audited under the same trace id; reject stops,
    showing the rejection. Either way, control returns to the REPL loop
    for the next request. No recovery detail is surfaced here (M5.3's
    job) — it only shows up in the audit stream.
    """
    render_approval_prompt(console, operator_request, result, guardrails, cluster_client)

    if prompt_approval(ask=ask):
        action = result.action
        decision = result.decision
        assert action is not None and decision is not None, "APPROVE tier always carries an Action and a Decision"

        namespace = action.args["namespace"]
        recovery_target = None
        if should_observe_and_recover(action, decision):
            # Resolved before execution: delete_pod's target pod won't
            # exist to resolve an owner from once it's been deleted.
            recovery_target = resolve_recovery_target(action, namespace, cluster_client)

        execution = execute_approved_action(action, cluster_client)

        if recovery_target is not None:
            observe_and_recover(action, decision, recovery_target, namespace, cluster_client, auditor, result.trace_id)

        status = "succeeded" if execution.success else "failed"
        console.print(f"[green]approved[/green] — executed ({status}): {_format_args(execution.detail, guardrails)}")
    else:
        console.print("[red]rejected[/red] — no action taken.")


def run_repl(
    *,
    model_client: ModelClient,
    cluster_client: ClusterClient,
    guardrails: Guardrails,
    auditor: Auditor,
    console: Console | None = None,
    ask: Callable[..., str] = Prompt.ask,
    request: Callable[..., str] = Prompt.ask,
) -> None:
    """The operator loop: prompt for a request, run it through
    run_agent_loop, render the curated decision path, and hand off to the
    approval prompt on APPROVE-tier. Blank input, "quit"/"exit", EOF, or
    Ctrl-C stop the REPL. Never calls input()/prompts anywhere but here
    and in handle_approve_tier — run_agent_loop stays non-interactive.
    """
    console = console or Console()
    while True:
        try:
            operator_request = request("\n[bold]operator[/bold]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]exiting[/dim]")
            break

        if not operator_request.strip() or operator_request.strip().lower() in {"quit", "exit"}:
            break

        result = run_agent_loop(
            operator_request,
            model_client=model_client,
            cluster_client=cluster_client,
            guardrails=guardrails,
            auditor=auditor,
        )
        render_decision_path(console, operator_request, result, guardrails)

        if result.outcome == AgentOutcome.DECIDED and result.decision is not None and result.decision.tier == Tier.APPROVE:
            handle_approve_tier(operator_request, result, cluster_client, console, guardrails, auditor, ask=ask)


def _ensure_cluster_reachable() -> ClusterClient:
    try:
        k8s_config.load_kube_config()
        k8s_client.CoreV1Api().list_namespace(limit=1, _request_timeout=5)
    except Exception as exc:
        print(f"cli: cluster not reachable ({exc}) — start/seed it first (make seed).", file=sys.stderr)
        sys.exit(1)
    return ClusterClient()


def main() -> None:
    cluster_client = _ensure_cluster_reachable()
    audit_log_path = _AUDIT_LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"

    console = Console()
    console.print(f"[dim]audit stream: tail -f {audit_log_path}[/dim]")

    run_repl(
        model_client=ModelClient(),
        cluster_client=cluster_client,
        guardrails=Guardrails(),
        auditor=Auditor(FileAuditSink(audit_log_path)),
        console=console,
    )


if __name__ == "__main__":
    main()
