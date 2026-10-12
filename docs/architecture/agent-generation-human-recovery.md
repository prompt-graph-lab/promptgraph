# Agent Generation Human Recovery Review foundation (C2B-8B)

`ui/agent_generation_human_recovery.py` is a private, characterization-only
host owner with no production call site or Recovery UI. It composes the
[C2B-8A ownership journal](agent-generation-ownership-journal.md)'s bounded
read-only inspection and explicit saved-Project reconciliation. Production
`execution_available` remains false. There is no Candidate association,
Project save, cleanup, worker resume or ComfyUI submission in this owner.

The C2B-8C-1 [protected-storage characterization](agent-generation-protected-storage.md)
adds explicit disposable purpose-root and fail-closed Windows capability
contracts. Matching identities and synthetic ACL-policy samples cannot upgrade
this owner's journal authenticity or current recovery authorization.

## Private case and presentation

`HumanRecoveryReviewOwner` holds one frozen `RecoveryCase` and at most one
review intention. Construction requires `characterization=True`, explicit
host-approved journal/Project/asset roots, an exact relative journal filename
and selected Project JSON path. The host may pin an independently retained
expected journal revision/digest. The owner does not discover an active or
last Project, scan OS temporary storage, load a mutable Project, or infer roots
from journal contents. Asset roots and inspection budgets retain C2B-8A limits:
up to seven asset roots, 64 inventory entries/referenced files and 32 MiB
aggregate encoded-image inspection, with only smaller budgets accepted.

The private snapshot combines:

- Original immutable operation, request/Illustration/run/workflow correlation,
  source/review digests, original Project root/file identity and selected path.
- Observed journal checkpoint, revision/digest/file identity, complete chain,
  unresolved observations and **unverified** authenticity.
- Bounded contained/promoted image verification, missing/altered/conflicting/
  unverified evidence, orphans, inventory errors and explicit truncation.
- Private file identity/size/mtime/ctime observations for at most 64 already
  inspected/listed entries beneath approved roots; unavailable metadata blocks
  association. These add no encoded-image reads or scan scope.
- Selected JSON content digest/file identity, original Illustration occurrence
  counts, current references to recorded assets and Candidate reconciliation.
- Separate saved/failed/uncertain/unknown callback observation and current
  persisted evidence. A current matching Candidate does not upgrade the callback.
- Unknown/unresolved external execution and fixed host observations of original
  session, runtime authority and source/review provenance.

`RecoveryContext` accepts only finite observation states. An `observed` runtime
or `recorded` source/review marker is context, never a capability or a freshness
proof. Defaults are missing authority/provenance and lost session. No claim,
approval, pairing, Start, publication or save authority is reconstructed.

The bounded projection contains ordinal request/Illustration/image labels, run
and output indices, checkpoint/revision, fixed statuses/reasons, verified image
format/dimensions/encoded size, association counts, save uncertainty, unknown
external submissions and manual checks. Raw correlation IDs are kept private;
ordinal labels still group repeated Illustrations/runs. Image metadata is
available only after current full byte/identity/decode comparison and a recorded
`verified` observation. The projection provides no image path, executable
handle, raw payload, root path, claim/session/process token, full prompt,
credential, endpoint or saved Candidate provenance. It is returned detached;
mutating a projection cannot modify the private case or decisions.

For JSON before save intent, changed original file identity requires
reconciliation. The host can supply an independently retained
`original_project_sha256` to compare original JSON bytes. Without it, content
is explicitly unverified. The journal's source/review digests describe their
own snapshots and are never inferred to be serialized JSON fingerprints.
After save intent, a recorded saved-JSON fingerprint
is compared separately; a mismatch marks the Project changed. Without that
fingerprint, different current bytes are `content_needs_reconciliation`, even
when Candidate association is exact. This is not semantic source freshness:
matching source/saved fingerprints remain unauthenticated journal evidence.
Original Illustration IDs must occur exactly once; a missing or duplicate ID
blocks association even when there is no recorded Candidate yet.

Current C2B-8A journal authenticity is always unverified. Hash agreement,
saved Candidate agreement, checkpoint completeness and human acknowledgment
cannot authenticate it. The private owner has no authenticity-upgrade input.
Expected tip/digest can detect a stale prefix, but cannot authenticate its
author. Without the retained tip, a valid rollback remains inspect-only.

## Conservative separate classifications

The projection exposes separate flags so association and inspection are not
mistaken for recovery authority:

| Classification | Meaning in this foundation |
| --- | --- |
| Evidence available for human inspection | At least one recorded image has exact current bytes/identity/decode and recorded verified metadata. It is still unauthenticated ownership evidence. |
| Evidence needing further reconciliation | Fixed blockers remain, including authenticity, source/review/runtime context, selected Project, assets, save, external execution or inventory coverage. |
| Candidate already associated | Current saved JSON has at least one exact recorded association. Partial insertion stays partial; this flag grants no append/save authority. |
| Recovery request needs fresh authorization | Always true. A review request is not an authorized recovery operation. |
| Evidence currently unsafe to associate | Always true until a separately implemented/authenticated recovery contract passes review. |

Unverified journals, missing/altered/unverified assets, duplicate Illustration
IDs, changed/missing Project, partial/conflicting Candidate insertion, failed or
uncertain persistence, unknown external execution, missing provenance, truncated
inventory and missing/expired runtime authority all retain explicit blockers.
An accepted request, Candidate or local image alone never establishes remote
completion. Only a correlated observed validated remote result (or definite
submission rejection) avoids `unknown`; explicit unresolved evidence still
keeps it unknown. These are observations, not a live remote query.

Inventory truncation, byte-budget exhaustion and inventory errors display
**not fully inspected**. Otherwise the label is **bounded scope inspected**;
there is no global absence claim or "no other files" result. Asset verification
problems are displayed separately. Direct-root scope never proves the absence
of nested/unapproved/unrecorded evidence.

## Decisions and staleness

The only supported decisions are:

| Decision | Result |
| --- | --- |
| Inspect | Read-only inspection; preserves an existing review intention. |
| Defer | Records one scoped deferral. |
| Request recovery review | Records a human review intention requiring fresh authorization. |
| Request discard review | Records a human review intention requiring independent cleanup authorization. |

The decision owner is separate from `GenerationJobRegistry`, executor inbox,
publication and `ProjectAgentSessionRuntime`. It has no widget/MCP/session
integration. A decision accepts only the exact privately held immutable Case
object/revision; an equal copied object, an older object or another owner's
case is refused. Every supported decision reopens the journal, bounded inventory
and selected JSON first. Differences replace the case, increment its host case
revision, clear a pending intention and return `stale_case`. Explicit context
refresh also invalidates review on session/provenance/authority changes.
Display refresh performs the same inspection. Repeating the same intention is
idempotent; a different intention on the unchanged case is refused. Inspect
does not clear or conflict with an intention. Close clears the intention and
rejects decisions.

The lock serializes this host owner only. Filesystem reads are sequential
observations, not a transaction or hostile-writer barrier. A journal difference
between the explicit read and inventory is reported as conflicting. Final
freshness checks for any future effect need their own authenticated original
host/publication gate; this owner performs no effect after a review decision.
It retains no automatic retry, resume or future permission grant.
Metadata changes also invalidate a pending review when an asset remains
tampered or an orphan remains unverified. Hostile writers that spoof metadata,
uninspected files beyond budget and atomic inspection across every local read
still require protected-root/authenticity policy; this owner makes no such claim.

## Read-only retention assessment

Retention is a bounded observation, never an expiry policy or cleanup plan.
The projection distinguishes:

| Class | Observed interpretation |
| --- | --- |
| Verified unpublished | Current verified bytes, no recorded Candidate and no selected JSON reference to the recorded image, with inspectable original/saved Project bytes. "Verified" means image consistency, not authenticated ownership. |
| Published/saved Candidate assets | Verified promoted bytes, exact current saved Candidate association, recorded saved callback and matching recorded saved-JSON fingerprint. Journal authenticity remains unverified. |
| Promoted after failed/uncertain save | Current verified promoted bytes with failed, uncertain or unknown save outcome; pin the evidence even if a matching Candidate is found. |
| Orphan/incomplete | Listed unindexed evidence, missing/altered/unverified/uninspected references, partial association or unverifiable persistence. |
| Quarantined/stale | Recorded quarantine or stale verification; metadata/association is withheld. |
| Unknown external submissions | Separate observed correlated request count, or null when no usable journal exists; local expiry or files do not prove remote cancellation. The count is always incomplete without authenticated completeness evidence, including when a journal is present. |

Each local class reports bounded recorded/listed references, observed present
entry count, observed verified encoded bytes and whether every size in that
class is known. Missing/uninspected references do not count as observed files.
Unindexed files are listed only within the inventory budget; their size/type is
unverified. The projection's 64 image rows can further bound displayed counts.
**Capacity is always incomplete/unknown** while the journal is unauthenticated;
truncation makes it incomplete independently. These counters are not global
storage usage, free-space verification, quota reservations or deletion budgets.
No age threshold, directory sweep, deletion, move or eviction is implemented.

## Proposed fresh Recovery authorization (C2B-8C-3; not implemented)

The [trust-profile decision and evidence matrix](agent-generation-protected-storage.md)
define the proposed security scope. Profile A is a recommendation requiring
human adoption; Profile B requires independently protected producer and
latest-head custody. Neither is current policy or an authenticity-upgrade input.
Under either profile, the steps below require a new separately reviewed host
owner. The existing `HumanRecoveryReviewOwner` remains inspection/intention only.
Its `RecoveryDecision.permission_granted` stays false, and its projection's
execution/publication/save/cleanup gates stay false.
`RecoveryContext(runtime_authority="observed")` is never that new owner.

| Stage | Private binding required in a future owner | Fence / permitted result |
| --- | --- | --- |
| 1. Read-only case | Exact bounded Journal revision/digest, expected-tip provenance or explicit absence, independently selected protected roots, file evidence, saved-JSON reconciliation and source/review lineage. | Inspectable evidence only. A copied projection/case ID or matching hash grants nothing. Incomplete or unverified findings remain visible. |
| 2. Human review intention | Exact privately held case and current case revision; association and discard intentions are different requests. | Existing intention may be recorded after rereading evidence; it cannot queue an effect or supply approval. |
| 3. Independently verified current host | Host-selected original Project identity/path/content, unique original Illustration IDs, source prompts/negative prompts/Modules/Scene, exact original reviewed request/output mapping, verified current asset bytes/roots, plus a new session/activation/pairing binding. Provenance is checked under the adopted profile and cannot be asserted solely by the Journal or MCP request. | Missing, changed, duplicate or ambiguous evidence blocks association. No active/last Project fallback, silently substituted source or restored old claim. |
| 4. Fresh explicit human action | Complete current recovery differences, all proposed output associations, already-saved members, unresolved external/save outcomes and the profile's limits are shown. Action binds that exact freshly checked review and host context. | A separate host confirmation, not old ACK, checkbox state, agent flag or persisted intention. Changed evidence invalidates it. |
| 5. One-shot authorized plan | Host-private custody binds the exact case/evidence and reviewed plan, selected original Project, unique targets, source/review fingerprints, job/manifest/request/run/output correlations, asset identities/hashes, latest-tip state, and fresh host/session/activation/pairing. | Single admitted attempt only; never serialize a runnable token in the Journal or expose it through MCP. Plan IDs/digests are identity, not authority. Loss, close, stale target or conflicting attempt fences it. |
| 6. Original-target host publication/save | Reconcile current Project and Candidate provenance again, check protected assets and all bindings immediately before mutation, then use separately reviewed host appender/history/Gallery/save owners. | Publish only the reviewed missing associations, retain observed partial/unknown outcomes and save through the exact original selected destination. No repeated mutation or automatic save retry. |

After process loss, "original-target host" means a newly explicitly chosen host
bound to the original persisted Project and separately verified source/review
lineage. It does not mean the old Python object, claim, session, activation,
pairing or approval survived. Reopening the same path, or switching back to the
same Project, does not satisfy stages 3..5. Missing lineage remains a blocker;
intentional transfer to a changed Project/Illustration would be a different
reviewed operation, not a force/ignore-stale Recovery option.

The immediate pre-mutation gate must follow current reviewed-operation custody:
recompute the complete plan from current host/evidence, require exact reviewed
equality, then reject drift before history, Candidate mutation, Gallery/session
publication or save. Recheck the original destination and source/activation
binding immediately before any separate save effect. A stale result publishes
no side effect or accepted confirmation. This design does not introduce a
cross-file transaction or claim to close hostile same-user read/use races.

Idempotence requires a bounded host-owned attempt record and reconciliation of
each exact output association, not a new claim inferred from the Journal. An
already exact saved Candidate is reported as present without attachment. A
partial result may propose only provably missing exact members after conflicts
and persistence uncertainty are resolved and a new human review/action occurs;
never replay the batch. If mutation or save raises after a possible effect,
record observed partial/unknown state, consume the admitted attempt and require
read-only reconciliation. A matching saved Candidate does not retrospectively
authorize the attempt or turn an unknown save callback into success. Recovery
must not resubmit remote generation or take an executor inbox envelope.

**Discard is a separate authorization path.** Its review must bind exact owned
files/roots and retained evidence, prove sufficient inventory and saved-Project
reference coverage, and resolve save/external-operation uncertainty. A missing
Project, uninspected reference, unknown ownership or reparse/identity drift blocks
discard; age, job expiry, capacity pressure, association approval and failed save
do not authorize deletion. Its own fresh human action and one-shot plan require
an immediate pre-deletion ownership/reference recheck. No recursive retry or
uncertain-evidence deletion is approved. Retention/defer remains available for
unresolved cases without granting cleanup authority.

These contracts are design gates only. A future implementation must document
host lock ordering and callback boundaries, and characterize concurrent stale
transitions, repeated action, partial append and save failure against the
existing publication owners. Production activation and operational tests remain
separate human decisions in the protected-storage go/no-go matrix.

## Characterization and remaining gates

`tests/test_agent_generation_human_recovery.py` uses disposable journal roots,
images and Project JSON. It covers complete and partial Candidate association,
unpublished verified bytes, changed/missing Project, duplicate/missing original
Illustrations, missing/altered/unverified/quarantined/stale images, save failure
and uncertain persistence, unknown external execution, truncated/byte-bounded/
conflicting inventory, journal rollback/authenticity uncertainty, repeated and
conflicting decisions, copied/stale cases, changed evidence, session loss and
expired/missing provenance/authority. Side-effect guards and byte comparisons
verify no Project save/mutation, journal write, deletion/move, network or worker
restart. Existing C2B-1..8A and Scene Module Swap focused regressions remain the
compatibility baseline; no full suite or live operational execution is claimed.

Production still needs an explicitly adopted threat/ownership policy (including
independent authentication if Profile B is required), protected roots/ACLs and
durability policy, fresh original Project/source/review/session/activation/
pairing authority, exact human recovery authorization, idempotent association
and original-host publication/save gates. Cleanup needs its own explicit
authorization, ownership verified under the adopted profile and saved-reference/
external uncertainty resolution. Global quota/reservation, truthful bounded real transport, worker
lifecycle and authorized operational restart/failure exercises remain separate.
This characterization foundation supplies none of those capabilities and does
not change C2B-1..8A or Scene Module Swap runtime owners.
