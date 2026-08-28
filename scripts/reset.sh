#!/usr/bin/env bash
# Restores a clean, known cluster state: deletes the demo namespace and
# re-applies manifests/seed/. Idempotent — safe to run repeatedly, even if
# the namespace doesn't exist yet. Touches ONLY cluster state: never Ollama
# models, MiniStack, or the venv.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_NAMESPACE="${DEMO_NAMESPACE:-bounded-agent-demo}"

if ! command -v kubectl >/dev/null 2>&1; then
    echo "reset.sh: kubectl not found on PATH" >&2
    exit 1
fi

echo "reset.sh: deleting namespace '$DEMO_NAMESPACE' (if present)"
kubectl delete namespace "$DEMO_NAMESPACE" --ignore-not-found --wait=true

echo "reset.sh: re-seeding cluster"
"$SCRIPT_DIR/seed.sh"

echo "reset.sh: done"
