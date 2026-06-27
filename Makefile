.PHONY: help install-dev format lint typecheck test check clean

help:
	@echo "install-dev - install package and dev/test dependencies"
	@echo "format      - run code formatting"
	@echo "lint        - run lint checks"
	@echo "typecheck   - run static type checks"
	@echo "test        - run unit tests"
	@echo "check       - run lint + typecheck + tests"
	@echo "clean       - remove generated/cache artifacts"

install-dev:
	python3 -m pip install --upgrade pip
	python3 -m pip install -e ".[dev,test]"

format:
	python3 -m ruff format .

fix:
	python3 -m ruff check --fix .

lint:
	pre-commit run --all-files --show-diff-on-failure

typecheck:
	pre-commit run mypy-local --all-files

test:
	python3 -m pytest -v tests

pr: clean fix lint typecheck test

check: lint typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .tox build dist *.egg-info
