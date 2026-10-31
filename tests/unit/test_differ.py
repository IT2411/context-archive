"""Unit tests for semantic diffing, downstream impact traversal, and Mermaid rendering."""

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


@pytest.mark.unit
def test_semantic_diff_impact_traversal_and_mermaid_formats(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Modify round_currency in utils.py and verify diff traces calculator and test_calculator."""
    repo = tmp_path / "diff_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0

    # Clean diff before any edits
    clean_text = runner.invoke(app, ["diff", str(repo), "--format", "text"])
    assert clean_text.exit_code == int(ExitCode.SUCCESS)
    assert "No structural or file changes detected." in clean_text.stdout

    clean_mermaid = runner.invoke(app, ["diff", str(repo), "--format", "mermaid"])
    assert "No structural changes detected" in clean_mermaid.stdout

    # Modify `round_currency` signature in `utils.py` and add a new function
    utils_path = repo / "src" / "sample_lib" / "utils.py"
    utils_src = utils_path.read_text(encoding="utf-8")
    utils_path.write_text(
        utils_src.replace(
            "def round_currency(value: Decimal) -> Decimal:",
            "def round_currency(value: Decimal, places: int = 2) -> Decimal:",
        )
        + "\ndef format_money(amount: Decimal) -> str:\n    return str(amount)\n",
        encoding="utf-8",
    )

    # 1. JSON diff format
    res_json = runner.invoke(app, ["diff", str(repo), "--format", "json"])
    assert res_json.exit_code == int(ExitCode.SUCCESS)
    payload = json.loads(res_json.stdout)

    assert payload["modified_files"] == ["src/sample_lib/utils.py"]
    sym_changes = {sc["symbol_id"]: sc for sc in payload["symbol_changes"]}
    round_id = "sym:py:src/sample_lib/utils.py:round_currency"
    fmt_id = "sym:py:src/sample_lib/utils.py:format_money"
    assert round_id in sym_changes
    assert sym_changes[round_id]["change_kind"] == "modified"
    assert sym_changes[round_id]["confidence"] == "direct"
    assert fmt_id in sym_changes
    assert sym_changes[fmt_id]["change_kind"] == "added"

    # Downstream impact includes calculate_total (hop 1) and test_calculate_total_with_tax (hop 2)
    impacts = {imp["target_id"]: imp for imp in payload["downstream_impacts"]}
    calc_id = "sym:py:src/sample_lib/calculator.py:calculate_total"
    test_id = "sym:py:tests/test_calculator.py:test_calculate_total_with_tax"
    assert calc_id in impacts
    assert impacts[calc_id]["relationship"] == "CALLS"
    assert impacts[calc_id]["confidence"] == "inferred_downstream"
    assert impacts[calc_id]["hop_distance"] == 1

    assert test_id in impacts
    assert impacts[test_id]["relationship"] == "TESTED_BY"
    assert impacts[test_id]["confidence"] == "inferred_downstream"
    assert impacts[test_id]["hop_distance"] == 2

    # 2. Text diff format
    res_text = runner.invoke(app, ["diff", str(repo), "--format", "text"])
    assert "sample_lib.utils.round_currency" in res_text.stdout
    assert "sample_lib.calculator.calculate_total" in res_text.stdout
    assert "inferred_downstream" in res_text.stdout

    # 3. Mermaid diff and export formats
    res_mermaid = runner.invoke(app, ["diff", str(repo), "--format", "mermaid"])
    assert res_mermaid.exit_code == int(ExitCode.SUCCESS)
    assert "flowchart TD" in res_mermaid.stdout
    assert "MODIFIED: Function" in res_mermaid.stdout
    assert "IMPACTED:" in res_mermaid.stdout

    mermaid_out = tmp_path / "arch.mmd"
    res_exp_mmd = runner.invoke(
        app, ["export", str(repo), "--format", "mermaid", "--output", str(mermaid_out)]
    )
    assert res_exp_mmd.exit_code == int(ExitCode.SUCCESS)
    assert "flowchart TD" in mermaid_out.read_text(encoding="utf-8")

    res_exp_stdout = runner.invoke(app, ["export", str(repo), "--format", "mermaid"])
    assert res_exp_stdout.exit_code == int(ExitCode.SUCCESS)
    assert "flowchart TD" in res_exp_stdout.stdout
