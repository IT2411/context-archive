"""Append-only JSONL change journal (.context/journal/YYYY-MM.jsonl) and cursor logic."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context_archive.exceptions import IntegrityError
from context_archive.lock import atomic_write_text
from context_archive.model.manifest import DETERMINISTIC_TIMESTAMP

if TYPE_CHECKING:
    from pathlib import Path

UpdateLevel = Literal["L1", "L2", "L3"]

ChangeCategory = Literal[
    "feature",
    "bug_fix",
    "refactor",
    "contract_change",
    "schema_change",
    "dependency_change",
    "config_change",
    "test_change",
    "docs_change",
    "revert",
    "unknown",
]

IntentOrigin = Literal["developer_confirmed", "deterministic_classifier", "heuristic"]
IntentConfidence = Literal["high", "medium", "low"]
FileOperation = Literal["added", "modified", "deleted", "renamed"]
ImpactConfidence = Literal["direct", "inferred_downstream"]
RecordStatus = Literal["active", "superseded"]


def compute_tree_fingerprint(file_fingerprints: dict[str, str]) -> str:
    """Compute a deterministic `sha256:<hex>` digest over sorted file fingerprints."""
    canonical = json.dumps(file_fingerprints, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


class JournalSourceState(BaseModel):
    """Git and tree fingerprint state recorded in a JournalRecord."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commit_sha: str | None = Field(default=None)
    branch: str | None = Field(default=None)
    is_dirty: bool = Field(default=False)
    tree_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class JournalIntent(BaseModel):
    """Developer-confirmed or deterministically classified change intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1)
    origin: IntentOrigin
    confidence: IntentConfidence


class JournalFileChange(BaseModel):
    """Per-file mutation entry inside a JournalRecord."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    operation: FileOperation
    old_sha256: str | None = Field(default=None)
    new_sha256: str | None = Field(default=None)
    modified_symbols: tuple[str, ...] = Field(default=())


class JournalImpactItem(BaseModel):
    """Direct or inferred downstream impact entry inside a JournalRecord."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_id: str = Field(min_length=1)
    relationship: str = Field(min_length=1)
    confidence: ImpactConfidence
    evidence_path: str = Field(min_length=1)


class JournalRecord(BaseModel):
    """Single append-only record conforming to docs/schemas/journal-record.schema.json."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    change_id: str = Field(pattern=r"^CA-[0-9]{8}-[0-9]{4,}$")
    parent_change_id: str | None = Field(default=None)
    recorded_at: str = Field(min_length=1)
    repository_id: str = Field(pattern=r"^repo:sha256:[a-f0-9]{32,64}$")
    base_snapshot_id: str = Field(pattern=r"^snapshot-[0-9]{4,}$")
    update_level: UpdateLevel
    source_state: JournalSourceState
    category: ChangeCategory
    intent: JournalIntent
    file_changes: tuple[JournalFileChange, ...] = Field(default=())
    impact_summary: tuple[JournalImpactItem, ...] = Field(default=())
    supersedes: tuple[str, ...] = Field(default=())
    record_status: RecordStatus = "active"

    def to_jsonl_line(self) -> str:
        """Serialize record to a single-line deterministic JSON string with trailing newline."""
        payload = self.model_dump(mode="json")
        return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def read_all_journal_records(context_dir: Path) -> list[JournalRecord]:
    """Read and validate all JSONL records across .context/journal/*.jsonl in order."""
    journal_dir = context_dir / "journal"
    if not journal_dir.is_dir():
        return []

    records: list[JournalRecord] = []
    for jsonl_file in sorted(journal_dir.glob("*.jsonl"), key=lambda p: p.name):
        try:
            lines = jsonl_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:  # pragma: no cover
            raise IntegrityError(f"Failed reading journal file '{jsonl_file}': {exc}") from exc

        for line_num, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
                records.append(JournalRecord.model_validate(parsed))
            except (ValueError, ValidationError) as exc:
                raise IntegrityError(
                    f"Corrupt journal record at '{jsonl_file}:{line_num}': {exc}"
                ) from exc

    return records


def generate_next_change_id(
    existing_records: list[JournalRecord],
    *,
    now: datetime | None = None,
    deterministic: bool = False,
) -> tuple[str, str, str]:
    """Generate `(change_id, recorded_at_iso, year_month_partition)`.

    Monotonically increments the 4-digit sequence number across all existing records.
    """
    if deterministic:
        date_prefix = "19700101"
        recorded_at = DETERMINISTIC_TIMESTAMP
        ym_partition = "1970-01"
    else:
        dt = now or datetime.now(timezone.utc)
        date_prefix = dt.strftime("%Y%m%d")
        recorded_at = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        ym_partition = dt.strftime("%Y-%m")

    max_seq = 0
    for rec in existing_records:
        parts = rec.change_id.split("-")
        if len(parts) == 3 and parts[2].isdigit():
            max_seq = max(max_seq, int(parts[2]))

    next_seq = max_seq + 1
    change_id = f"CA-{date_prefix}-{next_seq:04d}"
    return change_id, recorded_at, ym_partition


def append_journal_record(
    context_dir: Path,
    record: JournalRecord,
    *,
    partition_ym: str | None = None,
) -> Path:
    """Atomically append a single JournalRecord to .context/journal/YYYY-MM.jsonl."""
    journal_dir = context_dir / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    effective_ym = partition_ym or record.recorded_at[:7]
    target_path = journal_dir / f"{effective_ym}.jsonl"

    existing_content = ""
    if target_path.is_file():
        existing_content = target_path.read_text(encoding="utf-8")
        if existing_content and not existing_content.endswith("\n"):
            existing_content += "\n"

    updated_content = existing_content + record.to_jsonl_line()
    atomic_write_text(target_path, updated_content)
    return target_path
