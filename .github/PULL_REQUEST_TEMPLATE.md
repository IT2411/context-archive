## Summary

Describe the changes introduced in this pull request.

## Phase Verification Checklist

- [ ] `poetry check --lock` passes
- [ ] `poetry run ruff check .` passes with 0 errors
- [ ] `poetry run ruff format --check .` passes with 0 diffs
- [ ] `poetry run mypy src tests --strict` passes with 0 errors
- [ ] `poetry run pytest --cov=context_archive --cov-fail-under=90` passes
