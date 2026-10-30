"""Shared pytest fixtures for context-archive tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the root directory of the context-archive repository."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def fixtures_dir(repo_root: Path) -> Path:
    """Return the path to tests/fixtures."""
    return repo_root / "tests" / "fixtures"
