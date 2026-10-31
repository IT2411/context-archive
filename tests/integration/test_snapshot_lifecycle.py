"""End-to-end lifecycle test: 5 updates -> compact -> 2 updates -> handoff (No-Double-Replay)."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app
from context_archive.exceptions import ExitCode
from context_archive.state.journal import read_all_journal_records

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.integration
def test_snapshot_compaction_prevents_double_replay_in_handoff(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Perform 5 updates, compact to snapshot-0002, perform 2 updates, and verify handoff."""
    repo = tmp_path / "lifecycle_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0

    calc = repo / "src" / "sample_lib" / "calculator.py"
    base_src = calc.read_text(encoding="utf-8")

    # 1. Perform 5 incremental updates (CA-19700101-0001 through CA-19700101-0005)
    for i in range(1, 6):
        calc.write_text(
            base_src + f"\nPRE_COMPACT_CONST_{i} = {i}\n",
            encoding="utf-8",
        )
        res = runner.invoke(
            app,
            ["update", str(repo), "-m", f"Pre-compaction step {i}", "--deterministic"],
        )
        assert res.exit_code == int(ExitCode.SUCCESS)

    # 2. Compact into snapshot-0002.json
    compact_res = runner.invoke(app, ["compact", str(repo), "--deterministic", "--json"])
    assert compact_res.exit_code == int(ExitCode.SUCCESS)
    assert (repo / ".context" / "snapshots" / "snapshot-0002.json").is_file()

    # 3. Perform 2 post-compaction updates (CA-19700101-0006 and CA-19700101-0007)
    for i in range(6, 8):
        calc.write_text(
            base_src + f"\nPRE_COMPACT_CONST_5 = 5\nPOST_COMPACT_CONST_{i} = {i}\n",
            encoding="utf-8",
        )
        res = runner.invoke(
            app,
            ["update", str(repo), "-m", f"Post-compaction step {i}", "--deterministic"],
        )
        assert res.exit_code == int(ExitCode.SUCCESS)

    # Corrupt cache.sqlite before handoff to verify end-to-end cache self-healing
    (repo / ".context" / "cache.sqlite").write_bytes(b"CORRUPT_BYTES\x00")

    # 4. Run `ctxa handoff`
    handoff_res = runner.invoke(app, ["handoff", str(repo), "--deterministic"])
    assert handoff_res.exit_code == int(ExitCode.SUCCESS)

    md_text = (repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")

    # Section 8 (Recent Incremental Changes) must list ONLY the 2 post-compaction changes (6 & 7)
    # and NOT replay changes 1-5
    for old_idx in range(1, 6):
        assert f"Pre-compaction step {old_idx}" not in md_text
    assert "CA-19700101-0006" in md_text
    assert "Post-compaction step 6" in md_text
    assert "CA-19700101-0007" in md_text
    assert "Post-compaction step 7" in md_text

    # Meanwhile, the structural Section 5 (Key Symbols) reflects both pre- and post-compaction code
    assert "PRE_COMPACT_CONST_5" in md_text
    assert "POST_COMPACT_CONST_7" in md_text

    # And all 7 historical records remain preserved in .context/journal/*.jsonl
    all_records = read_all_journal_records(repo / ".context")
    assert len(all_records) == 7
