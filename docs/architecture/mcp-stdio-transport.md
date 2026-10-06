# PromptGraph MCP stdio transport (PoC-1c and PoC-1d)

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
`core.agent_facade`. The stdio server advertises the same seven logical tools:

- `promptgraph_capabilities`
- `promptgraph_project_summary`
- `promptgraph_list_scenes`
- `promptgraph_list_illustrations`
- `promptgraph_search_illustrations`
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

The PoC-1c subprocess integration test runs a test-only host with a synthetic
Project and uses the official SDK stdio client. It checks registered tools and
schemas, all seven operations, bounded errors, Preview-only behavior, JSON
results, no Project mutation, protocol stdout integrity, and graceful
subprocess exit. The test host's synthetic Project and PID/report markers are
test fixtures, not production Project discovery or transport configuration.

## Named Pipe gateway (PoC-1d)

`agent_adapters.mcp_sdk_binding.build_mcp_server(adapter)` preserves the
original exact `PromptGraphMCPAdapter` contract. A separate explicit
`tool_caller=` keyword accepts the small `MCPToolCaller` protocol for a
transport proxy. Both paths use the same `mcp_adapter.get_tool_catalog()` and
the same SDK result mapping; the adapter's domain semantics and schemas remain
authoritative.

`agent_adapters.mcp_named_pipe_gateway.serve_stdio_over_named_pipe(path)`
connects one protected pairing descriptor through
`LocalNamedPipeClient.connect_from_descriptor_file()`, binds that single
client as the tool caller, runs the existing stdio runner, then attempts an
explicit release on shutdown. It does not read a Project, access Streamlit or
session state, capture a Project, choose a session, or own Apply/approval. If a
call is still in flight at shutdown, the existing release rule refuses release
and closing the pipe leaves cleanup to the endpoint's #123 caretaker. No
request or reply is transferred to a later pairing.

Each tool call reads the route's current target epoch once, submits the
existing `{request_id, tool, arguments}` bridge envelope once, and waits for
that epoch's mailbox outcome. A stale result is returned as a bounded MCP
error; the gateway does not retry, switch routes, or resubmit against a newer
target. A completed bridge result is returned unchanged. Bridge rejection
reasons are reduced to a small allowlist, while arbitrary transport and host
exception details are not returned to the MCP client. The gateway adds no
response-size limit beyond the existing transport framing contract.

The PoC-1d integration test uses the official MCP stdio client against a
test-only gateway subprocess, a real authenticated Windows Named Pipe, and a
test host pump calling the existing full-run service boundary. It covers
tool/schema discovery, a Project-independent capability call, Project summary
and Batch Replace Preview against the active host Project, unchanged results,
Project immutability, and graceful gateway shutdown/re-pairability. The
fixture's host loop and Project are test-only and do not add production
launcher, pairing UI, or Project loading behavior.

PoC-1d added no SDK/runtime dependency or production process/CLI entry point.
PoC-1e adds a stable fixed-command launcher and per-logon explicit-session
rendezvous; see [MCP stable launcher and session rendezvous](mcp-stable-launcher.md).
Pairing UI, client configuration guidance, automatic reconnect, and broader
host lifecycle integration remain separate work.

For SDK API details, see the official [v2.2.0 stdio server API](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/server/stdio.py), [stdio client API](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/src/mcp/client/stdio.py), and [low-level server guide](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/docs/advanced/low-level-server.md).
