"""Typed exception hierarchy and standardized CLI exit codes for context-archive."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    """Standardized CLI exit codes defined in SRS Section 8.2."""

    SUCCESS = 0
    WARNING = 1
    STALE_OR_DIFF = 2
    CONFIG_OR_USAGE = 3
    INTEGRITY_ERROR = 4
    INTERNAL_ERROR = 5


class CtxaError(Exception):
    """Base exception for all known context-archive errors."""

    exit_code: ExitCode = ExitCode.INTERNAL_ERROR

    def __init__(self, message: str, *, exit_code: ExitCode | None = None) -> None:
        super().__init__(message)
        self.message = message
        if exit_code is not None:
            self.exit_code = exit_code


class CtxaWarningError(CtxaError):
    """Raised when an operation completes with strict-mode warnings (Exit 1)."""

    exit_code = ExitCode.WARNING


class StaleContextError(CtxaError):
    """Raised when verification detects stale context or diffs (Exit 2)."""

    exit_code = ExitCode.STALE_OR_DIFF


class ConfigError(CtxaError):
    """Raised on invalid CLI arguments, malformed TOML, or invalid paths (Exit 3)."""

    exit_code = ExitCode.CONFIG_OR_USAGE


class IntegrityError(CtxaError):
    """Raised on corrupt snapshots/journals, lock contention, or broken markers (Exit 4)."""

    exit_code = ExitCode.INTEGRITY_ERROR


class LockError(IntegrityError):
    """Raised when .context/.lock is held by an active process (Exit 4)."""
