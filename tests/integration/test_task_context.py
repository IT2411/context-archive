"""Integration tests for `ctxa context`: relevance ranking, omission transparency, and fallback."""

from __future__ import annotations

import json
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
def test_task_context_relevance_omission_and_fallback(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Test relevance inclusion, omission manifest under tight budget, and fallback."""
    repo = tmp_path / "ctx_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "note",
                "Always quantize currency to 0.01",
                str(repo),
                "--type",
                "constraint",
                "--deterministic",
            ],
        ).exit_code
        == 0
    )

    # 1. Relevance & neighbor inclusion test at 3000 tokens
    res_rel = runner.invoke(
        app,
        [
            "context",
            "Update calculate_total tax rounding",
            str(repo),
            "--max-tokens",
            "3000",
            "--format",
            "json",
        ],
    )
    assert res_rel.exit_code == int(ExitCode.SUCCESS)
    packet_data = json.loads(res_rel.stdout)
    assert packet_data["estimated_tokens"] <= 3000

    inc_names = {c["qualified_name"] for c in packet_data["included_candidates"]}
    assert "sample_lib.calculator.calculate_total" in inc_names
    assert "sample_lib.utils.round_currency" in inc_names
    assert "tests.test_calculator.test_calculate_total_with_tax" in inc_names
    assert "Always quantize currency to 0.01" in packet_data["markdown"]

    # 2. Omission transparency test under tight budget (220 tokens)
    res_tight = runner.invoke(
        app,
        [
            "context",
            "Update calculate_total tax rounding",
            str(repo),
            "--max-tokens",
            "220",
            "--format",
            "json",
        ],
    )
    assert res_tight.exit_code == int(ExitCode.SUCCESS)
    tight_data = json.loads(res_tight.stdout)
    assert tight_data["estimated_tokens"] <= 220
    assert len(tight_data["omitted_candidates"]) >= 1
    assert "Omitted Candidates:" in tight_data["markdown"]

    # 3. Low-information fallback test ("Fix bug") outputting Markdown to stdout
    res_fallback = runner.invoke(
        app,
        ["context", "Fix bug", str(repo), "--max-tokens", "2000"],
    )
    assert res_fallback.exit_code == int(ExitCode.SUCCESS)
    assert "<!-- CTXA:TASK_PACKET:START -->" in res_fallback.stdout
    assert "sample_lib.calculator.calculate_total" in res_fallback.stdout
