"""Official MCP SDK binding for the PromptGraph logical tool surface.

This module constructs an in-memory low-level SDK ``Server`` only. It accepts
the existing exact adapter or a host-supplied explicit tool-caller seam; it
does not own Project state or choose a transport.
"""

from copy import deepcopy
import json
from typing import Any, Protocol

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)

from agent_adapters import mcp_adapter
from core.version import PRODUCT_NAME, __version__


SDK_BINDING_CONTRACT_VERSION = "promptgraph.mcp-sdk-binding.v1"
_EFFECT_META_KEY = "promptgraph/effect"


class MCPToolCaller(Protocol):
    """Narrow synchronous call seam consumed by the SDK binding."""

    def call_tool(self, name: str, arguments: object) -> dict[str, Any]: ...


def _failure(reason: str) -> dict[str, Any]:
    return {
        "binding_contract_version": SDK_BINDING_CONTRACT_VERSION,
        "ok": False,
        "reason": reason,
        "diagnostics": [{"code": reason}],
    }


def _sdk_tool(entry: dict[str, Any]) -> Tool:
    """Translate one adapter entry into public MCP protocol types."""

    return Tool(
        name=entry["name"],
        description=entry["description"],
        inputSchema=deepcopy(entry["inputSchema"]),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        _meta={_EFFECT_META_KEY: entry["effect"]},
    )


def _tool_result(payload: dict[str, Any]) -> CallToolResult:
    """Return the exact adapter payload as structured data and JSON text."""

    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return CallToolResult(
        content=[TextContent(text=text)],
        structuredContent=payload,
        isError=payload.get("ok") is False,
    )


def build_mcp_server(
    adapter: mcp_adapter.PromptGraphMCPAdapter | None = None,
    *,
    tool_caller: MCPToolCaller | None = None,
) -> Server:
    """Bind the exact adapter or explicit caller to the public SDK Server API.

    The adapter catalog remains the only source of PromptGraph tool names,
    schemas, descriptions, and effect classification. The selected caller
    owns dispatch; this function retains no Project, Preview, or approval
    state.
    """

    if adapter is not None:
        if tool_caller is not None:
            raise TypeError("Pass an adapter or a tool caller, not both.")
        if type(adapter) is not mcp_adapter.PromptGraphMCPAdapter:
            raise TypeError("A PromptGraphMCPAdapter instance is required.")
        caller = adapter
        offload_tool_calls = False
    elif tool_caller is not None and callable(getattr(tool_caller, "call_tool", None)):
        caller = tool_caller
        offload_tool_calls = True
    else:
        raise TypeError("A PromptGraphMCPAdapter or explicit MCP tool caller is required.")

    catalog = mcp_adapter.get_tool_catalog()

    async def list_tools(
        _context: ServerRequestContext,
        _params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        # Construct fresh public SDK models so the server does not share a
        # mutable Tool/schema object with its own catalog snapshot.
        return ListToolsResult(tools=[_sdk_tool(entry) for entry in catalog])

    async def call_tool(
        _context: ServerRequestContext,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        try:
            arguments = {} if params.arguments is None else params.arguments
            if offload_tool_calls:
                # Remote callers may wait for a mailbox reply for many
                # seconds. Keep that synchronous wait off the MCP event loop,
                # and retain the worker until its bounded call completes if
                # the SDK request is cancelled.
                payload = await anyio.to_thread.run_sync(
                    caller.call_tool,
                    params.name,
                    arguments,
                    abandon_on_cancel=False,
                )
            else:
                # Preserve the established in-process adapter path.
                payload = caller.call_tool(params.name, arguments)
            if type(payload) is not dict:
                payload = _failure("invalid_adapter_result")
            return _tool_result(payload)
        except Exception:
            # The SDK-visible result must not contain provider, host, or
            # implementation exception text.
            return _tool_result(_failure("binding_call_failed"))

    return Server(
        PRODUCT_NAME,
        version=__version__,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
