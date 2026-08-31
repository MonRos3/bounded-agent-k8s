# Running a demo

A generic walkthrough for showing this system's capabilities to someone
else — any reader of this repo, any occasion. (If you're looking for a
specific, pre-scripted walkthrough for a particular audience, that lives
in `DEMO.md`, which is private and not part of this doc set.)

Prerequisites: the full stack up and seeded — see
[SETUP.md](./SETUP.md). Each walkthrough below is independent; run
whichever demonstrates what you want to show.

## 1. The tier system

The core safety mechanic: the same agent loop, three different outcomes,
decided by the deterministic gate — never by the model. Run `make cli`,
then try each of these as separate requests.

**AUTO** — reversible, narrow-scope, within PDB headroom:

```
scale healthy-web to 4 replicas in the bounded-agent-demo namespace
```

Watch for: `classified` renders green, `AUTO`; `action` shows it executed
immediately, no prompt.

**APPROVE** — reversible but consequential:

```
bump the memory limit for the web container on the healthy-web deployment in bounded-agent-demo to 256Mi
```

Watch for: `classified` renders yellow, `APPROVE`; a full approval panel
appears (the request, proposed action, tier/reason, a real server-side
dry-run diff showing the actual predicted change, the rollback plan) and
waits for approve/reject before anything executes.

**BLOCK** — protected zone, no override:

```
scale payments-core to 3 replicas in the bounded-agent-demo-protected namespace
```

Watch for: `classified` renders red, `BLOCK`, with the reason ("target is
in a protected zone"); `action` shows it was blocked and escalated —
there's nothing left to approve or reject, and no path in the code that
could execute it anyway.

## 2. Automatic regression recovery

The full observe → regress → recover cycle, with a *genuine* regression
(not a test-injected one): a scale-up that can't actually schedule, so it
never becomes ready, so it gets rolled back — automatically,
deterministically, with no human approval and no model involvement in
the recovery itself.

```sh
make seed     # if not already seeded
make demo     # sizes capacity-limited-web's CPU request to exactly
              # half the live node's allocatable CPU — replica 1 always
              # fits, replica 2 never can, on any single-node cluster
make cli
```

Then, in the operator terminal:

```
scale capacity-limited-web to 2 replicas in the bounded-agent-demo namespace
```

Watch for: the action executing (green, `AUTO`-tier — `scale_deployment`
is reversible and auto-approved), then a `── recovery ──` block appears
once the observe cycle finishes (~45s, since the new pod can never
become Ready): `observed` (the real ready-replica count, stuck at 1),
`regression` (REGRESSED — target not met), `recovery` (rolling back
automatically), and `recovered` (restored to prior state). Nothing here
is a prompt — the rollback already happened by the time it's shown.

The same cycle threads through the audit stream under one trace id:
`grep <trace-id> audit_logs/<file>.jsonl` shows `classified` →
`observed` → `regression_checked` → `rollback_invoked` in order — the
full detail behind the curated terminal view.

Run `make reset` afterward to restore clean seeded state (it deletes and
re-applies the whole namespace, so `capacity-limited-web`'s CPU request
goes back to its small seeded placeholder, not the demo-sized value).

## 3. Compliance posture scan

The operator plane, entirely separate from the agent — no LLM, no gate,
no agent involvement.

```sh
make seed-insecure
make compliance NAMESPACE=bounded-agent-demo-insecure
```

Watch for: the framing panel at the top (explicitly "evidence toward
SOC 2 compliance... not a SOC 2 certification" — printed in the report
itself, not just in docs), the posture summary (controls passed/failed),
and the failing findings with real affected resource names. At the end,
two evidence file paths print — open the `.json` or `.md` in
`compliance_reports/` to see the same report as a durable artifact you
could hand to someone, not just terminal output.

For a closer look at what's actually different about scanning under SOC
2 versus NSA, see [USAGE.md](./USAGE.md)'s compliance section.

Run `make reset-insecure` afterward to restore clean seeded state.
