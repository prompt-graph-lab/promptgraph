# PromptGraph MCP stdio transport (PoC-1c)

PoC-1c connects the existing PromptGraph MCP SDK binding to the official SDK's
stdio transport. It establishes a real subprocess-capable transport entry point
without adding an application launcher or choosing how a future host obtains
the active Project.

## Ownership

`agent_adapters.mcp_stdio_runner.serve_stdio(adapter)` is an awaitable transport
runner. The host creates the `PromptGraphMCPAdapter`, supplies its current
Project provider, and decides when to await the runner. The function builds the
existing SDK `Server` through `agent_adapters.mcp_sdk_binding.build_mcp_server`
and runs it inside the official `mcp.server.stdio.stdio_server()` context with
`Server.run(...)` and `Server.create_initialization_options()`.

The SDK context owns stdio claiming, protocol streams, and transport cleanup.
The runner has no Project singleton, discovery, filesystem load/save, Project
path argument, Project-related environment lookup, approval custody, or
persistence. It does not import Streamlit, session state, an LLM SDK, or model
code. It does not print to stdout or install logging handlers; stdout remains
reserved for MCP protocol messages.

## Exposed tools and approval boundary

The SDK server delegates to the existing SDK-independent adapter, which
continues to source its exact catalog and dispatch domain work through
`core.agent_facade`. The stdio server advertises the same six logical tools:

- `promptgraph_capabilities`
- `promptgraph_project_summary`
- `promptgraph_list_scenes`
- `promptgraph_list_illustrations`
- `promptgraph_get_illustration`
- `promptgraph_preview_batch_replace`

All tool arguments and results remain JSON values. The tools do not expose
Python Project or PromptLine objects. The catalog contains no Apply tool.
There is no agent approval signal: the host must retain the exact Preview
envelope a person approved, and `plan_id` remains a content identifier rather
than authorization. No Preview or approval state is stored in the runner.

## Scope and validation boundary

PoC-1c uses the official MCP Python SDK v2.2.0 public low-level `Server` and
`stdio_server()` APIs. It does not add a command-line entry point, select a
Project from a file/path, start an application-owned subprocess, or add
Streamable HTTP/SSE, authentication, or an internal LLM harness. The SDK's
runtime dependency and exact lock are unchanged from PoC-1b; no requirements,
license, supported-environment, or release-lock files are updated.

The subprocess integration test runs a test-only host with a synthetic Project
and uses the official SDK stdio client. It checks registered tools and schemas,
all six operations, bounded errors, Preview-only behavior, JSON results, no
Project mutation, protocol stdout integrity, and graceful subprocess exit. The
test host's synthetic Project and PID/report markers are test fixtures, not
production Project discovery or transport configuration.

For SDK API details, see the official [v2.2.0 stdio server API](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/server/stdio.py), [stdio client API](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/stdio.py), and [low-level server guide](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/docs/advanced/low-level-server.md).