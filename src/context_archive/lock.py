"""Atomic file-writing primitives and .context/.lock concurrency manager."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from context_archive.exceptions import CtxaError, ExitCode, LockError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import TracebackType


def atomic_write_bytes(
    target_path: Path,
    data: bytes,
    *,
    before_replace_hook: Callable[[Path], None] | None = None,
) -> None:
    """Atomically write bytes to target_path via a same-directory temp file and os.replace."""
    parent = target_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{target_path.name}.",
        suffix=".tmp",
    )
    tmp_path = parent / tmp_name
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if before_replace_hook is not None:
            before_replace_hook(tmp_path)
        tmp_path.replace(target_path)
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        if isinstance(exc, CtxaError):
            raise
        raise CtxaError(
            f"Atomic write failed for '{target_path}': {exc}",
            exit_code=ExitCode.INTERNAL_ERROR,
        ) from exc


def atomic_write_text(
    target_path: Path,
    content: str,
    *,
    encoding: str = "utf-8",
    before_replace_hook: Callable[[Path], None] | None = None,
) -> None:
    """Atomically write UTF-8 text to target_path."""
    atomic_write_bytes(
        target_path,
        content.encode(encoding),
        before_replace_hook=before_replace_hook,
    )


def _is_pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID exists and is running."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":  # pragma: no cover
        process_query_limited_info = 0x1000
        still_active = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(process_query_limited_info, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return bool(exit_code.value == still_active)
            return False
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, SystemError):
        return False
    return True


@dataclass(frozen=True)
class LockMetadata:
    """Metadata stored inside .context/.lock."""

    pid: int
    acquired_at: str


class ContextLock:
    """Process-safe file lock managing .context/.lock with stale PID recovery."""

    def __init__(self, context_dir: Path) -> None:
        self.context_dir = context_dir
        self.lock_path = context_dir / ".lock"
        self._acquired = False

    def acquire(self) -> LockMetadata:
        """Acquire .context/.lock or recover if held by a dead PID."""
        self.context_dir.mkdir(parents=True, exist_ok=True)
        metadata = LockMetadata(
            pid=os.getpid(),
            acquired_at=datetime.now(timezone.utc).isoformat(),
        )
        payload = json.dumps(
            {"pid": metadata.pid, "acquired_at": metadata.acquired_at},
            sort_keys=True,
        ).encode("utf-8")

        for attempt in range(2):
            try:
                fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                self._acquired = True
                return metadata
            except FileExistsError as exc:
                holder_pid = self._read_holder_pid()
                if holder_pid is not None and _is_pid_alive(holder_pid):
                    raise LockError(
                        f"Context lock '{self.lock_path}' is currently held by active "
                        f"process PID {holder_pid}."
                    ) from exc
                if attempt == 0:
                    self.lock_path.unlink(missing_ok=True)
                    continue
                raise LockError(f"Unable to acquire context lock at '{self.lock_path}'.") from exc

        raise LockError(  # pragma: no cover
            f"Unable to acquire context lock at '{self.lock_path}'."
        )

    def release(self) -> None:
        """Release .context/.lock if owned by this instance."""
        if self._acquired:
            self.lock_path.unlink(missing_ok=True)
            self._acquired = False

    def _read_holder_pid(self) -> int | None:
        """Read the PID from an existing lock file, returning None if corrupt/unreadable."""
        try:
            raw = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if isinstance(raw, dict) and isinstance(raw.get("pid"), int):
            return int(raw["pid"])
        return None

    def __enter__(self) -> LockMetadata:
        return self.acquire()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()
