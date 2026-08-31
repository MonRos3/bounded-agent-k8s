# Architecture

How this actually works, for a reader who wants the design, not just the
commands. For "how do I run it," see [SETUP.md](./SETUP.md) and
[USAGE.md](./USAGE.md).

![Design overview for the bounded Kubernetes AI agent](../bounded_agent_k8s.png)

## The core principle

**The model proposes, deterministic code disposes.** An LLM's judgment is
advisory only — it never executes anything directly, and its own
assessment of risk (an "advisory note" attached to its proposal) is
never trusted for a safety decision. Every safety-critical decision lives
in testable, deterministic logic outside the model's reasoning loop.
Concretely: nothing the model returns is ever used for more than "what
tool, with what arguments, on what target" — tier, blast radius, and
reversibility are computed independently of anything the model said about
them.

## The two-plane model

This system has two independent planes, not one:

- **The agent plane** (`k8s_agent/`) — acts *within* the envelope
  `safety_core/` defines. An operator describes a problem in natural
  language; the agent proposes, validates, classifies, and (within its
  tier) executes.
- **The operator plane** (`compliance/`) — verifies the envelope itself,
  independently. A human runs a Kubescape scan against a real hardening
  framework and gets a posture report. No LLM, no gate, no agent
  involvement anywhere in this plane.

These aren't two features built on a shared base — `compliance/` imports
neither `safety_core/` nor `k8s_agent/` (see `make verify-architecture`
for the runnable proof). It's a fully separate verification path that
happens to live in the same repository, on purpose: the agent acting
safely and the cluster actually being compliant are different questions,
and conflating their code would blur that.

## The request lifecycle

The real order, from `k8s_agent/agent.py`'s `run_agent_loop` — not a
paraphrase of milestone names, verified directly against the code:

1. **screen** — `Guardrails.screen_input()` runs on the raw operator
   text, *before* the model ever sees it. Catches known prompt-injection
   phrasing; fails closed on uncertainty.
2. **propose** — `ModelClient.propose()`: the LLM proposes a structured
   `ProposedAction` (tool + args + an advisory note). Untrusted — parsing
   never trusts structure and degrades to a fail-closed sentinel rather
   than raising on a malformed response.
3. **validate** — `validate_and_convert()`: the trust boundary between
   the model and the gate. Is the tool allow-listed? Do the args match
   the expected schema? A failure here never reaches the gate at all.
4. **classify** — `classify_live()`, wrapping `safety_core.gate.Gate`:
   the single deterministic decision point. Given the validated `Action`
   and live cluster state, it assigns a `Tier` — `AUTO`, `APPROVE`, or
   `BLOCK` — consulting the injected `RollbackPlanner` and
   `SuccessDefiner`. This is "the gate"; classification and gating are
   the same step, not two.
5. **act** — `AUTO` executes immediately via `execute_approved_action`
   (the one dispatch path, reused by both the automatic and
   human-approved cases). `APPROVE` returns without executing — a human
   decides via the CLI. `BLOCK` is terminal; there is no override path in
   the code, anywhere.
6. **observe** — for a reversible action with a success criterion,
   `observe_outcome()` waits for the real cluster to settle, using
   Kubernetes' own rollout-completion signal (the same computation
   `kubectl rollout status` uses), not a heuristic.
7. **regress** — `safety_core.success.check_regression()`, a pure
   function: does the observed state meet the criterion fixed at
   classify time?
8. **recover** — on regression, `execute_rollback()` invokes the
   `RollbackPlan` fixed at classify time — deterministic execution of a
   predetermined plan. No re-classification, no re-planning, no model
   involvement of any kind. This is asserted directly in tests, not just
   true by convention.

Every step is recorded under one `trace_id`, from the first guardrail
check through a recovery's rollback, whether the run stops after step 1
or runs all eight.

## `safety_core/`'s interfaces, and why domain-independence is load-bearing

`safety_core/` contains zero Kubernetes-, Terraform-, LLM-, or
cloud-specific code — not a style preference, a structural guarantee
`make verify-architecture` checks by grep, with one documented exception
(a dict key name that happens to read like a Kubernetes term; see the
allowlist and its comment in `scripts/verify_architecture.sh` for the
full reasoning). Domain behavior enters only through injected
interfaces:

- **`Policy` / `Rule`** — the allow-list and default tier per tool.
  Default-deny: an unconfigured tool is always blocked.
- **`Gate`** — the sole classifier. Receives its collaborators
  (`Policy`, `RollbackPlanner`, `SuccessDefiner`) injected; never
  constructs them. See `Gate.classify`'s branch order below.
- **`RollbackPlanner` / `RollbackPlan` / `RollbackRegistry`** — "can this
  be undone, and how" is a domain question (`k8s_agent.planners.
  K8sRollbackPlanner` answers it for Kubernetes); "is there a plan, and
  what happens when it's invoked" is not.
- **`SuccessDefiner` / `SuccessCriterion` / `check_regression`** — same
  split: what "success" means for a given action is domain-specific;
  comparing an observed value against a criterion is a pure function.
- **`Guardrails`** — deterministic input screening and output redaction,
  independent of what domain the input/output is about.
- **`AuditSink` / `Auditor`** — where an audit trail goes is domain/
  deployment-specific (stdout, a file, CloudWatch in production); that
  every safety-relevant step gets recorded is not optional.

Why this matters practically, not just architecturally: every one of
these is directly unit-testable with fakes, with no cluster, no model,
and no I/O — which is exactly why `safety_core/` carries ~99% test
coverage from the unit suite alone (see [SETUP.md](./SETUP.md)'s
coverage philosophy). A class that's hard to test in isolation is
usually doing too much or reaching for a collaborator it should have
been handed instead — this design is what avoiding that looks like in
practice, not just what it's supposed to look like.

## The blast-radius / tier / rollback design

`Gate.classify`'s actual branch order (`safety_core/gate.py`), each
branch forcing `BLOCK` or continuing to the next check:

1. Is the tool allow-listed at all? (default-deny)
2. Does the target exist? (a stale view of the cluster is refused, not
   guessed at)
3. Is the target in a protected zone? (namespace membership alone
   drives this — no per-action annotation needed)
4. Is the action reversible? (`RollbackPlanner.plan()` returning `None`
   forces `BLOCK` — irreversibility is disqualifying regardless of the
   rule's default tier)
5. Does the action breach PodDisruptionBudget headroom? (current
   `healthy_replicas` vs. `pdb_min_available` — see
   [FOLLOWUPS.md](./FOLLOWUPS.md) for a known, direction-agnostic
   simplification here)
6. Otherwise: the rule's default tier, escalated to `APPROVE` if the
   target is mid-rollout.

The gate never consults the model's own advisory note for any of this.

## Observability and the trace-id design

Every step of the pipeline above, and every step of a recovery cycle,
records an `AuditEvent` under one `trace_id` per operator request. Two
audiences get two destinations (M-HITL.2's design): the operator
terminal (`k8s_agent/cli.py`) renders a **curated** decision path —
screened → proposed → validated → classified → action, tier-colored,
not a log dump — while `FileAuditSink` writes the **complete** trail to
`audit_logs/<timestamp>.jsonl`. The trace id printed in the curated view
is what lets a reader correlate the two: `grep <trace-id>
audit_logs/*.jsonl` pulls every recorded detail behind one decision,
including a recovery cycle's `observed`/`regression_checked`/
`rollback_invoked` steps when one fires.

## The recovery loop

Built across M5.1–M5.2-fix, and the one place this design goes out of
its way to prove a negative: **the model has zero involvement in
recovery, and this is asserted in a test**
(`tests/test_recovery.py::test_recovery_never_calls_the_model`), not
just true by the shape of the code. The mechanism:

- **Observe** via Kubernetes' native readiness signal — not a homegrown
  heuristic (`k8s_agent/cluster.py`'s `observe_outcome`).
- **Regress** via `safety_core.success.check_regression` — a pure
  function, no I/O, no cluster access.
- **Recover** via `ClusterClient.execute_rollback`, executing the exact
  `RollbackPlan` the Gate's `RollbackPlanner` fixed at classify time —
  before the action ever ran. Recovery doesn't re-decide anything; it
  carries out a decision already made.

## The four controls, honestly

The project's original design lists four controls constraining the
agent's influence. Three are built and tested in this repo; one is a
stated principle for a real deployment, not code here — worth being
precise about which is which:

1. **Guardrails** (model boundary) — built: `safety_core/guardrails.py`,
   input screening and output redaction.
2. **The Gate / Policy** (action boundary) — built: `safety_core/gate.py`
   + `policy.py`, deterministic allow/deny and tier assignment.
3. **Scoped IAM** (privilege floor) — **not built**. The principle —
   even a compromised gate shouldn't be able to exceed what its
   credentials allow — is real and worth stating, but this repo doesn't
   implement it: `ClusterClient`/`ModelClient` use whatever credentials
   the environment (kubeconfig, `LAB_USE_AWS`'s boto3 client) hands
   them, unscoped. Not a lower-priority gap alongside the others in
   [`docs/FOLLOWUPS.md`](./FOLLOWUPS.md) — it's called out there as the
   priority next architectural addition, with what it would concretely
   involve (a least-privilege execution role, credentials scoped
   separately from the model-facing path, and a containment test that
   proves the floor holds even when the Gate doesn't).
4. **Observability** (across every layer) — built: the trace-id/audit
   design above, plus Kubescape's compliance scanning as an independent
   verification layer.
