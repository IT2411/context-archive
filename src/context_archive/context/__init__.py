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
from context_archive.context.reconciler import (
    DivergenceReport,
    check_for_git_conflict_markers,
    detect_journal_forks,
    merge_human_notes_blocks,
    reconcile_divergent_journal,
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
    "DivergenceReport",
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
    "check_for_git_conflict_markers",
    "compile_task_context",
    "compute_downstream_impacts",
    "compute_semantic_diff",
    "detect_journal_forks",
    "filter_unincorporated_records",
    "merge_human_notes_blocks",
    "reconcile_divergent_journal",
    "resolve_token_estimator",
    "tokenize_task_query",
    "validate_journal_lineage",
    "verify_repository_freshness",
]
