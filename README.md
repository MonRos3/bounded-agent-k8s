# Bounded Kubernetes AI Agent Proof-of-Concept

A demonstration of a secure, bounded AI agent for Kubernetes operations. An operator describes a problem in natural language; an LLM proposes a structured kubectl-style action with an advisory risk note; a deterministic gate, not the model, classifies the action's blast radius from live cluster state and assigns a tier: auto-execute, require human approval, or block and escalate.

Approved actions execute against a real cluster, everything is audited, and if an action regresses, a predetermined deterministic rollback fires automatically.

The core design principle: the model proposes, deterministic code disposes. The LLM's judgment is advisory; all safety-critical decisions live in testable, deterministic logic outside the model's reasoning loop.

## How to Use

### Environment model

The project runs across four independently-checkable layers:

1. **Python venv** — this repo's libraries (`boto3`, `kubernetes`, `requests`, ...).
2. **Docker containers** — MiniStack, serving local Bedrock/IAM/CloudWatch
   API surfaces on `localhost:4566`.
3. **System CLIs** — Ollama (`localhost:11434`), minikube, kubectl, kubescape.
4. **Code** — `safety_core/` (domain-independent safety spine) and
   `k8s_agent/` (Kubernetes-specific domain layer).

`make verify` checks each layer on its own and reports a ✓/✗ per layer, so a
failure tells you exactly which one is down rather than a generic
"environment not ready."

### Prerequisites

Install these yourself — they are system tools, not Python packages, and are
never installed via `requirements.txt`:

- [Docker](https://www.docker.com/) (running MiniStack)
- [minikube](https://minikube.sigs.k8s.io/) + `kubectl`
- [kubescape](https://kubescape.io/)
- [Ollama](https://ollama.com/)

### Quickstart

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
make verify
```

## Bounded AI Agent Design Overview

![Design overview for the bounded kubernetes AI agent](./bounded_agent_k8s.png)

## Four Controls

This design uses four controls to constrain an agent's influence, listed in order of a request flow:

(1) Guardrails; model boundary

- filters input and output
- the authority/final check (unless escalated to HITL)

(2) Policy Decision Point (PDP); action boundary

- deterministic allow/deny
- the authority/final check

(3) Scoped IAM; pivilege floor

- least-privilege credentials
- even a gate can't exceed this

(4) Observability; across layers

- guardrails and refusal rates as signals
