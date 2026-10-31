"""Unit and Hypothesis property tests for task-specific context compilation and token budgets."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from context_archive.cli import execute_full_handoff
from context_archive.config import load_config
from context_archive.context.compiler import compile_task_context
from context_archive.context.tokenizer import HeuristicTokenEstimator
from context_archive.exceptions import ConfigError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_compiler_strict_budget_enforcement_property(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Hypothesis property test: compiled packet never exceeds max_tokens across budgets/prompts."""
    repo = tmp_path / "prop_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)
    estimator = HeuristicTokenEstimator()

    @given(
        budget=st.integers(min_value=150, max_value=16000),
        prompt=st.sampled_from(
            [
                "Update calculate_total tax rounding in calculator.py",
                "LineItem unit_price validation",
                "round_currency half up decimal",
                "Fix bug",
                "CompletelyUnrelatedSymbolNameThatDoesNotExistInRepo",
            ]
        ),
    )
    @settings(max_examples=25, deadline=None)
    def _check_budget(budget: int, prompt: str) -> None:
        packet = compile_task_context(
            repo_root=repo,
            config=cfg,
            task=prompt,
            max_tokens=budget,
        )
        actual_count = estimator.count(packet.markdown)
        assert actual_count <= budget
        assert packet.estimated_tokens == actual_count

    _check_budget()


@pytest.mark.unit
def test_compiler_validation_errors(fixtures_dir: Path, tmp_path: Path) -> None:
    """Verify empty tasks or tiny budgets (< 128) raise ConfigError."""
    repo = tmp_path / "val_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)

    with pytest.raises(ConfigError):
        compile_task_context(repo_root=repo, config=cfg, task="   ")

    with pytest.raises(ConfigError):
        compile_task_context(repo_root=repo, config=cfg, task="Valid task", max_tokens=50)
