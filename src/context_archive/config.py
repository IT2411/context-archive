"""Typed configuration models, TOML loader, and deterministic fingerprinting."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context_archive.exceptions import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_EXCLUDE_GLOBS: tuple[str, ...] = (
    ".git/**",
    ".context/**",
    ".venv/**",
    "venv/**",
    "env/**",
    ".tox/**",
    ".nox/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    "target/**",
    "__pycache__/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    ".pytest_cache/**",
)

DEFAULT_SECRET_GLOBS: tuple[str, ...] = (
    ".env",
    ".env.*",
    "!**/.env.example",
    "!**/.env.template",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/id_rsa*",
    "**/*credentials*.json",
    ".aws/**",
    ".ssh/**",
)


class ProjectConfig(BaseModel):
    """[project] configuration section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(default="unnamed-project", min_length=1)
    description: str = Field(default="")
    primary_languages: tuple[str, ...] = Field(default=("python",))


class ScannerConfig(BaseModel):
    """[scanner] configuration section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_file_size_bytes: int = Field(default=1_048_576, ge=1024)
    max_depth: int = Field(default=25, ge=1, le=200)
    respect_gitignore: bool = Field(default=True)
    exclude_globs: tuple[str, ...] = Field(default=DEFAULT_EXCLUDE_GLOBS)
    secret_globs: tuple[str, ...] = Field(default=DEFAULT_SECRET_GLOBS)


class JournalConfig(BaseModel):
    """[journal] configuration section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    auto_compact_record_threshold: int = Field(default=25, ge=1)
    auto_compact_token_threshold: int = Field(default=4000, ge=100)


class ContextConfig(BaseModel):
    """[context] configuration section."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_max_tokens: int = Field(default=8000, ge=256)
    default_tokenizer: str = Field(default="heuristic", min_length=1)
    output_path: str = Field(default="PROJECT_CONTEXT.md", min_length=1)
    commit_context_dir: bool = Field(default=True)


class CtxaConfig(BaseModel):
    """Root configuration model for context-archive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    journal: JournalConfig = Field(default_factory=JournalConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)

    def fingerprint(self) -> str:
        """Return a deterministic SHA-256 fingerprint (`sha256:<hex>`) of the configuration."""
        canonical_payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical_payload).hexdigest()
        return f"sha256:{digest}"


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override dictionary into base dictionary."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_toml_file(path: Path) -> dict[str, Any]:
    """Parse a TOML file or raise ConfigError (Exit 3)."""
    try:
        content = path.read_text(encoding="utf-8")
        data = tomllib.loads(content)
    except OSError as exc:
        raise ConfigError(f"Failed to read configuration file '{path}': {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Malformed TOML in '{path}': {exc}") from exc
    return dict(data)


def load_config(
    repo_root: Path,
    *,
    cli_overrides: dict[str, Any] | None = None,
) -> CtxaConfig:
    """Load and validate configuration with strict precedence.

    Precedence order (highest to lowest):
    1. `cli_overrides`
    2. `<repo_root>/.ctxa.toml`
    3. `<repo_root>/pyproject.toml` (`[tool.ctxa]`)
    4. Built-in defaults (including project name fallback to repo folder name)
    """
    merged_raw: dict[str, Any] = {
        "project": {"name": repo_root.resolve().name or "unnamed-project"}
    }

    pyproject_path = repo_root / "pyproject.toml"
    if pyproject_path.is_file():
        pyproject_data = _parse_toml_file(pyproject_path)
        project_meta = pyproject_data.get("project")
        if isinstance(project_meta, dict):
            if isinstance(project_meta.get("name"), str) and project_meta["name"].strip():
                merged_raw["project"]["name"] = project_meta["name"].strip()
            if isinstance(project_meta.get("description"), str):
                merged_raw["project"]["description"] = project_meta["description"]

        tool_table = pyproject_data.get("tool")
        if isinstance(tool_table, dict) and "ctxa" in tool_table:
            ctxa_table = tool_table["ctxa"]
            if not isinstance(ctxa_table, dict):
                raise ConfigError(
                    f"Invalid [tool.ctxa] section in '{pyproject_path}': expected a table."
                )
            merged_raw = _deep_merge_dicts(merged_raw, ctxa_table)

    ctxa_toml_path = repo_root / ".ctxa.toml"
    if ctxa_toml_path.is_file():
        ctxa_toml_data = _parse_toml_file(ctxa_toml_path)
        merged_raw = _deep_merge_dicts(merged_raw, ctxa_toml_data)

    if cli_overrides:
        merged_raw = _deep_merge_dicts(merged_raw, cli_overrides)

    try:
        return CtxaConfig.model_validate(merged_raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid context-archive configuration: {exc}") from exc


def render_default_ctxa_toml(config: CtxaConfig) -> str:
    """Render a clean default .ctxa.toml file from a CtxaConfig instance."""
    langs = ", ".join(f'"{lang}"' for lang in config.project.primary_languages)
    return (
        "[project]\n"
        f'name = "{config.project.name}"\n'
        f'description = "{config.project.description}"\n'
        f"primary_languages = [{langs}]\n\n"
        "[scanner]\n"
        f"max_file_size_bytes = {config.scanner.max_file_size_bytes}\n"
        f"max_depth = {config.scanner.max_depth}\n"
        f"respect_gitignore = {'true' if config.scanner.respect_gitignore else 'false'}\n\n"
        "[journal]\n"
        f"auto_compact_record_threshold = {config.journal.auto_compact_record_threshold}\n"
        f"auto_compact_token_threshold = {config.journal.auto_compact_token_threshold}\n\n"
        "[context]\n"
        f"default_max_tokens = {config.context.default_max_tokens}\n"
        f'default_tokenizer = "{config.context.default_tokenizer}"\n'
        f'output_path = "{config.context.output_path}"\n'
        f"commit_context_dir = {'true' if config.context.commit_context_dir else 'false'}\n"
    )
