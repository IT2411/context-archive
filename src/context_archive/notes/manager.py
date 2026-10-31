"""Durable human notes manager (.context/notes.md) and two-way synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

from context_archive.exceptions import ConfigError
from context_archive.lock import atomic_write_text
from context_archive.model.manifest import (
    DETERMINISTIC_TIMESTAMP,
    Manifest,
    StateCursors,
    compute_text_fingerprint,
    load_manifest,
    write_manifest,
)
from context_archive.notes.boundaries import (
    replace_manual_block_in_markdown,
    validate_and_extract_manual_block,
)
from context_archive.renderers.markdown import DEFAULT_MANUAL_NOTES_BLOCK

if TYPE_CHECKING:
    from pathlib import Path

NoteType = Literal["decision", "constraint", "issue", "question", "next_step"]

HEADING_DECISIONS = "# 11. Architectural Decisions & Constraints (Human-Maintained)"
HEADING_ISSUES = "# 12. Known Issues, Risks & Open Questions (Human-Maintained)"
HEADING_NEXT_STEPS = "# 13. Pending Work & Next Steps (Human-Maintained)"

PLACEHOLDER_DECISIONS = (
    "- _No architectural decisions or constraints recorded yet. "
    "Use `ctxa note` or edit inside this block._"
)
PLACEHOLDER_ISSUES = "- _No known issues or open questions recorded yet._"
PLACEHOLDER_NEXT_STEPS = "- _No pending work items recorded yet._"

SECTION_BY_NOTE_TYPE: dict[NoteType, str] = {
    "decision": HEADING_DECISIONS,
    "constraint": HEADING_DECISIONS,
    "issue": HEADING_ISSUES,
    "question": HEADING_ISSUES,
    "next_step": HEADING_NEXT_STEPS,
}

PLACEHOLDER_BY_HEADING: dict[str, str] = {
    HEADING_DECISIONS: PLACEHOLDER_DECISIONS,
    HEADING_ISSUES: PLACEHOLDER_ISSUES,
    HEADING_NEXT_STEPS: PLACEHOLDER_NEXT_STEPS,
}


@dataclass(frozen=True)
class NoteRecord:
    """Structured metadata for a newly added human note."""

    note_type: NoteType
    text: str
    scope: str
    recorded_at: str
    origin: str = "developer_confirmed"

    def to_markdown_bullet(self) -> str:
        """Render the note as a deterministic Markdown bullet line."""
        type_label = self.note_type.upper()
        return (
            f"- **[{type_label}]** (`scope: {self.scope}` | `{self.recorded_at}` | "
            f"`origin: {self.origin}`): {self.text}"
        )


def ensure_canonical_notes_sections(raw_notes: str) -> str:
    """Ensure all three canonical human-maintained headings exist in the notes block."""
    cleaned = raw_notes.strip()
    if not cleaned:
        return DEFAULT_MANUAL_NOTES_BLOCK

    lines = cleaned.splitlines()
    for heading, placeholder in PLACEHOLDER_BY_HEADING.items():
        if heading not in cleaned:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(heading)
            lines.append(placeholder)
    return "\n".join(lines)


def sync_manual_notes(
    *,
    md_path: Path,
    notes_path: Path,
) -> str:
    """Two-way sync manual notes between PROJECT_CONTEXT.md and .context/notes.md.

    - If `md_path` exists, validates its `CTXA:MANUAL` boundaries (aborting with `.bak`
      and `IntegrityError` if corrupted).
    - If the manual block inside `md_path` has been edited relative to the default template
      or `.context/notes.md`, preserves the user's edits and writes them to `.context/notes.md`.
    - Otherwise loads `.context/notes.md` or initializes `DEFAULT_MANUAL_NOTES_BLOCK`.
    """
    notes_from_store: str | None = None
    if notes_path.is_file():
        stored_text = notes_path.read_text(encoding="utf-8", errors="replace").strip()
        if stored_text:
            notes_from_store = ensure_canonical_notes_sections(stored_text)

    notes_from_md: str | None = None
    if md_path.is_file():
        raw_md = md_path.read_text(encoding="utf-8", errors="replace")
        extracted = validate_and_extract_manual_block(raw_md, source_path=md_path)
        if extracted:
            notes_from_md = ensure_canonical_notes_sections(extracted)

    if notes_from_md is not None and notes_from_store is not None:
        # Prefer inline edits in PROJECT_CONTEXT.md if they differ from the default template
        if notes_from_md != DEFAULT_MANUAL_NOTES_BLOCK:
            effective = notes_from_md
        else:
            effective = notes_from_store
    elif notes_from_md is not None:
        effective = notes_from_md
    elif notes_from_store is not None:
        effective = notes_from_store
    else:
        effective = DEFAULT_MANUAL_NOTES_BLOCK

    notes_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(notes_path, effective + "\n")
    return effective


def _insert_bullet_into_section(notes_content: str, target_heading: str, bullet: str) -> str:
    """Insert a bullet line at the end of target_heading section, removing default placeholder."""
    normalized = ensure_canonical_notes_sections(notes_content)
    placeholder = PLACEHOLDER_BY_HEADING[target_heading]
    lines = normalized.splitlines()

    all_headings = {HEADING_DECISIONS, HEADING_ISSUES, HEADING_NEXT_STEPS}
    out_lines: list[str] = []
    in_target = False
    inserted = False

    for line in lines:
        stripped = line.strip()
        if stripped in all_headings:
            if in_target and not inserted:
                if out_lines and not out_lines[-1].strip():
                    out_lines.pop()
                out_lines.append(bullet)
                out_lines.append("")
                inserted = True
            in_target = stripped == target_heading
            out_lines.append(line)
            continue

        if in_target and stripped == placeholder:
            continue

        out_lines.append(line)

    if in_target and not inserted:
        if out_lines and not out_lines[-1].strip():
            out_lines.pop()
        out_lines.append(bullet)

    return "\n".join(out_lines).strip()


def append_human_note(
    *,
    repo_root: Path,
    output_md_path: Path,
    text: str,
    note_type: str = "decision",
    scope: str | None = None,
    deterministic: bool = False,
) -> NoteRecord:
    """Append a structured developer note to .context/notes.md and sync PROJECT_CONTEXT.md."""
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ConfigError("Note text cannot be empty.")

    if note_type not in SECTION_BY_NOTE_TYPE:
        raise ConfigError(
            f"Unsupported note type '{note_type}'. Expected one of: "
            f"{', '.join(sorted(SECTION_BY_NOTE_TYPE))}."
        )

    typed_note_type: NoteType = note_type  # type: ignore[assignment]
    timestamp = (
        DETERMINISTIC_TIMESTAMP
        if deterministic
        else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    record = NoteRecord(
        note_type=typed_note_type,
        text=cleaned_text,
        scope=(scope or "global").strip() or "global",
        recorded_at=timestamp,
    )

    context_dir = repo_root / ".context"
    notes_path = context_dir / "notes.md"
    current_notes = sync_manual_notes(md_path=output_md_path, notes_path=notes_path)

    target_heading = SECTION_BY_NOTE_TYPE[typed_note_type]
    updated_notes = _insert_bullet_into_section(
        current_notes,
        target_heading,
        record.to_markdown_bullet(),
    )
    atomic_write_text(notes_path, updated_notes + "\n")

    if output_md_path.is_file():
        raw_md = output_md_path.read_text(encoding="utf-8", errors="replace")
        updated_md = replace_manual_block_in_markdown(raw_md, updated_notes)
        atomic_write_text(output_md_path, updated_md)

    manifest_path = context_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = load_manifest(context_dir)
        updated_cursors = StateCursors(
            latest_snapshot_id=manifest.state_cursors.latest_snapshot_id,
            snapshot_incorporated_journal_cursor=(
                manifest.state_cursors.snapshot_incorporated_journal_cursor
            ),
            head_journal_cursor=manifest.state_cursors.head_journal_cursor,
            unincorporated_record_count=manifest.state_cursors.unincorporated_record_count,
            notes_fingerprint=compute_text_fingerprint(updated_notes + "\n"),
        )
        updated_manifest = Manifest(
            schema_version=manifest.schema_version,
            tool_version=manifest.tool_version,
            repository_id=manifest.repository_id,
            generated_at=manifest.generated_at,
            config_fingerprint=manifest.config_fingerprint,
            git_state=manifest.git_state,
            state_cursors=updated_cursors,
            scan_summary=manifest.scan_summary,
            file_fingerprints=manifest.file_fingerprints,
        )
        write_manifest(context_dir, updated_manifest)

    return record
