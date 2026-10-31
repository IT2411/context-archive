"""Unit tests for HeuristicTokenEstimator, TiktokenEstimator fallback, and query tokenization."""

from __future__ import annotations

import pytest

from context_archive.context.compiler import tokenize_task_query
from context_archive.context.tokenizer import (
    HeuristicTokenEstimator,
    resolve_token_estimator,
)
from context_archive.exceptions import ConfigError


@pytest.mark.unit
def test_heuristic_token_estimator_determinism_and_bounds() -> None:
    """Verify HeuristicTokenEstimator returns 0 for empty string and deterministic counts."""
    est = resolve_token_estimator("heuristic")
    assert isinstance(est, HeuristicTokenEstimator)
    assert est.name == "heuristic"
    assert est.count("") == 0

    sample = "def calculate_total(items: list[LineItem], tax_rate: Decimal) -> Decimal:"
    c1 = est.count(sample)
    c2 = est.count(sample)
    assert c1 == c2
    assert c1 > 10


@pytest.mark.unit
def test_resolve_token_estimator_errors_on_unknown_or_missing_tiktoken() -> None:
    """Verify unknown tokenizer specs raise ConfigError (Exit 3)."""
    with pytest.raises(ConfigError):
        resolve_token_estimator("unknown_tokenizer")

    # When tiktoken is not installed in the base environment, requesting it raises ConfigError
    with pytest.raises(ConfigError):
        resolve_token_estimator("tiktoken:cl100k_base")


@pytest.mark.unit
def test_tokenize_task_query_splits_camel_and_snake_case() -> None:
    """Verify camelCase, PascalCase, snake_case, and paths are split into normalized terms."""
    terms = tokenize_task_query(
        "Update calculate_total and OrderCreateRequest in src/calculator.py"
    )
    assert "calculate_total" in terms
    assert "calculate" in terms
    assert "total" in terms
    assert "order" in terms
    assert "create" in terms
    assert "request" in terms
    assert "calculator" in terms
