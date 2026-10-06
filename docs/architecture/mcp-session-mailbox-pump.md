# MCP session mailbox and Streamlit request pump

PoC-1e adds a session-scoped, capacity-one request mailbox and a public
Streamlit fragment that wakes the ordinary app run. It does not add a transport
or make an MCP process the Project owner.

## Ownership

```text
future test producer / later local broker
                  │ submit JSON for explicit target epoch
                  ▼
per-browser-session ProjectAgentSessionMailbox
                  │ one wake request
                  ▼
public non-parallel Streamlit fragment
                  │ st.rerun(scope="app")
                  ▼
normal full-app run and its local capture token
                  │ request-scoped capture
                  ▼
dispatch_project_agent_request(...)
                  │ exact bridge reply
                  ▼
mailbox reply, consumed once
```

The mailbox is transport-neutral standard-library code. It contains no
Project, PromptLine, Streamlit session, ScriptRunContext, capture, run token,
Project path, approval, or Apply state. A `ProjectTargetTracker` sits beside
the mailbox inside the session-scoped runtime. It keeps only a weak reference
for object identity and a normalized path string for activation comparison; it
does not own or load a Project. The path is routing freshness evidence, not an
authorization token or content revision.

`st.cache_resource(scope="session", on_release=...)` creates one runtime per
browser session. The release callback closes the mailbox and drops tracker
identity state without accessing session state. Streamlit does not guarantee
that this callback runs on process shutdown, crash, or kill; no such guarantee
is made here. The mailbox is not a process-global active-session registry.

## Target epochs and request lifecycle

An initial target observation establishes an opaque epoch. Replacing the
Project object, switching between no Project and a Project, or changing
`current_project_path` advances it. In-place prompt/content edits on the same
Project and path do not. Successful Save As changes the path while retaining
the Project object, so it advances the epoch; failed or refused Save As leaves
the path unchanged and does not. The session route itself remains alive across
these changes.

Every submission supplies the mailbox's current target epoch. A request for an
older epoch is rejected and never redirected to a newly active Project. A
target change invalidates pending, wake-requested, and service-due requests
before dispatch. A request already executing is not preempted; after the
bridge returns, its reply is discarded as stale. A completed reply that has
not been consumed is also replaced with a stale-target outcome if the target
changes. The consumer can present its submitted epoch but cannot change the
mailbox's current epoch.

There is at most one outstanding request across pending, wake requested,
executing, and reply ready. A second submission receives `busy`. The mailbox
does not queue or replace requests. Accepted requests are detached from exact
built-in JSON values and use the same generic request size/depth bounds as the
existing bridge; the bridge remains the owner of envelope and tool validation.
Replies are detached as JSON-shaped built-in values without a second payload
size limit, preserving the existing bridge's output contract.

Requests use a monotonic deadline, 60 seconds by default and at most 120
seconds. Expired work is not executed. Running bridge work is not cancelled;
if its deadline passes before publication, its result is discarded as
`expired`. There is no tool retry. The fragment may repeat a wake-up with a
bounded backoff only while an unclaimed request still needs a full-app run;
that never calls the bridge or repeats an executed tool.

## Fragment and service context

The fragment uses `st.fragment(run_every=1.0, parallel=False)`. Each tick
checks only the current mailbox. It atomically marks a wake request once, then
uses public `st.rerun(scope="app")`. On a full-app run, the first inline
fragment tick is suppressed, so a request already pending at run start does
not create a rerun loop. A request that arrives after that run begins can
still be claimed at its explicit service point without requiring another
rerun. If a run exits before reaching a service point, a later fragment tick
may request another full run for the still-unclaimed request.

The one-second cadence is a polling choice, not a scheduling or response-time
guarantee. Background-tab throttling, browser suspension, disconnection, or
closure can delay or prevent the wake-up; the request then expires or its
session resource is released.

Only an ordinary full-app run services work. After core session state is
initialized, `app.py` synchronizes the live Project/path target. Before each
supported service point it synchronizes the target again and claims one
request, then releases mailbox locks before calling the existing
`dispatch_project_agent_request(st.session_state, current_run_token, request)`.
The run token remains a local value from that app execution and is never
retained by the mailbox or fragment. A stale run token is rejected before
service. After dispatch, the app synchronizes target again and publishes the
exact bridge reply only if the target and deadline remain current.

The mailbox keeps its `completed` / `busy` / `stale_target` / `expired` /
`session_closed` / `internal_error` outcomes separate from the existing bridge
reply. It does not rewrite bridge contract fields, retain response history, or
allow Apply. The request id remains correlation only; `plan_id` remains
content identity, not authorization.

Process-local session registration and one-use pairing are defined in
[MCP session registration and pairing](mcp-session-registration-pairing.md).
The Windows local transport is described in
[MCP local named-pipe transport](mcp-local-named-pipe-transport.md). It
receives only the paired route handle and submits/consumes through that handle;
it does not call the Project bridge, read Streamlit state, capture a Project,
access the raw mailbox, or change target epochs. Any Apply approval flow
remains outside these slices.
