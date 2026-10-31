"""Unit tests for the read-only MCP server tools, provenance, and JSON-RPC stdio protocol."""

from __future__ import annotations

import io
import json
import shutil
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from context_archive.cli import app, execute_full_handoff, execute_incremental_update
from context_archive.config import load_config
from context_archive.exceptions import ConfigError
from context_archive.integrations.mcp_server import (
    MCP_TOOLS_SPEC,
    ReadOnlyMcpDispatcher,
    run_stdio_mcp_server,
)

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.mark.unit
def test_mcp_all_six_tools_provenance_and_stale_warning(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Invoke all 6 MCP tools, verify provenance/freshness fields, and test dirty-tree detection."""
    repo = tmp_path / "mcp_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)

    dispatcher = ReadOnlyMcpDispatcher(repo, cfg)

    # 1. get_project_overview
    overview = dispatcher.call_tool("get_project_overview")
    assert overview["freshness_status"] == "CURRENT"
    assert overview["is_fresh"] is True
    assert overview["snapshot_id"] == "snapshot-0001"
    assert len(overview["modules"]) >= 3
    assert "source_path" in overview["modules"][0]["provenance"]

    # 2. lookup_symbol
    lookup = dispatcher.call_tool("lookup_symbol", {"query": "calculate_total"})
    assert lookup["match_count"] >= 1
    first_match = lookup["matches"][0]
    assert first_match["provenance"]["source_path"] == "src/sample_lib/calculator.py"

    # 3. get_change_impact
    impact = dispatcher.call_tool(
        "get_change_impact",
        {"symbol_or_path": "sample_lib.utils.round_currency", "max_hops": 2},
    )
    assert len(impact["seed_symbols"]) == 1
    downstream_ids = {d["target_id"] for d in impact["downstream_impacts"]}
    assert "sym:py:src/sample_lib/calculator.py:calculate_total" in downstream_ids

    # 4. Perform an edit + update so query_journal has records
    calc_path = repo / "src" / "sample_lib" / "calculator.py"
    calc_path.write_text(
        calc_path.read_text(encoding="utf-8") + "\n# journaled edit\n",
        encoding="utf-8",
    )
    execute_incremental_update(repo, cfg, developer_message="MCP journal test", deterministic=True)

    journal_res = dispatcher.call_tool("query_journal", {"limit": 5})
    assert journal_res["total_records"] == 1
    assert journal_res["records"][0]["intent"]["summary"] == "MCP journal test"
    # Because handoff hasn't re-rendered PROJECT_CONTEXT.md yet, freshness is STALE_JOURNALED
    assert journal_res["freshness_status"] == "STALE_JOURNALED"

    # 5. compile_task_context
    task_res = dispatcher.call_tool(
        "compile_task_context",
        {"task": "Update calculate_total rounding", "max_tokens": 2000},
    )
    assert task_res["packet"]["estimated_tokens"] <= 2000

    # 6. verify_freshness after dirtying a file
    calc_path.write_text(
        calc_path.read_text(encoding="utf-8") + "\n# unrecorded dirty edit\n",
        encoding="utf-8",
    )
    ver_res = dispatcher.call_tool("verify_freshness")
    assert ver_res["freshness_status"] == "STALE_UNRECORDED"
    assert ver_res["is_fresh"] is False

    with pytest.raises(ConfigError):
        dispatcher.call_tool("write_file_or_exec_shell")


@pytest.mark.unit
def test_mcp_stdio_jsonrpc_protocol_loop(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    """Verify stdio JSON-RPC 2.0 server handles initialize, tools/list, and tools/call."""
    repo = tmp_path / "mcp_stdio_repo"
    shutil.copytree(fixtures_dir / "fixture_py_lib", repo)
    cfg = load_config(repo)
    execute_full_handoff(repo, cfg, deterministic=True)

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "lookup_symbol", "arguments": {"query": "LineItem"}},
        },
        {"jsonrpc": "2.0", "id": 4, "method": "unknown/method"},
    ]
    in_buf = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n{bad-json\n")
    out_buf = io.StringIO()

    run_stdio_mcp_server(repo, cfg, input_stream=in_buf, output_stream=out_buf)

    responses = [json.loads(line) for line in out_buf.getvalue().splitlines() if line.strip()]
    # 5 responses (notifications/initialized produces no response, plus 1 parse error)
    assert len(responses) == 5
    assert responses[0]["id"] == 1
    assert responses[0]["result"]["serverInfo"]["name"] == "context-archive"
    assert responses[1]["id"] == 2
    assert len(responses[1]["result"]["tools"]) == len(MCP_TOOLS_SPEC)
    assert responses[2]["id"] == 3
    assert responses[2]["result"]["isError"] is False
    assert responses[3]["id"] == 4
    assert "error" in responses[3]
    assert responses[4]["error"]["code"] == -32700

    # Also test CLI `ctxa mcp` with empty stdin
    cli_res = runner.invoke(app, ["mcp", str(repo)], input="")
    assert cli_res.exit_code == 0
