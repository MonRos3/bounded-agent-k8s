#!/usr/bin/env bash
# Architectural-integrity proofs: this project's structural claims
# (domain-independent safety core, one-way k8s_agent -> safety_core
# dependency, compliance/ as a separate sibling importing neither) are
# facts provable by grep, not just asserted in docs/docstrings. This
# script runs those proofs and reports a clear pass/fail for each — a
# reader doesn't have to take the README's word for it.
#
# Known, deliberate gaps this project chose NOT to fix are documented
# honestly in docs/FOLLOWUPS.md, not hidden here.
set -uo pipefail
PASS="✓"; FAIL="✗"; issues=0

echo "== Proof 1: safety_core/ is domain-independent =="
hits=$(grep -rni -E 'kubernetes|kubectl|\bpod\b|replica|namespace|terraform|bedrock|ollama|\baws\b' --include='*.py' safety_core/ 2>/dev/null || true)

# Known, accepted hits: three are comments/docstrings using domain terms
# in plain-English explanation (never code). One is real code but a
# deliberate, documented exception: safety_core/types.py's own docstring
# says State.facts is opaque from safety_core's perspective — Gate reads
# a caller-supplied string key, "healthy_replicas", without assigning it
# domain meaning. The string reads like a Kubernetes term; it's a dict
# key, not an import or domain logic. Matched by file + a distinctive
# substring (not line number) so incidental future edits elsewhere in
# these files don't spuriously break this allowlist.
ALLOWED_PATTERNS=(
    'safety_core/__init__\.py:.*Contains zero domain-specific'
    'safety_core/success\.py:.*ready_replica_count'
    'safety_core/gate\.py:.*Replicas that could still be lost'
    'safety_core/gate\.py:.*facts\.get\("healthy_replicas"\)'
)

unexpected="$hits"
for pattern in "${ALLOWED_PATTERNS[@]}"; do
    unexpected=$(echo "$unexpected" | grep -vE "$pattern" || true)
done

if [ -z "$unexpected" ]; then
    echo "  $PASS no unexpected domain terms in safety_core/ (1 documented code exception + 3 comment/docstring mentions)"
else
    echo "  $FAIL NEW domain terms found in safety_core/ — review, then fix or allowlist:"
    echo "$unexpected" | sed 's/^/      /'
    issues=$((issues+1))
fi

echo ""
echo "== Proof 2: dependency is one-way (k8s_agent -> safety_core, never reverse) =="
reverse=$(grep -rn -E '^\s*(import|from)\s+k8s_agent' --include='*.py' safety_core/ 2>/dev/null || true)
if [ -z "$reverse" ]; then
    echo "  $PASS safety_core/ never imports k8s_agent"
else
    echo "  $FAIL safety_core/ imports k8s_agent — the one-way dependency is broken:"
    echo "$reverse" | sed 's/^/      /'
    issues=$((issues+1))
fi

forward_count=$(grep -rl -E '^\s*(import|from)\s+safety_core' --include='*.py' k8s_agent/ 2>/dev/null | wc -l | tr -d ' ')
if [ "$forward_count" -gt 0 ]; then
    echo "  $PASS k8s_agent/ does import safety_core ($forward_count file(s)) — the dependency genuinely exists, this isn't passing by vacuous absence"
else
    echo "  $FAIL k8s_agent/ never imports safety_core — suspicious; the dependency should exist"
    issues=$((issues+1))
fi

echo ""
echo "== Proof 3: compliance/ is a separate sibling (imports neither safety_core nor k8s_agent) =="
compliance_imports=$(grep -rn -E '^\s*(import|from)\s+(safety_core|k8s_agent)' --include='*.py' compliance/ 2>/dev/null || true)
if [ -z "$compliance_imports" ]; then
    echo "  $PASS compliance/ imports neither safety_core nor k8s_agent"
else
    echo "  $FAIL compliance/ imports the agent or safety core — the operator/agent separation is broken:"
    echo "$compliance_imports" | sed 's/^/      /'
    issues=$((issues+1))
fi

echo ""
if [ "$issues" -eq 0 ]; then
    echo "All architecture proofs passed."
    exit 0
else
    echo "$issues proof(s) failed. Review above."
    exit 1
fi
