# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-10-30

### Added
- **Project Knowledge Engine:** Safe zero-execution repository scanner, secret/binary exclusion, Git state extractor, and deterministic canonical graph (`manifest.json`, `graph.json`).
- **Static Adapters:** Python AST analyzer (`python_ast:1.0`), FastAPI & Pydantic contract extractor (`fastapi_pydantic:1.0`), SQLAlchemy/SQLModel entity extractor (`sqlalchemy_entity:1.0`), and TypeScript/JavaScript cross-stack adapter (`typescript:1.0`).
- **Incremental Change Engine:** File/AST change detector (`L1`/`L2`/`L3`), append-only monthly JSONL journal (`.context/journal/YYYY-MM.jsonl`), partial graph invalidation, snapshot compaction (`ctxa compact`), and self-healing SQLite cache.
- **Context Delivery Engine:** Deterministic `PROJECT_CONTEXT.md` renderer, two-way synced human notes (`ctxa note` and `CTXA:MANUAL` sentinel boundaries), freshness verifier (`ctxa verify`), semantic impact differ (`ctxa diff`), token-budgeted task compiler (`ctxa context`), branch divergence reconciler (`ctxa rebuild`), Python SDK (`ContextArchiveEngine`), and read-only stdio MCP server (`ctxa mcp`).
