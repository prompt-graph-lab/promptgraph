# Agent Generation offline ownership journal foundation (C2B-8A)

`core/generation_ownership_journal.py` is a private, characterization-only owner
for bounded observations and restart inspection. It has no production call
site. `execution_available` remains false. This is not a recovery executor,
publication owner, Project writer, Start UI or restart reconstruction of a live
claim. The C2B-8B [Human Recovery Review foundation](agent-generation-human-recovery.md)
now composes its read-only observations into private immutable review cases and
non-executable review intentions; authenticity remains unverified. The C2B-7
[integration/recovery audit](agent-generation-integration-recovery.md),
C2B-5 [containment](agent-generation-output-containment.md) and C2B-6
[Candidate publication](agent-generation-candidate-publication.md) still define
the runtime boundaries.

The C2B-8C-1 [protected-storage characterization](agent-generation-protected-storage.md)
now separates observed identity, ACL policy, integrity, digest-chain validity,
authorship and current authorization. A separate opt-in disposable Windows owner
can provision/observe a protected owner-only private-journal root on local NTFS;
production integration and directory durability remain unavailable. Neither
readiness projection grants execution or Recovery authority.

The C2B-8C-3 [trust and authorization design](agent-generation-protected-storage.md)
records Profile A: Local Single-User Application as the adopted supported Pro
security scope. Profile B is an unsupported optional future deployment design;
its key/service infrastructure is not a prerequisite for normal local Pro work.
The [fresh Recovery boundary](agent-generation-human-recovery.md)
separates inspection, intention and new host authorization. Existing unverified
authenticity/inspect-only flags remain unchanged under this design.

## Ownership and schema

An explicitly enabled `OfflineJournalWriter` receives a host-captured
`ApprovedRoot`, detached `OperationObservation`, and injectable fault hook.
The host approves canonical existing roots independently of journal contents.
The writer allocates only `<operation_id>.json` and exclusive UUID temporary
files within that root. It never accepts a journal-supplied destination.

Version 1 uses schema `promptgraph-generation-ownership`, the canonical journal
root path/device/inode, operation/process/session/job/claim/manifest IDs,
original source and frozen review SHA-256, ordered immutable request/Illustration/
run/workflow correlations,
original Project root key/path/device/inode, relative JSON path and original
JSON device/inode. Each strictly sequential revision has an observation, previous
digest and SHA-256 over the schema, version, complete operation identity and
unsigned revision. The complete previous revision chain remains in every
replacement; a missing middle, changed identity, conflicting digest or reordered
checkpoint is rejected. The host may supply an independently retained expected
revision/digest when reopening to detect a stale but internally valid prefix.

Observations contain only fixed typed values:

- `RequestObservation`: request ID/index, workflow identity, fixed outcome and
  optional observed remote prompt ID;
- `RemoteResultObservation`: correlated prompt/receipt IDs, result fingerprint,
  validated-success/validated-failure/unproven execution evidence and
  ready/pending/unknown/stale/quarantined/unresolved state;
- `ContainmentObservation`: correlated remote/local receipt IDs, expected and
  verified counts and verified/incomplete/quarantined/stale/unresolved state;
- `FileObservation`: host root key/path/device/inode, traversal-free relative
  filename, file device/inode, SHA-256, encoded size, contained/promoted role,
  format/dimensions, request/descriptor/output correlation and explicit
  verification state;
- `PromotionObservation`: request/local receipt, approved root, bounded planned
  relative paths and intent/complete/partial/failed/unknown/stale state;
- `CandidateObservation`: Illustration, job/manifest/request/run/workflow,
  observational claim, remote/local receipt and descriptor IDs, output ordinal, SHA-256 and approved
  asset-root key/relative path; and
- `ProjectSaveObservation`: original root/path, intent/saved/failed/uncertain
  state and optional observed JSON identity/fingerprint;
- `UnresolvedObservation`: optional request correlation, explicit unknown/stale/
  quarantined/unresolved state and a fixed safe reason; and
- a fixed checkpoint/outcome, with no free-form exception or payload field.

No live Project, runnable inbox envelope, review/approval capability, credentials,
endpoint configuration, workflow body, Start token or callable is serialized.
Opaque observational IDs grant no custody. Unknown fields in the journal are
refused rather than interpreted. JSON uses strict duplicate-key rejection,
finite values, exact schema/version/types, bounded identifiers and relative
paths. Limits are 1 MiB per journal/selected Project JSON, eight revisions,
100 request observations and 1,600 image/Candidate observations per revision.
The **operation-wide** union of file and Candidate path references plus promotion
plans is at most 1,600 distinct `(root_key, relative_path)` pairs, including both
staging and durable copies. Repeated references to the same path count once;
distinct staging/durable paths both count. Maximum observed encoded byte sizes
per recorded path count toward one 256 MiB operation-wide ceiling. Overflow is
rejected before writing; no necessary evidence is silently truncated. These
conservative bounds can withhold a journal containing all 1,600 possible outputs
and a staging/durable copy of each. The 1 MiB byte ceiling can impose a lower cap.

Each nested record must match the immutable request/Illustration/run/workflow
contract and operation job/claim/manifest. Observed prompt and remote/local
receipt IDs remain consistent across revisions. Submission records occupy
checkpoints 1/2; remote-result evidence appears only after submission at 2..4;
containment and contained verified files occupy 4; promotion intent occupies 5;
observed promotion files/results and Candidate registration occupy 6; Project
save evidence occupies 7/8. An observed later-stage result before its checkpoint
is refused. This order and matching hashes never reconstruct runtime custody.

## Ordered checkpoints and durability

The offline caller records these eight aggregate checkpoints in order. This
module does not perform any of the effects between checkpoints:

| Revision | Checkpoint | Observation/effect boundary |
| --- | --- | --- |
| 1 | `submission_intent` | Intent file revision acknowledged by the live writer before the characterized possible-send callback; not a production durability guarantee. |
| 2 | `submission_observed` | Accepted/failed/unknown result, separately from intent. |
| 3 | `download_attempt` | Intent before simulated download/image verification. |
| 4 | `images_verified` | Complete/partial/failed/unknown batch observations before any publication eligibility decision. |
| 5 | `promotion_intent` | Intent before simulated durable asset copying. |
| 6 | `registration_observed` | Actual registered/partial/failed/uncertain Candidate observation after disposable in-memory mutation. |
| 7 | `save_intent` | Intent before simulated original Project JSON replacement. |
| 8 | `save_observed` | Separate saved/failed/uncertain callback observation. |

The write order is exclusive operation lock -> check expected old revision/file
identity -> exclusive UUID temp creation -> serialize bounded snapshot -> flush
and file `fsync` -> `before_replace` failure hook -> root/temp/old revision
recheck -> atomic `os.replace` -> `after_replace_before_ack` hook -> reopen and
verify the complete new revision -> acknowledge and advance the live writer.
Ordinary success releases only the unchanged lock created by that writer.
Failures pin that writer as uncertain and cannot be retried. No existing newer
or conflicting journal is taken over. A second writer encounters the exclusive
lock or refuses the existing journal. A real process exit may retain a lock,
temp file or new journal without an acknowledgment; there is no stale-lock
takeover. Temporary evidence is retained on injected failure.

### C2B-8D-14 executor intent-before-send boundary

`ui.agent_generation_executor_journal.GenerationExecutorJournalIntent` is the
current offline-only call site that binds this existing writer to the real
`ComfyExecutorAdapter` pre-send decision. The original host constructs the
owner from its current runtime, exact Project/source/review evidence, explicitly
approved Project root and Journal root. The worker receives no Journal writer
or send capability. Binding is accepted only after the inbox has taken the
exact envelope; a single-request manifest is required.

For that request, the host first accepts `submission_started`, the Journal
owner verifies the exact frozen request and live host/job/claim state, then
appends and verifies revision 1 (`submission_intent`). Only its exact live
acknowledgment plus a final host/request recheck grants the adapter's one-shot
possible-send claim. The injected transport runs unlocked. Its exact accepted,
definite pre-send rejection, or uncertain outcome is recorded separately in
revision 2 (`submission_observed`). No acknowledged intent means no callback;
after a possible send, any missing/invalid response or failed result
acknowledgment remains unknown and cannot be retried. An acknowledged intent
remains evidence if writing the later result fails.

This call site deliberately refuses multi-request manifests. The current eight
ordered checkpoints are aggregate operation stages and do not define how
repeated per-request submission intents fit into one Journal. Expanding beyond
one request requires a separately reviewed checkpoint schema and lifecycle;
the current contract is not silently generalized. Reopen and inventory remain
inspection-only and cannot recreate a claim, original-host authorization or
permission to send/replay. This is characterization, not proof of power-loss
durability or author authenticity. `execution_available` remains false.

### C2B-8D-15A bounded multi-request Journal contract

`core.generation_multi_request_journal` adds a separately identified offline
contract for sequential request recording. It uses schema
`promptgraph-generation-multi-request-ownership`, version 1, in the same
`<operation_id>.json` slot. V1's eight aggregate checkpoints, decoder,
revision meaning and writer remain unchanged. The two schemas cannot occupy the
same operation file simultaneously; neither writer migrates, overwrites or
reinterprets the other's evidence. This contract is persistence-only and is not
connected to `ComfyExecutorAdapter`.

The selected model keeps one bounded full-snapshot digest chain with three
ordered records per frozen request. Extending or reinterpreting the v1
eight-checkpoint sequence was rejected because it would change existing
revision meaning and inspection behavior. Splitting requests across separate
files was rejected because it would add a cross-file commit boundary without
making the remote-send outcome more knowable.

Each frozen request is represented in order by three possible revisions:

| Event | Meaning and next-send rule |
| --- | --- |
| `submission_intent` | Exact request correlation is written, reopened and acknowledged by the live writer before its possible-send boundary. Without this exact live acknowledgment, the caller must not invoke transport. |
| `submission_outcome` | Records `accepted`, definite `pre_send_rejected`, or `unknown`. An accepted prompt ID proves submission acceptance only; it does not prove that execution has finished. Unknown is terminal for this operation and never authorizes another request. |
| `request_settlement` | Records a separately validated original-host observation: `execution_completed`, `execution_failed`, or `pre_send_rejected`. Only this exact live typed observation, bound to the prior acknowledged revision/digest and the full operation/request/process/session identity, makes a later frozen request eligible for a new intent. |

Thus accepted submission and remote execution settlement remain separate.
Even a known pre-send rejection requires a separate original-host observation
before the following request. A missing outcome after an acknowledged intent,
an unknown outcome, missing settlement, skipped/reordered request, duplicate
event, substituted identity or lost acknowledgment cannot authorize the next
send. The writer does not repair, replay or silently advance any such state.

`MultiRequestJournalWriter` accepts only its exact current in-memory
`JournalAcknowledgement` object for the immediately preceding revision. Each
record is bound through the immutable operation snapshot and digest chain to
operation/job/claim/manifest and the frozen request ID/index, Illustration, run
and workflow identities. The settlement validator runs outside the Journal
writer lock and returns a typed host observation; the writer then rechecks the
exact live tip and binds that observation to it. The private characterization
issuer is a test seam, not a host authorization source. C2B-8D-15B must connect
it only to an independently validated current original-host/job settlement,
never to Journal bytes, a prompt ID or a matching opaque string.

The enforceable per-operation ceilings are:

- at most 100 frozen requests, 300 revisions and 300 retained event records;
- at most 1 MiB for the complete replaced Journal file;
- at most 2 MiB live operation data at replacement (old complete file plus one
  complete temporary file; the exclusive lock is empty); and
- at most 128 MiB of cumulative full-snapshot bytes written across the complete
  300-revision worst case.

The writer preflights the worst-case full operation, including maximum bounded
identifiers and prompt/host-observation IDs, before it can acknowledge the first
intent. If it cannot fit the supported workload, it refuses before any send.
Each append rechecks file-size/revision limits; a missing acknowledgment never
grants that request's possible-send boundary. A failure retains its lock/temp
or replaced file as uncertain evidence and the writer cannot retry. The
protected Windows characterization uses the existing pinned protected root and
CREATE_NEW owner-only ACL writer; focused native tests inspect lock, temporary
and final file identities/ACLs. This is not a power-loss, hostile same-user or
cross-file atomicity guarantee. “Acknowledged” means the current process
reopened and verified the replacement before returning its live acknowledgment;
it does not claim parent-directory flush, power-loss durability or persistence
across every hardware failure.

`reopen_multi_request_journal` strictly validates the separate schema and
sequence but returns `trust=inspect_only`, `authorship=unverified` and
`execution_available=false`. Reopening cannot construct a writer, settlement
observation, send authority or restart continuation. A digest-valid settled
prefix is still not original-host authorization. The v1 Human Recovery reader
does not interpret this format.

C2B-8D-15B must compose the actual Executor's one-shot intent/send/result flow
with this writer; preserve the no-integration behavior when it is absent; use
the accepted `submission_started` host event; persist accepted/rejected/unknown
outcomes without retry; wait for separately validated terminal host settlement
before the next intent; and stop later requests on missing, conflicting or
uncertain evidence. It must keep Journal I/O and transport/host callbacks
outside job/inbox mutation locks, maintain the existing lock order, and leave
restart, production worker registration, Start, Recovery, Candidate publication
and Project save disabled.

### C2B-8A v1 failure and reopen semantics

Failure before replacement leaves the old complete journal (or none for revision
1). Failure after replacement before acknowledgment may leave the complete new
journal. Reopen reports observed bytes, never success for an unobserved external
effect. Incomplete intent is explicitly `*_outcome_unknown`; it is not proof of
no submission, no download, no registration or no JSON save.
Reopened observations separately expose complete/incomplete checkpoint coverage,
the next unobserved checkpoint, and explicit unresolved reasons. Complete
checkpoint coverage means all eight observations exist, not that every effect
succeeded or that restart authority exists.

The supported offline writer contract serializes cooperating writers using the
exclusive lock. It is not a hostile-process compare-and-swap or ACL sandbox.
There is no parent-directory flush, asset/Project/journal transaction, Windows
power-loss guarantee or proof of persistence across every hardware failure.
The tested interruption hooks establish old-or-new readable file behavior in
disposable fixtures only. Protected-root provisioning/ACLs and an explicit
durability/uncertainty contract remain production gates within Profile A.
Hostile same-Windows-user processes, Administrator/SYSTEM and compromised host
code are outside its supported scope; LLM/MCP instructions remain untrusted.

## Authenticity and read-only inventory

SHA-256 detects accidental corruption and inconsistency. It **does not
authenticate against another same-user writer**, who can replace records and
recompute the whole chain. No encryption or ACL protection is claimed. A valid
chain can also be rolled back to a valid prefix without an independently trusted
latest revision/digest. Every reopened journal reports `authenticity=unverified`,
`trust=inspect_only` and `execution_available=false`; hashes/IDs never grant
attachment, approval, retry, worker take, publication or save authority.

Under adopted Profile A, bounded acknowledged live-writer observations may serve
as a current host tip during the live host/process lifetime. After restart,
absent an independently retained host-observed tip, latest-head custody is
unavailable. Where/how to retain that checkpoint and its write/acknowledgment
order and uncertainty contract remain unresolved. Digest-valid prefixes and
identical paths grant no automatic rollback repair, replay, Recovery association
or execution; neither hashes nor ACL observations authenticate authorship.

`inspect_inventory` directly lists at most 64 entries in one explicitly approved
journal root and at most 64 entries total across at most seven explicitly approved
asset roots (eight total roots including the journal). It does not recurse,
discover OS temporary directories, infer a
current/last Project or scan whole Projects. Explicit recorded relative files
may be inspected beneath their approved roots after ancestor reparse checks.
Every opened file uses `O_NOFOLLOW` where available, checks `lstat` ancestors,
canonical root/file path and device/inode before/after the read, and refuses
Windows reparse points and symlinks. Root allowlist entries are frozen host
observations; recapturing a substituted root does not satisfy recorded identity.

Image inspection has one aggregate encoded-byte budget (default 32 MiB, only
lowerable), at most 64 referenced files, the original C2B-5 signature/format,
single-frame, dimension/pixel and full-decode checks, and SHA-256/size/identity
comparison. `exact` describes matching bytes/metadata only. Missing, tampered,
conflicting, image-invalid, changed-root/file, unapproved-root, unreadable and
budget-exceeded observations are separate. Unindexed direct entries are
`unverified` orphans, never reconstructed receipts. Truncated inventory is
explicit and cannot prove global absence. Inventory reads no remote history,
downloads nothing and never relocates, adopts, cleans up or deletes files.
Candidate asset references participate in this bounded inventory even without
promoted file evidence: an absent asset is `missing`, a present asset without
original identity/size evidence is `unverified`, and a disagreeing promoted
record is `conflicting`. Candidate hashes alone do not verify or adopt an asset.

## Explicit selected-Project reconciliation

`reconcile_selected_project` accepts only the explicitly selected original root
key/path/identity and recorded relative Project JSON path. It reads bounded JSON
directly with duplicate-key checks. It never loads the live model, normalizes
unknown fields, updates active session state, calls an appender/serializer or
saves anything. Unknown saved Project/Candidate fields remain untouched.

Before a save intent, the original JSON file identity must match. An atomic
Project replacement after recorded save intent legitimately changes that
identity, so reconciliation observes current JSON without treating the changed
inode as confirmation that this operation wrote it. Original source SHA-256 is
retained observational context; this foundation does not prove current source
freshness or reconstruct a source/recovery authorization contract.

The selected JSON's Illustration ID, Candidate provenance correlation fields,
output ordinal, SHA-256 and canonical asset path are compared against each
expected detached Candidate observation. Saved relative paths are resolved
only beneath the selected JSON directory; traversal is refused. Duplicate or
different provenance/path associations conflict. States are:

- `exact`: every expected Candidate has one matching saved association;
- `absent`: no expected association is present;
- `partial`: some expected associations are exact and the remainder absent;
- `conflicting`: duplicate/different associations or different selected target;
- `missing` or `unreadable`: selected JSON cannot be read; and
- `uncertain`: malformed/bounded/unverifiable evidence, changed original file
  before save intent, missing allowlist, or no usable Candidate observations.

The journal's saved/failed/uncertain observation is reported independently from
the current JSON match state. An exact saved association after uncertain save
does not upgrade its callback outcome or authenticate the journal. Reconciliation
does not verify all referenced assets itself; combine it with inventory and
retain both limitations. Even an exact result has `attachment_allowed=false`.

The observational claim is checked against the immutable journal operation but
is not required in saved Candidate provenance: the existing C2B-6 Candidate
schema does not persist claim IDs. No new public Candidate field is introduced.

## Remaining gates

This foundation has no production integration into submission, containment,
publication or JSON save. Those owners retain their existing contracts. Future
production work must approve protected roots, platform durability, an explicit
implementation within adopted Profile A's threat/ownership policy, integration
of the C2B-8D-15A multi-request contract and safe journal storage limits. A
separately reviewed human recovery contract must re-establish current
Project/source/session/activation/pairing authority. Retention/cleanup requires
its own human decision and Project-reference/external-operation uncertainty
resolution. Real transport, worker lifecycle, Start UI and operational validation
remain separate gates. Restart inspection never recreates runtime claim custody.
