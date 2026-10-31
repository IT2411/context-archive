"""Unit tests for the incremental change detector, rename matching, and Update Level selection."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from context_archive.cli import execute_full_handoff, execute_incremental_update
from context_archive.config import load_config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_detector_l1_body_edit_vs_l2_signature_edit(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify body-only edits trigger L1 while signature edits trigger L2."""
    repo = tmp_path / "detector_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)

    calc_file = repo / "src" / "sample_lib" / "calculator.py"
    original_src = calc_file.read_text(encoding="utf-8")

    # 1. Body-only edit (L1)
    body_edited = original_src.replace(
        "tax = subtotal * tax_rate",
        "tax = (subtotal * tax_rate)  # internal comment edit",
    )
    calc_file.write_text(body_edited, encoding="utf-8")

    res_l1 = execute_incremental_update(repo, cfg, deterministic=True)
    assert res_l1.is_noop is False
    assert res_l1.update_level == "L1"
    assert res_l1.record is not None
    assert (
        "sym:py:src/sample_lib/calculator.py:calculate_total"
        in res_l1.record.file_changes[0].modified_symbols
    )

    # 2. Signature edit (L2)
    old_sig = (
        "def calculate_total(items: list[LineItem], "
        'tax_rate: Decimal = Decimal("0.00")) -> Decimal:'
    )
    new_sig = (
        "def calculate_total(items: list[LineItem], "
        'tax_rate: Decimal = Decimal("0.00"), discount: int = 0) -> Decimal:'
    )
    sig_edited = body_edited.replace(old_sig, new_sig)
    calc_file.write_text(sig_edited, encoding="utf-8")

    res_l2 = execute_incremental_update(repo, cfg, deterministic=True)
    assert res_l2.is_noop is False
    assert res_l2.update_level == "L2"
    assert res_l2.record is not None
    assert res_l2.record.category == "contract_change"


@pytest.mark.unit
def test_detector_rename_and_category_classification(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify SHA-256 rename detection and deterministic docs/test/dependency categories."""
    repo = tmp_path / "rename_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)

    # 1. Rename utils.py -> rounding.py without modifying content
    old_path = repo / "src" / "sample_lib" / "utils.py"
    new_path = repo / "src" / "sample_lib" / "rounding.py"
    old_path.rename(new_path)

    res_rename = execute_incremental_update(repo, cfg, deterministic=True)
    assert res_rename.record is not None
    assert len(res_rename.record.file_changes) == 1
    assert res_rename.record.file_changes[0].path == "src/sample_lib/rounding.py"
    assert res_rename.record.file_changes[0].operation == "renamed"

    # 2. Test-only change -> category="test_change"
    test_file = repo / "tests" / "test_calculator.py"
    test_file.write_text(
        test_file.read_text(encoding="utf-8") + "\n# extra test assertion comment\n",
        encoding="utf-8",
    )
    res_test = execute_incremental_update(repo, cfg, deterministic=True)
    assert res_test.record is not None
    assert res_test.record.category == "test_change"

    # 3. Docs-only change -> category="docs_change"
    (repo / "README.md").write_text("# Sample Library Docs\n", encoding="utf-8")
    res_docs = execute_incremental_update(repo, cfg, deterministic=True)
    assert res_docs.record is not None
    assert res_docs.record.category == "docs_change"
