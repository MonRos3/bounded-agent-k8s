# Known gaps and deferred work

This project's architecture is proven, not just asserted — see `make
verify-architecture` for the runnable proofs (domain-independent
`safety_core/`, the one-way `k8s_agent → safety_core` dependency,
`compliance/` as a separate sibling importing neither). What those proofs
don't and can't catch is the smaller stuff: real shortcuts and
simplifications found along the way and consciously left as-is, because
fixing them wasn't in scope for the task that found them and none of
them compromise safety. This file is that list — a strength signal, not
a to-do list. Every entry below was already flagged in code comments,
commit history, or a task's own planning notes; this just puts them all
in one place instead of leaving a reader to discover them by reading
every docstring or running the suite themselves.

- **PVC pod-owner resolution** — `delete_persistent_volume_claim` isn't
  in `classify_live`'s pod-scoped tool set, so its `pvc` argument is
  treated as a deployment name directly (the same bug class M3.2-fix
  resolved for pods, never fixed for PVCs). Never triggered in
  practice — no PVCs exist in the seed manifests, and it currently just
  BLOCKs for "target not found," which is safe, if for the wrong stated
  reason. Flagged in M3.3, still open.

- **Direction-agnostic PDB headroom** — `Gate._pdb_headroom` checks
  *current* `healthy_replicas` vs. `pdb_min_available` regardless of
  whether the action being classified would increase or decrease
  replica count, so a scale-*up* on an already-zero-headroom deployment
  BLOCKs even though scaling up can never breach a PDB floor. Found live
  during M5.3 (worked around there by giving that one demo deployment no
  PDB, rather than changing Gate logic). Over-conservative, errs safe.

- **`delete_pod`'s rollback plan doesn't target what was deleted** —
  `K8sRollbackPlanner` offers the same `rollout_undo` (revert pod
  template to a prior revision) as its "reversibility" story for *any*
  tool on a deployment with revision history, including `delete_pod` —
  but reverting a template doesn't meaningfully undo a pod deletion (the
  ReplicaSet controller already self-heals that independently, for an
  unrelated reason). Flagged during M5.2 planning; Gate/planner
  classification behavior was out of scope for every task since.

- **`handle_code_push` is a structural stub** — demonstrates that a
  code-push event could feed the same agent loop as an operator's
  request; no real git integration exists. Self-documented in its own
  docstring since M3.2; noted here for a reader scanning gaps in one
  place rather than across the whole codebase.

- **SOC 2 vs. NSA Kubescape control-set mismatch** — already fully
  documented in `README.md`'s compliance section and
  `tests/test_compliance_scan.py`'s comments (M6.2); cross-referenced
  here rather than re-explained, so this file stays the one place a
  reader finds *pointers* to every known gap even when the full writeup
  lives elsewhere.

- **Feature-level deferred work** (Kubescape remediate → rescan loop, a
  web UI) is tracked in `README.md`'s "Not yet built" section, not
  duplicated here — this file is for code-level/architectural shortcuts
  specifically, that section is for unbuilt features.

- **One known test-timing flake** —
  `tests/test_cluster_smoke.py::test_observe_outcome_reports_below_target_on_unready`
  (M5.1) deliberately races a tight 2s timeout against real pod
  scheduling and can fail under full-suite load, though it passes
  reliably in isolation; its own docstring already explains why. Not a
  code gap — a documented test-timing artifact, listed here anyway
  because this file's whole point is being the one place a reader finds
  every known rough edge, rather than discovering one by running the
  suite themselves. Left as-is per M7.1's precedent (`EVAL.md` documents
  the eval suite's own mid-batch flakiness the same way, rather than
  loosening a timeout to hide it).
