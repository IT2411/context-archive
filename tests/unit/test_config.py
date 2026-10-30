"""Unit tests for repository discovery, configuration precedence, and fingerprinting."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.config import CtxaConfig, load_config, render_default_ctxa_toml
from context_archive.exceptions import ConfigError, ExitCode
from context_archive.scanner.discovery import discover_repo_root

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_discover_repo_root_precedence(tmp_path: Path) -> None:
    """Verify upward discovery finds .ctxa.toml, pyproject.toml [tool.ctxa], .git, or fallback."""
    # 1. Fallback when no markers exist
    sub = tmp_path / "plain" / "nested"
    sub.mkdir(parents=True)
    res_fallback = discover_repo_root(sub)
    assert res_fallback.repo_root == sub.resolve()
    assert res_fallback.source == "fallback_dir"

    # 2. .git marker in parent
    git_root = tmp_path / "git_proj"
    git_nested = git_root / "src" / "pkg"
    git_nested.mkdir(parents=True)
    (git_root / ".git").mkdir()
    res_git = discover_repo_root(git_nested)
    assert res_git.repo_root == git_root.resolve()
    assert res_git.source == "git_dir"

    # 3. pyproject.toml with [tool.ctxa]
    pyproj_root = tmp_path / "pyproj"
    pyproj_nested = pyproj_root / "src"
    pyproj_nested.mkdir(parents=True)
    (pyproj_root / "pyproject.toml").write_text(
        '[project]\nname = "demo"\n[tool.ctxa.project]\nname = "demo-ctxa"\n',
        encoding="utf-8",
    )
    res_pyproj = discover_repo_root(pyproj_nested)
    assert res_pyproj.repo_root == pyproj_root.resolve()
    assert res_pyproj.source == "pyproject_toml"

    # 4. .ctxa.toml takes highest precedence
    (pyproj_root / ".ctxa.toml").write_text('[project]\nname = "override"\n', encoding="utf-8")
    res_ctxa = discover_repo_root(pyproj_nested)
    assert res_ctxa.repo_root == pyproj_root.resolve()
    assert res_ctxa.source == "ctxa_toml"


@pytest.mark.unit
def test_discover_repo_root_invalid_paths(tmp_path: Path) -> None:
    """Verify non-existent paths and file paths raise ConfigError with ExitCode.CONFIG_OR_USAGE."""
    missing = tmp_path / "does_not_exist"
    with pytest.raises(ConfigError) as exc_info:
        discover_repo_root(missing)
    assert exc_info.value.exit_code == ExitCode.CONFIG_OR_USAGE

    file_target = tmp_path / "some_file.txt"
    file_target.write_text("hello", encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info2:
        discover_repo_root(file_target)
    assert exc_info2.value.exit_code == ExitCode.CONFIG_OR_USAGE


@pytest.mark.unit
def test_config_precedence_and_pyproject_metadata(tmp_path: Path) -> None:
    """Test precedence: CLI flags > .ctxa.toml > pyproject.toml [tool.ctxa] > defaults."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "from-pep621"\ndescription = "PEP 621 desc"\n\n'
        "[tool.ctxa.scanner]\nmax_depth = 10\n"
        "[tool.ctxa.context]\ndefault_max_tokens = 4000\n",
        encoding="utf-8",
    )

    cfg_from_pyproj = load_config(tmp_path)
    assert cfg_from_pyproj.project.name == "from-pep621"
    assert cfg_from_pyproj.project.description == "PEP 621 desc"
    assert cfg_from_pyproj.scanner.max_depth == 10
    assert cfg_from_pyproj.context.default_max_tokens == 4000

    # Add .ctxa.toml to override max_depth and project name
    (tmp_path / ".ctxa.toml").write_text(
        '[project]\nname = "from-ctxa-toml"\n\n[scanner]\nmax_depth = 15\n',
        encoding="utf-8",
    )
    cfg_from_ctxa = load_config(tmp_path)
    assert cfg_from_ctxa.project.name == "from-ctxa-toml"
    assert cfg_from_ctxa.scanner.max_depth == 15
    assert cfg_from_ctxa.context.default_max_tokens == 4000

    # Apply CLI overrides
    cfg_cli = load_config(
        tmp_path,
        cli_overrides={"scanner": {"max_depth": 5}, "context": {"default_max_tokens": 9000}},
    )
    assert cfg_cli.scanner.max_depth == 5
    assert cfg_cli.context.default_max_tokens == 9000


@pytest.mark.unit
def test_config_fingerprint_stability_across_key_reordering(tmp_path: Path) -> None:
    """Verify config_fingerprint is identical regardless of TOML key or section order."""
    dir_a = tmp_path / "repo_a"
    dir_b = tmp_path / "repo_b"
    dir_a.mkdir()
    dir_b.mkdir()

    (dir_a / ".ctxa.toml").write_text(
        '[project]\nname = "alpha"\ndescription = "desc"\n'
        "[scanner]\nmax_depth = 20\nrespect_gitignore = true\n"
        "[context]\ndefault_max_tokens = 6000\n",
        encoding="utf-8",
    )
    (dir_b / ".ctxa.toml").write_text(
        "[context]\ndefault_max_tokens = 6000\n"
        "[scanner]\nrespect_gitignore = true\nmax_depth = 20\n"
        '[project]\ndescription = "desc"\nname = "alpha"\n',
        encoding="utf-8",
    )

    cfg_a = load_config(dir_a)
    cfg_b = load_config(dir_b)
    assert cfg_a.fingerprint() == cfg_b.fingerprint()
    assert cfg_a.fingerprint().startswith("sha256:")


@pytest.mark.unit
def test_invalid_config_raises_exit_code_3(tmp_path: Path) -> None:
    """Verify unknown keys, invalid types, or malformed TOML fail with exit code 3."""
    # 1. Malformed TOML syntax
    (tmp_path / ".ctxa.toml").write_text("[project\nname = broken", encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info:
        load_config(tmp_path)
    assert exc_info.value.exit_code == ExitCode.CONFIG_OR_USAGE

    # 2. Unknown configuration key (extra="forbid")
    (tmp_path / ".ctxa.toml").write_text('[project]\nunknown_key = "bad"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info2:
        load_config(tmp_path)
    assert exc_info2.value.exit_code == ExitCode.CONFIG_OR_USAGE

    # 3. Out-of-range integer value
    (tmp_path / ".ctxa.toml").write_text("[scanner]\nmax_depth = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info3:
        load_config(tmp_path)
    assert exc_info3.value.exit_code == ExitCode.CONFIG_OR_USAGE

    # 4. Non-table [tool.ctxa] in pyproject.toml
    (tmp_path / ".ctxa.toml").unlink()
    (tmp_path / "pyproject.toml").write_text('[tool]\nctxa = "not-a-table"\n', encoding="utf-8")
    with pytest.raises(ConfigError) as exc_info4:
        load_config(tmp_path)
    assert exc_info4.value.exit_code == ExitCode.CONFIG_OR_USAGE


@pytest.mark.unit
def test_render_default_ctxa_toml_roundtrip(tmp_path: Path) -> None:
    """Verify rendered default .ctxa.toml parses back into an identical CtxaConfig."""
    initial = CtxaConfig()
    rendered = render_default_ctxa_toml(initial)
    (tmp_path / ".ctxa.toml").write_text(rendered, encoding="utf-8")
    reloaded = load_config(tmp_path)
    assert reloaded.fingerprint() == initial.fingerprint()
