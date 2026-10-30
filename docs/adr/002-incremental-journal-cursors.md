# ADR 002: Append-Only Journal and Snapshot Compaction Cursors

## Status
Accepted

## Context
Regenerating a full repository graph after every minor edit is slow and loses the timeline of incremental developer intent. Conversely, replaying an unbounded log forever degrades assembly latency.

## Decision
1. Incremental updates append JSONL records to `.context/journal/YYYY-MM.jsonl` with monotonic `change_id`s (`CA-YYYYMMDD-NNNN`) and `parent_change_id` pointers.
2. Each snapshot (`snapshot-NNNN.json`) records `incorporated_journal_cursor` (the latest `change_id` folded into that checkpoint).
3. Effective context assembly reads only `Latest Snapshot + Journal Records where change_id > incorporated_journal_cursor`.

## Consequences
Historical journal files remain immutable on disk for auditability while `PROJECT_CONTEXT.md` stays compact and fast to assemble.
