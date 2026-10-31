"""Unit tests for the freshness verification engine (`ctxa verify`)."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff
from context_archive.config import load_config
from context_archive.context.verifier import verify_repository_freshness
from context_archive.exceptions import ExitCode

if TYPE_CHECKING:
    from pathlib import Path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_freshness_detection_matrix(fixtures_dir: Path, tmp_path: Path) -> None:
    """Verify CURRENT, file edits, additions, deletions, config edits, and branch switch."""
    repo = tmp_path / "verify_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "dev@example.com")
    _git(repo, "config", "user.name", "Dev")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Initial commit")

    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True, write_default_ctxa_toml=True)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Add context artifacts")
    execute_full_handoff(repo, cfg, deterministic=True)

    # 1. Immediately after handoff -> CURRENT (Exit 0)
    rep_clean = verify_repository_freshness(repo, cfg)
    assert rep_clean.status == "CURRENT"
    assert rep_clean.exit_code == int(ExitCode.SUCCESS)
    assert rep_clean.reasons == ()

    # 2. Modify 1 byte in a tracked .py file -> STALE_UNRECORDED (Exit 2)
    calc_path = repo / "src" / "sample_lib" / "calculator.py"
    original_calc = calc_path.read_text(encoding="utf-8")
    calc_path.write_text(original_calc + "\n# 1-byte comment edit\n", encoding="utf-8")

    rep_mod = verify_repository_freshness(repo, cfg)
    assert rep_mod.status == "STALE_UNRECORDED"
    assert rep_mod.exit_code == int(ExitCode.STALE_OR_DIFF)
    assert "src/sample_lib/calculator.py" in rep_mod.modified_files

    # Restore modified file
    calc_path.write_text(original_calc, encoding="utf-8")
    assert verify_repository_freshness(repo, cfg).status == "CURRENT"

    # 3. Add a new .py file -> STALE_UNRECORDED (Exit 2)
    extra_file = repo / "src" / "sample_lib" / "extra.py"
    extra_file.write_text("EXTRA = True\n", encoding="utf-8")
    rep_add = verify_repository_freshness(repo, cfg)
    assert rep_add.status == "STALE_UNRECORDED"
    assert rep_add.exit_code == int(ExitCode.STALE_OR_DIFF)
    assert "src/sample_lib/extra.py" in rep_add.added_files
    extra_file.unlink()

    # 4. Delete a tracked file -> STALE_UNRECORDED (Exit 2)
    utils_path = repo / "src" / "sample_lib" / "utils.py"
    utils_backup = utils_path.read_text(encoding="utf-8")
    utils_path.unlink()
    rep_del = verify_repository_freshness(repo, cfg)
    assert rep_del.status == "STALE_UNRECORDED"
    assert "src/sample_lib/utils.py" in rep_del.deleted_files
    utils_path.write_text(utils_backup, encoding="utf-8")

    # 5. Modify .ctxa.toml configuration -> STALE_UNRECORDED (Exit 2)
    (repo / ".ctxa.toml").write_text(
        '[project]\nname = "changed-name"\n[scanner]\nmax_depth = 12\n',
        encoding="utf-8",
    )
    new_cfg = load_config(repo)
    rep_cfg = verify_repository_freshness(repo, new_cfg)
    assert rep_cfg.status == "STALE_UNRECORDED"
    assert rep_cfg.exit_code == int(ExitCode.STALE_OR_DIFF)
    assert any("Configuration fingerprint changed" in r for r in rep_cfg.reasons)

    # Refresh handoff with new config, then switch Git branch -> STALE_UNRECORDED (Exit 2)
    _git(repo, "add", ".ctxa.toml")
    _git(repo, "commit", "-m", "Update config")
    execute_full_handoff(repo, new_cfg, deterministic=True)
    assert verify_repository_freshness(repo, new_cfg).status == "CURRENT"

    _git(repo, "checkout", "-b", "feat/new-branch")
    rep_branch = verify_repository_freshness(repo, new_cfg)
    assert rep_branch.status == "STALE_UNRECORDED"
    assert rep_branch.exit_code == int(ExitCode.STALE_OR_DIFF)
    assert any("Git branch changed" in r for r in rep_branch.reasons)


@pytest.mark.unit
def test_verifier_corrupt_or_missing_artifacts(tmp_path: Path) -> None:
    """Verify missing manifest or missing PROJECT_CONTEXT.md returns CORRUPT_OR_MISSING (Exit 4)."""
    cfg = load_config(tmp_path)
    rep_empty = verify_repository_freshness(tmp_path, cfg)
    assert rep_empty.status == "CORRUPT_OR_MISSING"
    assert rep_empty.exit_code == int(ExitCode.INTEGRITY_ERROR)
    assert "CORRUPT_OR_MISSING" in rep_empty.to_deterministic_json()
