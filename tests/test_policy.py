"""Policy allow-list, rule lookup, and protected-zone checks."""

from __future__ import annotations

from safety_core.policy import Policy, Rule
from safety_core.types import Tier


def _policy() -> Policy:
    return Policy(
        rules=[Rule(tool="scale_deployment", default_tier=Tier.AUTO, reversible=True)],
        protected_zones={"kube-system"},
    )


def test_is_allowed_true_for_configured_tool():
    assert _policy().is_allowed("scale_deployment") is True


def test_is_allowed_false_for_unconfigured_tool_default_deny():
    assert _policy().is_allowed("delete_cluster") is False


def test_rule_for_returns_configured_rule():
    assert _policy().rule_for("scale_deployment") == Rule(
        tool="scale_deployment", default_tier=Tier.AUTO, reversible=True
    )


def test_rule_for_returns_none_for_unconfigured_tool():
    assert _policy().rule_for("delete_cluster") is None


def test_is_protected_true_for_protected_zone():
    assert _policy().is_protected("kube-system") is True


def test_is_protected_false_for_unprotected_zone():
    assert _policy().is_protected("web") is False
