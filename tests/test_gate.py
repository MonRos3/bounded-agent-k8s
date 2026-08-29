"""Gate.classify() behavior, driven by fixtures/inputs_9.json.

Each fixture case's name states the rule it encodes; the parametrize id
mirrors that name so a failing case reads as the rule that broke.
"""

from __future__ import annotations

import pytest

from conftest import load_json_fixture
from safety_core.gate import Gate
from safety_core.types import Action, State, Tier

INPUT_CASES = load_json_fixture("inputs_9.json")


@pytest.mark.parametrize("case", INPUT_CASES, ids=[c["name"] for c in INPUT_CASES])
def test_gate_classifies_per_fixture(case, gate_policy, fake_rollback_planner, fake_success_definer):
    action = Action(**case["action"])
    state = State(facts=case["state"])
    gate = Gate(gate_policy, fake_rollback_planner, fake_success_definer)

    decision = gate.classify(action, state)

    assert decision.tier == Tier(case["expected_tier"])
    assert case["expected_reason_contains"] in decision.reason


def test_gate_blocks_unconfigured_tool_default_deny(gate_policy, fake_rollback_planner, fake_success_definer):
    action = Action(tool="not_a_configured_tool", args={}, rationale="")
    state = State(facts={})
    gate = Gate(gate_policy, fake_rollback_planner, fake_success_definer)

    decision = gate.classify(action, state)

    assert decision.tier == Tier.BLOCK
    assert "not an allowed action" in decision.reason
