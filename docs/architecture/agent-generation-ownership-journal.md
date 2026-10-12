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
| 1 | `submission_intent` | Intent durably acknowledged before simulated external submission. |
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
disposable fixtures only. Protected-root provisioning/ACLs, directory durability
and hostile filesystem concurrency remain production gates.

## Authenticity and read-only inventory

SHA-256 detects accidental corruption and inconsistency. It **does not
authenticate against another same-user writer**, who can replace records and
recompute the whole chain. No encryption or ACL protection is claimed. A valid
chain can also be rolled back to a valid prefix without an independently trusted
latest revision/digest. Every reopened journal reports `authenticity=unverified`,
`trust=inspect_only` and `execution_available=false`; hashes/IDs never grant
attachment, approval, retry, worker take, publication or save authority.

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
production work must approve protected roots, platform durability, authenticated
ownership policy, a multi-request recording lifecycle and safe journal storage
limits. A separately reviewed human recovery contract must re-establish current
Project/source/session/activation/pairing authority. Retention/cleanup requires
its own human decision and Project-reference/external-operation uncertainty
resolution. Real transport, worker lifecycle, Start UI and operational validation
remain separate gates. Restart inspection never recreates runtime claim custody.
