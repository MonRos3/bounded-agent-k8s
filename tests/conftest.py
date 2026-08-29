"""Shared pytest fixtures and test doubles for the safety_core test suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from safety_core.policy import Policy, Rule
from safety_core.rollback import RollbackPlan, RollbackPlanner
from safety_core.success import SuccessCriterion, SuccessDefiner
from safety_core.types import Action, State, Tier

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_json_fixture(filename: str) -> list[dict]:
    """Load a fixtures/*.json file as a list of case dicts.

    A plain helper, not a pytest fixture — test modules call it directly at
    collection time to build @pytest.mark.parametrize argument lists.
    """
    with open(FIXTURES_DIR / filename) as f:
        return json.load(f)


class FakeRollbackPlanner(RollbackPlanner):
    """Reversible iff state.facts['has_rollback_target'] is truthy.

    One generic double that correctly generalizes across every fixture case
    in inputs_9.json, rather than hardcoding per-case behavior.
    """

    def plan(self, action: Action, state: State) -> RollbackPlan | None:
        if state.facts.get("has_rollback_target"):
            return RollbackPlan(method="fake_rollback", detail={}, target_state={})
        return None


class FakeSuccessDefiner(SuccessDefiner):
    """Always defines the same fixed criterion, regardless of input.

    Gate tier assertions don't depend on the criterion's content, only that
    one is attached to the Decision.
    """

    def define(self, action: Action, state: State) -> SuccessCriterion | None:
        return SuccessCriterion(metric="fake_metric", target=1, baseline=0, comparison="gte")


@pytest.fixture
def fake_rollback_planner() -> FakeRollbackPlanner:
    return FakeRollbackPlanner()


@pytest.fixture
def fake_success_definer() -> FakeSuccessDefiner:
    return FakeSuccessDefiner()


@pytest.fixture
def gate_policy() -> Policy:
    """A Policy covering every tool used in fixtures/inputs_9.json.

    Each Rule's default_tier is that tool's baseline in the *absence* of any
    state-driven override — protected zone, PDB breach, irreversibility, and
    mid-batch overrides are the Gate's job (once implemented), not the
    Policy's. Chosen so the fixture-driven Gate tests are satisfiable by a
    plausible Gate implementation without editing the tests later.
    """
    return Policy(
        rules=[
            Rule(tool="get_pod_logs", default_tier=Tier.AUTO, reversible=True),
            Rule(tool="scale_deployment", default_tier=Tier.AUTO, reversible=True),
            Rule(tool="restart_deployment", default_tier=Tier.AUTO, reversible=True),
            Rule(tool="update_resource_limits", default_tier=Tier.APPROVE, reversible=True),
            Rule(tool="delete_pod", default_tier=Tier.APPROVE, reversible=True),
            Rule(
                tool="delete_persistent_volume_claim",
                default_tier=Tier.BLOCK,
                reversible=False,
            ),
        ],
        protected_zones={"kube-system"},
    )
