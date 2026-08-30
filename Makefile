.PHONY: verify verify-foundation reset seed seed-insecure reset-insecure test test-integration eval demo cli

RUNS ?= 4

verify:
	bash scripts/verify.sh

verify-foundation:
	bash scripts/verify_foundation.sh

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

eval:
	python3 tests/eval_llm.py --runs $(RUNS)

demo:
	bash scripts/demo_regression.sh

cli:
	python3 -m k8s_agent.cli
