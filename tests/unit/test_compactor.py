"""Unit tests for the snapshot compaction engine (`ctxa compact`)."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff, execute_incremental_update
from context_archive.config import load_config
from context_archive.state.compactor import compact_snapshot
from context_archive.state.journal import read_all_journal_records

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_compactor_creates_next_snapshot_and_preserves_journal(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify compact_snapshot creates snapshot-0002, advances cursor, and keeps .jsonl intact."""
    repo = tmp_path / "compact_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)

    # Compacting when 0 unincorporated records exist is a clean no-op
    noop_res = compact_snapshot(repo, cfg, deterministic=True)
    assert noop_res.compacted_record_count == 0
    assert noop_res.new_snapshot_id == "snapshot-0001"

    calc = repo / "src" / "sample_lib" / "calculator.py"
    base_text = calc.read_text(encoding="utf-8")
    calc.write_text(base_text + "\n# edit 1\n", encoding="utf-8")
    execute_incremental_update(repo, cfg, deterministic=True)
    calc.write_text(base_text + "\n# edit 2\n", encoding="utf-8")
    execute_incremental_update(repo, cfg, deterministic=True)

    comp_res = compact_snapshot(repo, cfg, deterministic=True)
    assert comp_res.previous_snapshot_id == "snapshot-0001"
    assert comp_res.new_snapshot_id == "snapshot-0002"
    assert comp_res.compacted_record_count == 2
    assert comp_res.incorporated_journal_cursor == "CA-19700101-0002"
    assert comp_res.snapshot.parent_snapshot_id == "snapshot-0001"
    assert comp_res.manifest.state_cursors.unincorporated_record_count == 0

    # Historical journal records must remain intact on disk
    all_records = read_all_journal_records(repo / ".context")
    assert len(all_records) == 2
