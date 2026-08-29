"""The real Policy for the demo: the same tool tiers already validated by
the M1 suite (tests/conftest.py's gate_policy fixture), pointed at the real
seeded protected namespace instead of a unit-test placeholder.
"""

from __future__ import annotations

from safety_core.policy import Policy, Rule
from safety_core.types import Tier

DEMO_POLICY = Policy(
    rules=[
        Rule(tool="get_pod_logs", default_tier=Tier.AUTO, reversible=True),
        Rule(tool="scale_deployment", default_tier=Tier.AUTO, reversible=True),
        Rule(tool="restart_deployment", default_tier=Tier.AUTO, reversible=True),
        Rule(tool="update_resource_limits", default_tier=Tier.APPROVE, reversible=True),
        Rule(tool="delete_pod", default_tier=Tier.APPROVE, reversible=True),
        Rule(tool="delete_persistent_volume_claim", default_tier=Tier.BLOCK, reversible=False),
    ],
    protected_zones={"bounded-agent-demo-protected"},
)
