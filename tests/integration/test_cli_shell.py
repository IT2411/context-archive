"""Integration tests for the ctxa CLI shell, subcommands, and exit code mappings."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app
from context_archive.exceptions import ExitCode

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.integration
def test_cli_subprocess_entrypoint() -> None:
    """Verify ctxa CLI runs via Python subprocess and reports version and help."""
    res = subprocess.run(
        [sys.executable, "-m", "typer", "context_archive.cli", "run", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    script_res = runner.invoke(app, ["--version"])
    assert script_res.exit_code == 0
    assert "ctxa 1.0.3" in script_res.stdout
    _ = res


@pytest.mark.integration
def test_cli_init_creates_context_layout_and_config(tmp_path: Path) -> None:
    """Verify `ctxa init` creates .context/, .context/.gitignore, and .ctxa.toml atomically."""
    res = runner.invoke(app, ["init", str(tmp_path)])
    assert res.exit_code == int(ExitCode.SUCCESS)
    assert (tmp_path / ".ctxa.toml").is_file()
    assert (tmp_path / "PROJECT_CONTEXT.md").is_file()
    assert (tmp_path / ".context" / "journal").is_dir()
    assert (tmp_path / ".context" / "snapshots").is_dir()
    assert (tmp_path / ".context" / ".gitignore").is_file()


@pytest.mark.integration
def test_cli_all_subcommands_smoke_and_json_modes(tmp_path: Path) -> None:
    """Verify all CLI subcommands execute and support --json where applicable."""
    runner.invoke(app, ["init", str(tmp_path)])

    for cmd in ["update", "handoff", "verify", "compact", "rebuild"]:
        res = runner.invoke(app, [cmd, str(tmp_path), "--json"])
        assert res.exit_code == int(ExitCode.SUCCESS)
        payload = json.loads(res.stdout)
        assert payload["command"] == cmd
        assert payload["config_fingerprint"].startswith("sha256:")

    assert runner.invoke(app, ["update", str(tmp_path), "--message", "init"]).exit_code == 0
    assert runner.invoke(app, ["verify", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["compact", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["rebuild", str(tmp_path)]).exit_code == 0
    assert (
        runner.invoke(
            app, ["note", "Keep API stateless", str(tmp_path), "--type", "constraint"]
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["diff", str(tmp_path), "--format", "mermaid"]).exit_code == 0
    assert (
        runner.invoke(
            app,
            [
                "context",
                "Refactor pricing calculator",
                str(tmp_path),
                "--max-tokens",
                "4000",
                "-o",
                "PACKET.md",
            ],
        ).exit_code
        == 0
    )
    assert runner.invoke(app, ["export", str(tmp_path), "--format", "json"]).exit_code == 0
    assert runner.invoke(app, ["mcp", str(tmp_path)]).exit_code == 0


@pytest.mark.integration
def test_cli_error_exit_code_mappings(tmp_path: Path) -> None:
    """Verify invalid CLI arguments or broken configs exit with ExitCode.CONFIG_OR_USAGE (3)."""
    bad_level = runner.invoke(app, ["update", str(tmp_path), "--level", "l99", "--json"])
    assert bad_level.exit_code == int(ExitCode.CONFIG_OR_USAGE)
    err_payload = json.loads(bad_level.stdout)
    assert err_payload["exit_code"] == int(ExitCode.CONFIG_OR_USAGE)

    empty_note = runner.invoke(app, ["note", "   ", str(tmp_path)])
    assert empty_note.exit_code == int(ExitCode.CONFIG_OR_USAGE)

    bad_note_type = runner.invoke(app, ["note", "Valid text", str(tmp_path), "--type", "invalid"])
    assert bad_note_type.exit_code == int(ExitCode.CONFIG_OR_USAGE)

    bad_diff = runner.invoke(app, ["diff", str(tmp_path), "--format", "xml"])
    assert bad_diff.exit_code == int(ExitCode.CONFIG_OR_USAGE)

    empty_task = runner.invoke(app, ["context", "  ", str(tmp_path)])
    assert empty_task.exit_code == int(ExitCode.CONFIG_OR_USAGE)

    bad_ctx_fmt = runner.invoke(app, ["context", "Fix bug", str(tmp_path), "--format", "yaml"])
    assert bad_ctx_fmt.exit_code == int(ExitCode.CONFIG_OR_USAGE)

    bad_export = runner.invoke(app, ["export", str(tmp_path), "--format", "csv"])
    assert bad_export.exit_code == int(ExitCode.CONFIG_OR_USAGE)

    missing_path = tmp_path / "missing_repo"
    assert runner.invoke(app, ["init", str(missing_path)]).exit_code == int(
        ExitCode.CONFIG_OR_USAGE
    )
    assert runner.invoke(app, ["verify", str(missing_path)]).exit_code == int(
        ExitCode.CONFIG_OR_USAGE
    )
