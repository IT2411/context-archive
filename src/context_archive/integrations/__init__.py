"""integrations subsystem for context-archive."""

from __future__ import annotations

from context_archive.integrations.mcp_server import (
    MCP_TOOLS_SPEC,
    ReadOnlyMcpDispatcher,
    run_stdio_mcp_server,
)

__all__ = [
    "MCP_TOOLS_SPEC",
    "ReadOnlyMcpDispatcher",
    "run_stdio_mcp_server",
]
