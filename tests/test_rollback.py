"""RollbackRegistry round-trip and RollbackPlanner double behavior."""

from __future__ import annotations

from safety_core.rollback import RollbackPlan, RollbackRegistry
from safety_core.types import Action, State


def test_register_then_invoke_round_trip_returns_audit_event():
    registry = RollbackRegistry()
    plan = RollbackPlan(method="rollout_undo", detail={"revision": 3}, target_state={"revision": 3})

    registry.register("trace-1", plan)
    event = registry.invoke("trace-1")

    assert event.trace_id == "trace-1"


def test_rollback_planner_double_returns_plan_when_reversible(fake_rollback_planner):
    action = Action(tool="scale_deployment", args={}, rationale="")
    state = State(facts={"has_rollback_target": True})

    plan = fake_rollback_planner.plan(action, state)

    assert plan is not None


def test_rollback_planner_double_returns_none_when_irreversible(fake_rollback_planner):
    action = Action(tool="delete_persistent_volume_claim", args={}, rationale="")
    state = State(facts={"has_rollback_target": False})

    plan = fake_rollback_planner.plan(action, state)

    assert plan is None
