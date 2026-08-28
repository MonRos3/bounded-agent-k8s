#!/usr/bin/env bash
# Applies the seed manifests to the currently-configured cluster.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_DIR="$SCRIPT_DIR/../manifests/seed"

if ! command -v kubectl >/dev/null 2>&1; then
    echo "seed.sh: kubectl not found on PATH" >&2
    exit 1
fi

# Only .gitkeep present (no real manifests yet) — nothing to apply.
if ! find "$SEED_DIR" -maxdepth 1 -type f ! -name ".gitkeep" | grep -q .; then
    echo "seed.sh: no manifests in $SEED_DIR yet — nothing to apply"
    exit 0
fi

echo "seed.sh: applying manifests from $SEED_DIR"
kubectl apply -f "$SEED_DIR"
