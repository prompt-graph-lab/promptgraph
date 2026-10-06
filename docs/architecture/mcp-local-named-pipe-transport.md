# MCP local named-pipe transport

This boundary connects an explicitly paired local client to one existing
`ProjectAgentPairedRoute`. It adds a protected pairing descriptor and a
Windows Named Pipe endpoint. The broker owns transport and pairing only; the
Streamlit session remains the sole owner of the live Project.

```text
explicit Streamlit session action
  → ProjectAgentSessionRuntime publishes its route descriptor
  → process-local WindowsNamedPipeBroker
  → one-instance, local-only named pipe
  → registry atomically claims exact route + one-use capability
  → ProjectAgentPairedRoute
  → existing capacity-one session mailbox
  → periodic fragment wakes an ordinary full-app run
  → existing request bridge services with that run's capture token
```

The broker never reads Project or Streamlit state, calls the capture gate or
request bridge, changes a target epoch, or exposes the raw mailbox. It has no
active-session fallback. Each endpoint is created for the exact route whose
session explicitly armed the offer. The process-local broker does not own a
Project and does not choose a route on behalf of a client.

## Protected offer and endpoint identity

The descriptor is a short-lived file in the local temporary directory, created
exclusively with a random filename and delete-on-close. Its Windows DACL grants
access only to the current logon SID and Local System. Remote temporary roots
are rejected. The descriptor contains the transport contract version, pipe
name, expected server PID, process incarnation, opaque route ID, one-use
capability, and offer lifetime. It contains no Project path, target epoch,
browser-session identifier, run token, prompts, approval state, or Project
data. Descriptor/result representations redact the path and capability.

Each offer receives a unique pipe name and a single-instance endpoint. The
pipe DACL uses the same logon SID and Local System, and the endpoint sets
`PIPE_REJECT_REMOTE_CLIENTS`. Before claiming the offer, the client checks
that the connected pipe server PID matches the descriptor. The claim then
supplies the exact contract version, process incarnation, route ID, and
capability to the existing registry, which enforces expiry, atomic one-use
claim, and route ownership. Wrong endpoints, altered identities, expiration,
and replay return bounded failures without exposing another route.

The descriptor is removed when the broker closes its handle after a successful
claim, expiration, route cleanup, or broker shutdown. A failed claim does not
consume a valid offer; its bounded response remains readable before that pipe
connection is closed. The endpoint remains available for a later legitimate
claim until the offer expires.

## Wire operations

After pairing, every message is one UTF-8 JSON object preceded by a four-byte
big-endian length. Duplicate keys, invalid JSON constants, unknown fields,
unsupported operations, and malformed values fail with bounded status codes.
Inbound frames are limited to 16 MiB. Responses retain the existing mailbox
and bridge payload contract and have no smaller application-level size limit;
the framing field is the only transport ceiling.

The paired client can call only:

- `current_target_epoch`;
- `submit` with an explicit target epoch and JSON request;
- `consume_reply` with the submitted epoch; and
- `release`.

The transport has no Project, Apply, approval, save, history, Streamlit,
capture, or request-bridge operation. It forwards requests through the paired
route to the existing mailbox; only the normal full-app pump reaches the
request bridge. Target epoch transitions preserve the pairing while the
mailbox rejects old-target work.

## Disconnect and route ownership

The existing pairing rule still rejects `release` as `in_flight` until the
same client consumes its terminal outcome and the mailbox is idle. If a
connected client disconnects after its submission was accepted, the endpoint
retains the submitted epoch and acts only as a caretaker: it consumes that
request's eventual outcome and retries release. This prevents a later pairing
generation from inheriting an old request or reply. It never cancels or
transfers work. If the request cannot be drained before the bounded caretaker
deadline, the endpoint fails closed and keeps that route unavailable for a
fresh offer until session cleanup or process restart.

Session cleanup unregisters the route before closing its mailbox, then stops
that session's endpoint and closes its descriptor handle. Broker shutdown
closes all owned endpoints and descriptors. Endpoints are isolated by route;
one browser session cannot address another session's mailbox.

This slice does not add an MCP stdio gateway, SDK changes, gateway launcher,
pairing UI, TCP/HTTP transport, Project I/O, or agent-callable Apply. A later
slice can forward the stdio gateway's logical MCP tools over this route without
moving Project or approval ownership out of PromptGraph.
