# Agent Generation integration, recovery and retention (Phase 4-C2B-7)

This is the production-readiness audit of C2B-1 through C2B-6 at main
`3956bb29ec9e1d82fceedd482d4e7c307d3f4438` (PR #153 merge). It records
implemented characterization guarantees and a proposed recovery design.
**Production execution remains unavailable.** There is no production Start,
worker, ComfyUI transport, production restart journal, recovery publication or cleanup
implementation in this slice. Passing injected-fake tests does not establish a
working production ComfyUI integration or crash durability.

[C2B-8A ownership journal foundation](agent-generation-ownership-journal.md)
now characterizes bounded offline journaling, inspect-only restart inventory and
explicit selected saved-Project Candidate reconciliation. It has no production
call site and does not restore claims, publish, save, retry or clean up. The audit
below records C2B-1..7 runtime behavior; its memory-only boundaries remain unchanged.

[C2B-8B Human Recovery Review foundation](agent-generation-human-recovery.md)
adds private immutable inspection cases, redacted bounded projections, scoped
non-executable review intentions and read-only retention assessment. It has no
production Recovery UI or call site. Fresh recovery/cleanup authorization,
authenticated journal ownership and publication/save authority remain gates.

## Evidence scope and current owners

The surrounding contracts are authoritative:

- [C2B-1 finalized executable manifest](agent-generation-executable-manifest.md)
- [C2B-2 executable review and confirmation](agent-generation-executable-review-ui.md)
- [C2B-3 one-shot inbox/handoff](agent-generation-executor-handoff.md)
- [C2B-4 frozen submission and remote receipts](agent-generation-comfy-executor-adapter.md)
- [C2B-5 contained local outputs](agent-generation-output-containment.md)
- [C2B-6 Candidate publication and JSON persistence](agent-generation-candidate-publication.md)
- [Scene Module Swap approval custody](agent-scene-module-swap-approval-custody.md)

The implemented guarantees below are scoped to explicit characterization owners,
disposable Projects/files and injected synchronous callbacks. The supported
host writer is a serialized full-app run plus its publication gate. Unrelated
background Project writers are not supported. Filesystem checks assume the host
controls the roots and writers; they detect replacement and corruption but do
not establish a hostile-process ACL sandbox. Callback classifications such as
definite rejection and save success are trusted seam inputs; a real transport
must earn those classifications independently.

### End-to-end transition and ownership map

`ui/` and `core/` paths below identify implementation owners. All execution,
containment and publication operations remain characterization-only. Inspection
of safe review projections and human confirmation are implemented host UI.

| Transition | Authoritative owner and required evidence | Commit/linearization point | Retry permission and invalidation |
| --- | --- | --- | --- |
| Pending proposal -> finalized review | `core/generation_executable_manifest.py`, `ui/agent_generation_executable_review.py`; explicit Scene, complete target/run coverage, source/config/workflow evidence, supported sampler-to-output and conditioning paths | Complete immutable manifest/projection; each request has canonical workflow bytes/digest and finalized seed slots | Inspection preserves seeds. Explicit Refresh discards prior review/confirmation and creates new identity. One unsupported target withholds the entire manifest. |
| Review -> human acknowledgment | `ui/agent_generation_executable_confirmation.py`; exact session-held carrier, fresh full manifest/projection and original proposal | Confirmation publication under runtime gate -> route fence -> mailbox -> custodian | Duplicate callback records one ACK. Activation/epoch/pairing/source/config drift refuses confirmation; transient reads may recover only after fresh inspection. ACK does not start work. |
| Confirmation + new human action -> reserved inbox | `ui/agent_generation_executor_handoff.py`, `ui/agent_generation_executor_inbox.py`; private post-confirmation action and freshly reconstructed review | Bounded reservation; no claim or external authority yet | Capacity/expiry before claim releases reservation and retains review custody; re-inspect before another explicit action. Production returns unavailable. |
| Reservation -> claimed/offered, consumed proposal | Handoff, `ui/agent_generation_job.py`; exact host/process/session/activation/epoch/pairing, manifest and ordered requests | Under gate -> route -> mailbox -> Generation custodian -> job -> inbox, job claim and committed envelope consume exact proposal/ACK; observable when locks release | One-shot claim. No restoration of consumed proposal. Unknown post-claim outcome pins ownership. The claim is memory-only, not durable. |
| Offer -> one worker take / handoff response | Inbox; typed exact job/claim/manifest receipt and actual observed take | Inbox moves to accepted under job-before-inbox locks; fake callback runs unlocked | No second take. Normal completed/partially-failed/failed progress before callback return preserves acceptance. Unavailable/unknown/cancelled/expired/invalidated ownership does not. |
| Accepted request -> submission started/accepted | `ui/agent_generation_comfy_executor.py`, `core/comfy_prompt_request.py`; exact manifest member, workflow bytes, finalized seeds, frozen endpoint | Count event precedes transport; adapter phase pins one attempt before callback; canonical unique prompt ID records acceptance | Sequential requests; no resubmission. Only trusted rejection before send is definite failure. Missing/invalid response becomes submission outcome unknown; later requests remain unsent. |
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

Records are untrusted on restart until strict bounded schema, root ownership,
sequence/digest and integrity checks succeed. A future protected installation
key may authenticate records (no key in journal; rotation/loss means inspect-only),
but that policy needs a reviewed supported key store and explicit threat model.
Reject unknown schema, absolute/escaping references, fabricated/rolled-back or
conflicting journal revisions and stale owner incarnations. Even an authenticated
journal proves retained observations, not current publication authorization.
The same-user process with write access to all roots is outside the current
integrity-only guarantee; do not claim cryptographic or ACL protection without
implementing and testing it.

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

## Audit findings and characterization evidence

No concrete P0/P1 safety defect was identified in the inspected supported
characterization paths. That does not clear production activation. The following
classification is scoped to the owners and tests cited, not a broad code audit.

| Classification | Finding / exact evidence |
| --- | --- |
| Already covered | Frozen output-linked prompt/seed identity: `tests/test_agent_generation_executable_manifest.py::test_disconnected_standard_sampler_cannot_mask_custom_output_sampler`, `test_preserve_zero_and_u64_boundary_and_no_second_randomization`. |
| Already covered | Exact review/ACK and one-shot claim/take/normal terminal acceptance: `tests/test_agent_generation_executable_review_ui.py::test_complete_manifest_and_display_comparison_refuses_tampering`; `tests/test_agent_generation_executor_handoff.py::test_double_human_claim_and_double_worker_acceptance_are_one_shot`, `test_normal_terminal_progress_before_handoff_preserves_observed_acceptance`. |
| Already covered | Unknown submission/no retry, accepted timeout: `tests/test_agent_generation_comfy_executor.py::test_ambiguous_submission_never_retries_or_starts_next_request`, `test_execution_timeout_progress_and_correlated_later_result_without_resubmission`. |
| Already covered | Original-history success, atomic batches and invalidation: `tests/test_comfy_output_containment.py::test_forged_statusless_success_rejected_by_standalone_containment_before_io`, `test_partial_batch_is_quarantined_atomic_and_retains_complete_evidence`, `test_pairing_release_between_post_io_gate_and_event_delivery_quarantines`. |
| Already covered | Original-host publication/partial appender/save uncertainty/IO locks: `tests/test_agent_generation_candidate_publication.py::test_original_host_and_source_drift_at_boundaries_never_appends`, `test_appender_exception_reports_observed_partial_registration_without_replay`, `test_exact_save_outcomes_concurrency_and_no_retry`, `test_io_callbacks_and_hashing_are_outside_owner_locks`. |
| Already covered | Composed fake path/reopen/provenance/no replay, promoted-before-append failure, partial insertion with later distinct requests/save block, definitive/uncertain save, post-promotion event race, incomplete/quarantined refusal and lost-memory refusal: `tests/test_agent_generation_integration_recovery_audit.py`. No actual crash journal/recovery is simulated. |
| Already covered | Independent Module Swap custody/ACK: `tests/test_agent_generation_candidate_publication.py::test_publication_preserves_pending_scene_swap_and_its_ack`; actual Apply/save failure boundaries: `tests/test_agent_scene_module_swap_apply_lifecycle.py::test_success_revalidates_applies_one_scene_and_publishes_in_order`, `test_autosave_failure_keeps_project_and_history_and_consumes_approval`. |
| Production blocker | Claims/receipt indexes/attempts are memory-only; no crash-consistent submission intent, restart inventory or saved-JSON reconciliation. Existing paths/hashes cannot recover exact authority. |
| Production blocker | No production human recovery/retention owner or safe cleanup authorization; global storage quota/reservation and protected Windows roots/ACLs not established. |
| Production blocker | No trusted real submission/result/download transport with deadlines, origin/redirect/authentication policy and truthful unknown classifications; no bounded production worker/host event delivery. |
| Production blocker | No production exact Human Start action, host publication wiring or reviewed retirement/replacement lifecycle; one pinned publisher currently supports one envelope/runtime. |
| Operational improvement | Later richer progress, reminders and visual inventory grouping can follow correctness gates. They must keep counts/privacy/retention budgets and never imply completion or cancellation from elapsed time. |

## Next bounded PR sequence and production go/no-go

1. **Private inventory/ownership journal foundation:** implement bounded schema,
   protected journal owner and crash ordering; test interruption after each intent/
   commit, malformed/stale record refusal and read-only saved-JSON reconciliation.
   Include the policy needed to protect journal authenticity; no execution/adoption.
2. **Human recovery/retention controls:** inventory/verify/reconcile/review
   decisions, fresh recovery custody and idempotent association boundaries,
   explicit cleanup controls/quota reservation. Include publisher/inbox retirement
   and replacement for distinct work; uncertain outcomes remain fenced.
3. **Protected filesystem and real transport policy:** approved staging/durable
   ACLs, filesystem durability threat model, exact endpoint origin, bounded `/prompt`,
   history and `/view` with redirect/auth/deadline policy. Initially offline/fake
   contract tests; journal intent must precede any later external send.
4. **Production worker integration:** bounded sequential worker using frozen
   envelope, original-host event delivery, explicit loss/shutdown behavior and
   independent publication/save owner. No enabled Start until prior gates hold.
5. **Exact authorized Human Start:** a new explicit human action after fresh full
   review/confirmation; one-shot durable intent/claim, host gates and visible
   unknown/unsaved/recovery states. MCP remains Preview/review-request only.
6. **Operational end-to-end validation:** separately human-authorized real ComfyUI
   and disposable Project exercise, operational restart/recovery/failure injections,
   storage-capacity behavior and proof of exact saved Candidate provenance.

The sequence may be split further; protected journal/root policy is a prerequisite
to useful durable records even if transport is reviewed later. Before **any**
production execution: durable unknown-submission evidence, inventory/reconciliation,
human recovery/retention and quota ownership, protected roots, truthful bounded real
transport, worker lifecycle, exact new Human Start and original-host publication/
persistence must all pass separate review. Operational E2E needs its own explicit
authorization; fake success here does not supply it. `execution_available` must
remain false until those gates are implemented and authorized. No automatic
resubmission, recovery association, cleanup or MCP execution is an alternative
to those gates.
