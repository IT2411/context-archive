# ADR 001: Deterministic Canonical Node and Edge Identifiers

## Status
Accepted

## Context
`context-archive` must produce byte-for-byte identical graph representations across repeated runs on Linux, macOS, and Windows without relying on random UUIDs or memory addresses.

## Decision
All Node and Edge IDs are deterministically derived from normalized POSIX relative paths and qualified symbol names:
- Repository ID: `repo:sha256:<digest>`
- File ID: `file:<posix_path>`
- Symbol ID: `sym:<lang>:<posix_path>:<qualified_symbol_name>`
- Edge ID: `edge:<KIND>:<source_id>-><target_id>`

## Consequences
Nodes and edges can be sorted lexicographically by `id` upon serialization, guaranteeing 100% deterministic JSON output and reliable incremental diffing.
