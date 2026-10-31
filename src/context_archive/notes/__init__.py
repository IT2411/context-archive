"""notes subsystem for context-archive."""

from __future__ import annotations

from context_archive.notes.boundaries import (
    replace_manual_block_in_markdown,
    validate_and_extract_manual_block,
)
from context_archive.notes.manager import (
    NoteRecord,
    NoteType,
    append_human_note,
    ensure_canonical_notes_sections,
    sync_manual_notes,
)

__all__ = [
    "NoteRecord",
    "NoteType",
    "append_human_note",
    "ensure_canonical_notes_sections",
    "replace_manual_block_in_markdown",
    "sync_manual_notes",
    "validate_and_extract_manual_block",
]
