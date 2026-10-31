"""Unit tests for the Python AST analyzer covering symbols, imports, calls, and edge cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.adapters.python_ast import PythonAstAdapter
from context_archive.config import load_config
from context_archive.scanner.walker import scan_repository

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_python_ast_complex_signatures_inheritance_and_dynamic_diagnostics(
    tmp_path: Path,
) -> None:
    """Test extraction of classes, async methods, *args/**kwargs, constants, and dynamic calls."""
    pkg = tmp_path / "src" / "core"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "base.py").write_text(
        "MAX_RETRIES: int = 3\n"
        "PLAIN_CONST = 'v1'\n\n"
        "class BaseWorker:\n"
        '    """Base worker class."""\n'
        "    def helper(self, value: int) -> int:\n"
        "        return value + 1\n",
        encoding="utf-8",
    )
    (pkg / "service.py").write_text(
        "import core.base as base_alias\n"
        "from .base import *\n"
        "from .base import BaseWorker, MAX_RETRIES\n\n"
        "class AsyncService(BaseWorker):\n"
        "    def local_step(self) -> int:\n"
        "        return 1\n\n"
        "    @classmethod\n"
        "    async def execute(\n"
        "        cls,\n"
        "        pos_only: int,\n"
        "        /,\n"
        "        name: str = 'default',\n"
        "        *args: int,\n"
        "        flag: bool = True,\n"
        "        **kwargs: str,\n"
        "    ) -> str | None:\n"
        '        """Execute service workflow.\n\n'
        "        Second paragraph is ignored in summary.\n"
        '        """\n'
        "        step_val = cls.local_step()\n"
        "        dynamic_res = getattr(cls, name)\n"
        "        _ = (MAX_RETRIES, dynamic_res, step_val, base_alias)\n"
        "        return name\n",
        encoding="utf-8",
    )

    cfg = load_config(tmp_path)
    scan_rep = scan_repository(tmp_path, cfg)
    adapter = PythonAstAdapter()
    assert adapter.adapter_id == "python_ast:1.0"
    res = adapter.extract_repository(tmp_path, scan_rep.files)

    by_id = {n.id: n for n in res.nodes}
    assert "sym:py:src/core/base.py:MAX_RETRIES" in by_id
    assert by_id["sym:py:src/core/base.py:MAX_RETRIES"].kind == "Variable"
    assert "sym:py:src/core/base.py:PLAIN_CONST" in by_id

    exec_id = "sym:py:src/core/service.py:AsyncService.execute"
    assert exec_id in by_id
    exec_node = by_id[exec_id]
    assert exec_node.kind == "Method"
    assert exec_node.attributes["is_async"] is True
    assert exec_node.attributes["decorators"] == ["classmethod"]
    assert exec_node.attributes["docstring_summary"] == "Execute service workflow."
    sig = exec_node.attributes["signature"]
    assert "pos_only: int, /" in sig
    assert "*args: int" in sig
    assert "flag: bool = True" in sig
    assert "**kwargs: str" in sig
    assert "-> str | None" in sig

    edge_ids = {e.id for e in res.edges}
    assert (
        "edge:INHERITS:sym:py:src/core/service.py:AsyncService->"
        "sym:py:src/core/base.py:BaseWorker" in edge_ids
    )
    assert (
        "edge:IMPORTS:mod:py:src/core/service.py:core.service->"
        "sym:py:src/core/base.py:BaseWorker" in edge_ids
    )
    assert (
        "edge:CALLS:sym:py:src/core/service.py:AsyncService.execute->"
        "sym:py:src/core/service.py:AsyncService.local_step" in edge_ids
    )

    diag_codes = {d.code for d in res.diagnostics}
    assert "unresolved_dynamic_call" in diag_codes
    assert "wildcard_import" in diag_codes


@pytest.mark.unit
def test_python_ast_syntax_error_resilience_and_prompt_injection_sanitization(
    fixtures_dir: Path,
) -> None:
    """Verify broken syntax adds a diagnostic without crashing and CTXA markers are sanitized."""
    edge_dir = fixtures_dir / "fixture_edge_cases"
    cfg = load_config(edge_dir)
    scan_rep = scan_repository(edge_dir, cfg)
    adapter = PythonAstAdapter()
    res = adapter.extract_repository(edge_dir, scan_rep.files)

    by_id = {n.id: n for n in res.nodes}
    adv_id = "sym:py:valid_module.py:adversarial_function"
    assert adv_id in by_id
    doc_summary = by_id[adv_id].attributes["docstring_summary"]
    assert "<!-- CTXA:" not in doc_summary
    assert "Process user input safely." in doc_summary

    syntax_diags = [d for d in res.diagnostics if d.code == "python_syntax_error"]
    assert len(syntax_diags) == 1
    assert syntax_diags[0].source_path == "broken_syntax.py"
