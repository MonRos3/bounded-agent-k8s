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
# for every deployment whose demo scenario depends on having a rollback
# target (Gate.classify checks irreversibility before the PDB-headroom
# rule, so healthy-web/degraded-checkout/solo-replica-web all need a 2nd
# revision too, or their scenarios would BLOCK for the wrong reason).
# no-rollback-web deliberately stays at 1 revision — that's its whole
# point — and payments-core doesn't need it either way, since the
# protected-zone check fires before reversibility is ever considered.
for deployment in healthy-web degraded-checkout solo-replica-web rollback-target-web capacity-limited-web; do
    echo "seed.sh: generating rollout history for $deployment"
    kubectl rollout restart "deployment/$deployment" -n bounded-agent-demo
    kubectl rollout status "deployment/$deployment" -n bounded-agent-demo --timeout=120s
done
