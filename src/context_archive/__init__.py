"""Portable AI Project Context Compiler (context-archive / ctxa)."""

from __future__ import annotations

__version__ = "1.0.0"

from context_archive.config import CtxaConfig, load_config
from context_archive.context.compiler import TaskPacket
from context_archive.context.verifier import VerificationReport
from context_archive.exceptions import (
    ConfigError,
    CtxaError,
    CtxaWarningError,
    ExitCode,
    IntegrityError,
    LockError,
    StaleContextError,
)
from context_archive.lock import (
    ContextLock,
    atomic_write_bytes,
    atomic_write_text,
)
from context_archive.sdk import (
    ContextArchiveEngine,
    HandoffResult,
    UpdateResult,
)

__all__ = [
    "ConfigError",
    "ContextArchiveEngine",
    "ContextLock",
    "CtxaConfig",
    "CtxaError",
    "CtxaWarningError",
    "ExitCode",
    "HandoffResult",
    "IntegrityError",
    "LockError",
    "StaleContextError",
    "TaskPacket",
    "UpdateResult",
    "VerificationReport",
    "__version__",
    "atomic_write_bytes",
    "atomic_write_text",
    "load_config",
]
