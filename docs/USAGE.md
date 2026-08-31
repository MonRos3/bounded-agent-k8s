# Usage

How to use the two planes in depth, once your environment is set up (see
[SETUP.md](./SETUP.md)). For the design behind any of this, see
[ARCHITECTURE.md](./ARCHITECTURE.md). For a guided walkthrough rather
than reference material, see [RUNNING_A_DEMO.md](./RUNNING_A_DEMO.md).

## The operator CLI (the agent plane)

The interactive way — a `rich`-formatted REPL that shows the curated
decision path and, on `APPROVE`-tier, prompts for approve/reject before
executing:

```sh
make cli                  # or: python3 -m k8s_agent.cli
```

Or call the loop directly (still the right way to script something
non-interactively, e.g. from `handle_code_push`):

```python
from k8s_agent.agent import run_agent_loop
from k8s_agent.model_client import ModelClient
from k8s_agent.cluster import ClusterClient
from k8s_agent.audit_sink import StdoutAuditSink
from safety_core.guardrails import Guardrails
from safety_core.audit import Auditor

result = run_agent_loop(
    "The healthy-web deployment in bounded-agent-demo needs to scale to 4 replicas.",
    model_client=ModelClient(),
    cluster_client=ClusterClient(),
    guardrails=Guardrails(),
    auditor=Auditor(StdoutAuditSink()),
)
print(result.outcome, result.decision)
```

This runs the full screen → propose → validate → classify → act → audit
pipeline against your live stack (see [ARCHITECTURE.md](./ARCHITECTURE.md)
for what each step does): `StdoutAuditSink` prints one JSON line per
audit step (trace id, action, decision, detail), and `result.decision`
carries the gate's tier, its reason, and (when relevant) the rollback
plan and success criterion.

### The curated decision path

Every request renders as: `request` → `screened` → `proposed` →
`validated` → `classified` → `action`, color-coded by tier — green
`AUTO`, yellow `APPROVE`, red `BLOCK`. This is deliberately not a log;
full detail lives in the audit stream (below).

### The approval flow (`APPROVE`-tier)

Before asking approve/reject, the prompt shows: the operator's original
request, the model's proposed action and advisory note, the gate's tier
and reason, the scope, a real Kubernetes server-side dry-run diff when
one is available (falling back to the requested change itself when it
isn't), and the rollback plan. Approve calls the same
`execute_approved_action` the automatic path uses — there's no separate,
second execution mechanism for the human-approved case. Reject stops;
the REPL loops for the next request.

### `BLOCK`

Terminal. There is no override in the code — the CLI has no call site
that could execute a blocked action, by construction, not by convention.

### If a reversible action regresses

For any reversible action with a success criterion — whether it executed
automatically or a human just approved it — the CLI shows a second,
clearly-separated `── recovery ──` block once the observe cycle
completes: the observed value, the regression verdict, and (only on
regression) the automatic rollback firing and its result. This is a
summary of what already happened, not a live progress stream — there's
no mid-wait indicator during the observe wait itself.

## Watching the system

Four streams, each for a different audience:

1. **The operator terminal** — `make cli`. The curated decision view
   described above.
2. **The audit stream** — `tail -f audit_logs/<file>.jsonl` (the CLI
   prints the exact path at startup). One JSON line per step of every
   trace, in full: `trace_id`, `timestamp`, `step`, `action`, `decision`,
   `detail`. Use the trace id printed in the operator terminal to pull
   the full detail behind one decision:
   `grep <trace-id> audit_logs/<file>.jsonl`.
3. **Ollama, verbose** — the model's raw request/response. If Ollama is
   running as a local process, its own stdout shows each request; if
   it's containerized, `docker logs -f ollama` (or your container's
   name).
4. **Docker/MiniStack, verbose** — `docker logs -f ministack` shows the
   Bedrock-proxy round trips between `ModelClient` and Ollama.

## The compliance capability (the operator plane)

A separate, **operator-owned** capability — no LLM, no gate, no agent
involvement anywhere in it (see [ARCHITECTURE.md](./ARCHITECTURE.md)'s
two-plane model). Invoked separately, on purpose: the agent's REPL is
`make cli`; compliance verification is its own command, run by a human.

```sh
make seed-insecure                                      # a namespace with deliberate misconfigurations
make compliance NAMESPACE=bounded-agent-demo-insecure    # guaranteed findings, for the demo
make compliance                                          # the realistic default: scans the whole cluster
make compliance NAMESPACE=... FRAMEWORK=nsa               # override the framework (default: soc2)
```

Kubescape scans against the **SOC 2** framework by default, and the
report shows the overall posture (controls passed/failed), failing
findings by severity (control ID, name, affected resources, what
failed), and — printed in the report itself, not buried in docs — an
honest framing line: this is **evidence toward SOC 2 compliance for the
Kubernetes infrastructure layer, not a SOC 2 certification**. SOC 2 is
an organizational audit performed by a licensed auditor, covering
controls well beyond Kubernetes configuration.

### Evidence artifacts

Every run writes a durable, timestamped evidence artifact to
`compliance_reports/` (gitignored): a structured `.json` and a
human-readable `.md`, both carrying the same honest framing line — the
mature version of "is this compliant" is a file you can keep and hand to
an auditor, not a terminal scroll.

### SOC 2 vs. NSA: a real, confirmed difference, not an assumption

If you also try the NSA framework against the same namespace (`make
compliance NAMESPACE=bounded-agent-demo-insecure FRAMEWORK=nsa` — see
`manifests/vulnerable/`'s own header comments), don't expect the same
findings. Kubescape's SOC 2 control set targets entirely different
concerns than NSA's pod-hardening checks — secrets/key management,
admin access restriction, network segmentation, encryption — not
container `securityContext` or resource limits. The same insecure
namespace genuinely fails different SOC 2 controls (missing
`NetworkPolicy`, mainly) than the ones its manifests were built to trip
under NSA — confirmed empirically while building this (M6.2), not
assumed; see `compliance/scan.py`'s and `tests/test_compliance_scan.py`'s
comments for the full finding.
