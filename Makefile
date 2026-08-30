.PHONY: verify verify-foundation reset seed test test-integration demo

verify:
	bash scripts/verify.sh

verify-foundation:
	bash scripts/verify_foundation.sh

reset:
	bash scripts/reset.sh

seed:
	bash scripts/seed.sh

test:
	python -m pytest

test-integration:
	python -m pytest -m integration

demo:
	@echo "demo: not yet implemented"
