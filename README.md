# context-archive (`ctxa`)

[![PyPI version](https://img.shields.io/pypi/v/context-archive.svg)](https://pypi.org/project/context-archive/) [![Python Versions](https://img.shields.io/pypi/pyversions/context-archive.svg)](https://pypi.org/project/context-archive/) [![CI Quality Gates](https://github.com/IT2411/context-archive/actions/workflows/ci.yml/badge.svg)](https://github.com/IT2411/context-archive/actions/workflows/ci.yml) [![M8ven Score](https://m8ven.ai/badge/mcp/it2411/context-archive)](https://m8ven.ai/mcp/it2411/context-archive?s=readme) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

**Portable AI Project Context Compiler with incremental change journaling, deterministic dependency graphs, and token-budgeted task handoffs.**

`context-archive` (`ctxa`) statically analyzes a software repository without executing untrusted code and compiles a versioned, model-agnostic handoff artifact (`PROJECT_CONTEXT.md`) alongside a machine-readable canonical project graph (`.context/graph.json`) and append-only change journal (`.context/journal/YYYY-MM.jsonl`).

It enables developers and AI coding agents (Claude Code, Cursor, GitHub Copilot, Google AI Studio, Codex CLI, Windsurf, custom MCP agents) to immediately understand the architecture, contracts, call/dependency relationships, test coverage, architectural decisions, and recent changes of a codebase without relying on prior chat history or vendor-locked memory systems.

---

## Why `context-archive`?

- **Zero-Execution Static Analysis:** Extracts AST symbols, signatures, contracts, and dependency edges deterministically without importing or executing target repository code.
- **Polyglot Language & Framework Coverage:** Built-in analyzers for **Python** (including **FastAPI**, **Pydantic**, **SQLAlchemy/SQLModel**), **TypeScript / JavaScript** (`fetch` / `axios` cross-stack contract linking), **Kotlin**, **Java** (including **Spring Boot** & JUnit), **C / C++** (including GoogleTest), **Go**, **Rust**, **C#**, **Ruby**, **PHP**, and **Swift**.
- **5-Stage Graph-Aware Task Context Compiler (`ctxa context`):** Compiles token-budgeted, task-specific subgraph packets using IDF-weighted concept matching, mandatory test-to-implementation dependency closure, mode-aware ranking (`implementation` vs. `architecture`), and brace-matched code excerpts.
- **First-Class Incrementalism (`ctxa update`):** Records localized code edits in `< 350ms` via an append-only monthly JSONL change journal and partial graph invalidation (`L1` / `L2` / `L3`) without full rebuilds.
- **Protected Human Knowledge (`ctxa note`):** Two-way synchronizes human-authored architectural decisions, constraints, known issues, and next steps between `.context/notes.md` and `<!-- CTXA:MANUAL:START/END -->` sentinel blocks in `PROJECT_CONTEXT.md`.
- **Cryptographic Freshness Verification (`ctxa verify`):** Verifies whether `PROJECT_CONTEXT.md` and `.context/` match the live Git commit, branch, configuration fingerprint, and SHA-256 digests of all tracked files.
- **Built-in Read-Only MCP Server (`ctxa mcp`):** Exposes live project overview, symbol lookup, downstream impact analysis, journal queries, and task context compilation over stdio JSON-RPC 2.0.

---

## Installation

### Via `pipx` (Recommended for CLI usage)

```bash
pipx install context-archive
```

### Via `pip` / `poetry`

```bash
pip install context-archive

# Optional extras (for exact OpenAI tiktoken BPE counting or MCP SDK):
pip install "context-archive[all]"
```

Verify installation:

```bash
ctxa --version
ctxa --help
```

---

## Quickstart Workflow

```bash
# 1. Initialize .context/, base snapshot (snapshot-0001.json), and PROJECT_CONTEXT.md
ctxa init

# 2. Record durable architectural decisions, constraints, or known issues
ctxa note "All monetary calculations must use Decimal with half-up rounding" \
  --type constraint \
  --scope src/pricing.py

# 3. Make code edits and record an incremental journal entry (L1/L2/L3 auto-detected)
ctxa update -m "Fix odd-chip remainder distribution in split pots"

# 4. Inspect semantic diff and 2-hop downstream caller/test impact
ctxa diff --format text
ctxa diff --format mermaid

# 5. Refresh portable PROJECT_CONTEXT.md and verify cryptographic freshness
ctxa handoff
ctxa verify

# 6. Compile a token-budgeted context packet for a specific engineering task
ctxa context "Fix odd-chip rounding when splitting a pot between multiple winners" \
  --max-tokens 4000

# 7. Fold unincorporated journal records into a new immutable snapshot checkpoint
ctxa compact
```

---

## CLI Reference

| Command | Description | Key Flags |
| :--- | :--- | :--- |
| `ctxa init [PATH]` | Initialize `.context/`, `.ctxa.toml`, `snapshot-0001.json`, and `PROJECT_CONTEXT.md`. | `--force`, `--deterministic` |
| `ctxa update [PATH]` | Detect file/AST mutations, append a JSONL journal record, and refresh affected graph nodes. | `--level auto\|l1\|l2\|l3`, `-m "<intent>"`, `--json` |
| `ctxa note "<text>" [PATH]` | Record a durable human note synced between `.context/notes.md` and `PROJECT_CONTEXT.md`. | `--type decision\|constraint\|issue\|question\|next_step`, `--scope <target>` |
| `ctxa handoff [PATH]` | Assemble effective state (`Snapshot + Unincorporated Journal + Notes`) into `PROJECT_CONTEXT.md`. | `-o <file>`, `--full`, `--strict`, `--deterministic`, `--json` |
| `ctxa verify [PATH]` | Verify whether `PROJECT_CONTEXT.md` and `.context/` match the live working tree and Git state. | `--strict`, `--json` |
| `ctxa diff [PATH]` | Compute direct symbol changes and 2-hop downstream impact against a baseline snapshot. | `--since <snapshot_id>`, `--format text\|json\|mermaid` |
| `ctxa context "<task>" [PATH]` | Compile a ranked, token-budgeted context packet with dependency closure and code excerpts. | `--max-tokens 8000`, `--tokenizer heuristic\|tiktoken`, `-o <file>`, `--format md\|json` |
| `ctxa compact [PATH]` | Fold unincorporated journal entries into a new immutable snapshot (`snapshot-NNNN.json`). | `--deterministic`, `--json` |
| `ctxa rebuild [PATH]` | Force a clean L3 full rebuild and reconcile any divergent Git branch journals/notes. | `--deterministic`, `--json` |
| `ctxa export [PATH]` | Export the canonical graph bundle or architecture diagram. | `--format json\|mermaid`, `-o <file>` |
| `ctxa mcp [PATH]` | Start the read-only Model Context Protocol (MCP) server over stdio. | — |

### Standardized Exit Codes

- `0` (`EXIT_SUCCESS`): Operation succeeded; context is fresh and valid.
- `1` (`EXIT_WARNING`): Operation completed with warnings under `--strict` mode.
- `2` (`EXIT_STALE_OR_DIFF`): `ctxa verify` detected stale/dirty context (`STALE_JOURNALED` or `STALE_UNRECORDED`).
- `3` (`EXIT_CONFIG_OR_USAGE`): Invalid CLI arguments, malformed `.ctxa.toml`, or invalid target path.
- `4` (`EXIT_INTEGRITY_ERROR`): Corrupt snapshot/journal schema, broken `CTXA:MANUAL` sentinel markers, or unresolved Git merge conflicts.
- `5` (`EXIT_INTERNAL_ERROR`): Unexpected runtime or I/O failure (existing artifacts are preserved via atomic writes).

---

## Supported Languages & Framework Adapters

| Adapter / Extractor | ID | Extensions | Extracted Entities & Graph Edges |
| :--- | :--- | :--- | :--- |
| **Python AST** | `python_ast:1.0` | `.py`, `.pyi` | `File`, `Module`, `Class`, `Function`, `Method`, `Variable`, `Test`; `CONTAINS`, `DEFINES`, `IMPORTS`, `INHERITS`, `CALLS`, `TESTED_BY` |
| **FastAPI & Pydantic** | `fastapi_pydantic:1.0` | `.py` | `Endpoint` (HTTP method, route, status code, `response_model`), `Schema` (`BaseModel` fields); `EXPOSES`, `VALIDATES_WITH`, `DEPENDS_ON` |
| **SQLAlchemy / SQLModel** | `sqlalchemy_entity:1.0` | `.py` | `DataEntity` (`__tablename__`, columns); `READS`, `WRITES` |
| **TypeScript / JavaScript** | `typescript:1.0` | `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs` | `File`, `Module`, exported `Function`, `interface`/`type` `Schema`; `IMPORTS`, cross-stack `CONSUMES` (`fetch`/`axios` -> backend `Endpoint`) |
| **Polyglot Static Analyzer** | `polyglot:1.0` | `.kt`, `.kts` (Kotlin), `.java` (Java), `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx` (C/C++), `.go` (Go), `.rs` (Rust), `.cs` (C#), `.rb` (Ruby), `.php` (PHP), `.swift` (Swift) | Packages/Namespaces (`Module`), Classes/Structs/Objects/Enums (`Class`), Interfaces/Traits (`Schema`), Functions/Methods (`Function`), Spring Boot routes (`Endpoint`), JUnit/GoogleTest/Cargo/Go tests (`Test`); `IMPORTS`, `INHERITS`, `DEPENDS_ON`, `CALLS`, `EXPOSES`, `TESTED_BY` |

---

## Python SDK

`context-archive` also provides a typed Python SDK (`PEP 561` compliant):

```python
from pathlib import Path
from context_archive import ContextArchiveEngine

engine = ContextArchiveEngine(repo_root=Path("."))

# 1. Record incremental changes
update_res = engine.update(intent="Add rate limiting to POST /orders")

# 2. Verify cryptographic freshness
verify_rep = engine.verify()
print(verify_rep.status)  # "CURRENT", "STALE_JOURNALED", or "STALE_UNRECORDED"

# 3. Generate portable PROJECT_CONTEXT.md
handoff_res = engine.generate_handoff(output=Path("PROJECT_CONTEXT.md"))

# 4. Compile a token-budgeted task packet
packet = engine.compile_task_context(
    task="Investigate client reconnection and seat token validation",
    max_tokens=6000,
)
print(f"Tokens used: {packet.estimated_tokens}/{packet.max_tokens} ({packet.retrieval_mode} mode)")
print(packet.markdown)
```

---

## Model Context Protocol (MCP) Integration

To expose `ctxa` as a live, read-only MCP tool server for Claude Desktop, Cursor, or custom MCP agents, add the following to your MCP configuration:

```json
{
  "mcpServers": {
    "context-archive": {
      "command": "ctxa",
      "args": ["mcp", "/path/to/your/repository"]
    }
  }
}
```

**Exposed Read-Only MCP Tools:**
- `get_project_overview`: Returns repository identity, freshness status, cursors, module map, contracts, and human notes.
- `lookup_symbol`: Searches canonical graph nodes by symbol name, qualified name, or file path with exact `path:line` provenance.
- `get_change_impact`: Computes N-hop downstream impacted callers, importers, endpoints, and tests.
- `query_journal`: Queries recent append-only JSONL change records by limit or category.
- `compile_task_context`: Compiles a ranked, token-bounded context packet for an engineering task.
- `verify_freshness`: Verifies whether `.context/` and `PROJECT_CONTEXT.md` match the live working tree.

---

## Repository Storage Layout

```text
<your-repository>/
├── .ctxa.toml                       # Project configuration (or [tool.ctxa] in pyproject.toml)
├── PROJECT_CONTEXT.md               # Portable AI & developer handoff artifact
└── .context/
    ├── manifest.json                # Repo ID, snapshot/journal cursors, SHA-256 file fingerprints
    ├── graph.json                   # Canonical dependency graph (Nodes + Edges + Provenance)
    ├── notes.md                     # Durable human-authored decisions, constraints & next steps
    ├── journal/
    │   └── YYYY-MM.jsonl            # Append-only incremental change journal records
    ├── snapshots/
    │   └── snapshot-0001.json       # Immutable base checkpoints with incorporated journal cursors
    └── cache.sqlite                 # Disposable local fingerprint cache (gitignored automatically)
```

---

## Security & Privacy Guarantees

1. **Zero Code Execution:** `ctxa` parses source files statically and never imports target modules or executes project build scripts.
2. **Zero Network Calls:** All CLI and SDK operations run 100% locally with zero outbound telemetry or API calls.
3. **Automatic Secret Exclusion:** `.env`, `.env.*` (except `.env.example`/`.env.template`), `*.pem`, `*.key`, `*.p12`, `id_rsa*`, `*credentials*.json`, `.aws/`, `.ssh/`, and out-of-tree symlinks are blocked by default.
4. **Prompt-Injection Defense:** Extracted docstrings are sanitized of `<!-- CTXA:... -->` sentinel markers, code excerpts are fenced, and every generated artifact includes an explicit untrusted-data security orientation header.

---

## Contributing & Quality Gates

We use **Poetry**, **Ruff**, **Mypy (`--strict`)**, and **Pytest**. Every change must pass all 5 verification gates:

```bash
poetry install
poetry check --lock
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests --strict
poetry run pytest --cov=context_archive --cov-fail-under=90
```

## License

Distributed under the [MIT License](LICENSE).