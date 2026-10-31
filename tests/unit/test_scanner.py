"""Unit tests for the safe repository scanner, secret filtering, and edge cases."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.config import CtxaConfig, ScannerConfig, load_config
from context_archive.scanner.walker import scan_repository

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_zero_execution_security_guarantee(tmp_path: Path) -> None:
    """Verify scanning a file with top-level RuntimeError inventories it without executing."""
    poison_file = tmp_path / "poison.py"
    poison_file.write_text(
        'raise RuntimeError("EXECUTED_UNTRUSTED_CODE")\n',
        encoding="utf-8",
    )

    cfg = load_config(tmp_path)
    report = scan_repository(tmp_path, cfg)

    paths = {f.path: f for f in report.files}
    assert "poison.py" in paths
    assert paths["poison.py"].category == "source_code"
    assert paths["poison.py"].language == "python"
    assert report.summary.files_analyzed == 1


@pytest.mark.unit
def test_secret_exclusion_and_env_example_allowlist(tmp_path: Path) -> None:
    """Verify .env, .env.production, *.pem, *.key, id_rsa, and credentials.json are excluded."""
    (tmp_path / ".env").write_text("SECRET=123", encoding="utf-8")
    (tmp_path / ".env.production").write_text("PROD_SECRET=456", encoding="utf-8")
    (tmp_path / ".env.example").write_text("SECRET=placeholder", encoding="utf-8")
    (tmp_path / "server.pem").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    (tmp_path / "private.key").write_text("PRIVATE_KEY_DATA", encoding="utf-8")
    (tmp_path / "id_rsa").write_text("SSH_PRIVATE_KEY", encoding="utf-8")
    (tmp_path / "aws_credentials.json").write_text('{"key": "secret"}', encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")

    cfg = load_config(tmp_path)
    report = scan_repository(tmp_path, cfg)

    scanned_paths = {f.path for f in report.files}
    assert "app.py" in scanned_paths
    assert ".env.example" in scanned_paths

    # None of the secret files may appear in scanned_files
    for secret_name in (
        ".env",
        ".env.production",
        "server.pem",
        "private.key",
        "id_rsa",
        "aws_credentials.json",
    ):
        assert secret_name not in scanned_paths

    # Verify secret contents never leak into serialized report JSON
    serialized = report.model_dump_json()
    assert "PROD_SECRET" not in serialized
    assert "BEGIN PRIVATE KEY" not in serialized


@pytest.mark.unit
def test_symlink_escape_and_cycle_detection(tmp_path: Path) -> None:
    """Verify out-of-tree symlinks, directory cycles, and broken symlinks are safely blocked."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_secret = outside_dir / "external_secret.txt"
    outside_secret.write_text("TOP_SECRET_EXTERNAL", encoding="utf-8")

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")

    # 1. Symlink escaping outside repo_root
    (repo_dir / "escape_link.py").symlink_to(outside_secret)

    # 2. Circular directory symlink
    sub_dir = repo_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "loop_to_root").symlink_to(repo_dir, target_is_directory=True)

    # 3. Broken symlink
    (repo_dir / "broken_link.py").symlink_to(repo_dir / "non_existent_target.py")

    cfg = load_config(repo_dir)
    report = scan_repository(repo_dir, cfg)

    scanned_paths = {f.path for f in report.files}
    assert scanned_paths == {"main.py"}

    diag_codes = {d.code for d in report.diagnostics}
    assert "symlink_escape_blocked" in diag_codes
    assert "symlink_cycle_detected" in diag_codes
    assert "broken_symlink" in diag_codes


@pytest.mark.unit
def test_binary_and_invalid_utf8_files_skipped_cleanly(tmp_path: Path) -> None:
    """Verify null-byte binary files and invalid UTF-8 files with .py extensions do not crash."""
    (tmp_path / "binary_masquerade.py").write_bytes(b"\x00\x01\x02BINARY_DATA")
    (tmp_path / "bad_utf8.py").write_bytes(b"def foo():\n    return '\xff\xfe\xfd'\n")
    (tmp_path / "clean.py").write_text("def clean() -> int:\n    return 42\n", encoding="utf-8")

    cfg = load_config(tmp_path)
    report = scan_repository(tmp_path, cfg)

    scanned_paths = {f.path for f in report.files}
    assert scanned_paths == {"clean.py"}
    assert report.summary.files_failed == 2

    diag_codes = {d.code for d in report.diagnostics}
    assert "binary_file_skipped" in diag_codes
    assert "invalid_utf8_encoding" in diag_codes


@pytest.mark.unit
def test_gitignore_max_size_max_depth_and_concurrent_modification(tmp_path: Path) -> None:
    """Verify .gitignore rules, max_file_size_bytes, max_depth, and mid-scan mutation detection."""
    (tmp_path / ".gitignore").write_text("ignored_dir/\n*.log\n", encoding="utf-8")
    ignored_dir = tmp_path / "ignored_dir"
    ignored_dir.mkdir()
    (ignored_dir / "skip.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "debug.log").write_text("log line\n", encoding="utf-8")

    # Large file exceeding 2048 bytes
    (tmp_path / "huge.py").write_text("x = 1\n" * 600, encoding="utf-8")

    # Deeply nested directory exceeding max_depth=2
    deep_dir = tmp_path / "d1" / "d2" / "d3"
    deep_dir.mkdir(parents=True)
    (deep_dir / "too_deep.py").write_text("y = 2\n", encoding="utf-8")

    # File that mutates mid-scan
    mutating_file = tmp_path / "mutating.py"
    mutating_file.write_text("initial = 1\n", encoding="utf-8")

    def _mutate_during_read(target: Path) -> None:
        if target.name == "mutating.py":
            target.write_text("modified_during_read = 22222\n", encoding="utf-8")

    cfg = CtxaConfig(
        scanner=ScannerConfig(max_file_size_bytes=2048, max_depth=2, respect_gitignore=True)
    )
    report = scan_repository(tmp_path, cfg, mid_read_hook=_mutate_during_read)

    scanned_paths = {f.path for f in report.files}
    assert "ignored_dir/skip.py" not in scanned_paths
    assert "debug.log" not in scanned_paths
    assert "huge.py" not in scanned_paths
    assert "d1/d2/d3/too_deep.py" not in scanned_paths
    assert "mutating.py" not in scanned_paths

    diag_codes = {d.code for d in report.diagnostics}
    assert "file_too_large" in diag_codes
    assert "max_depth_exceeded" in diag_codes
    assert "concurrently_modified" in diag_codes
