# Agent Generation integration, recovery and retention (Phase 4-C2B-8D)

This audit was established against the protected Generation path through PR #174,
merge commit `064212a9e78da8456cb5eac4c7b82e224c77bb08`. Its later C2B-8D-14
and C2B-8D-15A updates are recorded below. C2B-8D-1 through C2B-8D-12 collectively define and test, in separate and
partially composed characterization slices, a protected route from a frozen
request through the existing Candidate writer and Project JSON save. C2B-8D-14
connects the one-request offline Journal intent to the existing executor's
actual pre-send decision. **Production execution remains unavailable.** The
HTTP owners and Windows-protected path are exercised offline with injected
transports and disposable state; no test in this path proves a live ComfyUI
run, crash durability, or production worker integration.

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
[C2B-8D-14 executor Journal boundary](agent-generation-comfy-executor-adapter.md#c2b-8d-14-offline-journal-intent-before-send-characterization)
characterizes intent-before-send for one exact request through the existing
executor with an injected callback; it is not production durable-intent wiring.
Worker lifecycle, original-host production delivery and production authorization
remain separate gates. Profile A, `authorship=unverified`,
`execution_available=false`, `protected_storage_available=false` and
`promotion_available=false` are unchanged.

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
| Accepted handoff -> `POST /prompt` and prompt identity | Handoff/inbox/job owners, `ui/agent_generation_comfy_executor.py`, `core/comfy_prompt_request.py`, `core/comfy_http_submission.py`; exact frozen request and returned prompt UUID | Handoff/executor fake-provider tests plus isolated injected/monkeypatched HTTP wire tests; one attempt, sequential order, possible-send uncertainty, no automatic retry | HTTP submission is not the executor's production default and no live ComfyUI request is made. No worker registration, durable intent-before-send, production deadline policy, or original-host event loop. |
| Accepted prompt -> history observation | `core/comfy_http_history.py`, `core/comfy_remote_output_receipts.py`, executor result gate; exact accepted UUID and frozen origin | Bounded pending/ready/unknown transport contract, strict metadata parsing and correlation tests; explicit later read does not resubmit | No polling scheduler, live history interoperability evidence, or durable restart association. Missing/timeout history is unknown, never proof of execution failure. |
| Successful history -> `/view` stream -> protected staging | `core/comfy_http_view.py`, `core/comfy_output_containment.py`, `core/generation_windows_protected_assets.py`; exact remote descriptor, prompt/request binding, original-host freshness | Injected HTTP stream composed with real Windows disposable roots/files, incremental stream, native identity/DACL, decode/size/hash and retention checks | No production transport registration. No remote cancellation or cleanup, and no claim of constant-memory decode or hard end-to-end deadline. |
| Complete protected staging batch -> acceptance -> promotion | `WindowsProtectedAssetsCharacterization`, protected acceptance owner, `ProtectedDurablePromotionCharacterization`; exact issued receipts/owners, envelope/request/remote identity, descriptor order, host freshness | Windows-native disposable tests verify batch completeness, source/destination identity/ACL/bytes, one-shot promotion, capacity and close/invalidation commit races | Only characterization opt-in on approved disposable scopes. No production root provisioning or long-lived production handle lifecycle. |
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
| Accepted request -> submission started/accepted | `ui/agent_generation_comfy_executor.py`, optional `ui/agent_generation_executor_journal.py`, `core/comfy_prompt_request.py`; exact manifest member, workflow bytes, finalized seeds, frozen endpoint | Without the optional owner, existing behavior remains unchanged. With it, the host first accepts `submission_started`, then the exact revision-1 Journal intent is acknowledged and host/request state is rechecked before the one-shot injected callback. A valid unique prompt ID may be separately observed in revision 2. | The Journal seam is offline-only and refuses multi-request manifests. No acknowledged intent means zero callback invocations. Only trusted rejection before send is definite failure; missing/invalid response or lost result acknowledgment is unknown and never retried. |
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

## Readiness assessment (PR #174 audit, updated through C2B-8D-15A)

At the PR #174 audit baseline, the owners and focused tests showed no concrete
characterization defect requiring a runtime change. C2B-8D-14 now closes the
specific offline composition gap identified there: Journal intent is connected
to the executor's actual one-request pre-send decision. C2B-8D-15A now defines
and tests a separate bounded multi-request persistence contract, without
connecting it to the executor. This is still not a production clearance. The
following states distinguish implemented contracts, test composition and
missing authority.

| Area | Evidence-backed state | Remaining blocker or dependency | Risk if activated now |
| --- | --- | --- | --- |
| Exact original-host binding | Exact Project object/path, source snapshot, session/process, activation/epoch, pairing, job/claim/manifest, request and descriptor order are carried through protected admission, Candidate registration and save checks. | No production caller owns the complete route; only characterized callbacks and the serialized host-run assumption are present. | A stale/switching host or an unowned callback path could not be safely published. |
| One-shot submission/publication/save | C2B-8D-14 connects the existing executor's `submission_started` event to exact Journal intent acknowledgment before one injected send. C2B-8D-15A separately defines up to 100 request triplets (intent, submission outcome, original-host settlement), with accepted execution kept unsettled until a distinct host observation. Publication and JSON save remain one-shot. | The C2B-8D-14 executor seam still rejects multi-request manifests; C2B-15A is not connected to it. C2B-15B must wire the actual sequential lifecycle and terminal host settlement. Restart cannot prove whether an external request was sent without independently retained live-host latest-head evidence. Production HTTP/worker call sites remain absent. | Retrying after lost state could duplicate remote work. An accepted prompt alone cannot authorize a later send; any unacknowledged or unknown state must stop the sequence. |
| Native identity, DACL, bytes, promoted roots and Candidate paths | Disposable Windows-native tests pin protected roots/files, inspect owner-only ACLs and identities, reject path/reparse drift, verify streamed/copied bytes, and constrain protected Candidate paths to the frozen approved output root. | No production root provisioning, long-lived handle lifecycle, disk-wide quota or supported production path policy. Profile A excludes hostile same-user processes; bounded checks are not continuous isolation. | Production storage could outlive the current custody or exceed capacity; same-user tampering is outside the adopted guarantee. |
| Owner locks, close/invalidation and callbacks | Commit/terminal races are characterized; expensive native checks and external host callbacks run outside job/inbox locks, and leases fence final commits against close/invalidation. | Synchronous callback deadlines, DNS/header behavior, real event-loop scheduling and process shutdown remain unproven. | A blocked or lost production worker callback may leave an honestly unknown, pinned operation. |
| Partial registration, uncertainty and Undo | The existing Gallery writer records observed Candidate deltas and existing Undo history. A partial appender result remains `registration_uncertain`, is not replayed, and blocks final JSON save; later distinct requests may continue only after exact observed-state comparison. | No production path reaches this writer from protected receipts; no automatic rollback is authorized. | Partial Project mutation requires human inspection; it cannot be treated as all-or-nothing success. |
| Bounded events and retained evidence | Job/inbox logs are bounded diagnostic history. The publisher privately retains the exact settled event pair after successful registration; a sticky late-output marker survives detail eviction. PR #174 tests save after the first pair is evicted and refusal after late-output detail eviction. | Evidence is process-local. Its loss on restart does not reconstruct authority. | Treating log presence/absence alone as authority would permit false save or forget late output; current owner refuses when private proof is absent/conflicting. |
| Restart, Journal and Human Recovery | C2B-8A has native disposable Journal lifecycle and inspect-only reopen/inventory; C2B-8B has redacted, read-only recovery cases and non-executable intentions. Profile A accepts acknowledged live-writer latest-head observations only within the live host/process lifetime. | No production journal call site or restart checkpoint custody. After restart, without an independently retained host-observed tip, latest-head custody is unavailable; missing/conflicting evidence remains uncertain. No replay, Recovery association or Apply. | Old bytes or a digest-valid Journal prefix could be mistaken for current authority. |
| Retention and cleanup | Evidence is retained on uncertain/failed promotion, registration and save paths; bounded in-memory event logs are not disk-retention policy. No broad cleanup owner exists. | Global staging/quarantine/promoted capacity, reservation, inventory and explicit human discard/cleanup lifecycle remain unimplemented. | Disk exhaustion or unsafe deletion/adoption; elapsed time and expiry cannot authorize cleanup. |
| Transport, worker and real ComfyUI interoperability | `POST /prompt`, `GET /history/{prompt_id}` and streamed `GET /view` each have bounded offline contracts and injected/monkeypatched wire coverage. The executor consumes injected transport/result providers. C2B-8D-14 adds a one-request Journal seam; C2B-8D-15A characterizes the separate multi-request Journal persistence contract. | No real ComfyUI request, registered production HTTP wire, background worker, C2B-8D-15B Executor/Journal composition, production host-event delivery or measured deadline behavior. | Remote acceptance, history status, cancellation and output availability remain server/runtime assumptions. |
| UI activation and Human Start | Review/confirmation UI and a separate characterized Start boundary exist. Source search found no non-test call site for `capture_executor_human_start_for_characterization`, `handoff_generation_for_characterization`, or the executor’s characterization entry point. | No production UI activation, exact new Human Start dispatch, production worker registration or shutdown/replacement lifecycle. | Review confirmation could be confused with Start; an activation path could bypass the required fresh human action. |
| Candidate publication and Project JSON save | PR #174 composes the protected evidence path through the existing Candidate factory/appender, Undo snapshot and exact save callback; its disposable JSON is reopened and provenance checked. | Protected Candidate and save entry points are characterization-only. No production publication or save authority is enabled. | A successful offline fixture does not establish production Project integrity, user confirmation or durability. |
| Threat scope and authorship | Profile A is adopted for local single-user Pro. LLM/MCP inputs remain untrusted. | `authorship=unverified`; SHA-256 and ACL observations detect bounded corruption/drift but do not authenticate an author. Profile B is optional and unsupported, not a prerequisite for local Pro. | Same-user malicious processes, Administrator/SYSTEM and compromised host code are outside Profile A's guarantee; no digest should be misreported as a signature. |

Critical tests reviewed for this audit include the complete disposable protected
publication/save composition and its event-eviction cases in
`tests/test_agent_generation_protected_candidate_publication.py`, the repaired
native acceptance commit race
`tests/test_generation_windows_protected_stream.py::test_real_native_acceptance_commit_is_atomic_against_close_or_invalidation`,
the executor/admission/promotion/asset suites, the HTTP contract suites, and the
read-only Journal/Recovery suites. The C2B-8D-14 follow-up adds
`tests/test_agent_generation_executor_journal.py` because the earlier audit
identified that the Journal was not connected to the executor's real send
decision. These tests compose only disposable original-host state, the existing
executor and writer, and injected callbacks; they do not establish live HTTP,
crash durability or production authorization.

## Production go/no-go and next bounded milestones

**Decision: no-go for production Generation or executable Recovery.** The
characterization path is substantially composed, but every production capability
flag remains false. Profile B key/service infrastructure is not a prerequisite
for supported local Profile A use. It does not change the separate requirements
for explicit human Start, Recovery and Discard authorization; source/review
provenance; Project integrity; Candidate idempotence; or truthful save
uncertainty.

| Milestone | Dependency and risk addressed | Recommended bounded boundary |
| --- | --- | --- |
| 1. Multi-request Journal intent contract — implemented as C2B-8D-15A | C2B-8D-14 proves the actual executor boundary for one request. C2B-8D-15A adds a separate ≤100-request/300-revision schema with exact intent/outcome/settlement ordering and bounded storage preflight; v1 is unchanged. | No Executor integration exists yet. Reopened evidence remains inspect-only, and the host settlement issuer is a characterization seam. |
| 2. Disabled production worker/transport and original-host lifecycle — next boundary | Depends on the C2B-8D-15A contract plus explicit protected-root lifecycle, bounded worker shutdown/loss semantics and endpoint/auth/deadline policy. | C2B-8D-15B should connect the actual sequential Executor lifecycle to acknowledged Journal intent, outcome and separately validated terminal host settlement. Keep all gates false and Candidate publication/save owners unchanged. |
| 3. Real ComfyUI interoperability | Depends on reviewed transport/worker composition, supported version/endpoint behavior and disposable account/Project policy. | Separately human-authorized compatibility exercise; capture actual request/history/output behavior and server-side uncertainty. Offline/fake success is not evidence for this milestone. |
| 4. Protected filesystem production policy | Depends on root provisioning/handle lifecycle, staging/promoted capacity reservation and exact approved output destination policy. | Specify and validate local production roots, owner-only ACL/reparse/identity checks and cross-session capacity without mutating existing Project/user ACLs. |
| 5. Human Start and UI activation | Depends on 1, 2 and 4 plus final fresh review, original-host fencing and visible unknown/unsaved states. | Add a distinct user-confirmed Start action; wire no execution until the whole authorization chain is current. Confirmation alone must remain non-executable. |
| 6. Restart/recovery and retention/discard | Depends on adopted live/restart latest-head policy, protected Journal production lifecycle, source/review provenance, Project reconciliation and explicit human action. | Implement inspect-first restart inventory and human-authorized association/discard, with quotas and no automatic replay/cleanup. Missing/conflicting evidence remains uncertain. |

Before any production Start, durable unknown-submission evidence, protected
roots/capacity, truthful real transport, bounded worker and original-host event
delivery, exact fresh Human Start, Candidate publication/save, restart/recovery,
and retention/discard gates need separate implementation and review. Operational
ComfyUI testing needs explicit human authorization after those gates. Until then,
`execution_available=false`, `protected_storage_available=false`,
`promotion_available=false`, `candidate_publication_allowed=false`, and
`authorship=unverified`; Candidate publication remains unavailable and Recovery
remains inspect-only. No automatic retry, replay, cleanup, or MCP execution
substitutes for these gates.
