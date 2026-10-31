"""Branch divergence detection and multi-developer journal/note reconciliation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from context_archive.exceptions import IntegrityError
from context_archive.lock import atomic_write_text
from context_archive.notes.manager import (
    HEADING_DECISIONS,
    HEADING_ISSUES,
    HEADING_NEXT_STEPS,
    PLACEHOLDER_BY_HEADING,
    ensure_canonical_notes_sections,
)
from context_archive.state.journal import JournalRecord, read_all_journal_records

if TYPE_CHECKING:
    from pathlib import Path

CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


@dataclass(frozen=True)
class DivergenceReport:
    """Summary of journal or Git branch divergence."""

    has_conflict_markers: bool
    has_journal_fork: bool
    fork_change_ids: tuple[str, ...]
    branch_mismatch: bool
    recorded_branch: str | None
    live_branch: str | None


def check_for_git_conflict_markers(file_path: Path) -> bool:
    """Return True if a file contains unresolved Git merge conflict markers."""
    if not file_path.is_file():
        return False
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover
        return False
    return any(line.startswith(CONFLICT_MARKERS) for line in text.splitlines())


def detect_journal_forks(records: list[JournalRecord]) -> tuple[bool, list[str]]:
    """Detect if journal records contain divergent heads or duplicate sequence IDs from a merge."""
    if len(records) <= 1:
        return False, []

    seen_ids: set[str] = set()
    children_by_parent: dict[str | None, list[str]] = {}
    fork_ids: list[str] = []

    for rec in records:
        if rec.change_id in seen_ids:
            fork_ids.append(rec.change_id)
        seen_ids.add(rec.change_id)
        children_by_parent.setdefault(rec.parent_change_id, []).append(rec.change_id)

    for _parent, children in children_by_parent.items():
        if len(children) > 1:
            fork_ids.extend(children)

    expected_parent: str | None = None
    for idx, rec in enumerate(records):
        if (idx == 0 and rec.parent_change_id is not None) or (
            idx > 0 and rec.parent_change_id != expected_parent
        ):
            fork_ids.append(rec.change_id)
        expected_parent = rec.change_id

    unique_forks = sorted(set(fork_ids))
    return bool(unique_forks), unique_forks


def merge_human_notes_blocks(primary_notes: str, secondary_notes: str) -> str:
    """Union human notes across two branches without losing any developer's bullets."""
    norm_a = ensure_canonical_notes_sections(primary_notes)
    norm_b = ensure_canonical_notes_sections(secondary_notes)

    headings = (HEADING_DECISIONS, HEADING_ISSUES, HEADING_NEXT_STEPS)

    def _parse_sections(text: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {h: [] for h in headings}
        current_h: str | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped in headings:
                current_h = stripped
                continue
            if current_h is not None and stripped:
                placeholder = PLACEHOLDER_BY_HEADING[current_h]
                if stripped != placeholder and stripped not in sections[current_h]:
                    sections[current_h].append(line)
        return sections

    sec_a = _parse_sections(norm_a)
    sec_b = _parse_sections(norm_b)

    out_lines: list[str] = []
    for idx, h in enumerate(headings):
        if idx > 0:
            out_lines.append("")
        out_lines.append(h)
        combined: list[str] = list(sec_a[h])
        for item in sec_b[h]:
            if item not in combined:
                combined.append(item)
        if combined:
            out_lines.extend(combined)
        else:
            out_lines.append(PLACEHOLDER_BY_HEADING[h])

    return "\n".join(out_lines)


def reconcile_divergent_journal(context_dir: Path) -> list[JournalRecord]:
    """Reconcile divergent or merged journal records into a single linear, lossless chain.

    Preserves every unique record from all merged branches, re-sequencing any colliding
    `change_id`s and repairing `parent_change_id` pointers.
    """
    journal_dir = context_dir / "journal"
    if not journal_dir.is_dir():
        return []

    for jsonl_file in sorted(journal_dir.glob("*.jsonl"), key=lambda p: p.name):
        if check_for_git_conflict_markers(jsonl_file):
            raise IntegrityError(
                f"Unresolved Git merge conflict markers detected in '{jsonl_file}'. "
                "Remove conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) keeping both "
                "sets of JSONL lines, then run `ctxa rebuild`."
            )

    raw_records = read_all_journal_records(context_dir)
    if not raw_records:
        return []

    unique_records: list[JournalRecord] = []
    seen_payloads: set[str] = set()
    for rec in raw_records:
        fingerprint_key = json.dumps(
            {
                "tree": rec.source_state.tree_fingerprint,
                "intent": rec.intent.summary,
                "files": [fc.path for fc in rec.file_changes],
            },
            sort_keys=True,
        )
        if fingerprint_key not in seen_payloads:
            seen_payloads.add(fingerprint_key)
            unique_records.append(rec)

    unique_records.sort(key=lambda r: (r.recorded_at, r.change_id, r.intent.summary))

    reconciled: list[JournalRecord] = []
    prev_id: str | None = None
    used_ids: set[str] = set()

    for idx, rec in enumerate(unique_records, start=1):
        parts = rec.change_id.split("-")
        date_part = parts[1] if len(parts) == 3 else "19700101"
        candidate_id = rec.change_id
        if candidate_id in used_ids or (prev_id is not None and candidate_id <= prev_id):
            candidate_id = f"CA-{date_part}-{idx:04d}"
            while candidate_id in used_ids:
                idx += 1
                candidate_id = f"CA-{date_part}-{idx:04d}"

        used_ids.add(candidate_id)
        relinked = JournalRecord(
            schema_version=rec.schema_version,
            change_id=candidate_id,
            parent_change_id=prev_id,
            recorded_at=rec.recorded_at,
            repository_id=rec.repository_id,
            base_snapshot_id=rec.base_snapshot_id,
            update_level=rec.update_level,
            source_state=rec.source_state,
            category=rec.category,
            intent=rec.intent,
            file_changes=rec.file_changes,
            impact_summary=rec.impact_summary,
            supersedes=rec.supersedes,
            record_status=rec.record_status,
        )
        reconciled.append(relinked)
        prev_id = candidate_id

    by_partition: dict[str, list[JournalRecord]] = {}
    for rec in reconciled:
        ym = rec.recorded_at[:7] if len(rec.recorded_at) >= 7 else "1970-01"
        by_partition.setdefault(ym, []).append(rec)

    for jsonl_file in sorted(journal_dir.glob("*.jsonl")):
        jsonl_file.unlink(missing_ok=True)

    for ym, part_records in sorted(by_partition.items()):
        target = journal_dir / f"{ym}.jsonl"
        content = "".join(r.to_jsonl_line() for r in part_records)
        atomic_write_text(target, content)

    return reconciled
