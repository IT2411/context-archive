.PHONY: install check lint format typecheck test gates

install:
	poetry install

check:
	poetry check --lock

lint:
	poetry run ruff check .

format:
	poetry run ruff format --check .

typecheck:
	poetry run mypy src tests --strict

test:
	poetry run pytest --cov=context_archive --cov-fail-under=90

gates: check lint format typecheck test
