"""The trust-boundary checkpoint: converts an untrusted ProposedAction into
a trusted safety_core Action, or rejects it. Fails closed — an unknown
tool, malformed args, or anything else that doesn't check out returns
None, never a best-effort guess.
"""

from __future__ import annotations

from k8s_agent.prompt import TOOL_ARG_HINTS
from k8s_agent.proposal_types import ProposedAction
from safety_core.policy import Policy
from safety_core.types import Action

_TYPE_MAP: dict[str, type] = {"string": str, "integer": int}


def validate_and_convert(proposed: ProposedAction, policy: Policy) -> Action | None:
    """Return a trusted Action if `proposed` is well-formed and allow-listed,
    else None.

    Checks: the tool is allow-listed by `policy`; `args` is a dict; every
    required arg for that tool (per TOOL_ARG_HINTS) is present with the
    right primitive type. Permissive on extra, unexpected keys — this is
    not a strict schema, just enough to keep obviously-malformed proposals
    from ever reaching the gate. `proposed.advisory_note` becomes
    `Action.rationale` — the field Action's own contract says must never be
    trusted for safety decisions, which is exactly what it is here.
    """
    if not policy.is_allowed(proposed.tool):
        return None
    if not isinstance(proposed.args, dict):
        return None

    for arg_name, type_name in TOOL_ARG_HINTS.get(proposed.tool, {}).items():
        if arg_name not in proposed.args:
            return None
        expected_type = _TYPE_MAP.get(type_name)
        if expected_type is not None and not isinstance(proposed.args[arg_name], expected_type):
            return None

    return Action(tool=proposed.tool, args=proposed.args, rationale=proposed.advisory_note)
