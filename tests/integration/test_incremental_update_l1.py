"""Integration tests for `ctxa update` idempotency, revert tracking, and developer intent."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app
from context_archive.exceptions import ExitCode
from context_archive.lock import atomic_write_text
from context_archive.state.journal import read_all_journal_records

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.integration
def test_incremental_update_idempotency_revert_and_intent(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify idempotency (3 runs -> 1 record), revert tracking, and developer intent."""
    repo = tmp_path / "inc_l1_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0

    calc_path = repo / "src" / "sample_lib" / "calculator.py"
    original_content = calc_path.read_text(encoding="utf-8")

    # Modify function body only (L1) using atomic_write_text to preserve LF on Windows
    modified_content = original_content.replace(
        "return round_currency(subtotal + tax)",
        "total = subtotal + tax\n    return round_currency(total)",
    )
    atomic_write_text(calc_path, modified_content)

    # Run `ctxa update` 3 consecutive times
    res_1 = runner.invoke(
        app,
        [
            "update",
            str(repo),
            "--message",
            "Introduce intermediate total variable",
            "--deterministic",
            "--json",
        ],
    )
    assert res_1.exit_code == int(ExitCode.SUCCESS)
    payload_1 = json.loads(res_1.stdout)
    assert payload_1["is_noop"] is False
    assert payload_1["level"] == "L1"
    assert payload_1["change_id"] == "CA-19700101-0001"

    for _ in range(2):
        res_noop = runner.invoke(app, ["update", str(repo), "--deterministic", "--json"])
        assert res_noop.exit_code == int(ExitCode.SUCCESS)
        assert json.loads(res_noop.stdout)["is_noop"] is True

    # Verify only 1 record was written to .jsonl and intent is developer_confirmed
    records = read_all_journal_records(repo / ".context")
    assert len(records) == 1
    assert records[0].intent.origin == "developer_confirmed"
    assert records[0].intent.confidence == "high"
    assert records[0].intent.summary == "Introduce intermediate total variable"

    # Verify STALE_JOURNALED when PROJECT_CONTEXT.md has not been re-rendered yet
    verify_stale = runner.invoke(app, ["verify", str(repo), "--json"])
    assert verify_stale.exit_code == int(ExitCode.STALE_OR_DIFF)
    assert json.loads(verify_stale.stdout)["status"] == "STALE_JOURNALED"

    # Revert the file to its original contents (preserving LF) and run `ctxa update`
    atomic_write_text(calc_path, original_content)
    res_revert = runner.invoke(app, ["update", str(repo), "--deterministic", "--json"])
    assert res_revert.exit_code == int(ExitCode.SUCCESS)
    payload_rev = json.loads(res_revert.stdout)
    assert payload_rev["is_noop"] is False
    assert payload_rev["category"] == "revert"
    assert payload_rev["change_id"] == "CA-19700101-0002"

    # Verify both records remain intact in the append-only journal
    records_after = read_all_journal_records(repo / ".context")
    assert len(records_after) == 2
    assert records_after[0].change_id == "CA-19700101-0001"
    assert records_after[1].change_id == "CA-19700101-0002"
    assert records_after[1].parent_change_id == "CA-19700101-0001"
    assert records_after[1].category == "revert"

    # Render `ctxa handoff` and confirm `ctxa verify` returns CURRENT (0)
    assert runner.invoke(app, ["handoff", str(repo), "--deterministic"]).exit_code == 0
    assert runner.invoke(app, ["verify", str(repo)]).exit_code == int(ExitCode.SUCCESS)
    md_content = (repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    assert "CA-19700101-0001" in md_content
    assert "CA-19700101-0002" in md_content
