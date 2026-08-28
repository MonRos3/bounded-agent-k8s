#!/usr/bin/env bash
# Checks each of the four environment layers independently and reports a
# per-layer pass/fail table, so a failure says exactly which layer is down.
# Deliberately does not use `set -e`: every layer must be checked even if an
# earlier one fails.
set -uo pipefail

MINISTACK_ENDPOINT="${MINISTACK_ENDPOINT:-http://localhost:4566}"
OLLAMA_ENDPOINT="${OLLAMA_ENDPOINT:-http://localhost:11434}"

RESULTS=()
FAILED=0

pass() {
    RESULTS+=("  ✓ $1")
}

fail() {
    RESULTS+=("  ✗ $1")
    FAILED=1
}

echo "== Layer 1: Python venv =="
if [ -z "${VIRTUAL_ENV:-}" ]; then
    fail "venv: no virtualenv is activated (VIRTUAL_ENV is unset) — run 'source .venv/bin/activate'"
else
    pass "venv: active ($VIRTUAL_ENV)"
fi

if python3 -c "import boto3" >/dev/null 2>&1; then
    pass "boto3 importable"
else
    fail "boto3: not importable — run 'pip install -r requirements.txt' inside the venv"
fi

echo "== Layer 2: Docker / MiniStack (localhost:4566) =="
if docker info >/dev/null 2>&1; then
    pass "Docker daemon is running"
    if curl -sf -o /dev/null --max-time 3 "$MINISTACK_ENDPOINT/_localstack/health" \
        || curl -sf -o /dev/null --max-time 3 "$MINISTACK_ENDPOINT"; then
        pass "MiniStack responding on $MINISTACK_ENDPOINT"
    else
        fail "MiniStack: Docker is up but nothing is responding on $MINISTACK_ENDPOINT — is the container running?"
    fi
else
    fail "Docker: daemon not reachable — is Docker running?"
    fail "MiniStack: skipped (Docker is down)"
fi

echo "== Layer 3: Ollama (localhost:11434) =="
if curl -sf --max-time 3 "$OLLAMA_ENDPOINT/api/tags" >/dev/null 2>&1; then
    pass "Ollama responding on $OLLAMA_ENDPOINT"
else
    fail "Ollama: not responding on $OLLAMA_ENDPOINT — is 'ollama serve' running?"
fi

echo "== Layer 4: minikube / kubectl =="
if minikube status 2>/dev/null | grep -q "Running"; then
    pass "minikube status: Running"
    if kubectl cluster-info >/dev/null 2>&1; then
        pass "kubectl can reach the cluster"
    else
        fail "kubectl: minikube is Running but the cluster is unreachable — check kubeconfig/context"
    fi
else
    fail "minikube: not Running — run 'minikube start'"
    fail "kubectl: skipped (minikube is not Running)"
fi

echo "== Layer 5: system CLIs on PATH =="
if command -v kubectl >/dev/null 2>&1; then
    pass "kubectl found on PATH"
else
    fail "kubectl: not found on PATH"
fi

if command -v kubescape >/dev/null 2>&1; then
    pass "kubescape found on PATH"
else
    fail "kubescape: not found on PATH — see README prerequisites"
fi

echo ""
echo "===== Verification summary ====="
for line in "${RESULTS[@]}"; do
    printf "%s\n" "$line"
done
echo "================================"

if [ "$FAILED" -ne 0 ]; then
    echo "One or more layers failed. See ✗ lines above for which layer and why."
    exit 1
fi

echo "All layers healthy."
exit 0
