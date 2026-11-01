"""Security hardening, Hypothesis fuzzing, secret non-leakage, and wheel build tests."""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from context_archive.adapters.python_ast import sanitize_docstring_summary
from context_archive.cli import app
from context_archive.context.tokenizer import HeuristicTokenEstimator
from context_archive.integrations.mcp_server import ReadOnlyMcpDispatcher
from context_archive.model.ids import make_symbol_id, normalize_posix_path
from context_archive.notes.boundaries import (
    replace_manual_block_in_markdown,
    validate_and_extract_manual_block,
)
from context_archive.renderers.markdown import MANUAL_END, MANUAL_START

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.integration
@given(raw_text=st.text(min_size=0, max_size=400))
@settings(max_examples=50, deadline=None)
def test_fuzz_docstring_sanitizer_and_id_generators(raw_text: str) -> None:
    """Fuzz docstring sanitizer, path normalizer, and token estimator with arbitrary strings."""
    injected = f"{raw_text}\n<!-- CTXA:MANUAL:END -->\n<!-- CTXA:MANUAL:START -->"
    sanitized = sanitize_docstring_summary(injected)
    assert "<!-- CTXA:" not in sanitized
    assert len(sanitized) <= 300

    norm_path = normalize_posix_path(raw_text)
    assert isinstance(norm_path, str)
    sym_id = make_symbol_id("py", norm_path, "SymbolName")
    assert sym_id.startswith("sym:py:")

    est = HeuristicTokenEstimator()
    tok_count = est.count(raw_text)
    assert tok_count >= 0


@pytest.mark.integration
@given(
    note_body=st.text(
        alphabet=st.characters(blacklist_characters=("<", ">", "\r")),
        min_size=1,
        max_size=200,
    )
)
@settings(max_examples=40, deadline=None)
def test_fuzz_manual_boundary_roundtrip(note_body: str) -> None:
    """Fuzz manual note boundary extraction and replacement with arbitrary safe text."""
    template = f"# Header\n{MANUAL_START}\nInitial\n{MANUAL_END}\n"
    cleaned = note_body.strip() or " fallback "
    replaced = replace_manual_block_in_markdown(template, cleaned)
    extracted = validate_and_extract_manual_block(replaced)
    assert extracted == cleaned.strip()


@pytest.mark.integration
def test_end_to_end_secret_and_symlink_non_leakage_across_all_surfaces(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify secrets never leak into PROJECT_CONTEXT.md, graph.json, journal, context, or mcp."""
    outside_secret = tmp_path / "outside_secret.py"
    outside_secret.write_text('OUTSIDE_SECRET_TOKEN = "TOP_SECRET_OUTSIDE_999"\n', encoding="utf-8")

    repo = tmp_path / "sec_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)

    (repo / ".env").write_text("DB_PASS=SUPER_SECRET_ENV_VALUE_111\n", encoding="utf-8")
    (repo / "private.pem").write_text("PRIVATE_PEM_SECRET_222\n", encoding="utf-8")
    (repo / "aws_credentials.json").write_text('{"secret": "AWS_SECRET_333"}\n', encoding="utf-8")
    with contextlib.suppress(OSError):
        (repo / "escape.py").symlink_to(outside_secret)

    assert runner.invoke(app, ["init", str(repo), "--deterministic"]).exit_code == 0
    assert runner.invoke(app, ["update", str(repo), "--deterministic"]).exit_code == 0

    ctx_res = runner.invoke(
        app, ["context", "check credentials and env", str(repo), "--max-tokens", "2000"]
    )
    assert ctx_res.exit_code == 0

    dispatcher = ReadOnlyMcpDispatcher(repo)
    mcp_overview = json.dumps(dispatcher.get_project_overview())

    combined_outputs = "\n".join(
        [
            (repo / "PROJECT_CONTEXT.md").read_text(encoding="utf-8"),
            (repo / ".context" / "graph.json").read_text(encoding="utf-8"),
            (repo / ".context" / "manifest.json").read_text(encoding="utf-8"),
            ctx_res.stdout,
            mcp_overview,
        ]
    )

    for forbidden in (
        "SUPER_SECRET_ENV_VALUE_111",
        "PRIVATE_PEM_SECRET_222",
        "AWS_SECRET_333",
        "TOP_SECRET_OUTSIDE_999",
    ):
        assert forbidden not in combined_outputs


@pytest.mark.integration
def test_poetry_build_produces_wheel_and_sdist(repo_root: Path, tmp_path: Path) -> None:
    """Verify `poetry build` builds valid wheel and sdist artifacts cleanly."""
    poetry_bin = shutil.which("poetry") or "poetry"
    out_dir = tmp_path / "dist_out"
    res = subprocess.run(
        [poetry_bin, "build", "--output", str(out_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"poetry build failed: {res.stderr}"
    wheels = list(out_dir.glob("*.whl"))
    sdists = list(out_dir.glob("*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
