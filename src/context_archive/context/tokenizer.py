"""Pluggable token estimation engines (`heuristic` and optional `tiktoken`)."""

from __future__ import annotations

import importlib
import math
import re
from typing import Protocol, runtime_checkable

from context_archive.exceptions import ConfigError

_LEXEME_RE = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]")


@runtime_checkable
class TokenEstimator(Protocol):
    """Protocol for deterministic token count estimators."""

    @property
    def name(self) -> str:
        """Return canonical estimator identifier (e.g., `heuristic` or `tiktoken:cl100k_base`)."""

    def count(self, text: str) -> int:
        """Return estimated token count for `text`."""


class HeuristicTokenEstimator:
    """Zero-dependency deterministic lexical/character token estimator with 5% safety margin."""

    def __init__(self, *, safety_margin: float = 1.05) -> None:
        self._safety_margin = max(1.0, safety_margin)

    @property
    def name(self) -> str:
        return "heuristic"

    def count(self, text: str) -> int:
        if not text:
            return 0
        char_estimate = len(text) / 3.5
        lexemes = _LEXEME_RE.findall(text)
        lexeme_estimate = sum(max(1, math.ceil(len(tok) / 6.0)) for tok in lexemes)
        blended = max(char_estimate, float(lexeme_estimate) * 0.85)
        return max(1, math.ceil(blended * self._safety_margin))


class TiktokenEstimator:
    """Optional `tiktoken`-backed token estimator supporting `cl100k_base` and `o200k_base`."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        try:
            tiktoken_mod = importlib.import_module("tiktoken")
        except ImportError as exc:
            raise ConfigError(
                "Tokenizer 'tiktoken' requested, but optional package 'tiktoken' is not installed. "
                "Install via `poetry install --extras tiktoken` or use `--tokenizer heuristic`."
            ) from exc

        try:
            self._encoding = tiktoken_mod.get_encoding(encoding_name)
        except Exception as exc:
            raise ConfigError(f"Unknown tiktoken encoding '{encoding_name}': {exc}") from exc
        self._encoding_name = encoding_name

    @property
    def name(self) -> str:
        return f"tiktoken:{self._encoding_name}"

    def count(self, text: str) -> int:
        if not text:
            return 0
        tokens = self._encoding.encode(text, disallowed_special=())
        return len(tokens)


def resolve_token_estimator(spec: str = "heuristic") -> TokenEstimator:
    """Resolve a tokenizer specification string into a TokenEstimator instance."""
    cleaned = spec.strip().lower()
    if cleaned == "heuristic":
        return HeuristicTokenEstimator()
    if cleaned == "tiktoken":
        return TiktokenEstimator("cl100k_base")
    if cleaned.startswith("tiktoken:"):
        enc = cleaned.split(":", 1)[1].strip() or "cl100k_base"
        return TiktokenEstimator(enc)
    raise ConfigError(
        f"Unsupported tokenizer '{spec}'. Expected 'heuristic', 'tiktoken', "
        "or 'tiktoken:<encoding>'."
    )
