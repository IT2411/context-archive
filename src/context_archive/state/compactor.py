"""Snapshot compaction engine (`ctxa compact`) implementing SRS FR-11."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from context_archive.lock import ContextLock, atomic_write_text
from context_archive.model.graph import CanonicalGraph
from context_archive.model.manifest import (
    DETERMINISTIC_TIMESTAMP,
    Manifest,
    StateCursors,
    write_manifest,
)
from context_archive.state.snapshot import Snapshot, format_snapshot_id, write_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.config import CtxaConfig


@dataclass(frozen=True)
class CompactionResult:
    """Result of running `ctxa compact`."""

    previous_snapshot_id: str
    new_snapshot_id: str
    incorporated_journal_cursor: str | None
    compacted_record_count: int
    snapshot: Snapshot
    manifest: Manifest


def _next_snapshot_id(current_snapshot_id: str) -> str:
    """Increment `snapshot-NNNN` to `snapshot-(N+1)`."""
    parts = current_snapshot_id.split("-")
    if len(parts) == 2 and parts[1].isdigit():
        return format_snapshot_id(int(parts[1]) + 1)
    return "snapshot-0002"  # pragma: no cover


def compact_snapshot(
    repo_root: Path,
    config: CtxaConfig,
    *,
    deterministic: bool = False,
) -> CompactionResult:
    """Roll unincorporated journal entries into a new immutable snapshot checkpoint.

    Leaves all `.context/journal/*.jsonl` files intact on disk for historical auditing.
    """
    from context_archive.context.assembler import assemble_effective_context

    context_dir = repo_root / ".context"
    with ContextLock(context_dir):
        effective = assemble_effective_context(repo_root, config)
        prev_snap = effective.snapshot
        manifest = effective.manifest
        unincorporated = effective.unincorporated_records

        if not unincorporated:
            return CompactionResult(
                previous_snapshot_id=prev_snap.snapshot_id,
                new_snapshot_id=prev_snap.snapshot_id,
                incorporated_journal_cursor=prev_snap.incorporated_journal_cursor,
                compacted_record_count=0,
                snapshot=prev_snap,
                manifest=manifest,
            )

        new_snap_id = _next_snapshot_id(prev_snap.snapshot_id)
        head_cursor = unincorporated[-1].change_id
        merged_change_ids = tuple(
            list(prev_snap.incorporated_change_ids) + [r.change_id for r in unincorporated]
        )

        timestamp = (
            DETERMINISTIC_TIMESTAMP
            if deterministic
            else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        compacted_graph = CanonicalGraph.build(
            repository_id=manifest.repository_id,
            base_snapshot_id=new_snap_id,
            applied_journal_cursor=head_cursor,
            nodes=effective.graph.nodes,
            edges=effective.graph.edges,
            diagnostics=effective.graph.diagnostics,
        )

        new_snapshot = Snapshot(
            snapshot_id=new_snap_id,
            parent_snapshot_id=prev_snap.snapshot_id,
            repository_id=manifest.repository_id,
            created_at=timestamp,
            config_fingerprint=manifest.config_fingerprint,
            git_state=manifest.git_state,
            incorporated_journal_cursor=head_cursor,
            incorporated_change_ids=merged_change_ids,
            file_fingerprints=manifest.file_fingerprints,
            graph=compacted_graph,
        )
        write_snapshot(context_dir, new_snapshot)
        atomic_write_text(context_dir / "graph.json", compacted_graph.to_deterministic_json())

        updated_manifest = Manifest(
            schema_version=manifest.schema_version,
            tool_version=manifest.tool_version,
            repository_id=manifest.repository_id,
            generated_at=timestamp,
            config_fingerprint=manifest.config_fingerprint,
            git_state=manifest.git_state,
            state_cursors=StateCursors(
                latest_snapshot_id=new_snap_id,
                snapshot_incorporated_journal_cursor=head_cursor,
                head_journal_cursor=head_cursor,
                unincorporated_record_count=0,
                notes_fingerprint=manifest.state_cursors.notes_fingerprint,
            ),
            scan_summary=manifest.scan_summary,
            file_fingerprints=manifest.file_fingerprints,
        )
        write_manifest(context_dir, updated_manifest)

    return CompactionResult(
        previous_snapshot_id=prev_snap.snapshot_id,
        new_snapshot_id=new_snap_id,
        incorporated_journal_cursor=head_cursor,
        compacted_record_count=len(unincorporated),
        snapshot=new_snapshot,
        manifest=updated_manifest,
    )
