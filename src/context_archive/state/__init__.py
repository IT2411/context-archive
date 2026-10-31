"""state subsystem for context-archive."""

from __future__ import annotations

from context_archive.state.detector import (
    ChangeDetectionResult,
    detect_repository_changes,
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
    "JournalFileChange",
    "JournalImpactItem",
    "JournalIntent",
    "JournalRecord",
    "JournalSourceState",
    "Snapshot",
    "UpdateLevel",
    "append_journal_record",
    "compute_tree_fingerprint",
    "detect_repository_changes",
    "format_snapshot_id",
    "generate_next_change_id",
    "load_snapshot",
    "read_all_journal_records",
    "write_snapshot",
]
