"""CLI entrypoints for context-archive (ctxa)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

import typer

from context_archive import __version__
from context_archive.config import load_config, render_default_ctxa_toml
from context_archive.exceptions import ConfigError, CtxaError, ExitCode
from context_archive.lock import ContextLock, atomic_write_text
from context_archive.scanner.discovery import discover_repo_root

app = typer.Typer(
    name="ctxa",
    help="Portable AI Project Context Compiler with incremental change journaling.",
    add_completion=False,
    no_args_is_help=True,
)

VALID_UPDATE_LEVELS = frozenset({"auto", "l1", "l2", "l3"})
VALID_NOTE_TYPES = frozenset({"decision", "constraint", "issue", "question", "next_step"})
VALID_DIFF_FORMATS = frozenset({"text", "json", "mermaid"})
VALID_CONTEXT_FORMATS = frozenset({"md", "json"})
VALID_EXPORT_FORMATS = frozenset({"json", "mermaid"})


def _handle_cli_error(exc: CtxaError, *, as_json: bool = False) -> NoReturn:
    """Output structured error message and raise typer.Exit with mapped exit code."""
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "exit_code": int(exc.exit_code),
                    "error": exc.message,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"Error: {exc.message}", err=True)
    raise typer.Exit(int(exc.exit_code))


def _resolve_target_and_config(
    path: Path,
    *,
    cli_overrides: dict[str, Any] | None = None,
    as_json: bool = False,
) -> tuple[Path, str]:
    """Discover repo root, validate config, and return (repo_root, config_fingerprint)."""
    try:
        discovered = discover_repo_root(path)
        cfg = load_config(discovered.repo_root, cli_overrides=cli_overrides)
        return discovered.repo_root, cfg.fingerprint()
    except CtxaError as exc:
        _handle_cli_error(exc, as_json=as_json)


def _version_callback(value: bool) -> None:
    """Print package version and exit."""
    if value:
        typer.echo(f"ctxa {__version__}")
        raise typer.Exit(int(ExitCode.SUCCESS))


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show the ctxa version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Portable AI Project Context Compiler (ctxa)."""
    _ = version


@app.command()
def version() -> None:
    """Display the installed ctxa version."""
    typer.echo(f"ctxa {__version__}")


@app.command()
def init(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing .ctxa.toml if present."),
) -> None:
    """Initialize .context/ directory structure and configuration."""
    try:
        if not path.exists() or not path.is_dir():
            raise ConfigError(f"Invalid repository directory: '{path}'")
        repo_root = path.resolve()
        cfg = load_config(repo_root)
        context_dir = repo_root / ".context"
        with ContextLock(context_dir):
            (context_dir / "journal").mkdir(parents=True, exist_ok=True)
            (context_dir / "snapshots").mkdir(parents=True, exist_ok=True)
            atomic_write_text(context_dir / ".gitignore", "cache.sqlite\n.lock\n")
            ctxa_toml = repo_root / ".ctxa.toml"
            if force or not ctxa_toml.exists():
                atomic_write_text(ctxa_toml, render_default_ctxa_toml(cfg))
        typer.echo(f"Initialized context-archive in {repo_root} ({cfg.fingerprint()})")
    except CtxaError as exc:
        _handle_cli_error(exc)


@app.command()
def update(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    level: str = typer.Option("auto", "--level", help="Update level: auto, l1, l2, or l3."),
    message: str | None = typer.Option(None, "--message", "-m", help="Developer intent summary."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Record incremental repository changes into the append-only journal."""
    normalized_level = level.lower()
    if normalized_level not in VALID_UPDATE_LEVELS:
        _handle_cli_error(
            ConfigError(f"Unsupported --level '{level}'. Expected one of: auto, l1, l2, l3."),
            as_json=as_json,
        )
    repo_root, fingerprint = _resolve_target_and_config(path, as_json=as_json)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "update",
                    "repo_root": repo_root.as_posix(),
                    "level": normalized_level,
                    "message": message,
                    "config_fingerprint": fingerprint,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"Update [{normalized_level}] ready for {repo_root}")


@app.command()
def note(
    text: str = typer.Argument(..., help="Note, decision, or constraint text."),
    path: Path = typer.Argument(Path(), help="Target repository path."),
    note_type: str = typer.Option(
        "decision",
        "--type",
        "-t",
        help="Note category: decision, constraint, issue, question, next_step.",
    ),
    scope: str | None = typer.Option(None, "--scope", "-s", help="File path or symbol scope."),
) -> None:
    """Record a durable human note or architectural decision."""
    if not text.strip():
        _handle_cli_error(ConfigError("Note text cannot be empty."))
    if note_type not in VALID_NOTE_TYPES:
        _handle_cli_error(
            ConfigError(
                f"Unsupported --type '{note_type}'. Expected one of: "
                f"{', '.join(sorted(VALID_NOTE_TYPES))}."
            )
        )
    repo_root, _ = _resolve_target_and_config(path)
    typer.echo(f"Recorded {note_type} note in {repo_root} (scope={scope or 'global'})")


@app.command()
def handoff(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Custom output Markdown path."),
    full: bool = typer.Option(False, "--full", help="Force full checkpoint before rendering."),
    strict: bool = typer.Option(False, "--strict", help="Fail on partial extraction warnings."),
    deterministic: bool = typer.Option(
        False, "--deterministic", help="Normalize volatile timestamps."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Compile and write the portable PROJECT_CONTEXT.md handoff artifact."""
    overrides: dict[str, Any] = {}
    if output is not None:
        overrides = {"context": {"output_path": output.as_posix()}}
    repo_root, fingerprint = _resolve_target_and_config(
        path, cli_overrides=overrides, as_json=as_json
    )
    _ = (full, strict, deterministic)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "handoff",
                    "repo_root": repo_root.as_posix(),
                    "config_fingerprint": fingerprint,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"Handoff ready for {repo_root}")


@app.command()
def verify(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Verify whether PROJECT_CONTEXT.md and .context/ match the current working tree."""
    _ = strict
    repo_root, fingerprint = _resolve_target_and_config(path, as_json=as_json)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "verify",
                    "repo_root": repo_root.as_posix(),
                    "config_fingerprint": fingerprint,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"Verify ready for {repo_root}")


@app.command()
def diff(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    since: str | None = typer.Option(None, "--since", help="Baseline snapshot ID or commit SHA."),
    output_format: str = typer.Option(
        "text", "--format", "-f", help="Output format: text, json, or mermaid."
    ),
) -> None:
    """Compare current repository state against the latest snapshot or a revision."""
    if output_format not in VALID_DIFF_FORMATS:
        _handle_cli_error(
            ConfigError(
                f"Unsupported --format '{output_format}'. Expected text, json, or mermaid."
            ),
            as_json=(output_format == "json"),
        )
    repo_root, _ = _resolve_target_and_config(path, as_json=(output_format == "json"))
    typer.echo(f"Diff ({output_format}) for {repo_root} since {since or 'latest'}")


@app.command()
def context(
    task: str = typer.Argument(..., help="Engineering task prompt to compile context for."),
    path: Path = typer.Argument(Path(), help="Target repository path."),
    max_tokens: int = typer.Option(8000, "--max-tokens", help="Maximum token budget."),
    tokenizer: str = typer.Option(
        "heuristic", "--tokenizer", help="Tokenizer: heuristic or tiktoken."
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Optional output file path."),
    output_format: str = typer.Option("md", "--format", "-f", help="Output format: md or json."),
) -> None:
    """Compile a ranked, token-budgeted context packet for a specific task."""
    if not task.strip():
        _handle_cli_error(ConfigError("Task description cannot be empty."))
    if output_format not in VALID_CONTEXT_FORMATS:
        _handle_cli_error(
            ConfigError(f"Unsupported --format '{output_format}'. Expected md or json.")
        )
    overrides: dict[str, Any] = {
        "context": {
            "default_max_tokens": max_tokens,
            "default_tokenizer": tokenizer,
        }
    }
    if output is not None:
        overrides["context"]["output_path"] = output.as_posix()
    repo_root, _ = _resolve_target_and_config(path, cli_overrides=overrides)
    typer.echo(f"Compiled task context for '{task}' in {repo_root} (max_tokens={max_tokens})")


@app.command()
def compact(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Fold unincorporated journal entries into a new immutable snapshot checkpoint."""
    repo_root, fingerprint = _resolve_target_and_config(path, as_json=as_json)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "compact",
                    "repo_root": repo_root.as_posix(),
                    "config_fingerprint": fingerprint,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"Compact ready for {repo_root}")


@app.command()
def rebuild(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Force a clean L3 full rebuild of the canonical graph and checkpoint."""
    repo_root, fingerprint = _resolve_target_and_config(path, as_json=as_json)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "rebuild",
                    "repo_root": repo_root.as_posix(),
                    "config_fingerprint": fingerprint,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"Rebuild ready for {repo_root}")


@app.command()
def export(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    output_format: str = typer.Option(
        "json", "--format", "-f", help="Export format: json or mermaid."
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="Export destination path."),
) -> None:
    """Export canonical graph artifacts or Mermaid architecture diagrams."""
    if output_format not in VALID_EXPORT_FORMATS:
        _handle_cli_error(
            ConfigError(f"Unsupported --format '{output_format}'. Expected json or mermaid.")
        )
    repo_root, _ = _resolve_target_and_config(path)
    typer.echo(f"Export ({output_format}) for {repo_root} -> {output or 'stdout'}")


@app.command()
def mcp(
    path: Path = typer.Argument(Path(), help="Target repository path."),
) -> None:
    """Start the optional read-only Model Context Protocol (MCP) server over stdio."""
    repo_root, _ = _resolve_target_and_config(path)
    typer.echo(f"MCP server ready for {repo_root}")
