"""Public Python SDK (`ContextArchiveEngine`) implementing SRS Section 8.3."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from context_archive.cli import (
    execute_full_handoff,
    execute_incremental_update,
)
from context_archive.config import CtxaConfig, load_config
from context_archive.context.compiler import TaskPacket, compile_task_context
from context_archive.context.verifier import (
    VerificationReport,
    verify_repository_freshness,
)

if TYPE_CHECKING:
    from context_archive.model.graph import CanonicalGraph
    from context_archive.model.manifest import Manifest


@dataclass(frozen=True)
class UpdateResult:
    """Public SDK result returned by `ContextArchiveEngine.update()`."""

    is_noop: bool
    update_level: str
    change_id: str | None
    manifest: Manifest


@dataclass(frozen=True)
class HandoffResult:
    """Public SDK result returned by `ContextArchiveEngine.generate_handoff()`."""

    output_path: Path
    snapshot_id: str
    manifest: Manifest
    graph: CanonicalGraph
    has_warnings: bool


class ContextArchiveEngine:
    """High-level programmatic Python SDK for `context-archive`."""

    def __init__(self, repo_root: Path = Path(), config: CtxaConfig | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.config = config or load_config(self.repo_root)

    def update(
        self,
        *,
        intent: str | None = None,
        level: str = "auto",
        deterministic: bool = False,
    ) -> UpdateResult:
        """Record incremental repository changes into the append-only journal."""
        res = execute_incremental_update(
            self.repo_root,
            self.config,
            requested_level=level,
            developer_message=intent,
            deterministic=deterministic,
        )
        return UpdateResult(
            is_noop=res.is_noop,
            update_level=res.update_level,
            change_id=res.record.change_id if res.record else None,
            manifest=res.manifest,
        )

    def verify(self) -> VerificationReport:
        """Verify whether PROJECT_CONTEXT.md and .context/ match the live working tree."""
        return verify_repository_freshness(self.repo_root, self.config)

    def generate_handoff(
        self,
        *,
        output: Path | None = None,
        deterministic: bool = False,
    ) -> HandoffResult:
        """Compile and write the portable PROJECT_CONTEXT.md handoff artifact."""
        cfg = self.config
        if output is not None:
            cfg = load_config(
                self.repo_root,
                cli_overrides={"context": {"output_path": output.as_posix()}},
            )
        artifacts = execute_full_handoff(
            self.repo_root,
            cfg,
            deterministic=deterministic,
        )
        return HandoffResult(
            output_path=artifacts.output_md_path,
            snapshot_id=artifacts.snapshot.snapshot_id,
            manifest=artifacts.manifest,
            graph=artifacts.graph,
            has_warnings=artifacts.has_warnings,
        )

    def compile_task_context(
        self,
        *,
        task: str,
        max_tokens: int = 6000,
        tokenizer: str | None = None,
    ) -> TaskPacket:
        """Compile a ranked, token-budgeted context packet for a specific task."""
        if not (self.repo_root / ".context" / "manifest.json").is_file():
            execute_full_handoff(self.repo_root, self.config)
        return compile_task_context(
            repo_root=self.repo_root,
            config=self.config,
            task=task,
            max_tokens=max_tokens,
            tokenizer_spec=tokenizer,
        )
