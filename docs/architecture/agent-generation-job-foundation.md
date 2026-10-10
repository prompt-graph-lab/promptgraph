# Host Generation Job foundation (Phase 4-C1)

This slice adds session-local ownership and deterministic fake-event contracts.
`execution_available: false` remains the runtime and capability contract. No
Start/Approve UI, MCP Start/job observation, worker, ComfyUI submission/download,
Candidate creation, Project mutation, output-file write or autosave is added.
The [review UI](agent-generation-review-ui.md) remains review-only. Its proposal
and plan IDs cannot authorize a job or execution.

## Current execution audit

The following observations were verified at public main
`69de7c578f7c2fe2e6c98fccac178f610ce79622`, rather than inferred from a proposed
service. The broader [generation audit](agent-generation-candidate-audit.md)
provides product and Candidate adoption boundaries.

| Stage | Current behavior and owner |
| --- | --- |
| Frozen preparation | `app._build_selected_routes_gallery_generation_plan(full_preflight=True)` deep-copies the planning Project. `core.gallery_generation.build_selected_routes_generation_plan` resolves selected Scenes in physical Project order, excludes Workbench/deleted Illustrations, rejects ambiguous stable IDs, builds one workflow per Illustration from a detached line, and creates runs 1..N in Illustration order. Any blocked target fails whole-plan submission validation. Input signatures cover Project/path, structure, authored inputs, metadata, Module Library and host options; the full signature also covers prepared workflows. Raw plans contain Project line objects and workflow JSON. They are unsuitable as worker or observation payloads. |
| Fresh human submission | The Selected Scenes button recomputes full preflight and compares input/full signatures with stored Fresh Preview, then pushes history. `core.gallery_generation.execute_gallery_generation_plan` walks requests sequentially, rejects duplicate request IDs, deep-copies each prepared workflow into the submitter argument, catches per-request failures and continues. Its `submitted_count` increments **before** calling the submitter: it counts attempts, not proven accepted ComfyUI submissions. |
| Progress and downloads | `app._execute_selected_routes_gallery_generation_plan` supplies a nested submitter that updates Streamlit widgets/session duration estimates while consuming `core.comfyui.generate_image_with_progress`. That generator submits once, consumes matching WebSocket progress, polls history after execution, resolves output descriptors, creates the host output directory and downloads real files. It reports `done` only if at least one download succeeded; some downloads can fail while others succeed. `done` carries paths, prompt ID and diagnostics. The selected-scenes submitter retains unique paths and discards most of this provenance; a queued prompt or execution-done event alone is not a registered Candidate. |
| Output publication | `ingest_gallery_generation_outputs` resolves the active normal Illustration by stable ID, resolves/existence-checks paths, removes repeated paths within the request and paths already present in persistent dict records, invokes the Candidate factory, and appends through the supplied host callback. It reports failure when no new Candidate is added. This path deduplication is not external submission idempotency. |
| Candidate/session/save | `app._make_generated_candidate_record` captures existing generated-record semantics; `_append_line_generated_candidates` appends persistent `line.generated_candidates` and synchronizes the session cache. The UI calls `save_current_project_if_possible` after execution if any Candidates were added. Successful in-memory append and save success are distinct. Earlier successes survive later request failures; there is no transaction rolling back real downloads or all Candidate appends. `_get_line_generated_candidates` merges and mutates caches/persistent records, so it is not a read-only observer. |
| Host lifecycle | `ProjectAgentSessionRuntime` serializes host target synchronization/publication with its publication gate. The periodic fragment remains wake-only and the capacity-one mailbox serves bounded requests through normal app capture. `ProjectTargetTracker` changes opaque epoch on Project object/path activation, including switch-away/back and Save As. Epoch is an activation guard, not a content/workflow freshness check. |

The smallest C2 seam is the existing per-request submitter's detached execution
result **before** `ingest_gallery_generation_outputs`. Keep preparation, stable
Illustration resolution, Candidate creation/append, history and persistence in
the normal host run. Move only external submission/progress/download processing
behind an immutable work/event contract after removing widget/session callbacks
from that execution path. Do not broadly refactor the existing human Gallery
flow or reuse Scene Module Swap's operation-specific approval owner.

## Owner and contracts implemented here

`ui.agent_generation_job.GenerationJobRegistry` owns one active job for one
browser-session runtime. The normal runtime constructs a production instance,
synchronizes target under `_publication_gate`, and closes it with session
cleanup. There is no live caller of job preparation, claims or fake events.
Production instances cannot reach `claimed`/`running` states. An explicit
`characterization=True` constructor permits only the methods named
`*_for_characterization`; these model transitions with fake count-only events
and receipts, perform no execution, and are not an authority interface for C2.

Job identity is a random opaque handle, distinct from Scene, Illustration,
request, plan and ComfyUI prompt IDs. Private immutable binding includes its
session incarnation, process incarnation, origin pairing generation, target
epoch, Project activation token and exact plan identity. Runtime uses the
existing tracker epoch for both epoch and activation: it already observes
Project object/path activation without retaining those objects in the job owner.
Content/workflow freshness still needs the separate exact-plan check.
Frozen request records retain only bounded correlation IDs, stable Illustration
IDs, run indices and workflow fingerprints; workflows, paths, settings and
Project objects are not retained. Preparation copies the list and scalar records.

Claim handling is atomic: a same-key/exact-binding duplicate while active
returns the original private claim receipt; a conflicting key/binding refuses;
terminal jobs never claim again. Claims are stored in memory before the first
fake submission event. This is session-local bounded bookkeeping, not durable
exactly-once submission. Ordinary disconnect/release does not invoke the owner
or cancel a job. Another pairing cannot claim or publish the original job and
disconnect grants no transfer, retry or remote cancellation authority. Host
observation is private and can continue independent of transport availability.

Lock order is runtime publication gate -> job lock. The registry never acquires
runtime, registry, mailbox or review-custodian locks and never calls external
execution/publication callbacks while locked. Clock reads occur before locking;
clock injection exists for deterministic tests. Mailbox/custodian lock order
is untouched. Workers have no Streamlit/Project import or access through the
immutable event contract. No generation runs in the mailbox or periodic fragment.

## Truthful states and transitions

| State | Meaning / permitted next step in characterization |
| --- | --- |
| `prepared_not_started` | Frozen intent only; fake exact claim -> `claimed`; host pre-submit cancel -> `cancelled`; expiry -> `expired`. No execution authority. |
| `claimed` | One-shot in-memory claim recorded; before any send attempt, cancellation remains possible. `submission_started` -> `running`. |
| `running` | A submission attempt has begun. `submitted` -> `awaiting_result`; definitive `failed` settles that request, allowing the next unsent request only after settlement (or terminal `failed` if all requests failed); ambiguous submission -> terminal `submission_outcome_unknown`. Pre-submit cancellation is now refused. |
| `awaiting_result` | May include external completion/downloads awaiting host registration or unsent requests after a settled earlier request. An `outputs_ready` event alone cannot complete a request/job. Separate exact host publication receipt settles it; only then may the next request begin. |
| `completed` | Every request's fake host registration receipt confirms all reported downloaded outputs registered in memory. `save_state` is independently `not_attempted`, `saved` or `save_failed`; completion is never inferred from a ComfyUI response. |
| `partially_failed` | Some outputs registered, while at least one request/output failed registration. Those registered counts remain visible even when a later save fails. |
| `failed` | All requests settled without registered output. |
| `submission_outcome_unknown` | Submission acceptance cannot be established. Unsent requests remain unsent, late events cannot restart the job, and no retry/resubmission is allowed. |
| `stale_target_outputs_not_registered` | Activation/target drift, or host receipt's plan/origin mismatch, fences publication. Retained downloaded and already registered counts remain distinct; switching back does not revive the job. |
| `unavailable` | Session closure, active lease expiry, foreign/missing/evicted job, or a fresh runtime/process cannot establish continuing custody. This is not proof that external work failed or stopped. |
| `cancelled` / `expired` | Terminal before submission. No remote interrupt or queue-clear operation is represented. |

Request states separately distinguish unsent, submitting, awaiting external
result, awaiting host registration, completed, partially failed, failed and
unknown submission. Worker events cannot assert host registration or save.
After submission begins, `failed` means a definitive failure such as a known
submission rejection. A timeout or lost response whose acceptance is uncertain
must use `submission_unknown`; it cannot settle the request as `failed` to
continue the job or retry submission.
Sequence numbers must be contiguous across the job; request submission follows
the frozen order. Exact retained event duplicates are no-ops, changed same-sequence
events conflict, and older evicted duplicates/out-of-order/late events are
rejected without changes. Host publication/save duplicates are also no-ops;
conflicts refuse. Accepted transitions increase monotonic job revision; rejected
and duplicate calls do not. Snapshot polling never renews expiry.

## Bounds, disclosure and loss

- At most 5 distinct runs per Illustration, 100 total requests, 16 reported
  downloaded outputs per request, 1,024 accepted worker events and the last 64
  event records per job. Immutable count-only events contain no free-form errors
  or paths. Current sequential contract uses fewer events than the hard budget.
- Prepared intent expires after 15 minutes. Claimed work has a fixed one-hour
  lease; expiry reports unavailable, never remote cancellation. Terminal records
  retain for 10 minutes from the observed terminal transition. At most 8 records
  remain; oldest terminal records are evicted to prepare new work. There are no
  unbounded tombstones/replay logs; forgetting a job never resurrects that ID.
- Cleanup is explicit (`cleanup`) and lazy on calls, including target sync and
  snapshots. Browser-session close fences all events/claims and reports
  unavailable. Process restart has no reconciliation/persistence: a new owner
  cannot retrieve old handles. No fabricated resume/failed/completed outcome.
- Snapshots return only opaque job handle, states, revision, bounded indices,
  counts, save outcome and count-only event history. They contain no Project,
  Streamlit state, origin/pairing/claim tokens, plan/workflow JSON, correlation
  IDs, filenames, raw paths, prompt IDs, secrets or exception text. Copies are
  detached, and snapshots are not advertised through MCP.

## Exact Phase 4-C2 scope (future, not activated)

1. Define one bounded human **Start** lifecycle over the fresh host review. A
   plan/proposal ID, agent request or approval flag alone must never authorize
   execution. Recompute and compare exact complete plan/config/workflow and
   activation immediately before an atomic one-shot host claim. Record that
   claim before external submission and never auto-retry ambiguous acceptance.
2. Detach immutable bounded execution work with finalized workflow/seed identity,
   host-selected endpoint/output destination and job/request correlation. These
   private execution details must never enter job observation. Add an executor
   with no Streamlit or live Project access; bound its event inbox/progress
   coalescing and freeze sequential request ownership before launch.
3. Deliver typed bounded output receipts to the normal host run. Revalidate
   original activation, exact agreed plan and stable Illustration IDs before
   each publication. Reuse `ingest_gallery_generation_outputs` and existing
   Candidate factory/appender; do not equate network/download success with
   publication. Capture Candidate in-memory registration separately from save.
4. Keep bounded host-owned output recovery/quarantine for late/stale results,
   without deleting downloaded files, reattaching to a new Project, transferring
   pairing authority or submitting again. C1 retains safe counts only, not
   recoverable file locators. Define a human recovery action and expiry before
   adding real output storage. Remote cancellation/restart reconciliation and
   MCP observation are separately bounded later work, not implicit in Start.

Decisions still required for C2: finalized seed/workflow identity versus preview
freshness; typed validation/provenance and download-failure counts; worker inbox
limits and lease/recovery behavior; exact allowed content changes after Start
(default here is exact identity, so reorder/drift does not grant attachment);
human recovery custody and filesystem containment; and whether to preserve safe
ComfyUI prompt/seed provenance in generated Candidate metadata. The fake model
does not certify runtime success, offline prompt binding, exactly-once network
semantics or supported asynchronous writers.

Focused tests exercise concurrent claims, immutable bounded events/snapshots,
partial/unknown/stale outcomes, fake worker isolation, retention, actual runtime
switch/Save As/close, and existing Gallery/review/Scene Module Swap contracts.
No full suite or live generation is required for this foundation PR.

## Phase 4-C2A: host authorization preparation (execution remains disabled)

`ui.agent_generation_start_lifecycle` owns the private human callback carrier,
immutable execution-manifest preparation, and an atomic custody/claim seam.
There is no visible Start control, production executor, MCP Start tool, job
observation tool, submission, output write, Candidate append, or autosave here.

The existing Generation Review intentionally reports
`workflow_binding_verified=False` and uncommitted execution seeds. It cannot
certify the actual executable workflow. Production authorization therefore
returns `executable_review_required` without allocating a job, consuming pending
custody, or acknowledging successful Start. IDs and agent approval assertions
never bypass this condition. C2A's explicitly named characterization certificate
and acceptance callback are usable only with a characterization-enabled job
owner; they model contracts, and do not establish real prompt binding or seeds.

The direct host action captures exact proposal/plan identity and a private
runtime incarnation. The lifecycle reloads complete current safe Preview and
host preflight through the existing Facade/Gallery planner. Endpoint and output
location come from the existing `generation_options.comfyui_endpoint` and
`generation_options.output_directory` host fields. Its internal
`_host_preflight` sink copies only requests, workflow data, generation options,
and host output location; it never copies Gallery plan `target_lines` or a live
Project. Freshness checks include activation, Scene membership/prompt/Module
state, host config and raw workflow signatures. A plan ID match cannot certify
a differing executable workflow: characterization certification binds the
complete safe Review and complete detached preflight independently. Host endpoint
and output destination must equal the certificate; neither comes from an agent.

Private frozen manifest records contain ordered stable Illustration IDs, run
and request correlation, exact workflow bytes/digests, parameter bytes, host
endpoint/output location, seed policy and content identity. Job/claim correlation
is attached only after the atomic claim. Workflow fields are bounded to 4,096
characters, each serialized workflow to 1,000,000 bytes, and aggregate repeated
workflow plus parameter storage to 8 MiB; existing job limits enforce 100 requests
and five runs. Immutable bytes/scalars retain no Project/session/widget objects.
Public job snapshots remain count-only and contain none of the manifest data.

Expensive preflight and manifest encoding run outside locks. Final linearization
uses publication gate -> mailbox -> Generation custodian -> job registry. Under
that ordering the exact pending proposal is checked, the one active job slot is
reserved and claimed, and custody is consumed together. Failed preparation,
missing executor, invalid certificate or busy slot leaves the proposal pending.
Duplicate actions cannot claim twice. Only Generation custody's exact ACK is
retired; Scene Module Swap custody and ACKs remain independent. Host full-app-run
ownership remains required: arbitrary concurrent Project/config writers are not
supported and must not bypass the publication gate.

The fake acceptance callback runs after all locks are released. Definite inbox
rejection retires the claim as failed. Exceptions, unrecognized responses and
ambiguous handoff become terminal `submission_outcome_unknown`; the lifecycle
returns no runnable manifest and never retries that proposal. A target switch,
Save As or session close invalidates the job, including during acceptance.
Ordinary transport release cannot mint authorization. Lease expiry is not proof
of external non-acceptance, and is never a reason to replay claimed work.

### Required C2B work before enabling Start

C2B must provide a genuine human-reviewed executable certificate covering final
prompt binding, workflow, per-request seed policy/parameters and host destination,
including any workflow transformation after the current display Preview. It
must replace the characterization seam with one production atomic claim and a
bounded nonblocking worker inbox reservation/acceptance contract. No second
Gallery submission path may be introduced. A worker must own immutable correlated
work without Streamlit/live Project references, and report through bounded typed
events. No user-visible Start success may precede actual executor custody.

If inbox capacity is unavailable, preparation must leave custody unconsumed. If
acceptance becomes ambiguous after claim, fence the claim and retain explicit
human recovery information without automatic retry or pretending that submission
failed. C2B must define containment, download/output receipt verification, stale
output quarantine/recovery and normal-full-run Candidate/history/save publication
before enabling execution. These remain unresolved production decisions; C2A's
fake tests do not certify network exactly-once behavior or a supported executor.
