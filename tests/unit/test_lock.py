"""Unit tests for atomic file writes and .context/.lock concurrency management."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from context_archive.exceptions import CtxaError, ExitCode, LockError
from context_archive.lock import ContextLock, _is_pid_alive, atomic_write_text

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_atomic_write_text_preserves_existing_file_on_mid_write_failure(tmp_path: Path) -> None:
    """Verify atomic_write_text leaves destination intact if an exception occurs before replace."""
    target = tmp_path / "PROJECT_CONTEXT.md"
    original_content = "# Original Context\nDo not corrupt me.\n"
    atomic_write_text(target, original_content)
    assert target.read_text(encoding="utf-8") == original_content

    def _inject_failure(_tmp_file: Path) -> None:
        raise RuntimeError("Simulated mid-write crash")

    with pytest.raises(CtxaError) as exc_info:
        atomic_write_text(target, "# New Interrupted Content", before_replace_hook=_inject_failure)

    assert exc_info.value.exit_code == ExitCode.INTERNAL_ERROR
    # Original file must be 100% intact and no leftover .tmp files should remain
    assert target.read_text(encoding="utf-8") == original_content
    leftover_tmps = list(tmp_path.glob("*.tmp"))
    assert leftover_tmps == []


@pytest.mark.unit
def test_context_lock_blocks_concurrent_acquisition(tmp_path: Path) -> None:
    """Verify ContextLock prevents re-acquisition while held by an active PID."""
    context_dir = tmp_path / ".context"
    with ContextLock(context_dir) as meta:
        assert meta.pid == os.getpid()
        assert (context_dir / ".lock").is_file()

        second_lock = ContextLock(context_dir)
        with pytest.raises(LockError) as exc_info:
            second_lock.acquire()
        assert exc_info.value.exit_code == ExitCode.INTEGRITY_ERROR

    assert not (context_dir / ".lock").exists()


@pytest.mark.unit
def test_context_lock_recovers_from_dead_pid_and_corrupt_lock(tmp_path: Path) -> None:
    """Verify ContextLock recovers automatically when lock file has a dead PID or corrupt JSON."""
    context_dir = tmp_path / ".context"
    context_dir.mkdir(parents=True)
    lock_file = context_dir / ".lock"

    # 1. Dead PID lock recovery
    lock_file.write_text(
        json.dumps({"pid": 999_999_999, "acquired_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    with ContextLock(context_dir) as meta:
        assert meta.pid == os.getpid()
    assert not lock_file.exists()

    # 2. Corrupt lock file recovery
    lock_file.write_text("{corrupt-json", encoding="utf-8")
    with ContextLock(context_dir) as meta2:
        assert meta2.pid == os.getpid()
    assert not lock_file.exists()


@pytest.mark.unit
def test_is_pid_alive_checks() -> None:
    """Verify _is_pid_alive handles current PID, negative PIDs, and non-existent PIDs."""
    assert _is_pid_alive(os.getpid()) is True
    assert _is_pid_alive(0) is False
    assert _is_pid_alive(-5) is False
    assert _is_pid_alive(999_999_999) is False
