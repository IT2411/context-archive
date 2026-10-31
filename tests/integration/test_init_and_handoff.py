"""End-to-end integration tests for `ctxa init`, `ctxa handoff`, and `ctxa export`."""

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
def test_handoff_deterministic_idempotency_and_json_export(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify two consecutive `ctxa handoff --deterministic` runs produce identical artifacts."""
    work_repo = tmp_path / "sample_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", work_repo)

    res1 = runner.invoke(app, ["handoff", str(work_repo), "--deterministic"])
    assert res1.exit_code == int(ExitCode.SUCCESS)

    md_1 = (work_repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    graph_1 = (work_repo / ".context" / "graph.json").read_text(encoding="utf-8")
    snap_1 = (work_repo / ".context" / "snapshots" / "snapshot-0001.json").read_text(
        encoding="utf-8"
    )

    res2 = runner.invoke(app, ["handoff", str(work_repo), "--deterministic"])
    assert res2.exit_code == int(ExitCode.SUCCESS)

    md_2 = (work_repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    graph_2 = (work_repo / ".context" / "graph.json").read_text(encoding="utf-8")
    snap_2 = (work_repo / ".context" / "snapshots" / "snapshot-0001.json").read_text(
        encoding="utf-8"
    )

    assert md_1 == md_2
    assert graph_1 == graph_2
    assert snap_1 == snap_2

    # Test JSON export to file and stdout
    export_file = tmp_path / "exported_bundle.json"
    exp_res = runner.invoke(
        app,
        ["export", str(work_repo), "--format", "json", "--output", str(export_file)],
    )
    assert exp_res.exit_code == int(ExitCode.SUCCESS)
    bundle = json.loads(export_file.read_text(encoding="utf-8"))
    assert bundle["schema_version"] == "1.0.0"
    assert "manifest" in bundle
    assert "graph" in bundle


@pytest.mark.integration
def test_handoff_strict_mode_exits_1_on_syntax_or_binary_warnings(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify `ctxa handoff --strict` returns ExitCode.WARNING (1) on fixture_edge_cases."""
    edge_copy = tmp_path / "edge_cases"
    shutil.copytree(fixtures_dir / "fixture_edge_cases", edge_copy)

    # Without --strict, exits 0
    res_normal = runner.invoke(app, ["handoff", str(edge_copy), "--deterministic"])
    assert res_normal.exit_code == int(ExitCode.SUCCESS)

    # With --strict, exits 1 (EXIT_WARNING)
    res_strict = runner.invoke(app, ["handoff", str(edge_copy), "--strict", "--json"])
    assert res_strict.exit_code == int(ExitCode.WARNING)


@pytest.mark.integration
def test_handoff_aborts_and_creates_backup_on_corrupted_manual_markers(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify broken CTXA:MANUAL markers create PROJECT_CONTEXT.md.bak and exit with code 4."""
    work_repo = tmp_path / "corrupt_markers_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", work_repo)

    runner.invoke(app, ["init", str(work_repo), "--deterministic"])
    md_path = work_repo / "PROJECT_CONTEXT.md"
    raw = md_path.read_text(encoding="utf-8")

    # Corrupt by deleting the closing marker while preserving user text
    corrupted = raw.replace("<!-- CTXA:MANUAL:END -->", "My Precious Manual Note")
    md_path.write_text(corrupted, encoding="utf-8")

    res = runner.invoke(app, ["handoff", str(work_repo)])
    assert res.exit_code == int(ExitCode.INTEGRITY_ERROR)

    bak_path = work_repo / "PROJECT_CONTEXT.md.bak"
    assert bak_path.is_file()
    assert "My Precious Manual Note" in bak_path.read_text(encoding="utf-8")
