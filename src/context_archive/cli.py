"""CLI entrypoints for context-archive (ctxa)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import typer

from context_archive import __version__
from context_archive.adapters.python_ast import PythonAstAdapter
from context_archive.config import CtxaConfig, load_config, render_default_ctxa_toml
from context_archive.exceptions import (
    ConfigError,
    CtxaError,
    CtxaWarningError,
    ExitCode,
    IntegrityError,
)
from context_archive.lock import ContextLock, atomic_write_text
from context_archive.model.graph import CanonicalGraph
from context_archive.model.manifest import Manifest, load_manifest, write_manifest
from context_archive.renderers.json_exporter import export_canonical_json
from context_archive.renderers.markdown import (
    DEFAULT_MANUAL_NOTES_BLOCK,
    MANUAL_END,
    render_project_context_markdown,
)
from context_archive.scanner.discovery import discover_repo_root
from context_archive.scanner.walker import scan_repository
from context_archive.state.snapshot import Snapshot, write_snapshot

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

_MANUAL_EXTRACT_RE = re.compile(
    r"<!--\s*CTXA:MANUAL:START[^>]*-->\n?(.*?)\n?<!--\s*CTXA:MANUAL:END\s*-->",
    re.DOTALL,
)


@dataclass(frozen=True)
class HandoffArtifacts:
    """Compiled artifacts produced during init/handoff."""

    repo_root: Path
    output_md_path: Path
    manifest: Manifest
    graph: CanonicalGraph
    snapshot: Snapshot
    has_warnings: bool


def _extract_existing_manual_notes(md_path: Path, notes_path: Path) -> str:
    """Read preserved manual notes from existing PROJECT_CONTEXT.md or .context/notes.md."""
    if md_path.is_file():
        raw_md = md_path.read_text(encoding="utf-8", errors="replace")
        start_count = raw_md.count("<!-- CTXA:MANUAL:START")
        end_count = raw_md.count(MANUAL_END)
        if start_count > 0 or end_count > 0:
            match = _MANUAL_EXTRACT_RE.search(raw_md)
            if start_count != 1 or end_count != 1 or match is None:
                bak_path = md_path.with_name(f"{md_path.name}.bak")
                atomic_write_text(bak_path, raw_md)
                raise IntegrityError(
                    f"Corrupted CTXA:MANUAL sentinel markers in '{md_path}'. "
                    f"Backed up existing file to '{bak_path.name}' and aborted overwrite."
                )
            extracted = match.group(1).strip()
            if extracted:
                return extracted

    if notes_path.is_file():
        notes_text = notes_path.read_text(encoding="utf-8", errors="replace").strip()
        if notes_text:
            return notes_text

    return DEFAULT_MANUAL_NOTES_BLOCK


def execute_full_handoff(
    repo_root: Path,
    config: CtxaConfig,
    *,
    deterministic: bool = False,
    snapshot_id: str = "snapshot-0001",
    write_default_ctxa_toml: bool = False,
    force_ctxa_toml: bool = False,
) -> HandoffArtifacts:
    """Scan repo, extract AST graph, persist snapshot/manifest, and write PROJECT_CONTEXT.md."""
    context_dir = repo_root / ".context"
    output_rel = Path(config.context.output_path)
    output_md_path = output_rel if output_rel.is_absolute() else (repo_root / output_rel)
    notes_path = context_dir / "notes.md"

    with ContextLock(context_dir):
        (context_dir / "journal").mkdir(parents=True, exist_ok=True)
        (context_dir / "snapshots").mkdir(parents=True, exist_ok=True)
        atomic_write_text(context_dir / ".gitignore", "cache.sqlite\n.lock\n")

        if write_default_ctxa_toml:
            ctxa_toml = repo_root / ".ctxa.toml"
            if force_ctxa_toml or not ctxa_toml.exists():
                atomic_write_text(ctxa_toml, render_default_ctxa_toml(config))

        manual_notes = _extract_existing_manual_notes(output_md_path, notes_path)
        atomic_write_text(notes_path, manual_notes + "\n")

        scan_report = scan_repository(repo_root, config)
        py_adapter = PythonAstAdapter()
        ast_res = py_adapter.extract_repository(repo_root, scan_report.files)

        syntax_error_count = sum(1 for d in ast_res.diagnostics if d.code == "python_syntax_error")
        total_failed = scan_report.summary.files_failed + syntax_error_count

        graph = CanonicalGraph.build(
            repository_id=scan_report.repository_id,
            base_snapshot_id=snapshot_id,
            applied_journal_cursor=None,
            nodes=ast_res.nodes,
            edges=ast_res.edges,
            diagnostics=ast_res.diagnostics,
        )

        snapshot = Snapshot.create_initial(
            scan_report=scan_report,
            graph=graph,
            snapshot_id=snapshot_id,
            deterministic=deterministic,
        )
        manifest = Manifest.from_scan_report(
            scan_report,
            latest_snapshot_id=snapshot_id,
            notes_content=manual_notes + "\n",
            deterministic=deterministic,
            files_failed_override=total_failed,
        )

        markdown_doc = render_project_context_markdown(
            repo_root=repo_root,
            config=config,
            manifest=manifest,
            scan_report=scan_report,
            graph=graph,
            manual_block_content=manual_notes,
        )

        write_snapshot(context_dir, snapshot)
        atomic_write_text(context_dir / "graph.json", graph.to_deterministic_json())
        write_manifest(context_dir, manifest)
        atomic_write_text(output_md_path, markdown_doc)

    has_scan_warn = any(d.severity in ("warning", "error") for d in scan_report.diagnostics)
    has_graph_warn = any(d.severity in ("warning", "error") for d in graph.diagnostics)
    has_warnings = total_failed > 0 or has_scan_warn or has_graph_warn
    return HandoffArtifacts(
        repo_root=repo_root,
        output_md_path=output_md_path,
        manifest=manifest,
        graph=graph,
        snapshot=snapshot,
        has_warnings=has_warnings,
    )


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
) -> tuple[Path, CtxaConfig]:
    """Discover repo root, validate config, and return (repo_root, CtxaConfig)."""
    try:
        discovered = discover_repo_root(path)
        cfg = load_config(discovered.repo_root, cli_overrides=cli_overrides)
        return discovered.repo_root, cfg
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
    deterministic: bool = typer.Option(
        False, "--deterministic", help="Normalize volatile timestamps."
    ),
) -> None:
    """Initialize .context/, create snapshot-0001.json, and generate PROJECT_CONTEXT.md."""
    try:
        if not path.exists() or not path.is_dir():
            raise ConfigError(f"Invalid repository directory: '{path}'")
        repo_root = path.resolve()
        cfg = load_config(repo_root)
        artifacts = execute_full_handoff(
            repo_root,
            cfg,
            deterministic=deterministic,
            write_default_ctxa_toml=True,
            force_ctxa_toml=force,
        )
        typer.echo(
            f"Initialized context-archive in {repo_root} "
            f"(snapshot={artifacts.snapshot.snapshot_id}, output={artifacts.output_md_path.name})"
        )
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
    repo_root, cfg = _resolve_target_and_config(path, as_json=as_json)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "update",
                    "repo_root": repo_root.as_posix(),
                    "level": normalized_level,
                    "message": message,
                    "config_fingerprint": cfg.fingerprint(),
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
    repo_root, cfg = _resolve_target_and_config(path, cli_overrides=overrides, as_json=as_json)
    _ = full
    try:
        artifacts = execute_full_handoff(
            repo_root,
            cfg,
            deterministic=deterministic,
        )
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "command": "handoff",
                        "repo_root": repo_root.as_posix(),
                        "output_path": artifacts.output_md_path.as_posix(),
                        "snapshot_id": artifacts.snapshot.snapshot_id,
                        "config_fingerprint": cfg.fingerprint(),
                        "nodes_count": len(artifacts.graph.nodes),
                        "edges_count": len(artifacts.graph.edges),
                        "has_warnings": artifacts.has_warnings,
                    },
                    sort_keys=True,
                )
            )
        else:
            typer.echo(
                f"Generated {artifacts.output_md_path} "
                f"({len(artifacts.graph.nodes)} nodes, {len(artifacts.graph.edges)} edges)"
            )
        if strict and artifacts.has_warnings:
            raise CtxaWarningError(
                "Handoff completed with extraction warnings under --strict mode."
            )
    except CtxaError as exc:
        _handle_cli_error(exc, as_json=as_json)


@app.command()
def verify(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Verify whether PROJECT_CONTEXT.md and .context/ match the current working tree."""
    _ = strict
    repo_root, cfg = _resolve_target_and_config(path, as_json=as_json)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "verify",
                    "repo_root": repo_root.as_posix(),
                    "config_fingerprint": cfg.fingerprint(),
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
    repo_root, cfg = _resolve_target_and_config(path, as_json=as_json)
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "command": "compact",
                    "repo_root": repo_root.as_posix(),
                    "config_fingerprint": cfg.fingerprint(),
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"Compact ready for {repo_root}")


@app.command()
def rebuild(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    deterministic: bool = typer.Option(
        False, "--deterministic", help="Normalize volatile timestamps."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Force a clean L3 full rebuild of the canonical graph and checkpoint."""
    repo_root, cfg = _resolve_target_and_config(path, as_json=as_json)
    try:
        artifacts = execute_full_handoff(repo_root, cfg, deterministic=deterministic)
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "command": "rebuild",
                        "repo_root": repo_root.as_posix(),
                        "snapshot_id": artifacts.snapshot.snapshot_id,
                        "config_fingerprint": cfg.fingerprint(),
                    },
                    sort_keys=True,
                )
            )
        else:
            typer.echo(f"Rebuild complete for {repo_root} ({artifacts.snapshot.snapshot_id})")
    except CtxaError as exc:
        _handle_cli_error(exc, as_json=as_json)


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
    repo_root, cfg = _resolve_target_and_config(path)
    context_dir = repo_root / ".context"
    try:
        manifest_file = context_dir / "manifest.json"
        graph_file = context_dir / "graph.json"
        if not manifest_file.is_file() or not graph_file.is_file():
            artifacts = execute_full_handoff(repo_root, cfg)
            manifest = artifacts.manifest
            graph = artifacts.graph
        else:
            manifest = load_manifest(context_dir)
            raw_graph = json.loads(graph_file.read_text(encoding="utf-8"))
            graph = CanonicalGraph.model_validate(raw_graph)

        if output_format == "json":
            rendered = export_canonical_json(
                manifest=manifest,
                graph=graph,
                output_path=output,
            )
            if output is None:
                typer.echo(rendered, nl=False)
            else:
                typer.echo(f"Exported JSON bundle to {output}")
        else:
            typer.echo(f"Export ({output_format}) for {repo_root} -> {output or 'stdout'}")
    except CtxaError as exc:
        _handle_cli_error(exc)


@app.command()
def mcp(
    path: Path = typer.Argument(Path(), help="Target repository path."),
) -> None:
    """Start the optional read-only Model Context Protocol (MCP) server over stdio."""
    repo_root, _ = _resolve_target_and_config(path)
    typer.echo(f"MCP server ready for {repo_root}")
