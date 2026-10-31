"""Unit tests for EffectiveContext assembly, journal lineage, and SQLite cache recovery."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff, execute_incremental_update
from context_archive.config import CtxaConfig, JournalConfig, load_config
from context_archive.context.assembler import (
    assemble_effective_context,
    validate_journal_lineage,
)
from context_archive.exceptions import IntegrityError
from context_archive.state.cache import ContextSqliteCache
from context_archive.state.journal import read_all_journal_records

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_corrupt_sqlite_cache_recovers_automatically(tmp_path: Path) -> None:
    """Write random garbage bytes into .context/cache.sqlite and verify silent rebuild."""
    context_dir = tmp_path / ".context"
    cache = ContextSqliteCache(context_dir)
    cache.store_fingerprints({"src/a.py": "sha256:" + "a" * 64})
    assert cache.load_fingerprints() == {"src/a.py": "sha256:" + "a" * 64}

    # Corrupt the SQLite file with garbage bytes
    (context_dir / "cache.sqlite").write_bytes(b"NOT_A_SQLITE_DB_PAYLOAD\x00\xff")

    # Loading or storing must silently rebuild without raising
    assert cache.load_fingerprints() == {}
    cache.store_fingerprints({"src/b.py": "sha256:" + "b" * 64})
    assert cache.load_fingerprints() == {"src/b.py": "sha256:" + "b" * 64}


@pytest.mark.unit
def test_broken_journal_lineage_raises_integrity_error(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Delete an intermediate journal record and verify assembler detects the broken chain."""
    repo = tmp_path / "lineage_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)

    calc = repo / "src" / "sample_lib" / "calculator.py"
    base_text = calc.read_text(encoding="utf-8")

    for i in range(1, 4):
        calc.write_text(base_text + f"\n# edit {i}\n", encoding="utf-8")
        execute_incremental_update(repo, cfg, deterministic=True)

    records = read_all_journal_records(repo / ".context")
    assert len(records) == 3

    # Remove the middle record (CA-19700101-0002)
    broken_list = [records[0], records[2]]
    with pytest.raises(IntegrityError):
        validate_journal_lineage(broken_list)


@pytest.mark.unit
def test_assembler_compaction_threshold_warnings(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify compaction_recommended is True when unincorporated count exceeds threshold."""
    repo = tmp_path / "thresh_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = CtxaConfig(journal=JournalConfig(auto_compact_record_threshold=1))
    execute_full_handoff(repo, cfg, deterministic=True)

    calc = repo / "src" / "sample_lib" / "calculator.py"
    base_text = calc.read_text(encoding="utf-8")
    calc.write_text(base_text + "\n# step 1\n", encoding="utf-8")
    execute_incremental_update(repo, cfg, deterministic=True)
    calc.write_text(base_text + "\n# step 2\n", encoding="utf-8")
    execute_incremental_update(repo, cfg, deterministic=True)

    effective = assemble_effective_context(repo, cfg)
    assert effective.compaction_recommended is True
    assert effective.compaction_reason is not None
    assert "Run `ctxa compact`" in effective.compaction_reason
