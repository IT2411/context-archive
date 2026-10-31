"""state subsystem for context-archive."""

from __future__ import annotations

from context_archive.state.cache import ContextSqliteCache
from context_archive.state.compactor import CompactionResult, compact_snapshot
from context_archive.state.detector import (
    ChangeDetectionResult,
    detect_repository_changes,
)
from context_archive.state.invalidator import (
    GraphInvalidationResult,
    compute_invalidated_paths,
    refresh_graph_incrementally,
)
from context_archive.state.journal import (
    ChangeCategory,
    JournalFileChange,
    JournalImpactItem,
    JournalIntent,
    JournalRecord,
    JournalSourceState,
    UpdateLevel,
    append_journal_record,
    compute_tree_fingerprint,
    generate_next_change_id,
    read_all_journal_records,
)
from context_archive.state.snapshot import (
    Snapshot,
    format_snapshot_id,
    load_snapshot,
    write_snapshot,
)

__all__ = [
    "ChangeCategory",
    "ChangeDetectionResult",
    "CompactionResult",
    "ContextSqliteCache",
    "GraphInvalidationResult",
    "JournalFileChange",
    "JournalImpactItem",
    "JournalIntent",
    "JournalRecord",
    "JournalSourceState",
    "Snapshot",
    "UpdateLevel",
    "append_journal_record",
    "compact_snapshot",
    "compute_invalidated_paths",
    "compute_tree_fingerprint",
    "detect_repository_changes",
    "format_snapshot_id",
    "generate_next_change_id",
    "load_snapshot",
    "read_all_journal_records",
    "refresh_graph_incrementally",
    "write_snapshot",
]
