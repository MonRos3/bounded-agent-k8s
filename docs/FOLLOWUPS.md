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

## Priority next addition: least-privilege execution scoping

Of everything in this file, this is the one item that isn't just a
deferred simplification — it's the next real architectural addition
this project needs, not a nice-to-have alongside the rest.
[`docs/ARCHITECTURE.md`](./ARCHITECTURE.md)'s "four controls" section
already states this honestly: three of the four controls are built
(Guardrails, the Gate/Policy, Observability); Scoped IAM is not.
"Deferred" is the right word for _when_, not _whether_ — a bounded
agent whose execution credentials aren't themselves bounded still has
an unbounded worst case if the Gate is ever wrong, bypassed, or simply
hasn't been asked about a given code path yet.

What it would involve:

- **A least-privilege execution role for `ClusterClient`** — a
  Kubernetes `Role`/`ClusterRole` (or the IAM-mapped equivalent for a
  real EKS deployment, per the README's AWS mapping) scoped to exactly
  the verbs and resource types `_EXECUTORS` actually needs
  (`patch`/`delete` on `deployments`/`pods`, nothing broader) — not the
  ambient credentials of whatever kubeconfig happens to be active, which
  is what it uses today.
- **Scoped credentials for the model-facing path, distinct from the
  execution path** — `ModelClient` should never hold, or need, any
  credential capable of a cluster mutation. Today that separation is
  true only because of how the code happens to be structured, not
  because anything enforces it.
- **A containment test that actually proves the floor** — not "the Gate
  correctly blocks X" (the existing suite already covers that
  extensively), but "even if the Gate is wrong, or bypassed entirely,
  the credentials `ClusterClient` holds physically cannot do more than
  the scoped role allows." That's a different kind of test from
  anything in `tests/` today: it has to attempt an out-of-scope action
  directly against the API server using the _scoped_ credentials and
  assert it's rejected at the Kubernetes RBAC layer — independent of,
  and never routed through, whatever the Gate would have decided.

This is what "even a gate can't exceed this" — the original design
principle behind Scoped IAM — needs to mean concretely, rather than
staying a sentence in a design doc.

## Other known gaps and deferred work

- **PVC pod-owner resolution** — `delete_persistent_volume_claim` isn't
  in `classify_live`'s pod-scoped tool set, so its `pvc` argument is
  treated as a deployment name directly (the same bug class M3.2-fix
  resolved for pods, never fixed for PVCs). Never triggered in
  practice — no PVCs exist in the seed manifests, and it currently just
  BLOCKs for "target not found," which is safe, if for the wrong stated
  reason. Flagged in M3.3, still open.

- **`delete_pod`'s rollback plan doesn't target what was deleted** —
  `K8sRollbackPlanner` offers the same `rollout_undo` (revert pod
  template to a prior revision) as its "reversibility" story for _any_
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
  reader finds _pointers_ to every known gap even when the full writeup
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

## OPA / Rego for gate policy — triggered follow-up (not yet needed)

**Status:** Deliberately deferred. Documented as a triggered decision, not a gap.

The Gate's policy (tier classification: allow-list, protected zones, blast-radius
rules) is currently expressed as rules-as-data in Python (`safety_core/policy.py`,
`safety_core/gate.py`), evaluated deterministically outside the model's reasoning
loop. This is already policy-as-code in the sense that matters — declarative rules,
independently testable, inspectable — and it is 99% unit-tested and domain-independent.

**The candidate:** the gate's policy could instead be expressed in [Rego] and
evaluated by [Open Policy Agent (OPA)][opa] — the CNCF-standard policy engine for
declarative authorization, widely used in Kubernetes admission control. This would
make the policy declarative-and-separable from the agent code, hot-reloadable
without redeploying, and expressible once for multiple consumers.

**Why it is NOT adopted now:** at a single gate serving a single domain, OPA is
over-engineering. The Python gate is already correct, deterministic, and tested;
rewriting a proven, load-bearing component to gain "declarative-ness" and
"standard-ness" — neither of which is a correctness the gate currently lacks — adds
a dependency and a second language (Rego) for no present need. The risk of swapping
out the gate is highest precisely when other work (e.g. autonomy) is about to be
built on top of it.

**The trigger to adopt it:** when a second agent shares this policy engine — most
concretely, the planned Terraform agent (project two), which reuses the
domain-independent `safety_core`. Two-plus agents evaluating against one shared
policy is exactly where OPA earns its place: one declarative policy, multiple
enforcers. A secondary trigger is a need to change policy _without_ redeploying code
(e.g. tightening a rule live based on observed behavior), where OPA's hot-reload is
genuinely useful.

[opa]: https://www.openpolicyagent.org/
[Rego]: https://www.openpolicyagent.org/docs/latest/policy-language/
