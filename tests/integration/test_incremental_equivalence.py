"""Critical Phase 7 gate: Incremental L2 updates vs. Full L3 Rebuild equivalence test."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app
from context_archive.model.graph import CanonicalGraph

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.integration
def test_multi_step_incremental_l2_matches_full_l3_rebuild(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Apply 4-step mutation sequence with `ctxa update` and assert `ctxa rebuild` equivalence."""
    inc_repo = tmp_path / "inc_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", inc_repo)

    assert runner.invoke(app, ["init", str(inc_repo), "--deterministic"]).exit_code == 0

    # Step 1: Edit a function signature in utils.py
    utils_path = inc_repo / "src" / "sample_lib" / "utils.py"
    utils_path.write_text(
        '"""Currency rounding utilities."""\n\n'
        "from __future__ import annotations\n\n"
        "from decimal import ROUND_HALF_UP, Decimal\n\n\n"
        "def round_currency(value: Decimal, precision: str = '0.01') -> Decimal:\n"
        '    """Round a decimal value using half-up rounding."""\n'
        "    return value.quantize(Decimal(precision), rounding=ROUND_HALF_UP)\n\n\n"
        "def unused_helper() -> int:\n"
        "    return 0\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["update", str(inc_repo), "--deterministic"]).exit_code == 0

    # Step 2: Add a new helper module discounts.py and import/call it from calculator.py
    discounts_path = inc_repo / "src" / "sample_lib" / "discounts.py"
    discounts_path.write_text(
        '"""Discount calculation helpers."""\n\n'
        "from __future__ import annotations\n\n"
        "from decimal import Decimal\n\n\n"
        "def apply_discount(subtotal: Decimal, discount_amount: Decimal) -> Decimal:\n"
        '    """Subtract discount_amount from subtotal, clamped at zero."""\n'
        "    return max(Decimal('0.00'), subtotal - discount_amount)\n",
        encoding="utf-8",
    )
    calc_path = inc_repo / "src" / "sample_lib" / "calculator.py"
    calc_src = calc_path.read_text(encoding="utf-8")
    calc_updated = calc_src.replace(
        "from .utils import round_currency",
        "from .discounts import apply_discount\nfrom .utils import round_currency",
    ).replace(
        "tax = subtotal * tax_rate",
        "discounted = apply_discount(subtotal, Decimal('0.00'))\n    tax = discounted * tax_rate",
    )
    calc_path.write_text(calc_updated, encoding="utf-8")
    assert runner.invoke(app, ["update", str(inc_repo), "--deterministic"]).exit_code == 0

    # Step 3: Delete `unused_helper` from utils.py
    utils_path.write_text(
        '"""Currency rounding utilities."""\n\n'
        "from __future__ import annotations\n\n"
        "from decimal import ROUND_HALF_UP, Decimal\n\n\n"
        "def round_currency(value: Decimal, precision: str = '0.01') -> Decimal:\n"
        '    """Round a decimal value using half-up rounding."""\n'
        "    return value.quantize(Decimal(precision), rounding=ROUND_HALF_UP)\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["update", str(inc_repo), "--deterministic"]).exit_code == 0

    # Step 4: Update test_calculator.py to also import and test apply_discount
    test_path = inc_repo / "tests" / "test_calculator.py"
    test_path.write_text(
        test_path.read_text(encoding="utf-8")
        + "\nfrom sample_lib.discounts import apply_discount\n\n"
        "def test_apply_discount() -> None:\n"
        "    assert apply_discount(Decimal('10.00'), Decimal('2.00')) == Decimal('8.00')\n",
        encoding="utf-8",
    )
    assert runner.invoke(app, ["update", str(inc_repo), "--deterministic"]).exit_code == 0

    # Clone the final working tree into a separate directory and run a clean `ctxa rebuild` (L3)
    rebuild_repo = tmp_path / "rebuild_repo"
    shutil.copytree(
        inc_repo,
        rebuild_repo,
        ignore=shutil.ignore_patterns(".context", "PROJECT_CONTEXT.md"),
    )
    assert runner.invoke(app, ["rebuild", str(rebuild_repo), "--deterministic"]).exit_code == 0

    inc_graph = CanonicalGraph.model_validate(
        json.loads((inc_repo / ".context" / "graph.json").read_text(encoding="utf-8"))
    )
    rebuild_graph = CanonicalGraph.model_validate(
        json.loads((rebuild_repo / ".context" / "graph.json").read_text(encoding="utf-8"))
    )

    assert inc_graph.nodes == rebuild_graph.nodes
    assert inc_graph.edges == rebuild_graph.edges
    assert inc_graph.diagnostics == rebuild_graph.diagnostics
