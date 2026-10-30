# Phase-by-Phase Development Cycle

## Portable AI Project Context Compiler (`context-archive` / `ctxa`)

**Document Status:** Production Engineering Implementation Plan  
**Version:** 2.0.0  
**Companion Document:** `SRS.md`  
**Package & Dependency Manager:** Poetry (`poetry-core>=1.9.0`)  
**Quality Gate Toolchain:** `ruff` (linting + formatting), `mypy --strict` (static typing), `pytest` + `pytest-cov` (testing & coverage)  

---

## 1. Development Strategy & Core Engineering Rules

We are building a local-first, deterministic Python CLI and SDK (`context-archive` / `ctxa`) organized around three cooperating subsystems:
1. **Project Knowledge Engine:** Safe repository scanning, AST extraction, canonical dependency graph, and base snapshots.
2. **Incremental Change Engine:** File/Git change detection, append-only JSONL journal, partial graph invalidation, and snapshot compaction.
3. **Context Delivery Engine:** Effective-state assembly, `PROJECT_CONTEXT.md` generation, freshness verification, semantic diffs, task-specific token-budgeted packets, and optional MCP integration.

### 1.1 Unbreakable Phase Gate Rule
**No phase may be marked complete, merged to `main`, or followed by the next phase until all 5 verification gates pass with zero errors:**
```bash
poetry check --lock
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy src tests --strict
poetry run pytest --cov=context_archive --cov-fail-under=90
```

### 1.2 Master Phase Sequence
- **Phase 0:** GitHub-Ready Foundation, Poetry Bootstrap & Product Contracts
- **Phase 1:** Package Skeleton, CLI Shell, Configuration & Exit Codes
- **Phase 2:** Safe Repository Scanner, Secret Exclusion & Git State Extractor
- **Phase 3:** Canonical Graph Model, Provenance & Python AST Analyzer
- **Phase 4:** Base Snapshots, Manifest & First `PROJECT_CONTEXT.md` Generator
- **Phase 5:** Durable Human Notes, Protected Boundaries & Freshness Verification (`ctxa verify`)
- **Phase 6:** Incremental Change Detection & Append-Only Journal (`ctxa update` L1)
- **Phase 7:** Partial Graph Invalidation, Impact Analysis & Semantic Diff (`ctxa update` L2/L3 & `ctxa diff`)
- **Phase 8:** Snapshot Lifecycle, Compaction & Effective Context Assembly (`ctxa compact` & `ctxa rebuild`)
- **Phase 9:** Task-Specific Context Compiler & Pluggable Token Budgets (`ctxa context`)
- **Phase 10:** Framework Contracts (FastAPI, Pydantic, SQLAlchemy) & Cross-Stack Adapters (TypeScript/JS)
- **Phase 11:** Team Workflows, Branch Reconciliation & Optional Read-Only MCP Server (`ctxa mcp`)
- **Phase 12:** Benchmarking, Security Hardening, Packaging & v1.0.0 Release

---

## 2. Target Repository Structure (GitHub-Ready from Day 1)

```text
context-archive/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml
│   │   ├── feature_request.yml
│   │   └── config.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── dependabot.yml
│   └── workflows/
│       ├── ci.yml                  # Runs poetry check, ruff, mypy --strict, pytest matrix
│       └── release.yml             # Trusted PyPI publishing on v* tags
├── .editorconfig
├── .gitignore
├── .pre-commit-config.yaml
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── DEVELOPMENT_PLAN.md
├── LICENSE
├── Makefile                        # Convenience targets wrapping Poetry commands
├── README.md
├── SECURITY.md
├── SRS.md
├── poetry.lock
├── pyproject.toml
├── docs/
│   ├── adr/                        # Architecture Decision Records
│   ├── architecture.md
│   ├── configuration.md
│   ├── context-format.md
│   ├── schemas/                    # JSON Schemas (manifest, graph, snapshot, journal)
│   └── supported-languages.md
├── src/
│   └── context_archive/
│       ├── __init__.py
│       ├── py.typed                # PEP 561 marker for mypy
│       ├── cli.py                  # Typer CLI entrypoints
│       ├── config.py               # .ctxa.toml & pyproject.toml loader/validator
│       ├── exceptions.py           # Typed hierarchy & exit code mappings
│       ├── lock.py                 # Atomic file writes & .context/.lock manager
│       ├── scanner/
│       │   ├── __init__.py
│       │   ├── discovery.py        # Repo root & ignore rule evaluation
│       │   ├── walker.py           # Safe traversal, binary/secret filters, SHA-256
│       │   └── report.py           # ScanReport models
│       ├── git/
│       │   ├── __init__.py
│       │   └── state.py            # Commit, branch, dirty-tree & diff inspector
│       ├── model/
│       │   ├── __init__.py
│       │   ├── ids.py              # Deterministic Node/Edge/Repo ID generators
│       │   ├── provenance.py       # Source path, lines, extractor, confidence
│       │   ├── graph.py            # Canonical Node, Edge, Graph & serialization
│       │   └── manifest.py         # Manifest schema & cursor models
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── base.py             # LanguageAdapter & FrameworkExtractor Protocols
│       │   ├── python_ast.py       # Python AST symbol, import, call, test extractor
│       │   ├── fastapi.py          # FastAPI routes, Depends, Pydantic schemas
│       │   ├── sqlalchemy.py       # Database entity extractor
│       │   └── typescript.py       # TS/JS modules, exports, API client calls
│       ├── state/
│       │   ├── __init__.py
│       │   ├── snapshot.py         # Snapshot creation, loading & lineage validation
│       │   ├── journal.py          # Append-only JSONL reader/writer & cursor logic
│       │   ├── detector.py         # Change detection & Update Level (L1/L2/L3) selector
│       │   ├── invalidator.py      # Partial graph update & dependency invalidation
│       │   ├── compactor.py        # Snapshot compaction engine
│       │   └── cache.py            # Optional SQLite local cache
│       ├── notes/
│       │   ├── __init__.py
│       │   ├── manager.py          # .context/notes.md & structured annotations
│       │   └── boundaries.py       # CTXA:MANUAL sentinel parser & backup recovery
│       ├── context/
│       │   ├── __init__.py
│       │   ├── assembler.py        # Effective state (Snapshot + Unapplied Journal + Notes)
│       │   ├── verifier.py         # Freshness verification engine (ctxa verify)
│       │   ├── differ.py           # Graph diff & downstream impact traversal
│       │   ├── compiler.py         # Task-specific candidate ranking & packet builder
│       │   └── tokenizer.py        # Pluggable heuristic & tiktoken estimators
│       ├── renderers/
│       │   ├── __init__.py
│       │   ├── markdown.py         # PROJECT_CONTEXT.md deterministic renderer
│       │   ├── json_exporter.py    # Graph & manifest exporters
│       │   └── mermaid.py          # Architecture & impact Mermaid diagrams
│       └── integrations/
│           ├── __init__.py
│           └── mcp_server.py       # Optional read-only MCP stdio server
└── tests/
    ├── conftest.py                 # Shared fixtures & temporary repo builders
    ├── fixtures/                   # Representative fixture repos (lib, fastapi, fullstack)
    ├── golden/                     # Golden expected Markdown & JSON outputs
    ├── unit/                       # Fast isolated module tests
    ├── integration/                # End-to-end CLI & multi-step lifecycle tests
    └── benchmarks/                 # Speed, memory & token-budget benchmark harness
```

---

## 3. Baseline `pyproject.toml` Specification (Poetry + Ruff + Mypy + Pytest)

Phase 0 and Phase 1 must initialize `pyproject.toml` with the following strict configuration:

```toml
[tool.poetry]
name = "context-archive"
version = "0.1.0"
description = "Portable AI Project Context Compiler with incremental change journaling"
authors = ["Context Archive Contributors"]
license = "MIT"
readme = "README.md"
homepage = "https://github.com/org/context-archive"
repository = "https://github.com/org/context-archive"
keywords = ["ai", "context", "llm", "ast", "developer-tools", "mcp", "handoff"]
packages = [{ include = "context_archive", from = "src" }]
include = ["src/context_archive/py.typed"]

[tool.poetry.dependencies]
python = "^3.11"
pydantic = "^2.8.0"
typer = "^0.12.0"
rich = "^13.7.0"
pathspec = "^0.12.1"
tiktoken = { version = "^0.7.0", optional = true }
mcp = { version = "^1.0.0", optional = true }

[tool.poetry.extras]
tiktoken = ["tiktoken"]
mcp = ["mcp"]
all = ["tiktoken", "mcp"]

[tool.poetry.group.dev.dependencies]
pytest = "^8.3.0"
pytest-cov = "^5.0.0"
pytest-randomly = "^3.15.0"
hypothesis = "^6.112.0"
ruff = "^0.6.0"
mypy = "^1.11.0"
pre-commit = "^3.8.0"

[tool.poetry.scripts]
ctxa = "context_archive.cli:app"

[build-system]
requires = ["poetry-core>=1.9.0"]
build-backend = "poetry.core.masonry.api"

[tool.ruff]
target-version = "py311"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E", "W",   # pycodestyle
    "F",        # pyflakes
    "I",        # isort
    "B",        # flake8-bugbear
    "C4",       # flake8-comprehensions
    "UP",       # pyupgrade
    "SIM",      # flake8-simplify
    "TCH",      # flake8-type-checking
    "PTH",      # flake8-use-pathlib
    "RUF",      # ruff-specific
    "S",        # flake8-bandit (security)
]
ignore = ["S101"] # Allow assert in tests (enforced via per-file-ignores for src)

[tool.ruff.lint.per-file-ignores]
"src/**" = ["S101"]
"tests/**" = ["S101", "S105", "S106", "S603", "S607"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_any_generics = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
plugins = ["pydantic.mypy"]
mypy_path = "src"

[tool.pytest.ini_options]
minversion = "8.0"
addopts = "-ra -q --strict-markers --strict-config"
testpaths = ["tests"]
markers = [
    "unit: fast isolated unit tests",
    "integration: end-to-end filesystem and CLI workflow tests",
    "golden: deterministic golden-file comparison tests",
    "benchmark: performance and token budget benchmarks",
]

[tool.coverage.run]
source = ["src/context_archive"]
branch = true

[tool.coverage.report]
fail_under = 90
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

---

## 4. Phase-by-Phase Execution Plan

---

### Phase 0 — GitHub-Ready Foundation, Poetry Bootstrap & Product Contracts

#### Objective
Initialize a clean, reproducible Poetry environment, configure all GitHub repository governance and CI workflows, lock down JSON Schemas, and build synthetic fixture repositories before feature code spreads.

#### Tasks
1. Initialize Git repository and create `.gitignore`, `.editorconfig`, `LICENSE` (MIT), `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `CHANGELOG.md`.
2. Author `.github/workflows/ci.yml` running `poetry check --lock`, `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest` across Ubuntu, macOS, and Windows on Python 3.11, 3.12, and 3.13.
3. Add `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`, and `.pre-commit-config.yaml`.
4. Initialize `pyproject.toml` with Poetry and generate `poetry.lock`.
5. Author formal JSON Schema files under `docs/schemas/`:
   - `manifest.schema.json`
   - `graph.schema.json`
   - `snapshot.schema.json`
   - `journal-record.schema.json`
6. Create three deterministic fixture repositories under `tests/fixtures/`:
   - `fixture_py_lib`: Pure Python package with modules, classes, relative imports, decorators, and pytest tests.
   - `fixture_fastapi`: FastAPI + Pydantic + SQLAlchemy service with routes, dependencies, schemas, and tests.
   - `fixture_edge_cases`: Syntax errors, binary files with `.py` extensions, fake `.env` secrets, broken symlinks, and prompt-injection docstrings.
7. Document ADRs (`docs/adr/001-canonical-ids.md`, `002-incremental-journal-cursors.md`, `003-manual-note-boundaries.md`).

#### Mandatory Phase 0 Quality Gates & Tests
- **Pytest (`tests/unit/test_bootstrap.py`):**
  - Verify package version import and `py.typed` existence.
  - Validate that all fixture directories exist and contain expected test files.
  - Validate that all JSON schema files in `docs/schemas/` are valid Draft 2020-12 JSON Schemas.
- **Ruff & Mypy:**
  - `poetry run ruff check .` -> 0 errors.
  - `poetry run ruff format --check .` -> 0 formatting diffs.
  - `poetry run mypy src tests --strict` -> 0 issues.

#### Deliverables
- GitHub-ready repository skeleton, CI workflow, `pyproject.toml`, `poetry.lock`, JSON Schemas, ADRs, and test fixtures.

#### Exit Criteria
- CI pipeline runs green on GitHub Actions; `poetry install` creates a working environment; all 5 phase gate commands pass.

---

### Phase 1 — Package Skeleton, CLI Shell, Configuration & Atomic Primitives

#### Objective
Deliver an installable `ctxa` CLI with complete subcommand stubs, standardized exit codes, repository root discovery, typed `.ctxa.toml` / `pyproject.toml` configuration loading, and atomic file-writing / locking utilities.

#### Tasks
1. Implement `src/context_archive/exceptions.py` with typed exceptions mapped to `SRS.md` exit codes (`0` through `5`).
2. Implement `src/context_archive/lock.py`:
   - `atomic_write_text()` and `atomic_write_bytes()` using temporary files in the target directory + `os.replace()`.
   - `ContextLock` context manager managing `.context/.lock` with PID and stale lock recovery.
3. Implement `src/context_archive/scanner/discovery.py` to locate `repo_root` via explicit path, `.ctxa.toml`, `pyproject.toml` (`[tool.ctxa]`), or `.git`.
4. Implement `src/context_archive/config.py` using Pydantic v2 models (`CtxaConfig`, `ScannerConfig`, `JournalConfig`, `ContextConfig`) with strict validation and deterministic SHA-256 `config_fingerprint` calculation.
5. Implement `src/context_archive/cli.py` with Typer commands (`init`, `update`, `note`, `handoff`, `verify`, `diff`, `context`, `compact`, `rebuild`, `export`), `--version`, `--help`, and structured error handling.

#### Mandatory Phase 1 Quality Gates & Tests
- **Pytest (`tests/unit/test_config.py`, `tests/unit/test_lock.py`, `tests/integration/test_cli_shell.py`):**
  - Test `--help` and `--version` execution via `typer.testing.CliRunner` and subprocess `poetry run ctxa`.
  - Test configuration precedence: CLI flags > `.ctxa.toml` > `pyproject.toml [tool.ctxa]` > defaults.
  - Test invalid configuration types/keys fail immediately with exit code `3` (`EXIT_CONFIG_OR_USAGE`).
  - Test `config_fingerprint` stability across key reorderings in TOML.
  - Test `atomic_write_text` leaves existing destination file completely intact when an exception is injected mid-write.
  - Test `ContextLock` blocks concurrent acquisition and recovers from dead-PID lock files.
- **Ruff & Mypy:**
  - `poetry run ruff check .` & `poetry run ruff format --check .` pass.
  - `poetry run mypy src tests --strict` passes with zero untyped CLI decorators or `Any` leaks.

#### Deliverables
- Working `ctxa` CLI, configuration engine, atomic file writer, lock manager, and Phase 1 test suite.

#### Exit Criteria
- `poetry build` builds a wheel that installs in a clean virtualenv and runs `ctxa --help`; all unit/integration tests, Ruff, and Mypy checks pass with >= 90% coverage.

---

### Phase 2 — Safe Repository Scanner, Secret Exclusion & Git State Extractor

#### Objective
Discover and classify repository files safely without executing target code, enforce `.gitignore` and secret exclusions, compute SHA-256 file fingerprints, and extract Git metadata.

#### Tasks
1. Implement `src/context_archive/scanner/walker.py`:
   - Walk directory tree respecting `max_depth` and `max_file_size_bytes`.
   - Enforce path containment (`resolved_path.is_relative_to(repo_root)`) and symlink loop detection via `(st_dev, st_ino)`.
   - Evaluate `.gitignore`, `.ignore`, default excludes (`.venv`, `node_modules`, `__pycache__`, etc.), and secret globs (`.env*` except `.env.example`, `*.pem`, `*.key`, credentials) using `pathspec`.
   - Detect binary files via null-byte inspection in the first 8 KB and handle non-UTF-8 encodings gracefully without crashing.
   - Compute file SHA-256 fingerprints and detect mid-scan file modifications via pre/post `stat` checks.
   - Classify files (`source_code`, `test`, `manifest`, `config`, `documentation`, `unsupported`, `excluded`).
2. Implement `src/context_archive/git/state.py`:
   - Extract commit SHA, branch name (or `DETACHED_HEAD`), dirty status, staged/unstaged/untracked counts, and sanitized remote URL via safe subprocess calls (`git status --porcelain=v2 --branch`) with fallback when Git is absent.
   - Compute deterministic `repository_id` from initial commit SHA or normalized root manifest identity.
3. Implement `src/context_archive/scanner/report.py` producing an immutable, serializable `ScanReport`.

#### Mandatory Phase 2 Quality Gates & Tests
- **Pytest (`tests/unit/test_scanner.py`, `tests/unit/test_git_state.py`, `tests/integration/test_safe_scan.py`):**
  - **Zero-Execution Security Test:** Scan a file containing `raise RuntimeError("EXECUTED")` at top level; verify it is inventoried without execution.
  - **Secret Exclusion Test:** Verify `.env`, `.env.production`, `id_rsa`, `server.pem`, and `aws_credentials.json` are excluded by default while `.env.example` is allowed, and secret file contents never appear in logs or reports.
  - **Symlink Escape & Cycle Test:** Create a symlink pointing to `/etc/passwd` (or outside `tmp_path`) and a circular directory symlink; verify both are safely skipped and logged as diagnostics.
  - **Binary & Corrupt Encoding Test:** Verify invalid UTF-8 bytes and null-byte binary files with `.py` extensions are skipped cleanly without raising unhandled exceptions.
  - **Git Matrix Test:** Test clean Git repo, dirty working tree, untracked files, detached HEAD, newborn repo with 0 commits, and non-Git directory.
- **Ruff & Mypy:**
  - `poetry run ruff check .` (including Bandit `S` security rules on `subprocess` calls in `git/state.py`) passes.
  - `poetry run ruff format --check .` and `poetry run mypy src tests --strict` pass.

#### Deliverables
- `scanner` module, `git` state extractor, `ScanReport` model, and security/edge-case test suite.

#### Exit Criteria
- Scanner inventories all fixture repositories accurately, blocks all secret/escape vectors, handles non-Git directories, and passes all 5 quality gates.

---

### Phase 3 — Canonical Graph Model, Provenance & Python AST Analyzer

#### Objective
Convert scanned Python files into a deterministic, schema-versioned canonical graph of `Nodes` and `Edges` backed by exact source provenance.

#### Tasks
1. Implement `src/context_archive/model/ids.py` to generate deterministic, POSIX-normalized IDs for repositories, files, modules, classes, functions, methods, variables, tests, and edges.
2. Implement `src/context_archive/model/provenance.py` (`Provenance`, `EvidenceKind`, `ConfidenceLevel`).
3. Implement `src/context_archive/model/graph.py` (`CanonicalGraph`, `Node`, `Edge`, `Diagnostic`) with deterministic sorting of nodes and edges upon JSON serialization and graph query primitives (inbound/outbound neighbors, subgraph slicing).
4. Implement `src/context_archive/adapters/base.py` defining the `LanguageAdapter` protocol.
5. Implement `src/context_archive/adapters/python_ast.py`:
   - Parse Python source via `ast.parse()` without importing or executing modules.
   - Extract `Module`, `Class`, `Function`, and `Method` nodes with full signatures (arguments, defaults, type annotations, return annotations), async markers, decorators, and sanitized first-paragraph docstrings.
   - Resolve absolute and relative intra-repository `IMPORTS` edges across `src/` and flat package layouts.
   - Extract statically resolvable `CALLS` and `INHERITS` edges (`evidence_kind="deterministic"` for resolved imports/local defs; record unresolved dynamic `getattr`/`eval` calls as diagnostics rather than fake edges).
   - Identify test files and link `TESTED_BY` edges from test functions to imported/invoked target symbols.

#### Mandatory Phase 3 Quality Gates & Tests
- **Pytest (`tests/unit/test_model.py`, `tests/unit/test_python_ast.py`, `tests/integration/test_graph_determinism.py`):**
  - Test AST extraction on nested classes, async functions, `@property` / custom decorators, `*args`/`**kwargs`, type unions (`X | Y`), and multi-level relative imports (`from ..core import utils`).
  - **Determinism Property Test:** Run extraction twice on `fixture_py_lib` in shuffled file discovery orders; assert serialized `graph.json` strings are byte-for-byte identical.
  - **Syntax Error Resilience Test:** Analyze `fixture_edge_cases` containing a broken `.py` file alongside valid `.py` files; verify valid files populate the graph and the broken file adds a `SyntaxError` diagnostic without crashing.
  - **Provenance Accuracy Test:** Verify every extracted node's `line_start` and `line_end` point to the exact `def`/`class` lines in the fixture source file.
  - **Prompt-Injection Sanitization Test:** Verify docstrings containing `<!-- CTXA:MANUAL:END -->` have sentinel markers neutralized during extraction.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- Canonical model, deterministic ID generator, Python AST adapter, graph traversal primitives, and JSON Schema validation tests.

#### Exit Criteria
- Python repositories are parsed into valid, deterministic `CanonicalGraph` instances conforming to `docs/schemas/graph.schema.json`, passing all 5 quality gates.

---

### Phase 4 — Base Snapshots, Manifest & First `PROJECT_CONTEXT.md` Generator

#### Objective
Ship the first end-to-end command (`ctxa init` and `ctxa handoff`) that creates an initial base snapshot (`snapshot-0001.json`), writes `.context/manifest.json` and `.context/graph.json`, and renders a deterministic, portable `PROJECT_CONTEXT.md`.

#### Tasks
1. Implement `src/context_archive/model/manifest.py` and `src/context_archive/state/snapshot.py` to create and validate `.context/manifest.json` and `.context/snapshots/snapshot-0001.json`.
2. Implement `src/context_archive/renderers/markdown.py`:
   - Render the orientation/security header (`CTXA:HEADER`) and all 13 standard headings defined in `SRS.md` Section 10.
   - Extract quick-start and test commands from `pyproject.toml`, `Makefile`, or `package.json` where present.
   - Render architecture summary, module index, key symbol signatures with `path:line` provenance links, test coverage map, and extraction limitations.
   - Include empty/initial `CTXA:MANUAL:START` / `CTXA:MANUAL:END` sections for Sections 11–13.
3. Implement `src/context_archive/renderers/json_exporter.py` for `ctxa export --format json`.
4. Wire `ctxa init` and `ctxa handoff [--output] [--deterministic] [--strict] [--json]` in `cli.py`.

#### Mandatory Phase 4 Quality Gates & Tests
- **Pytest (`tests/unit/test_markdown_renderer.py`, `tests/golden/test_handoff_golden.py`, `tests/integration/test_init_and_handoff.py`):**
  - **Golden-File Regression Test:** Run `ctxa handoff --deterministic` on `fixture_py_lib` and compare `PROJECT_CONTEXT.md` and `graph.json` against `tests/golden/fixture_py_lib/`.
  - Verify all 13 required headings and sentinel comments (`CTXA:HEADER`, `CTXA:GENERATED`, `CTXA:MANUAL`) exist in generated output.
  - Verify `--strict` exits with code `1` (`EXIT_WARNING`) when a repository contains unparseable Python files, and `0` on clean repositories.
  - Test atomic output: simulate an exception during Markdown rendering and verify an existing `PROJECT_CONTEXT.md` is not corrupted.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- `ctxa init`, `ctxa handoff`, `ctxa export`, snapshot writer, manifest writer, Markdown renderer, and golden test suite.

#### Exit Criteria
- Running `ctxa handoff` on any Python project produces a complete, verifiable `PROJECT_CONTEXT.md` and `.context/` directory in one command; all 5 quality gates pass.

---

### Phase 5 — Durable Human Notes, Protected Boundaries & Freshness Verification (`ctxa verify`)

#### Objective
Guarantee that human-authored architectural decisions and notes are never lost across regenerations, and implement `ctxa verify` to detect stale or modified repository states.

#### Tasks
1. Implement `src/context_archive/notes/boundaries.py`:
   - Parse `PROJECT_CONTEXT.md` to locate `<!-- CTXA:MANUAL:START ... -->` and `<!-- CTXA:MANUAL:END -->`.
   - Validate marker count and order. If markers are missing, duplicated, or inverted, save `PROJECT_CONTEXT.md.bak` and raise `IntegrityError` (exit code `4`).
2. Implement `src/context_archive/notes/manager.py`:
   - Manage `.context/notes.md` with structured sections (`Decisions & Constraints`, `Known Issues & Risks`, `Pending Work & Next Steps`).
   - Implement two-way synchronization: edits made directly inside `PROJECT_CONTEXT.md`'s manual block are synced back to `.context/notes.md` before regeneration, and entries added via `ctxa note "<text>" [--type ...] [--scope ...]` are appended with UTC timestamps and `origin: developer_confirmed`.
3. Implement `src/context_archive/context/verifier.py` (`ctxa verify`):
   - Compare `.context/manifest.json` against live Git commit, branch, dirty status, `config_fingerprint`, `notes_fingerprint`, and SHA-256 digests of all tracked files.
   - Return structured `VerificationReport` with status `CURRENT` (exit `0`), `STALE_JOURNALED` (exit `2`), `STALE_UNRECORDED` (exit `2`), or `CORRUPT_OR_MISSING` (exit `4`).

#### Mandatory Phase 5 Quality Gates & Tests
- **Pytest (`tests/unit/test_notes.py`, `tests/unit/test_verifier.py`, `tests/integration/test_notes_and_verify.py`):**
  - **Note Survival Test:** Add 3 notes via `ctxa note`, manually edit Section 11 inside `PROJECT_CONTEXT.md`, and run `ctxa handoff` 5 times; assert both CLI notes and manual Markdown edits are preserved in `PROJECT_CONTEXT.md` and `.context/notes.md`.
  - **Corrupt Boundary Recovery Test:** Delete `<!-- CTXA:MANUAL:END -->` from `PROJECT_CONTEXT.md` and run `ctxa handoff`; verify exit code is `4`, `PROJECT_CONTEXT.md.bak` is created with the user's text intact, and no data is lost.
  - **Freshness Detection Matrix:**
    - Immediately after `ctxa handoff` -> `ctxa verify` exits `0` (`CURRENT`).
    - Modify 1 byte in a tracked `.py` file -> `ctxa verify` exits `2` (`STALE_UNRECORDED`) and names the modified file.
    - Add a new `.py` file -> `ctxa verify` exits `2`.
    - Modify `.ctxa.toml` -> `ctxa verify` exits `2` (config fingerprint mismatch).
    - Switch Git branch -> `ctxa verify` exits `2` (branch mismatch).
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- `notes` subsystem, `ctxa note`, `ctxa verify`, boundary recovery mechanism, and verification test suite.

#### Exit Criteria
- Human notes are 100% protected against overwrite/corruption and `ctxa verify` catches every category of repository drift; all 5 quality gates pass.

---

### Phase 6 — Incremental Change Detection & Append-Only Journal (`ctxa update` L1)

#### Objective
Record localized repository changes as compact, evidence-backed records in an append-only JSONL journal (`.context/journal/YYYY-MM.jsonl`) without regenerating the entire project graph.

#### Tasks
1. Implement `src/context_archive/state/detector.py`:
   - Diff current working tree against `manifest.file_fingerprints` and Git status to identify `added`, `modified`, `deleted`, and `renamed` files (via SHA-256 content matching).
   - Compare AST symbol signatures of modified files against existing graph nodes to classify update scope as **L1 (Journal-Only)** when only function bodies, comments, or docstrings changed, vs. **L2/L3** when signatures, imports, or files changed.
   - Implement deterministic change categorization (`docs_change`, `test_change`, `config_change`, `dependency_change`, `contract_change`, `schema_change`, `revert`, `unknown`).
2. Implement `src/context_archive/state/journal.py`:
   - Append validated `JournalRecord` objects to `.context/journal/YYYY-MM.jsonl` with monotonic IDs (`CA-YYYYMMDD-NNNN`), `parent_change_id` linkage, and atomic file locking.
   - Enforce idempotency: if current `tree_fingerprint` and `config_fingerprint` match the head journal record (or base snapshot if no unincorporated records exist), `ctxa update` performs a no-op and appends nothing.
3. Wire `ctxa update [--level auto|l1|l2|l3] [--message "<intent>"] [--json]` in `cli.py`.

#### Mandatory Phase 6 Quality Gates & Tests
- **Pytest (`tests/unit/test_detector.py`, `tests/unit/test_journal.py`, `tests/integration/test_incremental_update_l1.py`):**
  - **Idempotency Test:** Modify a function body, run `ctxa update` 3 consecutive times; verify only 1 record is written to `.jsonl`.
  - **Revert Tracking Test:** Modify a file, run `ctxa update`, revert the file to its original contents, and run `ctxa update`; verify a second journal record with `category="revert"` is appended and the first record remains intact.
  - **Rename Detection Test:** `git mv` (or move) a file without changing its content; verify detector classifies it as `renamed` via SHA-256 matching.
  - **Developer Intent Test:** Run `ctxa update --message "Fix off-by-one error"`; verify `intent.origin == "developer_confirmed"` and `intent.confidence == "high"`.
  - Validate every emitted JSONL line against `docs/schemas/journal-record.schema.json`.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- Change detector, append-only JSONL journal engine, deterministic classifier, and `ctxa update` L1 workflow.

#### Exit Criteria
- Localized code edits are recorded in `< 350ms` as schema-valid JSONL journal records with strict idempotency; all 5 quality gates pass.

---

### Phase 7 — Partial Graph Invalidation, Impact Analysis & Semantic Diff (`ctxa update` L2/L3 & `ctxa diff`)

#### Objective
Enable partial graph updates (`L2`) that re-analyze only changed files and invalidated dependents while guaranteeing equivalence with full rebuilds (`L3`), and deliver `ctxa diff` with downstream impact traversal.

#### Tasks
1. Implement `src/context_archive/state/invalidator.py`:
   - Given modified/added/deleted files, identify all directly defined symbols and outbound edges in `CanonicalGraph`.
   - Identify reverse-dependent modules/symbols via inbound `IMPORTS`, `CALLS`, `INHERITS`, `EXPOSES`, and `TESTED_BY` edges.
   - Re-run `LanguageAdapter` on modified files and affected dependents, splice updated nodes/edges into the canonical graph, and recompute deterministic edge IDs.
   - Escalate automatically to **L3 (Full Checkpoint)** if configuration changed, > 30% of repository files changed, or unresolved cross-module wildcard imports prevent safe partial invalidation.
2. Implement `src/context_archive/context/differ.py` (`ctxa diff`):
   - Compute structural diffs between any two graphs/snapshots (added, removed, modified files, symbols, signatures, and contracts).
   - Traverse up to `N` hops (default `2`) from modified symbols to report downstream impacted callers (`CALLS`), importers (`IMPORTS`), and tests (`TESTED_BY`), explicitly tagging each as `direct` vs. `inferred_downstream`.
3. Implement `src/context_archive/renderers/mermaid.py` to render architecture and diff impact subgraphs as Mermaid flowcharts (`ctxa diff --format mermaid`).

#### Mandatory Phase 7 Quality Gates & Tests
- **Pytest (`tests/unit/test_invalidator.py`, `tests/unit/test_differ.py`, `tests/integration/test_incremental_equivalence.py`):**
  - **Incremental vs. Full Rebuild Equivalence Test (Critical Gate):** On `fixture_py_lib`, apply a multi-step sequence: (1) edit a function signature, (2) add a new helper module and import it, (3) delete an unused function, (4) update a test. Run `ctxa update` (L2) after each step. Then run `ctxa rebuild` (L3) on a clone of the final tree. Assert the resulting `CanonicalGraph` nodes and edges are 100% identical.
  - **Impact Traversal Test:** Modify `calculate_total` in `pricing.py`; run `ctxa diff` and verify it identifies `calculate_total` as a `direct` change and `post_checkout` (caller) + `test_calculate_total` (test) as `inferred_downstream` impacts with exact `path:line` provenance.
  - **Mermaid Rendering Test:** Verify `ctxa diff --format mermaid` outputs valid Mermaid syntax with deterministic node ordering.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- Partial graph invalidator, L2/L3 escalation logic, `ctxa diff` impact analyzer, Mermaid renderer, and incremental equivalence test suite.

#### Exit Criteria
- Partial graph updates match full rebuilds 100% of the time and `ctxa diff` accurately surfaces downstream callers and tests; all 5 quality gates pass.

---

### Phase 8 — Snapshot Lifecycle, Compaction & Effective Context Assembly (`ctxa compact` & `ctxa rebuild`)

#### Objective
Prevent unbounded journal growth by implementing snapshot compaction (`ctxa compact`) and effective-state assembly so `PROJECT_CONTEXT.md` always reflects `Latest Snapshot + Unincorporated Journal Entries + Active Notes`.

#### Tasks
1. Implement `src/context_archive/context/assembler.py`:
   - Load latest snapshot (`snapshot-NNNN.json`) referenced in `manifest.json`.
   - Read `.context/journal/*.jsonl` and filter strictly for records where `change_id > snapshot_incorporated_journal_cursor` and `record_status == "active"` (excluding any IDs listed in `supersedes`).
   - Validate lineage continuity (`parent_change_id` chain). Raise `IntegrityError` if journal records are missing or out of order.
   - Combine with active notes from `.context/notes.md` to produce `EffectiveContext`.
2. Implement `src/context_archive/state/compactor.py` (`ctxa compact` and `ctxa rebuild`):
   - Create `snapshot-(N+1).json` storing `parent_snapshot_id`, `incorporated_journal_cursor` (head `change_id`), and `incorporated_change_ids`.
   - Update `manifest.json` cursors so subsequent assemblies skip already-incorporated journal records while leaving `.context/journal/*.jsonl` intact on disk.
   - Emit automatic compaction recommendation warnings when unincorporated journal records exceed configured thresholds (`> 25` records or `> 4,000` tokens).
3. Implement `src/context_archive/state/cache.py` (optional disposable `.context/cache.sqlite` for fast AST/fingerprint lookups with automatic rebuild on corruption).

#### Mandatory Phase 8 Quality Gates & Tests
- **Pytest (`tests/unit/test_assembler.py`, `tests/unit/test_compactor.py`, `tests/integration/test_snapshot_lifecycle.py`):**
  - **No-Double-Replay Test:** Create initial snapshot, perform 5 `ctxa update` cycles, run `ctxa compact` (creating `snapshot-0002.json`), perform 2 more `ctxa update` cycles, and run `ctxa handoff`. Verify `Recent Incremental Changes` in `PROJECT_CONTEXT.md` lists only the 2 post-compaction changes while the structural sections reflect all 7 changes.
  - **Historical Preservation Test:** Verify `ctxa compact` never deletes or truncates `.context/journal/YYYY-MM.jsonl`.
  - **Corrupt SQLite Cache Recovery Test:** Write random garbage bytes into `.context/cache.sqlite` and run `ctxa handoff`; verify `ctxa` detects corruption, rebuilds the cache silently from source/snapshots, and succeeds with exit code `0`.
  - **Broken Journal Lineage Test:** Manually delete an intermediate line from a `.jsonl` file; verify `assembler` detects the missing `parent_change_id` link and alerts the user to run `ctxa rebuild`.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- Effective context assembler, snapshot compactor, `ctxa compact`, `ctxa rebuild`, resilient SQLite cache, and lifecycle tests.

#### Exit Criteria
- Long-lived repositories can accumulate hundreds of journal entries, compact them into clean checkpoints without losing history, and assemble current context instantaneously; all 5 quality gates pass.

---

### Phase 9 — Task-Specific Context Compiler & Pluggable Token Budgets (`ctxa context`)

#### Objective
Implement `ctxa context "<task>" --max-tokens N` to compile a ranked, token-budgeted context packet tailored to a specific engineering prompt without requiring an LLM.

#### Tasks
1. Implement `src/context_archive/context/tokenizer.py`:
   - Define `TokenEstimator` protocol.
   - Implement `HeuristicTokenEstimator` (deterministic lexical/character weighting with a 5% conservative safety buffer, zero external dependencies).
   - Implement optional `TiktokenEstimator` (supporting `cl100k_base` and `o200k_base` when the `tiktoken` extra is installed).
2. Implement `src/context_archive/context/compiler.py`:
   - Tokenize the task prompt (split `camelCase`/`snake_case`, extract file paths and symbol names, strip stop words).
   - Score nodes in `EffectiveContext` using a transparent deterministic formula:
     - Exact/prefix match on symbol name, qualified name, or file path (`+50` / `+25`).
     - Match in docstring or endpoint path (`+15`).
     - Graph proximity: 1-hop (`+20`) and 2-hop (`+10`) neighbors of seed nodes via `CALLS`, `IMPORTS`, `EXPOSES`, `VALIDATES_WITH`, `TESTED_BY`.
     - Modified in unincorporated journal entries (`+15`).
   - Allocate budget across strict priority tiers:
     1. Mandatory orientation header + active global constraints/decisions.
     2. Top-ranked seed symbols (signatures, provenance, concise docstrings/excerpts).
     3. Directly linked API/schema contracts and immediate callers/callees.
     4. Linked test functions (`TESTED_BY`) and relevant recent journal records.
     5. High-level repository module map (if budget remains).
   - Deduplicate repeated nodes and append a `Context Packet Manifest` footer reporting estimated tokens, tokenizer used, snapshot/journal cursor, and a list of high-scoring candidates omitted due to budget limits.

#### Mandatory Phase 9 Quality Gates & Tests
- **Pytest (`tests/unit/test_tokenizer.py`, `tests/unit/test_compiler.py`, `tests/integration/test_task_context.py`):**
  - **Strict Budget Enforcement Test (Hypothesis property test):** Across budgets ranging from `500` to `16,000` tokens and varied task strings, assert `estimator.count(packet.markdown) <= max_tokens` 100% of the time.
  - **Relevance & Contract Inclusion Test:** Query `ctxa context "Update calculate_total tax rounding" --max-tokens 3000`; verify `calculate_total`, its caller route, its test `test_calculate_total`, and project-wide constraints are all included, while unrelated modules are excluded.
  - **Omission Transparency Test:** Constrain budget to `600` tokens so only top seeds fit; verify the packet footer explicitly lists the truncated neighbor symbols under `Omitted Candidates`.
  - **Low-Information Fallback Test:** Query a generic prompt (`"Fix bug"`); verify compiler falls back to a balanced architectural overview + recent journal changes without crashing or fabricating data.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- `tokenizer` module, `compiler` ranking and budgeting engine, `ctxa context` command, and property-based budget tests.

#### Exit Criteria
- `ctxa context` reliably produces explainable, token-bounded Markdown and JSON packets that never exceed `--max-tokens`; all 5 quality gates pass.

---

### Phase 10 — Framework Contracts (FastAPI, Pydantic, SQLAlchemy) & Cross-Stack Adapters (TypeScript/JS)

#### Objective
Extract first-class API routes, validation schemas, database models, and TypeScript/JavaScript frontend modules to link cross-stack contracts in handoffs and impact analyses.

#### Tasks
1. Implement `src/context_archive/adapters/fastapi.py`:
   - Detect `FastAPI` and `APIRouter` instances and route decorators (`.get`, `.post`, `.put`, `.delete`, `.patch`).
   - Extract HTTP method, normalized path string, handler function, `response_model`, request body parameter types, `Depends(...)` callables, and status codes into `Endpoint` nodes with `EXPOSES` and `DEPENDS_ON` edges.
   - Extract Pydantic `BaseModel` subclasses and field definitions (`name`, `type`, `default`) into `Schema` nodes linked via `VALIDATES_WITH`.
2. Implement `src/context_archive/adapters/sqlalchemy.py`:
   - Extract SQLAlchemy declarative models / `SQLModel` table classes (`__tablename__`, primary/foreign keys, column types) into `DataEntity` nodes linked to services/routes via `READS` / `WRITES` where referenced.
3. Implement `src/context_archive/adapters/typescript.py`:
   - Parse `.ts`, `.tsx`, `.js`, `.jsx` files to extract ES module `import`/`export` declarations, exported functions/components, TypeScript `interface`/`type` declarations, and static `fetch(...)` / `axios.<method>(...)` API call sites.
   - Link frontend API call sites (`CONSUMES` edges) to backend `Endpoint` nodes when static URL path templates match, marking dynamic URL interpolations as `heuristic` (`confidence="medium"`).
4. Add an `AdapterConformanceSuite` base test class ensuring every adapter honors partial invalidation (`L2`), deterministic ID generation, and incremental equivalence.

#### Mandatory Phase 10 Quality Gates & Tests
- **Pytest (`tests/unit/test_fastapi_adapter.py`, `tests/unit/test_sqlalchemy_adapter.py`, `tests/unit/test_typescript_adapter.py`, `tests/integration/test_cross_stack_contracts.py`):**
  - Run analysis on `fixture_fastapi` and verify all routes, Pydantic request/response schemas, `Depends` dependencies, and SQLAlchemy tables appear in Section 6 (`API, Schema & Data Contracts`) of `PROJECT_CONTEXT.md`.
  - **Cross-Stack Impact Test:** Modify a Pydantic response schema field in the Python backend of a full-stack fixture; run `ctxa diff` and verify it traces impact from `Schema` -> `Endpoint` -> TypeScript frontend caller (`CONSUMES`).
  - **Incremental Conformance Test:** Verify modifying a single FastAPI route or `.ts` file triggers an L2 partial update that matches a full L3 rebuild.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- FastAPI/Pydantic extractor, SQLAlchemy/SQLModel extractor, TypeScript/JavaScript adapter, cross-stack linker, and adapter conformance test suite.

#### Exit Criteria
- Frontend/backend repositories generate unified contract maps and cross-stack impact warnings with full incremental equivalence; all 5 quality gates pass.

---

### Phase 11 — Team Workflows, Branch Reconciliation & Optional Read-Only MCP Server (`ctxa mcp`)

#### Objective
Enable safe context sharing across Git branches and developers, detect divergent histories without silent overwrites, and provide an optional read-only Model Context Protocol (`ctxa mcp`) server for live agent queries.

#### Tasks
1. Implement branch divergence and team reconciliation in `src/context_archive/context/verifier.py` and `assembler.py`:
   - Detect when `.context/` artifacts were generated on a different branch or non-ancestor Git commit.
   - Detect merge conflicts or divergent `parent_change_id` forks in `.context/journal/*.jsonl`.
   - Refuse to silently drop conflicting notes or journal records; provide clear reconciliation instructions and `ctxa rebuild` recovery while preserving all unioned journal records and human notes.
2. Implement snapshot/context bundle import and export (`ctxa export` / `ctxa handoff`) for clean-clone verification.
3. Implement `src/context_archive/integrations/mcp_server.py` (guarded behind optional `mcp` dependency so core installs never require it):
   - Expose read-only MCP tools over stdio:
     - `get_project_overview()`
     - `lookup_symbol(query: str)`
     - `get_change_impact(symbol_or_path: str, max_hops: int = 2)`
     - `query_journal(limit: int = 10, category: str | None = None)`
     - `compile_task_context(task: str, max_tokens: int = 6000)`
     - `verify_freshness()`
   - Every MCP response must include `freshness_status`, `snapshot_id`, `journal_cursor`, and source `provenance` references.
   - Expose zero file-write or shell-execution capabilities.

#### Mandatory Phase 11 Quality Gates & Tests
- **Pytest (`tests/unit/test_branch_reconciliation.py`, `tests/unit/test_mcp_server.py`, `tests/integration/test_team_handoff.py`):**
  - **Branch Divergence Simulation Test:** In a temporary Git repo, create `branch-a` and `branch-b` from `main`, run `ctxa update` and `ctxa note` independently on both branches, merge them, and verify `ctxa` detects the dual journal heads, preserves both developers' notes, and cleanly reconciles via `ctxa rebuild`.
  - **Cross-Clone Handoff Test:** Clone a repository containing committed `.context/` and `PROJECT_CONTEXT.md` into a new directory; verify `ctxa verify` passes (`CURRENT`) and a receiving agent/developer can run `ctxa context` immediately without rebuilding.
  - **MCP Server Contract & Security Test:** Invoke all 6 MCP tool handlers directly and via stdio protocol client; verify JSON schema compliance, provenance presence, stale-context warnings when a file is dirty, and confirm core CLI works when `mcp` package is not installed.
- **Ruff & Mypy:**
  - `poetry run ruff check .`, `poetry run ruff format --check .`, and `poetry run mypy src tests --strict` pass.

#### Deliverables
- Branch divergence detector, journal/note reconciliation workflow, optional read-only MCP server (`ctxa mcp`), and team handoff integration tests.

#### Exit Criteria
- Context artifacts survive multi-developer Git branch workflows safely, and MCP-capable agents can query live project context with strict read-only guarantees; all 5 quality gates pass.

---

### Phase 12 — Benchmarking, Security Hardening, Packaging & v1.0.0 Release

#### Objective
Prove performance, memory bounds, and token efficiency via automated benchmarks, complete end-to-end security auditing, finalize documentation, and publish a production-ready v1.0.0 package.

#### Tasks
1. Implement `tests/benchmarks/bench_performance.py` and `bench_token_efficiency.py`:
   - Measure cold L3 scan/handoff latency (`< 2.5s` target on 250-file synthetic repo), L1/L2 incremental update latency (`< 350ms` target), `ctxa verify` latency (`< 200ms` target), and peak RSS memory (`< 250 MB` target).
   - Measure token budget accuracy and compare compiled task context size against raw file-dump baselines across 10 standardized engineering tasks.
2. Perform comprehensive security and edge-case audit:
   - Fuzz configuration parser, manual note boundary parser, and AST docstring sanitizer with `hypothesis`.
   - Verify `.env`, private keys, credentials, and out-of-tree symlinks cannot leak through `PROJECT_CONTEXT.md`, `graph.json`, `journal/*.jsonl`, `ctxa context`, or `ctxa mcp`.
3. Finalize documentation in `docs/` (`architecture.md`, `configuration.md`, `context-format.md`, `supported-languages.md`) and `README.md` with copy-pasteable quick-start workflows.
4. Validate wheel and sdist builds via `poetry build`, test installation in a clean, network-disabled environment, and verify `.github/workflows/release.yml`.

#### Mandatory Phase 12 Quality Gates & Tests
- **Pytest (`tests/benchmarks/`, `tests/integration/test_security_fuzz.py`, full suite):**
  - Run full test suite across Python 3.11, 3.12, and 3.13 on Linux, macOS, and Windows.
  - Assert performance benchmarks meet latency and memory budgets.
  - Run `hypothesis` property-based fuzzing tests on `boundaries.py`, `tokenizer.py`, and `ids.py` with zero failures.
  - Build wheel (`poetry build`) -> install wheel into a fresh `venv` -> run `ctxa init`, `ctxa update`, `ctxa note`, `ctxa handoff`, `ctxa verify`, `ctxa diff`, `ctxa context`, and `ctxa compact` against a sample project.
- **Ruff & Mypy:**
  - `poetry run poetry check --lock` -> 0 errors.
  - `poetry run ruff check .` -> 0 errors.
  - `poetry run ruff format --check .` -> 0 diffs.
  - `poetry run mypy src tests --strict` -> 0 errors.
  - `poetry run pytest --cov=context_archive --cov-fail-under=90` -> >= 90% branch/line coverage.

#### Deliverables
- Benchmark report, security fuzz suite, complete user & architecture documentation, verified PyPI distribution artifacts (`sdist` + `wheel`), and `v1.0.0` GitHub release.

#### Exit Criteria
- All release checklist items in `SRS.md` Section 13 pass, all 5 automated quality gates pass across the full OS/Python matrix, and `context-archive` v1.0.0 is ready for public release.

---

## 5. Summary of Phase Exit Gate Matrix

Every phase must pass its dedicated test suite plus all prior suites before advancing:

| Phase | Core Deliverable | Required `pytest` Suites | `ruff check` & `ruff format --check` | `mypy src tests --strict` | Coverage Gate |
| :---: | :--- | :--- | :---: | :---: | :---: |
| **0** | GitHub Repo, Poetry, Schemas, Fixtures | `test_bootstrap.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **1** | CLI Shell, Config, Lock, Atomic Writes | `+ test_config.py`, `test_lock.py`, `test_cli_shell.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **2** | Safe Scanner, Secret Filter, Git State | `+ test_scanner.py`, `test_git_state.py`, `test_safe_scan.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **3** | Canonical Graph, Provenance, Python AST | `+ test_model.py`, `test_python_ast.py`, `test_graph_determinism.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **4** | Base Snapshot, Manifest, `ctxa handoff` | `+ test_markdown_renderer.py`, `test_handoff_golden.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **5** | Durable Notes, Sentinel Guard, `ctxa verify` | `+ test_notes.py`, `test_verifier.py`, `test_notes_and_verify.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **6** | Change Detector & JSONL Journal (`L1`) | `+ test_detector.py`, `test_journal.py`, `test_incremental_update_l1.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **7** | Partial Graph Update (`L2/L3`) & `ctxa diff` | `+ test_invalidator.py`, `test_differ.py`, `test_incremental_equivalence.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **8** | Compaction, Assembler & Cache (`ctxa compact`) | `+ test_assembler.py`, `test_compactor.py`, `test_snapshot_lifecycle.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **9** | Task Compiler & Token Budgets (`ctxa context`) | `+ test_tokenizer.py`, `test_compiler.py`, `test_task_context.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **10** | FastAPI, Pydantic, SQLAlchemy & TS Adapters | `+ test_fastapi_adapter.py`, `test_typescript_adapter.py`, `test_cross_stack_contracts.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **11** | Branch Reconciliation & Read-Only MCP (`ctxa mcp`) | `+ test_branch_reconciliation.py`, `test_mcp_server.py`, `test_team_handoff.py` | Required (0 issues) | Required (0 issues) | `>= 90%` |
| **12** | Benchmarks, Fuzzing, Docs & v1.0.0 Release | `+ bench_performance.py`, `test_security_fuzz.py`, Clean Wheel Smoke Test | Required (0 issues) | Required (0 issues) | `>= 90%` |