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

## Remaining gates

This slice characterizes one original-runtime publisher for one accepted
envelope. Explicit recovery/inventory, session restart reconstruction, owner
retirement/replacement, durable retention/cleanup and protected filesystem policy
remain separate work. Production activation also requires separately approved
real ComfyUI transport/redirect policy, worker lifecycle, Start UI, exact human
confirmation and operational validation. Scene Module Swap custody and ACK
continue to belong to their existing owners and are unchanged by publication.
No execution or publication capability is exposed through MCP.
