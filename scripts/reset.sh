#!/usr/bin/env bash
# Restores a clean, known cluster state: deletes the demo namespaces and
# re-applies manifests/seed/. Idempotent — safe to run repeatedly, even if
# the namespaces don't exist yet. Touches ONLY cluster state: never Ollama
# models, MiniStack, or the venv.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-bounded-agent-demo}"
DEMO_PROTECTED_NAMESPACE="${DEMO_PROTECTED_NAMESPACE:-bounded-agent-demo-protected}"

if ! command -v kubectl >/dev/null 2>&1; then
    echo "reset.sh: kubectl not found on PATH" >&2
    exit 1
fi

for ns in "$DEMO_NAMESPACE" "$DEMO_PROTECTED_NAMESPACE"; do
    echo "reset.sh: deleting namespace '$ns' (if present)"
    kubectl delete namespace "$ns" --ignore-not-found --wait=true
done

echo "reset.sh: re-seeding cluster"
"$SCRIPT_DIR/seed.sh"

echo "reset.sh: done"
