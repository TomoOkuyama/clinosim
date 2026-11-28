.PHONY: install test-unit test-integration test-e2e test-all lint typecheck format

# Package lives at repo-root `clinosim/` (flat layout, not `src/clinosim/`).
# Fixed in P0-2 (session 46) — earlier Makefile pointed at a nonexistent
# `src/` prefix so `make lint`/`make typecheck`/`make format` all failed
# immediately. CI depends on these targets now.

# The test targets select by directory, never by marker (not every test file carries
# its marker, so `-m unit` silently skips tests). `test-unit` runs the
# directories the CI unit job runs (.github/workflows/ci.yml).

install:
	pip install -e ".[all]"

test-unit:
	pytest tests/unit tests/modules tests/simulator -v --tb=short

test-integration:
	pytest tests/integration -v --tb=short

test-e2e:
	pytest tests/e2e -v --tb=long

test-all:
	pytest tests/ -v

lint:
	ruff check clinosim/ tests/
	ruff format --check clinosim/ tests/

typecheck:
	mypy clinosim/

format:
	ruff format clinosim/ tests/
	ruff check --fix clinosim/ tests/
