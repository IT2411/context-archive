# ADR 003: Dual-Synced Human Notes and Protected Sentinel Boundaries

## Status
Accepted

## Context
Developers record architectural decisions, constraints, and next steps either via `ctxa note` or by directly editing `PROJECT_CONTEXT.md`. Automated regenerations must never overwrite human notes.

## Decision
1. Durable notes live in `.context/notes.md`.
2. `PROJECT_CONTEXT.md` wraps Sections 11-13 in `<!-- CTXA:MANUAL:START ... -->` and `<!-- CTXA:MANUAL:END -->` sentinel comments.
3. Before overwriting `PROJECT_CONTEXT.md`, `ctxa` validates the sentinel markers, syncs any inline manual edits back to `.context/notes.md`, and aborts with a `.bak` backup and exit code `4` if markers are corrupted.

## Consequences
Zero human-authored knowledge can be lost during `ctxa handoff`, `ctxa update`, or `ctxa rebuild`.
