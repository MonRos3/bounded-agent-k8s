"""build_facts() translation behavior, against hand-built DeploymentState
objects — no real cluster, no I/O.
"""

from __future__ import annotations

from k8s_agent.cluster_types import DeploymentState
from k8s_agent.state_builder import build_facts
from safety_core.gate import Gate
from safety_core.types import Action, State, Tier


def _deployment(
    namespace: str = "web",
    healthy_replicas: int = 4,
    desired_replicas: int = 4,
    pdb_min_available: int | None = 2,
    revisions: list[int] | None = None,
    mid_batch: bool = False,
) -> DeploymentState:
    return DeploymentState(
        namespace=namespace,
        healthy_replicas=healthy_replicas,
        desired_replicas=desired_replicas,
        pdb_min_available=pdb_min_available,
        revisions=revisions if revisions is not None else [21, 22],
        mid_batch=mid_batch,
    )


def test_rollback_history_present_has_rollback_target_true():
    facts = build_facts(_deployment(revisions=[21, 22]), protected_zones=set())

    assert facts["has_rollback_target"] is True


def test_single_revision_has_rollback_target_false():
    facts = build_facts(_deployment(revisions=[1]), protected_zones=set())

    assert facts["has_rollback_target"] is False


def test_current_revision_is_the_latest():
    facts = build_facts(_deployment(revisions=[7, 8, 9]), protected_zones=set())

    assert facts["revision"] == 9


def test_namespace_in_protected_zones_is_protected_true():
    facts = build_facts(_deployment(namespace="kube-system"), protected_zones={"kube-system"})

    assert facts["protected"] is True


def test_namespace_not_in_protected_zones_is_protected_false():
    facts = build_facts(_deployment(namespace="web"), protected_zones={"kube-system"})

    assert facts["protected"] is False


def test_pdb_configured_passes_through_min_available():
    facts = build_facts(_deployment(pdb_min_available=3), protected_zones=set())

    assert facts["pdb_min_available"] == 3


def test_pdb_absent_is_none():
    facts = build_facts(_deployment(pdb_min_available=None), protected_zones=set())

    assert facts["pdb_min_available"] is None


def test_mid_batch_flag_passes_through():
    assert build_facts(_deployment(mid_batch=True), protected_zones=set())["mid_batch"] is True
    assert build_facts(_deployment(mid_batch=False), protected_zones=set())["mid_batch"] is False


def test_build_facts_keys_match_gate_vocabulary():
    facts = build_facts(_deployment(), protected_zones=set())

    assert set(facts.keys()) == {
        "healthy_replicas",
        "pdb_min_available",
        "protected",
        "has_rollback_target",
        "revision",
        "mid_batch",
    }


def test_build_facts_output_classified_correctly_by_gate(gate_policy, fake_rollback_planner, fake_success_definer):
    facts = build_facts(
        _deployment(namespace="web", healthy_replicas=4, pdb_min_available=2, revisions=[21, 22]),
        protected_zones={"kube-system"},
    )
    action = Action(tool="scale_deployment", args={}, rationale="")
    gate = Gate(gate_policy, fake_rollback_planner, fake_success_definer)

    decision = gate.classify(action, State(facts=facts))

    assert decision.tier == Tier.AUTO
