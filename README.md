# context-archive (`ctxa`)

**Portable AI Project Context Compiler with incremental change journaling.**

`context-archive` (`ctxa`) statically analyzes a software repository and compiles a compact, versioned, model-agnostic handoff artifact (`PROJECT_CONTEXT.md`) alongside a machine-readable canonical project graph (`.context/graph.json`) and append-only change journal (`.context/journal/YYYY-MM.jsonl`).

## Key Features

- **Zero-Execution Static Analysis:** Deterministic AST extraction without importing or executing target repository code.
- **First-Class Incrementalism:** Append-only JSONL change journal and partial graph updates (`ctxa update`).
- **Protected Human Knowledge:** Preserves architectural notes and constraints across regenerations (`<!-- CTXA:MANUAL:START/END -->`).
- **Cryptographic Freshness Verification:** Detects stale context or dirty working trees via `ctxa verify`.
- **Task-Specific Context Compilation:** Ranks and budgets relevant symbols/contracts within strict token limits (`ctxa context`).

## Development Quickstart

```bash
poetry install
poetry check --lock
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests --strict
poetry run pytest --cov=context_archive --cov-fail-under=90
```

## License

MIT
