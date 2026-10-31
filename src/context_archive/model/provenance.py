"""Source provenance, evidence kind, and confidence models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from context_archive.model.ids import normalize_posix_path

EvidenceKind = Literal["deterministic", "heuristic", "human_confirmed", "external_spec"]
ConfidenceLevel = Literal["high", "medium", "low", "unknown"]


class Provenance(BaseModel):
    """Exact source location and extraction metadata for a Node or Edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(min_length=1)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    extractor: str = Field(min_length=1)
    evidence_kind: EvidenceKind = Field(default="deterministic")
    confidence: ConfidenceLevel = Field(default="high")

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            updated = dict(data)
            if isinstance(updated.get("source_path"), str):
                updated["source_path"] = normalize_posix_path(updated["source_path"])
            line_start = updated.get("line_start")
            line_end = updated.get("line_end")
            if isinstance(line_start, int) and isinstance(line_end, int) and line_end < line_start:
                updated["line_end"] = line_start
            return updated
        return data
