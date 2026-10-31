"""Read-only Model Context Protocol (MCP) server over stdio implementing SRS FR-17."""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

from context_archive import __version__
from context_archive.config import CtxaConfig, load_config
from context_archive.context.assembler import assemble_effective_context
from context_archive.context.compiler import compile_task_context
from context_archive.context.differ import compute_downstream_impacts
from context_archive.context.verifier import verify_repository_freshness
from context_archive.exceptions import ConfigError

if TYPE_CHECKING:
    from pathlib import Path
    from typing import TextIO

MCP_TOOLS_SPEC: tuple[dict[str, Any], ...] = (
    {
        "name": "get_project_overview",
        "description": "Return repository identity, freshness status, cursors, and module map.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "lookup_symbol",
        "description": "Search canonical graph nodes by symbol name, qualified name, or path.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "get_change_impact",
        "description": "Compute downstream callers, importers, and tests for a symbol or path.",
        "inputSchema": {
            "type": "object",
            "required": ["symbol_or_path"],
            "properties": {
                "symbol_or_path": {"type": "string"},
                "max_hops": {"type": "integer", "default": 2},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "query_journal",
        "description": "Query recent append-only change journal records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
                "category": {"type": ["string", "null"], "default": None},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "compile_task_context",
        "description": "Compile a ranked, token-budgeted context packet for a task.",
        "inputSchema": {
            "type": "object",
            "required": ["task"],
            "properties": {
                "task": {"type": "string"},
                "max_tokens": {"type": "integer", "default": 6000},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "verify_freshness",
        "description": "Verify whether .context/ and PROJECT_CONTEXT.md match the live repo.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
)


class ReadOnlyMcpDispatcher:
    """Strictly read-only MCP tool handler and JSON-RPC 2.0 stdio dispatcher."""

    def __init__(self, repo_root: Path, config: CtxaConfig | None = None) -> None:
        self.repo_root = repo_root.resolve()
        self.config = config or load_config(self.repo_root)

    def _freshness_envelope(self) -> dict[str, Any]:
        """Build mandatory freshness and cursor metadata included in every MCP tool response."""
        ver = verify_repository_freshness(self.repo_root, self.config)
        effective = assemble_effective_context(self.repo_root, self.config)
        cursors = effective.manifest.state_cursors
        return {
            "freshness_status": ver.status,
            "is_fresh": ver.status == "CURRENT",
            "stale_reasons": list(ver.reasons),
            "repository_id": effective.manifest.repository_id,
            "snapshot_id": cursors.latest_snapshot_id,
            "journal_cursor": cursors.head_journal_cursor,
        }

    def get_project_overview(self) -> dict[str, Any]:
        """Return project overview, module map with provenance, and active human notes."""
        envelope = self._freshness_envelope()
        effective = assemble_effective_context(self.repo_root, self.config)
        modules = [
            {
                "id": n.id,
                "qualified_name": n.qualified_name,
                "docstring_summary": n.attributes.get("docstring_summary", ""),
                "provenance": n.provenance.model_dump(mode="json"),
            }
            for n in effective.graph.nodes
            if n.kind == "Module"
        ]
        contracts = [
            {
                "id": n.id,
                "kind": n.kind,
                "qualified_name": n.qualified_name,
                "signature": n.attributes.get("signature", ""),
                "provenance": n.provenance.model_dump(mode="json"),
            }
            for n in effective.graph.nodes
            if n.kind in ("Endpoint", "Schema", "DataEntity")
        ]
        return {
            **envelope,
            "project_name": self.config.project.name,
            "description": self.config.project.description,
            "modules": modules,
            "contracts": contracts,
            "manual_notes": effective.manual_notes,
        }

    def lookup_symbol(self, query: str) -> dict[str, Any]:
        """Search graph symbols matching `query` with full source provenance."""
        envelope = self._freshness_envelope()
        effective = assemble_effective_context(self.repo_root, self.config)
        q_low = query.strip().lower()
        matches: list[dict[str, Any]] = []
        for node in effective.graph.nodes:
            if node.kind == "File":
                continue
            if (
                q_low in node.name.lower()
                or q_low in node.qualified_name.lower()
                or q_low in node.provenance.source_path.lower()
            ):
                matches.append(
                    {
                        "id": node.id,
                        "kind": node.kind,
                        "name": node.name,
                        "qualified_name": node.qualified_name,
                        "attributes": node.attributes,
                        "provenance": node.provenance.model_dump(mode="json"),
                    }
                )
        return {
            **envelope,
            "query": query,
            "match_count": len(matches),
            "matches": matches,
        }

    def get_change_impact(self, symbol_or_path: str, max_hops: int = 2) -> dict[str, Any]:
        """Return direct symbol matches and N-hop downstream impacted callers/tests."""
        envelope = self._freshness_envelope()
        effective = assemble_effective_context(self.repo_root, self.config)
        target_q = symbol_or_path.strip()
        seed_nodes = [
            n
            for n in effective.graph.nodes
            if n.id == target_q
            or n.qualified_name == target_q
            or n.name == target_q
            or n.provenance.source_path == target_q
        ]
        seed_ids = {n.id for n in seed_nodes if n.kind != "File"}
        impacts = compute_downstream_impacts(
            effective.graph,
            seed_ids,
            max_hops=max(1, min(5, max_hops)),
        )
        return {
            **envelope,
            "query": symbol_or_path,
            "seed_symbols": [
                {
                    "id": n.id,
                    "qualified_name": n.qualified_name,
                    "kind": n.kind,
                    "provenance": n.provenance.model_dump(mode="json"),
                }
                for n in seed_nodes
                if n.kind != "File"
            ],
            "downstream_impacts": [imp.model_dump(mode="json") for imp in impacts],
        }

    def query_journal(self, limit: int = 10, category: str | None = None) -> dict[str, Any]:
        """Return recent journal records, optionally filtered by category."""
        envelope = self._freshness_envelope()
        effective = assemble_effective_context(self.repo_root, self.config)
        records = list(reversed(effective.all_journal_records))
        if category:
            records = [r for r in records if r.category == category]
        sliced = records[: max(1, limit)]
        return {
            **envelope,
            "total_records": len(effective.all_journal_records),
            "returned_count": len(sliced),
            "records": [r.model_dump(mode="json") for r in sliced],
        }

    def compile_task_context(self, task: str, max_tokens: int = 6000) -> dict[str, Any]:
        """Compile a token-bounded TaskPacket for `task`."""
        envelope = self._freshness_envelope()
        packet = compile_task_context(
            repo_root=self.repo_root,
            config=self.config,
            task=task,
            max_tokens=max_tokens,
        )
        return {
            **envelope,
            "packet": packet.model_dump(mode="json"),
        }

    def verify_freshness(self) -> dict[str, Any]:
        """Return full freshness VerificationReport."""
        envelope = self._freshness_envelope()
        ver = verify_repository_freshness(self.repo_root, self.config)
        return {
            **envelope,
            "verification_report": ver.model_dump(mode="json"),
        }

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch a read-only MCP tool call by name."""
        args = arguments or {}
        if name == "get_project_overview":
            return self.get_project_overview()
        if name == "lookup_symbol":
            return self.lookup_symbol(str(args.get("query", "")))
        if name == "get_change_impact":
            return self.get_change_impact(
                str(args.get("symbol_or_path", "")),
                int(args.get("max_hops", 2)),
            )
        if name == "query_journal":
            cat = args.get("category")
            return self.query_journal(
                limit=int(args.get("limit", 10)),
                category=str(cat) if isinstance(cat, str) else None,
            )
        if name == "compile_task_context":
            return self.compile_task_context(
                task=str(args.get("task", "")),
                max_tokens=int(args.get("max_tokens", 6000)),
            )
        if name == "verify_freshness":
            return self.verify_freshness()
        raise ConfigError(f"Unknown or unsupported MCP tool '{name}'.")

    def handle_jsonrpc_message(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process a single JSON-RPC 2.0 MCP message and return the response object."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params") or {}

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "context-archive", "version": __version__},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": list(MCP_TOOLS_SPEC)},
            }

        if method == "tools/call":
            tool_name = str(params.get("name", ""))
            tool_args = params.get("arguments")
            try:
                payload = self.call_tool(
                    tool_name,
                    tool_args if isinstance(tool_args, dict) else {},
                )
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(payload, sort_keys=True),
                            }
                        ],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def run_stdio_mcp_server(
    repo_root: Path,
    config: CtxaConfig,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> None:
    """Run the read-only MCP JSON-RPC 2.0 server over stdin/stdout."""
    dispatcher = ReadOnlyMcpDispatcher(repo_root, config)
    in_stream = input_stream or sys.stdin
    out_stream = output_stream or sys.stdout

    for raw_line in in_stream:
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            req = json.loads(stripped)
            if not isinstance(req, dict):
                continue
            resp = dispatcher.handle_jsonrpc_message(req)
            if resp is not None:
                out_stream.write(json.dumps(resp, sort_keys=True) + "\n")
                out_stream.flush()
        except ValueError:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            out_stream.write(json.dumps(err_resp, sort_keys=True) + "\n")
            out_stream.flush()
