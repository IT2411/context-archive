"""adapters subsystem for context-archive."""

from __future__ import annotations

from context_archive.adapters.base import AdapterExtractionResult, LanguageAdapter
from context_archive.adapters.fastapi import FastApiContractExtractor
from context_archive.adapters.pipeline import extract_all_adapters
from context_archive.adapters.python_ast import PythonAstAdapter
from context_archive.adapters.sqlalchemy import SqlAlchemyEntityExtractor
from context_archive.adapters.typescript import TypeScriptAdapter

__all__ = [
    "AdapterExtractionResult",
    "FastApiContractExtractor",
    "LanguageAdapter",
    "PythonAstAdapter",
    "SqlAlchemyEntityExtractor",
    "TypeScriptAdapter",
    "extract_all_adapters",
]
