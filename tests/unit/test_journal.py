"""Unit tests for the append-only JSONL journal engine and monotonic cursor generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from context_archive.exceptions import IntegrityError
from context_archive.state.journal import (
    JournalFileChange,
    JournalIntent,
    JournalRecord,
    JournalSourceState,
    append_journal_record,
    compute_tree_fingerprint,
    generate_next_change_id,
    read_all_journal_records,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_journal_append_read_and_schema_compliance(
    tmp_path: Path,
    repo_root: Path,
) -> None:
    """Verify JSONL records are appended, read back, and match journal-record.schema.json."""
    context_dir = tmp_path / ".context"
    tree_fp = compute_tree_fingerprint({"src/mod.py": "sha256:" + "a" * 64})

    cid_1, rec_at_1, ym_1 = generate_next_change_id([], deterministic=True)
    assert cid_1 == "CA-19700101-0001"
    rec_1 = JournalRecord(
        change_id=cid_1,
        parent_change_id=None,
        recorded_at=rec_at_1,
        repository_id="repo:sha256:" + "0" * 32,
        base_snapshot_id="snapshot-0001",
        update_level="L1",
        source_state=JournalSourceState(
            commit_sha="1" * 40,
            branch="main",
            is_dirty=True,
            tree_fingerprint=tree_fp,
        ),
        category="unknown",
        intent=JournalIntent(
            summary="Adjust internal rounding step",
            origin="developer_confirmed",
            confidence="high",
        ),
        file_changes=(
            JournalFileChange(
                path="src/mod.py",
                operation="modified",
                old_sha256="sha256:" + "b" * 64,
                new_sha256="sha256:" + "a" * 64,
                modified_symbols=("sym:py:src/mod.py:calc",),
            ),
        ),
    )
    jsonl_path = append_journal_record(context_dir, rec_1, partition_ym=ym_1)
    assert jsonl_path.is_file()

    cid_2, rec_at_2, ym_2 = generate_next_change_id([rec_1], deterministic=True)
    assert cid_2 == "CA-19700101-0002"
    rec_2 = JournalRecord(
        change_id=cid_2,
        parent_change_id=cid_1,
        recorded_at=rec_at_2,
        repository_id="repo:sha256:" + "0" * 32,
        base_snapshot_id="snapshot-0001",
        update_level="L2",
        source_state=JournalSourceState(
            commit_sha="1" * 40,
            branch="main",
            is_dirty=True,
            tree_fingerprint=tree_fp,
        ),
        category="contract_change",
        intent=JournalIntent(
            summary="Update signature",
            origin="deterministic_classifier",
            confidence="high",
        ),
    )
    append_journal_record(context_dir, rec_2, partition_ym=ym_2)

    loaded = read_all_journal_records(context_dir)
    assert len(loaded) == 2
    assert loaded[0].change_id == "CA-19700101-0001"
    assert loaded[1].change_id == "CA-19700101-0002"
    assert loaded[1].parent_change_id == "CA-19700101-0001"

    # Verify all required keys from docs/schemas/journal-record.schema.json exist on every line
    schema_data = json.loads(
        (repo_root / "docs" / "schemas" / "journal-record.schema.json").read_text(encoding="utf-8")
    )
    required_keys = set(schema_data["required"])
    for raw_line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line_obj = json.loads(raw_line)
        assert required_keys.issubset(set(line_obj.keys()))


@pytest.mark.unit
def test_corrupt_journal_line_raises_integrity_error(tmp_path: Path) -> None:
    """Verify malformed JSONL lines raise IntegrityError (Exit 4)."""
    journal_dir = tmp_path / ".context" / "journal"
    journal_dir.mkdir(parents=True)
    (journal_dir / "2026-10.jsonl").write_text("{corrupt-jsonl-line\n", encoding="utf-8")

    with pytest.raises(IntegrityError):
        read_all_journal_records(tmp_path / ".context")
