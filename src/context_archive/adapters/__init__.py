"""adapters subsystem for context-archive."""

from __future__ import annotations

from context_archive.adapters.base import AdapterExtractionResult, LanguageAdapter
from context_archive.adapters.python_ast import PythonAstAdapter

__all__ = [
    "AdapterExtractionResult",
    "LanguageAdapter",
    "PythonAstAdapter",
]
