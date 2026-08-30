#!/usr/bin/env bash
# Applies the deliberately-insecure demo manifests (manifests/vulnerable/)
# for the M6.1 Kubescape compliance demo. Entirely separate from
# scripts/seed.sh: the insecure namespace never interacts with the
# agent's own demo deployments, and this script is never called by the
# agent's own seed/reset lifecycle.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VULNERABLE_DIR="$SCRIPT_DIR/../manifests/vulnerable"

if ! command -v kubectl >/dev/null 2>&1; then
    echo "seed_insecure.sh: kubectl not found on PATH" >&2
    exit 1
fi

echo "seed_insecure.sh: applying manifests from $VULNERABLE_DIR"
kubectl apply -f "$VULNERABLE_DIR"
