#!/usr/bin/env bash
# One-command pre-demo readiness check: everything scripts/verify.sh
# checks (environment layers), PLUS demo-specific application state --
# that both seed namespaces are actually applied right now, not just
# that the cluster is reachable. Never fakes green: every check below is
# a real, live query at the moment this runs, not a cached assumption.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILED=0
PASS="✓"; FAIL="✗"

echo "############################################"
echo "# Environment layers (scripts/verify.sh)"
echo "############################################"
bash "$SCRIPT_DIR/verify.sh" || FAILED=1

check_deployment() {
    if kubectl get deployment "$2" -n "$1" >/dev/null 2>&1; then
        echo "  $PASS $1/$2"
    else
        echo "  $FAIL $1/$2 — missing; run 'make seed' or 'make seed-insecure'"
        FAILED=1
    fi
}

echo ""
echo "############################################"
echo "# Demo state: bounded-agent-demo"
echo "############################################"
for d in healthy-web degraded-checkout rollback-target-web no-rollback-web solo-replica-web capacity-limited-web; do
    check_deployment bounded-agent-demo "$d"
done

echo ""
echo "############################################"
echo "# Demo state: bounded-agent-demo-protected"
echo "############################################"
check_deployment bounded-agent-demo-protected payments-core

echo ""
echo "############################################"
echo "# Demo state: bounded-agent-demo-insecure"
echo "############################################"
for d in insecure-root-container insecure-no-resource-limits insecure-privileged insecure-privilege-escalation; do
    check_deployment bounded-agent-demo-insecure "$d"
done

echo ""
if [ "$FAILED" -ne 0 ]; then
    echo "NOT demo-ready — see the ✗ lines above."
    exit 1
fi
echo "Demo-ready: all layers up, both namespaces seeded."
echo "(capacity-limited-web's CPU sizing is time-sensitive -- still run 'make demo' fresh right before presenting; this check only confirms it exists, not that it's freshly sized.)"
exit 0
