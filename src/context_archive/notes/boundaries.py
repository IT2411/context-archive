"""Sentinel boundary parser and backup recovery for PROJECT_CONTEXT.md (ADR 003)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_archive.exceptions import IntegrityError
from context_archive.lock import atomic_write_text
from context_archive.renderers.markdown import MANUAL_END

if TYPE_CHECKING:
    from pathlib import Path

MANUAL_START_PREFIX = "<!-- CTXA:MANUAL:START"


def validate_and_extract_manual_block(
    markdown_text: str, *, source_path: Path | None = None
) -> str:
    """Validate CTXA:MANUAL sentinel markers and return the inner manual block text.

    If markers are missing, duplicated, or inverted, writes `<source_path>.bak` (when
    `source_path` is provided) and raises `IntegrityError` (Exit 4).
    """
    start_count = markdown_text.count(MANUAL_START_PREFIX)
    end_count = markdown_text.count(MANUAL_END)

    start_idx = markdown_text.find(MANUAL_START_PREFIX)
    end_idx = markdown_text.find(MANUAL_END)

    # Find closing '-->' of the start marker
    start_close_idx = markdown_text.find("-->", start_idx) if start_idx != -1 else -1

    is_valid = (
        start_count == 1
        and end_count == 1
        and start_idx != -1
        and start_close_idx != -1
        and end_idx != -1
        and start_close_idx < end_idx
    )

    if not is_valid:
        if source_path is not None and source_path.is_file():
            bak_path = source_path.with_name(f"{source_path.name}.bak")
            atomic_write_text(bak_path, markdown_text)
        loc = f" in '{source_path}'" if source_path is not None else ""
        raise IntegrityError(
            f"Corrupted or missing CTXA:MANUAL sentinel boundaries{loc}. "
            "Backed up existing file to '.bak' and aborted overwrite."
        )

    inner = markdown_text[start_close_idx + len("-->") : end_idx]
    return inner.strip()


def replace_manual_block_in_markdown(markdown_text: str, new_manual_block: str) -> str:
    """Replace the content inside CTXA:MANUAL markers of an existing PROJECT_CONTEXT.md."""
    _ = validate_and_extract_manual_block(markdown_text)
    start_idx = markdown_text.find(MANUAL_START_PREFIX)
    start_close_idx = markdown_text.find("-->", start_idx) + len("-->")
    end_idx = markdown_text.find(MANUAL_END)

    prefix = markdown_text[:start_close_idx]
    suffix = markdown_text[end_idx:]
    cleaned_block = new_manual_block.strip()
    return f"{prefix}\n{cleaned_block}\n{suffix}"
