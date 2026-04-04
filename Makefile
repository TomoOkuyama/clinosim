.PHONY: install test-unit test-integration test-e2e test-all lint typecheck

install:
	pip install -e ".[all]"

test-unit:
	pytest tests/unit/ -m unit -v --tb=short

test-integration:
	pytest tests/integration/ -m integration -v --tb=short

test-e2e:
	pytest tests/e2e/ -m e2e -v --tb=long

test-all:
	pytest tests/ -v

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

typecheck:
	mypy src/clinosim/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/
