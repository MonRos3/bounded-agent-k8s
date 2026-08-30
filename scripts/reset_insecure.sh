#!/usr/bin/env bash
# Restores a clean, known state for the M6.1 compliance demo: deletes
# bounded-agent-demo-insecure and re-applies manifests/vulnerable/.
# Idempotent — safe to run repeatedly. Touches only that one namespace;
# never the agent's own bounded-agent-demo/bounded-agent-demo-protected.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSECURE_NAMESPACE="${INSECURE_NAMESPACE:-bounded-agent-demo-insecure}"

if ! command -v kubectl >/dev/null 2>&1; then
    echo "reset_insecure.sh: kubectl not found on PATH" >&2
    exit 1
fi

echo "reset_insecure.sh: deleting namespace '$INSECURE_NAMESPACE' (if present)"
kubectl delete namespace "$INSECURE_NAMESPACE" --ignore-not-found --wait=true

echo "reset_insecure.sh: re-seeding"
"$SCRIPT_DIR/seed_insecure.sh"

echo "reset_insecure.sh: done"
