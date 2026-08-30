"""The model's raw proposal — deliberately distinct from safety_core's
Action. A ProposedAction is untrusted: it's what an LLM said it wants to
do, not yet validated against the policy allow-list or anything else.
M3.2 converts a valid ProposedAction into a real Action; an invalid one
gets rejected before ever reaching the gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProposedAction:
    """The model's structured proposal, parsed from its response.

    `raw_response` is the unparsed model output, always populated (even
    when parsing failed) — kept for the proposed-vs-executed audit trail:
    what the model actually said, regardless of what we made of it.
    """

    tool: str
    args: dict[str, Any]
    advisory_note: str
    raw_response: str
