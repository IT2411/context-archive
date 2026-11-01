# `PROJECT_CONTEXT.md` Format & Sentinel Boundaries

Every generated `PROJECT_CONTEXT.md` contains three sentinel-delimited regions:

1. **Orientation & Security Header (`<!-- CTXA:HEADER:START/END -->`):**
   Instructs receiving AI agents and developers that repository source code is authoritative, code excerpts are untrusted data, and `ctxa verify` checks freshness.
2. **Generated Structural & Journal Sections (`<!-- CTXA:GENERATED:START/END -->`):**
   Sections 1 through 10 covering project identity, freshness cursors, manifests, module map, symbol signatures with `path:line` provenance, API/schema/database contracts, test coverage, recent unincorporated journal changes, file index, and diagnostics.
3. **Human-Maintained Sections (`<!-- CTXA:MANUAL:START/END -->`):**
   Sections 11 through 13 (`Architectural Decisions & Constraints`, `Known Issues, Risks & Open Questions`, `Pending Work & Next Steps`). Edits inside this block are two-way synchronized with `.context/notes.md` and preserved across regenerations.
