"""Safe, zero-execution repository file walker with secret and binary filtering."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

import pathspec

from context_archive.git.state import compute_repository_id, extract_git_state
from context_archive.scanner.report import (
    FileCategory,
    ScanDiagnostic,
    ScannedFile,
    ScanReport,
    ScanSummary,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from context_archive.config import CtxaConfig

BINARY_SNIFF_BYTES = 8192

LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
}

MANIFEST_FILENAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "poetry.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "requirements.txt",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        "Dockerfile",
    }
)

CONFIG_SUFFIXES: frozenset[str] = frozenset({".toml", ".yaml", ".yml", ".json", ".ini", ".cfg"})
DOC_SUFFIXES: frozenset[str] = frozenset({".md", ".rst", ".txt"})


def _build_pathspec(patterns: list[str]) -> pathspec.PathSpec:
    """Compile gitwildmatch patterns into a PathSpec matcher."""
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def _load_ignore_patterns(repo_root: Path, *, respect_gitignore: bool) -> list[str]:
    """Load ignore rules from .gitignore and .ignore if enabled."""
    patterns: list[str] = []
    if not respect_gitignore:
        return patterns

    for ignore_name in (".gitignore", ".ignore"):
        ignore_path = repo_root / ignore_name
        if ignore_path.is_file():
            try:
                lines = ignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
                patterns.extend(lines)
            except OSError:
                continue
    return patterns


def _is_test_path(rel_posix: str, filename: str) -> bool:
    """Return True if a source file belongs to a test suite."""
    parts = rel_posix.split("/")
    if "tests" in parts or "test" in parts or "__tests__" in parts:
        return True
    stem = Path(filename).stem
    return (
        stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith(".test")
        or stem.endswith(".spec")
    )


def _classify_file(rel_posix: str) -> tuple[FileCategory, str | None]:
    """Classify a non-excluded text file into a FileCategory and optional language."""
    path_obj = Path(rel_posix)
    filename = path_obj.name
    suffix = path_obj.suffix.lower()

    if filename in MANIFEST_FILENAMES:
        return "manifest", None

    if suffix in LANGUAGE_BY_SUFFIX:
        lang = LANGUAGE_BY_SUFFIX[suffix]
        if _is_test_path(rel_posix, filename):
            return "test", lang
        return "source_code", lang

    if filename.startswith(".env.") or suffix in CONFIG_SUFFIXES:
        return "config", None

    if suffix in DOC_SUFFIXES:
        return "documentation", None

    return "unsupported", None


def _read_and_hash_file(
    file_path: Path,
    *,
    max_bytes: int,
    on_Progress_hook: Callable[[Path], None] | None = None,
) -> tuple[str | None, int, ScanDiagnostic | None]:
    """Safely read a file, detect binary/encoding/concurrent edits, and return SHA-256."""
    rel_name = file_path.name
    for attempt in range(2):
        try:
            stat_before = file_path.stat()
        except OSError as exc:
            return (
                None,
                0,
                ScanDiagnostic(
                    code="file_stat_error",
                    severity="warning",
                    message=f"Unable to stat '{rel_name}': {exc}",
                ),
            )

        if stat_before.st_size > max_bytes:
            return (
                None,
                stat_before.st_size,
                ScanDiagnostic(
                    code="file_too_large",
                    severity="info",
                    message=(
                        f"Skipped file exceeding max_file_size_bytes "
                        f"({stat_before.st_size} > {max_bytes})."
                    ),
                ),
            )

        hasher = hashlib.sha256()
        first_chunk: bytes | None = None
        total_read = 0

        try:
            with file_path.open("rb") as handle:
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    if first_chunk is None:
                        first_chunk = chunk[:BINARY_SNIFF_BYTES]
                        if b"\x00" in first_chunk:
                            return (
                                None,
                                stat_before.st_size,
                                ScanDiagnostic(
                                    code="binary_file_skipped",
                                    severity="warning",
                                    message="Skipped binary file containing null bytes.",
                                ),
                            )
                    total_read += len(chunk)
                    if total_read > max_bytes:
                        return (
                            None,
                            total_read,
                            ScanDiagnostic(
                                code="file_too_large",
                                severity="info",
                                message="File grew beyond max_file_size_bytes during read.",
                            ),
                        )
                    hasher.update(chunk)
                    if on_Progress_hook is not None:
                        on_Progress_hook(file_path)

            if first_chunk is not None:
                try:
                    first_chunk.decode("utf-8")
                except UnicodeDecodeError:
                    return (
                        None,
                        stat_before.st_size,
                        ScanDiagnostic(
                            code="invalid_utf8_encoding",
                            severity="warning",
                            message="Skipped file with non-UTF-8 byte sequence.",
                        ),
                    )

            stat_after = file_path.stat()
        except OSError as exc:
            return (
                None,
                0,
                ScanDiagnostic(
                    code="file_read_error",
                    severity="warning",
                    message=f"Failed reading file: {exc}",
                ),
            )

        if (
            stat_before.st_mtime_ns == stat_after.st_mtime_ns
            and stat_before.st_size == stat_after.st_size
        ):
            return f"sha256:{hasher.hexdigest()}", total_read, None

        if attempt == 1:
            return (
                None,
                stat_after.st_size,
                ScanDiagnostic(
                    code="concurrently_modified",
                    severity="warning",
                    message="File was modified concurrently during active scan.",
                ),
            )

    return None, 0, None  # pragma: no cover


def scan_repository(
    repo_root: Path,
    config: CtxaConfig,
    *,
    mid_read_hook: Callable[[Path], None] | None = None,
) -> ScanReport:
    """Safely walk and inventory a repository without executing any repository code."""
    resolved_root = repo_root.resolve()
    exclude_patterns = list(config.scanner.exclude_globs) + _load_ignore_patterns(
        resolved_root,
        respect_gitignore=config.scanner.respect_gitignore,
    )
    exclude_spec = _build_pathspec(exclude_patterns)
    secret_spec = _build_pathspec(list(config.scanner.secret_globs))
    self_managed_files = {
        config.context.output_path,
        f"{config.context.output_path}.bak",
        "PROJECT_CONTEXT.md",
        "PROJECT_CONTEXT.md.bak",
    }

    visited_dirs: set[tuple[int, int]] = set()
    try:
        root_stat = resolved_root.stat()
        visited_dirs.add((root_stat.st_dev, root_stat.st_ino))
    except OSError:
        pass

    scanned_files: list[ScannedFile] = []
    diagnostics: list[ScanDiagnostic] = []

    files_discovered = 0
    files_analyzed = 0
    files_excluded = 0
    files_failed = 0
    unsupported_files = 0

    def _walk_dir(current_dir: Path, depth: int) -> None:
        nonlocal files_discovered, files_analyzed, files_excluded, files_failed, unsupported_files

        if depth > config.scanner.max_depth:
            rel_dir = current_dir.relative_to(resolved_root).as_posix()
            diagnostics.append(
                ScanDiagnostic(
                    code="max_depth_exceeded",
                    severity="warning",
                    message=f"Directory exceeded max_depth ({config.scanner.max_depth}).",
                    source_path=rel_dir,
                )
            )
            return

        try:
            entries = sorted(current_dir.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            rel_dir = (
                current_dir.relative_to(resolved_root).as_posix()
                if current_dir != resolved_root
                else "."
            )
            diagnostics.append(
                ScanDiagnostic(
                    code="directory_access_error",
                    severity="warning",
                    message=f"Cannot list directory: {exc}",
                    source_path=rel_dir,
                )
            )
            return

        for entry in entries:
            rel_posix = entry.relative_to(resolved_root).as_posix()

            # Skip ctxa's own output artifacts so repeated runs are 100% idempotent
            if rel_posix in self_managed_files:
                continue

            if entry.is_symlink():
                try:
                    resolved_target = entry.resolve(strict=True)
                except OSError:
                    files_failed += 1
                    diagnostics.append(
                        ScanDiagnostic(
                            code="broken_symlink",
                            severity="warning",
                            message="Skipped broken or cyclic symbolic link.",
                            source_path=rel_posix,
                        )
                    )
                    continue

                if not resolved_target.is_relative_to(resolved_root):
                    files_excluded += 1
                    diagnostics.append(
                        ScanDiagnostic(
                            code="symlink_escape_blocked",
                            severity="warning",
                            message="Blocked symbolic link resolving outside repository root.",
                            source_path=rel_posix,
                        )
                    )
                    continue

            try:
                is_dir = entry.is_dir()
            except OSError:
                continue

            if is_dir:
                dir_match_path = f"{rel_posix}/"
                if exclude_spec.match_file(rel_posix) or exclude_spec.match_file(dir_match_path):
                    continue
                if secret_spec.match_file(rel_posix) or secret_spec.match_file(dir_match_path):
                    files_excluded += 1
                    continue

                try:
                    dir_stat = entry.stat()
                except OSError:
                    continue

                inode_key = (dir_stat.st_dev, dir_stat.st_ino)
                if inode_key in visited_dirs:
                    diagnostics.append(
                        ScanDiagnostic(
                            code="symlink_cycle_detected",
                            severity="warning",
                            message="Skipped directory symlink cycle.",
                            source_path=rel_posix,
                        )
                    )
                    continue

                visited_dirs.add(inode_key)
                _walk_dir(entry, depth + 1)
                continue

            if not entry.is_file():
                continue

            files_discovered += 1

            # 1. Secret exclusion check (highest security priority)
            if secret_spec.match_file(rel_posix):
                files_excluded += 1
                diagnostics.append(
                    ScanDiagnostic(
                        code="secret_excluded",
                        severity="info",
                        message="Excluded file matching secret/credential protection pattern.",
                        source_path=rel_posix,
                    )
                )
                continue

            # 2. Standard ignore/exclude check
            if exclude_spec.match_file(rel_posix):
                files_excluded += 1
                continue

            # 3. Read, validate UTF-8/non-binary, and compute SHA-256
            digest, size_bytes, diag = _read_and_hash_file(
                entry,
                max_bytes=config.scanner.max_file_size_bytes,
                on_Progress_hook=mid_read_hook,
            )
            if diag is not None:
                diagnostics.append(
                    ScanDiagnostic(
                        code=diag.code,
                        severity=diag.severity,
                        message=diag.message,
                        source_path=rel_posix,
                    )
                )
                if diag.code in ("file_too_large",):
                    files_excluded += 1
                else:
                    files_failed += 1
                continue

            if digest is None:  # pragma: no cover
                files_failed += 1
                continue

            category, language = _classify_file(rel_posix)
            if category == "unsupported":
                unsupported_files += 1
            else:
                files_analyzed += 1

            scanned_files.append(
                ScannedFile(
                    path=rel_posix,
                    category=category,
                    language=language,
                    size_bytes=size_bytes,
                    sha256=digest,
                )
            )

    _walk_dir(resolved_root, 1)

    git_state = extract_git_state(resolved_root)
    repo_id = compute_repository_id(resolved_root, project_name=config.project.name)

    scanned_files.sort(key=lambda f: f.path)
    diagnostics.sort(key=lambda d: (d.source_path or "", d.code))

    return ScanReport(
        repository_id=repo_id,
        repo_root=resolved_root.as_posix(),
        config_fingerprint=config.fingerprint(),
        git_state=git_state,
        summary=ScanSummary(
            files_discovered=files_discovered,
            files_analyzed=files_analyzed,
            files_excluded=files_excluded,
            files_failed=files_failed,
            unsupported_files=unsupported_files,
        ),
        files=tuple(scanned_files),
        diagnostics=tuple(diagnostics),
    )
