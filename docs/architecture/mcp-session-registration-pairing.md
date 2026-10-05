# MCP session registration and pairing

This boundary registers the live session mailboxes introduced by the MCP
session pump and gives a future local gateway a one-use way to address one
explicit browser session. It adds no external transport, listener, pairing UI,
Project access, or persistence.

## Ownership

```text
Streamlit browser session
  owns ProjectAgentSessionRuntime
    owns mailbox + target tracker + registration authority
             │ arm one local pairing offer
             ▼
process-local ProjectAgentSessionRegistry
  keeps route metadata + weak mailbox reference + secret verifiers
             │ exact incarnation + route + one-use capability
             ▼
ProjectAgentPairedRoute
  target lookup + submit + consume + release only
             ▼
existing capacity-one session mailbox
```

The process registry is a module-owned singleton for the lifetime of the
PromptGraph Python process. It has no “current session,” first-session, or
last-registered fallback. Each Streamlit session registers a distinct opaque
route. A route ID is addressing information, not authentication; only that
session's registration authority can arm an offer for the route.

The registry retains no `Project`, `PromptLine`, session state, ScriptRunContext,
run token, capture, Project path, approval, or Apply state. It holds a weak
reference to each session mailbox, a verifier for the session registration
authority, a verifier and monotonic expiry for an armed offer, and the active
pairing generation. A weak-reference callback removes a route whose mailbox
has disappeared; explicit session cleanup unregisters it before closing the
mailbox.

## Identity lifetimes

| Identity | Lifetime and purpose |
| --- | --- |
| Process incarnation | Random opaque value for one registry/process lifetime; distinguishes stale offers after restart. It is not secret. |
| Session route | Random address for one registered browser session; stable across reruns, Project switches, Save As, and in-place edits. |
| Registration authority | Session-held in-process secret object used only to arm or unregister that session's route. It is never part of a pairing offer. |
| Target epoch | Existing mailbox routing freshness for Project activation. It changes independently and does not revoke pairing. |
| Bootstrap capability | Separate 256-bit random secret, stored in the registry only as a one-way verifier, valid for 60 seconds by default, and consumed once. |
| Pairing generation | Internal generation for one claimed connection; makes older paired handles fail after release or a later claim. |
| `request_id` / `plan_id` | Existing request correlation and Preview content identity. Neither is session identity, pairing authorization, or approval. |

The session-side offer uses contract version
`promptgraph.session-pairing-bootstrap.v1` and contains only the process
incarnation, route ID, bootstrap capability, and lifetime information. Its
`repr` redacts the capability. The capability is not logged or stored
persistently. Python cannot promise cryptographic memory erasure; the offer
object only keeps the plaintext while its session owner needs to deliver it in
a later, separately designed local descriptor.

## Pair and release behavior

Arming while unpaired issues a new offer. Re-arming replaces any earlier
unclaimed offer, so only one bootstrap verifier can be valid for a route.
Arming an already paired route returns bounded `already_paired` status without
displacing its current client.

Claiming requires an exact process incarnation, route ID, and capability. The
registry validates and consumes the offer under synchronization, so concurrent
claimants produce one winner and no replay. Wrong route, wrong incarnation,
wrong capability, and replay fail without redirecting or consuming another
route's offer. Expired offers are removed and cannot be revived; the session
owner must arm a fresh one.

The successful claimant receives only `ProjectAgentPairedRoute`, never the
mailbox or registration authority. It can read the current target epoch,
submit one JSON request against an explicit epoch, consume that request's
reply, and release its own pairing. Every operation is generation-checked.
Release invalidates that handle but keeps the session route and mailbox alive;
a new client requires a new session-side arm. Session cleanup unregisters the
route first, which invalidates offers and handles before the mailbox closes.

Pairing is between one client and one browser-session route, not between a
client and a Project. A Project switch or successful Save As changes the
existing target epoch while the paired route remains valid. The mailbox
continues to reject old-epoch work and accepts new work only for the current
epoch. The paired handle cannot synchronize epochs, claim full-app service,
complete replies, close the mailbox, or access Project/Streamlit state.

## Deferred boundary

This module uses only Python standard-library synchronization, randomness,
hashing, and weak references plus the existing mailbox abstraction. It adds no
MCP SDK, socket, Windows named pipe, filesystem descriptor, subprocess, HTTP
server, process lifecycle, or pairing UI. A later transport task must decide
how the user initiates pairing and how the one-use offer is delivered through
a protected local descriptor; this pairing lifecycle does not by itself
authenticate a Windows pipe endpoint or implement transport security.
