# Contributing to `context-archive`

Thank you for contributing to `context-archive` (`ctxa`)!

## Quality Gates

Every pull request and phase must pass all 5 verification gates with zero errors:

```bash
poetry check --lock
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests --strict
poetry run pytest --cov=context_archive --cov-fail-under=90
```
