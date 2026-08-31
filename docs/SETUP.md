# Setup

Full environment setup and troubleshooting. For the short version, see
the README's Quickstart.

## Environment model

The project runs across four independently-checkable layers:

1. **Python venv** — this repo's libraries (`boto3`, `kubernetes`, `requests`, ...).
2. **Docker containers** — MiniStack, serving local Bedrock/IAM/CloudWatch
   API surfaces on `localhost:4566`.
3. **System CLIs** — Ollama (`localhost:11434`), minikube, kubectl, kubescape.
4. **Code** — `safety_core/` (domain-independent safety spine),
   `k8s_agent/` (Kubernetes-specific agent layer), `compliance/` (the
   separate operator-owned verification layer).

`make verify` checks each layer on its own and reports a ✓/✗ per layer,
so a failure tells you exactly which one is down rather than a generic
"environment not ready."

## Prerequisites

Install these yourself — they are system tools, not Python packages, and
are never installed via `requirements.txt`:

- [Docker](https://www.docker.com/) (running MiniStack)
- [minikube](https://minikube.sigs.k8s.io/) + `kubectl`
- [kubescape](https://kubescape.io/)
- [Ollama](https://ollama.com/)

## 1. Install and start each layer

**Python venv:**

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

**Ollama** (local model server):

```sh
ollama pull llama3.1
ollama serve   # if not already running as a background service
```

**MiniStack** (local Bedrock-shaped endpoint, proxying to Ollama):

```sh
docker run -d --name ministack -p 4566:4566 \
  -e MINISTACK_BEDROCK_PROXY_URL=http://host.docker.internal:11434/ \
  ministackorg/ministack:latest
```

The `MINISTACK_BEDROCK_PROXY_URL` env var is what makes MiniStack forward
`converse` calls to your real Ollama instance instead of returning a
generic mock response — without it, `ModelClient` still gets a
well-formed reply, just not a real model completion. `.env`'s
`LAB_USE_AWS` flag switches `ModelClient`/`ClusterClient` between this
local endpoint and real AWS with the same code.

**minikube** (local Kubernetes cluster):

```sh
minikube start
make seed     # applies manifests/seed/ — the demo namespaces/deployments/PDBs
```

`make reset` restores this same clean state later (e.g. after a demo run
that scaled or deleted something). `make seed`/`make reset` are also what
generate the rollout history some seeded deployments need.

For the compliance capability's deliberately-insecure demo namespace,
also run `make seed-insecure` (and `make reset-insecure` to tear it
down) — kept entirely separate from `make seed`/`make reset`.

**Verify everything is up:**

```sh
make verify
```

Checks each of the four layers independently and reports a ✓/✗ per layer,
so a failure tells you exactly which one is down rather than a generic
"environment not ready." It's fine — and expected — to have some layers
down; the point is knowing which.

`make verify-foundation` is a different, complementary check: not whether
the runtime environment is reachable, but whether the *repo itself* is
still structurally sound — expected scaffolding exists, `.env.example`
hygiene holds, a few code-quality invariants on `safety_core/` pass.
Safe to re-run any time as the project grows, not just at initial setup.

`make verify-architecture` proves this project's core structural claims
rather than just asserting them: `safety_core/` is domain-independent (a
precise, allowlist-based grep — not "eyeball it," a real violation fails
the check), the `k8s_agent → safety_core` dependency is genuinely
one-way, and `compliance/` imports neither. Each proof prints a clear
✓/✗. Known gaps these proofs don't (and aren't meant to) catch —
conscious simplifications found and deferred along the way, not hidden
ones — are documented honestly in
[`FOLLOWUPS.md`](./FOLLOWUPS.md).

`make demo-check` is a fourth, narrower check on top of `make verify`:
not just "are the four layers reachable," but "is today's demo state
actually seeded" — every deployment `manifests/seed/` and
`manifests/vulnerable/` are supposed to produce, checked live against
the cluster at the moment it runs (never a cached assumption). Useful
any time you want to confirm the cluster matches what the seed manifests
describe, not just before a demo.

## 2. Run the tests

Three commands, each a different layer of the testing story:

```sh
make test              # unit tests (109) always run and always stay fast
                        # (well under a second) — no cluster required.
                        # The other 28, integration-marked, run alongside
                        # them automatically whenever a live cluster is
                        # reachable (as it usually is in active dev), or
                        # skip gracefully (not fail) when it isn't —
                        # `make test`'s own speed and count depend on
                        # which of those is true when you run it.
make test-integration   # only the integration-marked tests — requires the
                        # live, seeded stack from step 1. Real Kubernetes
                        # I/O: ClusterClient, classify_live, the recovery
                        # cycle, Kubescape compliance scanning.
make eval RUNS=4        # the probabilistic counterpart: runs the real
                        # model N times against a 15-case corpus and
                        # reports rates, never a single pass/fail.
                        # Requires the full live stack. See ../EVAL.md for
                        # the two-part story (designed accuracy +
                        # boundary fail-safe rate) this suite exists to
                        # measure.
```

### Coverage

```sh
make coverage           # unit-only (same scope as `make test`, so it
                         # never needs a live cluster to report the
                         # headline safety_core/ number)
```

**Coverage philosophy**: `safety_core/` — the deterministic safety
spine — is 99% covered by the unit suite *alone*; every module but
`gate.py` (98%, one line) is 100%. It doesn't need a live cluster to
prove itself, by design: everything safety-critical is pure and
injectable, so it's unit-tested directly. `k8s_agent/` and `compliance/`
are lower by design, not by neglect — they're I/O boundaries (real
Kubernetes API calls, real subprocess invocations of Kubescape) and
interactive entry points (the REPL loops in `k8s_agent/cli.py` and
`compliance/cli.py`), verified against a live cluster rather than
mocked. Concretely: `k8s_agent/cluster.py` and `compliance/scan.py` sit
at 22%/27% from `make coverage` alone, and rise to 80%/82% once `make
test-integration` also runs — project-wide, 70% unit-only versus 86%
combined. This project doesn't chase 100% outside `safety_core/`: a
mocked unit test asserting `kubectl apply` was "called with the right
args" is weaker evidence than a live integration test that actually
calls it.

## Troubleshooting

Real issues hit while building this project, not hypothetical ones:

- **`pytest` runs but behaves strangely, or can't import the project's
  own packages.** Use `python -m pytest`, not a bare `pytest` — on
  machines with Homebrew's own `pytest` on `PATH` ahead of the venv's,
  the bare command silently runs the *wrong* interpreter's pytest,
  outside the venv entirely. The Makefile's `test`/`test-integration`/
  `coverage` targets already use `python -m pytest` for exactly this
  reason; if you're ever running pytest directly, do the same.
- **The model always returns a generic placeholder string** (something
  like `[ministack mock generic ...]`) instead of a real completion.
  MiniStack needs `MINISTACK_BEDROCK_PROXY_URL` set (see the MiniStack
  step above) to actually forward requests to Ollama — without it, it
  still responds in the right shape, just without a real model behind
  it. `ModelClient` degrades gracefully either way (never crashes on a
  malformed or mock response), so this failure mode is easy to miss
  unless you're specifically looking at what the model proposed.
- **The wrong-interpreter trap, generally.** If a dependency seems
  "not installed" despite `pip install -r requirements-dev.txt`
  succeeding, or a script behaves like it's reading a different
  `.env`/config than the one you edited, check `which python3` and
  `which pip` resolve inside `.venv/bin/` before assuming it's a code
  problem — a surprising number of "it's broken" issues during this
  project's own development turned out to be a second Python
  installation shadowing the venv.

### Getting back to a known-good state

Whatever's wrong, try the cheapest fix first — restarting minikube
unnecessarily costs real minutes you don't get back. An escalation
ladder, not a single flat sequence:

**Level 1 — usually enough (~30s):**
```sh
make reset && make reset-insecure
make demo-check
```
Covers the overwhelming majority of "something looks wrong" cases: a
scaled/deleted/mutated deployment, a stale rollout, leftover state from
a previous run. Both scripts are idempotent — safe even if the
namespaces are already gone or already fine.

**Level 2 — if the model seems to be returning generic placeholder text**
(see the MiniStack entry above): restart MiniStack.
```sh
docker restart ministack
```
If the container was removed entirely rather than just stopped, re-run
the full `docker run` command from the setup steps above — the one flag
that's easy to forget when recreating it from scratch is
`MINISTACK_BEDROCK_PROXY_URL`; without it, MiniStack comes back up but
silently stops proxying to Ollama.

**Level 3 — last resort, the cluster itself seems broken** (not just its
contents — `make demo-check`'s environment-layer section is failing on
minikube/kubectl specifically, not just missing deployments):
```sh
minikube stop && minikube start
```
Then go back to Level 1 to reseed.

Always finish with `make demo-check` before trusting the result —
that's exactly what it's for.
