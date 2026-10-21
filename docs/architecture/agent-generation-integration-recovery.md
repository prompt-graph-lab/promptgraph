# Agent Generation integration, recovery and retention (Phase 4-C2B-8D)

This audit was established against the protected Generation path through PR #174,
merge commit `064212a9e78da8456cb5eac4c7b82e224c77bb08`, and is refreshed through
PR #186, merge commit `b761b28fab52e7d0abb2bf34a6293f77a93ca832`. Its later
C2B-8D-14, C2B-8D-15A/15B, C2B-8D-16A/16B and C2B-8D-17A through 17E-B updates
are recorded below. C2B-8D-1 through C2B-8D-12 collectively define and test, in separate and
partially composed characterization slices, a protected route from a frozen
request through the existing Candidate writer and Project JSON save. C2B-8D-14
connects the single-request v1 and multi-request offline Journal intents to the
existing executor's actual sequential pre-send decisions. **Production
execution remains unavailable.** The
HTTP owners and Windows-protected path are exercised offline with injected
transports and disposable state; the 16B Worker lifecycle is also
characterization-only. No test in this path proves a live ComfyUI run, crash
durability, or production worker integration.

[C2B-8A ownership journal foundation](agent-generation-ownership-journal.md)
characterizes bounded offline journaling, inspect-only restart inventory and
explicit selected saved-Project Candidate reconciliation. It has no production
call site and does not restore claims, publish, save, retry or clean up.

[C2B-8B Human Recovery Review foundation](agent-generation-human-recovery.md)
adds private immutable inspection cases, redacted bounded projections, scoped
non-executable review intentions and read-only retention assessment. It has no
production Recovery UI or call site; those intentions grant no action authority.

[C2B-8D-2 HTTP submission characterization](agent-generation-comfy-executor-adapter.md#c2b-8d-2-offline-http-submission-transport)
now provides bounded offline-tested `POST /prompt` over original frozen request
instances, with an explicit optional stdlib wire and truthful possible-send
uncertainty. It is not a production default and performs no real server requests
in its tests. [C2B-8D-3 history](agent-generation-comfy-executor-adapter.md#c2b-8d-3-offline-http-history-transport)
and [C2B-8D-4 view](agent-generation-output-containment.md#c2b-8d-4-offline-http-view-transport)
provide the corresponding offline transport contracts. The
[C2B-8D-14/15B executor Journal boundary](agent-generation-comfy-executor-adapter.md#c2b-8d-14-offline-journal-intent-before-send-characterization)
characterizes one-request v1 and sequential multi-request intent-before-send
through the existing executor with injected callbacks; it is not production
durable-intent wiring. The disabled characterization Worker lifecycle is
described in C2B-8D-16B below; production registration, original-host production
delivery and production authorization remain separate gates. Profile A,
`authorship=unverified`,
`execution_available=false`, `protected_storage_available=false` and
`promotion_available=false` are unchanged.

## C2B-8D-16A injected HTTP and Journal composition

`ui.agent_generation_http_executor.compose_http_executor_for_characterization`
assembles the existing `PromptHTTPSubmissionTransport`,
`PromptHTTPHistoryTransport`, history-result adapter,
`ComfyExecutorAdapter`, exact `GenerationExecutorJournalIntent`, and original
host event delivery. Creation requires the exact host state/runtime and an
unbound Journal owner created for those same objects. Both transports require
explicit injected wire factories and share one bounded `PromptHTTPPolicy`;
the composition rejects the optional standard-library network wires. Each
request's destination is still derived only from its exact frozen request.
There is no production registration or default transport.

For each accepted request, the composed path preserves this sequence:

`submission_started accepted`
→ `submission_intent acknowledged`
→ one injected `POST /prompt`
→ `submission_outcome acknowledged`
→ original-host `submitted` accepted
→ exact-prompt injected `GET /history/{prompt_id}`
→ existing remote-output validation and host count event.

An initial History read happens once after accepted submission. Before every
History GET, including an explicit re-read, the composition requires the exact
accepted envelope, active frozen request and prompt, current original Project
and path, process/session, activation/epoch/pairing, live Job Registry and
Inbox event custody, and the Journal owner's exact acknowledged tip. These
checks use the existing host lock order and release all host/job/inbox/Journal
owner locks before HTTP I/O. After the GET, the same custody is revalidated
before its result can reach the Executor. A caller may explicitly request
another exact-prompt History read while the Executor is waiting for remote
metadata; that operation never invokes POST again. If custody is lost before
the GET, no request is issued. If close or invalidation races an already-started
GET, its result is discarded as unknown/invalidated; the implementation does
not claim that the remote GET was cancelled. Pending, timeout, malformed,
mismatched or uncertain results cannot advance another request. A correlated
successful History result reaches only the existing
`validate_remote_outputs` owner and `remote_outputs_ready` event. It does not
emit local `outputs_ready`, register a Candidate, settle the Journal request,
or save the Project. The existing C2B-8D-15B live original-host registration
or validated-failure gates remain necessary before the next request is
eligible.

The integrated characterization uses in-memory HTTP wires and disposable
original-host and Journal owners. It checks Journal acknowledgment before POST,
acknowledged POST outcome before History GET, exact correlation, lock-free I/O,
explicit pending re-read, local pre-send rejection, response-loss uncertainty,
and reentrant/concurrent advancement and close without a second POST. This
composition does not establish real HTTP interoperability, background polling,
production Worker lifecycle, restart continuation, output download/containment or
production authorization. All production capability flags remain false and
`authorship=unverified`.

## C2B-8D-16B disabled host-owned HTTP I/O Worker lifecycle

The separate explicit composition
`compose_http_executor_with_worker_for_characterization` inserts a private
host-owned Worker behind the existing 16A adapter transport/result-provider
seams. It uses only injected in-memory HTTP wire factories and retains all
16A executor, Journal, freshness and original-host event owners. The existing
synchronous composition is unchanged when no Worker is supplied. Construction
does not start a thread; only the original host may explicitly start, observe
and close the Worker.

The Worker carries one bounded task at a time on a one-item queue. Tasks include
only the exact prepared frozen request, accepted prompt UUID for History, and
immutable operation/job/claim/manifest/request/attempt correlation. The Worker
does not receive the live Project, Streamlit state, host locks, Job Registry,
Inbox, Journal writer, event sink or reusable authorization tokens. The host
first accepts `submission_started`, writes and acknowledges the exact Journal
intent, and rechecks current host authority. Only then may the existing
transport execute on the Worker thread. The result returns to the waiting host
thread, which records the outcome, rechecks host custody and delivers events
through the existing `ComfyExecutorAdapter` and
`deliver_executor_event_for_characterization`. No Worker-thread path writes
Journal or mutates Registry, Inbox, Project, Candidate, Undo or save state.

Close before admission and queued close before transport entry make zero HTTP
calls. After possible POST entry, timeout, exception, lost completion, close or
host invalidation pins the request as unknown; the one-shot claim cannot be
retried. Close during History GET discards a late response and does not claim
remote cancellation. A live thread that outlasts the bounded wait/join is
reported `close_pending` with `thread_alive=true` and `safe_terminated=false`.
Terminal and safe-termination observations are explicit. This shutdown bound
does not bound DNS, response headers or the entire HTTP operation. There is no
background History polling; only an explicit host call may request a later GET,
and it cannot resubmit POST.

Worker start/close serialize through the Worker's short lifecycle lock, not the
host admission lease. The lease spans the `submission_started` event, Journal
intent acknowledgment and one-item queue admission, then releases before the
bounded HTTP wait. Close does not wait for Journal callbacks or disk I/O. If it
linearizes during an already-started intent write, that intent may still be
acknowledged, but the Worker's queue gate refuses it as a definite pre-send
rejection when no task is active; no HTTP call occurs, and the Journal records
the outcome. Once close or another terminal Worker state linearizes, an
`advance` can preserve settlement for an already completed/registered request
but stops before creating a later request's event or intent. Thus shutdown
does not turn remaining unsent requests into false failures. A request whose
queue admission preceded close still follows the existing one-shot pre-send
versus possible-send uncertainty rules.

Offline integration tests use disposable Projects, Journal owners and injected
wire fakes to characterize exact intent-before-send, accepted POST/History
result return, host-only event delivery, sequential requests, pre-send versus
possible-send outcomes, callback reentry, duplicate attempts, close races,
late results, host drift, missing completion, post-registration close fencing
and live-thread reporting. This
composition does not establish production scheduling under Streamlit reruns,
production registration, process-restart authority, live ComfyUI
interoperability, Candidate publication or Project save. Production capability
flags remain false and `authorship=unverified`.

## C2B-8D-17A protected storage preflight and capacity reservation

`WindowsProtectedStorageAdmissionCharacterization` composes five explicit
native root owners under one approved scope identity: private Journal,
temporary containment, retained uncertain evidence, promoted assets and the
selected Project JSON reference. It rechecks the original native identity,
owner-only ACL and local NTFS observation and takes a bounded metadata-only
inventory of direct files. Existing files are counted as retained uncertain,
not adopted. The selected JSON is not read or mutated.

The private accounting kernel tracks reserved estimates, observed-used bytes
and retained-uncertain capacity separately. Journal and image limits derive from
the existing bounded owners; staging and promoted assets share the existing
aggregate ceiling, and the distinct retained-uncertain root has its own bounded
budget. Uncertain bytes stay charged to their original purpose; no files are
moved automatically. Exact in-memory operation/reservation tokens prevent reuse,
cross-operation consumption and forged release. Concurrent reservations are
bounded and only one write admission may be outstanding. A known cancellation
before write can release its reservation. Completion counts only bounded new
native files; any uncertain state, drift, close or invalidation retains the
upper bound. This is process-local policy accounting, not an OS quota or a
guarantee that disk space is free. A fresh free-space sample is used only as a
preflight observation and cannot prevent another process from consuming space.

At the 17A baseline, no writer consumed the reservation contract. The later
17B/17C, 17D and 17E-B slices now add explicit opt-in integrations for byte
images, streamed staging images, protected promotion batches, and protected
Journal V1/multi-request replacements. Their exact boundaries are recorded in
[the protected-storage architecture](agent-generation-protected-storage.md).
These integrations do not provide a cross-process quota or restart-time
reservation recovery. A fresh capture charges existing files as uncertain, but
cannot restore a lost reservation whose write left no file. No existing user
directory or ACL is repaired, and no cleanup occurs. Production root policy and
capacity ownership remain separate gates. All production flags remain false
and authorship remains unverified.

## C2B-8D-17B/17C protected asset writers consume reservations

C2B-8D-17B integrates the existing byte-oriented protected image writer, and
C2B-8D-17C integrates the existing streamed remote image writer. Both require
the same exact asset-root owners as the capacity ledger, a unique one-shot
operation identity, bounded reservation and native inventory completion. The
stream boundary reserves the maximum single-image policy bound before native
file creation or provider invocation, then commits actual bytes only after
stream close, image verification, native identity/ACL/content checks, inventory
comparison and final host freshness validation. The reservation's unused
portion is released only at that successful commit. Uncertain admitted writes
retain the full upper bound and evidence.

These are disposable offline contracts only. They do not provide a cross-
process quota, restart reservation recovery, production root policy, actual
disk guarantee, or production execution authorization. Native I/O and host
callbacks remain outside lifecycle locks except for the bounded
`CREATE_NEW`/handle-retention and final in-memory commit boundaries. All
production flags remain false and authorship remains unverified.

## C2B-8D-17D protected promotion batch admission

`ProtectedDurablePromotionCharacterization.promote_with_capacity_admission_for_characterization()`
uses the exact staging/promoted root owners held by the capacity ledger. It
reserves the complete ordered batch before the first destination `CREATE_NEW`,
then reuses the protected asset writer and promotion owner for exclusive
copying, image verification, and native identity/ACL/byte checks. The exact
expected inventory delta and all destination files must reconcile before the
immutable promotion receipt and observed-used ledger commit become visible.
Close, invalidation, host drift or any uncertain partial copy retains the full
reservation and evidence; no partial destination is deleted, overwritten,
adopted, retried or rolled back. Existing unadmitted promotion behavior remains
available, and the admitted method is explicit characterization-only opt-in.

## C2B-8D-17E-A/B protected Journal replacement capacity

17E-A added the bounded replacement preflight/reconciliation contract. 17E-B
adds explicit `WindowsProtectedJournalCharacterization` methods that wrap the
existing protected V1 and multi-request Journal append owners with one exact
capacity admission per replacement. They preserve both Journal schemas, their
revision limits and acknowledgements; the existing Journal writer remains the
only file writer. Native identity/ACL, complete inventory delta and exact
revision/digest acknowledgement must reconcile before success. After an
admission token is issued, uncertain write/flush/replace/reopen/acknowledgement
or close outcomes retain the full replacement bound and evidence.

The Journal capacity integration exists, but it is **not connected by default
to `GenerationExecutorJournalIntent`**. That owner still uses the ordinary
characterization append methods; a caller must explicitly select the
capacity-integrated append API. These are opt-in disposable/offline contracts,
not an OS quota, cross-process coordination, restart authority, power-loss
guarantee, author authentication or permission to execute. Existing roots are
not repaired and uncertain evidence is not cleaned up. All production flags
remain false and `authorship=unverified`.

## Evidence scope and current owners

The surrounding contracts are authoritative:

- [C2B-1 finalized executable manifest](agent-generation-executable-manifest.md)
- [C2B-2 executable review and confirmation](agent-generation-executable-review-ui.md)
- [C2B-3 one-shot inbox/handoff](agent-generation-executor-handoff.md)
- [C2B-4 frozen submission and remote receipts](agent-generation-comfy-executor-adapter.md)
- [C2B-5 contained local outputs](agent-generation-output-containment.md)
- [C2B-6 Candidate publication and JSON persistence](agent-generation-candidate-publication.md)
- [C2B-8D protected storage and Candidate path](agent-generation-protected-storage.md)
- [C2B-8A ownership journal](agent-generation-ownership-journal.md)
- [C2B-8B Human Recovery inspection](agent-generation-human-recovery.md)
- [Scene Module Swap approval custody](agent-scene-module-swap-approval-custody.md)

The implemented guarantees below are scoped to explicit characterization owners,
disposable Projects/files and injected synchronous callbacks. The supported
host writer is a serialized full-app run plus its publication gate. Unrelated
background Project writers are not supported. Filesystem checks assume the host
controls the roots and writers; they detect replacement and corruption but do
not establish a hostile-process ACL sandbox. Callback classifications such as
definite rejection and save success are trusted seam inputs; a real transport
must earn those classifications independently.

## Post-PR-174 protected path: integration trace

The following is the current protected characterization route. “Composed” means
the focused test connects the named owners in a disposable host and uses an
injected ComfyUI/result or stream provider; it does not mean a real server,
production Start, or background worker was exercised.

| Transition | Owner and evidence | What is characterized | Production boundary still absent |
| --- | --- | --- | --- |
| Frozen request -> reviewed offer | `core/generation_executable_manifest.py`, executable review and confirmation owners; exact Project/source/config/workflow bindings, complete target/run coverage, supported sampler-to-output/conditioning path, finalized seeds | Direct offline manifest and review tests; explicit human review/confirmation custody | No production Start call site; confirmation is not execution authorization. `capture_executor_human_start_for_characterization` is not wired into `app.py`. |
| Accepted handoff -> `POST /prompt` and prompt identity | Handoff/inbox/job owners, `ui/agent_generation_comfy_executor.py`, `core/comfy_prompt_request.py`, `core/comfy_http_submission.py`; exact frozen request and returned prompt UUID | Handoff/executor fake-provider tests plus isolated injected/monkeypatched HTTP wire tests; one attempt, sequential order, possible-send uncertainty, no automatic retry | HTTP submission is not the executor's production default and no live ComfyUI request is made. No production Worker registration or production durable-intent call site; C2B-8D-14/15B/16A characterize the Journal-gated pre-send contract offline. Production deadline policy and original-host event-loop delivery remain absent. |
| Accepted prompt -> history observation | `core/comfy_http_history.py`, `core/comfy_remote_output_receipts.py`, executor result gate; exact accepted UUID and frozen origin | Bounded pending/ready/unknown transport contract, strict metadata parsing and correlation tests; explicit later read does not resubmit | No polling scheduler, live history interoperability evidence, or durable restart association. Missing/timeout history is unknown, never proof of execution failure. |
| Successful history -> `/view` stream -> protected staging | `core/comfy_http_view.py`, `core/comfy_output_containment.py`, `core/generation_windows_protected_assets.py`; exact remote descriptor, prompt/request binding, original-host freshness | Injected HTTP stream composed with real Windows disposable roots/files, incremental stream, native identity/DACL, decode/size/hash and retention checks | No production transport registration. No remote cancellation or cleanup, and no claim of constant-memory decode or hard end-to-end deadline. |
| Complete protected staging batch -> acceptance -> promotion | Legacy path: `WindowsProtectedAssetsCharacterization`, protected acceptance owner and `ProtectedDurablePromotionCharacterization`; Profile A currently stops at the 19F-B destination-capacity preflight | Windows-native disposable tests cover the legacy source/destination copy path; Profile A tests cover exact accepted-batch revalidation and destination-only reservation for batches that fit the shared ledger | Profile A has no CREATE_NEW Promotion writer, copied destination, aggregate Promotion receipt or production authority. With the current shared 16-entry cap, a retained 16-image source batch cannot reserve a second 16-entry destination. No production root lifecycle. |
| Promotion -> `outputs_ready` -> Candidate admission | executor adapter and `GenerationProtectedCandidateAdmission`; opaque event ID is correlation only, promotion receipt remains owner-held | Composed fake executor tests emit one count-only event; admission tests verify exact original Project/path/snapshot, activation/epoch/pairing, job/claim/request and event evidence | Event delivery is not wired to a production worker. Admission is eligibility evidence, not human approval or a reusable capability. All publication gates remain disabled. |
| Admission -> Candidate append through existing Gallery writer | `GenerationCandidatePublication.publish_protected_for_characterization`, existing Gallery candidate factory/appender and Undo snapshot | Windows-native disposable composition mutates only the exact in-memory fixture Project, records actual Candidate delta, checks path/provenance and one-shot settlement; partial append remains uncertain and is not replayed | No production entry point or enabled publication authority. No second writer or conversion to legacy receipt custody was introduced. |
| Settled Candidate registration -> Project JSON save | Same publication owner and existing app save callback -> `core.io.save_project_to_json`; exact Project object/path and protected provenance | Disposable integration writes then reopens JSON with the normal loader; verifies Candidate lineage, prompt/seed/provenance, one-shot save and distinct save outcome | Does not establish crash/power-loss durability, cross-file atomicity, or permission to recover after restart. Save uncertainty is retained; no retry/rollback/cleanup. |

The tests that compose the protected route are characterization tests, not a
single live transport-to-save exercise: `tests/test_agent_generation_protected_candidate_publication.py`
uses the existing review/handoff setup, successful-history fixture, disposable
native protected roots, real Candidate factory/appender and save callback. HTTP
submission/history/view contracts are tested separately with injected or
monkeypatched wires. `tests/test_agent_generation_integration_recovery_audit.py`
continues to cover the earlier legacy contained-output route and its no-replay
and save-uncertainty properties; it is not evidence that C2B-8D has a production
caller.

### Prior local-output route: C2B-5/6 ownership map

This earlier table describes the separate legacy `ContainedOutputStore` and
`DurableGenerationAssets` characterization route. Its contracts remain in place;
the newer protected route above does not fabricate or bypass its receipt
ownership.

`ui/` and `core/` paths below identify the legacy implementation owners. All
execution, containment and publication operations remain characterization-only.
Inspection of safe review projections and human confirmation are implemented
host UI.

| Transition | Authoritative owner and required evidence | Commit/linearization point | Retry permission and invalidation |
| --- | --- | --- | --- |
| Pending proposal -> finalized review | `core/generation_executable_manifest.py`, `ui/agent_generation_executable_review.py`; explicit Scene, complete target/run coverage, source/config/workflow evidence, supported sampler-to-output and conditioning paths | Complete immutable manifest/projection; each request has canonical workflow bytes/digest and finalized seed slots | Inspection preserves seeds. Explicit Refresh discards prior review/confirmation and creates new identity. One unsupported target withholds the entire manifest. |
| Review -> human acknowledgment | `ui/agent_generation_executable_confirmation.py`; exact session-held carrier, fresh full manifest/projection and original proposal | Confirmation publication under runtime gate -> route fence -> mailbox -> custodian | Duplicate callback records one ACK. Activation/epoch/pairing/source/config drift refuses confirmation; transient reads may recover only after fresh inspection. ACK does not start work. |
| Confirmation + new human action -> reserved inbox | `ui/agent_generation_executor_handoff.py`, `ui/agent_generation_executor_inbox.py`; private post-confirmation action and freshly reconstructed review | Bounded reservation; no claim or external authority yet | Capacity/expiry before claim releases reservation and retains review custody; re-inspect before another explicit action. Production returns unavailable. |
| Reservation -> claimed/offered, consumed proposal | Handoff, `ui/agent_generation_job.py`; exact host/process/session/activation/epoch/pairing, manifest and ordered requests | Under gate -> route -> mailbox -> Generation custodian -> job -> inbox, job claim and committed envelope consume exact proposal/ACK; observable when locks release | One-shot claim. No restoration of consumed proposal. Unknown post-claim outcome pins ownership. The claim is memory-only, not durable. |
| Offer -> one worker take / handoff response | Inbox; typed exact job/claim/manifest receipt and actual observed take | Inbox moves to accepted under job-before-inbox locks; fake callback runs unlocked | No second take. Normal completed/partially-failed/failed progress before callback return preserves acceptance. Unavailable/unknown/cancelled/expired/invalidated ownership does not. |
| Accepted request -> submission started/accepted | `ui/agent_generation_comfy_executor.py`, optional `ui/agent_generation_executor_journal.py`, `core/comfy_prompt_request.py`; exact manifest member, workflow bytes, finalized seeds, frozen endpoint | Without the optional owner, legacy behavior remains unchanged. The v1 path keeps its two-revision single-request Journal. Multi-request uses 15A's separate schema: each accepted `submission_started` is followed by an acknowledged intent before one injected send, then an accepted/pre-send-rejected/unknown outcome. Every next request requires a fresh exact original-host settlement against the live Job Registry and complete accepted event ledger. | No acknowledged intent means zero callback invocations. Possible-send uncertainty never retries. Accepted prompt, pending/timeout, remote metadata and partial registration do not by themselves authorize the next send. Diagnostic history is 64 events; settlement uses exact private host evidence bounded by 1024 events and refuses when incomplete. Reopen remains inspect-only. |
| Accepted prompt -> pending/timeout/remote metadata | Executor and `core/comfy_remote_output_receipts.py`; exact prompt/request/workflow/output nodes, bounded validated history | Correlated host count event plus retained immutable remote receipt | Timeout/unknown is not execution failure or cancellation. An exact later result may resolve accepted execution without another submit. Invalid or late history cannot advance original-host counts. |
| Remote receipt -> local verified batch | `core/comfy_output_containment.py` plus original-host gate in handoff; original validated history proves explicit success, exact descriptors, storage ownership, bounded stream, signature/decode/hash/identity | Atomic local receipt insertion only after all files verify; pre/post gate and separate `outputs_ready` event move request to awaiting host registration | One pinned attempt, no redownload. Status-less success is unproven. Incomplete/quarantined/late evidence cannot grant local output or publication authority. |
| Local batch -> durable promoted assets | `core/generation_output_promotion.py`; exact private store/envelope/receipt objects, approved frozen destination, local identities/SHA-256 | Per-request attempt pinned before IO; complete promoted tuple only after exclusive copy, file fsync and revalidation | No overwrite or replay after failed/partial copy. Retain evidence. Durable files alone do not prove registration. |
| Durable assets -> Candidate append / observed count | `ui/agent_generation_candidate_publication.py`, `core/gallery_generation.py`, existing app factory/appender; exact original Project object/path/source snapshot, activation/pair/job/receipts and local count event | Publication marker before IO; after unlocked preparation, host/route gate fences existing appender mutation; actual persistent records determine count and registry settlement | Exact historical receipt returns without append; copied/conflicting receipts fail. Appender error may leave observed records and Undo entry; no rollback or replay. |
| Settled registration -> JSON save | Publisher and existing exact-object/path app save callback -> `core/io.save_project_to_json` | One-shot `saving` marker; temp JSON flush/fsync then `os.replace`; callback result and fresh original-host check settle separate persistence outcome | Registration uncertainty prevents save. Exact callback true/false/unknown maps to saved/failed/uncertain. Lost authority after write remains uncertain. No automatic save retry or changed-target save. |
| Settled work -> retirement / expiry / close | Job registry, inbox and runtime | Known terminal inbox retirement is explicit; job retention cleanup or invalidation is separate | Unknown/stale/lost slots require recovery. Current publisher remains pinned for one envelope; no replacement publisher lifecycle. Expiry/close does not delete files or cancel external work. |

An appender exception with a proven observed partial count currently settles the
registry request as `partially_failed` while its publication receipt remains
`registration_uncertain`. Explicit adapter advancement can then submit later
**distinct** requests. It cannot replay/repair the uncertain request. The
publisher's uncertainty blocks final JSON save even after all later requests
settle. This is the existing count/publication distinction, not a guarantee that
every uncertain append pauses the whole chain. See
`GenerationCandidatePublication.publish_for_characterization`,
`GenerationJobRegistry.publication_for_characterization`,
`ComfyExecutorAdapter.advance_for_characterization`, and the composed test
`test_partial_insertion_never_replays_and_uncertainty_blocks_final_save`.

### Cross-cutting fences and evidence limits

The worker envelope never owns a live Project/path or callbacks. The runtime's
separate private `GenerationPublicationOrigin` carries exact original Project,
path, detached source snapshot and review bytes. Publication accepts exact
store/receipt object custody, not equal IDs. Project switch, successful Save As,
pair release/replacement, disarm, close, process/session changes and lease expiry
remove usable authority. Switching back/re-pairing does not restore it. A
historical duplicate receipt is evidence of an earlier attempt, not current
file integrity or permission to act. Save rehashes promoted images.

IO, hash/decode, clone, factory preparation and save callback run outside
job/inbox locks; expensive IO also releases host gates. Final mutation rechecks
authority under the runtime/route gate. A save callback uses the captured exact
Project/path outside locks, relying on serialized host writer ownership; a lost
post-write host check records uncertainty, never success for a new Project.

Current caps: 100 requests, five runs, 16 images/request; 1,000,000-byte workflow and
8 MiB aggregate manifest; remote payload 64 KiB, receipt retention 512 KiB,
16 late batches; 64 retained events/job, 1,024 events/job; containment 32 MiB/image,
128 MiB/request, 256 MiB/store (quarantine included), 8,192 pixels per dimension
and 16,777,216 pixels total. Registry retains at most eight jobs with prepared
900 s, active 3,600 s and terminal 600 s leases. Inbox reservation is 30 s.
These are memory/work limits, not disk retention promises. Successive stores,
sessions and processes have no global disk-budget manager. C2B-6 duplicates
verified bytes into durable storage; retained staging may coexist with it.

Scene Module Swap has separate custody/ACK/Apply and publication owners.
Generation preparation, claim and publication do not consume its pending review
or mailbox ACK. A later Module Swap/source edit still changes Generation's
source evidence and can fence further publication. Independence does not mean
concurrent mutations to the same Project can ignore freshness.

## Failure and recovery matrix

**M** denotes currently memory-only evidence (all private owners/claims/receipt
indexes/attempt states). **F** denotes actual filesystem bytes that may survive
process exit; OS temp eviction, external writes and power loss are not prevented.
**J** denotes saved Project JSON, if present; existence is not proof of which
attempt wrote it. Remote history/files have server-controlled retention.
The human options below are proposed future operations, not shipped recovery.

| Failure boundary | Surviving evidence / unknowns | Safe future human option and refusal |
| --- | --- | --- |
| Before claim | M review/seeds/confirmation until expiry or close; no external send or journal | Re-inspect and explicitly Refresh/confirm/start a new action. No old ACK authority after drift. |
| Claim accepted, worker response unknown | M consumed custody, job/claim/envelope and observed take/progress if any; external send may be unknown | Inspect original evidence and independently query server if possible. Do not retake, reopen proposal or resubmit. A missing worker response is not no-send proof. |
| ComfyUI submission outcome unknown | M attempted frozen request; prompt ID may be absent; remote job may exist | Preserve unknown status; correlation-assisted inspection only. No retry based on timeout or matching workflow hash. |
| Accepted prompt, execution timeout | M accepted prompt/request, pending count/timeout; external state unknown | Read exact remote history through separately approved inspection. No cancellation inference or duplicate submit. |
| Remote outputs, download incomplete | M validated history/descriptors and failed receipt; F complete files retained, only proven partial owned files may have been removed | Inspect batch; independently verify retained bytes. Current attempt stays pinned. A future human download recovery must be a distinct authorized operation, not implicit retry or publication. |
| Verified local batch, no promotion | M verified image identities/hashes + exact store/host custody; F temp images, not J | Retain/inspect; future explicit recovery only after fresh source/host authorization. Restart cannot reconstruct current authority from files. |
| Partial/interrupted promotion | M attempt pinned, known file identities; F UUID durable files may be partial, complete or unindexed after crash | Hash/decode and reconcile inventory; never infer complete batch from file count/name. Retain ambiguous files, no implicit recopy or Candidate append. |
| Partial Candidate insertion | M observed count/records, uncertainty, Undo; F promoted images; J usually unchanged | Inspect actual in-memory/saved records and exact provenance. No replay of uncertain insertion. Later distinct requests may progress as above; final save stays blocked. |
| Registration complete, save not attempted | M registered Candidates/counts and Undo; F durable assets; J absent/older | Original live authorized owner may perform its one save. Restart loses that owner; reconcile older JSON before any new human recovery association. |
| Definitive save failure | M callback false and complete registration; F assets; J absent/older or independently existing | Retain files and in-memory Candidates, show unsaved. No publisher retry. Future explicit save/recovery must inspect current source and reconcile exact JSON first. |
| Save uncertain after atomic replacement | M callback unknown/lost authority; F assets; J may already contain every Candidate | Read/reconcile JSON and hashes before any further write or association. Do not roll back/delete files or append duplicates based on receipt status. |
| Session close / pair release | M authority invalid/closed, bounded late receipt evidence while process holds owners; F unchanged; remote may run | Observation/inventory only until new explicit recovery authorization. Re-pairing cannot revive old job. No expiry cleanup or remote cancellation assertion. |
| Project switch / Save As | M activation/path/epoch mismatch; F retained, registration or J may precede transition | Preserve original exact-target evidence. Never redirect to active/new path. Switching back does not restore authority; inspect both known save locations when relevant. |
| Process crash / restart | M lost: claims, accepted envelope identity, history, path/file indexes, exact source/ACK/pairing; F/J may survive | Current implementation has no journal, scanner or reconstruction. Explicit bounded inventory is a prerequisite. Neither Project reopen nor identical path creates the old owner. |
| Orphan staging/durable files | F only; ownership, batch completeness, hash/provenance/publication/save association may be unknown | Treat as unverified inventory candidates, not receipts. No glob-based adoption or deletion. Quarantine pending provenance/reconciliation. |
| Unknown remote execution after local expiry | M may expire/evict; no local asset guaranteed; server may still execute/retain output | Show unresolved external operation. Require remote correlation evidence or human acknowledgment of unresolved ownership; never automatically cancel, resubmit or declare failed. |

The current atomic JSON writer fsyncs the temporary file and replaces the
destination. It has no journal transaction tying that replacement to assets,
and no parent-directory flush/power-loss contract. C2B-5/6 fsync image files,
but do not make directory entries, claim state or receipts restart durable.
Tests raising after replacement prove truthful uncertainty with readable JSON;
they do not prove survival of power failure at every point.

## Proposed human recovery authority

The later C2B-8C-3 [trust-profile decision](agent-generation-protected-storage.md)
and [fresh Recovery authorization design](agent-generation-human-recovery.md)
refine the policy gates below. Profile A: Local Single-User Application is
formally adopted as Pro's supported security scope: locally operated personal
Windows illustration production. Public online service deployments are outside
that threat model; online self-deployers add and maintain their own protection.
The PromptGraph Lite hosted demo does not expand Pro's guarantee. Hostile
same-Windows-user processes, Administrator/SYSTEM and compromised host code are
out of scope. LLM/MCP instructions remain untrusted, and human Start, Recovery
and Discard custody and all existing agent safety boundaries remain.
Profile B is an unsupported optional future deployment design, not a prerequisite
for normal Pro development. All current production and Recovery gates stay closed.

Recovery of already existing bytes and generation/resubmission are distinct
operations. Inventory never takes an inbox envelope, sends `/prompt`, consumes
a new proposal, publishes Candidates, saves or deletes anything. It reports
observations and uncertainty, with explicit scan/budget boundaries.

1. **Inventory/inspection:** a host-owned protected-root allowlist yields bounded
   untrusted records and retained files; no current/last Project inference.
2. **Integrity verification:** open without following reparse/symlink paths;
   verify root/ancestor/file identity, byte limits, image decode and hash against
   independently trusted private evidence. Hash equality proves bytes only.
3. **Saved-JSON reconciliation:** explicitly select the original recorded Project
   location; load its current JSON, preserve unknown fields, inspect canonical
   Candidate provenance/path/hash relationships and distinguish absent, exact,
   partial and conflicting records. Re-read identity/content before any commit.
4. **Human decision:** display all files/requests, source differences, registration
   and persistence uncertainty. Offer inspect, defer, separately reviewed
   association, or separately reviewed discard. Nothing auto-selects recovery.
5. **Fresh host authorization:** an eventual new recovery lifecycle needs a new
   explicit human review/action and current session/Project/activation/epoch/
   pairing binding. It cannot reconstruct the old claim or pretend an expired
   original object survived. After restart an explicitly chosen new host must
   establish a new recovery contract against the original persisted source
   evidence; this is not implemented and requires its own review.
6. **Retention/cleanup authorization:** a separate decision proves storage
   ownership and resolves Project references/save/external-operation uncertainty.
   Association approval never implicitly approves deletion, or vice versa.

Refuse automatic association for a changed/missing Project or Illustration,
missing original source evidence, changed prompt/negative prompt/Module/Scene
state, lost pairing/activation, uncertain save, ambiguous request/output order,
duplicate/conflicting saved provenance, unverifiable bytes or missing journal
ownership. A matching public Project ID, path, prompt ID, old receipt, workflow
hash, file hash or user assertion cannot independently authorize association.
Changed source may be inspectable but cannot be silently treated as original;
any intentional remapping requires a separately reviewed new operation. An
exact saved Candidate is reported as already associated, not appended again.

## Proposed bounded restart inventory and ownership journal

No journal or persistent inventory is implemented here. A production design must
establish an application-owned private journal and approved containment/durable
roots under a reviewed Windows logon-user ACL policy. `chmod`/UUID names alone
do not establish that policy. Remote storage remains owned by ComfyUI.

### Minimal record and authenticity

A versioned private record needs an operation nonce, schema/version, originating
process/session observational identity, job/claim/manifest/request/run/workflow
correlations, frozen source/review fingerprints and seed/prompt evidence,
approved root identities, each bounded relative file reference/size/hash/format,
validated remote-history success/correlation, and independent submission,
containment, promotion, observed registration and save-intent/result states.
Include sequence/revision, predecessor digest and explicit unknown outcomes;
never persist an executable Start credential or a runnable inbox/approval token.

Proposed ceilings: existing 100 requests/16 images/request, one journal operation
with at most 1,600 file references, at most 16 MiB including manifest/review and
bounded original history, and 64 retained checkpoints. Refuse overflow before
external work; do not truncate provenance needed for reconciliation. Sensitive
prompt/path/endpoint evidence stays private and is redacted from public jobs/MCP.
Endpoint secrets should not be journaled; frozen endpoint identity and a
separately protected transport configuration suffice.

Records remain unauthenticated on restart even when strict bounded schema, root
ownership, sequence/digest and integrity checks succeed. SHA-256/digest chains
and ACL observations do not authenticate their author. Optional future Profile B
authentication needs independent protected producer/key/service custody; it is
not a supported local-use prerequisite.
Reject unknown schema, absolute/escaping references, fabricated/rolled-back or
conflicting journal revisions and stale owner incarnations. Even an authenticated
journal proves retained observations, not current publication authorization.
The same-user process with write access to all roots is outside the current
integrity-only guarantee; do not claim cryptographic or ACL protection without
implementing and testing it.

Profile A permits bounded acknowledged writer observations as a current host tip
within the live host/process lifetime. After restart, absent an independently
retained host-observed tip, latest-head custody is unavailable. Where/how to retain
a checkpoint and its write/acknowledgment order and uncertainty contract remain
unresolved. A digest-valid prefix or identical path grants no automatic rollback
repair, replay, Recovery association or execution.

### Write order and crash states

| Boundary | Required future journal ordering | Crash interpretation |
| --- | --- | --- |
| Before external submission | Persist exact frozen request identity and one-shot submission intent before calling transport; then persist accepted prompt or unknown/definite no-send evidence | Intent without conclusive outcome is unknown, never an unsent retry candidate. No local journal can guarantee network exactly-once. |
| Download/local verify | Record attempt before allocation; flush/fsync complete image handles, verify identity/hash/decode; atomically commit complete batch record only afterward | Uncommitted files are incomplete/unverified inventory, even when decodable. Partial batch cannot be reconstructed as verified automatically. |
| Durable promotion | Record promotion intent; exclusive UUID copies, flush/fsync/check; commit complete promoted mapping after batch verification | Missing commit or partial copy is retained uncertain evidence; do not adopt or overwrite. |
| Candidate append | Record association intent before in-memory mutation; record exact observed Candidate delta after fenced commit | Crash may lose Project memory even with observed-count record. Saved JSON is authoritative for persistence, not memory checkpoint. |
| JSON save | Persist expected serialized Project/Candidate identity and destination/save intent before write; temp-file flush/fsync -> replace -> durability barrier -> persistence checkpoint | Missing final checkpoint means uncertain save, even when replacement occurred. Reconcile destination content before any further action. |
| Inventory/cleanup | Persist bounded read-only scan checkpoint; cleanup has separate explicit authorization and ownership/reference checks immediately before deletion | Interrupted inventory can resume bounded inspection without action authority. Interrupted cleanup reports remaining uncertainty; no blind recursive retry. |

Journal checkpoints use a same-directory exclusive temporary file, bounded
encoding, file flush/fsync, atomic replacement and platform-supported directory
durability barriers. Specify and test Windows handle/FlushFileBuffers semantics
and filesystem support rather than claiming a portable directory fsync guarantee.
Images, journal and Project JSON are separate writes, so reconciliation remains
necessary. Never remove retained assets merely because a newer checkpoint exists.

Inventory scans only explicit approved C2B-5 roots and C2B-6 asset parents; never
the entire temp drive/Project tree. Proposed inspection page limit: 32 owned
operation roots and 1,600 entries/root, 16 MiB metadata, 256 MiB hash budget per
user action, stable opaque cursor and "more/unverified" status. Stop on capacity,
identity/reparse changes or unavailable roots. Recheck every resumed entry;
interrupted scans are observations, not freshness certificates. Unknown/orphan
entries stay separate from authenticated ownership records. A disk budget must
account for staging plus promoted copies across sessions/processes and reserve
capacity before submission, with no eviction of protected or uncertain evidence.

## Proposed retention and cleanup policy

Retention durations/caps below are planning defaults requiring product approval,
not an implemented deletion schedule. Storage ownership belongs to a dedicated
host inventory/retention owner, not Job Registry expiry or remote callbacks.
Capacity handling should stop new work and expose required human action; it must
not silently remove evidence. A proposed per-user 2 GiB staging/quarantine budget
with a visible 80% warning is separate from host-approved Project asset capacity.
Neither budget is permission to delete protected files.

| Evidence class | Proposed retention/status | Safe cleanup prerequisite |
| --- | --- | --- |
| Verified unpublished images | Retain at least seven days, "verified, unassociated"; prompt human review at threshold/cap | Explicit discard plus proven ownership, no saved Project reference, no uncertain save/external operation; age alone never deletes. |
| Published assets referenced by saved Projects | Project asset lifetime; "referenced/saved" | Separate Project-aware removal/reference reconciliation, including known saves/forks; ordinary generation retention must refuse deletion. |
| Promoted after failed/uncertain save | Pin as "unsaved/possibly saved" without automatic TTL deletion | Resolve JSON association/save uncertainty and explicit human cleanup; a false/unknown callback does not authorize deletion. |
| Orphan/incomplete files | Quarantine, seven-day review reminder; bounded inspectable inventory | Prove root/file ownership and unresolved-operation/reference absence; missing receipt is not enough. Unproven orphan ownership remains inspect-only. |
| Unknown external submission | Pin observational journal/status until resolved or explicitly archived as unresolved | Do not equate local expiry with remote completion/cancellation. Cleanup of related files requires explicit reconciliation; external uncertainty must remain recorded. |
| Quarantined/stale complete outputs | Retain under quarantine cap; never offer default association | Inspect integrity, resolve references and explicit discard. Stale job authority cannot be used to recover or delete. |
| Expired session memory / recovery metadata | Existing bounded memory TTL/eviction may forget; future minimal private journal retained until evidence resolution | Expiry may retire memory only. Do not run file cleanup from it. Journal retirement follows verified reconciliation and preserves unresolved status. |
| Remote ComfyUI images/history | Server policy, explicitly shown as unknown unless independently observed | Local retention/cleanup does not delete remote files or assert remote cancellation; remote cleanup is separately authorized transport work. |

Directory-wide deletion is refused for project-referenced files, ambiguous save,
unresolved external operations, incomplete inventory, unknown ownership or
reparse/identity drift. Current C2B-5 cleanup of a proven incomplete newly owned
file is narrowly part of a failed stream attempt; it is not this future general
retention policy. C2B-6 has no destructive cleanup. Restart must never auto-adopt,
auto-publish, auto-save, replay execution or revive expired authorization.

## Readiness assessment (PR #186; C2B-8D-17E-B)

The PR #174/17C matrix is retained as historical context; this section is the
current assessment through PR #186. PR #186 adds explicit protected Journal replacement admission and
reconciliation APIs on top of 17E-A; PR #184/185/186 have also added promotion
and Journal capacity integration. The following classifications distinguish
offline implementation, direct tests, test composition, production connection,
and environmental evidence.

| Transition | Evidence classification and current characterization | Concrete source and test evidence | Missing production implementation or dependency |
| --- | --- | --- | --- |
| Frozen manifest → review → confirmation → Human Start | Manifest and review/confirmation are implemented and directly tested. A separate Start/handoff boundary is characterized, but is not connected to a production UI or caller. Review confirmation does not authorize execution. | `core/generation_executable_manifest.py`; `ui/agent_generation_start_lifecycle.py`; `ui/agent_generation_executor_handoff.py`; `tests/test_agent_generation_executable_manifest.py`, `tests/test_agent_generation_executable_review_ui.py`, `tests/test_agent_generation_review_custody.py`, `tests/test_agent_generation_start_lifecycle.py`. | Add a visible, explicit, fresh Human Start action and production original-host lifecycle only after storage, transport and shutdown gates. Keep Start distinct from review confirmation. |
| Executor handoff → multi-request Journal intent → HTTP submission | The sequential one-shot executor and V1/multi-request Journal contracts are implemented and composed with injected offline HTTP wires and an explicitly started characterization Worker. No production transport/worker registration exists. Protected Journal capacity methods are an explicit opt-in and are not called by default from `GenerationExecutorJournalIntent`. | `ui/agent_generation_executor_journal.py`; `ui/agent_generation_http_executor.py`; `ui/agent_generation_http_io_worker.py`; `core/generation_protected_journal.py`; `tests/test_agent_generation_executor_journal.py`, `tests/test_generation_protected_journal.py`, `tests/test_generation_protected_multi_request_journal.py`. | Decide and implement production original-host ownership, Worker registration/shutdown and whether production Journal writes must use the capacity-integrated append methods. Preserve intent-before-send, one-shot claims and unknown outcomes. |
| History/result → protected stream → staging → acceptance | History, `/view` streaming, staging and protected batch acceptance each have bounded direct offline tests. HTTP submission/history compose through the Executor, while protected streaming/acceptance use separate injected stream providers; there is no single test composition from HTTP history through HTTP view into an accepted protected batch, and no production composition. | `core/comfy_http_history.py`; `core/comfy_http_view.py`; `core/generation_windows_protected_assets.py`; `tests/test_comfy_http_history.py`, `tests/test_comfy_http_view.py`, `tests/test_generation_windows_protected_stream.py`. | Connect exact correlated history descriptors to the bounded HTTP stream owner under original-host freshness and protected-root lifecycle. Validate actual ComfyUI `/history` and `/view` behavior before production use. |
| Protected staging → acceptance → promotion → `outputs_ready` → Candidate admission → Gallery registration | The owners are individually tested and the protected Candidate publication composition connects promotion, count-only event, admission and the existing Gallery Candidate writer in disposable Windows fixtures. This is composed offline evidence, not production publication. | `core/generation_windows_protected_assets.py`; `core/generation_windows_protected_promotion.py`; `ui/agent_generation_protected_candidate_admission.py`; `ui/agent_generation_candidate_publication.py`; `tests/test_generation_windows_protected_promotion.py`, `tests/test_agent_generation_protected_candidate_admission.py`, `tests/test_agent_generation_protected_candidate_publication.py`. | No production entry point or publication authority. Add production custody only through the existing single Candidate writer, preserving exact provenance, idempotence, Undo and no-replay uncertainty. |
| Candidate registration → Project JSON save and uncertainty | Exact-object/path save is separately one-shot and directly exercised in the protected composition. Disposable JSON is reopened and its Candidate provenance checked; failed/unknown saves remain uncertain. | `ui/agent_generation_candidate_publication.py`; `core/io.py`; `tests/test_agent_generation_protected_candidate_publication.py`, including saved JSON reopen, event-eviction, callback outcome and host-loss cases. | Production publication/save is not connected. Establish host UI feedback, persistence error handling and durability expectations without adding a parallel Project writer or automatic save retry. |
| Protected capacity: byte image, stream, promotion batch and Journal replacement | 17A provides five-root native preflight/inventory and process-local reserved/used/uncertain accounting. 17B/17C integrate byte and streamed staging writes; 17D integrates exact promotion-batch writes; 17E-A/B integrate protected Journal replacement accounting through explicit methods. These are directly characterized with disposable Windows roots. | `core/generation_storage_admission.py`; `core/generation_windows_protected_assets.py`; `core/generation_windows_protected_promotion.py`; `core/generation_protected_journal.py`; `tests/test_generation_storage_admission.py`, `tests/test_generation_windows_protected_assets.py`, `tests/test_generation_windows_protected_promotion.py`. | The protected Journal capacity integration is **not connected by default to `GenerationExecutorJournalIntent`**. All integrations are explicit characterization opt-ins. No production root provisioning, cross-process/OS quota or restart-time reservation recovery exists; free-space observations are advisory. |
| Worker lifecycle, close/invalidation, restart inspection and Human Recovery | A bounded host-owned I/O Worker has direct offline tests for start, queueing, close, late result and host invalidation. Journal reopen and Human Recovery are read-only/inspect-only and directly tested. | `ui/agent_generation_http_io_worker.py`; `core/generation_protected_journal.py`; `ui/agent_generation_human_recovery.py`; `tests/test_agent_generation_executor_journal.py`, `tests/test_generation_protected_journal.py`, `tests/test_agent_generation_human_recovery.py`, `tests/test_generation_ownership_journal.py`. | No production scheduling/shutdown/replacement, restart continuation, Recovery UI/Apply, or discard/cleanup lifecycle. A restarted process cannot reconstruct claim or latest-head authority from Journal bytes; missing/conflicting independently observed evidence stays uncertain. |
| Profile A threat scope and authorship | Profile A is adopted for local single-user Pro. Untrusted LLM/MCP instructions remain outside the trust boundary. | `docs/architecture/agent-generation-protected-storage.md`; Profile A policy references in the Journal, Recovery and publication architecture. | `authorship=unverified`: SHA-256, ACL and native identity evidence are not cryptographic author authentication. Profile B service/key infrastructure is optional unsupported architecture, not a prerequisite for Pro. Same-user malicious processes, Administrator/SYSTEM and compromised host code remain outside scope. |

The protected path is **composed across owners in tests**, but there is no one
live HTTP-to-Project-save exercise. `tests/test_agent_generation_protected_candidate_publication.py`
uses disposable original-host state, protected native roots, the existing
Candidate factory/appender, Undo snapshot and save callback. HTTP submission,
history and view contracts use injected/offline wires; protected staging uses
injected stream providers. This does not demonstrate live ComfyUI behavior,
process-crash durability, production authorization or actual user storage
policy.

This assessment table is the PR #186 snapshot. The C2B-8D-19A addendum at
the end records the later non-executing original-host lifecycle foundation and
supersedes the table's recommendation to start by defining that foundation.

### Focused validation and environment evidence

Validation was run on Windows 11 Pro x64 build 26200, CPython 3.14.4, Streamlit
1.60.0 and pywin32 312. The project-local `.venv` was created by the documented
`setup.bat`; supported-environment and exact 69-package runtime-lock checks
passed. Pytest 9.1.1 was added as an audit-only tool because pytest is
intentionally not part of the committed runtime lock. The system Python had
Streamlit 1.56.0, below the supported/pinned 1.60.0; it was not used for the
green validation runs.

| Focused suites | Result |
| --- | --- |
| Protected storage admission, protected Journal V1/multi-request, protected roots/assets, stream and promotion (8 selected suites) | 446 passed, 0 skipped, 0 errors. Windows-native ACL/identity cases ran with pywin32 available. |
| Executor-Journal, handoff, Comfy executor, HTTP submission/history/view, protected Candidate admission/publication and existing Candidate publication (9 selected suites) | 631 passed, 1 skipped, 0 errors. The skip was `test_symlink_approved_directory_is_refused`: this Windows host did not permit disposable symlink creation. |
| Executable manifest/review/confirmation, Human Start, preview, ownership Journal, multi-request Journal, Human Recovery and prior integration audit (10 selected suites) | 381 passed, 0 skipped, 0 errors. |
| PR #186 native Journal ACK/ledger compensation with competing admission (`test_native_integrated_journal_post_commit_ack_failure_retains_prior_and_full_bound`) | 3 consecutive passes; the complete storage-admission suite above also passed it. |
| Executor-Journal collection under the supported environment | 66 tests collected successfully; no Streamlit collection error. |

The bare system interpreter reproduced the Executor-Journal collection failure:
Streamlit 1.56.0 raised `TypeError: fragment() got an unexpected keyword
argument 'parallel'` while importing `ui/project_agent_session_pump.py`. That
version is below the supported/pinned Streamlit 1.60.0. In the supported
project-local environment the same suite collected all 66 tests successfully,
so this checkpoint identifies an environment mismatch rather than a collection
failure in the supported runtime. The full repository suite was not run. No real
ComfyUI/network requests, production Worker, restart continuation, Recovery
Apply, cleanup or production Start were attempted.

### Implementation gaps versus environment gaps

The remaining no-go items below are implementation/authorization gaps: there
is no production Start caller, production Worker/HTTP registration, approved
root provisioning lifecycle, production Candidate/save call path or restart
authority. They are not resolved by passing offline tests. The test-environment
gap was Streamlit 1.56.0 in the unpinned system interpreter; the supported
Streamlit 1.60.0 project environment collected and ran the focused suites. One
Windows symlink characterization remained skipped because this host denied the
operation. No runtime lock change or unsupported environment workaround was
used to claim success.

## Production go/no-go and next bounded milestones

**Decision: no-go for production Generation or executable Recovery.** The
offline route is materially broader than the PR #174 baseline, but production
capability flags remain false. Profile B keys or service infrastructure are
not prerequisites for supported local Profile A use. That policy decision does
not weaken explicit human Start, Recovery and Discard authorization;
source/review provenance; Project integrity; Candidate idempotence; or truthful
save uncertainty. LLM/MCP instructions remain untrusted even though hostile
processes under the same Windows user are outside the adopted Profile A threat
model.

| Order | Milestone | Remaining implementation gap and risk | Evidence required to close the gate |
| --- | --- | --- | --- |
| 1 | Original-host integration and production lifecycle | No production owner registers the Worker/transports, survives Streamlit reruns, fences close/replacement or delivers results to the same Project/session. | A separately reviewed production lifecycle with exact Project/path/session/process/activation/pairing and claim binding, bounded shutdown, one-shot intent-before-send and original-host event delivery; failure/close races remain unknown and non-retriable. |
| 2 | Protected root provisioning and capacity policy | Current roots are host-supplied native observations for disposable fixtures. Reservations are process-local, not an OS quota; 17B/C/D and 17E-B methods require explicit opt-in, and Journal capacity is not the default Executor append path. Profile A Promotion currently has destination-capacity preflight only; retained source plus destination may exceed the shared 16-entry/256 MiB policy. | Define a local Profile A root lifecycle that never repairs/adopts existing user directories; integrate the exact selected capacity methods at production writers; document concurrent app/process and restart accounting policy, evidence retention and capacity ceilings. Resolve bounded retained-source/destination accounting before the Profile A Promotion writer. No disk-space guarantee should be claimed. |
| 3 | Real ComfyUI/HTTP interoperability | All transport tests use injected/offline wires; endpoint, version, history status, `/view` descriptors, response framing and remote uncertainty have not been observed against a real server. | After explicit human authorization and disposable endpoint selection, verify exact POST/history/view behavior, supported workflow compatibility, bounded outcomes and no-resubmit semantics. Record the server/runtime version and uncertain cases. |
| 4 | Explicit Human Start and UI activation | Review/confirmation and a Start characterization seam exist, but no production UI action dispatches it. | Add a distinct explicit human Start control and visible pending/unknown/unsaved state. Revalidate review, Project and host identity immediately before a one-shot production claim; confirmation alone must not execute. |
| 5 | Candidate publication and Project JSON save | Existing Candidate/Undo/save owners have protected offline composition but no production call path for these receipts. | Connect only through the existing Gallery writer and exact-object/path save owner; prove idempotent provenance, Undo ordering, partial-append uncertainty, one-shot save and reload integrity in the supported host lifecycle. |
| 6 | Restart, Recovery, retention and discard | Reopened Journal/Recovery data are inspect-only. After restart there is no independently retained original-host latest-head observation, so authority cannot be inferred from a valid prefix, digest, file or prompt ID. There is no production retention/discard lifecycle. | Define restart latest-head custody separately from live-host observations; require independent original-host evidence or retain `uncertain`. Add inspect-first Recovery and explicit human association/Discard, with bounded retention and no replay, automatic rollback or cleanup. |

C2B-8D-19A provides a non-executing original-host lifecycle foundation; 19B
adds the legacy five-root Worker association; 19C-B binds a four-root Profile A
capacity owner and separate Project reference; and 19C-C associates that
binding with one supplied Worker. These remain non-executing
characterizations. They do not enable a production transport, Start, protected
write, publication or save. Root provisioning and capacity-writer integration
remain separate gates before live ComfyUI use.

Before activation, each gate needs its own implementation review and production-
appropriate validation. In particular, protected Journal capacity integration
must remain explicit until a reviewed production owner connects it; the
`GenerationExecutorJournalIntent` characterization path currently does not
select those capacity-integrated append methods. No PR in this audit enables
that connection.

Until those gates are closed, keep
`execution_available=false`, `protected_storage_available=false`,
`promotion_available=false`, `candidate_publication_allowed=false`, and
`authorship=unverified`. Candidate publication remains unavailable and Human
Recovery remains inspect-only. No automatic retry, replay, cleanup, or MCP
execution substitutes for the required human and original-host authority.

## C2B-8D-19A non-executing original-host lifecycle foundation

ui/agent_generation_original_host_lifecycle.py adds one private lifecycle
associated with the existing ProjectAgentSessionRuntime. It reuses the
runtime's ProjectTargetTracker, ProjectAgentSessionRegistry,
GenerationJobRegistry and GenerationExecutorInbox; it does not add another
session manager, registry, inbox, or Project owner.

A binding holds a weak reference to the exact selected Project object and
compares the exact supplied Project path, tracker target epoch/activation,
runtime, registration object and route ID, registry process incarnation,
job-registry session/process incarnation, live pairing generation, and the
exact currently held immutable envelope/job objects when a claim exists.
Opaque IDs are only correlation within those exact owner references. Repeated
full-app runs with the same observed target and owners retain the same lifecycle.
Project object/path/epoch changes, route or registration replacement, pairing
generation changes, issued job/claim replacement, explicit disarm, or runtime
Close retires the old lifecycle permanently. Returning to a prior Project or
path creates a new generation.

Readiness, Worker correlation, and Worker-result observation each check the
exact current registration and pairing generation while holding the route's
short operation lock. A pairing release/replacement or route invalidation is
therefore fenced at the next observation even if Streamlit has not performed a
new full-app synchronization. A later synchronization can create a fresh
generation only when current host and claim evidence is still mutually
consistent; an old claim bound to a prior pairing remains unavailable.

States are bound_non_executing, revocation_requested, closed, and
uncertain. A revoker marks revocation_requested immediately. The private
characterization callback runs outside the runtime, job, inbox and lifecycle
locks; while it is active, Close/replacement does not wait and does not close
resources. When that bounded callback returns, the retired lifecycle becomes
closed. Observation failure becomes terminal uncertain. This slice owns no
protected operation or native handle, so it has nothing to close underneath an
in-flight protected operation. Lock order is runtime publication gate, route
registry snapshot, job registry, inbox, then the lifecycle's short lock.
No native I/O, network request, worker wait, or user callback is made while
holding those locks.

The readiness projection reports only bound/unavailable categories and the
presence or mismatch of dependencies. `OriginalHostGenerationLifecycle.observe_protected_references_for_characterization()`
checks that the supplied five purpose-root objects are the exact objects held
by the supplied `WindowsProtectedStorageAdmissionCharacterization`. It does
not call root readiness, inspect paths, revalidate ACLs or file identities,
provision roots, create a ledger, select a writer, or infer storage
authorization. Writer dependencies remain absent unless a later reviewed
integration adds them. `native_acl_or_identity_revalidated` is always false
for this legacy reference-only seam.

The Worker seam returns only bounded lifecycle/job/claim/manifest correlation
scalars. Fixed-field worker observations may be retained in a bounded
in-memory diagnostic queue, but even an exact observation is classified only
as observed_non_authoritative; stale, foreign or late correlations are
stale_non_authoritative. Neither path emits an ExecutorEvent, advances the
Job Registry, authorizes the next request, or grants Candidate/save authority.
The worker receives no Project, session state, mutable host owner, route handle,
root object or executable capability from this lifecycle.

All gates remain false: execution_available,
protected_storage_available, promotion_available,
candidate_publication_allowed, Project save, Recovery execution, Human Start,
and cleanup. authorship=unverified.

Focused characterization is in
tests/test_agent_generation_original_host_lifecycle.py, alongside existing
session runtime, Job Registry, handoff and review custody regressions. It proves
same-target identity preservation, replacement/no-resurrection, pairing and
registration rotation, bounded non-authoritative foreign/stale Worker results,
revocation during a blocked callback, runtime-gate serialization, reentrant
Close and reference-only root/capacity matching. These tests use no real
transport or protected filesystem operation.

## C2B-8D-19B non-executing Worker/storage association

`ui/agent_generation_original_host_worker_storage.py` adds one private
`OriginalHostWorkerStorageIntegration` to an explicitly opted-in 19A lifecycle.
The runtime accepts one exact, supplied `HostOwnedHTTPIOWorker`, the five
purpose-root objects and their matching
`WindowsProtectedStorageAdmissionCharacterization`. Binding verifies the exact
owner types, purpose names, object identities and a fresh Worker with no prior
accepted/completed operations. The Worker atomically records a one-shot owner
claim under its existing state lock, shared with start and operation admission;
another lifecycle cannot claim that Worker, and the claim is never transferred
or released for a later generation. An associated operation must first register
its exact correlation through the original-host owner, so an unregistered
caller cannot start transport work on the claimed Worker. Same-target reruns
preserve the association;
Project/path/epoch, route/pairing, claim, disarm and runtime close changes
permanently revoke it. Retired integration owners remain strongly retained in
a 16-owner runtime bound; new integration binding is refused at the ceiling
until a clean, non-uncertain close is explicitly observed. Uncertain evidence
is retained and is never evicted to make room.

The integration exposes characterization-only correlation and operation-lease
methods through `ProjectAgentSessionRuntime`:
`bind_generation_worker_storage_for_characterization`,
`generation_worker_http_correlation_for_characterization`,
`begin_generation_worker_http_operation_for_characterization`, and
`observe_generation_worker_http_result_for_characterization`. Before issuing
or accepting correlation it rechecks the exact tracked Project object and
normalized path, target epoch/activation, live nonterminal job and claim,
manifest/envelope objects, session/process, route and current pairing under
the runtime's ordered host locks. A prepared request is revalidated against
the exact finalized envelope request, host endpoint, workflow bytes and output
nodes. Beginning a host operation installs one exact Worker-local correlation
admission before returning its lease; that registration is consumed when the
Worker admits the operation and is cleared by revocation. Submission
correlation is one-shot; history correlation is limited to
the exact UUID from a current, exact Worker-issued accepted completion for
that request. The HTTP result and prompt UUID remain diagnostic/correlation
data; neither advances the Job Registry or Inbox or grants authority.

An active operation lease, its Worker and the exact five root/admission-owner
references remain held if host revocation occurs during work. The new
`HostOwnedHTTPIOWorker.request_close_for_characterization()` is a short,
nonjoining fence used during revocation. It refuses further task admission,
marks a possible POST as uncertain and reports `close_pending` while its thread
is alive. `finish_generation_worker_storage_close_for_characterization()` is
the separate bounded join path; it runs outside runtime, route, registry, Job,
Inbox and lifecycle locks. Close is idempotent and reentrant. A result that
arrives after revocation is stale, and uncertain operation leases keep their
root references even if the Worker thread later terminates.

This is reference ownership only. The integration never starts or calls
`perform_for_characterization()`, performs no native root/ACL/file verification
or storage write, and invokes none of the capacity-integrated methods. The
selected later writer seams remain
`WindowsProtectedAssetsCharacterization.create_image_with_admission_for_characterization`,
`stage_remote_image_with_admission_for_characterization`,
`ProtectedDurablePromotionCharacterization.promote_with_capacity_admission_for_characterization`,
and `WindowsProtectedJournalCharacterization.append_with_capacity_for_characterization`
plus its multi-request intent/outcome/settlement variants. Selecting their
names here creates no writer callable or storage authority. Journal append is
not connected to `GenerationExecutorJournalIntent` by this PR.

Focused coverage is in
`tests/test_agent_generation_original_host_worker_storage.py` and the 19A
lifecycle suite. It uses injected local fake transports and disposable
reference-only owner objects; no external HTTP request or protected filesystem
write is performed. It covers exact binding, used/mismatched owners,
same-target preservation, Project/pairing/claim revocation, one-shot submission,
accepted-prompt history correlation, non-authoritative results, stale/foreign/
duplicate results, blocked transport close, reentrant runtime close, retained
uncertainty and root references.

19B is not production original-host integration. There is still no production
Worker registration or Start UI, no production transport or root provisioning,
no native ACL/identity revalidation at this new boundary, and no call to the
capacity-integrated image, promotion or Journal writers. Candidate publication,
Project save, executable Recovery, Discard and cleanup remain separate gates.
Process restart, concurrent PromptGraph processes and capacity reservation
recovery are unresolved. All production capability flags remain false and the
production decision remains NO-GO.

## C2B-8D-19C-A Profile A protected-root placement and capacity policy

The proposed Profile A layout places the four app-owned writable roots
(`private_journal`, `temporary_containment`, `retained_uncertain`, and
`promoted_assets`) under one local app-specific scope in the user's Local
AppData. The independently selected Project JSON remains at its ordinary
user-selected path and is a read-only original-host reference, not part of the
private storage tree. No Project move, copy, ACL repair, or production root
provisioning is authorized by this policy.

At the 19C-A policy checkpoint, the 17A admission seam required all five
purpose roots, including `selected_project_json`, beneath one approved scope.
C2B-8D-19C-B now adds a four-writable-root characterization plus an independent
read-only Project JSON reference, then binds its normalized path to the exact
current original-host lifecycle. This closes that characterization gap without
moving or re-ACLing Projects; production admission remains NO-GO.

Capacity accounting remains process-local rather than a disk quota. The
256 MiB staging-plus-promotion budget and 16 entries are shared; uncertainty
remains charged and is never automatically moved or deleted. The 19C-B
scope-writer lease excludes a second cooperating PromptGraph admission owner
for the same native scope, but does not prevent unrelated processes that ignore
the lease or guarantee disk space. Free-space checks cannot prevent later
`ENOSPC`. Process restart loses reservation tokens and live latest-head
custody; fresh inventory is uncertain and cannot restore a reservation whose
write left no file. Production write admission still requires a production
scope lifecycle and a reviewed restart policy. Root close does not delete
files. The detailed policy, bounds, 19C-B contract and next acceptance criteria
are in the [protected-storage architecture](agent-generation-protected-storage.md#c2b-8d-19c-a-profile-a-protected-root-placement-and-capacity-policy).

The 19C-A portion was policy-only. C2B-8D-19C-B adds an opt-in disposable
scope lease and host binding characterization but does not change any writer,
connect Journal capacity by default, enable execution, or grant Project,
Candidate, Recovery, or cleanup authority. All production flags remain false
and `authorship=unverified`.

## C2B-8D-19C-B four-root binding and scope lease characterization

The new `capture_profile_a_root_set_for_characterization()` API accepts the
four exact writable purpose owners under one independently approved local
NTFS scope and reuses the existing 17A capacity ledger. The legacy five-root
capture remains available. Both forms acquire the same scope lease, preventing
a second cooperating process from constructing a competing ledger through
either API.

`WindowsProjectJsonReferenceCharacterization` separately pins an explicitly
selected existing Project JSON outside the protected scope. It validates a
local fixed NTFS ordinary file, native identity, single-link and reparse
conditions, a bounded ordinary DACL shape, and size/last-write metadata. The
Project reference uses read-only access and does not require the protected
root's owner-only DACL. It does not read or hash Project contents, prevent
same-user changes, or grant save authority.

`ProjectAgentSessionRuntime.bind_generation_profile_a_storage_for_characterization()`
revalidates the native root-set and Project-reference owners outside host
locks. It then rechecks the exact 19A lifecycle generation, Project object,
normalized path and target epoch before publication. The lifecycle records
only a reference binding. Project switch, Save As, epoch, pairing or claim
invalidation and session close retire that binding; returning to the old path
does not restore it. Storage evidence is not automatically closed by those
Project transitions. The capacity owner retains a bounded set of exact
lifecycle references for lease-release checks, so runtime garbage collection
cannot hide late Worker uncertainty. A new association is refused while a
prior lifecycle remains unsettled; the storage owner retains at most one
lifecycle association at a time.

`WindowsProtectedScopeWriterLease` uses the approved scope's native volume
and file identity to name a zero-byte owner-only marker, created atomically
with `CREATE_NEW`, no sharing, and native path/identity/ACL checks. Another
process using the admission owner fails closed while the marker exists. An
abandoned marker is not inspected, stolen, timed out or automatically removed.
A settled explicit owner close releases only its exact marker; uncertain
operations or a still-active associated host/Worker lifecycle retain the
marker. Scope close does not delete roots or retained image, Journal, Project
or other evidence files. This is cooperating-owner exclusion, not an OS quota
or protection from a process that ignores the lease.

Focused Windows tests characterize four-root capture, an ordinary Project
outside the scope, identity/ACL/path drift, target replacement during blocked
native readiness, cross-process exclusion, abandoned/uncertain marker refusal
and no binding resurrection. They do not establish production provisioning,
restart reservation recovery, power-loss durability or production write
authorization. After restart, reservations and host authority remain
unavailable; existing files are uncertain, and an orphaned marker blocks
capture pending separately authorized resolution.

The next bounded milestone after C2B-8D-19C-C is the C2B-8D-19D
Worker-to-protected-writer pre-admission characterization below. It reserves
capacity only; the later writer-authorization boundary must still bind exact
remote output evidence and issue the existing native writer admission only
after a fresh original-host check. Production root provisioning, real
transport, Human Start, Candidate/Project publication, restart and
retention/Discard remain separate NO-GO gates.

## C2B-8D-19C-C Profile A Worker/storage association

`ProjectAgentSessionRuntime.bind_generation_profile_a_worker_storage_for_characterization()`
adds an explicit path that binds the existing 19B
`OriginalHostWorkerStorageIntegration` to exactly four writable root owners,
their `_profile_a_root_set=True` capacity owner, the separately captured
read-only `WindowsProjectJsonReferenceCharacterization`, the already-bound
19A lifecycle and one supplied fresh `HostOwnedHTTPIOWorker`. The legacy
`bind_generation_worker_storage_for_characterization()` path remains a
separate five-root contract; it does not infer Profile A from a changed root
map or silently drop `selected_project_json`.

Profile A binding requires the 19C-B lifecycle/reference binding and a current
nonterminal Job Claim, Inbox envelope and manifest before Worker ownership is
claimed. Capacity-root and Project-reference `readiness()` calls are performed
outside host locks. The final publication rechecks Project object and
normalized path, target epoch, activation, route/pairing, lifecycle generation,
Claim and manifest, then serializes lifecycle -> capacity owner -> Worker
claim. Capacity-owner close cannot interleave with the final Worker claim; if
close wins earlier, or a Project, Claim, route, lifecycle, root or reference
changes, the binding is refused. The Worker's existing one-shot owner claim is
preserved and is never transferred or resurrected.

At each later correlation/admission/result boundary, Profile A mode rechecks
that the exact four supplied root objects still match the capacity owner's
four-root map, the capacity owner and scope lease remain open/held, and the
same independent Project-reference object remains bound to the current
lifecycle and path. These are in-memory reference checks. Native ACL, handle,
file-identity and Project-reference freshness are observed at bind time only;
reference equality does not claim a fresh native verification. Native
readiness is never called while host/Claim locks are held. Results remain
diagnostic and non-authoritative, and invalidation prevents new operations or
settles an active operation as uncertain.

Project switch, Save As, epoch, activation, pairing, Claim or lifecycle
retirement revokes the Worker association and requests a nonjoining Worker
close. Active or uncertain operations retain their exact roots, capacity owner,
Project-reference object and scope-lease evidence. Project transitions never
close the app-owned owner or roots, release uncertain capacity, retry work, or
restore the old association on switch-back. An explicitly completed bounded
close can settle only resources whose existing owner contracts permit it;
there is no implicit cleanup.

The Profile A and legacy paths both leave execution, protected storage,
promotion, Candidate publication, Project save and Recovery gates false, with
`authorship=unverified`. C2B-8D-19C-C does not invoke a storage writer, Journal,
HTTP transport, Candidate publisher or Project save. It does not enable
production root provisioning, cross-process quotas, restart authority
reconstruction, retention/Discard, or production worker execution.

## C2B-8D-19D Profile A Worker-to-protected-writer pre-admission

`ProjectAgentSessionRuntime.pre_admit_generation_worker_staging_for_characterization()`
associates one exact currently active host-registered `submission`
`GenerationWorkerOperationLease` with a single bounded
`temporary_containment` reservation in the already bound Profile A
`WindowsProtectedStorageAdmissionCharacterization`. The lease must be the
original object held by the same lifecycle's Worker integration; a copied,
foreign, stale, replayed, or legacy five-root lease is refused. There is at
most one attempt per manifest request, capped at the existing 100-request
manifest bound. The host supplies a `CapacityEstimate` for one request's
staging batch: at most the existing 256 MiB containment aggregate and 16
images. The existing ledger remains responsible for its purpose and shared
temporary/promoted byte and entry limits, retained-uncertain inventory, and
observed free-space refusal.

The runtime first validates the live Project object/path, activation, epoch,
pairing, Job Claim, Inbox envelope, Profile A storage binding, and exact Worker
lease under the existing host lock hierarchy. The native capacity owner then
creates an internal operation and reservation outside host, Job, Inbox,
lifecycle and integration locks. Capacity and separately bound read-only
Project-reference readiness are observed outside those locks. A final host
publication rechecks the same lifecycle, Claim, Project binding, Worker lease,
capacity owner, scope-writer lease, and exact still-reserved ledger tokens.
Only then is a bounded immutable `pre_admitted_non_authoritative` observation
returned. It contains the request index and estimate only; it contains no
correlation, filesystem path, capacity token, operation token, or writer
capability.

This observation does not authorize a download, native write, Journal update,
promotion, Candidate, save, Recovery, or execution. Worker completion remains
diagnostic evidence and is not required or accepted as proof of trusted local
output, successful authorship, or write permission. The API never calls
`admit_write`, starts/performs the Worker, invokes a stream/writer, or creates
files. The legacy five-root binding keeps its previous contract and does not
gain this Profile A pre-admission path.

Duplicate attempts cannot create another reservation. The exact observation
can cancel only its own still-reserved pre-write estimate; Claim/Project/Worker
revocation also fences publication and cancels a provably unconsumed
reservation. If capacity-owner close/invalidation wins after reserve, the
existing ledger retains the estimate as uncertain rather than releasing it.
No capacity reservation or host authority is reconstructed after restart.
The reservation remains process-local accounting, not an OS quota, a disk
space guarantee, or a promise that a later write will succeed. It accounts for
the existing shared staging/promoted cap but does not reserve external worker,
network, Journal-replacement, or unrelated filesystem capacity.

C2B-8D-19E-A below now binds exact accepted/history Worker evidence to this
reservation and stops before writer authorization. The next writer boundary,
19E-B, must consume this exact evidence and reservation, revalidate host/root
state and the actual stream limits, then issue the existing `admit_write`
token to the protected stream owner. It must preserve one-shot send and
uncertain-output rules and prove cancellation/close races. Until that boundary
and later production transport/root/Start/publication gates are reviewed, all
production capability flags remain false and `authorship=unverified`.

## C2B-8D-19E-A Profile A remote-output writer-authorization evidence

`ProjectAgentSessionRuntime.observe_generation_worker_remote_output_writer_evidence_for_characterization()`
is the first half of that writer boundary. It consumes the exact 19D
pre-admission observation retained by the same original-host Worker/storage
integration. The attempt privately binds the one submission lease, its
host-prepared frozen request, the Worker's accepted submission completion and
prompt UUID, the exact later history lease/completion, and the bounded history
JSON returned by that Worker operation. The Worker retains the prepared
request alongside only its latest issued completion; a copied completion,
completion for another prepared request, later replacement, or non-running
Worker cannot be used as equivalent evidence.

The owner passes those original history bytes to the existing
`validate_remote_outputs()` implementation. It requires complete output-node
coverage, unique supported descriptors, exact job/Claim/manifest/request/
workflow/prompt correlation, and an explicit successful history status.
Status-less history is not execution-success evidence. History metadata stays
untrusted remote metadata; filenames and output presence do not prove image
bytes, decoded content, authorship, or local-file identity.

This evidence phase applies a stricter reservation policy without changing the
19D reservation contract: at most 16 images, no more than 32 MiB reserved per
image, and no more than 128 MiB for the request. The existing reservation's
byte estimate must cover the policy bound implied by its descriptor count and
its entry estimate must cover every descriptor. These are host-supplied upper
bounds only; this phase cannot verify actual image sizes because it performs
no download or stream. An immutable
`GenerationWorkerRemoteOutputWriterEvidence` is published only after fresh
capacity/root and read-only Project-reference readiness observations, then a
final original-host Claim/Project/lifecycle check and an exact latest Worker
completion fence. Native readiness runs outside host, Job, Inbox and lifecycle
locks. The final in-memory publication is serialized with lifecycle, capacity,
integration and Worker close/invalidation.

The returned evidence explicitly reports `write_authorized=false`,
`writer_admission_issued=false`, unverified image bytes/content,
`execution_available=false`, `protected_storage_available=false`,
`promotion_available=false`, and `authorship=unverified`. It is retained by
the issuing integration with its exact validated remote receipt. The API does
not call `admit_write`, issue a writer token, make another HTTP request, create
a file, append Journal data, promote an image, or mutate a Candidate or
Project. A safe pre-write refusal may cancel only its exact still
reserved estimate; worker/host uncertainty or failed settlement retains
capacity rather than authorizing replay.

C2B-8D-19E-B below adds the one-image protected Writer handoff. Production root
provisioning, production Worker/transport registration, real ComfyUI
interoperability, Human Start/UI activation, Candidate/Project publication,
restart authority, Recovery, retention and Discard remain separate NO-GO
gates.

## C2B-8D-19E-B single-image protected Writer handoff

The characterization-only runtime seam
`ProjectAgentSessionRuntime.stage_generation_worker_remote_output_with_protected_writer_for_characterization()`
connects the exact 19E-A Worker evidence and privately retained successful
remote receipt to one protected staging stream. It requires the original
Profile A Worker/storage integration, the same bound four-root capacity owner
and scope-writer lease, the exact frozen request and one validated descriptor.
Copied evidence, another integration's evidence, stale host/Claim/Project
state, an inspect-only or foreign Writer, changed root identity, or a closed
capacity scope is refused. More than one descriptor is rejected before
`admit_write`, provider invocation or file creation.

The disposable Asset Writer borrows the original `temporary_containment` and
`promoted_assets` root objects. One Writer is pinned to one exact Worker/storage
integration and may be reused for later single-image requests after each
previous handoff settles; another Writer or integration cannot take over its
retained contents. Its close does not close those app-owned root handles. The
existing 19D reservation must cover 32 MiB and one staging entry. The handoff
consumes that exact reservation and calls the existing
`admit_write_for_characterization()` once; it creates no second operation or
reservation. The resulting opaque write token remains inside the designated
Writer. Its Profile A borrowed mode rejects direct legacy create and
batch-commit entry points.

The Writer uses the existing offline stream implementation and bounded
descriptor lookup. It validates the declared and actual body lengths against
the image, request and storage limits, decodes image data, hashes and rereads
stored bytes, checks native identity/owner-only ACL, and requires exactly one
new staging file in the ledger's inventory delta. Immediately before CREATE_NEW,
capacity/root and Project-reference readiness are reobserved outside host
locks; the exact write token and held scope-writer lease are checked at the
short in-memory commit gate. Native readiness, inventory scans, stream and
image observations happen outside Host, Job, Inbox and lifecycle locks.
Original-host checks fence the one-shot handoff before admission, at CREATE_NEW
authorization, during external stream callbacks, and before the count-only
result is published.

On success, the host returns only a bounded
`protected_image_staged_non_authoritative` count observation. The exact
`VerifiedProtectedImageObservation` and write token remain private to the
original integration and Writer. This is local byte/image evidence plus
capacity accounting only; it is not a `LocalOutputReceipt`, accepted batch,
promotion receipt, Candidate admission or Project-save authorization. It does
not prove authorship or enable any capability flag.

Before a CREATE_NEW call is possible, the exact unused reservation or admitted
write is canceled only when the native/capacity owner can prove cancellation.
If CREATE_NEW may have been called, a failed stream, Writer close, host
revocation, ACL/identity/content drift, or uncertain accounting retains the
partial file/handle evidence and capacity. No automatic retry, overwrite,
deletion or cleanup occurs. A successful pre-create cancellation remains a
terminal cancellation even when an earlier host callback began the final
authorization boundary.

Tests characterize injected stream bytes against disposable Windows-native
roots. They do not exercise a live ComfyUI endpoint or production Worker.
Multi-image atomic staging remains the next bounded storage step; after that,
separate gates remain for production root provisioning, cross-process capacity
policy, live HTTP interoperability, production Worker/original-host lifecycle,
explicit Human Start/UI activation, durable Journal ordering and restart
inspection, protected promotion, Candidate publication and Project save,
Recovery, retention and Discard. Execution, protected storage, promotion,
Candidate publication and Project-save flags remain false; `authorship` stays
unverified.

## C2B-8D-19F-B Profile A accepted-batch Promotion capacity preflight

The scope-reduced 19F-B boundary
`ProjectAgentSessionRuntime.preflight_generation_worker_accepted_output_promotion_for_characterization()`
starts from the exact original-Host Acceptance observation, not the legacy
Promotion owner. It revalidates the privately retained accepted batch, its
issuing Acceptance/protected-assets owners, successful Worker history and
remote receipt, frozen request, ordered verified staging observations,
completed staging ledger delta, four-root capacity owner, scope-writer lease,
read-only selected-Project reference and current original Host/Claim/Project
binding. This uses a settled-Acceptance freshness gate rather than treating
the older in-progress Acceptance callback as proof of current Promotion
eligibility.

Native source verification and readiness checks run outside Host, Job, Inbox,
lifecycle and protected-owner locks. The shared capacity ledger then reserves
only the accepted source byte total and descriptor count for `promoted_assets`;
the completed `temporary_containment` source remains observed and is not
double-reserved. A final current-Host gate binds the exact reservation to a
private one-shot attempt and returns only a count-only immutable
`GenerationWorkerProtectedPromotionPreflightObservation`. It does not issue a
writer capability or CREATE_NEW authority, copy image bytes, publish a
Promotion receipt, advance executor output readiness, or create Candidate or
Project-save authority. The exact observation may cancel its still-reserved
destination estimate before any write is authorized. No source evidence is
deleted or automatically cleaned up.

The preflight is a capacity decision, not a complete Promotion bridge. Under
the current 16-entry shared temporary/promoted ceiling, a 16-image staging
batch occupies all entries, so a second 16-entry destination reservation is
refused before destination creation. Retaining the source while copying also
means byte capacity must cover both observed source and reserved destination.
The next bounded Promotion step must define the retained-source/destination
capacity policy and add a narrow Host-issued Profile A writer path that uses
this exact reservation, CREATE_NEW owner-only files, per-image native/content
verification, one aggregate ledger/receipt commit and a final publication
gate serialized with close/invalidation. Partial or uncertain copies must be
retained with no retry, overwrite, deletion or cleanup. The generic Profile A
Promotion factory remains fail-closed until that owner is implemented and
reviewed. Every production capability flag remains false and
`authorship=unverified`.
