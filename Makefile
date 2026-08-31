.PHONY: verify verify-foundation verify-architecture demo-check reset seed seed-insecure reset-insecure test test-integration coverage eval demo cli compliance

RUNS ?= 4

verify:
	bash scripts/verify.sh

verify-foundation:
	bash scripts/verify_foundation.sh

verify-architecture:
	bash scripts/verify_architecture.sh

demo-check:
	bash scripts/demo_check.sh

reset:
	bash scripts/reset.sh

seed:
	bash scripts/seed.sh

seed-insecure:
	bash scripts/seed_insecure.sh

reset-insecure:
	bash scripts/reset_insecure.sh

test:
	python -m pytest

test-integration:
	python -m pytest -m integration

coverage:
	python -m pytest -q --cov=safety_core --cov=k8s_agent --cov=compliance --cov-report=term-missing -m "not integration"

eval:
	python3 tests/eval_llm.py --runs $(RUNS)

demo:
	bash scripts/demo_regression.sh

cli:
	python3 -m k8s_agent.cli

compliance:
	python3 -m compliance.cli $(if $(NAMESPACE),--namespace $(NAMESPACE),) $(if $(FRAMEWORK),--framework $(FRAMEWORK),)
