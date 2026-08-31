# Bounded Kubernetes AI Agent Proof-of-Concept

## What it is

A bounded AI agent for Kubernetes operations: an operator describes a
problem in natural language, an LLM proposes a structured action, and a
deterministic safety envelope — not the model — decides what actually
happens. Alongside it, a separate, operator-owned SOC 2
compliance-verification capability scans the cluster and produces a
posture report. The two-plane model, in a sentence: **the agent acts
within the envelope; the operator verifies the envelope, independently.**

The core design principle: the model proposes, deterministic code
disposes. The LLM's judgment is advisory; every safety-critical decision
lives in testable, deterministic logic outside the model's reasoning
loop. Approved actions execute against a real cluster, everything is
audited under one trace id, and if an action regresses, a predetermined
deterministic rollback fires automatically — no re-classification, no
model involvement.

## What you can use it for

**Safe delegation of routine cluster toil** — scaling, restarts,
resource-limit tweaks, recycling a stuck pod — to an AI agent, without
handing that agent unbounded power over your cluster. For a team that
wants the convenience of natural-language operations without the risk of
an LLM having open-ended authority in production: reversible, narrow
actions auto-execute; consequential ones require a human's explicit
approval, with a real dry-run preview; anything touching a protected
zone or with no path back is blocked outright, with no override.

**Point-in-time compliance posture evidence** for the Kubernetes layer —
a real Kubescape scan against the SOC 2 framework, rendered as a
report and persisted as a durable, honestly-framed evidence artifact,
run independently of (and without needing) the agent at all.

## Quickstart

Prerequisites — four independently-checkable layers: a Python venv,
Docker (for MiniStack), system CLIs (Ollama, minikube/kubectl,
kubescape), and this repo's code. Full installation steps, environment
variables, and troubleshooting: **[docs/SETUP.md](./docs/SETUP.md)**.

Once set up:

```sh
make verify        # confirms all four layers are up, tells you which isn't if not
make cli            # the agent's interactive REPL
make compliance      # the operator's compliance scan + posture report
```

## Tech stack & AWS mapping

Runs entirely locally by design, with the same code path to production —
verified, not just claimed:

| Local (this repo) | Production equivalent | What actually swaps |
|---|---|---|
| minikube | Amazon EKS | Nothing in `ClusterClient` — built on standard `kubeconfig`, works against any reachable cluster unmodified |
| MiniStack (`localhost:4566`) proxying to Ollama | Amazon Bedrock | `ModelClient`'s `LAB_USE_AWS=1` flag switches the same `boto3` `bedrock-runtime` client to real AWS — same `converse()` call, same code |
| `FileAuditSink` (`audit_logs/*.jsonl`) | CloudWatch Logs | `AuditSink` is an interface designed to support this — **not built** here; production would add a `CloudWatchAuditSink` |
| Kubescape (local CLI via `subprocess`) | Kubescape, same CLI, against the real EKS cluster | Nothing swaps — Kubescape is cluster-agnostic |
| Local/test credentials | A scoped IAM role (least privilege) | A deployment-time operational choice, not code this repo enforces |

The first two rows are the load-bearing claim — same safety code, local
and in production, only endpoints swap — and they're true today, in the
actual client code. The last two are stated honestly as not built,
rather than implied to be symmetric with the first two.

## Architecture

Two independent planes sharing a repo, not a shared codebase:

- **`safety_core/`** — the deterministic safety spine. Zero
  Kubernetes/cloud/LLM-specific code (a structural guarantee, checked by
  `make verify-architecture`, not just asserted). Domain behavior enters
  only through injected interfaces: `Policy`/`Gate`, `RollbackPlanner`,
  `SuccessDefiner`, `AuditSink`.
- **`k8s_agent/`** — the agent plane. Depends on `safety_core/`
  (one-way, proven); supplies the Kubernetes-specific implementations of
  its interfaces and the LLM/CLI/cluster-I/O layers around them.
- **`compliance/`** — the operator plane. Depends on **neither** — a
  fully separate verification path, not a feature built on the same
  base.

**The model proposes, the deterministic gate disposes**: `Gate.classify`
is the single decision point for every action, consulting injected
collaborators, never the model's own advisory note. The full
propose → screen → validate → classify → act → observe → regress →
recover pipeline, the Gate's exact blast-radius logic, and the recovery
loop's model-free guarantee are documented in depth in
**[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)**.

## Learn more

- **[docs/SETUP.md](./docs/SETUP.md)** — full installation, running the
  tests, coverage philosophy, troubleshooting.
- **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** — the deep design:
  the full request lifecycle, `safety_core/`'s interfaces, the
  blast-radius/tier/rollback logic, observability, the recovery loop.
- **[docs/USAGE.md](./docs/USAGE.md)** — using both planes in depth: the
  operator CLI, the approval flow, watching the four streams, running
  compliance scans and reading the evidence.
- **[docs/RUNNING_A_DEMO.md](./docs/RUNNING_A_DEMO.md)** — a guided
  walkthrough of the tier system, automatic recovery, and a compliance
  scan.
- **[EVAL.md](./EVAL.md)** — the LLM eval suite: designed-scenario
  accuracy and boundary fail-safe rate, the probabilistic counterpart to
  the deterministic unit tests.
- **[docs/FOLLOWUPS.md](./docs/FOLLOWUPS.md)** — known gaps and
  deferred work, documented honestly with rationale.

## Honest scope

This is **a working demonstration of the architecture** — every claim
above is backed by code that runs and tests that pass, verified live
throughout its own development, not just designed on paper. It is
**not a production deployment**: no real IAM scoping, no CloudWatch
audit sink, a single-node demo cluster, and a handful of consciously
deferred simplifications documented (with rationale, not excuses) in
[docs/FOLLOWUPS.md](./docs/FOLLOWUPS.md).

Not yet built:

- **Kubescape remediate → rescan loop** — scanning and reporting exist;
  nothing acts on a finding automatically. Given compliance is
  operator-owned verification by design, "remediation" here would mean
  surfacing a suggested fix for a human to apply, never an automatic
  mutation — there's no gate or agent involvement to route it through.
- **Web UI** — the operator console is terminal-only.
