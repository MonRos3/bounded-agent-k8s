"""Typed view over Kubernetes cluster data — the k8s-layer counterpart to
the opaque State.facts dict safety_core consumes. Kubernetes domain
knowledge (what a replica/PDB/revision is) lives here, not in safety_core/,
and this module never imports from safety_core/: the translation is
one-directional, k8s_agent -> facts dict -> safety_core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeploymentState:
    """A typed snapshot of one Deployment's observed cluster state.

    `revisions` is ordered oldest to newest; the current revision is
    `revisions[-1]`. Deliberately richer than what's translated into facts
    today (e.g. `desired_replicas` isn't yet read by the Gate) — this type
    catches the type-safety a plain dict gives up, independent of which
    fields safety_core currently consumes.
    """

    namespace: str
    healthy_replicas: int
    desired_replicas: int
    pdb_min_available: int | None
    revisions: list[int]
    mid_batch: bool


@dataclass(frozen=True)
class DryRunDiff:
    """A read-only preview of what a proposed action would change, from a
    real Kubernetes server-side dry run (or, for the one simulated
    action, a descriptor consistent with that simulation).

    `kind` says what shape `changes` has: "field_delta" (changes maps
    field name -> (old, new), from a real dry-run patch/update),
    "removal" (a delete that a real dry-run confirmed would be accepted;
    changes is empty, description says what would be removed), or
    "simulated_removal" (delete_persistent_volume_claim's simulated path
    — no real dry run was performed at all; description says so).
    """

    kind: str
    changes: dict[str, tuple[Any, Any]]
    description: str | None
