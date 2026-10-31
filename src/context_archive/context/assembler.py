"""Effective context assembler combining Latest Snapshot + Unincorporated Journal + Notes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from context_archive.exceptions import IntegrityError
from context_archive.model.graph import CanonicalGraph
from context_archive.model.manifest import Manifest, load_manifest
from context_archive.renderers.markdown import DEFAULT_MANUAL_NOTES_BLOCK
from context_archive.state.journal import JournalRecord, read_all_journal_records
from context_archive.state.snapshot import Snapshot, load_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.config import CtxaConfig


@dataclass(frozen=True)
class EffectiveContext:
    """Authoritative current repository state assembled from snapshot, journal, and notes."""

    manifest: Manifest
    snapshot: Snapshot
    graph: CanonicalGraph
    all_journal_records: tuple[JournalRecord, ...]
    unincorporated_records: tuple[JournalRecord, ...]
    manual_notes: str
    estimated_journal_tokens: int
    compaction_recommended: bool
    compaction_reason: str | None


def validate_journal_lineage(records: list[JournalRecord]) -> None:
    """Verify unbroken `parent_change_id` chain and monotonic ordering across journal records."""
    expected_parent: str | None = None
    seen_ids: set[str] = set()

    for idx, rec in enumerate(records):
        if rec.change_id in seen_ids:
            raise IntegrityError(f"Duplicate journal change_id detected: '{rec.change_id}'.")
        if idx == 0:
            if rec.parent_change_id is not None:
                raise IntegrityError(
                    f"First journal record '{rec.change_id}' has unexpected "
                    f"parent_change_id '{rec.parent_change_id}'. Run `ctxa rebuild`."
                )
        elif rec.parent_change_id != expected_parent:
            raise IntegrityError(
                f"Broken journal lineage at '{rec.change_id}': expected parent "
                f"'{expected_parent}', found '{rec.parent_change_id}'. Run `ctxa rebuild`."
            )
        seen_ids.add(rec.change_id)
        expected_parent = rec.change_id


def filter_unincorporated_records(
    records: list[JournalRecord],
    incorporated_cursor: str | None,
) -> list[JournalRecord]:
    """Filter for active, non-superseded journal records after `incorporated_cursor`."""
    validate_journal_lineage(records)

    superseded_ids: set[str] = set()
    for rec in records:
        superseded_ids.update(rec.supersedes)

    result: list[JournalRecord] = []
    for rec in records:
        if rec.record_status != "active" or rec.change_id in superseded_ids:
            continue
        if incorporated_cursor is not None and rec.change_id <= incorporated_cursor:
            continue
        result.append(rec)

    return result


def assemble_effective_context(
    repo_root: Path,
    config: CtxaConfig,
) -> EffectiveContext:
    """Assemble EffectiveContext from manifest.json, latest snapshot, journal, and notes."""
    context_dir = repo_root / ".context"
    manifest = load_manifest(context_dir)
    latest_snap_id = manifest.state_cursors.latest_snapshot_id
    snapshot = load_snapshot(context_dir, latest_snap_id)

    graph_path = context_dir / "graph.json"
    if graph_path.is_file():
        try:
            raw_graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph = CanonicalGraph.model_validate(raw_graph)
        except Exception as exc:
            raise IntegrityError(f"Corrupt .context/graph.json: {exc}") from exc
    else:
        graph = snapshot.graph

    all_records = read_all_journal_records(context_dir)
    inc_cursor = manifest.state_cursors.snapshot_incorporated_journal_cursor

    # Verify that if inc_cursor is set, it exists in the journal history
    if inc_cursor is not None and all_records:
        known_ids = {r.change_id for r in all_records}
        if inc_cursor not in known_ids:
            raise IntegrityError(
                f"Snapshot incorporated cursor '{inc_cursor}' is missing from journal history. "
                "Run `ctxa rebuild`."
            )

    unincorporated = filter_unincorporated_records(all_records, inc_cursor)

    notes_path = context_dir / "notes.md"
    manual_notes = (
        notes_path.read_text(encoding="utf-8", errors="replace").strip()
        if notes_path.is_file()
        else DEFAULT_MANUAL_NOTES_BLOCK
    )

    journal_chars = sum(len(r.to_jsonl_line()) for r in unincorporated)
    estimated_tokens = int(journal_chars / 3.5)

    compaction_recommended = False
    compaction_reason: str | None = None
    if len(unincorporated) > config.journal.auto_compact_record_threshold:
        compaction_recommended = True
        compaction_reason = (
            f"Unincorporated journal records ({len(unincorporated)}) exceed threshold "
            f"({config.journal.auto_compact_record_threshold}). Run `ctxa compact`."
        )
    elif estimated_tokens > config.journal.auto_compact_token_threshold:
        compaction_recommended = True
        compaction_reason = (
            f"Estimated unincorporated journal tokens ({estimated_tokens}) exceed threshold "
            f"({config.journal.auto_compact_token_threshold}). Run `ctxa compact`."
        )

    return EffectiveContext(
        manifest=manifest,
        snapshot=snapshot,
        graph=graph,
        all_journal_records=tuple(all_records),
        unincorporated_records=tuple(unincorporated),
        manual_notes=manual_notes or DEFAULT_MANUAL_NOTES_BLOCK,
        estimated_journal_tokens=estimated_tokens,
        compaction_recommended=compaction_recommended,
        compaction_reason=compaction_reason,
    )
