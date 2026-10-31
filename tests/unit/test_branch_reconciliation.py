"""Unit tests for branch divergence detection, conflict marker guards, and note/journal unioning."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.context.reconciler import (
    check_for_git_conflict_markers,
    detect_journal_forks,
    merge_human_notes_blocks,
    reconcile_divergent_journal,
)
from context_archive.exceptions import IntegrityError
from context_archive.state.journal import (
    JournalFileChange,
    JournalIntent,
    JournalRecord,
    JournalSourceState,
)

if TYPE_CHECKING:
    from pathlib import Path


def _make_record(
    change_id: str, parent_id: str | None, summary: str, tree_char: str
) -> JournalRecord:
    return JournalRecord(
        change_id=change_id,
        parent_change_id=parent_id,
        recorded_at="1970-01-01T00:00:00Z",
        repository_id="repo:sha256:" + "0" * 32,
        base_snapshot_id="snapshot-0001",
        update_level="L1",
        source_state=JournalSourceState(
            commit_sha="1" * 40,
            branch="main",
            is_dirty=False,
            tree_fingerprint="sha256:" + tree_char * 64,
        ),
        category="unknown",
        intent=JournalIntent(
            summary=summary,
            origin="developer_confirmed",
            confidence="high",
        ),
        file_changes=(
            JournalFileChange(
                path="src/mod.py",
                operation="modified",
                old_sha256="sha256:" + "a" * 64,
                new_sha256="sha256:" + tree_char * 64,
            ),
        ),
    )


@pytest.mark.unit
def test_detect_and_reconcile_divergent_journal_forks(tmp_path: Path) -> None:
    """Verify two branch records sharing the same parent_change_id are detected and reconciled."""
    rec_root = _make_record("CA-19700101-0001", None, "Root change", "b")
    rec_branch_a = _make_record("CA-19700101-0002", "CA-19700101-0001", "Branch A edit", "c")
    rec_branch_b = _make_record("CA-19700101-0002", "CA-19700101-0001", "Branch B edit", "d")

    has_fork, fork_ids = detect_journal_forks([rec_root, rec_branch_a, rec_branch_b])
    assert has_fork is True
    assert "CA-19700101-0002" in fork_ids

    journal_dir = tmp_path / ".context" / "journal"
    journal_dir.mkdir(parents=True)
    jsonl_file = journal_dir / "1970-01.jsonl"
    jsonl_file.write_text(
        rec_root.to_jsonl_line() + rec_branch_a.to_jsonl_line() + rec_branch_b.to_jsonl_line(),
        encoding="utf-8",
    )

    reconciled = reconcile_divergent_journal(tmp_path / ".context")
    assert len(reconciled) == 3
    assert [r.change_id for r in reconciled] == [
        "CA-19700101-0001",
        "CA-19700101-0002",
        "CA-19700101-0003",
    ]
    assert reconciled[0].parent_change_id is None
    assert reconciled[1].parent_change_id == "CA-19700101-0001"
    assert reconciled[2].parent_change_id == "CA-19700101-0002"
    summaries = {r.intent.summary for r in reconciled}
    assert summaries == {"Root change", "Branch A edit", "Branch B edit"}


@pytest.mark.unit
def test_conflict_markers_and_merge_human_notes(tmp_path: Path) -> None:
    """Verify Git conflict markers raise IntegrityError and branch notes union cleanly."""
    journal_dir = tmp_path / ".context" / "journal"
    journal_dir.mkdir(parents=True)
    conflict_file = journal_dir / "2026-10.jsonl"
    conflict_file.write_text("<<<<<<< HEAD\n=======\n>>>>>>> branch-b\n", encoding="utf-8")

    assert check_for_git_conflict_markers(conflict_file) is True
    with pytest.raises(IntegrityError):
        reconcile_divergent_journal(tmp_path / ".context")

    notes_a = (
        "# 11. Architectural Decisions & Constraints (Human-Maintained)\n"
        "- **[DECISION]**: Developer A decision\n"
    )
    notes_b = (
        "# 11. Architectural Decisions & Constraints (Human-Maintained)\n"
        "- **[DECISION]**: Developer B decision\n"
    )
    merged = merge_human_notes_blocks(notes_a, notes_b)
    assert "Developer A decision" in merged
    assert "Developer B decision" in merged
