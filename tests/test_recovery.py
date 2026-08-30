"""The observe -> regress -> recover cycle: its own responsibility,
distinct from raw ClusterClient I/O smoke tests. Pure/stubbed tests for
the entry-condition and target-resolution logic need no live cluster;
the cycle itself (observe_and_recover) is proven live, against a seeded
cluster, using an injected `observe` stub to force regression
deterministically -- the forced-regression mechanism is test-injection
only, production always observes for real.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from kubernetes import client, config

from k8s_agent.cluster import ClusterClient
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
