"""Typed view over Kubernetes cluster data — the k8s-layer counterpart to
the opaque State.facts dict safety_core consumes. Kubernetes domain
knowledge (what a replica/PDB/revision is) lives here, not in safety_core/,
and this module never imports from safety_core/: the translation is
one-directional, k8s_agent -> facts dict -> safety_core.
"""

from __future__ import annotations

from dataclasses import dataclass


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
