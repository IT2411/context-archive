"""Unit tests for partial graph invalidation and L2 -> L3 escalation rules."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff
from context_archive.config import load_config
from context_archive.scanner.walker import scan_repository
from context_archive.state.invalidator import (
    compute_invalidated_paths,
    refresh_graph_incrementally,
)
from context_archive.state.journal import JournalFileChange

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_compute_invalidated_paths_propagates_to_reverse_dependents(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify modifying utils.py invalidates calculator.py and test_calculator.py."""
    repo = tmp_path / "inv_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    artifacts = execute_full_handoff(repo, cfg, deterministic=True)

    changes = [
        JournalFileChange(
            path="src/sample_lib/utils.py",
            operation="modified",
            old_sha256="sha256:" + "0" * 64,
            new_sha256="sha256:" + "1" * 64,
            modified_symbols=("sym:py:src/sample_lib/utils.py:round_currency",),
        )
    ]
    invalidated, reason = compute_invalidated_paths(artifacts.graph, changes)
    assert reason is None
    assert "src/sample_lib/utils.py" in invalidated
    assert "src/sample_lib/calculator.py" in invalidated
    assert "tests/test_calculator.py" in invalidated


@pytest.mark.unit
def test_invalidator_escalates_on_init_py_or_deletion(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify editing __init__.py or deleting a file escalates L2 to L3 cleanly."""
    repo = tmp_path / "esc_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    artifacts = execute_full_handoff(repo, cfg, deterministic=True)
    scan_rep = scan_repository(repo, cfg)

    init_change = [
        JournalFileChange(
            path="src/sample_lib/__init__.py",
            operation="modified",
            old_sha256="sha256:" + "0" * 64,
            new_sha256="sha256:" + "1" * 64,
        )
    ]
    res_init = refresh_graph_incrementally(
        repo_root=repo,
        previous_graph=artifacts.graph,
        live_files=scan_rep.files,
        file_changes=init_change,
        requested_level="L2",
        base_snapshot_id="snapshot-0001",
        applied_journal_cursor="CA-19700101-0001",
    )
    assert res_init.escalated_to_l3 is True
    assert res_init.effective_level == "L3"
