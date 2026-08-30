"""System prompt and tool-schema assembly for ModelClient.propose(). The
schema is derived from the demo Policy's allow-list — the model is never
offered a tool the deterministic gate wouldn't recognize.
"""

from __future__ import annotations

import json

from safety_core.policy import Policy

_SYSTEM_PROMPT = (
    "You are a Kubernetes operations assistant. Given an operator's request "
    "and a list of allowed tools, propose exactly ONE tool call that "
    "addresses the request.\n\n"
    "Respond with ONLY a single JSON object — no prose before or after, no "
    "markdown code fences — matching exactly this shape:\n"
    '{"tool": "<one of the allowed tool names>", "args": {<tool arguments>}, '
    '"advisory_note": "<a short note on the risk/rationale of this action>"}\n\n'
    "Only propose a tool from the allowed-tools list below; never invent a "
    "tool name. Your proposal is advisory only — a separate deterministic "
    "system independently verifies and approves or blocks it before "
    "anything runs."
)

# Policy.Rule only carries tier/reversibility, not argument shapes — this
# fills that gap. Single source of truth: used both for prompting (below)
# and for validating a proposal's args (k8s_agent/validation.py). A tool
# with no entry here still appears in the schema (with an empty hint dict)
# rather than vanishing.
TOOL_ARG_HINTS: dict[str, dict[str, str]] = {
    "get_pod_logs": {"namespace": "string", "pod": "string"},
    "scale_deployment": {"namespace": "string", "deployment": "string", "target_replicas": "integer"},
    "restart_deployment": {"namespace": "string", "deployment": "string"},
    "update_resource_limits": {
        "namespace": "string",
        "deployment": "string",
        "container": "string",
        "memory_limit": "string",
    },
    "delete_pod": {"namespace": "string", "pod": "string"},
    "delete_persistent_volume_claim": {"namespace": "string", "pvc": "string"},
}


def build_tool_schema(policy: Policy) -> dict[str, dict[str, str]]:
    """The set of tools offered to the model, derived from `policy`'s
    allow-list — if the policy changes, the offered tools change with it.
    """
    return {rule.tool: TOOL_ARG_HINTS.get(rule.tool, {}) for rule in policy.rules}


def build_prompt(operator_request: str, tool_schema: dict[str, dict[str, str]]) -> str:
    """Assemble the full prompt text: system instructions + the tool
    schema + the operator's request.
    """
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"Allowed tools (schema):\n{json.dumps(tool_schema, indent=2)}\n\n"
        f"Operator request: {operator_request}"
    )
