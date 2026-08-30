#!/usr/bin/env bash
# Sizes capacity-limited-web's per-pod CPU request to exactly half the
# live node's allocatable CPU (+ a margin), so replica 1 always fits and
# replica 2 never can — portable across any single-node cluster size, not
# a guessed constant. Run this after `make seed`, before `make cli`.
set -euo pipefail

NAMESPACE="bounded-agent-demo"
DEPLOYMENT="capacity-limited-web"

if ! command -v kubectl >/dev/null 2>&1; then
    echo "demo_regression.sh: kubectl not found on PATH" >&2
    exit 1
fi

if ! kubectl get "deployment/${DEPLOYMENT}" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "demo_regression.sh: ${DEPLOYMENT} not found in ${NAMESPACE} — run 'make seed' first" >&2
    exit 1
fi

ALLOCATABLE_CPU="$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.cpu}')"
REQUEST_MILLI="$(python3 -c "
raw = '${ALLOCATABLE_CPU}'
milli = int(raw[:-1]) if raw.endswith('m') else int(float(raw) * 1000)
print(milli // 2 + 500)
")"

echo "demo_regression.sh: node allocatable cpu=${ALLOCATABLE_CPU}; sizing ${DEPLOYMENT}'s request to ${REQUEST_MILLI}m"
kubectl set resources "deployment/${DEPLOYMENT}" -n "$NAMESPACE" --containers=web --requests=cpu="${REQUEST_MILLI}m"
kubectl rollout status "deployment/${DEPLOYMENT}" -n "$NAMESPACE" --timeout=60s

echo
echo "Ready. Run 'make cli', then try:"
echo "  scale capacity-limited-web to 2 replicas in the bounded-agent-demo namespace"
