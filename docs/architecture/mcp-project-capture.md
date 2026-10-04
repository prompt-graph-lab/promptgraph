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

The app's current default is `runner.fastReruns=True`, so captures fail closed
by default. This PR does not change that application behavior or add a setting
control. A future host that needs live capture must explicitly launch with
`runner.fastReruns=false`, or first provide a shared serialization protocol
that every concurrent Project writer participates in. A capture is
request-scoped and represents the Project at the clone point; it is not a
durable Project identity or content revision.

The clone uses the existing `Project.clone()` deep-copy semantics. Facade
summary, Scene, Illustration/detail, and Batch Replace Preview operations run
against the snapshot only. They do not mutate the source Project or publish a
Project change. Existing Agent Facade fingerprints and Preview validation
remain authoritative for later freshness checks.

## Still deferred

There is no MCP Project provider, IPC, Project discovery/load/save, Apply,
approval custody, history, or publication in this boundary. Before any future
bridge is activated, its host must keep the Streamlit session as the active
Project owner, obtain an isolated request-scoped capture under the proven
serialization precondition, and separately preserve the exact approved
Preview envelope for any future host-owned Apply. `plan_id` remains content
identity, not authorization.

The characterization intentionally uses Streamlit 1.60.0 test-only internals
to drive the real AppSession/ScriptRunner overlap. Production code uses only
the public Streamlit configuration lookup; it adds no private Streamlit API.
