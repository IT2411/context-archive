"""Unit tests for sentinel boundary parsing, backup recovery, and notes management."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from context_archive.exceptions import ConfigError, IntegrityError
from context_archive.notes.boundaries import (
    replace_manual_block_in_markdown,
    validate_and_extract_manual_block,
)
from context_archive.notes.manager import (
    append_human_note,
    ensure_canonical_notes_sections,
)
from context_archive.renderers.markdown import MANUAL_END, MANUAL_START

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
def test_validate_and_replace_manual_block_success() -> None:
    """Verify valid CTXA:MANUAL markers are parsed and updated cleanly."""
    doc = f"# Header\n{MANUAL_START}\n# 11. Decisions\n- Keep it simple\n{MANUAL_END}\n"
    extracted = validate_and_extract_manual_block(doc)
    assert "- Keep it simple" in extracted

    updated = replace_manual_block_in_markdown(doc, "# 11. Decisions\n- New rule")
    assert "- New rule" in updated
    assert "- Keep it simple" not in updated


@pytest.mark.unit
def test_corrupt_boundaries_raise_integrity_error_and_write_backup(tmp_path: Path) -> None:
    """Verify missing, duplicate, or inverted markers write .bak and raise IntegrityError."""
    md_path = tmp_path / "PROJECT_CONTEXT.md"

    # 1. Missing end marker
    broken_1 = f"# Doc\n{MANUAL_START}\nUser custom note that must not be lost"
    md_path.write_text(broken_1, encoding="utf-8")
    with pytest.raises(IntegrityError):
        validate_and_extract_manual_block(broken_1, source_path=md_path)
    bak_path = tmp_path / "PROJECT_CONTEXT.md.bak"
    assert bak_path.is_file()
    assert "User custom note that must not be lost" in bak_path.read_text(encoding="utf-8")

    # 2. Inverted markers (END before START)
    inverted = f"{MANUAL_END}\nsome text\n{MANUAL_START}\n"
    with pytest.raises(IntegrityError):
        validate_and_extract_manual_block(inverted)

    # 3. Duplicate start markers
    duplicated = f"{MANUAL_START}\n{MANUAL_START}\ntext\n{MANUAL_END}"
    with pytest.raises(IntegrityError):
        validate_and_extract_manual_block(duplicated)


@pytest.mark.unit
def test_append_human_note_categories_and_validation(tmp_path: Path) -> None:
    """Verify all 5 note types populate their corresponding sections and validate inputs."""
    md_path = tmp_path / "PROJECT_CONTEXT.md"

    rec_dec = append_human_note(
        repo_root=tmp_path,
        output_md_path=md_path,
        text="Use Decimal for currency math",
        note_type="decision",
        scope="src/calculator.py",
        deterministic=True,
    )
    assert rec_dec.origin == "developer_confirmed"

    append_human_note(
        repo_root=tmp_path,
        output_md_path=md_path,
        text="Never call external APIs during scan",
        note_type="constraint",
        deterministic=True,
    )
    append_human_note(
        repo_root=tmp_path,
        output_md_path=md_path,
        text="Wildcard imports reduce static call resolution",
        note_type="issue",
        deterministic=True,
    )
    append_human_note(
        repo_root=tmp_path,
        output_md_path=md_path,
        text="Should we add Rust support in v2?",
        note_type="question",
        deterministic=True,
    )
    append_human_note(
        repo_root=tmp_path,
        output_md_path=md_path,
        text="Implement Phase 6 append-only journal",
        note_type="next_step",
        deterministic=True,
    )

    notes_text = (tmp_path / ".context" / "notes.md").read_text(encoding="utf-8")
    assert "**[DECISION]** (`scope: src/calculator.py`" in notes_text
    assert "**[CONSTRAINT]**" in notes_text
    assert "**[ISSUE]**" in notes_text
    assert "**[QUESTION]**" in notes_text
    assert "**[NEXT_STEP]**" in notes_text

    # Default placeholders should be replaced once real notes exist in each section
    assert "No architectural decisions or constraints recorded yet" not in notes_text
    assert "No known issues or open questions recorded yet" not in notes_text
    assert "No pending work items recorded yet" not in notes_text

    # Partial heading repair check
    repaired = ensure_canonical_notes_sections("# 11. Custom\n- item")
    assert "# 12. Known Issues" in repaired
    assert "# 13. Pending Work" in repaired

    with pytest.raises(ConfigError):
        append_human_note(repo_root=tmp_path, output_md_path=md_path, text="   ")
    with pytest.raises(ConfigError):
        append_human_note(
            repo_root=tmp_path, output_md_path=md_path, text="ok", note_type="bad_type"
        )
