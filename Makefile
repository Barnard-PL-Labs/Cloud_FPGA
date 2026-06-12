.PHONY: test test-unit test-integration test-e2e

# Run everything except hardware tests (requires Docker for Redis)
test:
	python -m pytest -v -m "not hardware"

# Fast unit tests only — no Docker needed
test-unit:
	python -m pytest orchestrator/tests/unit/ -v

# Integration tests — requires Docker
test-integration:
	python -m pytest orchestrator/tests/integration/ -v -m "not hardware"

# End-to-end tests — requires Docker
test-e2e:
	python -m pytest orchestrator/tests/e2e/ -v -m "not hardware"
