"""Benchmark comparing compiled task context packets against raw repository file dumps."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff
from context_archive.config import load_config
from context_archive.context.compiler import compile_task_context
from context_archive.context.tokenizer import HeuristicTokenEstimator

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.benchmark
def test_task_context_token_efficiency_vs_raw_repo_dump(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify compiled task packets use fewer tokens than raw dumps while keeping key symbols."""
    repo = tmp_path / "token_bench_repo"
    shutil.copytree(fixtures_dir / "fixture_fastapi", repo)

    extra_dir = repo / "app" / "unrelated"
    extra_dir.mkdir(parents=True)
    for idx in range(15):
        (extra_dir / f"service_{idx:02d}.py").write_text(
            f'"""Unrelated domain service {idx:02d}."""\n\n'
            + "\n".join(
                f"def unrelated_op_{idx}_{fn}(x: int) -> int:\n"
                f'    """Perform unrelated operation {fn}."""\n'
                f"    return x + {fn}\n"
                for fn in range(10)
            ),
            encoding="utf-8",
        )

    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)
    estimator = HeuristicTokenEstimator()

    raw_repo_text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(repo.rglob("*.py")))
    raw_tokens = estimator.count(raw_repo_text)

    packet = compile_task_context(
        repo_root=repo,
        config=cfg,
        task="Modify create_order endpoint and OrderCreateRequest validation",
        max_tokens=1200,
    )

    assert packet.estimated_tokens <= 1200
    assert packet.estimated_tokens < raw_tokens * 0.50
    inc_names = {c.qualified_name for c in packet.included_candidates}
    assert "app.main.create_order" in inc_names
    assert "app.schemas.OrderCreateRequest" in inc_names
