#!/usr/bin/env bash
# Architecture & repo-hygiene invariants — distinct from scripts/verify.sh,
# which checks whether the runtime environment (venv/Docker/system CLIs) is
# reachable right now. This script checks whether the repo itself is still
# structurally sound: safety_core/ stays domain-independent, expected
# scaffolding exists, .env hygiene holds. Safe to re-run any time; intended
# to catch regressions as the project grows, not just at initial setup.
#
# The domain-independence grep will also match commented "Kubernetes" or
# "kubectl" — false positives there are fine, but any actual code using
# these terms in safety_core/ is a real problem.

set -uo pipefail
PASS="✓"; FAIL="✗"; issues=0
check() { if eval "$2"; then echo "  $PASS $1"; else echo "  $FAIL $1"; issues=$((issues+1)); fi; }

echo "== safety_core/ architecture invariants =="
echo "  -- domain-independence grep (should be empty or comments-only) --"
hits=$(grep -rin "kubernetes\|kubectl\|\bpod\b\|replica\|namespace\|terraform\|bedrock\|ollama\|\baws\b" safety_core/ 2>/dev/null || true)
if [ -z "$hits" ]; then echo "  $PASS no domain terms in safety_core/"; else
  echo "  $FAIL domain terms found — review (comments OK, code not):"; echo "$hits" | sed 's/^/      /'; issues=$((issues+1)); fi
check "safety_core imports cleanly" "python -c 'import safety_core' 2>/dev/null"
check "types.py uses frozen dataclasses" "grep -q 'frozen=True' safety_core/types.py"
check "abstract interfaces use ABC/abstractmethod" "grep -rq 'abstractmethod' safety_core/"

echo ""
echo "== repo scaffolding & hygiene =="
for d in safety_core k8s_agent manifests/seed manifests/vulnerable scripts fixtures tests; do
  check "dir exists: $d" "[ -d '$d' ]"
done
for f in README.md DEMO.md Makefile requirements.txt requirements-dev.txt .env.example scripts/verify.sh scripts/reset.sh; do
  check "file exists: $f" "[ -f '$f' ]"
done
check ".env is gitignored" "git check-ignore -q .env"
check ".env.example is NOT ignored" "! git check-ignore -q .env.example"

echo "  -- .env.example secret scan (eyeball any hits) --"
secrets=$(grep -Ei 'secret|password|token|key' .env.example 2>/dev/null | grep -Ev '=$|=(your|placeholder|example|test|changeme|http|0|1|localhost)' || true)
if [ -z "$secrets" ]; then echo "  $PASS no obvious real secrets in .env.example"; else
  echo "  $FAIL possible secrets — review:"; echo "$secrets" | sed 's/^/      /'; issues=$((issues+1)); fi

check "verify.sh references all four layers" \
  "grep -qi 'ollama' scripts/verify.sh && grep -qi 'minikube\|kubectl' scripts/verify.sh && grep -qi '4566\|ministack' scripts/verify.sh && grep -qi 'boto3\|venv' scripts/verify.sh"

echo ""
if [ "$issues" -eq 0 ]; then echo "All foundation checks passed.";
else echo "$issues issue(s) flagged. Review above."; fi
