"""Unified multi-language and framework contract extraction pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_archive.adapters.base import AdapterExtractionResult
from context_archive.adapters.fastapi import FastApiContractExtractor
from context_archive.adapters.python_ast import PythonAstAdapter
from context_archive.adapters.sqlalchemy import SqlAlchemyEntityExtractor
from context_archive.adapters.typescript import TypeScriptAdapter

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.scanner.report import ScannedFile


def extract_all_adapters(
    repo_root: Path,
    files: tuple[ScannedFile, ...] | list[ScannedFile],
) -> AdapterExtractionResult:
    """Run all active language and framework adapters and link cross-stack contracts."""
    py_adapter = PythonAstAdapter()
    py_res = py_adapter.extract_repository(repo_root, files)

    fastapi_extractor = FastApiContractExtractor()
    fastapi_res = fastapi_extractor.extract_repository(
        repo_root,
        files,
        existing_nodes=py_res.nodes,
    )

    sqlalchemy_extractor = SqlAlchemyEntityExtractor()
    sa_res = sqlalchemy_extractor.extract_repository(repo_root, files)

    combined_backend_nodes = (*py_res.nodes, *fastapi_res.nodes, *sa_res.nodes)
    ts_adapter = TypeScriptAdapter()
    ts_res = ts_adapter.extract_repository(
        repo_root,
        files,
        existing_nodes=combined_backend_nodes,
    )

    return AdapterExtractionResult(
        nodes=(*py_res.nodes, *fastapi_res.nodes, *sa_res.nodes, *ts_res.nodes),
        edges=(*py_res.edges, *fastapi_res.edges, *sa_res.edges, *ts_res.edges),
        diagnostics=(
            *py_res.diagnostics,
            *fastapi_res.diagnostics,
            *sa_res.diagnostics,
            *ts_res.diagnostics,
        ),
    )
