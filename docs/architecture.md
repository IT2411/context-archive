# Architecture Overview (`context-archive` / `ctxa`)

`context-archive` is organized around three cooperating, local-first engines sharing a single schema-versioned canonical data model:

1. **Project Knowledge Engine (`scanner`, `git`, `model`, `adapters`):**
   - Traverses the repository without importing or executing target code.
   - Enforces `.gitignore`, `.ignore`, and secret exclusions (`.env*`, `*.pem`, `*.key`, credentials).
   - Extracts deterministic `Node`, `Edge`, `Provenance`, and `Diagnostic` records across Python, FastAPI, Pydantic, SQLAlchemy, and TypeScript/JavaScript.

2. **Incremental Change Engine (`state`):**
   - Compares working-tree SHA-256 file fingerprints and AST symbol signatures against the latest recorded state.
   - Classifies changes into **L1 (Journal-Only)**, **L2 (Partial Graph Refresh)**, or **L3 (Full Checkpoint)**.
   - Appends immutable JSONL records to `.context/journal/YYYY-MM.jsonl` and compacts checkpoints via `ctxa compact`.

3. **Context Delivery Engine (`notes`, `context`, `renderers`, `integrations`):**
   - Assembles `EffectiveContext` = `Latest Snapshot + Unincorporated Journal Records + Active Human Notes`.
   - Synchronizes and protects human-maintained sections (`<!-- CTXA:MANUAL:START/END -->`).
   - Renders `PROJECT_CONTEXT.md`, verifies freshness (`ctxa verify`), computes semantic impact diffs (`ctxa diff`), compiles token-bounded task packets (`ctxa context`), and serves read-only MCP queries (`ctxa mcp`).
