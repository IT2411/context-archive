"""Phase 0 bootstrap, schema, ADR, and fixture verification tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

import context_archive
from context_archive.cli import app

if TYPE_CHECKING:
    from pathlib import Path

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
runner = CliRunner()


@pytest.mark.unit
def test_package_version_and_py_typed(repo_root: Path) -> None:
    """Verify package version and PEP 561 py.typed marker existence."""
    assert context_archive.__version__ == "1.0.3"
    py_typed = repo_root / "src" / "context_archive" / "py.typed"
    assert py_typed.is_file()


@pytest.mark.unit
def test_cli_version_and_help() -> None:
    """Verify CLI --version, version subcommand, and --help flags execute cleanly."""
    version_res = runner.invoke(app, ["--version"])
    assert version_res.exit_code == 0
    assert "ctxa 1.0.3" in version_res.stdout

    subcmd_res = runner.invoke(app, ["version"])
    assert subcmd_res.exit_code == 0
    assert "ctxa 1.0.3" in subcmd_res.stdout

    help_res = runner.invoke(app, ["--help"])
    assert help_res.exit_code == 0
    assert "Portable AI Project Context Compiler" in help_res.stdout


@pytest.mark.unit
@pytest.mark.parametrize(
    "schema_filename",
    [
        "manifest.schema.json",
        "graph.schema.json",
        "snapshot.schema.json",
        "journal-record.schema.json",
    ],
)
def test_json_schemas_are_valid_draft_2020_12(
    repo_root: Path,
    schema_filename: str,
) -> None:
    """Validate that all formal JSON Schemas exist and conform to Draft 2020-12 structure."""
    schema_path = repo_root / "docs" / "schemas" / schema_filename
    assert schema_path.is_file(), f"Missing schema file: {schema_path}"

    raw_data = json.loads(schema_path.read_text(encoding="utf-8"))
    assert isinstance(raw_data, dict)
    assert raw_data.get("$schema") == DRAFT_2020_12
    assert raw_data.get("type") == "object"
    assert "title" in raw_data
    assert "required" in raw_data
    assert isinstance(raw_data["required"], list)
    assert "properties" in raw_data
    assert isinstance(raw_data["properties"], dict)


@pytest.mark.unit
def test_fixture_repositories_exist_and_are_complete(fixtures_dir: Path) -> None:
    """Verify all three deterministic fixture repositories and their key files exist."""
    py_lib = fixtures_dir / "fixture_py_lib"
    assert (py_lib / "pyproject.toml").is_file()
    assert (py_lib / "src" / "sample_lib" / "calculator.py").is_file()
    assert (py_lib / "src" / "sample_lib" / "utils.py").is_file()
    assert (py_lib / "tests" / "test_calculator.py").is_file()

    fastapi_dir = fixtures_dir / "fixture_fastapi"
    assert (fastapi_dir / "pyproject.toml").is_file()
    assert (fastapi_dir / "app" / "main.py").is_file()
    assert (fastapi_dir / "app" / "models.py").is_file()
    assert (fastapi_dir / "app" / "schemas.py").is_file()
    assert (fastapi_dir / "tests" / "test_orders.py").is_file()

    edge_dir = fixtures_dir / "fixture_edge_cases"
    assert (edge_dir / ".env").is_file()
    assert (edge_dir / ".env.example").is_file()
    assert (edge_dir / "valid_module.py").is_file()
    assert (edge_dir / "broken_syntax.py").is_file()
    binary_file = edge_dir / "masquerading_binary.py"
    assert binary_file.is_file()
    assert b"\x00" in binary_file.read_bytes()


@pytest.mark.unit
@pytest.mark.parametrize(
    "adr_filename",
    [
        "001-canonical-ids.md",
        "002-incremental-journal-cursors.md",
        "003-manual-note-boundaries.md",
    ],
)
def test_adrs_exist(repo_root: Path, adr_filename: str) -> None:
    """Verify Architecture Decision Records exist and are non-empty."""
    adr_path = repo_root / "docs" / "adr" / adr_filename
    assert adr_path.is_file()
    content = adr_path.read_text(encoding="utf-8")
    assert "## Status" in content
    assert "## Decision" in content
