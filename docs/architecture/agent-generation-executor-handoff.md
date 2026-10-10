# Generation executor inbox and handoff foundation

Phase 4-C2B-3 establishes a private bounded ownership contract with deterministic
fake workers. **Production execution remains unavailable.** This adds no Start,
Generate, Run or Apply control, real worker, MCP inbox/Start access, ComfyUI
submission/download, output file, Candidate/history mutation or autosave.
Executable Review and explicit human confirmation retain their existing behavior;
production C2A still returns `executable_review_required`.

Phase 4-C2B-4 adds an offline [frozen ComfyUI executor and private remote output
receipt seam](agent-generation-comfy-executor-adapter.md). Remote readiness is
separate from local downloaded outputs, host registration and save; production
execution remains unavailable.

## Owners and integration point

The browser's `ProjectAgentSessionRuntime` holds one private
`GenerationExecutorInbox` alongside the existing `GenerationJobRegistry`.
The registry remains the only job/state owner. The inbox owns one reservation,
one committed immutable envelope and worker acceptance, not a second job registry
or Gallery planner. Both default to production mode with
`execution_available = False`; all take/claim/progress exercises require explicit
characterization instances and named characterization entry points.

`ui.agent_generation_executor_handoff.handoff_generation_for_characterization`
uses the actual C2B-2 server-held review/confirmation and C2B-1 finalized manifest.
It never uses C2A's characterization certificate or acceptance callback as
production authority. It calls the existing exact review reconstruction, which
reuses Facade/Gallery planning and freezes reviewed per-request seeds.

The future real executor belongs at the existing Selected Scenes per-request
submitter's external submission/progress/download segment, immediately before
`ingest_gallery_generation_outputs`. Its private input is the immutable envelope;
its output is the bounded correlated event contract delivered to the original
session's normal host run. Existing ComfyUI integration owners should perform
sequential submission, without Streamlit widget/session callbacks. The current
submission-time randomizer must not run on already reviewed workflow bytes.
This PR neither wires that integration nor provides a runnable network worker.

## Reservation, claim, consumption and acceptance

1. A distinct private `ExecutorHumanStartAction` models a future explicit human
   Start after exact human confirmation. Its characterization capture binds the
   confirmed manifest, origin and review revision; an action from before
   confirmation or a prior Refresh cannot authorize the newly reviewed seeds.
   C2A's IDs-only action carrier, confirmation alone and public IDs cannot grant
   handoff authority. Production fails closed before reservation.
2. Fresh reconstruction verifies exact proposal, origin, source, workflow,
   seeds, host settings and displayed projection against the server-held review.
   The inbox validates immutable types, workflow digests, ordered indices and
   payload bounds outside owner locks. Capacity-one reservation is merely
   `reserved`, never a successful Start or accepted job.
3. Final owner checks use publication gate -> route operation lock -> mailbox ->
   Generation custodian -> job registry -> inbox. The route lock fences pairing
   replacement, as in C2B-2. Reservation expiry/capacity failure before claim
   releases the reservation and leaves pending custody/confirmation recoverable.
4. Under those locks the existing registry records the one-shot claim, the
   inbox commits the offer, and exact Generation custody/ACK plus executable
   confirmation are consumed. The linearization point is this committed offer
   and consumed custody becoming visible when the owner locks release. No take
   or submission event can precede the recorded job claim. The claim is stored
   in session memory; it is **not** durable across process restart or a disk log.
5. The deterministic fake worker receives only a typed offer receipt after all
   locks release. It takes the private envelope exactly once, then reports
   correlated events. Returning an `accepted` string or fabricated acceptance
   receipt without an actual take is an unknown handoff, never successful Start.
   Accepted workers may report `running` or `awaiting_result` before the handoff
   returns; successful acceptance does not require the job to stay `claimed`.
6. The host fences target/pairing again before reporting characterized acceptance.
   Double clicks, duplicate worker takes, stale receipts and changed correlations
   cannot create a second worker-owned job.

No callback, expensive workflow preparation, network request or file operation
spans ownership locks. The inbox never acquires a runtime, route or mailbox lock.
Operations involving both job and inbox always acquire job before inbox.
Supported Project/config writers still belong to the serialized full host run
and publication gate; arbitrary outside writers are not supported.

## Outcomes and uncertainty

| Boundary/outcome | Meaning |
| --- | --- |
| `execution_unavailable` | A production owner cannot reserve, claim, take or execute. |
| `capacity_unavailable` / `reservation_unavailable` | No claim or custody transfer; exact pending review remains recoverable. |
| `reserved` | Temporary private capacity only; no job/Start/worker authority. |
| `offered` | Claim is recorded and custody consumed before worker take. |
| `characterized_acceptance` | One fake worker has taken ownership; progress may already have advanced. |
| `handoff_rejected` | Definite rejection before take/submission; claimed job becomes failed and reservation capacity is released. The consumed proposal never becomes runnable again. |
| `handoff_unknown` | Missing/malformed reply, exception, timeout or conflicting rejection after take. The job is fenced as `submission_outcome_unknown`; the slot remains pinned for recovery. |
| `handoff_invalidated` / `late_event` | Original host authority is no longer current. No output registration or save authority returns. |

Rejection after an observed take/progress is ambiguous, because it cannot prove
no external send. Unknown outcomes never cause automatic retry, a second take,
resubmission of the consumed proposal or runnable-state restoration. Network
exactly-once is not assumed. An accepted worker with no progress remains claimed
until the existing fixed lease expires. Worker death, lease expiry, session close
and process loss report unavailable custody, never invented completed, failed or
remotely cancelled outcomes. Expiration is not a remote cancellation request.

After a known completed/partially-failed/failed result, an explicit original-host
characterization retirement can release capacity. Unknown/stale/lost outcomes
require separately designed human recovery and pin the slot. Definite rejection
can release capacity for a later distinct proposal, never replay the old action.

## Frozen envelope and event limits

The envelope contains only frozen `JobBinding` tokens, original review identity,
job/claim correlation, and the exact `FinalizedManifest`. It preserves proposal,
plan, Scene, ordered request/stable Illustration IDs, run indices, workflow bytes
and SHA-256 fingerprints, finalized seed provenance, source identity, seed policy
and host configuration bytes. No live Project, session state, widget, callback or
mutable settings reference crosses the worker boundary. Destinations come only
from the verified host configuration, with no separate arbitrary user workflow,
destination or output-path argument.

- One slot per session, including reserved/offered/accepted/unknown ownership.
  Reservations expire after 30 seconds and can be released only before commit.
- At most 100 requests, 5 runs per Illustration, 160 characters per correlation
  field, 1,000,000 bytes per serialized workflow, and 8 MiB of aggregate repeated
  workflow/seed-provenance/config bytes. Tuples, exact frozen dataclass types and
  bytes are required; mutable lists/bytearrays are rejected.
- `HandoffReceipt` contains only bounded status and opaque correlations.
  `ExecutorEvent` correlates job, claim and manifest with the registry's count-only
  `WorkerEvent`. Output events also require an opaque 32-hex `OutputReceipt` ID
  and exact output count. There are no raw exceptions, filenames or paths.
- The existing registry allows 1,024 contiguous events/job, 16 outputs/request,
  64 retained events and sequential request settlement. The inbox keeps the last
  64 full correlated events so a changed output receipt at the same sequence
  conflicts rather than becoming an identical progress duplicate.
- At most 16 late output events remain in a separate private bounded recovery
  ring. Duplicate retained late receipts do not grow it. Late events cannot
  advance jobs or grant publication. Eviction forgets evidence without reviving
  execution. This is opaque count/correlation evidence, not a downloadable file
  recovery implementation. The one bounded envelope remains retained after
  close/uncertainty; retention never authorizes take or publication.

No thread, unbounded queue, retry loop or transport is created. Production/MCP
catalog and request bridge do not import or advertise the handoff owner.

## Invalidation and publication boundaries

Project activation and Save As use the existing target tracker and registry
fence. Pairing replacement is excluded from final claim by the route operation
lock and is checked again on handoff return and every original-host event.
Ordinary transport release neither cancels work nor transfers ownership. Explicit
session Disarm invalidates active job custody and inbox take; session close
closes both owners. Proposal expiry/cancellation before claim prevents handoff.
After consumption there is no pending proposal to expire/replay; remote state
continues to be represented by the job and receipts.

Worker acceptance racing target invalidation may have occurred externally, but
the invalidated host cannot publish. Late output receipts remain separate even
after session close, pairing replacement or lease expiry. Switching back or
re-pairing never restores the old publication authority.

Submission started, externally accepted/definitively rejected/unknown, outputs
ready, host in-memory registration and save result remain distinct. A worker
event cannot assert Candidate publication or persistence. Existing fake host
registration/save receipts in `GenerationJobRegistry` remain separate; this
handoff slice never invokes them to mutate Project, Candidates or history.
Scene Module Swap custody, Apply and ACK are unchanged.

## Remaining execution-enablement work

Production Human Start requires a separate authorized slice connecting the exact
fresh confirmation and a new explicit human action to a production claim/inbox.
Other required work is a bounded real worker using existing ComfyUI owners and
frozen seeds; download containment and verified output custody; original full-run
host publication through existing Candidate ingestion/history owners; independent
save results; explicit human recovery/quarantine and output-retention policy;
restart/remote cancellation semantics. No confirmation or test acceptance in
this PR satisfies those production gates.

Focused deterministic tests cover capacity, immutability, exact seeds, concurrent
claim/take, progress before handoff return, full receipt conflicts, ordering,
ambiguity, loss/expiry, invalidation races, bounded late receipts and isolated
no-I/O behavior. Existing Review, Job, Manifest, C2A and Scene Module Swap tests
provide the surrounding regression checks. No full suite or live generation
is required for this foundation.
