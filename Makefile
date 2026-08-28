.PHONY: verify reset seed test demo

verify:
	bash scripts/verify.sh

reset:
	bash scripts/reset.sh

seed:
	bash scripts/seed.sh

test:
	pytest

demo:
	@echo "demo: not yet implemented"
