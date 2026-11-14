.PHONY: install test lint fmt

install:
	python -m pip install -r requirements-dev.txt

test:
	python -m pytest

lint:
	ruff check src tests

fmt:
	ruff check --fix src tests
