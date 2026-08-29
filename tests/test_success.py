"""check_regression() behavior and the SuccessDefiner double's contract."""

from __future__ import annotations

import pytest

from conftest import load_json_fixture
from safety_core.success import SuccessCriterion, check_regression
from safety_core.types import Action, State

REGRESSION_CASES = load_json_fixture("regression_3.json")


@pytest.mark.parametrize("case", REGRESSION_CASES, ids=[c["name"] for c in REGRESSION_CASES])
def test_check_regression_per_fixture(case):
    criterion = SuccessCriterion(**case["criterion"])
    assert check_regression(criterion, case["observed"]) == case["expected_regression"]


@pytest.mark.parametrize(
    "comparison,target,observed_value,expected",
    [
        ("gte", 5, 5, False),
        ("gte", 5, 6, False),
        ("gte", 5, 4, True),
        ("lte", 5, 5, False),
        ("lte", 5, 4, False),
        ("lte", 5, 6, True),
        ("eq", 5, 5, False),
        ("eq", 5, 4, True),
        ("eq", 5, 6, True),
    ],
    ids=[
        "gte_no_regression_when_observed_equals_target",
        "gte_no_regression_when_observed_exceeds_target",
        "gte_regression_when_observed_below_target",
        "lte_no_regression_when_observed_equals_target",
        "lte_no_regression_when_observed_below_target",
        "lte_regression_when_observed_exceeds_target",
        "eq_no_regression_when_observed_equals_target",
        "eq_regression_when_observed_below_target",
        "eq_regression_when_observed_above_target",
    ],
)
def test_check_regression_across_comparison_operators(comparison, target, observed_value, expected):
    criterion = SuccessCriterion(metric="test_metric", target=target, baseline=0, comparison=comparison)
    observed = {"test_metric": observed_value}
    assert check_regression(criterion, observed) == expected


def test_success_definer_double_returns_expected_criterion_shape(fake_success_definer):
    action = Action(tool="noop", args={}, rationale="")
    state = State(facts={})

    criterion = fake_success_definer.define(action, state)

    assert isinstance(criterion, SuccessCriterion)
    assert criterion.metric and criterion.comparison
