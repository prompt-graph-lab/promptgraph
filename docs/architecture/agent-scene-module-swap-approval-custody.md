# Agent Scene Module Swap approval custody

This document records a code-backed design audit for turning an agent-created
single-Scene Module Swap Preview into a human-reviewed, host-only Apply. It is
design guidance only. At the audited baseline, PromptGraph has the agent-facing
Preview and the existing human Selected Routes Module Swap flow, but no
agent-review proposal store, approval panel, or agent-preview Apply lifecycle.

The audit inspected public PromptGraph at `775086e4941782a6bfac28fb16ab6a4c063bde3a`
(PR #135 merge), including the owners and tests listed below. Current code and
characterization tests remain authoritative if a later implementation differs.

## Decision

Keep `promptgraph_preview_scene_module_swap` observational. Add a distinct,
explicit request to place one exact Preview into a host-owned review queue. The
host recomputes the Preview against the active Project, checks the caller's
Preview content identity, and retains the newly computed safe envelope in the
current Streamlit session. A separate host UI presents the full impact and
collects a one-time human decision. A later host lifecycle recomputes the exact
Preview and calls the existing core Apply owner with one explicit Scene.

There is no agent-callable Apply. Neither `plan_id`, a proposal ID, nor an
agent-supplied `approved` field grants authority. The existing Preview remains
unchanged and creates no pending item.

## Existing owners and evidence

| Owner | Current responsibility and relevant evidence |
| --- | --- |
| `core.agent_facade.preview_scene_module_swap` | Validates an explicit active Scene, source and target Module names, and strict/loose mode. It calls the authoritative planner for exactly `[scene_id]`, then returns a bounded JSON-safe envelope. `source_fingerprint` is the core planner signature; `projection_digest` covers the complete ordered projection; `plan_id` identifies the whole envelope. At most 100 review rows are returned while the planner allows up to 1,000 targets. |
| `core.module_swap_selected_routes.build_selected_routes_module_swap_plan` | Owns Module Swap semantics and freshness signature. The signature binds selected Scene/Illustration structure, target prompt and token state, relevant image-reference state, Module Library, Project source-directory value, mode, `project_path`, and `disabled_modules`. The agent facade deliberately calls it with `project_path=""` and `disabled_modules=None`. |
| `core.module_swap_selected_routes.apply_selected_routes_module_swap` | Rebuilds the plan against the supplied Project and expected signature, then deep-copies the Project, rebuilds the plan on the clone, applies only planned target Illustration IDs, validates the result, and returns a replacement Project. A stale or failed operation returns no replacement Project. |
| `ui.module_swap_selected_routes_lifecycle.apply_and_publish_selected_routes_module_swap` | Owns the existing human Selected Routes Apply publication. It reads the shared `gallery_selected_route_ids`, current path, and disabled Modules; after a successful core Apply it calls history, replaces the session Project, restores focus, saves, then consumes `module_swap_preview`. It is not an exact agent-Preview custodian and must not be reused by mutating Gallery selection to impersonate one. |
| `agent_adapters.mcp_adapter` | Owns the catalog and request-shape boundary. `promptgraph_preview_scene_module_swap` is a reviewed Preview tool; there is no approval or Apply tool. The adapter delegates to the facade and does not retain the Project or Preview. |
| `ui.project_agent_request_bridge.dispatch_project_agent_request` | Validates the request envelope, lazily obtains a request-scoped captured Project when needed, calls the adapter, confirms capture/run identity remains current, and returns the adapter result unchanged. It retains no result or human approval state. |
| `ui.project_agent_session_mailbox.ProjectAgentSessionMailbox` | Holds at most one detached request and one reply/outcome for the explicit session target epoch. `complete()` publishes the bridge reply as `reply_ready`; the paired producer consumes it once through `consume_reply()`. A target switch or deadline before consumption can stale or expire the reply. The mailbox contains no Project, Streamlit state, Preview custody, or Apply state. |
| `ui.project_agent_session_pump.service_project_agent_session_request` | Runs only at explicit points in a normal full-app run. It synchronizes target epoch, claims one request, calls the bridge, synchronizes again, and completes the mailbox. The public periodic fragment only wakes an app rerun. The pump does not currently publish an agent result into host session state. |
| `ui.project_agent_session_registry` / `ProjectAgentPairedRoute` | Addresses one explicitly paired mailbox and exposes only target lookup, submit, consume, and release. It does not retain a Project or expose session state or approval authority. |
| `ui.project_capture_safety` | Captures a clone of the exact active Project using the current full-run token and serialized rerun configuration, then checks that the same active Project/run remains current. It is a request-safety gate, not a revision counter for in-place edits. |
| `ui.mcp_connection_ui.render_mcp_connection_sidebar` | Shows and controls the current session's MCP connection. Its fragment is connection-only and intentionally does not own Project data or approval. |
| `app.py` and `ui.gallery_selected_routes_session.reset_gallery_selected_route_session_state` | `app.py` previews and confirms the human Selected Routes operation. Project replacement and route reset clear the human `module_swap_preview` and confirmation. No agent proposal key exists today. |
| `tests/test_module_swap_selected_routes_lifecycle.py` and `tests/test_module_swap_selected_routes_confirmation_round_trip.py` | Characterize human publication order and no-publication on stale/failure/no-op, plus resetting confirmation when its preview signature becomes stale. Request bridge, mailbox, pump, registry, and capture tests characterize their separate owners. |

The existing human renderer currently limits visible line previews. It also has
access to raw planner entries, which can include local image paths and Module
snapshots. Neither that truncated renderer nor its raw preview object is an
acceptable agent-review record.

## Current request and human Apply paths

Agent request path:

```text
MCP client → stdio gateway → paired route → session mailbox
           → fragment wake → normal full-app run
           → request bridge → MCP adapter → agent facade Preview
           → exact bridge reply → mailbox reply_ready
           → gateway consumes reply → MCP client
```

The host currently has no retained copy after the dispatch returns. The exact
reply belongs to the mailbox until the gateway consumes it; consumption is
external to Streamlit and cannot itself be the moment that mutates host state.

Existing human Selected Routes path:

```text
Gallery-selected Scene IDs → app.py core Preview → session module_swap_preview
  → human confirmation → selected-routes lifecycle
  → core fresh-signature check + clone Apply
  → history → Project replacement → focus restore → save
```

The shared Gallery selection, host path, and disabled-Module state are part of
that human operation's signature and inputs. An agent request instead names one
Scene explicitly and its facade uses an empty `project_path` and no disabled
Module set. Reusing the human lifecycle unchanged would therefore apply a
different intent or require changing shared selection state.

## Authority and trust matrix

| Action or data | Owner | Rule |
| --- | --- | --- |
| Build an exploratory Preview | Agent facade through the MCP adapter | Read-only; no queueing, approval, or mutation. |
| Request human review | Explicit MCP review-request operation plus host lifecycle | One exact Scene intent and an expected Preview content ID; no approval authority. |
| Capture the active Project | Normal full-app run and capture gate | Request-local clone only; no Project path or run token leaves the host. |
| Retain the proposal | Session-local host approval custodian | One bounded record for this browser session; no Project/PromptLine/graph objects and no process-global current proposal. |
| Render changes and decide | Human through host UI | Review every target and explicitly approve, reject, or dismiss. MCP arguments cannot make this decision. |
| Recheck and Apply | Dedicated host lifecycle calling `core.module_swap_selected_routes` | One explicit Scene; exact current Preview match; core clone-based Apply; never an MCP tool. |
| Publish a successful replacement | Host application | History, Project replacement, Gallery/focus sanitation, then autosave and bounded status. |
| Pair or transport the MCP client | Existing session registry and Named Pipe owners | Pairing addresses a session; it does not authorize a Project mutation. |

For a future implementation, keep the new owners narrow: a
`ui.agent_scene_module_swap_approval_lifecycle` owns the session-local proposal
record and its prepare/promote/abort/consume transitions; a separate
`ui.agent_review_panel` renders the record and accepts direct human decisions;
`app.py` only wires the panel and lifecycle callbacks into normal full-app
runs. The mailbox pump may coordinate proposal commit with its reply outcome,
but it does not become the proposal store. `core.agent_facade` remains pure.

## Proposal origin

Two origins were considered:

1. Treat every `promptgraph_preview_scene_module_swap` call as a review proposal.
   This avoids adding a tool, but turns ordinary exploration and repeated
   previews into host notifications and competing approval items. The existing
   tool is explicitly a Preview, so changing it to have session side effects
   would be surprising.
2. Keep that Preview pure and add a separate explicit tool, proposed name
   `promptgraph_request_scene_module_swap_review`. This makes the human handoff
   intentional and idempotency/staleness rules explicit.

Choose option 2. The review request repeats the explicit Scene, Module names,
and mode, and includes the `plan_id` returned by the Preview as an
`expected_plan_id` content precondition. During the normal full-app request,
the host recomputes `preview_scene_module_swap` from the current captured
Project. If the fresh `plan_id` differs, return a bounded stale response and
create no proposal. If it matches, the host stores its own freshly computed
envelope; it does not store an envelope supplied by the agent. The content ID
is a compare-and-swap value only, never authorization.

Normal Preview calls continue to have zero side effects. A no-op, invalid,
over-limit, or stale review request cannot create an actionable proposal.

## Proposed versioned host record

The record is session-local and transient. The version below is a design
contract, not a current persisted schema:

```json
{
  "record_version": "promptgraph.agent-scene-module-swap-review.v1",
  "proposal_id": "<host-generated opaque identifier>",
  "state": "pending",
  "request_id": "<bounded correlation value>",
  "target_epoch": "<opaque current session epoch>",
  "request": {
    "scene_id": "<explicit Scene separator id>",
    "source_module_name": "<name>",
    "target_module_name": "<name>",
    "match_mode": "strict",
    "expected_plan_id": "<Preview content identity>"
  },
  "preview_envelope": "<exact host-computed promptgraph.agent-facade.v1 envelope>",
  "created_at_monotonic": 0.0,
  "expires_at_monotonic": 900.0,
  "decision": null,
  "outcome": null
}
```

`proposal_id` is an address for display and one-shot UI state, not a bearer
secret. `request_id` is correlation only. `preview_envelope` is the exact
safe facade envelope; it contains no raw Module definition or local image path.
The custodian must validate its exact schema and JSON types before storage and
must reject rather than truncate if its encoded byte size exceeds a documented
custody cap. Determine that cap with a max-shape fixture against the facade's
100 visible rows, per-text limits, and token-delta limits before implementation.

Recommended initial limits are one active proposal per browser session and a
15-minute monotonic expiry. A duplicate request for the same correlation and
content precondition returns the existing pending acknowledgment without
extending the expiry. A different review request while one is pending receives
`review_already_pending`; it never replaces or transfers the record. After a
terminal decision, retain only a small bounded tombstone/status record, not the
envelope, so callbacks cannot replay the same proposal.

The record must not contain a `Project`, `PromptLine`, Module snapshot/body,
graph, image path, Project path, capture token, raw mailbox, pairing
capability, or general session object. Store no filesystem state and write no
receipt to Project metadata.

## State and mailbox completion boundary

Recommended states:

```text
absent → prepared → pending → applying → applied
                         ├──→ rejected
                         ├──→ dismissed
                         ├──→ expired
                         ├──→ stale
                         └──→ apply_failed
```

`prepared` is host-internal and cannot be rendered or approved. The full-run
host dispatcher computes the candidate and verifies the capture is still
current. It stages the candidate as `prepared`, then asks the mailbox to
publish the bounded review-request acknowledgment. Only if
`ProjectAgentSessionMailbox.complete()` returns `completed` for the same
request, target epoch, and deadline does the host lifecycle promote that
candidate to `pending` before the full-app run returns. Otherwise it discards
the candidate. Thus mailbox completion is the proposal's authoritative
creation boundary; later reply consumption by the gateway is not.

This ordering makes a delivered acknowledgment follow a host-staged exact
Preview while keeping an uncompleted, stale, expired, or malformed request
non-actionable. If the app is interrupted with a `prepared` record, the next
full run discards it; it must never be mistaken for a pending human decision.
An ordinary Preview has no candidate and follows the existing bridge path.

## Identity and freshness

The proposal is bound to three separate facts:

- **Session route and target epoch:** the existing mailbox route identifies one
  browser session. A Project object replacement, no-Project/Project change, or
  Project path change advances the target epoch. The route survives those
  transitions, but an old proposal does not.
- **Explicit intent:** `scene_id`, `source_module_name`,
  `target_module_name`, and `match_mode` are normalized from the review request.
  Never infer them from current Gallery selection, focused Illustration, or
  another tab.
- **Content identity:** the exact safe Preview envelope, its `plan_id`,
  `source_fingerprint`, and complete `projection_digest` identify the reviewed
  content. Target epoch does not detect in-place edits, so recompute the
  envelope before displaying an actionable confirmation and again immediately
  before Apply.

Freshness comparisons must use the same facade context that produced the
agent's Preview. In particular, call the Selected Routes planner with exactly
`[scene_id]`, `project_path=""`, `disabled_modules=None`, and the explicit
mode. Do not silently substitute the human Gallery operation's host path,
disabled-Module set, or selected routes; those are different planner inputs.
Require exact full-envelope equality after fresh recomputation, not only a
matching `plan_id` or digest. The core Apply then independently checks the
planner signature on the active Project and on its clone.

The existing capture gate protects the request-run identity and Project object
identity, not the content revision. The facade/core fingerprint and the
host-side re-preview are the content freshness checks.

## Human review, approval, and Apply

The host review screen must show the complete impact for all planned target
Illustrations, not only the facade's first 100 agent-visible rows. The facade
currently accepts up to 1,000 targets. Build a host-only display
projection from a fresh planner result on each render and paginate or otherwise
let the human inspect every row. Keep raw planner entries ephemeral; they can
contain Module snapshots and image paths. Display only the explicit Scene,
Module names, strict/loose mode, counts, every positive-prompt Before/After,
changed/no-op status, token delta, and drift-risk summary. Explain that the
operation is prompt-only and Negative Prompts, images, Candidates, Variants,
and generation state are unchanged.

Before enabling the human approval control, recompute the facade envelope and
require exact equality with the stored envelope and target epoch. Bind the
confirmation widget to both `proposal_id` and `plan_id` (or an equivalent
complete-envelope digest); clear it on any content or epoch change. A checkbox
is only the UI's staging state. The explicit host Approve action is the human
decision and can be consumed once.

On that action, the host lifecycle rechecks the target epoch and recomputes the
full envelope one last time. It rejects stale content and no-op plans. For a
valid match it calls `apply_selected_routes_module_swap` with only
`[scene_id]`, the exact explicit Module names/mode, and the envelope's
`source_fingerprint` as `expected_signature`, preserving the agent facade's
`project_path=""` and `disabled_modules=None` planner context. It must not
change `gallery_selected_route_ids` to fit the existing human lifecycle.

No Apply result, raw core plan, or replacement Project is sent back to the
MCP client. An immediate bounded tool acknowledgment may confirm only that a
host proposal was queued, not that it was approved or applied. Any later agent
notification or decision-status tool is a separate protocol decision.

## Cancellation, expiry, and target changes

- A human may reject or dismiss a pending proposal. Clear its confirmation and
  consume the proposal so the same widget callback cannot apply it later.
- A target epoch change invalidates the proposal and confirmation. Show a
  bounded stale notice, then require a fresh Preview and explicit new review
  request for the new active Project. The pairing/session route remains intact.
- In-place edits do not advance target epoch. Exact facade re-preview still
  makes the proposal stale before it can be approved or applied.
- A normal paired-pipe disconnect does not approve, cancel, or transfer a
  completed host proposal. Keep it available to the same session's human until
  dismissal or expiry; never expose it to a later pairing generation. An
  explicit host Disconnect/Disarm action cancels pending proposals.
- Session close removes session state naturally; registry cleanup continues to
  unregister the route and close the mailbox. Do not rely on a process-global
  store or `on_release` as durable approval history.
- A second distinct request cannot replace a pending proposal. Duplicate
  completion cannot extend its expiry or create another active copy.
- Expired, rejected, dismissed, stale, applied, and failed records cannot be
  replayed through their prior one-shot confirmation state.

These rules are additional host proposal semantics. They do not change existing
mailbox deadlines, transport caretaker behavior, session pairing, or Project
target epoch policy.

## UI placement

Add a dedicated, persistent **Agent Review** surface in the normal Streamlit
application run. It should be reachable regardless of the active Gallery
operation and must never borrow the current Gallery selection. The existing
MCP Connection sidebar can link to or badge this surface, but its
connection-only fragment should remain free of Project and proposal state.
Likewise, do not place approval work inside a polling fragment: a fragment may
refresh display state, but only a normal full-app run and a direct human action
may approve or Apply.

Render clear states for no proposal, waiting for review, stale, expired,
completed, and bounded failure. For pending work, show explicit **Approve and
Apply**, **Reject**, and **Dismiss** controls. Never hide omitted target rows
behind a digest, and do not make approval depend on changing Scene selection,
focus, or another Gallery operation.

## Disclosure and security boundaries

Agent-visible data remains the existing safe facade Preview plus a bounded
review-request acknowledgment. It must not include Module bodies/snapshots,
arbitrary metadata, raw planner diagnostics, image paths, Project paths,
host session keys, target epoch, run token, proposal storage internals, or
pairing material. Error responses stay bounded and omit exception text.

Host-only session data may contain the exact safe envelope and opaque local
proposal bookkeeping, but no Project graph or object references. The UI's
display projection is rebuilt locally and strips local paths and raw metadata.
The human button is the sole authorization source. A model echoing the Preview,
`plan_id`, `proposal_id`, or an `approved` property never substitutes for it.

The MCP transport, gateway, adapter catalog, registry, and mailbox stay
transport/dispatch owners. They do not gain Project access, approval authority,
or Apply access. No new filesystem path, network endpoint, persistence, or
global current-session mechanism is introduced.

## Recommended implementation slices and acceptance

### PR-A: session-local proposal custody

Add the explicit review-request route, bounded versioned record, one-slot
deduplication, expiry, prepare/commit/abort integration with full-run mailbox
completion, and target-epoch invalidation. Do not add Apply or UI yet.

Acceptance: ordinary Preview never creates state; matching expected plan ID
stores the exact host-computed envelope only after successful mailbox
completion; mismatch/expired/stale completion stores none; duplicate and
second-request behavior is deterministic; size/TTL bounds reject without
truncating; no Project or raw planner object survives the request run; target
switch and session cleanup isolate proposals.

### PR-B: human review surface

Add a dedicated host panel, complete paginated Before/After review, proposal
states, Reject/Dismiss, and one-time confirmation binding. Do not Apply in this
slice.

Acceptance: every target row is inspectable, including a Scene over 100 rows;
raw paths and Module definitions are not rendered; normal Gallery selection,
focus, connection state, and existing human Module Swap controls remain
unchanged; confirmation resets on stale/changed proposal and cannot be set by
an MCP argument.

### PR-C: revalidation and host-only Apply/publication

Add a dedicated approval lifecycle that recomputes exact intent, invokes the
core Apply owner, and publishes only its successful replacement Project.

Acceptance: stale envelope, epoch, or Project changes; replay; denied/expired
proposal; no-op; and core failure make no history, Project, Gallery, or save
publication. A success applies exactly one explicit Scene and publishes in the
order: pre-Apply history, Project replacement, selection/focus sanitation,
autosave, then terminal proposal/result state. Autosave failure keeps the
successful in-memory Apply and history, reports save failure, consumes the
proposal, and cannot repeat the mutation. Duplicate approval callbacks apply
at most once.

### PR-D: Streamlit/MCP end-to-end characterization

Exercise the public Streamlit 1.60.0 session route, stdio gateway, mailbox,
review request, host review, and host-only Apply using the real product owners.

Acceptance: test one and multiple sessions, target switch/Save As between
Preview and approval, in-place prompt/Module edits, busy mailbox, timeout,
paired-client disconnect, explicit disconnect, session close, stale proposal,
successful publication, autosave failure, and no duplicate Apply. The gateway
must remain free of Project/session/approval ownership.

## Open decisions and go/no-go

Recommended defaults are one pending proposal per browser session, a
15-minute monotonic expiry, and no asynchronous decision notification to the
agent. If the client needs the human's later decision, design a separate
session-bound status/result operation; do not leave a synchronous MCP call
blocked while a human considers the Preview or send a result through a new
pairing generation.

Before PR-A, derive and test the encoded-byte ceiling for a maximal valid
facade envelope rather than inventing a truncation rule. Keep the existing
1,000-target planner cap and require the human surface to render all targets.
These are implementation limits, not authorization shortcuts.

**Go:** proceed in PR-A through PR-D as separate reviewed slices after this
design is accepted. **No-go:** do not combine custody, UI, and Apply into one
change; do not reinterpret an exploratory Preview as a review request; do not
route Apply through MCP; do not reuse shared Gallery selection as agent intent;
and do not treat any identifier, digest, or agent assertion as human approval.
