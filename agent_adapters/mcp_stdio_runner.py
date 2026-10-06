"""Run an explicit PromptGraph tool caller over the official stdio transport.

This is an awaitable transport boundary, not an application entry point. The
in-process host supplies a PromptGraphMCPAdapter; a separately paired gateway
may supply the narrow tool-caller protocol. This runner owns neither Project
selection nor a local transport connection.
"""

from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from agent_adapters.mcp_sdk_binding import MCPToolCaller, build_mcp_server
from mcp.server.stdio import stdio_server


async def serve_stdio(
    adapter: PromptGraphMCPAdapter | None = None,
    *,
    tool_caller: MCPToolCaller | None = None,
) -> None:
    """Serve the existing PromptGraph MCP catalog on process stdio streams.

    The SDK context owns stdio claiming, protocol framing, and stream cleanup.
    This function neither creates a Project provider nor starts a process.
    ``tool_caller`` is an explicit SDK seam used by the Named Pipe gateway;
    the legacy adapter argument remains exact-type checked.
    """

    server = build_mcp_server(adapter, tool_caller=tool_caller)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
