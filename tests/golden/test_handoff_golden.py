"""Golden-file regression tests for deterministic PROJECT_CONTEXT.md and graph.json."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff
from context_archive.config import load_config

if TYPE_CHECKING:
    from pathlib import Path

REQUIRED_HEADINGS: tuple[str, ...] = (
    "# 1. Project Identity & Quick Orientation",
    "# 2. Current Source State & Freshness Metadata",
    "# 3. Technology Stack, Manifests & Development Commands",
    "# 4. Architecture Overview & Module Map",
    "# 5. Key Symbols & Execution Flows",
    "# 6. API, Schema & Data Contracts",
    "# 7. Tests & Verification Coverage",
    "# 8. Recent Incremental Changes (Since Base Snapshot)",
    "# 9. Source Reference Index",
    "# 10. Extraction Coverage, Unknowns & Limitations",
    "# 11. Architectural Decisions & Constraints (Human-Maintained)",
    "# 12. Known Issues, Risks & Open Questions (Human-Maintained)",
    "# 13. Pending Work & Next Steps (Human-Maintained)",
)


@pytest.mark.golden
def test_fixture_py_lib_matches_golden_files(
    fixtures_dir: Path,
    repo_root: Path,
    tmp_path: Path,
) -> None:
    """Run deterministic handoff on a clean copy of fixture_py_lib and compare to golden files."""
    work_repo = tmp_path / "fixture_py_lib"
    shutil.copytree(fixtures_dir / "fixture_py_lib", work_repo)

    cfg = load_config(work_repo)
    artifacts = execute_full_handoff(work_repo, cfg, deterministic=True)

    generated_md = artifacts.output_md_path.read_text(encoding="utf-8")
    generated_graph = (work_repo / ".context" / "graph.json").read_text(encoding="utf-8")

    # Verify all 13 headings and sentinels exist
    for heading in REQUIRED_HEADINGS:
        assert heading in generated_md
    assert "<!-- CTXA:HEADER:START -->" in generated_md
    assert "<!-- CTXA:GENERATED:START -->" in generated_md
    assert "<!-- CTXA:MANUAL:START" in generated_md

    golden_dir = repo_root / "tests" / "golden" / "fixture_py_lib"
    golden_md_path = golden_dir / "PROJECT_CONTEXT.md"
    golden_graph_path = golden_dir / "graph.json"

    assert golden_md_path.is_file()
    assert golden_graph_path.is_file()

    assert generated_md == golden_md_path.read_text(encoding="utf-8")
    assert generated_graph == golden_graph_path.read_text(encoding="utf-8")
