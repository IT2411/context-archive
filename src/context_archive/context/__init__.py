"""context subsystem for context-archive."""

from __future__ import annotations

from context_archive.context.assembler import (
    EffectiveContext,
    assemble_effective_context,
    filter_unincorporated_records,
    validate_journal_lineage,
)
from context_archive.context.compiler import (
    RankedCandidate,
    TaskPacket,
    compile_task_context,
    tokenize_task_query,
)
from context_archive.context.differ import (
    DownstreamImpactItem,
    SemanticDiffReport,
    SymbolDiffItem,
    compute_downstream_impacts,
    compute_semantic_diff,
)
from context_archive.context.tokenizer import (
    HeuristicTokenEstimator,
    TiktokenEstimator,
    TokenEstimator,
    resolve_token_estimator,
)
from context_archive.context.verifier import (
    VerificationReport,
    VerificationStatus,
    verify_repository_freshness,
)

__all__ = [
    "DownstreamImpactItem",
    "EffectiveContext",
    "HeuristicTokenEstimator",
    "RankedCandidate",
    "SemanticDiffReport",
    "SymbolDiffItem",
    "TaskPacket",
    "TiktokenEstimator",
    "TokenEstimator",
    "VerificationReport",
    "VerificationStatus",
    "assemble_effective_context",
    "compile_task_context",
    "compute_downstream_impacts",
    "compute_semantic_diff",
    "filter_unincorporated_records",
    "resolve_token_estimator",
    "tokenize_task_query",
    "validate_journal_lineage",
    "verify_repository_freshness",
]
