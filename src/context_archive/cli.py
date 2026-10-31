"""CLI entrypoints for context-archive (ctxa)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import typer

from context_archive import __version__
from context_archive.adapters.pipeline import extract_all_adapters
from context_archive.config import CtxaConfig, load_config, render_default_ctxa_toml
from context_archive.context.assembler import (
    filter_unincorporated_records,
)
from context_archive.context.compiler import compile_task_context
from context_archive.context.differ import (
    SemanticDiffReport,
    compute_downstream_impacts,
    compute_semantic_diff,
)
from context_archive.context.verifier import verify_repository_freshness
from context_archive.exceptions import (
    ConfigError,
    CtxaError,
    CtxaWarningError,
    ExitCode,
)
from context_archive.lock import ContextLock, atomic_write_text
from context_archive.model.graph import CanonicalGraph
from context_archive.model.manifest import Manifest, StateCursors, load_manifest, write_manifest
from context_archive.notes.manager import append_human_note, sync_manual_notes
from context_archive.renderers.json_exporter import export_canonical_json
from context_archive.renderers.markdown import render_project_context_markdown
from context_archive.renderers.mermaid import render_diff_mermaid, render_graph_mermaid
from context_archive.scanner.discovery import discover_repo_root
from context_archive.scanner.walker import scan_repository
from context_archive.state.cache import ContextSqliteCache
from context_archive.state.compactor import compact_snapshot
from context_archive.state.detector import detect_repository_changes
from context_archive.state.invalidator import refresh_graph_incrementally
from context_archive.state.journal import (
    JournalRecord,
    JournalSourceState,
    append_journal_record,
    compute_tree_fingerprint,
    generate_next_change_id,
    read_all_journal_records,
)
from context_archive.state.snapshot import (
    Snapshot,
    format_snapshot_id,
    load_snapshot,
    write_snapshot,
)

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


@dataclass(frozen=True)
class HandoffArtifacts:
    """Compiled artifacts produced during init/handoff."""

    repo_root: Path
    output_md_path: Path
    manifest: Manifest
    graph: CanonicalGraph
    snapshot: Snapshot
    has_warnings: bool


@dataclass(frozen=True)
class IncrementalUpdateResult:
    """Result of executing `ctxa update`."""

    repo_root: Path
    is_noop: bool
    update_level: str
    record: JournalRecord | None
    manifest: Manifest


def _format_recent_journal_lines(
    records: list[JournalRecord],
    incorporated_cursor: str | None,
) -> list[str]:
    """Render unincorporated journal entries as Markdown bullets for Section 8."""
    unincorporated = filter_unincorporated_records(records, incorporated_cursor)
    if not unincorporated:
        return []

    lines: list[str] = []
    for rec in unincorporated:
        files_str = ", ".join(f"`{fc.path}` ({fc.operation})" for fc in rec.file_changes)
        files_part = f" — Files: {files_str}" if files_str else ""
        lines.append(
            f"- **`{rec.change_id}`** [`{rec.update_level}` | `{rec.category}` | "
            f"`origin: {rec.intent.origin}`]: {rec.intent.summary}{files_part}"
        )
    return lines


def execute_full_handoff(
    repo_root: Path,
    config: CtxaConfig,
    *,
    deterministic: bool = False,
    snapshot_id: str | None = None,
    force_new_checkpoint: bool = False,
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

        manual_notes = sync_manual_notes(md_path=output_md_path, notes_path=notes_path)

        existing_manifest: Manifest | None = None
        if (context_dir / "manifest.json").is_file():
            existing_manifest = load_manifest(context_dir)

        journal_records = read_all_journal_records(context_dir)
        head_cursor = journal_records[-1].change_id if journal_records else None

        if force_new_checkpoint and existing_manifest is not None:
            cur_snap = existing_manifest.state_cursors.latest_snapshot_id
            parts = cur_snap.split("-")
            next_num = int(parts[1]) + 1 if len(parts) == 2 and parts[1].isdigit() else 2
            effective_snapshot_id = snapshot_id or format_snapshot_id(next_num)
            inc_cursor = head_cursor
        else:
            effective_snapshot_id = snapshot_id or (
                existing_manifest.state_cursors.latest_snapshot_id
                if existing_manifest is not None
                else "snapshot-0001"
            )
            inc_cursor = (
                existing_manifest.state_cursors.snapshot_incorporated_journal_cursor
                if existing_manifest is not None
                else None
            )

        uninc_records = filter_unincorporated_records(journal_records, inc_cursor)

        scan_report = scan_repository(repo_root, config)
        cache = ContextSqliteCache(context_dir)
        cache.store_fingerprints(scan_report.file_fingerprints())

        pass
        ast_res = extract_all_adapters(repo_root, scan_report.files)

        syntax_error_count = sum(1 for d in ast_res.diagnostics if d.code == "python_syntax_error")
        total_failed = scan_report.summary.files_failed + syntax_error_count

        graph = CanonicalGraph.build(
            repository_id=scan_report.repository_id,
            base_snapshot_id=effective_snapshot_id,
            applied_journal_cursor=head_cursor,
            nodes=ast_res.nodes,
            edges=ast_res.edges,
            diagnostics=ast_res.diagnostics,
        )

        snapshot_file = context_dir / "snapshots" / f"{effective_snapshot_id}.json"
        if not snapshot_file.is_file() or snapshot_id is not None or force_new_checkpoint:
            parent_snap_id = (
                existing_manifest.state_cursors.latest_snapshot_id
                if (existing_manifest is not None and force_new_checkpoint)
                else None
            )
            snapshot = Snapshot(
                snapshot_id=effective_snapshot_id,
                parent_snapshot_id=parent_snap_id,
                repository_id=scan_report.repository_id,
                created_at=(
                    "1970-01-01T00:00:00Z"
                    if deterministic
                    else Manifest.from_scan_report(scan_report).generated_at
                ),
                config_fingerprint=scan_report.config_fingerprint,
                git_state=scan_report.git_state,
                incorporated_journal_cursor=inc_cursor,
                incorporated_change_ids=tuple(r.change_id for r in journal_records),
                file_fingerprints=scan_report.file_fingerprints(),
                graph=graph,
            )
            write_snapshot(context_dir, snapshot)
        else:
            snapshot = load_snapshot(context_dir, effective_snapshot_id)

        manifest = Manifest.from_scan_report(
            scan_report,
            latest_snapshot_id=effective_snapshot_id,
            snapshot_incorporated_journal_cursor=inc_cursor,
            head_journal_cursor=head_cursor,
            unincorporated_record_count=len(uninc_records),
            notes_content=manual_notes + "\n",
            deterministic=deterministic,
            files_failed_override=total_failed,
        )

        recent_lines = _format_recent_journal_lines(journal_records, inc_cursor)
        markdown_doc = render_project_context_markdown(
            repo_root=repo_root,
            config=config,
            manifest=manifest,
            scan_report=scan_report,
            graph=graph,
            manual_block_content=manual_notes,
            recent_changes_lines=recent_lines,
        )

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


def execute_incremental_update(
    repo_root: Path,
    config: CtxaConfig,
    *,
    requested_level: str = "auto",
    developer_message: str | None = None,
    deterministic: bool = False,
) -> IncrementalUpdateResult:
    """Detect repository changes, append a JSONL journal record, and refresh graph state."""
    context_dir = repo_root / ".context"
    manifest_file = context_dir / "manifest.json"
    graph_file = context_dir / "graph.json"

    if not manifest_file.is_file() or not graph_file.is_file():
        artifacts = execute_full_handoff(repo_root, config, deterministic=deterministic)
        return IncrementalUpdateResult(
            repo_root=repo_root,
            is_noop=False,
            update_level="L3",
            record=None,
            manifest=artifacts.manifest,
        )

    with ContextLock(context_dir):
        manifest = load_manifest(context_dir)
        raw_graph = json.loads(graph_file.read_text(encoding="utf-8"))
        previous_graph = CanonicalGraph.model_validate(raw_graph)
        base_snapshot = load_snapshot(context_dir, manifest.state_cursors.latest_snapshot_id)
        baseline_tree_fp = compute_tree_fingerprint(base_snapshot.file_fingerprints)

        existing_records = read_all_journal_records(context_dir)
        live_scan = scan_repository(repo_root, config)
        cache = ContextSqliteCache(context_dir)
        cache.store_fingerprints(live_scan.file_fingerprints())

        detection = detect_repository_changes(
            repo_root=repo_root,
            manifest=manifest,
            previous_graph=previous_graph,
            live_scan=live_scan,
            existing_records=existing_records,
            baseline_tree_fingerprint=baseline_tree_fp,
            requested_level=requested_level,
            developer_message=developer_message,
        )

        if detection.is_noop:
            return IncrementalUpdateResult(
                repo_root=repo_root,
                is_noop=True,
                update_level=detection.update_level,
                record=None,
                manifest=manifest,
            )

        change_id, recorded_at, ym_partition = generate_next_change_id(
            existing_records,
            deterministic=deterministic,
        )
        parent_change_id = existing_records[-1].change_id if existing_records else None

        effective_level = detection.update_level
        if detection.update_level in ("L2", "L3"):
            invalidation = refresh_graph_incrementally(
                repo_root=repo_root,
                previous_graph=previous_graph,
                live_files=live_scan.files,
                file_changes=detection.file_changes,
                requested_level=detection.update_level,
                base_snapshot_id=manifest.state_cursors.latest_snapshot_id,
                applied_journal_cursor=change_id,
            )
            updated_graph = invalidation.graph
            effective_level = invalidation.effective_level
        else:
            updated_graph = CanonicalGraph.build(
                repository_id=previous_graph.repository_id,
                base_snapshot_id=previous_graph.base_snapshot_id,
                applied_journal_cursor=change_id,
                nodes=previous_graph.nodes,
                edges=previous_graph.edges,
                diagnostics=previous_graph.diagnostics,
            )

        modified_symbol_ids = {
            sym_id for fc in detection.file_changes for sym_id in fc.modified_symbols
        }
        downstream_items = compute_downstream_impacts(
            updated_graph,
            modified_symbol_ids,
            max_hops=2,
        )
        journal_impacts = tuple(item.to_journal_impact() for item in downstream_items)

        record = JournalRecord(
            change_id=change_id,
            parent_change_id=parent_change_id,
            recorded_at=recorded_at,
            repository_id=manifest.repository_id,
            base_snapshot_id=manifest.state_cursors.latest_snapshot_id,
            update_level=effective_level,
            source_state=JournalSourceState(
                commit_sha=live_scan.git_state.commit_sha,
                branch=live_scan.git_state.branch,
                is_dirty=live_scan.git_state.is_dirty,
                tree_fingerprint=detection.tree_fingerprint,
            ),
            category=detection.category,
            intent=detection.intent,
            file_changes=detection.file_changes,
            impact_summary=journal_impacts,
            supersedes=(),
            record_status="active",
        )
        append_journal_record(context_dir, record, partition_ym=ym_partition)
        atomic_write_text(graph_file, updated_graph.to_deterministic_json())

        inc_cursor = manifest.state_cursors.snapshot_incorporated_journal_cursor
        all_records = [*existing_records, record]
        uninc_records = filter_unincorporated_records(all_records, inc_cursor)

        updated_manifest = Manifest(
            schema_version=manifest.schema_version,
            tool_version=manifest.tool_version,
            repository_id=manifest.repository_id,
            generated_at=recorded_at,
            config_fingerprint=live_scan.config_fingerprint,
            git_state=live_scan.git_state,
            state_cursors=StateCursors(
                latest_snapshot_id=manifest.state_cursors.latest_snapshot_id,
                snapshot_incorporated_journal_cursor=inc_cursor,
                head_journal_cursor=change_id,
                unincorporated_record_count=len(uninc_records),
                notes_fingerprint=manifest.state_cursors.notes_fingerprint,
            ),
            scan_summary=live_scan.summary,
            file_fingerprints=live_scan.file_fingerprints(),
        )
        write_manifest(context_dir, updated_manifest)

    return IncrementalUpdateResult(
        repo_root=repo_root,
        is_noop=False,
        update_level=effective_level,
        record=record,
        manifest=updated_manifest,
    )


def execute_repository_diff(
    repo_root: Path,
    config: CtxaConfig,
    *,
    since_snapshot_id: str | None = None,
) -> SemanticDiffReport:
    """Compute a SemanticDiffReport between a baseline snapshot and the live repository."""
    context_dir = repo_root / ".context"
    if not (context_dir / "manifest.json").is_file():
        execute_full_handoff(repo_root, config)

    manifest = load_manifest(context_dir)
    target_snap_id = since_snapshot_id or manifest.state_cursors.latest_snapshot_id
    baseline_snapshot = load_snapshot(context_dir, target_snap_id)

    live_scan = scan_repository(repo_root, config)
    pass
    ast_res = extract_all_adapters(repo_root, live_scan.files)
    live_graph = CanonicalGraph.build(
        repository_id=live_scan.repository_id,
        base_snapshot_id=target_snap_id,
        applied_journal_cursor=manifest.state_cursors.head_journal_cursor,
        nodes=ast_res.nodes,
        edges=ast_res.edges,
        diagnostics=ast_res.diagnostics,
    )

    records = read_all_journal_records(context_dir)
    inc_cursor = baseline_snapshot.incorporated_journal_cursor
    body_modified: set[str] = set()
    for rec in filter_unincorporated_records(records, inc_cursor):
        for fc in rec.file_changes:
            body_modified.update(fc.modified_symbols)

    return compute_semantic_diff(
        baseline_id=target_snap_id,
        baseline_graph=baseline_snapshot.graph,
        baseline_fingerprints=baseline_snapshot.file_fingerprints,
        current_graph=live_graph,
        current_fingerprints=live_scan.file_fingerprints(),
        body_modified_symbols=body_modified,
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
            snapshot_id="snapshot-0001",
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
    deterministic: bool = typer.Option(
        False, "--deterministic", help="Normalize volatile timestamps."
    ),
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
    try:
        result = execute_incremental_update(
            repo_root,
            cfg,
            requested_level=normalized_level,
            developer_message=message,
            deterministic=deterministic,
        )
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "command": "update",
                        "repo_root": repo_root.as_posix(),
                        "is_noop": result.is_noop,
                        "level": result.update_level,
                        "change_id": result.record.change_id if result.record else None,
                        "category": result.record.category if result.record else None,
                        "message": message,
                        "config_fingerprint": cfg.fingerprint(),
                    },
                    sort_keys=True,
                )
            )
        elif result.is_noop:
            typer.echo(f"No changes detected in {repo_root} (idempotent no-op).")
        else:
            cid = result.record.change_id if result.record else "snapshot-0001"
            typer.echo(f"Recorded {result.update_level} update ({cid}) in {repo_root}")
    except CtxaError as exc:
        _handle_cli_error(exc, as_json=as_json)


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
    deterministic: bool = typer.Option(
        False, "--deterministic", help="Normalize volatile timestamps."
    ),
) -> None:
    """Record a durable human note or architectural decision."""
    repo_root, cfg = _resolve_target_and_config(path)
    output_rel = Path(cfg.context.output_path)
    output_md_path = output_rel if output_rel.is_absolute() else (repo_root / output_rel)
    context_dir = repo_root / ".context"
    try:
        with ContextLock(context_dir):
            record = append_human_note(
                repo_root=repo_root,
                output_md_path=output_md_path,
                text=text,
                note_type=note_type,
                scope=scope,
                deterministic=deterministic,
            )
        typer.echo(f"Recorded {record.note_type} note in {repo_root} (scope={record.scope})")
    except CtxaError as exc:
        _handle_cli_error(exc)


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
    try:
        artifacts = execute_full_handoff(
            repo_root,
            cfg,
            deterministic=deterministic,
            force_new_checkpoint=full,
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
    report = verify_repository_freshness(repo_root, cfg)
    if as_json:
        payload = report.model_dump(mode="json")
        payload["command"] = "verify"
        payload["config_fingerprint"] = cfg.fingerprint()
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(f"Verification status: {report.status} ({repo_root})")
        for reason in report.reasons:
            typer.echo(f"  - {reason}")
    if report.exit_code != int(ExitCode.SUCCESS):
        raise typer.Exit(report.exit_code)


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
    repo_root, cfg = _resolve_target_and_config(path, as_json=(output_format == "json"))
    try:
        report = execute_repository_diff(repo_root, cfg, since_snapshot_id=since)
        if output_format == "json":
            typer.echo(report.to_deterministic_json(), nl=False)
        elif output_format == "mermaid":
            typer.echo(render_diff_mermaid(report), nl=False)
        else:
            typer.echo(report.render_text(), nl=False)
    except CtxaError as exc:
        _handle_cli_error(exc, as_json=(output_format == "json"))


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
        _handle_cli_error(
            ConfigError("Task description cannot be empty."),
            as_json=(output_format == "json"),
        )
    if output_format not in VALID_CONTEXT_FORMATS:
        _handle_cli_error(
            ConfigError(f"Unsupported --format '{output_format}'. Expected md or json.")
        )
    repo_root, cfg = _resolve_target_and_config(path, as_json=(output_format == "json"))
    try:
        if not (repo_root / ".context" / "manifest.json").is_file():
            execute_full_handoff(repo_root, cfg)

        packet = compile_task_context(
            repo_root=repo_root,
            config=cfg,
            task=task,
            max_tokens=max_tokens,
            tokenizer_spec=tokenizer,
        )
        rendered = packet.to_deterministic_json() if output_format == "json" else packet.markdown
        if output is not None:
            out_path = output if output.is_absolute() else (repo_root / output)
            atomic_write_text(out_path, rendered)
            typer.echo(
                f"Compiled task context to {out_path} "
                f"({packet.estimated_tokens}/{packet.max_tokens} tokens)"
            )
        else:
            typer.echo(rendered, nl=False)
    except CtxaError as exc:
        _handle_cli_error(exc, as_json=(output_format == "json"))


@app.command()
def compact(
    path: Path = typer.Argument(Path(), help="Target repository path."),
    deterministic: bool = typer.Option(
        False, "--deterministic", help="Normalize volatile timestamps."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON output."),
) -> None:
    """Fold unincorporated journal entries into a new immutable snapshot checkpoint."""
    repo_root, cfg = _resolve_target_and_config(path, as_json=as_json)
    try:
        res = compact_snapshot(repo_root, cfg, deterministic=deterministic)
        if as_json:
            typer.echo(
                json.dumps(
                    {
                        "command": "compact",
                        "repo_root": repo_root.as_posix(),
                        "previous_snapshot_id": res.previous_snapshot_id,
                        "new_snapshot_id": res.new_snapshot_id,
                        "compacted_record_count": res.compacted_record_count,
                        "incorporated_journal_cursor": res.incorporated_journal_cursor,
                        "config_fingerprint": cfg.fingerprint(),
                    },
                    sort_keys=True,
                )
            )
        else:
            typer.echo(
                f"Compacted {res.compacted_record_count} journal record(s) into "
                f"{res.new_snapshot_id} in {repo_root}"
            )
    except CtxaError as exc:
        _handle_cli_error(exc, as_json=as_json)


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
        artifacts = execute_full_handoff(
            repo_root,
            cfg,
            deterministic=deterministic,
            force_new_checkpoint=True,
        )
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
        else:
            rendered = render_graph_mermaid(graph)
            if output is not None:
                atomic_write_text(output, rendered)

        if output is None:
            typer.echo(rendered, nl=False)
        else:
            typer.echo(f"Exported {output_format} artifact to {output}")
    except CtxaError as exc:
        _handle_cli_error(exc)


@app.command()
def mcp(
    path: Path = typer.Argument(Path(), help="Target repository path."),
) -> None:
    """Start the optional read-only Model Context Protocol (MCP) server over stdio."""
    repo_root, _ = _resolve_target_and_config(path)
    typer.echo(f"MCP server ready for {repo_root}")
