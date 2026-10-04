"""Run a host-owned MCP adapter over the official SDK stdio transport.

This is an awaitable transport boundary, not an application entry point. The
host remains responsible for creating the adapter and supplying its current
Project provider before invoking this function.
"""

from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from agent_adapters.mcp_sdk_binding import build_mcp_server
from mcp.server.stdio import stdio_server


async def serve_stdio(adapter: PromptGraphMCPAdapter) -> None:
    """Serve the existing PromptGraph MCP catalog on the process stdio streams.

    The SDK context owns stdio claiming, protocol framing, and stream cleanup.
    This function neither creates a Project provider nor starts a process.
    """

    server = build_mcp_server(adapter)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )