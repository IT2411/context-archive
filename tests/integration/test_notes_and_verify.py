"""End-to-end integration tests for note survival across 5+ handoffs and `ctxa verify`."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app
from context_archive.exceptions import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.integration
def test_note_survival_across_multiple_handoffs_and_inline_edits(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Add 3 CLI notes, edit Section 11 inline in PROJECT_CONTEXT.md, and run handoff 5 times."""
    repo = tmp_path / "notes_survival_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0

    # Add 3 notes via `ctxa note`
    assert (
        runner.invoke(
            app,
            [
                "note",
                "All monetary values must use Decimal",
                str(repo),
                "--type",
                "decision",
                "--scope",
                "src/sample_lib/calculator.py",
                "--deterministic",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "note",
                "Never use floating point for tax rates",
                str(repo),
                "--type",
                "constraint",
                "--deterministic",
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            [
                "note",
                "Add discount code support in next sprint",
                str(repo),
                "--type",
                "next_step",
                "--deterministic",
            ],
        ).exit_code
        == 0
    )

    # Verify freshness is still CURRENT after adding notes via `ctxa note`
    verify_res = runner.invoke(app, ["verify", str(repo), "--json"])
    assert verify_res.exit_code == int(ExitCode.SUCCESS)

    # Manually edit Section 11 inside PROJECT_CONTEXT.md
    md_path = repo / "PROJECT_CONTEXT.md"
    raw_md = md_path.read_text(encoding="utf-8")
    edited_md = raw_md.replace(
        "# 11. Architectural Decisions & Constraints (Human-Maintained)\n",
        "# 11. Architectural Decisions & Constraints (Human-Maintained)\n"
        "- **[INLINE-HUMAN-EDIT]**: Preserve this custom inline architectural note.\n",
    )
    md_path.write_text(edited_md, encoding="utf-8")

    # Run `ctxa handoff` 5 consecutive times
    for _ in range(5):
        res = runner.invoke(app, ["handoff", str(repo), "--deterministic"])
        assert res.exit_code == int(ExitCode.SUCCESS)

    final_md = md_path.read_text(encoding="utf-8")
    final_notes = (repo / ".context" / "notes.md").read_text(encoding="utf-8")

    for expected_phrase in (
        "All monetary values must use Decimal",
        "Never use floating point for tax rates",
        "Add discount code support in next sprint",
        "Preserve this custom inline architectural note.",
    ):
        assert expected_phrase in final_md
        assert expected_phrase in final_notes

    # Final `ctxa verify` must pass with ExitCode.SUCCESS (0)
    final_verify = runner.invoke(app, ["verify", str(repo)])
    assert final_verify.exit_code == int(ExitCode.SUCCESS)
