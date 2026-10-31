"""Integration tests scanning the synthetic fixture repositories."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.config import load_config
from context_archive.scanner.walker import scan_repository

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
def test_scan_fixture_py_lib(fixtures_dir: Path) -> None:
    """Verify fixture_py_lib is inventoried with accurate categories and SHA-256 fingerprints."""
    target = fixtures_dir / "fixture_py_lib"
    cfg = load_config(target)
    report = scan_repository(target, cfg)

    by_path = {f.path: f for f in report.files}
    assert "pyproject.toml" in by_path
    assert by_path["pyproject.toml"].category == "manifest"

    assert "src/sample_lib/calculator.py" in by_path
    assert by_path["src/sample_lib/calculator.py"].category == "source_code"
    assert by_path["src/sample_lib/calculator.py"].language == "python"

    assert "tests/test_calculator.py" in by_path
    assert by_path["tests/test_calculator.py"].category == "test"
    assert by_path["tests/test_calculator.py"].language == "python"

    fingerprints = report.file_fingerprints()
    assert len(fingerprints) == len(report.files)
    assert all(fp.startswith("sha256:") for fp in fingerprints.values())


@pytest.mark.integration
def test_scan_fixture_edge_cases(fixtures_dir: Path) -> None:
    """Verify fixture_edge_cases excludes .env, skips binaries, and keeps .env.example."""
    target = fixtures_dir / "fixture_edge_cases"
    cfg = load_config(target)
    report = scan_repository(target, cfg)

    by_path = {f.path: f for f in report.files}
    assert ".env" not in by_path
    assert "masquerading_binary.py" not in by_path
    assert ".env.example" in by_path
    assert "valid_module.py" in by_path
    # broken_syntax.py is valid UTF-8 text so the file scanner inventories it;
    # the Python AST analyzer in Phase 3 will record the SyntaxError diagnostic.
    assert "broken_syntax.py" in by_path

    diag_codes = {d.code for d in report.diagnostics}
    assert "secret_excluded" in diag_codes
    assert "binary_file_skipped" in diag_codes
