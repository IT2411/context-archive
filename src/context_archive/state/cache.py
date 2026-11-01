"""Resilient, disposable SQLite local cache (.context/cache.sqlite) with auto-recovery."""

from __future__ import annotations

import contextlib
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CACHE_SCHEMA_VERSION = "1.0.0"


class ContextSqliteCache:
    """Local SQLite cache for file SHA-256 digests and metadata with corruption recovery."""

    def __init__(self, context_dir: Path) -> None:
        self.context_dir = context_dir
        self.db_path = context_dir / "cache.sqlite"
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """Initialize SQLite schema or recreate DB if corrupt/incompatible."""
        self.context_dir.mkdir(parents=True, exist_ok=True)
        try:
            with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS cache_meta ("
                    "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS file_cache ("
                    "path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL)"
                )
                row = conn.execute(
                    "SELECT value FROM cache_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO cache_meta (key, value) VALUES ('schema_version', ?)",
                        (CACHE_SCHEMA_VERSION,),
                    )
                elif row[0] != CACHE_SCHEMA_VERSION:
                    raise sqlite3.DatabaseError("Incompatible cache schema version")
                conn.commit()
        except sqlite3.Error:
            self._rebuild_corrupt_db()

    def _rebuild_corrupt_db(self) -> None:
        """Delete corrupt cache.sqlite and initialize a fresh database."""
        self.db_path.unlink(missing_ok=True)
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE file_cache ("
                "path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL)"
            )
            conn.execute(
                "INSERT INTO cache_meta (key, value) VALUES ('schema_version', ?)",
                (CACHE_SCHEMA_VERSION,),
            )
            conn.commit()

    def store_fingerprints(self, file_fingerprints: dict[str, str]) -> None:
        """Persist a batch of file fingerprints into cache.sqlite, recovering on error."""
        try:
            self._write_rows(file_fingerprints)
        except sqlite3.Error:
            self._rebuild_corrupt_db()
            self._write_rows(file_fingerprints)

    def _write_rows(self, file_fingerprints: dict[str, str]) -> None:
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("DELETE FROM file_cache")
            conn.executemany(
                "INSERT INTO file_cache (path, sha256, size_bytes) VALUES (?, ?, 0)",
                sorted(file_fingerprints.items()),
            )
            conn.commit()

    def load_fingerprints(self) -> dict[str, str]:
        """Read cached file fingerprints, returning empty dict and rebuilding on corruption."""
        try:
            with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
                rows = conn.execute("SELECT path, sha256 FROM file_cache").fetchall()
                return {str(r[0]): str(r[1]) for r in rows}
        except sqlite3.Error:
            self._rebuild_corrupt_db()
            return {}
