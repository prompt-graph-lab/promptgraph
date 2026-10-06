# MCP stable launcher and session rendezvous

The stable launcher lets an MCP client use one fixed command while still
connecting only to the exact PromptGraph browser session that a person armed.
It does not discover a current, first, or most-recent session.

```text
one Streamlit session explicitly arms
       │
       ├── existing one-use descriptor and capability
       │
       └── protected per-logon rendezvous record
                    │ fixed launcher reads one ready descriptor path
                    ▼
       agent_adapters.mcp_named_pipe_launcher
                    │
                    ▼
       existing stdio gateway → authenticated Named Pipe route
```

## Ownership and protection

`ProjectAgentSessionRuntime.arm_launcher_rendezvous()` arms only that
runtime's registered session. Its matching `launcher_rendezvous_status()` and
`disarm_launcher_rendezvous()` methods provide bounded state for a later UI.
The runtime keeps the broker associated with that exact registration; neither
the broker nor the launcher has a process-global current-session pointer.

The broker creates one deterministic rendezvous file in the current Windows
logon user's local temporary directory. Its name contains only a truncated
hash of the logon SID. The file is created atomically with the same DACL as the
pairing descriptor: the current logon SID and Local System. It is held open
with delete-on-close, so a process exit or crash releases the user-wide slot.
The exclusive create prevents another PromptGraph process or session from
silently replacing an existing target.

The record has a strict versioned JSON shape containing status, server PID,
opaque process incarnation, the protected descriptor path while ready, and a
monotonic expiry. It contains no capability, Project path, target epoch,
prompt, approval, mailbox, or session object. Once the descriptor is claimed,
the record changes to `claimed` and clears the descriptor path; the rendezvous
lease remains held for the lifetime of that paired gateway so another session
cannot take over while the first client is active. The status surface and
object representations do not include protected paths or incarnation values.

## Fixed launcher

Configure the MCP client with the stable command:

```text
python -m agent_adapters.mcp_named_pipe_launcher
```

Run that command from the PromptGraph repository root with its supported Python
environment. No transient descriptor path or project-specific argument is
needed. The launcher reads only the per-logon rendezvous, accepts only one
live, unexpired `ready` record, and passes its exact descriptor path to the
existing `serve_stdio_over_named_pipe()` gateway. That gateway retains the existing
server-PID check, one-use capability claim, MCP catalog, and route lifecycle.
There is no retry, session switch, or reconnect. Launcher diagnostics go to
stderr; stdout remains exclusively for MCP stdio messages. Errors are reduced
to bounded status codes.

The launcher imports no Project, Streamlit, capture, Apply, or approval owner.
The broker remains a transport owner and does not read Project/session state,
capture a Project, or execute the app-side bridge.

## Lifecycle and recovery

The rendezvous and descriptor use the existing short one-use pairing lifetime.
Expired or dead-process records are removed when it is safe to do so; unknown
or inaccessible records fail closed as already-owned/unavailable. A live but
expired `preparing` record remains non-ready and cannot be stolen; its owning
session must finish/disarm it, or the PromptGraph process must exit. Normal
disarm revokes the unclaimed offer, closes its route, and removes that
session's rendezvous ownership. Session cleanup unregisters the route before
closing transport resources and removes its pending rendezvous. A successful
gateway release removes its rendezvous lease. If the gateway disconnects with
work in flight, the existing Named Pipe caretaker owns that request lifecycle;
the route remains unavailable rather than transferring work to another
session or pairing generation. Delete-on-close also releases the slot when the
PromptGraph process exits.

This boundary adds no MCP SDK, runtime dependency, server daemon, UI, install
flow, Apply tool, or approval behavior. Human-facing Connect/Waiting/Connected/
Disconnect controls and client configuration guidance remain the next UI
boundary.
