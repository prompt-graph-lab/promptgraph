# MCP Project capture safety gate

PoC-1d establishes a host-only, session-owned capture boundary for the live
`st.session_state.project`. It does not connect that snapshot to an MCP
process. The Streamlit session remains the sole owner of the active Project;
`core.agent_facade` remains the owner of Project observations and Batch Replace
Preview semantics.

## Why a session-state lookup is not enough

In the pinned Streamlit 1.60.0 runtime, `runner.fastReruns=True` causes an
ordinary full-app rerun to request that the current ScriptRunner stop, clear
the current-runner reference, and start a new runner immediately. The old
script can continue until it reaches a Streamlit yield point. `SafeSessionState`
locks each state operation, but the `Project` object is returned after that
lookup; the lock does not cover a later `Project.clone()`.

The test-only AppSession characterization uses barriers inside a real
`ScriptRunner` run. It demonstrates that the old run can pause partway through
`Project.clone()`, a new fast-rerun runner can mutate the live Project, and the
old clone can then contain the old prompt with the new metadata revision. A
new-run token by itself does not make that in-progress clone atomic.

With `runner.fastReruns=False`, `AppSession` queues the rerun on the existing
ScriptRunner. The next full script run starts only after the current full run
finishes. The tests characterize this serialization using the same real
Streamlit 1.60.0 AppSession/ScriptRunner path.

The inspected upstream sources are [AppSession 1.60.0](https://github.com/streamlit/streamlit/blob/1.60.0/lib/streamlit/runtime/app_session.py#L479-L501),
[SafeSessionState 1.60.0](https://github.com/streamlit/streamlit/blob/1.60.0/lib/streamlit/runtime/state/safe_session_state.py#L98-L118),
and the [fast-rerun default and warning](https://github.com/streamlit/streamlit/blob/1.60.0/lib/streamlit/config.py#L752-L762).

## Supported PromptGraph rerun mode

The repository-owned `.streamlit/config.toml` sets
`runner.fastReruns = false`. `run.bat` changes the working directory to the
repository root before launching Streamlit, so this per-project setting is
loaded for the supported launcher and for the documented manual command run
from that root. The setting establishes the supported default; it is not a
universal transaction guarantee and does not rule out every possible form of
concurrency. The tested statement is limited to the pinned Streamlit 1.60.0
normal full-app rerun path characterized above.

Streamlit merges configuration sources and permits environment variables and
command-line flags to override the project file. In particular, setting
`STREAMLIT_RUNNER_FAST_RERUNS=true` restores the overlapping-rerun mode. The
application does not force or mutate this option after startup, and
`ui.project_capture_safety` continues to check the effective runtime value at
each capture. An override to `True` therefore keeps capture fail-closed. A
change to this non-theme startup option takes effect after restarting the
Streamlit process. This runtime contract does not activate an MCP Project
provider or bridge.

## Capture contract

`ui.project_capture_safety` owns the narrow capture gate. At the beginning of
each app script execution, `app.py` creates a fresh opaque run token in that
browser session and keeps the returned token local to that execution. A
capture caller must pass that token; it cannot look up the latest token and
thereby make an old run appear current.

`capture_active_project(session_state, run_token)` succeeds only when:

- Streamlit reports `runner.fastReruns` as exactly `False` both before and
  after cloning;
- the caller's run token is the current token in that session;
- the session has an exact `core.project.Project` at `project`; and
- the same Project object is still active after `Project.clone()` completes.

It returns a host-only `CapturedProject` containing an isolated `Project`
clone, the run token, and a weak reference used only to validate source
identity. It does not contain Streamlit state. `is_capture_current` rejects a
capture from an older run, a replaced Project, or a runtime where fast reruns
are enabled. Failures have bounded reason codes; clone/config/session errors
do not expose exception text or paths. There is no fallback to saved Project
JSON.

Upstream Streamlit's own default remains `runner.fastReruns=True`; PromptGraph's
repository-owned supported default is `False`, as documented above. An
environment or command-line override that enables fast reruns makes capture
fail closed. A capture is request-scoped and represents the Project at the
clone point; it is not a durable Project identity or content revision.

The clone uses the existing `Project.clone()` deep-copy semantics. Facade
summary, Scene, Illustration/detail, and Batch Replace Preview operations run
against the snapshot only. They do not mutate the source Project or publish a
Project change. Existing Agent Facade fingerprints and Preview validation
remain authoritative for later freshness checks.

## App-side request/reply bridge

`ui.project_agent_request_bridge.dispatch_project_agent_request(...)` is the
synchronous host-side dispatcher. A caller supplies the current Streamlit
session state, its trusted app-run token, and exactly one JSON request:

```json
{"request_id":"req-1","tool":"promptgraph_project_summary","arguments":{}}
```

The outer object has exactly `request_id`, `tool`, and `arguments` keys.
`request_id` is a bounded non-empty correlation string only; it is not a
session or Project identity, revision, approval, authorization, capability, or
replay token. Arguments must be a bounded tree of ordinary JSON values. The
bridge rejects custom objects, non-string object keys, cycles, non-finite
numbers, and overlarge/deep values without invoking coercion hooks.

A completed bridge reply preserves the adapter result as-is:

```json
{"bridge_contract_version":"promptgraph.app-agent-request-bridge.v1","request_id":"req-1","status":"completed","result":{}}
```

Host failures use a distinct bounded rejection reply with
`status: "rejected"`, a bounded `reason`, and short `diagnostics`; raw
exception text, paths, reprs, Streamlit internals, and stack traces are not
returned. An adapter/domain result with `ok: false` is still a completed
bridge request because dispatch succeeded.

The bridge does not own the logical tool list or tool-specific argument rules.
`agent_adapters.mcp_adapter` remains the owner of exactly these six tools:

- `promptgraph_capabilities`
- `promptgraph_project_summary`
- `promptgraph_list_scenes`
- `promptgraph_list_illustrations`
- `promptgraph_get_illustration`
- `promptgraph_preview_batch_replace`

The bridge always delegates to `PromptGraphMCPAdapter.call_tool(...)`; the
adapter retains transport validation and tool dispatch, while
`core.agent_facade` retains observation and Preview semantics. There is no
agent-callable Apply or approval path.

The bridge supplies the adapter a request-local lazy Project provider rather
than maintaining a second list of Project-dependent tools. Capabilities,
unknown tools (including attempted Apply), and tool arguments rejected by the
adapter before provider access do not capture a Project. When the adapter asks
for a Project, the provider calls `capture_active_project(...)` on first
access, retains that successful capture only for this dispatch, and returns
the same isolated snapshot for any further provider calls in the request. The
snapshot is fixed for that request and current adapter/facade operations treat
it as read-only; the underlying `Project` type is not frozen. The provider
never recaptures midway. Capture failures become bounded host-level rejections
with the capture owner's bounded reason in diagnostics. The bridge checks
`is_capture_current(...)` after dispatch and rejects the result if run or
active-Project ownership changed before reply release.

Capture currentness proves only run ownership and active Project object
ownership. It does not detect arbitrary in-place Project edits as a content
revision. The Agent Facade's Preview fingerprint/digest remains the freshness
evidence for Preview content. Each new bridge call captures independently;
no Project or capture is retained between requests, and no response history
is kept.

This boundary has no session pairing or IPC. It adds no gateway connection,
socket, named pipe, HTTP server, process launch, filesystem loading, Project
discovery, or persistence. The trusted app caller must explicitly provide its
session state and run token; local session pairing and request transport to the
client-launched stdio gateway remain a later boundary. The run token is never
part of the request or reply.

The private release-engineering export manifest remains outside this public
repository. Before the next private public-tree export, release engineering
must classify the already-added `.streamlit/config.toml`; this note does not
create or replace that private manifest.

## Still deferred

There is no external MCP Project provider, session pairing, IPC, Project
discovery/load/save, Apply, approval custody, history, or publication in this
boundary. If a future host-owned Apply is designed, that host must preserve the
exact approved Preview envelope. `plan_id` remains content identity, not
authorization.

The characterization intentionally uses Streamlit 1.60.0 test-only internals
to drive the real AppSession/ScriptRunner overlap. Production code uses only
the public Streamlit configuration lookup; it adds no private Streamlit API.
