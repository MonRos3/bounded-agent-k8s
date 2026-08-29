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

# A Deployment always starts at revision 1 on first apply — static YAML
# alone can't seed "has rollback history". Trigger a real rollout restart
# for rollback-target-web so it deterministically has a second revision.
echo "seed.sh: generating rollout history for rollback-target-web"
kubectl rollout restart deployment/rollback-target-web -n bounded-agent-demo
kubectl rollout status deployment/rollback-target-web -n bounded-agent-demo --timeout=120s
