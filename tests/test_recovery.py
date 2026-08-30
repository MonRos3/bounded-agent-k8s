"""The observe -> regress -> recover cycle: its own responsibility,
distinct from raw ClusterClient I/O smoke tests. Pure/stubbed tests for
the entry-condition and target-resolution logic need no live cluster;
the cycle itself (observe_and_recover) is proven live, against a seeded
cluster, using an injected `observe` stub to force regression
deterministically -- the forced-regression mechanism is test-injection
only, production always observes for real.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from kubernetes import client, config

from k8s_agent.cluster import ClusterClient, ExecutionResult
from k8s_agent.recovery import (
    RecoveryOutcome,
    observe_and_recover,
    resolve_recovery_target,
    should_observe_and_recover,
)
from safety_core.audit import AuditEvent, AuditSink, Auditor
from safety_core.rollback import RollbackPlan
from safety_core.success import SuccessCriterion
from safety_core.types import Action, Decision, Tier

_NAMESPACE = "bounded-agent-demo"
_HEALTHY_DEPLOYMENT = "healthy-web"


class FakeAuditSink(AuditSink):
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)


def _scale_action(target: int) -> Action:
    return Action(
        tool="scale_deployment",
        args={"namespace": _NAMESPACE, "deployment": _HEALTHY_DEPLOYMENT, "target_replicas": target},
        rationale="",
    )


def _decision_with(*, success: SuccessCriterion | None, rollback: RollbackPlan | None) -> Decision:
    return Decision(
        tier=Tier.AUTO, reason="test", reversible=rollback is not None, scope="scale_deployment",
        rollback=rollback, success=success,
    )


def _criterion(target: int, baseline: int) -> SuccessCriterion:
    return SuccessCriterion(metric="healthy_replicas", target=target, baseline=baseline, comparison="gte")


def _scale_to_plan(prior_replicas: int) -> RollbackPlan:
    return RollbackPlan(
        method="scale_to",
        detail={"namespace": _NAMESPACE, "deployment": _HEALTHY_DEPLOYMENT, "replicas": prior_replicas},
        target_state={"replicas": prior_replicas},
    )


def _update_resource_limits_action(memory: str) -> Action:
    return Action(
        tool="update_resource_limits",
        args={"namespace": _NAMESPACE, "deployment": _HEALTHY_DEPLOYMENT, "container": "web", "memory_limit": memory},
        rationale="",
    )


def _rollout_undo_plan(target_revision: int) -> RollbackPlan:
    """Deliberately mirrors K8sRollbackPlanner's real detail shape for a
    non-scale tool: {**action.args, "target_revision": ...} -- so this
    test exercises the exact plan shape the real planner would build,
    not a hand-simplified stand-in.
    """
    return RollbackPlan(
        method="rollout_undo",
        detail={
            "namespace": _NAMESPACE,
            "deployment": _HEALTHY_DEPLOYMENT,
            "container": "web",
            "memory_limit": "unused-once-rolled-back",
            "target_revision": target_revision,
        },
        target_state={"revision": target_revision},
    )


def _container_memory_limit(namespace: str, deployment: str, container: str) -> str | None:
    dep = client.AppsV1Api().read_namespaced_deployment(deployment, namespace)
    for c in dep.spec.template.spec.containers:
        if c.name == container:
            return (c.resources.limits or {}).get("memory") if c.resources else None
    return None


def _wait_for_new_revision(cluster: ClusterClient, deployment: str, namespace: str, previous_count: int) -> list[int]:
    """The Deployment controller creates a new ReplicaSet (and assigns
    its revision annotation) asynchronously after a template-changing
    patch — reading revisions back immediately can race it. Polls until
    the revision list has genuinely grown, so callers never compute a
    rollback target off a stale list. Same pattern as
    tests/test_cluster_smoke.py's helper of the same name.
    """
    deadline = time.monotonic() + 10
    revisions = cluster.get_deployment_state(deployment, namespace).revisions
    while len(revisions) <= previous_count and time.monotonic() < deadline:
        time.sleep(0.5)
        revisions = cluster.get_deployment_state(deployment, namespace).revisions
    return revisions


# --- should_observe_and_recover: pure logic, no cluster needed ---


def test_should_observe_and_recover_true_when_reversible_with_criterion():
    decision = _decision_with(success=_criterion(5, 4), rollback=_scale_to_plan(4))
    assert should_observe_and_recover(_scale_action(5), decision) is True


def test_should_observe_and_recover_false_for_read_only_tool():
    action = Action(tool="get_pod_logs", args={"namespace": _NAMESPACE, "pod": "x"}, rationale="")
    decision = _decision_with(success=_criterion(4, 4), rollback=_scale_to_plan(4))
    assert should_observe_and_recover(action, decision) is False


def test_should_observe_and_recover_false_when_no_success_criterion():
    decision = _decision_with(success=None, rollback=_scale_to_plan(4))
    assert should_observe_and_recover(_scale_action(5), decision) is False


def test_should_observe_and_recover_false_when_no_rollback_plan():
    decision = _decision_with(success=_criterion(5, 4), rollback=None)
    assert should_observe_and_recover(_scale_action(5), decision) is False


# --- resolve_recovery_target: pure logic against a stub cluster client ---


def test_resolve_recovery_target_reads_deployment_arg_directly():
    cluster_client = MagicMock()

    target = resolve_recovery_target(_scale_action(5), _NAMESPACE, cluster_client)

    assert target == _HEALTHY_DEPLOYMENT
    cluster_client.resolve_pod_owner.assert_not_called()


def test_resolve_recovery_target_resolves_pod_owner_for_delete_pod():
    cluster_client = MagicMock()
    cluster_client.resolve_pod_owner.return_value = _HEALTHY_DEPLOYMENT
    action = Action(tool="delete_pod", args={"namespace": _NAMESPACE, "pod": "healthy-web-abc123"}, rationale="")

    target = resolve_recovery_target(action, _NAMESPACE, cluster_client)

    assert target == _HEALTHY_DEPLOYMENT
    cluster_client.resolve_pod_owner.assert_called_once_with("healthy-web-abc123", _NAMESPACE)


# --- observe_and_recover: live cluster, forced regression via injected observer ---


@pytest.fixture(scope="module")
def cluster() -> ClusterClient:
    try:
        config.load_kube_config()
    except Exception as exc:
        pytest.skip(f"no kubeconfig available: {exc}")

    try:
        client.CoreV1Api().list_namespace(limit=1, _request_timeout=5)
    except Exception as exc:
        pytest.skip(f"cluster not reachable: {exc}")

    return ClusterClient()


@pytest.mark.integration
def test_regression_triggers_deterministic_rollback(cluster: ClusterClient):
    before = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
    requested = before.desired_replicas + 1
    action = _scale_action(requested)
    decision = _decision_with(
        success=_criterion(requested, before.desired_replicas), rollback=_scale_to_plan(before.desired_replicas)
    )
    sink = FakeAuditSink()
    auditor = Auditor(sink)
    trace_id = auditor.new_trace()

    try:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, requested)

        forced_below_target = lambda deployment, namespace, metric: {"healthy_replicas": before.desired_replicas}
        result = observe_and_recover(
            action, decision, _HEALTHY_DEPLOYMENT, _NAMESPACE, cluster, auditor, trace_id, observe=forced_below_target
        )

        assert result.outcome == RecoveryOutcome.REGRESSED_AND_RECOVERED
        assert result.rollback_execution is not None and result.rollback_execution.success

        after = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
        assert after.desired_replicas == before.desired_replicas

        steps = [e.step for e in sink.events]
        assert steps == ["observed", "regression_checked", "rollback_invoked"]
        assert {e.trace_id for e in sink.events} == {trace_id}
    finally:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, before.desired_replicas)


@pytest.mark.integration
def test_no_regression_no_rollback(cluster: ClusterClient):
    before = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
    requested = before.desired_replicas + 1
    action = _scale_action(requested)
    decision = _decision_with(
        success=_criterion(requested, before.desired_replicas), rollback=_scale_to_plan(before.desired_replicas)
    )
    auditor = Auditor(FakeAuditSink())
    trace_id = auditor.new_trace()

    try:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, requested)

        forced_meets_target = lambda deployment, namespace, metric: {"healthy_replicas": requested}
        result = observe_and_recover(
            action, decision, _HEALTHY_DEPLOYMENT, _NAMESPACE, cluster, auditor, trace_id, observe=forced_meets_target
        )

        assert result.outcome == RecoveryOutcome.NO_REGRESSION
        assert result.rollback_execution is None

        after = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
        assert after.desired_replicas == requested
    finally:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, before.desired_replicas)


@pytest.mark.integration
def test_recovery_never_calls_the_model(cluster: ClusterClient):
    """The deterministic-recovery invariant, executable: a stand-in
    ModelClient sits in scope throughout a forced-regression recovery run
    and is never touched -- observe_and_recover has no parameter to
    receive one through in the first place.
    """
    before = cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE)
    requested = before.desired_replicas + 1
    action = _scale_action(requested)
    decision = _decision_with(
        success=_criterion(requested, before.desired_replicas), rollback=_scale_to_plan(before.desired_replicas)
    )
    auditor = Auditor(FakeAuditSink())
    trace_id = auditor.new_trace()
    model_client = MagicMock()

    try:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, requested)

        forced_below_target = lambda deployment, namespace, metric: {"healthy_replicas": before.desired_replicas}
        observe_and_recover(
            action, decision, _HEALTHY_DEPLOYMENT, _NAMESPACE, cluster, auditor, trace_id, observe=forced_below_target
        )

        model_client.propose.assert_not_called()
        assert model_client.mock_calls == []
    finally:
        cluster.scale_deployment(_HEALTHY_DEPLOYMENT, _NAMESPACE, before.desired_replicas)


@pytest.mark.integration
def test_regression_on_template_mutating_tool_triggers_deterministic_rollback(cluster: ClusterClient):
    """Proves the recovery loop is now complete for revision-based
    rollbacks, not just scale: a real template change, forced regression,
    real rollback via "rollout_undo" -- verified by reading the live
    template back, not by trusting the outcome.
    """
    container = "web"
    original_memory = _container_memory_limit(_NAMESPACE, _HEALTHY_DEPLOYMENT, container)
    before_count = len(cluster.get_deployment_state(_HEALTHY_DEPLOYMENT, _NAMESPACE).revisions)
    action = _update_resource_limits_action("777Mi")
    auditor = Auditor(FakeAuditSink())
    trace_id = auditor.new_trace()

    try:
        cluster.update_resource_limits(_HEALTHY_DEPLOYMENT, _NAMESPACE, container, memory="777Mi")
        assert _container_memory_limit(_NAMESPACE, _HEALTHY_DEPLOYMENT, container) == "777Mi"

        revisions = _wait_for_new_revision(cluster, _HEALTHY_DEPLOYMENT, _NAMESPACE, before_count)
        target_revision = revisions[-2]
        decision = _decision_with(success=_criterion(4, 4), rollback=_rollout_undo_plan(target_revision))

        forced_regression = lambda deployment, namespace, metric: {"healthy_replicas": 0}
        result = observe_and_recover(
            action, decision, _HEALTHY_DEPLOYMENT, _NAMESPACE, cluster, auditor, trace_id, observe=forced_regression
        )

        assert result.outcome == RecoveryOutcome.REGRESSED_AND_RECOVERED
        assert _container_memory_limit(_NAMESPACE, _HEALTHY_DEPLOYMENT, container) == original_memory
    finally:
        cluster.update_resource_limits(_HEALTHY_DEPLOYMENT, _NAMESPACE, container, memory=original_memory)


def test_observe_and_recover_passes_resolved_deployment_to_execute_rollback_not_plan_detail():
    """Regression guard: delete_pod's action.args never has a
    "deployment" key (only "pod"), so a real rollout_undo plan for it
    can't carry one in plan.detail either. observe_and_recover must use
    the already-resolved deployment/namespace it observed against, not
    trust plan.detail's own (possibly absent) values.
    """
    action = Action(tool="delete_pod", args={"namespace": _NAMESPACE, "pod": "healthy-web-abc123"}, rationale="")
    decision = _decision_with(
        success=_criterion(4, 4),
        rollback=RollbackPlan(
            method="rollout_undo",
            detail={"namespace": _NAMESPACE, "pod": "healthy-web-abc123", "target_revision": 3},
            target_state={"revision": 3},
        ),
    )
    cluster_client = MagicMock()
    cluster_client.execute_rollback.return_value = ExecutionResult(success=True, detail={})
    auditor = Auditor(FakeAuditSink())

    observe_and_recover(
        action, decision, _HEALTHY_DEPLOYMENT, _NAMESPACE, cluster_client, auditor, "trace-1",
        observe=lambda d, n, m: {"healthy_replicas": 0},
    )

    _, detail_arg = cluster_client.execute_rollback.call_args[0]
    assert detail_arg["deployment"] == _HEALTHY_DEPLOYMENT
    assert detail_arg["namespace"] == _NAMESPACE
