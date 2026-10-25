# Agent Generation original-host Candidate publication

Phase 4-C2B-6 characterizes the integration after
[contained verified local outputs](agent-generation-output-containment.md).
`execution_available` remains false. The new owners have no production call
site, Start UI, MCP execution tool, network transport, worker, download or
automatic generation. Tests use disposable fake Projects, temporary directories
and temporary JSON only. This is not authorization to publish Candidates or
save an active user Project.

## Ownership and original-host evidence

The original runtime privately retains `GenerationPublicationOrigin`, bound to
the exact C2B-3 accepted `ExecutionEnvelope` object. That separate host carrier
holds the original Project object, exact save path, detached source snapshot and
finalized review bytes. The worker envelope and handoff/take results contain none
of those host values. Snapshot copying happens before handoff owner locks; the original source
is checked again when the offer and custody consumption commit. Public jobs and
MCP projections do not expose these objects, paths or private review bytes.

`GenerationCandidatePublication.create_for_characterization` requires both
characterization-only registry/inbox owners and the exact accepted envelope.
One publisher is pinned in the original runtime. Its durable directory must be
explicitly approved by the host and exactly match the absolute
`output_directory` frozen in that envelope's original host configuration.
Neither the active UI path at publication time nor a remote filename selects a
destination. An invalid allocation stays pinned; there is no automatic retry or
silent replacement of an uncertain owner.

The publication guard uses the existing publication gate, route operation lock,
job lock and inbox lock ordering. It checks session/process incarnation, exact
Project object/path, non-restorable activation and target epoch, current pairing
generation, accepted envelope identity, job/claim/manifest, ordered
request/Illustration/run/workflow, remote/local receipt correlation and the
matching local count event. The store additionally requires the exact original
remote/local objects in its private index, local file identity and SHA-256.
Another object carrying equal IDs or paths does not acquire receipt custody.

The complete Project source snapshot checks prompts, negative prompts, Modules,
Scene ordering, source image, lineage and other Project state. Each successful
publication updates only the expected Candidate delta. Unexpected in-place
mutation blocks the next commit; switching away and back never restores the
original activation. The full-app host remains the serialized Project writer,
as in Scene Module Swap. Arbitrary unrelated threads mutating Project objects
are not an additional supported writer contract.

## Durable promotion

C2B-8D-1's separate [disposable Windows protected asset owner](agent-generation-protected-storage.md#c2b-8d-1-disposable-protected-staging-and-promoted-assets)
is extended by the offline [C2B-8D-8 protected promotion characterization](agent-generation-protected-storage.md#c2b-8d-8-protected-durable-promotion).
That owner can copy one exact accepted staging batch into its existing native
protected `promoted_assets` root and retain a distinct immutable
`VerifiedProtectedPromotionReceipt`. It does not return `PromotedImage`, create
`DurableGenerationAssets` custody, or confer Candidate publication authority.
The [C2B-8D-10 admission observation](agent-generation-protected-storage.md#c2b-8d-10-original-host-candidate-publication-admission-observation)
rechecks exact promotion custody and its accepted host `outputs_ready` event,
then issues private immutable eligibility evidence. It still does not enter
Candidate publication or Project save. The existing approved-parent legacy
publisher below retains its strict receipt validation and behavior.

`core.generation_output_promotion.DurableGenerationAssets` owns filesystem work.
It creates an exclusive UUID directory under the explicitly approved existing
parent. Parent/root identities and canonical paths are frozen and checked.
Every ancestor is checked with `lstat`, including Windows reparse attributes.
Every destination is an application UUID plus the independently verified format
extension. Remote names and subfolders are lookup metadata only.

Source and destination handles are checked against their original device/inode
identities. New files use `O_EXCL` and `O_NOFOLLOW` where supported; no existing
file is overwritten. Copying is bounded by the verified image byte count;
files are flushed, fsynced and hashed again. The complete batch and original
contained receipt are revalidated before Candidate commit. A Candidate never
references the C2B-5 temporary staging file.

Promotion, hash checks, cloning, factory metadata preparation and JSON
serialization run outside owner locks. Candidate ingestion receives the already
verified path set, so it does not perform filesystem existence checks while
holding the publication gate. Job/inbox locks are released before the appender.
The publication gate and route operation lock serialize the final host mutation
with supported target/pairing/close transitions.

As with C2B-5, integrity checks are not a filesystem ACL sandbox against an
external process able to rewrite the approved directory. The host owns the
directory and file writers. A protected durable-root/ACL policy and hostile
filesystem concurrency review remain prerequisites to production activation.

Complete staging bytes, partial or complete promoted files, identities, exact
receipts and attempt outcomes remain retained on failure. There is no deletion,
overwrite, expiry cleanup, restart-time adoption, automatic redownload,
regeneration or publication replay. Process interruption can leave orphaned
assets; their existence alone does not prove Candidate registration or saving.

## Existing Candidate and history owners

Publication calls only `core.gallery_generation.ingest_gallery_generation_outputs`.
The host supplies the existing app `_make_generated_candidate_record` and
`_append_line_generated_candidates`; the latter remains the persistent and
session-cache synchronization owner. No new Gallery planner or alternate
Candidate writer is introduced. Tests compile those exact app functions without
running the application UI.

The app factory supplies its existing path, timestamp and record schema.
Generation fields then come from the finalized immutable review, never current
editable text or the legacy submission-time randomizer. `seed_mode` is
`frozen_execution`. The single seed and prompt fields are populated only when
unambiguous; otherwise they are `None`, with explicit availability flags. All
reviewed prompt bindings, seeds and parameters remain in generation provenance,
including job/manifest/request/run/workflow, remote/local receipts, descriptor,
output ordinal and the actual image SHA-256. Seed zero is preserved.

Request order comes from the existing frozen manifest; image order comes from
the validated receipt. Source image, prompts, Scene ordering and adoption state
are not changed. Before each request's first append, a detached original Project
snapshot enters the existing bounded Undo history. Zero observed registration
removes that history entry; a partial append retains it. The usual 20-entry
history cap remains. In-memory registration is not rolled back on save failure.

## One-shot attempts and truthful outcomes

| Stage | Linearization and result |
| --- | --- |
| Publication claim | A per-owner bounded marker pins the request before callback/I/O. An identical concurrent call sees `publication_in_progress`; another request sees `publication_busy`. |
| Promotion | The entire promoted batch is verified before it can reach ingestion. A partial/corrupt/unsafe attempt is `promotion_failed`, retained and never retried. |
| Candidate append | The existing appender mutates the original Illustration under the host gate. Actual persistent records, rather than the ingestion return count, determine registration evidence. |
| Registration receipt | While original authority and expected source still hold, the existing job registry settles the observed count once. Full success is `registered`; zero/partial results and exceptions are distinguished. |
| Uncertain appender | If it mutates before raising, the observed count is retained with `registration_uncertain`. A path/Project/source change during append also remains uncertain. No successful save can be claimed from that receipt. |
| JSON save claim | A separate one-shot `saving` marker is acquired only after registered request counts agree with this publisher's receipts and the job is settled. Concurrent calls see `saving`. |
| Persistence receipt | An exact successful callback produces `saved`; a definitive false result produces `save_failed`; exception, malformed result or lost authority produces `save_uncertain`. The callback evidence stays private on lost authority. |

Exact duplicate calls return historical receipts without promoting/appending or
saving again. Conflicting or copied receipt objects are refused. A historical
registration receipt is not an assertion that the asset is still intact; save
rehashes every promoted asset again. Registration, promotion and save states
remain independent. There is no automatic save retry, even after failure.

## Exact Project persistence

Tests supply the existing app `save_agent_scene_module_swap_project` as the
exact-object/path callback. Its authoritative write is
`core.io.save_project_to_json(original_project, original_path)`. The convenience
current-Project autosave helper is never used. Supplemental folder-layout and UI
feedback errors do not turn an already successful JSON write into failure.

The existing serializer intentionally normalizes Module/attribute/Candidate
state in place. Its exact normalizations are computed on a detached clone
outside locks, allowing the final source check to recognize those established
save effects while rejecting unrelated edits. The JSON writer still owns atomic
temporary-file replacement and relative Candidate paths. Reopen coverage verifies
that asset references and provenance survive that established persistence format.

The save callback runs outside all owner locks on the captured original object
and path. The serialized full-app host writer and the callback's exact-target
guard supply the supported persistence boundary. A switch/close/source change
observed on return cannot authorize a new target or confirm saving: the publisher
retains `save_uncertain`, including any known callback result. No implicit
rollback, save retry or changed-target convenience save occurs.

## Protected Candidate JSON persistence (C2B-8D-12)

Protected mode extends this same `GenerationCandidatePublication` owner; it
does not add a second Project writer or bypass the app's existing
`save_agent_scene_module_swap_project` callback. Save is available only after
every request is settled and each request that produced outputs has one exact
`registered` publication receipt whose count matches the job registry, accepted
event evidence, private admission observation, promotion receipt and complete
ordered descriptor set. The publisher retains the exact accepted
`remote_outputs_ready` / `outputs_ready` event pair for each successfully
settled request in bounded per-request custody. The job and inbox event logs
remain bounded diagnostic histories and may evict older entries; save permits
that eviction only when the publisher-held pair is still exact and every
surviving log entry agrees. Missing or changed private evidence, conflicting
surviving events, and any observed late output event block save. A single
sticky inbox marker preserves that late-output refusal even if the bounded late
event detail is later evicted. A failed zero-output request may remain settled
in a `partially_failed` job. Any missing, partial or uncertain registration
blocks save, including an earlier uncertain append followed by a later
successful request.

Immediately before the callback, the same original protected owners revalidate
accepted staging and promoted files, native identities, DACLs, verified bytes,
the pinned promoted root and approved destination. The save-specific host check
replaces the admission-time `awaiting_host_registration` predicate with the
exact completed Candidate registration and retained `remote_outputs_ready` /
`outputs_ready` event proof captured by the original publisher when that exact
registration commits. Every persisted Candidate path and provenance tuple is
matched back to its ordered descriptor, frozen prompt/seed data and exact
promotion/admission identity. The original Project object/path/source snapshot,
session/process, activation/epoch, pairing and single publisher owner remain
required.

Each issuing promotion owner supplies a separate one-shot save lease. Protected
asset, acceptance and promotion close/invalidation wait for an already claimed
save callback, while the callback itself runs without native, protected-owner,
admission, job or inbox locks. The publisher rechecks all protected files and
host evidence after the callback before recording the registry save outcome.
If close, invalidation, file/ACL drift or original-host loss overlaps a possible
write, the result is `save_uncertain`; known callback outcome is retained
privately. `True`, `False` and exception/malformed results map to `saved`,
`save_failed` and `save_uncertain` only when the post-write checks still permit
that classification. The attempt is one-shot; there is no retry, rollback,
Candidate replay, asset deletion or JSON deletion.

The callback retains the established serializer's in-place Module, attribute
and Candidate normalization. Before persistence, the writer applies that same
serialization normalization to a detached expected Project, then accepts only
the original expected state or that exact normalized state after the callback.
The app callback remains responsible for calling `core.io.save_project_to_json`
on the captured Project and path; no current-UI autosave or alternate serializer
is used.

This remains offline characterization only. It does not prove crash/power-loss
durability, cross-file atomicity, restart-time authority reconstruction,
cryptographic authorship, or protection from hostile same-user processes or
transient changes restored between bounded checks. Retained protected files and
JSON after uncertainty are not recovery authority. `execution_available=false`,
`protected_storage_available=false`, `promotion_available=false`, and
`authorship=unverified` remain in force; Candidate publication, Recovery, Start,
Journal, production transport, cleanup and MCP execution are not enabled.

## Remaining gates

The [C2B-7 integration and recovery audit](agent-generation-integration-recovery.md)
maps these characterized boundaries together, records crash/evidence limitations,
and proposes human recovery, inventory, retention and production prerequisites.

This slice characterizes one original-runtime publisher for one accepted
envelope. Explicit recovery/inventory, session restart reconstruction, owner
retirement/replacement, durable retention/cleanup and protected filesystem policy
remain separate work. Production activation also requires separately approved
real ComfyUI transport/redirect policy, worker lifecycle, Start UI, exact human
confirmation and operational validation. Scene Module Swap custody and ACK
continue to belong to their existing owners and are unchanged by publication.
No execution or publication capability is exposed through MCP.

## Protected Candidate admission is not Candidate publication

C2B-8D-10 adds an offline, original-host observation for the exact protected
promotion receipt and accepted `outputs_ready` event. Its source snapshot,
Project object/path, session/process, activation/epoch/pairing, request, manifest,
job/claim and ordered descriptors are rechecked before the observation is
issued. The promotion owner performs native file/ACL/content verification
outside host mutation gates; the final in-memory commit is serialized against
protected-owner revocation, runtime close, target/pairing changes and job/inbox
event changes.

The observation is private evidence only. It does not satisfy the legacy
`LocalOutputReceipt` and `PromotedImage` checks in
`GenerationCandidatePublication`, does not create another Candidate writer,
and does not append, settle publication counts, change Undo history or save.
The C2B-8D-11 protected writer path is a narrowly audited extension of this
same single Candidate writer. It accepts only the exact admission observation
retained by its issuing owner, preserves the legacy receipt path unchanged, and
does not manufacture `LocalOutputReceipt`, `PromotedImage`, or
`DurableGenerationAssets` custody. Protected `promoted_assets` must be a strict
descendant of the exact frozen `output_directory` approved by the original
host. No arbitrary destination or path fallback is accepted. Registration and
Project persistence remain separate: this characterization performs no save.
If an appender leaves an exact, observed subset before raising, that request
stays `registration_uncertain` and is never retried. The admission comparison
baseline advances only when the full original Project equals the prior
expected state plus that observed Candidate subset, allowing a later distinct
request without resolving the earlier uncertainty. Save remains blocked.
`authorship=unverified` and all production execution/storage/promotion gates
remain false. See the [protected Candidate writer integration](agent-generation-protected-storage.md#c2b-8d-11-protected-candidate-writer-integration)
for its native custody and approved destination contract.

## C2B-8D-19G-A Profile A protected Candidate admission preflight

The current Profile A original-Host path now has a one-shot, read-only
preflight after its 19F-E protected Promotion publication. It binds the exact
count observation and privately retained Promotion receipt to the live Host
lifecycle, `GenerationPublicationOrigin` and its unchanged source snapshot,
Project object/path and read-only Project JSON reference, route/process/session,
pairing, Job Claim, frozen request, successful remote receipt, descriptor
order, protected Acceptance, Promotion and completed staging/destination
capacity records. Native source/promoted bytes are decoded and hashed again;
the full root inventory and ACL/identity evidence are rechecked outside the
Host/Job/Inbox commit locks.

The returned `GenerationWorkerProtectedCandidateAdmissionPreflightObservation`
is only count evidence and reports `candidate_eligibility="not_established"`.
The 19G-A preflight remains separate from event custody: it neither requires
nor consumes the genuine accepted `remote_outputs_ready` / `outputs_ready`
pair, and it does not call `GenerationProtectedCandidateAdmission`, synthesize
events or legacy receipts, invoke `GenerationCandidatePublication`, append
Candidates, settle registration counts, mutate Undo history or save Project
JSON. The 19G-E transition can now supply the source-bound event pair; only the
separate 19G-F bridge below passes that exact evidence to the existing
admission owner. The existing single Candidate writer and its legacy
validation remain unchanged.

Preflight is one-shot. A copied or replayed Promotion observation is rejected;
stale Project snapshot, Host, Claim, pairing, native file, ACL, inventory or
ledger evidence withholds success and retains only the downstream preflight
uncertainty. The already-published Promotion and completed capacity records
remain intact. A valid 19G-A result may be observed before or after 19G-F; the
two one-shot observations have separate attempt custody. This characterization
is offline-only: all production capability flags remain false, no Candidate or
Project state is changed, and `authorship=unverified`.

## C2B-8D-19G-B records only the original-Host pre-send event

The new prospective Profile A seam accepts `submission_started` through the
existing Job Registry and Inbox before the exact Worker operation is
registered. The original Worker integration privately records that exact
accepted event as Profile A sourced. The read-only event-chain observation
distinguishes it from generic/fake Executor events, and never upgrades an old
event or 19G-A promotion-count observation by matching values. If capacity is
invalidated between Job/Inbox acceptance and Worker registration, the accepted
event is retained but is not source-bound; the Worker lease is withheld and
the one-shot integration is revoked.

At the 19G-B boundary, later `submitted`, `remote_outputs_ready`, and
`outputs_ready` events were not yet source-bound, so that step alone did not
satisfy protected Candidate Admission's ordered event requirements. The later
19G-C/D/E sections now characterize those subsequent transitions from their
original-Host Worker/result/Promotion boundaries. 19G-B still never calls
Candidate Admission or the Candidate writer; `candidate_eligibility` remains
`not_established`. Its event indicates a pre-send transition only, not an
actual HTTP send or remote acceptance. Existing admission and the single
Candidate writer remain separate and unchanged. All production gates remain
false and `authorship=unverified`.

## C2B-8D-19G-C sources only accepted submission

The Profile A source chain now allows `submitted` only after the original Host
observes the exact Worker-issued accepted HTTP completion from an operation
whose `submission_started` was already accepted and privately source-bound.
The Job Registry and Inbox accept one exact count-zero event carrying the
validated Prompt ID and no output receipt; the same accepted event object is
then retained by the Profile A integration. Rejected-before-send, unknown,
forged or stale completion evidence cannot produce it, and no send or event is
retried. An accepted-but-unbound event remains visible as accepted evidence but
cannot become Profile A source provenance.

This advances the request only to `awaiting_result` with `registered=0`. It does
not satisfy Candidate Admission: no `remote_outputs_ready`, protected
`outputs_ready`, promotion receipt, Candidate mutation, Undo publication or
Project save is produced. Candidate eligibility remains
`not_established`, and production gates remain disabled. The next bounded
source transition is ready-history plus exact remote-output evidence.

## C2B-8D-19G-D verified remote History is not Candidate readiness

The original Host now accepts one source-bound `remote_outputs_ready` event
after the exact 19G-B/C event pair, Worker-issued ready History, accepted prompt
identity, and successful `validate_remote_outputs` receipt with complete
one-to-sixteen ordered descriptors. The Job moves to `awaiting_download` and
records the remote descriptor count while `registered=0`. The same exact
`ExecutorEvent` must remain accepted by both Job Registry and Inbox and bound
by the issuing Profile A integration; copied or accepted-but-unbound events do
not count as source provenance.

This event only proves that remote metadata passed the existing validator. Its
opaque `OutputReceipt` is correlation evidence, not local protected custody or
Candidate authority. It does not satisfy the later protected `outputs_ready`
event expected by Candidate Admission, because no images have been contained
and promoted. The source chain therefore requires `outputs_ready` next and
keeps `candidate_eligibility="not_established"`. Candidate append, registration
settlement, Undo publication and Project save remain separate host-owned
transitions; all production capability flags remain false and
`authorship=unverified`.

## C2B-8D-19G-E protected Promotion event precedes Candidate admission

The original Host now emits and retains one exact `outputs_ready` event only
after the already-published protected Promotion batch is revalidated through
its issuing owners. Together with the exact source-bound
`remote_outputs_ready` event from 19G-D, this supplies the event-custody
portion expected by the existing Candidate admission owner. The output event
contains only the verified count and an opaque Promotion correlation ID; the
Promotion receipt itself stays private and owner-issued.

This bridge ends at Job state `awaiting_host_registration` with
`registered=0`. Its public observation reports
`candidate_eligibility="not_established"`; it does not call Candidate
Admission, append a Candidate, alter Undo, or save Project JSON. Admission and
publication remain separate host-owned transitions, and all production gates
remain false with `authorship=unverified`. The event pair is usable only while
the exact accepted event objects remain current in both Job Registry and Inbox;
eviction, disagreement, stale host state or uncertain acknowledgment fails
closed and cannot be replayed.

## C2B-8D-19G-F genuine protected Candidate Admission evidence bridge

The original Host accepts only the exact 19G-E count-only `outputs_ready`
observation retained by its Profile A integration. Before invoking the
existing `GenerationProtectedCandidateAdmission`, the bridge verifies that
`submission_started → submitted → remote_outputs_ready → outputs_ready` still
forms the same source-bound Job/Inbox chain, including identity of each
original Inbox event and authority-list entry. It also requires the exact
active envelope, Claim, manifest, process/session, activation/epoch, pairing,
request, original Project object/path/source snapshot, read-only Project JSON
reference, ordered one-to-sixteen descriptors and Promotion rows,
`awaiting_host_registration`, matching output counts and `registered=0`. Late,
copied, stale, conflicting or uncertain evidence fails closed.

The bridge reuses the existing protected Admission owner and passes it only the
original private Promotion owner, receipt, successful remote receipt and
request index. That owner revalidates protected native Promotion custody. Its
`ProtectedCandidateAdmissionResult` and private observation remain retained by
the original Host/integration; the bridge returns only a count-only
`GenerationWorkerProtectedCandidateAdmissionObservation` with
`candidate_eligibility="evidence_observed"`. The result means that existing
admission evidence was observed for a possible separately reviewed later
writer step. It is not permission to append a Candidate, alter Job registration,
publish Gallery/Undo state or save the Project. The 19G-A count preflight stays
independent and can be invoked before or after 19G-F without consuming its
attempt.

Admission is one-shot. Duplicate calls do not return the private observation;
close, invalidation, event replacement, native drift or final Host mismatch
withhold public success and retain uncertain evidence. The bridge creates no
new event, capacity reservation, ledger operation, image write or legacy
receipt. Candidate publication and Project JSON save remain separate host
owners. This remains offline characterization: all production capability
flags remain false and `authorship=unverified`.

## C2B-8D-19G-G Profile A in-memory Candidate publisher

19G-G composes the exact 19G-F Candidate-admission observation with this
existing Gallery Candidate publisher. The app-facing characterization entry
point accepts only the count-only Host locator; it binds the real app Candidate
factory, line appender and save callback internally. The publisher reuses the
existing `GenerationCandidatePublication` owner and original Admission commit
guard. It does not create a parallel Candidate writer or adapt protected
evidence into legacy `LocalOutputReceipt`, `ContainedOutputStore`,
`PromotedImage` or `DurableGenerationAssets` custody.

The older protected-publication cases in
`tests/test_agent_generation_protected_candidate_publication.py` retain their
legacy/fake-adapter setup and do not independently prove the source-bound
Profile A chain. The genuine 19G-B/C/D/E/F-to-19G-G composition is characterized
by the Windows-native disposable cases in
`tests/test_agent_generation_original_host_worker_storage.py`.

Profile A authorizes paths through its exact four-root capacity owner, held
scope-writer lease, promoted-assets root identity, protected-assets owner,
Project JSON reference, active Host and retained Promotion/admission evidence.
The frozen Comfy `output_directory` remains a distinct configuration value;
its tree must be disjoint from the app-private Profile A scope. This is a
separate Profile A authorization path and does not relax the existing strict
approved-parent check for legacy/protected publication.

Native Promotion, ACL, byte, capacity and root observations complete before
the short Candidate commit. The existing Promotion/Admission commit boundary
and a new capacity-owner publication lease order Candidate appending against
Host, protected-owner and capacity close/invalidation. If capacity revocation
wins first, no Candidate is appended; if the in-memory append already entered
its lease, close waits for that bounded commit to settle. Uncertain or partial
registration remains one-shot and retained; copied or late locators cannot
replay it. Success updates only in-memory Gallery Candidates, the existing
Undo history and Job registered count. The Project JSON save callback is not
invoked, and the file remains unchanged. Save remains a separate future gate.

Disposable native Windows compositions cover one, two and sixteen images,
exact provenance and ordering, copied-locator refusal, unchanged Project JSON,
and lifecycle/capacity close races. This does not activate production
execution or Candidate publication: `execution_available=false`,
`protected_storage_available=false`, `promotion_available=false`,
`candidate_publication_allowed=false`, `project_save_allowed=false`, and
`authorship=unverified` remain in force.
