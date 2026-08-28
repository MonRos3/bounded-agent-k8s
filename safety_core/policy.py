"""Policy: the default tier and reversibility for each allowed tool, and the
set of zones the operator has marked off-limits regardless of tool.
"""

from __future__ import annotations

from dataclasses import dataclass

from safety_core.types import Tier


@dataclass(frozen=True)
class Rule:
    """The default disposition for one tool, before live-state facts adjust it.

    `reversible` is the tool's baseline reversibility. A RollbackPlanner may
    still find a specific invocation has no plan even when the rule says the
    tool is generally reversible — the Gate treats "no plan found" for that
    action as authoritative over this default.
    """

    tool: str
    default_tier: Tier
    reversible: bool


@dataclass(frozen=True)
class Policy:
    """The configured rule set: what's allowed, its default tier and
    reversibility, and which zones are protected outright.

    Immutable and domain-agnostic — `rules` and `protected_zones` are
    supplied by the caller (e.g. loaded from k8s_agent config); Policy
    assigns no meaning to the strings beyond lookup.
    """

    rules: list[Rule]
    protected_zones: set[str]

    def is_allowed(self, tool: str) -> bool:
        """Return True if `tool` has a configured Rule.

        An unconfigured tool is denied — fail closed, never fall through to
        an implicit allow.
        """
        raise NotImplementedError

    def rule_for(self, tool: str) -> Rule | None:
        """Return the Rule configured for `tool`, or None if unconfigured."""
        raise NotImplementedError

    def is_protected(self, zone: str) -> bool:
        """Return True if `zone` is a member of protected_zones."""
        raise NotImplementedError
