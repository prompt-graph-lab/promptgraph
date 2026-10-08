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
| `agent_adapters.mcp_adapter` | Owns the catalog and request-shape boundary. `promptgraph_preview_scene_module_swap` is a reviewed Preview tool; there is no Apply tool. The adapter delegates to the facade and does not retain the Project or Preview. The proposed review-request tool's catalog schema and non-capturing transport validation also belong here; a direct adapter invocation cannot accept or retain a proposal. |
| `ui.project_agent_request_bridge.dispatch_project_agent_request` | Validates the request envelope, lazily obtains a request-scoped captured Project when needed, calls the adapter, confirms capture/run identity remains current, and returns the adapter result unchanged. The proposed review-request path must dispatch to the host review lifecycle after adapter-owned argument validation; it must not use an adapter success result as proof of custody. |
| `ui.project_agent_session_mailbox.ProjectAgentSessionMailbox` | Holds at most one detached request and one reply/outcome for the explicit session target epoch. `complete()` publishes the bridge reply as `reply_ready`; the paired producer consumes it once through `consume_reply()`. A target switch or deadline before consumption can stale or expire the reply. For a future review request only, a narrow completion primitive must coordinate reply visibility with a host callback while retaining mailbox ownership; the mailbox still contains no Project, Streamlit state, proposal, or Apply state. |
| `ui.project_agent_session_pump.service_project_agent_session_request` | Runs only at explicit points in a normal full-app run. It synchronizes target epoch, claims one request, calls the bridge, synchronizes again, and completes the mailbox. The public periodic fragment only wakes an app rerun. For a prepared review request, the pump is the completion coordinator; proposal data stays in the host lifecycle and the mailbox receives only the bounded reply. |
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

Choose option 2. The new MCP tool is
`promptgraph_request_scene_module_swap_review`. It repeats the explicit Scene,
Module names, and mode, and includes the `plan_id` returned by the Preview as
an `expected_plan_id` content precondition. During the normal full-app request,
the host recomputes `preview_scene_module_swap` from the current captured
Project. If the fresh `plan_id` differs, return a bounded stale response and
create no proposal. If it matches, the host stores its own freshly computed
envelope; it does not store an envelope supplied by the agent. The content ID
is a compare-and-swap value only, never authorization.

Normal Preview calls continue to have zero side effects. A no-op, invalid,
over-limit, or stale review request cannot create an actionable proposal.

## Proposed review-request dispatch path

The catalog and the trusted host operation have different responsibilities.
The catalog-driven MCP client sees the new tool, but the adapter itself cannot
accept a proposal. Preserve the following single path:

```text
MCP client
  → stdio gateway and exact paired route
  → capacity-one mailbox submit
  → periodic fragment wake only
  → normal full-app run claims the request
  → request bridge validates the outer envelope
  → adapter-owned, non-capturing validation of the review tool arguments
  → bridge-owned request provider captures the active Project for this run
  → host review lifecycle asks the facade for a fresh safe Preview
  → compare fresh plan_id with expected_plan_id; check capture is still current
  → host lifecycle prepares a bounded session-local proposal record
  → pump and mailbox coordinate proposal commit with bounded ack publication
  → paired producer consumes the ack; MCP client receives queue status only
```

On successful preparation, the bridge returns a host-internal dispatch outcome
containing only the bounded JSON acknowledgment and an opaque prepared-custody
token. The pump recognizes that outcome for the review-request tool and passes
the token to the mailbox's coordinated completion operation. This internal
carrier is not the bridge reply envelope: it is never JSON-serialized,
returned by `ProjectAgentPairedRoute`, or sent to the MCP client, and it
contains no Project or raw planner data. Ordinary tool calls continue to return
their existing JSON-safe result directly. Any bridge/capture validation error
aborts the prepared token before the normal bounded failure reply is published.

`agent_adapters.mcp_adapter.get_tool_catalog()` remains authoritative for the
tool definition. Its strict object schema requires `scene_id`,
`source_module_name`, `target_module_name`, and `expected_plan_id`; `match_mode`
is optional with the same `strict` default and allowed values as the existing
Preview. `expected_plan_id` must be the exact 64-character lowercase hex digest
form returned by the existing facade. Unknown fields are rejected. The adapter
owns a reusable non-capturing transport validator for this schema; the bridge
calls it before any Project provider is accessed. Domain review semantics stay
with `core.agent_facade.preview_scene_module_swap`; the new tool does not duplicate
planner or facade validation. Capability metadata may advertise this explicit
host-review request separately from a Preview, while `agent_callable_apply`
remains `false`; the request does not create an agent mutation capability. The
catalog description/effect must label a request for human review, not a Preview
or mutation result.

The bridge special-cases this tool after outer-envelope and adapter-schema
validation, then dispatches to
`ui.agent_scene_module_swap_approval_lifecycle`. That host owner uses the
current run token and the bridge-owned request-local captured Project from the
existing capture gate, recomputes the exact safe facade envelope, requires
`valid is true`, an exact `expected_plan_id` match, and a non-zero
`changed_count`, and verifies the capture remains current before preparing
custody. `expected_plan_id` is
checked separately and is not passed to the facade as planner input. The
request is not sent through ordinary
`PromptGraphMCPAdapter.call_tool()` after this point. A direct logical adapter
or standalone SDK call has no session-local custodian and therefore returns a
bounded `host_review_unavailable` refusal before calling its Project provider;
it must never return `review_queued`. Ordinary read and Preview tools retain
their existing adapter → facade → bridge behavior.

Only a successful coordinated commit may return a bounded positive tool result,
for example `status: queued_for_human_review` with an opaque `proposal_id` and
fixed expiry summary. It states only that a human-review item is available; it
does not mean viewed, approved, applied, or saved. Tool-level refusals such as
`stale_preview`, `review_already_pending`, `request_id_conflict`, and
`host_review_unavailable` remain bounded JSON failures. A mailbox-level stale,
expired, closed, or unavailable outcome is not converted into a positive
acknowledgment. No completion waits for the human decision.

Pairing generation is host routing metadata, never an MCP argument. The paired
route stamps its private generation onto the mailbox submission; the mailbox
claim carries that internal metadata to the full-run pump without adding it to
the JSON request. The proposal/tombstone records the originating route
generation and bounded request correlation internally. An exact retry from that same generation may
receive the same queued acknowledgment without extending expiry or creating a
second proposal. A different pairing generation cannot retrieve that old
acknowledgment or proposal ID; while the proposal is pending it receives only
a generic bounded `review_already_pending` or replay refusal. Reusing a
correlation ID with different normalized intent returns
`request_id_conflict`. This preserves the session-owned human proposal without
transferring its result to a later gateway pairing.

## Proposed versioned host record

The record is session-local and transient. The version below is a design
contract, not a current persisted schema:

```json
{
  "record_version": "promptgraph.agent-scene-module-swap-review.v1",
  "proposal_id": "<host-generated opaque identifier>",
  "state": "pending",
  "request_id": "<bounded correlation value>",
  "origin_pairing_generation": 1,
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
secret. `request_id` is correlation only. `origin_pairing_generation` is
host-only routing metadata obtained from the exact paired route, never from an
MCP field. `preview_envelope` is the exact safe facade envelope; it contains no
raw Module definition or local image path.
The custodian must validate its exact schema and JSON types before storage and
must reject rather than truncate if its encoded byte size exceeds a documented
custody cap. Determine that cap with a max-shape fixture against the facade's
100 visible rows, per-text limits, and token-delta limits before implementation.

Recommended initial limits are one active proposal per browser session and a
15-minute monotonic expiry. An exact duplicate from the originating pairing
generation may return the existing pending acknowledgment without extending
the expiry. A duplicate from another generation never receives that
acknowledgment. A different review request while one is pending receives
`review_already_pending`; it never replaces or transfers the record. Reuse of
a correlation ID with different normalized intent receives
`request_id_conflict`. After a terminal decision, retain only a small bounded
tombstone/status record, not the envelope, so callbacks cannot replay the same
proposal.

The record must not contain a `Project`, `PromptLine`, Module snapshot/body,
graph, image path, Project path, capture token, raw mailbox, pairing
capability, or general session object. Store no filesystem state and write no
receipt to Project metadata.

## Atomic proposal commitment and mailbox acknowledgment

Recommended states:

```text
absent → prepared → pending → applying → applied
                         ├──→ rejected
                         ├──→ dismissed
                         ├──→ expired
                         ├──→ stale
                         └──→ apply_failed
```

`prepared` is host-internal and cannot be listed, rendered, approved, rejected,
or applied. The host lifecycle computes and size-checks the candidate outside
mailbox/custodian locks and stages it with the current request claim, pairing
generation, target epoch, and monotonic deadline. No transport, Named Pipe, or
registry operation lock is held during capture, Project cloning, facade
Preview, or size calculation.

The current sequential proposal—call `complete()`, then separately promote the
record—has a race: `consume_reply()` may acquire the mailbox lock and return the
successful ack before the later promotion succeeds. Calling those methods
sequentially is not an atomicity guarantee. PR-A must introduce one narrow
mailbox completion operation (for example `complete_with_host_commit`) used
only for this review-request result. Its exact owner is the mailbox for reply
state and request/deadline validation, with a callback into the host lifecycle
custodian for proposal state; it does not move proposal ownership into the
mailbox.

The operation follows one lock order: mailbox lock, then the session-local
custodian lock. No custodian-held path may acquire the mailbox lock. UI reads
and Apply eligibility checks acquire the custodian lock only; route release,
target synchronization, and mailbox cleanup acquire mailbox/registry locks
without nesting a custodian lock in reverse order. The commit callback performs
only bounded in-memory state changes. It calls no Streamlit API, Project/core
operation, capture, filesystem, transport, or user callback.

Within that operation, the pump supplies the claim, current target epoch,
detached/bounded reply, and prepared-record token. The reply is copied and
JSON-validated before taking either lock. While holding the mailbox lock, the
mailbox revalidates, in this order:

1. the session is open and the exact claim is still `EXECUTING`;
2. the request/claim/host target epochs match the mailbox's current epoch and
   no execution-time invalidation was recorded;
3. the original request deadline has not expired;
4. the detached reply passed exact-JSON validation and fits the existing
   mailbox/bridge reply contract.

Only after these checks does it acquire the custodian lock. The host custodian,
not the mailbox, then verifies that the prepared record matches the request
correlation, pairing generation, normalized intent, content identity, session,
epoch, and its own expiry, and that the one-pending-slot rule still holds. It
rechecks that the same prepared token is not aborted, expired, replaced, or
already committed, and that the bounded positive ack corresponds to that
record. While both locks are held, the mailbox first writes the bounded reply
and `reply_ready` state; the custodian then performs the `prepared → pending`
assignment. That custodian assignment is the proposal acceptance
linearization point. Releasing the custodian lock makes the proposal visible,
but the mailbox lock remains held until afterward, so `consume_reply()` cannot
return the acknowledgment before the proposal is committed. The mailbox lock
release is the acknowledgment's consumer-visibility point, strictly after the
proposal acceptance point. Both writes happen before either state is exposed
through its owner; `consume_reply()` cannot race ahead by polling while the
transaction holds the mailbox lock.

Session cleanup marks the custodian closed under its lock before unregistering
the route and closing the mailbox; it must release the custodian lock before
waiting on registry or mailbox locks. The commit callback checks that closed
marker while holding the custodian lock. If cleanup marks closed first, commit
fails without a positive ack. If commit wins first, cleanup follows and
removes the proposal before the session is released. Target synchronization
continues to linearize through the mailbox lock; no code path may hold the
custodian lock while acquiring the mailbox lock.

Failures before that boundary leave no actionable proposal and no successful
ack. The mailbox alone decides stale target, expired deadline, session closed,
claim mismatch, and invalid/bounded-reply outcomes before invoking the commit
callback. A conflict or lost prepared token returns a bounded non-success
tool result or mailbox terminal outcome. After both locks are acquired, only
non-throwing in-memory field assignments may remain. If an unexpected
exception still occurs before both stores reach their committed states, roll
back the mailbox reply/state and custodian record while both locks are held,
then release them; no reader may observe the partial state. Never call
`complete()` successfully first and hope a later `promote()` repairs custody.

Interruption behavior is explicit:

- Before preparation: no proposal state exists.
- After `prepared` staging but before commit: `finally` aborts it. A later
  full-run/UI sweep also removes expired or orphaned prepared records by
  request claim and monotonic deadline. `prepared` is never actionable and
  cannot occupy the active human-review slot after its request is no longer
  live.
- During the paired commit: both reader locks stay held until commit or
  rollback. An exception before publication aborts the preparation and leaves
  no successful ack. A hard process stop discards the ephemeral mailbox and
  custodian together; no durable approval survives restart.
- After commit but before `consume_reply()`: the proposal is already pending
  for the same session's human. The ack remains subject to the mailbox's
  original deadline, target epoch, pairing, and disconnect cleanup. If the
  producer never consumes it, normal mailbox expiry/stale/caretaker handling
  may clear or report that reply, but it does not roll back, recreate, or
  extend the already committed proposal. The human proposal follows its own
  15-minute TTL and target/session cancellation rules.

A target switch that wins the mailbox lock, or session cleanup that marks the
custodian closed before commit, causes the operation to fail without creating a
proposal. If commit wins first,
the later target/session transition invalidates or removes the proposal and
may turn an unconsumed mailbox ack stale; a previously consumed queue ack still
means only that the proposal was queued at its commit epoch. Human display and
Apply recheck epoch and exact Preview, so that ordering cannot authorize a
stale Apply. A normal paired-client disconnect after commit does not move the
proposal to a later pairing generation. An ordinary Preview has no candidate
and follows the existing bridge path.

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
target epoch policy. The mailbox request acknowledgment and the human proposal
have separate lifetimes: consuming, expiring, staling, or caretaker-draining an
unconsumed acknowledgment never makes the queue operation run again. The
proposal remains bound to its originating session and pairing generation and
is independently invalidated by proposal TTL, target change, explicit host
disconnect/disarm, or session cleanup.

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
stores the exact host-computed envelope only after the coordinated mailbox
completion commits; mismatch/expired/stale/closed completion stores none and
cannot publish a positive queue acknowledgment; duplicate and second-request
behavior is deterministic and cannot transfer an acknowledgment across
pairing generations; size/TTL bounds reject without truncating; malformed
request arguments are rejected before capture; standalone adapter invocation
cannot fabricate acceptance; no Project or raw planner object survives the
request run; target switch and session cleanup isolate proposals.

Concurrency acceptance for the commit protocol must use deterministic
barriers/events, never sleep-based timing. Race `consume_reply()` against a
prepared review commit and prove that a consumed positive acknowledgment
always has a committed pending proposal first. Also prove that target epoch
change, request expiry, session close, claim mismatch, reply validation
failure, a lost prepared token, or a custodian commit exception cannot leave
an actionable proposal paired with a positive acknowledgment. Exercise
interruption before staging, after staging but before commit, during rollback,
and after commit before reply consumption. In the last case the original
mailbox outcome may become expired/stale, but the one committed proposal
remains only in its originating browser session until its own TTL or an
explicit host cancellation; retries do not create a second proposal or extend
either expiry. A same-generation exact retry may return the same bounded ack;
cross-generation replay must return a non-accepted result without revealing
the old proposal ID. Existing read-only and ordinary Preview calls must remain
unchanged, and no Apply/history/save authority may appear on MCP or gateway
owners.

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
