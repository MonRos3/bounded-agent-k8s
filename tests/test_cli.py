"""Light tests for cli.py's testable parts: the approve/reject decision
logic with stubbed input, and that approval (only) reaches
execute_approved_action. No real console, no real cluster, no real model —
this task's tests are about the decision logic, not the rendering.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from rich.console import Console

from k8s_agent.agent import AgentOutcome, AgentResult
from k8s_agent.cli import handle_approve_tier, prompt_approval, render_approval_prompt
from k8s_agent.cluster import ExecutionResult
from k8s_agent.cluster_types import DryRunDiff
from safety_core.guardrails import Guardrails
from safety_core.types import Action, Decision, Tier


class FakeClusterClient:
    """Trivial execute-only stub — this test only cares whether the right
    method is (or isn't) called, not classification. dry_run_diff
    defaults to None (no preview available) so tests that don't care
    about the diff still exercise render_approval_prompt's fallback path
    without needing to stub it themselves.
    """

    def scale_deployment(self, name, namespace, replicas):
        return ExecutionResult(success=True, detail={"replicas": replicas})

    def update_resource_limits(self, name, namespace, container, *, cpu=None, memory=None):
        return ExecutionResult(success=True, detail={"container": container})

    def dry_run_diff(self, action):
        return None


def _approve_result() -> AgentResult:
    action = Action(
        tool="update_resource_limits",
        args={"namespace": "bounded-agent-demo", "deployment": "healthy-web", "container": "web", "memory_limit": "512Mi"},
        rationale="",
    )
    decision = Decision(
        tier=Tier.APPROVE,
        reason="Reversible but consequential.",
        reversible=True,
        scope="update_resource_limits",
        rollback=None,
        success=None,
    )
    return AgentResult(
        trace_id="trace-1",
        outcome=AgentOutcome.DECIDED,
        proposed=None,
        action=action,
        decision=decision,
        surfaced_message="Approval required for 'update_resource_limits' ...",
    )


@pytest.mark.parametrize("response", ["approve", "Approve", "a", "yes", "y"])
def test_prompt_approval_accepts_common_affirmatives(response):
    assert prompt_approval(ask=lambda *a, **k: response) is True


@pytest.mark.parametrize("response", ["reject", "no", "n", "", "nope", "  "])
def test_prompt_approval_rejects_anything_else(response):
    assert prompt_approval(ask=lambda *a, **k: response) is False


def test_approve_response_executes_action():
    cluster_client = MagicMock(wraps=FakeClusterClient())
    console = Console(quiet=True)

    handle_approve_tier(
        "bump memory on healthy-web",
        _approve_result(),
        cluster_client,
        console,
        Guardrails(),
        ask=lambda *a, **k: "approve",
    )

    cluster_client.update_resource_limits.assert_called_once_with(
        "healthy-web", "bounded-agent-demo", "web", memory="512Mi"
    )


def test_reject_response_does_not_execute():
    cluster_client = MagicMock(wraps=FakeClusterClient())
    console = Console(quiet=True)

    handle_approve_tier(
        "bump memory on healthy-web",
        _approve_result(),
        cluster_client,
        console,
        Guardrails(),
        ask=lambda *a, **k: "reject",
    )

    cluster_client.update_resource_limits.assert_not_called()


def test_render_approval_prompt_shows_real_diff_when_available():
    cluster_client = MagicMock()
    cluster_client.dry_run_diff.return_value = DryRunDiff(
        kind="field_delta", changes={"replicas": (2, 3)}, description=None
    )
    console = Console(record=True, width=200)

    render_approval_prompt(console, "scale healthy-web", _approve_result(), Guardrails(), cluster_client)

    output = console.export_text()
    assert "server-side dry-run" in output
    assert "replicas" in output
    assert "2 -> 3" in output
    assert "requested change" not in output


def test_render_approval_prompt_falls_back_when_no_diff():
    cluster_client = MagicMock()
    cluster_client.dry_run_diff.return_value = None
    console = Console(record=True, width=200)

    render_approval_prompt(console, "scale healthy-web", _approve_result(), Guardrails(), cluster_client)

    output = console.export_text()
    assert "requested change" in output
    assert "server-side dry-run" not in output
