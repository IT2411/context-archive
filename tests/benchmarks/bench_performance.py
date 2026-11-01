"""Automated latency, incremental speedup, and memory ceiling benchmarks."""

from __future__ import annotations

import time
import tracemalloc
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff, execute_incremental_update
from context_archive.config import load_config
from context_archive.context.verifier import verify_repository_freshness

if TYPE_CHECKING:
    from pathlib import Path


def _build_synthetic_repo(root: Path, module_count: int = 35) -> None:
    """Create a multi-module Python repository for performance and memory benchmarking."""
    pkg = root / "src" / "bench_pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""Benchmark package."""\n', encoding="utf-8")

    for idx in range(module_count):
        prev_import = f"from .mod_{idx - 1:03d} import compute_{idx - 1:03d}\n" if idx > 0 else ""
        prev_call = f"compute_{idx - 1:03d}(val)" if idx > 0 else "val"
        (pkg / f"mod_{idx:03d}.py").write_text(
            f'"""Module {idx:03d} docstring."""\n\n'
            f"{prev_import}\n"
            f"CONST_{idx:03d}: int = {idx}\n\n"
            f"def compute_{idx:03d}(val: int) -> int:\n"
            f'    """Compute step {idx:03d}."""\n'
            f"    return ({prev_call}) + CONST_{idx:03d}\n",
            encoding="utf-8",
        )


@pytest.mark.benchmark
def test_cold_scan_incremental_update_verify_latency_and_memory_bounds(
    tmp_path: Path,
) -> None:
    """Assert cold L3 handoff, L1 update, verify latency, and peak RSS memory bounds."""
    repo = tmp_path / "bench_repo"
    _build_synthetic_repo(repo, module_count=35)
    cfg = load_config(repo)

    tracemalloc.start()
    t0 = time.perf_counter()
    execute_full_handoff(repo, cfg, deterministic=True)
    cold_elapsed = time.perf_counter() - t0
    _current_mem, peak_mem_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem_bytes / (1024 * 1024)
    assert cold_elapsed < 2.5, f"Cold handoff took {cold_elapsed:.3f}s (> 2.5s budget)"
    assert peak_mb < 250.0, f"Peak memory {peak_mb:.2f} MB exceeded 250 MB ceiling"

    # Measure L1 incremental update latency on a single modified file (< 350ms target)
    target_mod = repo / "src" / "bench_pkg" / "mod_010.py"
    target_mod.write_text(
        target_mod.read_text(encoding="utf-8") + "\n# localized body comment edit\n",
        encoding="utf-8",
    )
    t_upd = time.perf_counter()
    upd_res = execute_incremental_update(repo, cfg, deterministic=True)
    update_elapsed = time.perf_counter() - t_upd
    assert upd_res.update_level == "L1"
    assert update_elapsed < 0.35, f"L1 update took {update_elapsed:.3f}s (> 0.35s budget)"

    # Refresh handoff and measure `ctxa verify` latency (< 200ms target)
    execute_full_handoff(repo, cfg, deterministic=True)
    t_ver = time.perf_counter()
    ver_rep = verify_repository_freshness(repo, cfg)
    verify_elapsed = time.perf_counter() - t_ver
    assert ver_rep.status == "CURRENT"
    assert verify_elapsed < 0.20, f"Verify took {verify_elapsed:.3f}s (> 0.20s budget)"
