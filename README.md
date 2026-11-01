# context-archive (`ctxa`)

**Portable AI Project Context Compiler with incremental change journaling.**

`context-archive` (`ctxa`) statically analyzes a software repository and compiles a compact, versioned, model-agnostic handoff artifact (`PROJECT_CONTEXT.md`) alongside a machine-readable canonical project graph (`.context/graph.json`) and append-only change journal (`.context/journal/YYYY-MM.jsonl`).

## Quickstart Workflow

```bash
# 1. Initialize .context/, snapshot-0001.json, and PROJECT_CONTEXT.md
ctxa init

# 2. Record durable architectural decisions or constraints
ctxa note "All monetary calculations must use Decimal" --type constraint --scope src/pricing.py

# 3. Record incremental code changes into the append-only JSONL journal
ctxa update -m "Add discount rounding to calculate_total"

# 4. Inspect semantic diff and downstream caller/test impact
ctxa diff --format text

# 5. Refresh portable PROJECT_CONTEXT.md and verify cryptographic freshness
ctxa handoff
ctxa verify

# 6. Compile a token-budgeted context packet for a specific task
ctxa context "Add rate limiting to POST /orders" --max-tokens 6000

# 7. Fold unincorporated journal records into a new snapshot checkpoint
ctxa compact
```

## Development & Verification Gates

```bash
poetry check --lock
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests --strict
poetry run pytest --cov=context_archive --cov-fail-under=90
```

## License

MIT
