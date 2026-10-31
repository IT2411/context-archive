"""Immutable snapshot checkpoint model (.context/snapshots/snapshot-NNNN.json)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context_archive.exceptions import IntegrityError
from context_archive.git.state import GitState
from context_archive.lock import atomic_write_text
from context_archive.model.graph import CanonicalGraph
from context_archive.model.manifest import DETERMINISTIC_TIMESTAMP

if TYPE_CHECKING:
    from pathlib import Path

    from context_archive.scanner.report import ScanReport


def format_snapshot_id(sequence_number: int) -> str:
    """Format a 1-indexed integer into `snapshot-NNNN`."""
    return f"snapshot-{max(1, sequence_number):04d}"


class Snapshot(BaseModel):
    """Immutable point-in-time checkpoint matching docs/schemas/snapshot.schema.json."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    snapshot_id: str = Field(pattern=r"^snapshot-[0-9]{4,}$")
    parent_snapshot_id: str | None = Field(default=None)
    repository_id: str = Field(pattern=r"^repo:sha256:[a-f0-9]{32,64}$")
    created_at: str = Field(min_length=1)
    config_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    git_state: GitState
    incorporated_journal_cursor: str | None = Field(default=None)
    incorporated_change_ids: tuple[str, ...] = Field(default=())
    file_fingerprints: dict[str, str] = Field(default_factory=dict)
    graph: CanonicalGraph

    @classmethod
    def create_initial(
        cls,
        *,
        scan_report: ScanReport,
        graph: CanonicalGraph,
        snapshot_id: str = "snapshot-0001",
        deterministic: bool = False,
    ) -> Snapshot:
        """Create a base snapshot from a repository ScanReport and CanonicalGraph."""
        created_at = (
            DETERMINISTIC_TIMESTAMP
            if deterministic
            else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        return cls(
            snapshot_id=snapshot_id,
            parent_snapshot_id=None,
            repository_id=scan_report.repository_id,
            created_at=created_at,
            config_fingerprint=scan_report.config_fingerprint,
            git_state=scan_report.git_state,
            incorporated_journal_cursor=None,
            incorporated_change_ids=(),
            file_fingerprints=scan_report.file_fingerprints(),
            graph=graph,
        )

    def to_deterministic_json(self, *, indent: int = 2) -> str:
        """Serialize snapshot to deterministically sorted JSON."""
        payload = self.model_dump(mode="json")
        git_dict = payload.get("git_state")
        if isinstance(git_dict, dict) and git_dict.get("remote_url") is None:
            git_dict.pop("remote_url", None)
        graph_dict = payload.get("graph", {})
        if isinstance(graph_dict, dict):
            for edge_dict in graph_dict.get("edges", []):
                if isinstance(edge_dict, dict) and not edge_dict.get("attributes"):
                    edge_dict.pop("attributes", None)
            for diag_dict in graph_dict.get("diagnostics", []):
                if isinstance(diag_dict, dict) and diag_dict.get("line") is None:
                    diag_dict.pop("line", None)
        return json.dumps(payload, indent=indent, sort_keys=True) + "\n"


def write_snapshot(context_dir: Path, snapshot: Snapshot) -> Path:
    """Atomically write .context/snapshots/<snapshot_id>.json."""
    snapshots_dir = context_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    target = snapshots_dir / f"{snapshot.snapshot_id}.json"
    atomic_write_text(target, snapshot.to_deterministic_json())
    return target


def load_snapshot(context_dir: Path, snapshot_id: str) -> Snapshot:
    """Load and validate a snapshot file from .context/snapshots/<snapshot_id>.json."""
    target = context_dir / "snapshots" / f"{snapshot_id}.json"
    if not target.is_file():
        raise IntegrityError(f"Snapshot file is missing: '{target}'")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return Snapshot.model_validate(raw)
    except (OSError, ValueError, ValidationError) as exc:
        raise IntegrityError(f"Corrupt or incompatible snapshot '{target}': {exc}") from exc
