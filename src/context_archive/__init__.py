"""Portable AI Project Context Compiler (context-archive / ctxa)."""

from __future__ import annotations

from context_archive.config import CtxaConfig, load_config
from context_archive.exceptions import (
    ConfigError,
    CtxaError,
    CtxaWarningError,
    ExitCode,
    IntegrityError,
    LockError,
    StaleContextError,
)
from context_archive.lock import ContextLock, atomic_write_bytes, atomic_write_text

__version__ = "0.1.0"
__all__ = [
    "ConfigError",
    "ContextLock",
    "CtxaConfig",
    "CtxaError",
    "CtxaWarningError",
    "ExitCode",
    "IntegrityError",
    "LockError",
    "StaleContextError",
    "__version__",
    "atomic_write_bytes",
    "atomic_write_text",
    "load_config",
]
