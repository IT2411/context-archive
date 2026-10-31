"""Unit tests for the deterministic PROJECT_CONTEXT.md renderer and snapshot/manifest models."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from context_archive.config import load_config
from context_archive.exceptions import IntegrityError
from context_archive.model.manifest import load_manifest
from context_archive.renderers.markdown import (
    GENERATED_END,
    GENERATED_START,
    HEADER_END,
    HEADER_START,
    MANUAL_END,
    MANUAL_START,
    extract_dev_commands,
)
from context_archive.state.snapshot import format_snapshot_id, load_snapshot

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_format_snapshot_id_and_missing_loaders(tmp_path: Path) -> None:
    """Verify snapshot ID formatting and IntegrityError on missing/corrupt files."""
    assert format_snapshot_id(1) == "snapshot-0001"
    assert format_snapshot_id(42) == "snapshot-0042"

    with pytest.raises(IntegrityError):
        load_manifest(tmp_path)

    with pytest.raises(IntegrityError):
        load_snapshot(tmp_path, "snapshot-0001")

    # Corrupt JSON files also raise IntegrityError
    (tmp_path / "manifest.json").write_text("{corrupt", encoding="utf-8")
    with pytest.raises(IntegrityError):
        load_manifest(tmp_path)

    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / "snapshot-0001.json").write_text("{corrupt", encoding="utf-8")
    with pytest.raises(IntegrityError):
        load_snapshot(tmp_path, "snapshot-0001")


@pytest.mark.unit
def test_extract_dev_commands_from_manifests(tmp_path: Path) -> None:
    """Verify development commands are extracted from pyproject.toml, Makefile, and package.json."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n[project.scripts]\ndemo-cli = "demo.cli:app"\n'
        "[tool.pytest.ini_options]\nminversion = '8.0'\n",
        encoding="utf-8",
    )
    (tmp_path / "Makefile").write_text("lint:\n\truff check .\ntest:\n\tpytest\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "web", "scripts": {"build": "vite build"}}),
        encoding="utf-8",
    )

    cmds = extract_dev_commands(tmp_path)
    joined = "\n".join(cmds)
    assert "demo-cli" in joined
    assert "poetry run pytest" in joined
    assert "`make lint`" in joined
    assert "`npm run build`" in joined
    _ = (
        HEADER_START,
        HEADER_END,
        GENERATED_START,
        GENERATED_END,
        MANUAL_START,
        MANUAL_END,
        load_config,
    )
