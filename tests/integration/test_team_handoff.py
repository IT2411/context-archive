"""Integration tests for multi-branch divergence reconciliation, clean clone handoff, and SDK."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive import ContextArchiveEngine
from context_archive.cli import app
from context_archive.exceptions import ExitCode
from context_archive.state.journal import read_all_journal_records

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
def test_branch_divergence_reconciliation_and_cross_clone_handoff(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Simulate two developers on branch-a and branch-b, merge, reconcile, and clone."""
    repo = tmp_path / "team_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "team@example.com")
    _git(repo, "config", "user.name", "Team Dev")
    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Initial baseline with context")

    # Developer A on branch-a makes an edit, records a journal entry, and adds a note
    _git(repo, "checkout", "-b", "branch-a")
    utils_path = repo / "src" / "sample_lib" / "utils.py"
    utils_base = utils_path.read_text(encoding="utf-8")
    utils_path.write_text(utils_base + "\nDEV_A_CONST = 'A'\n", encoding="utf-8")
    assert (
        runner.invoke(
            app, ["update", str(repo), "-m", "Dev A added constant", "--deterministic"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app, ["note", "Dev A architectural decision", str(repo), "--deterministic"]
        ).exit_code
        == 0
    )
    rec_a_line = (repo / ".context" / "journal" / "1970-01.jsonl").read_text(encoding="utf-8")
    notes_a_text = (repo / ".context" / "notes.md").read_text(encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Dev A work")

    # Developer B on branch-b from main makes a different edit, journal entry, and note
    _git(repo, "checkout", "main")
    _git(repo, "checkout", "-b", "branch-b")
    calc_path = repo / "src" / "sample_lib" / "calculator.py"
    calc_base = calc_path.read_text(encoding="utf-8")
    calc_path.write_text(calc_base + "\nDEV_B_CONST = 'B'\n", encoding="utf-8")
    assert (
        runner.invoke(
            app, ["update", str(repo), "-m", "Dev B added constant", "--deterministic"]
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["note", "Dev B constraint note", str(repo), "--type", "constraint", "--deterministic"],
        ).exit_code
        == 0
    )
    rec_b_line = (repo / ".context" / "journal" / "1970-01.jsonl").read_text(encoding="utf-8")

    # Simulate merging branch-a and branch-b (both code changes, unioned journal lines, and notes)
    utils_path.write_text(utils_base + "\nDEV_A_CONST = 'A'\n", encoding="utf-8")
    (repo / ".context" / "journal" / "1970-01.jsonl").write_text(
        rec_a_line + rec_b_line,
        encoding="utf-8",
    )
    # Put Dev A's notes in notes.md and Dev B's notes in PROJECT_CONTEXT.md to test 2-way union
    (repo / ".context" / "notes.md").write_text(notes_a_text, encoding="utf-8")

    # Because both journal records have change_id CA-19700101-0001 and parent=None,
    # a naive `ctxa update` refuses silent partial overwrite with ExitCode.INTEGRITY_ERROR (4)
    calc_path.write_text(calc_base + "\nDEV_B_CONST = 'B2'\n", encoding="utf-8")
    fork_update = runner.invoke(app, ["update", str(repo), "--deterministic"])
    assert fork_update.exit_code == int(ExitCode.INTEGRITY_ERROR)

    # Reconcile cleanly via `ctxa rebuild`
    rebuild_res = runner.invoke(app, ["rebuild", str(repo), "--deterministic"])
    assert rebuild_res.exit_code == int(ExitCode.SUCCESS)

    # Commit reconciled state so Git working tree is clean before cloning
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Reconciled merge commit")
    assert runner.invoke(app, ["handoff", str(repo), "--deterministic"]).exit_code == 0
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Update context for reconciled merge")
    assert runner.invoke(app, ["handoff", str(repo), "--deterministic"]).exit_code == 0

    # Verify both developers' journal records and both developers' notes survived!
    reconciled_records = read_all_journal_records(repo / ".context")
    assert len(reconciled_records) == 2
    summaries = {r.intent.summary for r in reconciled_records}
    assert summaries == {"Dev A added constant", "Dev B added constant"}

    final_md = (repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    assert "Dev A architectural decision" in final_md
    assert "Dev B constraint note" in final_md

    # Cross-Clone Handoff Test: clone into a new directory and verify `ctxa verify` & SDK work
    cloned_repo = tmp_path / "cloned_repo"
    shutil.copytree(repo, cloned_repo)

    engine = ContextArchiveEngine(repo_root=cloned_repo)
    ver_rep = engine.verify()
    assert ver_rep.status == "CURRENT"

    packet = engine.compile_task_context(task="Check DEV_A_CONST and DEV_B_CONST", max_tokens=2000)
    assert packet.estimated_tokens <= 2000
    assert "DEV_A_CONST" in packet.markdown or "DEV_B_CONST" in packet.markdown

    sdk_upd = engine.update(intent="No-op SDK check", deterministic=True)
    assert sdk_upd.is_noop is True

    sdk_ho = engine.generate_handoff(deterministic=True)
    assert sdk_ho.output_path.is_file()
