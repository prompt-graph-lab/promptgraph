# Agent Generation protected storage and trust design (C2B-8C-1..4)

`core/generation_protected_storage.py` characterizes the protected-storage policy
required by the [Ownership Journal](agent-generation-ownership-journal.md),
[containment](agent-generation-output-containment.md), durable asset promotion
and [Human Recovery](agent-generation-human-recovery.md). It has **no production
call site**. `execution_available` and every execution, association, publication,
save and cleanup status remain false. Recovery remains inspect-only.
`core/generation_windows_protected_storage.py` adds a separate opt-in native
Windows observation owner for narrowly supported disposable roots.
`core/generation_protected_journal.py` adds an offline disposable Journal lifecycle
over that native owner and the existing Journal and Human Recovery inspection
owners. It has no production call site; containment, promotion and execution
remain unconnected.

## Threat model and separate evidence

The foundation distinguishes accidental corruption, another-user filesystem
access, same-user writers, path substitution, interrupted writes and unsupported
storage. Privileged administrators, SYSTEM, compromised host code and hardware
failure are not authenticated or isolated by this foundation. Even a later
owner-only ACL cannot distinguish legitimate host code from another process
running with that user's token. No secrets, HMAC keys, signatures, encryption,
DPAPI-backed identity or trusted author are introduced.

| Observation or future gate | Meaning | Does not imply |
| --- | --- | --- |
| Observed root/file identity | Same Python `st_dev/st_ino` at bounded path checks | Handle-pinned access, verified ACL, trusted writer or freshness between checks |
| Verified ACL snapshot (native disposable owner only) | Complete bounded modeled owner-only DACL on the pinned object | Authentication of another process using the same user token or general effective-access certification |
| File integrity | Existing C2B-8A byte/hash/image checks agree | Authenticated source or current runtime custody |
| Digest-chain validity | Internal ordered journal hashes agree | Author authentication or latest-state proof |
| Latest-head custody | A bounded acknowledged live-writer tip, or an independently retained host-observed restart tip, can detect an older prefix within its custody scope | Authorship or restart custody derived from journal bytes alone |
| Authorship authentication (unverified here) | Separately designed trusted writer policy | Current Project/source/session/activation/pairing authorization |
| Current authorization (absent here) | Separately reviewed fresh host capability | Authority derived from paths, ACLs, checksums, IDs or human inspection |

A same-user writer can replace journal contents and recompute every SHA-256.
Tests demonstrate a digest-valid changed process identity and a valid rollback
without a retained latest head. Both reopen as unauthenticated inspect-only
evidence. A retained expected tip detects rollback without establishing
authorship. Neither policy-compatible synthetic ACL samples nor successful
filesystem observations are accepted as an authenticity upgrade.

## Explicit disposable purpose roots

`ProtectedStorageCharacterization.capture_for_characterization` requires both
`characterization=True` and `disposable_opt_in=True`, an existing canonical
absolute disposable scope and exactly four independently supplied purpose paths:

| Purpose | Allowed observation |
| --- | --- |
| `private_journal` | Existing private journal directory identity |
| `temporary_containment` | Existing staging/containment directory identity |
| `promoted_assets` | Existing durable asset directory identity |
| `selected_project_json` | Exact original selected Project JSON identity; reference only |

All paths must be strict descendants of the opt-in scope. Purposes cannot alias
or nest within each other. Journal-supplied paths, inferred active/last Projects,
OS temp discovery and arbitrary user directories are not accepted. Outside
paths and missing/extra purposes are rejected before filesystem probing. The
caller supplies the original selected JSON independently of journal contents;
the owner does not select, read, change or save its contents. The disposable
contract intentionally does not admit a real Project outside the scope.

Capture and recheck use `lstat` on every ancestor, including the drive root,
refuse symlinks and Windows reparse points (including junctions), require
ordinary directories/files, reject multiply linked selected files, and compare
original scope/root/file identities. Substituting a directory or identical
selected JSON bytes does not recapture identity. No recursive scan, content
read, allocation, ACL change, deletion or transport occurs. These path checks
detect observed substitutions; they do not close hostile check/use races.
That limitation keeps protected-storage capability unavailable.

`readiness()` returns a detached bounded projection: four purpose rows, fixed
identity/ACL/integrity states, platform/backend blockers and separate trust gates.
It exposes no paths, device/inode values, SIDs, process/claim/session IDs,
exceptions, payloads, credentials or endpoint information. ACL/integrity/chain/
authorization are never inferred from unchanged identity. Missing, inaccessible,
reparse and changed objects remain closed. All non-Windows platforms are
unsupported. This path/stat owner reports `native_observation_required` on
Windows; it never infers native guarantees. A separate native owner's projection
can report a verified ACL snapshot while overall protected-storage readiness
and all execution/Recovery gates stay false.

## Windows capability evaluation and precise unsupported boundary

Windows offers handle-oriented APIs. The evaluated host exposes `CreateFileW`,
`GetFileInformationByHandleEx`, `GetVolumeInformationByHandleW`,
`FlushFileBuffers`, `GetSecurityInfo`, `SetSecurityInfo`,
`GetSecurityDescriptorControl`, `GetAce` and `GetTokenInformation`. Export
presence is an availability observation, not a completed security owner.
The repository pins `pywin32==312`; its documented application environment is
the local `.venv` created by `setup.bat` with Windows CPython 3.14 x64 and the
requirements lock. This disposable checkout initially had no application
`.venv`; the initial test interpreter lacked `win32security`/`ntsecuritycon`.
That absence is not a claim about a correctly installed application environment.

Python path/stat checks and `mkdir(mode=0o700)` are not the verified Windows
owner/DACL contract. On the evaluated Windows stdlib, `O_NOFOLLOW` and
`O_DIRECTORY` are absent. Shell ACL text is not used as a security verifier.
The separate native owner uses pywin32 312 plus typed ctypes calls for
`FileIdInfo` and `GetVolumeInformationByHandleW`. Missing dependencies/APIs,
unsupported platforms or failed native observations fail closed.

`WindowsProtectedRootCharacterization` requires the same two explicit opt-ins,
an existing canonical disposable scope, and an exact purpose. It opens and pins
every ancestor, scope and target with `GENERIC_READ | READ_CONTROL`, no DELETE
sharing, and `OPEN_REPARSE_POINT | BACKUP_SEMANTICS`. Metadata-only desired access
did not fence rename in the first native characterization; requesting
`GENERIC_READ` establishes the tested sharing fence without reading contents.
Actual native tests now refuse both live root and scope rename attempts.

File identity uses `FileIdInfo`'s 64-bit volume and 128-bit file ID, compared with
the approved path's Python identity. Legacy `GetFileInformationByHandle`'s
32-bit volume serial did not match Python's volume identity. Reparse/directory/
hardlink attributes and final path are inspected on the same opened object.
The final handle path must match the selected path, be non-UNC, and report
`DRIVE_FIXED`; a mapped remote drive cannot pass merely by reporting NTFS.
The same handle's volume must report NTFS and persistent ACL support.

The writable scope and every existing intermediate directory through the selected
target must **already** have protected current-user-only DACLs. Ancestors above the
approved scope remain pinned for path checks without imposing this ACL policy.
No existing scope, intermediate directory or target is repaired.
`provision_journal_for_characterization` chooses
one new UUID private-journal child and supplies a protected owner-only DACL
atomically to exclusive `CreateDirectory`. A collision is an error, never a
repair/overwrite. If subsequent verification fails, new evidence is retained;
no cleanup occurs. There is no provisioning method for assets or selected JSON.
`capture_for_characterization` only opens existing purpose paths read-only.

The native verifier reads owner and complete bounded DACL through `GetSecurityInfo`
on that handle, requires the current process-token user as owner, a protected
non-null DACL, and only explicit basic owner allow entries with `FILE_ALL_ACCESS`
and optional object/container inheritance flags. Inherited, other-principal,
deny/object/callback or unmodeled ACEs are unsupported/unsafe. Thread impersonation
is unsupported. Token/group/privilege cases outside this narrow owner-only model
are not accepted as a general effective-access proof. No privilege is enabled.
The complete in-scope chain's descriptor and identity observations are retained
and rechecked before returning the private owner. Each readiness call compares
every pinned in-scope handle's ACL and identity with those original observations,
checks the paths for identity/reparse changes, and rechecks the target filesystem.
Even a change to another supported owner-only ACL invalidates the observation.

The native projection can report `owner_only_acl_observed` and `acl_verified=true`
for this snapshot while handles remain open. Closing releases handles and changes
the projection to closed/unverified; it never deletes the root. Paths/SIDs remain
private. No native observation authenticates same-user writers, verifies content,
establishes directory durability, grants current authorization or makes overall
`protected_storage_available` true. Existing production owners remain unchanged.

`AclPolicySample` is explicitly synthetic. The conservative model requires
an exact current-user owner SID, present protected DACL and bounded explicit
owner-only allow entries with modeled file rights. Inherited entries,
Everyone/Users/other principals (including SYSTEM in this narrow model), changed
owner, absent/null DACL and unprotected inheritance are unsafe. Unmodeled ACE
kinds, masks or malformed/unbounded inputs are unsupported.
`compatible_model_only` still has `acl_verified=false` and cannot be passed into
readiness to upgrade any gate. A future policy may review additional system
principals; this model approves none implicitly.

Microsoft's [GetSecurityInfo contract](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
retrieves a descriptor through a handle and describes race limitations.
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
defines open/handle semantics a later backend must validate. OS APIs are
available; supported protected-storage implementation is not established here.

## Write, replacement and durability characterization

`characterize_write_boundary` interprets the existing offline writer's ordered
flush/fsync, replacement and acknowledgment boundaries without performing them.
Disposable tests exercise the actual C2B-8A writer with injected fsync failure
and interruptions before replace and after replace before acknowledgment:

| Boundary | Observable state | Meaning |
| --- | --- | --- |
| File sync fails / before replacement | Old complete file, or no first revision; temp evidence may remain | Unacknowledged, pinned writer, no retry |
| After replacement before acknowledgment | Complete new file may be visible | Ambiguous acknowledgment, no replay or effect-success inference |
| Acknowledged and reopened | New revision observed in that process | No directory durability, power-loss or cross-file transaction guarantee |

Current owners do not establish a supported parent-directory persistence barrier
on Windows. File `fsync` and `os.replace` do not by themselves prove a persisted
directory entry under hardware/power failure. Journal, staging asset, promoted
asset and selected JSON remain separate writes. A matching new journal cannot
acknowledge separate remote submission, Candidate registration or JSON save.
[FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)
documents file/volume flushing; this foundation performs no volume flush or
administrative operation and claims no portable directory-fsync equivalent.

The native owner's narrow ACL observation supports only a verified local fixed
NTFS handle. ReFS, FAT/exFAT, remote shares, mapped drives and unknown filesystems
are unsupported. The path/stat owner has no filesystem verification. Even a
successful native NTFS ACL observation lacks overall protected-storage readiness;
directory durability remains `unsupported`, and execution stays closed.

## Protected Journal lifecycle (C2B-8C-2)

`WindowsProtectedJournalCharacterization.provision_for_characterization` requires
both explicit opt-ins, delegates private-directory creation to the native root
owner, and retains its complete pinned ancestor chain until explicit close.
The host supplies the disposable scope independently. The resulting native root
identity must equal the separately captured `ApprovedRoot`; Journal paths never
construct authority. Only this newly provisioned owner may initialize one private
writer. Its process-local lock serializes operations; exclusive native file
creation still fences competing writers for the same operation.

The ordinary `OfflineJournalWriter` retains its existing public constructor and
default filesystem behavior. Three private I/O methods permit the disposable
subclass to create lock and temporary files with `CREATE_NEW` and the same
protected current-user-only DACL at creation, verify observed file identities,
and release only its acknowledged live lock. Existing file ACLs are never repaired.
The temporary inode and its DACL move to the final Journal name on replacement.
Native tests inspect real lock, temporary and final file security descriptors.

Before and after initialization, append, reopen, inventory and Human Recovery
inspection, the host rechecks the pinned root chain, filesystem and bounded direct
child files. Native file checks reject reparses, multiple links, unsupported DACLs
and changed observed ACLs. They hold handles while inspecting and revalidating the
snapshot; all opened file handles are released afterward so the existing atomic
replacement can proceed. Direct-child inspection is limited to 64 entries and
fails closed above that bound rather than inspecting a partial set as safe.
The initial created-file ACL snapshot is retained before the creation fault seam;
changing it to another otherwise supported owner-only DACL still invalidates the
observation. Post-operation verification also runs when a read or parse fails.

Inside an append, checks surround exclusive lock/temp creation, precede replacement
after file flush/fsync, follow the final reread and surround verified lock release.
The fault seams characterize file creation, pre-replace, post-replace/pre-ACK and
operation-return boundaries. These are bounded observations, not handle-relative
file content I/O or a proof against hostile same-user check/use races. Retained
directory handles fence the tested directory substitutions. No claim of complete
same-user file-writer isolation or continuous ACL protection is made.

Every failed append pins its writer uncertain with no retry. Pre-replace failures
retain old complete bytes, lock and temporary evidence; post-replace failures can
leave complete new bytes and unknown acknowledgment. Failed post-operation
verification withholds the return value and cannot count as a successful write.
No stale-lock takeover, temp cleanup, uncertain-evidence deletion or automatic
replay is performed. Releasing the unchanged lock after an acknowledged live
append is the normal writer operation, not recovery cleanup. File fsync and
replacement do not establish directory/power-loss durability or a transaction
with assets or Project JSON.

Closing native handles invalidates the entire lifecycle. A host may explicitly
reopen an independently selected Journal directory through fresh native root
verification. That owner exposes inspection only and cannot initialize a writer.
Reopened records remain `authenticity=unverified` / `trust=inspect_only`.
Human Recovery returns only its existing bounded projection, not a retained case
or decision owner. An original selected Project root is separately supplied;
missing Projects and incomplete or rolled-back Journals remain inspection
findings. Native protection applies to the Journal directory/files only, not an
independently supplied Project or asset root. This slice does not inspect assets.

ACL snapshots, original producer observations, digest-chain integrity, separately
supplied expected revision/digest, independently authenticated authorship, trusted
latest-head custody and current Project/session authorization remain different
evidence. A digest-valid older prefix is not detectable without an independently
retained expected tip, and even that tip does not authenticate an author.
`execution_available=False`, `protected_storage_available=False` and
`authorship=unverified` remain unchanged. No keys, HMAC, DPAPI, network, worker,
Candidate mutation, Project save, Start or Recovery execution are introduced.

## Adopted product security scope: Profile A

**Profile A: Local Single-User Application is formally adopted as PromptGraph
Pro's supported security scope.** Pro is a locally operated personal Windows
illustration-production application. Public online service deployments are
outside its supported threat model; online self-deployers add and maintain
their own protection. The PromptGraph Lite hosted demo does not expand Pro's
security guarantee. Hostile processes running as the same Windows user,
Administrator/SYSTEM and compromised host code are out of scope.

This process-isolation exclusion does not make LLM/MCP instructions trusted.
LLM/MCP input remains untrusted, with existing agent safety boundaries and
human Start, Recovery and Discard custody preserved. Policy adoption changes
no runtime trust flag. The current owners still report
`execution_available=false`, `protected_storage_available=false` and unverified
authorship; reopened Recovery remains inspect-only. Earlier requirements for
authenticated ownership must be resolved explicitly against the chosen threat
profile, rather than implemented by renaming a digest or ACL observation.

| Question | Profile A: local single-user application | Profile B: process-isolated authorship |
| --- | --- | --- |
| Security boundary | Verified owner-only Windows ACLs constrain ordinary other-user access on supported local storage. | A separately protected signer/key custodian or distinct Windows identity/service must constrain hostile same-user clients as well. |
| Exclusions | Same-user malicious processes, administrators/SYSTEM, compromised host code and hardware failure remain outside the guarantee. ACL checks are bounded snapshots, not continuous file isolation. | Administrator/SYSTEM or compromise of the trusted service/key custodian remains outside any proposed guarantee unless separately designed. Isolation from ordinary same-user processes must be demonstrated. |
| Journal evidence | Schema, hashes and original live producer observations support corruption detection and reconciliation. They do not independently authenticate the author. | Author verification needs an independently pinned verifier identity and protected key custody. A signature identifies an authorized producer, not the truth/completeness of its observations or current action authority. |
| Latest revision | Acknowledged live-writer observations may be the current host tip within the live host/process lifetime. After restart, absent an independently retained host-observed tip, custody is unavailable. Same-user rewriting of both stores remains out of scope. | Latest-head custody must also resist same-user rewrite/rollback, independently of the journal and signing key. A valid old signature alone is insufficient. |
| Operational cost | Native root/file policy, truthful uncertainty, fresh human review, retention and current publication gates are still required. | Also requires installation/IPC authorization, verifier provisioning, service availability, migration, rotation/revocation/loss and restart/head reconciliation policy. |

Profile B is an unsupported optional future deployment design, not a prerequisite
for normal Pro development or supported local use. A future deployment requiring
authenticated authorship against hostile same-user processes needs a separate
Profile B custody and operational review. Profile A adoption grants no production
activation or Recovery permission; authorship remains unverified.

The Profile A latest-head policy accepts bounded acknowledged live-writer
observations as a current host tip within the live host/process lifetime. After
restart, absent an independently retained host-observed tip, latest-head custody
is unavailable. Where/how to retain a restart checkpoint and its intent/ACK order
and uncertainty contract remain unresolved implementation choices. Journal bytes,
a digest-valid prefix or an identical path cannot bootstrap that checkpoint.
Missing/conflicting custody stays inspect-only: no automatic rollback repair,
replay, Recovery association or execution.

Profile B cannot be supplied by a key stored beside the journal, a fabricated
secret, or same-user DPAPI alone. Microsoft's [CryptProtectData example](https://learn.microsoft.com/en-us/windows/win32/SecCrypto/example-c-program-using-cryptprotectdata)
describes the default decrypt boundary as the same user account on the same
machine. The inference for this design is that it does not distinguish two
processes using that account. Windows [security principals](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/understand-security-principals)
provide distinct service/user security contexts; choosing one does not itself
prove safe IPC, signing policy or key isolation. A signing service that signs
arbitrary client bytes would authenticate hostile assertions as readily as
host observations. Producer admission and exact operation binding need review.

For Profile B, key rotation must retain a bounded verifier history and bind each
revision to the admitted producer and key epoch. Loss/revocation, unavailable
service, conflicting heads or an unverifiable migration leave evidence
inspect-only; do not reseal it as a new trusted history. A latest-head design
must define intent/acknowledgment ordering between journal and head, monotonic
update/conflict behavior and service restart. Crashes between those writes leave
an unresolved pair, not permission to select the higher revision or overwrite
either copy. No cryptography, key store or service is implemented here.

## Evidence, authority and process loss

These are independent axes, not levels in a ladder. A future projection should
retain explicit missing/unknown/conflicting states rather than compute one
overall "trusted" boolean. The runtime's `authenticity=unverified` continues to
mean exactly that under the adopted Profile A scope.

| Axis / current owner | Current observation and limitation | After process loss | Prerequisite for a future effect |
| --- | --- | --- | --- |
| Root ACL and file identity / native storage | Pinned handles, local NTFS, modeled owner-only DACLs and before/after identity checks; no hostile same-user content-I/O proof. | Bytes/ACLs may remain; handles and original live observation do not. Fresh native verification must compare independently selected roots and retained provenance, not recapture journal-supplied authority. | Separately approved Journal, staging, promoted-asset and Project scopes; fresh file/ancestor checks at use. Journal protection does not protect asset roots. |
| Schema/revision/digest / Journal | Strict complete chain and bounded correlation checks detect malformed/inconsistent bytes. | Surviving bytes can be revalidated; a valid prefix/recomputed chain can still pass. | Complete necessary evidence and current integrity; never a claim or permission. |
| Original producer / live writer | Exact live owner, expected predecessor and acknowledged append are observations. Process/session IDs in reopened records are assertions. | Owner object, lock custody and knowledge of acknowledgment do not survive. A retained lock is evidence, not a transferable lease. | Host-owned lineage under approved profile; no reconstruction of the old writer/claim. |
| Latest-head custody | Bounded acknowledged live-writer observations may supply the current host tip. No restart checkpoint custodian is implemented; `expected_revision/digest` only compares a supplied tip. | Absent an independently retained host-observed tip, latest-head custody is unavailable; checkpoint retention/order/uncertainty contracts remain unresolved. | Missing/conflicting custody permits inspection only. Never derive the expected tip from the journal being checked or an identical path. |
| Authenticated authorship | Unverified; SHA-256/ACL/file identity are not a signature. | Nothing can upgrade authorship on reopen. Profile B would require surviving independently protected verification/custody evidence. | Adopted Profile A limitations apply; optional future Profile B verification is separate. Neither authorizes an action. |
| Original Project/source/review provenance | Journal correlations and saved JSON are inspectable evidence. Source/review fingerprints cannot establish their own trusted origin. | Files may survive; original Project object, exact source/review carrier and approval custody do not. | Independently verified original lineage, explicit unique Illustration targets, source/Scene/Module state and exact reviewed evidence. Changed/missing lineage blocks Recovery association. |
| Fresh session/activation/pairing/human review | RecoveryContext strings and review intentions are observations; no current capability. | Session, activation epoch, pairing generation, ACK and pending intention are not restored from disk. | A new exact host context and explicit human action under the future Recovery contract; switching back never revives old authority. |
| Candidate publication/save | Current JSON may show exact/partial/absent/conflicting association; callback and persistence outcome remain separate. | Saved bytes may remain; appender/publisher one-shot indexes and runtime attempts do not. | New host-only publication/save custody, idempotent reconciliation and immediate stale gate. Exact saved Candidates are not appended again. |
| Retention/discard | Inventory and counters are bounded; ownership, saved-reference and external-operation completeness can be unknown. | Files and unresolved observations may remain; no deletion approval survives. | Independent explicit discard authorization plus complete ownership/reference checks. Association approval does not grant discard or vice versa. |

## Rollback, rewrite and failure interpretation

The distinction below applies within the adopted scope; it is not a new classifier.
Existing [Journal](agent-generation-ownership-journal.md) and
[Human Recovery](agent-generation-human-recovery.md) states remain authoritative.

| Scenario | Detectable observation / limit | Required interpretation |
| --- | --- | --- |
| Malformed JSON, missing middle revision, wrong digest or request correlation | Existing bounded schema/chain checks reject it. | Detectable inconsistency; retain evidence, no reconstruction or retry. |
| Digest-valid older prefix | Detectable only against an independently retained expected tip. With no tip, it is indistinguishable from a journal that stopped there. | Latest-state/completeness unknown; no inference of unsent requests or absent later effects. |
| Same-user rewrite with recomputed digests | Can pass schema, chain and owner-only ACL observations. A rewritten same-user tip store can also agree. | Indistinguishable authorship attack under Profile A and outside its supported guarantee. Optional future Profile B must protect both producer and latest-head custody. |
| Missing latest head | There is no independent evidence that the observed revision is latest. File timestamps, IDs, directory order and largest revision do not supply it. | Inspect-only freshness uncertainty; no reset/new-tip bootstrap from these bytes. |
| Interruption before/after replacement or post-write verification failure | Old or new readable bytes, lock/temp evidence, unknown acknowledgment; actual file observations are testable. | Writer remains uncertain, no replay/takeover/automatic cleanup. New bytes do not prove acknowledged persistence or any external effect. |
| Uncertain remote submission | Intent or accepted prompt evidence may exist without definitive result; local expiry is not remote cancellation. | Keep unresolved ownership; no automatic resubmission. Inspect remote evidence only through a separately approved future transport. |
| Partial Candidate publication | Current saved JSON can show exact subset, conflict or no persisted memory delta. | Preserve per-output association and save uncertainty; never replay the whole batch. Exact members are not attached twice. |
| Failed/uncertain Project save | A matching saved Candidate or JSON digest can coexist with unknown callback outcome. | Report both observations; no upgrade of callback/authorship, attachment, retry or deletion authority. |
| Changed/missing Project or duplicate/missing Illustration | Exact selected-root/path and unique stable-ID reconciliation can detect it within the inspected scope. | No active/current Project fallback or silent target remap. Intentional remapping would be a separate reviewed operation. |
| Missing/tampered promoted assets | Bounded identity/size/hash/decode inventory detects inspected differences; uninspected entries remain unknown. | Withhold association. A matching Candidate record does not repair, authenticate or authorize disposal of the asset. |

Repository characterization supporting these distinctions includes
`test_digest_valid_same_user_rewrite_and_rollback_remain_inspect_only` in
`tests/test_generation_protected_storage.py`,
`test_native_reopen_incomplete_rollback_and_missing_project` in
`tests/test_generation_protected_journal.py`, and
`test_save_uncertainty_does_not_upgrade_from_matching_candidate` in
`tests/test_agent_generation_human_recovery.py`. These are existing tests,
not new execution or power-loss observations made by this design slice.

## Production decision matrix and next bounded slice

**Current overall result: no-go for production Generation and executable
Recovery under adopted Profile A.** Profile B key/service infrastructure is not
a prerequisite for supported local use. Categories below distinguish a human decision
(D), required implementation (I), required Windows/operational validation (V)
and an unsupported guarantee (U). Completing one row does not clear the rest.

| Gate | Category | Action required before go |
| --- | --- | --- |
| Journal lifecycle | I, V | Integrate bounded intent-before-effect/observed-outcome recording, exclusive writer retirement and truthful unknown states; disposable C2B-8C-2 alone is insufficient. |
| Protected roots and assets | I, V | Approve/provision production scopes and native Journal, staging, promoted-file and original Project use; validate ACL/identity/reparse behavior throughout. Never repair existing Project ACLs implicitly. |
| Threat scope/authorship | A adopted; B optional U | Apply Profile A's local-use exclusions; authorship stays unverified. Independent producer/key/service custody belongs only to an optional future Profile B design. |
| Latest-head implementation | I, V | Implement the adopted live-tip/missing-restart-tip policy. Decide checkpoint retention and ordering/uncertainty contracts; missing/conflicting custody permits inspection only. Same-user-resistant custody is U under A. |
| Crash/durability | D, I, V; current guarantees U | Approve supported filesystem and unknown-outcome policy, characterize restart ordering and any chosen durability barrier. File fsync/replacement supplies no power-loss or cross-file transaction guarantee. |
| Recovery and retention | D, I, V | Review separate human association/discard authorization, source/review provenance, Project integrity, Candidate idempotence, quotas/reference completeness and original-host publication/save uncertainty. Current intentions grant nothing. |
| Transport, worker and Human Start | I, V | Review truthful bounded real transport, one-shot worker/host event lifecycle, loss/shutdown and exact fresh human Start; policy adoption cannot enable them. |
| Operational validation | D, V | Separately authorize disposable real ComfyUI/Project restart/failure/capacity exercises only after implementation gates. Fake/offline success is not activation approval. |

**C2B-8C-3 recommendation, implemented by the C2B-8C-4 slice below:** a bounded offline trust-evidence inspection projection
composing the existing native Journal and Human Recovery observations. Expose
separate root/file, chain, observed-producer, expected-tip provenance/lifetime,
source/review and current-context states with fixed redacted reasons. A supplied
tip must remain explicitly host-supplied observational context; the slice must
not implement a trusted head store or claim authenticated authorship. Exercise
valid prefix/rewrite, missing tip, closed handles, changed source and conflicting
evidence; keep every permission false and Recovery inspect-only. This can make
the decision matrix visible and testable without granting runtime authority,
adding keys/services, reconstructing a claim or performing an effect.

## Validation and remaining production gates

Focused disposable tests cover explicit/unapproved/overlapping purposes, Windows
and non-Windows fail-closed status, redaction, scope/root/file substitutions,
symlink/reparse ancestor/file observations, actual hardlinks, unsafe/inherited
principals, modeled/unmodeled ACLs, fsync failure, old/new file interruptions,
ambiguous acknowledgment, digest-valid forgery, rollback and Human Recovery
inspect-only behavior. True native Windows tests separately cover atomic secured
private-journal creation, same-handle descriptor/identity inspection, read-only
existing-root inspection, fully protected nested directory/JSON inspection,
live scope/intermediate/root rename refusal, writable intermediate principals,
inheritance/unsupported ACEs, and intermediate ACL changes during capture or
readiness (including changed owner-only snapshots). They also cover actual Everyone
and inheritance ACL changes, unsupported/mapped filesystems, absent dependencies,
unapproved paths and retained evidence after post-creation interruption.
Synthetic ACL/reparse samples are distinguished from these native tests. The
existing publication symlink test may skip when Windows disallows symlink creation;
no successful native junction or general hostile-race guarantee is inferred.

Before production activation, separately review and integrate protected-root
ownership for journal/containment/promotion, approved scope provisioning and
child-file ACL propagation; expand native substitution/ACE/race validation in
the locked Windows environment and define supported long-lived handle lifecycles;
establish an explicit file/replacement/directory durability policy; implement
latest-head custody within adopted Profile A's scope; and establish fresh human
recovery authorization. Quota/retention, approved cleanup, real transport,
worker lifecycle, Human Start and original-host publication/save gates from
C2B-7 still apply. This characterization grants none of them.

## C2B-8C-4: bounded trust-evidence inspection projection

`ui.agent_generation_trust_evidence.inspect_trust_evidence_for_characterization`
composes the existing Journal and Human Recovery owners over explicitly supplied
`ApprovedRoot` objects. It requires characterization opt-in and never derives a
root from Journal text. The portable entry point reports native ACL/root evidence
as `not_inspected`. For real disposable Windows inspection,
`WindowsProtectedJournalCharacterization.inspect_trust_evidence_for_characterization`
uses its already opted-in retained native handles and existing before/after
root, intermediate-directory and direct-child ACL checks. Failed checks,
including after-read drift or closed handles, withhold the Recovery case and
report a fixed unavailable state.

The detached `promptgraph.generation-trust-evidence.v1` result has a 64 KiB
serialized bound. The nested Recovery representation retains existing 100-request
and 64-image bounds and fixed diagnostic reasons. An overgrown combined result
withholds the case; it never truncates a case into apparently complete evidence.
No paths, SIDs, prompts, credentials, raw digests, or private correlation IDs
are displayed. It exposes separate root/ACL, file observation, chain validity,
checkpoint coverage, producer, expected tip, authorship, original Project,
source/review, session/activation/pairing, Candidate association, save, external
submission, inventory and retention axes. It offers no generic trusted/safe flag.

A complete supplied revision/digest pair is comparative context only. States
include no expected tip, matches, conflicts, `behind_supplied_tip`, and unavailable
observed tip. The supplied tip's provenance and custody remain unverified even
when bytes match; a lower observed revision cannot alone prove an actual rollback.
A digest-valid same-user rewrite without a comparator also remains unauthenticated.
No persistent head store or automatic repair is added. A matching native retained
writer operation/revision/digest/file identity is labeled a live acknowledged
snapshot observation; reopening without that writer supplies only a reopened
assertion. Neither authenticates a producer. Policy permits the acknowledged
live snapshot as a bounded current host tip; this projection does not establish
independent restart latest-head custody.

Source/review digests in the Journal are `recorded_unverified`; independent
source/review comparisons are explicitly unavailable. This projection does not
accept caller flags asserting fresh source, review or session state. A changed
selected saved Project can be observed by the existing Recovery owner, while
independent live source/review drift requires a later reviewed host observation
interface. Stored session/process identifiers never confer current authority.
The current session is missing, activation/pairing unavailable and runtime
authorization absent. Candidate matches and saved-byte observations remain
separate from save uncertainty, authorship and fresh human authorization.

Focused portable and actual native Windows fixtures cover unverified matching
tips, valid prefixes and resealed source/review changes, invalid/missing Journals,
missing/changed Projects, partial Candidates, uncertain save/remote submission,
truncated inventory, detached/redacted/bounded output, forged-parameter refusal,
closed handles and pre/post-read root/file ACL drift. Byte comparisons and guarded
write/deletion/network APIs check read-only behavior. Runtime integration,
Generation/Recovery execution, Candidate publication and save remain disabled:
`execution_available=false`, `protected_storage_available=false`,
`authorship=unverified`, and Recovery inspect-only.

**Next bounded engineering work:** review the protected asset owner integration
boundary below, then offline contracts for real transport (origin/authentication,
redirects, deadlines, bounded result/download evidence and truthful unknown
outcomes). Review source/review/session comparison and restart-checkpoint
retention/order/uncertainty contracts as separate bounded owners. Speculative
Profile B keys/services are not prerequisites. None of these plans activates
execution, persistent tip custody, publication or cleanup; the remaining
production go/no-go gates above still apply.

## C2B-8D-1: disposable protected staging and promoted assets

`core.generation_windows_protected_assets.WindowsProtectedAssetsCharacterization`
is a separate offline owner for `temporary_containment` and `promoted_assets`.
The host explicitly opts into an existing disposable owner-only scope. Native
provisioning exclusively creates two host UUID directories with protected
owner-only DACLs at creation. Independently selected host-provisioned directories
can instead be reopened for inspection only. Overlap, aliasing and out-of-scope
paths are refused. No root authority comes from Journal or ComfyUI metadata.
No existing Project/user directory ACL is repaired. Private Journal provisioning,
writer receipts and latest-head ownership are unchanged.

The existing native root owner pins the complete path chain without delete
sharing, verifies fixed local NTFS and file identity, rejects reparse points,
and compares the initial owner-only protected DACL snapshots of every in-scope
ancestor and root. The asset owner retains its native file handles and initial
file identity/DACL snapshots before callbacks or writes. Each file is exclusively
created with a host UUID and supported image extension and a protected owner-only
DACL. Native writes, flush, bounded reads, Pillow verification/decode and SHA-256
comparisons precede a private `ProtectedImageObservation`. Initial ACL snapshots
are compared at lifecycle boundaries; another valid owner-only ACL also invalidates
the observation. File snapshots include the complete native owner/DACL descriptor bytes,
so changed ACL revision/control bytes cannot pass merely by retaining equal ACEs.
An observed identity/ACL failure permanently invalidates this
owner, even if a fixture later restores the original ACL. Closing handles invalidates
the observations. Changes made and restored between inspections are not proven
detectable; Profile A excludes hostile same-user processes.

The existing containment image limits apply: encoded image/request/aggregate
bytes, image count, dimensions and pixels can only be reduced. Inventory and
read sizes are bounded. Failed writes reserve capacity and retain all created
files; unknown existing entries, invalid/incomplete images and uncertain outcomes
never trigger deletion, overwrite, retry or automatic recovery. A successful
flush/read proves only currently observed bytes, not directory or power-loss
durability or a cross-file transaction. Evidence files and root directories survive
close and failed allocation. A fresh reopen supplies new inspect-only observations;
it cannot validate an old observation or reconstruct a writable owner. Invalid
inventory withholds the complete result and retains the files.

### Integration boundary and remaining gates

This owner supplies neither `LocalOutputReceipt` nor `PromotedImage` and has no
production call site. C2B-8D-5 below adds an explicit offline stream observation
into staging; copy/promotion between roots remains unavailable.
`ContainedOutputStore` still allocates under OS temporary storage;
`DurableGenerationAssets` still creates a directory under its approved parent.
Those constructors have not acquired native-protected semantics. The existing
containment image verifier is reused; the byte-create API records no request
receipt. Native observation of image/root bytes never confers Candidate publication
authority.

A future bounded integration must connect these offline observations to the
complete containment receipt and durable-copy boundaries while preserving exact
accepted-envelope/remote/local receipt custody, one-attempt behavior,
original-host freshness and publication/save ordering. It must separately define
the handle lifetime across original-host shutdown and Recovery, aggregate retained
evidence accounting and human-approved retention/discard. Host scope provisioning,
latest-head custody, current human authorization, transport, worker and Human Start
remain separate production gates. Profile A is adopted; no Profile B signing,
keys or services were added. All current authorization gates still apply to
LLM/MCP instructions. `execution_available=false`,
`protected_storage_available=false`, `authorship=unverified`, Recovery inspect-only,
and Candidate attachment/publication, Project save and cleanup remain disabled.

### Native characterization evidence

Disposable tests on Windows 11 build 26200 exercise real `CreateDirectory`,
`CreateFile(CREATE_NEW)`, `GetSecurityInfo`, `SetSecurityInfo`, handle identity,
native read/write/flush and rename refusal for root/scope/file handles. They cover
both asset purposes, protected creation, fully protected nested host-provisioned
roots reopened without ACL changes, changed owner-only/writable/inherited
file/root ACLs, unsafe scope/intermediate ACLs, retained interrupted or invalid
files, closed handles and fresh inspect-only reopen. A real disposable NTFS
junction created with `mklink /J` is refused; actual hardlinks are refused.
Interruption callbacks, unavailable dependency/platform/filesystem observations
and deterministic UUID collisions are explicitly injected tests, not actual
crash, non-NTFS-volume or hostile-race observations. The runtime and exact focused
commands/results are recorded with the PR. No ComfyUI network transport ran.

## C2B-8D-5: offline protected staging stream bridge

`stage_remote_image_for_characterization` explicitly composes the existing
`DownloadStream` provider with an already provisioned, writable disposable
Windows asset owner. It accepts the original host-issued `FrozenPromptRequest`,
exact envelope and `RemoteOutputReceipt`, and an exact descriptor object from
that receipt. Preparation provenance and the complete original history are
revalidated before any native allocation or callback. Explicit successful
execution is required; status-less metadata and a replaced success summary
cannot authorize a transfer. The first accepted attempt pins the exact envelope,
prepared request and receipt objects. Copies, substituted bindings and repeated
request/descriptor attempts are refused before invoking the provider.

Only `temporary_containment` receives stream bytes. Remote paths never enter the
local destination: a host UUID name is exclusively allocated with
`CreateFile(CREATE_NEW)` and the native owner-only protected DACL supplied at
creation. The original root/file handles, identity and DACL observations are
retained before the first external callback. Failed initial file observation
retains the new file and handle and permanently fences the owner. Root/file
validation brackets provider/read/close callbacks, writes, flush and stored-byte
reads. Observed ACL/identity loss permanently invalidates the owner, even if the
original descriptor is later restored. Existing byte-create behavior remains
available outside a stream attempt; callback reentry cannot start a second
stream or a concurrent byte-create operation.

The trusted original host supplies `host_freshness(envelope, remote)` with those
exact objects. Its return must be literal `True`; exceptions or stale context
fail closed. It runs before allocation, before and after each remote operation,
and after stored-byte verification. These callbacks run outside the asset
reservation lock. This bridge supplies no current-session/job freshness owner
itself, and no application call site installs a permissive callback by default.
Lost freshness withholds the observation and retains evidence. An acquired stream
is closed once even when a native/freshness pre-check fails; failed close cannot
produce verified evidence. Provider/read/close errors expose fixed bounded
failure codes rather than callback exception text.

Reads request at most 64 KiB and write each accepted chunk natively before the
next read; there is no download prebuffer or OS-temp staging file. Positive
integer declared length, actual byte count, exact EOF, image count and reduced
image/request/aggregate limits are enforced. One extra byte is requested to
detect an overrun. Declared body bytes are reserved before writes, so partial or
ambiguous write failures cannot release capacity or permit retry. Readiness
reports retained file count and byte reservation; fresh inspect-only inventory
also accounts for observed sizes, including rejected bytes. Failed attempts
make the owner permanently uncertain for further writes. Files, including empty,
partial, malformed, stale or uncertain files, survive failure and close.

Only exact-length completion, successful stream close, native flush, bounded
stored-byte reread, existing Pillow verification/full decode and stored-vs-stream
SHA-256 equality produce a `VerifiedProtectedImageObservation`. Extensions are
checked against decoded image format; extension and Content-Type do not establish
validity. This separate type contains exact remote correlation and a private
`ProtectedImageObservation`. It is neither a `LocalOutputReceipt` nor a
`PromotedImage`, does not implement their acceptance interfaces, and causes no
executor count event, Candidate, Project save, Journal or MCP operation. A fresh
reopen produces only new inspect-only byte observations; it cannot restore remote
correlation, old observations, retries or writable authority.

### C2B-8D-6: protected batch receipt custody

`commit_verified_remote_image_batch_for_characterization` adds one immutable,
owner-held `VerifiedProtectedImageBatchReceipt` for one exact host-prepared
request and its original successful `RemoteOutputReceipt`. The caller must supply
the complete descriptor set as exact `VerifiedProtectedImageObservation`
instances issued by the same owner. Missing, duplicate, extra, copied or
substituted observations are rejected. The original host-freshness callback
runs before verification and again after the potentially slow native file
identity, ACL, stored-byte reread and decoded-byte checks. Both callbacks run
outside the owner lock. Publication then performs a guarded final owner check
under that lock, serializing against close; close winning first prevents the
receipt, while a committed receipt is invalidated for further inspection by
subsequent close.

The receipt records only the bounded request/remote correlation, a deterministic
content identity and the canonical descriptor-ordered observation tuple. Exact
object custody is retained in the issuing owner; copies and receipts from a
reopened owner cannot be inspected as its receipt. A failed first batch attempt
retains all staged evidence, publishes no batch, marks the owner uncertain and
permits no retry or cleanup. A duplicate call after successful commit is
rejected without invalidating the original receipt. This owner remains
characterization-only and is not registered with an executor or
`ContainedOutputStore`; it does not synthesize a `LocalOutputReceipt`, advance
execution counts, promote assets, publish Candidates, save Projects, mutate a
Journal or authorize Recovery.

This batch boundary covers all descriptors for one request, not an atomic
transaction across requests or filesystem state. It does not establish
power-loss durability, same-user hostile-process isolation, or cryptographic
authorship. The existing `execution_available=false`,
`protected_storage_available=false` and `authorship=unverified` gates remain in
force. A later integration must define an explicit owner and acceptance contract
between these private observations and existing containment/publication owners;
it must not bypass `ContainedOutputStore` by treating this receipt as its input.

### C2B-8D-7: protected containment acceptance

`ProtectedOutputAcceptanceCharacterization` is a separate offline
containment-side owner for one exact batch. Creation requires explicit
characterization and disposable opt-in. Acceptance is one-shot and requires the
original `WindowsProtectedAssetsCharacterization` issuer, exact envelope,
owner-prepared request, successful remote receipt, and exact issued
`VerifiedProtectedImageBatchReceipt`. The issuing owner retains and checks the
same host-freshness callback used to commit that batch. It rechecks the full
descriptor-ordered batch, current native handles, file identity, ACL and stored
image bytes, then checks original-host freshness again before committing
acceptance under the protected owner's lock. Publication of the protected and
acceptance-owner records is serialized under both locks in protected-owner →
acceptance-owner order. Close or invalidation that wins before this joint
commit withholds acceptance. If the joint commit wins first, a later close or
invalidation fences further inspection without reclassifying the committed
acceptance as uncertain, while retaining all evidence.

The result is the distinct immutable `AcceptedProtectedOutputBatch`. It retains
private references to the exact issuer, envelope, prepared request, remote
receipt, batch receipt and host-freshness callback. Copied receipts, substituted
bindings, incomplete batches, callback substitution, stale host state, native
content/ACL drift, repeated acceptance, and cross-owner evidence fail closed.
Accepted results are inspectable only through that same acceptance owner while
the original protected owner and host binding remain current. Failures do not
retry, clean up, overwrite or discard retained evidence.

This is acceptance evidence only. It is not `LocalOutputReceipt`, does not
populate `ContainedOutputStore` or its private indexes, does not grant executor
progress, does not move bytes into `promoted_assets`, and does not authorize
Candidate or Project publication. The separate [C2B-8D-8 protected durable
promotion](#c2b-8d-8-protected-durable-promotion) below copies this exact accepted
batch into the already provisioned protected root and issues distinct
owner-held evidence. Promotion, executor settlement, publication approval and
save remain distinct authority steps. `execution_available=false`,
`protected_storage_available=false`, `authorship=unverified`, Human Start,
Recovery execution, Candidate/Project/Journal mutation and cleanup remain
disabled.

### C2B-8D-8: protected durable promotion

`ProtectedDurablePromotionCharacterization` accepts only the exact
`AcceptedProtectedOutputBatch` retained by its original
`ProtectedOutputAcceptanceCharacterization` and the same
`WindowsProtectedAssetsCharacterization` that issued the staging observations.
It binds the original host envelope, prepared request, successful remote
receipt, complete descriptor-ordered batch and original host-freshness callback.
Copied/substituted acceptances, another acceptance owner, another protected
owner, incomplete or reordered image correlation, and stale or invalidated
acceptance fail closed.

Promotion is a one-shot offline copy into that protected owner's already
provisioned `promoted_assets` root. The owner preserves each source staging
file, revalidates accepted source identities, native owner-only ACL snapshots,
stored byte counts and SHA-256 values, and preflights the shared conservative
image/byte limits. Destinations use the existing native `CREATE_NEW` file path
with a protected owner-only DACL. The native destination handle, file identity
and ACL snapshot are retained immediately at creation. Before success, the
owner rereads and fully decodes every destination, and checks format, dimensions,
byte count and SHA-256 against its source. Remote filenames and caller-selected
paths never choose a destination.

The immutable `VerifiedProtectedPromotionReceipt` and its
`ProtectedPromotedImage` rows are a separate private contract. Each ordered row
binds one exact remote descriptor, original staging observation and new
protected `promoted_assets` observation. The receipt is jointly published to
the promotion owner and original protected owner only after the complete copy
and final source/host/native checks. Publication is serialized against
protected-owner close and acceptance close/invalidation under the existing
protected-owner → acceptance-owner lock order. Host-freshness callbacks run
outside both locks. A close or invalidation before the joint commit prevents the
receipt; one after commit fences later inspection but does not rewrite the
committed result.

The receipt is not legacy `PromotedImage` or `DurableGenerationAssets` custody.
It cannot be passed to Candidate publication, does not by itself advance
executor progress, does not populate `ContainedOutputStore`, and authorizes no
Project save, Journal mutation or Recovery. The separate C2B-8D-9 bridge below
can emit one count-only host event after revalidating this receipt; that event
still grants none of those authorities. There is no restart-time adoption,
overwrite, retry or cleanup. If a copy or final validation fails, any created
destination files and handles remain as partial/uncertain evidence, no batch
receipt is published, and the attempt cannot be repeated. Capacity accounts for
staging and promoted files together under the existing conservative limits, so
a known over-capacity batch is rejected before copying; write or later
verification failures can still retain partial destinations.

This characterization verifies native file identity, ACL and byte integrity at
the observed checks. It does not establish same-user hostile-process isolation,
cryptographic authorship, directory or power-loss durability, or atomicity across
files. Reads and Pillow decoding retain the existing bounded size policy but are
not constant-memory. Reopening storage is inspect-only and cannot reconstruct
the promotion owner or its authority. `execution_available=false`,
`protected_storage_available=false`, `promotion_available=false`, and
`authorship=unverified` remain in force.

### C2B-8D-9: protected promotion to executor outputs-ready event

`ComfyExecutorAdapter.accept_protected_promotion_for_characterization` is the
explicit offline bridge from a `VerifiedProtectedPromotionReceipt` to the
existing `ExecutorEvent(kind="outputs_ready")`. It accepts only the exact
receipt held by its issuing `ProtectedDurablePromotionCharacterization` and
checks that the receipt still binds the adapter's active envelope, the exact
host-prepared request, accepted successful `RemoteOutputReceipt`, request
index, prompt UUID, workflow identity and complete descriptor count/order.
The promotion owner then re-inspects the full promoted batch, including its
current native handles, identities, ACLs, stored bytes, original accepted
batch and original-host freshness. The adapter performs the host-local
freshness gate and confirms the job still awaits download immediately before
emitting. These callbacks and native checks run outside job/inbox locks and
protected-owner locks; the existing event sink retains its target, pairing,
sequence, one-shot and job-before-inbox checks.

After that inspection, the issuing promotion owner establishes a separate
one-shot event-dispatch lease while checking the live protected → acceptance →
promotion owner chain under its normal lock order. This lease is the event
commit point. Owner locks are released before the host callback. Close or
invalidation first prevents new leases and revokes the dispatch boundary; if a
lease already committed, revocation waits for that callback to return before
completing. Thus revocation that wins before the commit point fences the event,
while an already committed event is ordered before completed revocation. The
lease does not make a rejected or uncertain callback retryable.
If that callback synchronously attempts to close or invalidate one of these
owners on the dispatch thread, the terminal call is refused before lifecycle
flags change; revocation from another thread still waits for the committed
callback to return.

The event carries only the image count and a truncated opaque promotion
identity for correlation. That identifier is not custody authority, and the
protected promotion receipt is never converted into `LocalOutputReceipt`,
`OutputReceipt` custody, `PromotedImage` or `ContainedOutputStore` state. One
attempt is retained per request. A copied, cross-owner, stale, late, invalidated
or uncertain attempt, including a rejected or ambiguous event-sink result,
cannot be automatically retried or used to emit a second successful event.
The registry transition ends at `awaiting_host_registration`; no Candidate
append, publication settlement or Project save occurs. A later explicit host
publication result and save remain separate owners, as do real transport,
production worker registration, Human Start, Journal and Recovery.

This boundary characterizes the event handoff only. It does not make protected
storage or executor production-ready: `execution_available=false`,
`protected_storage_available=false`, `promotion_available=false`, and
`authorship=unverified` remain in force. Closing or invalidating custody before
the event's host checks fences the event; if event delivery is uncertain, the
attempt and protected evidence remain retained rather than resent. The event
does not claim Candidate registration count, Project save, durable recovery or
cryptographic authorship.

### C2B-8D-10: original-host Candidate publication admission observation

`GenerationProtectedCandidateAdmission` is a separate one-shot, offline owner
for asking whether one exact `VerifiedProtectedPromotionReceipt` is currently
eligible to enter the original-host Candidate publication process. It is
pinned to the runtime's exact `GenerationPublicationOrigin` and accepted
envelope. Admission also requires the exact issuing promotion owner, exact
promotion receipt and original successful remote receipt, plus the complete
ordered descriptor set and exact active prepared request.

Before issuing its immutable private `ProtectedCandidateAdmissionObservation`,
the owner revalidates the full native promotion through its issuer and checks
the exact original Project object/path/source snapshot, session and process,
activation/target epoch, current pairing generation, job/claim/manifest,
request index and the single accepted `outputs_ready` event. The event's
truncated promotion identity is only a correlation value: the promotion owner
must still retain the exact receipt object and full protected custody chain.
Both the corresponding `remote_outputs_ready` and `outputs_ready` event records
must remain present and consistent with job event history and ordered counts.
Missing, duplicate, conflicting, stale, copied, substituted, cross-owner or
uncertain evidence is refused. Native file work and original-host callbacks run
outside the job/inbox and protected-owner locks. A bounded final host check
holds the original publication gate, route operation lock, protected →
acceptance → promotion locks, then job → inbox locks while issuing the
observation; no external callback or native I/O runs in that commit section.

The admission owner does not append Candidates, mutate Undo history, settle the
job's publication count, call an appender, or save a Project. The result is
eligibility evidence only, not approval or a reusable capability. It does not
convert protected receipts into `LocalOutputReceipt`, `ContainedOutputStore`
custody or legacy `PromotedImage`. Failed or uncertain one-shot attempts retain
their exact evidence and cannot be retried automatically; close fences further
observation without deleting files or receipts.

The next separate boundary must decide whether and how this observation enters
the existing single Candidate writer while preserving that writer's strict
legacy receipt validation, exact original-host authority, Undo ordering and
save uncertainty behavior. No parallel Project mutation path is implied.
Production remains disabled: `execution_available=false`,
`protected_storage_available=false`, `promotion_available=false`,
`candidate_publication_allowed=false`, and `authorship=unverified`. This
characterization does not prove hostile same-user process isolation,
cryptographic authorship, restart-time authority reconstruction, crash
durability, or hostile mutation between bounded checks.

### C2B-8D-11: protected Candidate writer integration

`GenerationCandidatePublication` remains the single Candidate writer. Its
protected characterization mode accepts only the exact
`ProtectedCandidateAdmissionObservation` retained by the original admission
owner and the exact promotion/acceptance owners that issued the evidence. It
does not translate protected evidence into `LocalOutputReceipt`,
`PromotedImage`, or `DurableGenerationAssets`, and the legacy writer path keeps
its existing receipt checks. Before Candidate mutation, the publisher
revalidates the active prepared request, original host/event authority, exact
admission and promotion custody, native promoted-file identity/ACL/content,
and request/descriptor correlation. A bounded private lease serializes final
publication against protected-owner close and invalidation; expensive native
verification and host callbacks remain outside protected, job and inbox locks.

The protected image destination is derived only from the retained protected
assets owner. The pinned `promoted_assets` root must be a strict descendant of
the exact frozen `output_directory` approved by the original host, and each
promoted image must be a direct child of that root. Missing roots, an equal or
outside root, path substitution, or any unapproved destination fail closed.
Existing app ingestion and the original-host Candidate appender remain the
only mutation path. The writer records the actual persistent Candidate delta,
uses the existing Undo ordering, and settles the exact request's registration
count once. Protected provenance identifies the promotion/admission and
verified image bytes without claiming a legacy local receipt. Candidate
registration remains distinct from Project save; this C2B-8D-11 step performs
no save. C2B-8D-12 adds a separate exact original-host save decision after
successful registration. If an appender raises after leaving a provable
subset, the first request remains `registration_uncertain` and cannot be
replayed. Admission advances its
comparison baseline only when the complete original Project matches the prior
baseline plus exactly that observed Candidate subset; this can admit a later
distinct request while preserving the job's `partially_failed` state and
blocked save outcome.

This boundary does not authorize production execution or protected storage,
does not add retry, cleanup, restart-time authority reconstruction, Journal or
Recovery behavior, and does not prove protection from hostile same-user
processes, transient path/ACL races, crash durability or cryptographic
authorship. `execution_available=false`,
`protected_storage_available=false`, `promotion_available=false`, and
`authorship=unverified` remain in force. See the [Candidate publication
contract](agent-generation-candidate-publication.md#protected-candidate-admission-is-not-candidate-publication)
for the shared writer boundary and persistence separation.

### C2B-8D-12: protected Candidate JSON persistence

Protected JSON persistence is a characterization-only extension of the same
`GenerationCandidatePublication` owner and its original app save callback. It
does not register another Candidate writer or Project serializer. Save requires
all requests to be settled, and every output-producing request to have exactly
one successful Candidate registration receipt whose count matches the job,
the exact event pair retained by the original publisher, admission observation,
promotion receipt and complete ordered descriptor set. The bounded job/inbox
event logs are diagnostic histories and may evict older entries; save allows
their absence only while the publisher's private per-request pair remains
exact and any surviving entry agrees. Missing or changed private proof,
conflicting surviving events, and observed late outputs block save. A sticky
inbox marker preserves late-output refusal even after bounded late-event detail
is evicted. A definitive failed request with no outputs may remain in a
`partially_failed` job. Missing evidence, partial registration, or any
`registration_uncertain` result blocks save even when later requests completed.

At save time, the issuing promotion owner revalidates accepted staging and
promoted files, native identities, DACLs, bytes, approved destination, pinned
promoted root, exact Candidate paths and recorded provenance. A distinct
read-only save-time host verifier checks settled job state and the exact
`remote_outputs_ready` / `outputs_ready` event pair captured by the publisher
at successful registration; it does not require those entries to remain in
bounded diagnostic logs and does not reuse admission's pre-registration
`awaiting_host_registration` check. The original Project
object/path/source snapshot, session/process, activation/epoch, pairing and
publisher ownership remain bound. The established `save_agent_scene_module_swap_project`
callback continues to call `core.io.save_project_to_json` on that exact object
and path. Expected serializer normalization is computed on a detached Project
before the callback.

Each promotion owner issues a separate one-shot save lease. Asset, acceptance
and promotion close/invalidation cannot complete across an active save callback;
the callback itself runs without native, protected-owner, admission, job or
inbox locks. Protected files and original-host evidence are rechecked after a
possible write. If the callback's result, current host or protected evidence is
uncertain, the save is retained as `save_uncertain`; a known callback outcome is
kept privately. No retry, rollback, Candidate replay or cleanup occurs. A
callback returning false is `save_failed` only when post-checks still establish
the original host and protected custody.

This contract does not establish crash/power-loss durability, cross-file
atomicity, restart-time authority reconstruction, cryptographic authorship,
hostile same-user process isolation, or detection of transient mutations
restored between checks. Retained JSON and protected images after uncertainty do
not authorize Recovery or publication. The gates remain
`execution_available=false`, `protected_storage_available=false`,
`promotion_available=false`, and `authorship=unverified`.

### Observed evidence and unresolved guarantees

Portable refusal contracts and actual disposable Windows-native fixtures cover
PNG/JPEG/WebP/BMP, exact correlation and issuance, DACL/identity at creation and
rename refusal, incremental writes, short/extra/oversized/nonbyte/malformed
streams, interruption/timeout/close failure, native write/flush failure, ACL and
identity drift, freshness loss around callbacks, retained evidence, one-attempt
reentry, host-name collision and fresh inspect-only reopen. Offline composition
uses `PromptHTTPViewTransport` with an injected wire and misleading Content-Type;
the HTTP provider contract is unchanged. Existing byte-create, containment and
C2B-8D-4 tests remain in the focused validation set. Faults and identity mismatches
are injected where noted; rename refusal, file ACL changes and file creation/IO
use real Windows APIs. No network server or production Generation ran.

C2B-8D-7's disposable Windows cases also exercise successful protected
acceptance, exact issuer/callback binding, copied and incomplete receipts,
cross-owner refusal, stale host state, content/ACL drift, repeated acceptance,
concurrent duplicate attempts, close/invalidation races, and retained bytes.

C2B-8D-8's disposable Windows cases exercise single and multiple descriptor
promotion, exact source/destination correlation, native destination `CREATE_NEW`
identity and ACL evidence, decoded byte/size/hash equality, source preservation,
copy/write/flush interruption, capacity refusal, stale host state, copied or
substituted acceptance, close/invalidation races at and before the commit
boundary, duplicate attempts and retained partial evidence.

C2B-8D-9's focused executor integration cases exercise exact one- and
multi-image promotion receipts, count-only `outputs_ready`, request ordering,
copied/cross-owner/closed receipts, promoted content/ACL drift, original-host
freshness loss, event-sink rejection or uncertain acknowledgement, close and
acceptance invalidation in the gap after successful inspection but before the
event commit point, revocation waiting for an already committed callback,
concurrent promotion close during unlocked freshness verification, and
duplicate/late event fencing. The offline suite does not call a real ComfyUI
endpoint, create Candidates, save a Project or enable production execution.

Stored-byte verification uses the existing bounded reread/decode implementation;
it is not a constant-memory decoder. Synchronous injected callbacks rely on their
own deadline/interrupt contract; the HTTP characterization wire supplies its
existing read budget. This owner adds no thread cancellation or hard wall-clock
guarantee. Transient changes restored between checks, hostile same-user writers,
directory durability, crash/power-loss atomicity and cross-file transactions
remain unproven. Close failures fence observations and retain evidence; they do
not establish that every underlying OS handle actually closed.

Host scope provisioning, production integration of protected promotion with
executor/publication owners, latest-head custody, fresh human authority,
approved retention/discard, production transport registration, worker lifecycle
and Human Start remain separate gates.
`execution_available=false`, `protected_storage_available=false`,
`authorship=unverified`, Recovery inspect-only, and Candidate/Project/Journal/MCP
execution and cleanup remain unchanged.

## C2B-8D-17A offline storage preflight and capacity admission

`core/generation_storage_admission.py` adds
`WindowsProtectedStorageAdmissionCharacterization`, an explicit host-side
composition of five already captured native roots: `private_journal`,
`temporary_containment`, `retained_uncertain`, `promoted_assets`, and the exact
`selected_project_json` read-only reference. The caller supplies the approved
scope and exact root-owner objects. Each root must still report its captured
local NTFS, owner-only ACL and native identity; all five must belong to the
same captured scope identity and have distinct, non-overlapping paths and
identities. The admission owner neither provisions roots nor repairs ACLs.
The native root owner has a separate explicitly opted-in disposable provision
method for a new `retained_uncertain` child; exclusive directory creation
fails if that name already exists. The existing four-purpose path-only policy
owner and its contract are unchanged.

Capture inventories only bounded direct children of the four writable roots.
It rejects links/reparse points, subdirectories, unsupported files, excessive
entry counts, unsafe file ACLs and unavailable identities. It records file
identity, size and the owner-only ACL snapshot, but does not read file content.
Any pre-existing file has no live operation custody and is charged to retained
uncertain accounting; it is never adopted as successful output. The selected
Project JSON is identity/ACL checked as a reference and is never read, written
or used as a storage destination.

Within one process, only one accounting owner may capture a given approved
scope identity, regardless of which valid writable-root set is supplied. This
also rejects alternate or partially overlapping root sets that could
otherwise create independent ledgers for shared capacity. A second capture is
refused, including after the first owner closes or invalidates; closing cannot
reset an unresolved ledger and permit a fresh empty one. The process-local
claim table is bounded to 128 distinct scope keys, after which new captures
fail closed. The selected Project JSON remains bound to the owner but is not
part of the capacity key, so changing that read-only reference cannot create
another ledger for the same approved scope.

The accounting kernel issues one exact operation token and at most one
reservation per operation. Estimates use bounded byte and entry upper bounds.
Concurrent reservations share policy ceilings; staging and promoted assets
share the existing `ContainmentLimits.aggregate_bytes` ceiling, and only one
write admission may be active at once. The default ceilings are at most the
existing 1 MiB Journal file limit, the existing 256 MiB staging/promoted
aggregate, and a 256 MiB `retained_uncertain` root. Uncertain writes remain
charged against the original purpose's retained-uncertain counter; they are
not moved into the separate retained root. Journal revisions, asset entry
counts, per-operation estimates and root inventory are bounded independently.
Arithmetic and exact integer types are validated before
admission. The owner also samples local filesystem free bytes and refuses a
reservation larger than the current sample after subtracting outstanding and
uncertain reservations. The sample is observational and may change immediately;
it is not a capacity guarantee.

A known pre-write cancellation releases its exact reservation. A completed
admitted write is counted as observed-used only when the native inventory shows
at least one new protected file within the reserved byte/entry bounds and no
prior entry was removed or replaced. An all-zero inventory delta does not prove
completion: it invalidates the owner and moves the full write estimate into
retained-uncertain capacity. Unknown outcome, inventory drift, close or
invalidation likewise converts unsettled upper bounds into retained-uncertain
capacity; there is no timeout release while the owner is live, retry or
cleanup. A reservation or write-admission token is bound to its exact
in-memory owner, operation and one-shot state; copied tokens, cross-operation
use, duplicate operation IDs, double release and duplicate completion are
rejected.

This is a **process-local accounting contract**, not an OS quota or a claim
that the corresponding disk space is free. It does not prevent another
process from consuming disk or bypassing this ledger. Successful scope claims
and reservations disappear from memory at process exit; a fresh capture
classifies existing files as retained uncertain, but cannot reconstruct a
lost reservation whose write left no file. The in-process duplicate-capture
guard is not restart-persistent and does not satisfy production restart
accounting. Native identity and ACL observations are separately rechecked, but
the accounting result does not itself prove pinned handles, content integrity,
Journal durability, author identity, current Project/session authority or
permission to execute. At this stage no Journal or promotion writer consumes
these reservation tokens; the one protected image writer boundary is described
below. Cross-process quota remains an explicit production blocker.

## C2B-8D-17B protected image writer admission

`WindowsProtectedAssetsCharacterization.create_image_with_admission_for_characterization()`
is an explicit disposable-only integration with the existing
`create_image_for_characterization()` writer. The admission owner must hold the
same exact `WindowsProtectedRootCharacterization` objects for both writable
asset purposes as the image owner; equivalent paths or separately captured
roots are refused. Both owners remain bound to the same approved scope through
the admission owner's existing root checks.

Before calling the existing writer, the integration consumes a unique
operation identity, reserves `len(input_bytes)` and one entry for the selected
purpose, then obtains that operation's one-shot write token. Thus an
over-capacity, duplicate, stale, closed or mismatched admission is rejected
before `CREATE_NEW`. An owner-local lease serializes the admitted write against
other asset writes and close. External close marks the asset owner revoking and
waits outside its lock; callback reentry on the writer thread fails fast
instead of waiting on itself. The asset lifecycle lock covers only the
`CREATE_NEW` plus immediate retained-handle registration boundary. Native
metadata reads, injected fault callbacks, writes, flush and byte verification
run outside that lock, so close can publish revocation while one of those
steps is stalled; the writer then retains its evidence and the full reservation
as uncertain. A known pre-write cancellation releases only its exact
ledger-held reservation without rescanning the filesystem, so a separate
active write cannot strand an unused reservation.

The existing native `CREATE_NEW`, owner-only file ACL, pinned handle and
identity capture, byte write/flush, image decode, and retained-failure path
remain authoritative. After it returns, the admission owner rereads and
validates the image bytes, scans the exact native roots, and requires exactly
one new file under the requested purpose, with the expected filename, size,
native identity and ACL. Under the bounded lock order
`protected-assets owner -> admission owner`, it commits only that exact delta
to observed-used accounting. The reservation is released only after that
commit; a successful readiness view reports `writer_integrated=true` while
production capability flags remain false.

Any exception after write admission, returned-observation substitution,
content/ACL/root drift, incomplete or unexpected inventory, close, or
invalidation retains the full byte/entry upper bound as uncertain and fences
the affected owner. Existing files are never removed, overwritten, retried or
silently adopted. A failure before the existing writer actually creates a
file may therefore retain capacity conservatively. No native I/O, byte
verification, or injected writer-fault callback is performed while the new
two-owner commit locks are held. Existing unintegrated callers continue using
the original writer API and behavior.

This boundary does not add a quota, cross-process coordination, restart
authority, native-root provisioning on user directories, cleanup/discard,
Journal replacement, staging download integration, promotion integration,
Candidate publication, Project save or production Generation. It does not
prove power-loss durability or defend against a hostile same-user process.
The focused test run in the current environment reported `138 passed, 170
skipped`; Windows-native ACL/identity characterization was skipped because
`win32security` is unavailable in this Python environment, so that result is
not evidence of Windows file-system behavior. The PR validation must rerun the
native cases where those prerequisites are installed. All production gates
remain false, including
`execution_available=false`, `protected_storage_available=false`,
`promotion_available=false`, and `candidate_publication_allowed=false`;
`authorship=unverified`.

## C2B-8D-17C protected remote stream writer admission

`WindowsProtectedAssetsCharacterization.stage_remote_image_with_admission_for_characterization()`
composes the existing streamed remote-image writer with the exact
`WindowsProtectedStorageAdmissionCharacterization` that owns the same protected
asset root objects. It requires explicit characterization/disposable opt-in,
the exact frozen request and successful remote receipt binding, an exact
descriptor object, a host freshness callback, and a unique operation identity.
It does not accept paths, remote URLs, or a caller-provided byte-count estimate.

Before `CREATE_NEW` and before calling the injected image stream provider, the
owner reserves one `temporary_containment` entry and the policy upper bound
`min(image_bytes, request_bytes, aggregate_bytes)`, then consumes the one-shot
write admission. The remote `Content-Length` is examined only after that full
reservation exists and cannot shrink it. The existing stream writer remains
authoritative for atomic native file creation/handle retention, owner-only ACL,
incremental writes, close, size/hash checks and image decoding. The capacity
lease spans the entire stream lifecycle and makes asset-owner close signal
revocation then wait for the writer to settle. No asset or admission lock is
held around freshness callbacks, provider/read/close callbacks, native reads,
decoding, writes or flushes; `CREATE_NEW` plus immediate handle retention stays
atomic under the asset lifecycle lock.

After streaming, the admission owner rechecks the exact image bytes, hash,
native identity/ACL and complete inventory. A final original-host freshness
callback runs outside locks; the exact `VerifiedProtectedImageObservation` and
actual one-file/actual-byte accounting are committed under the existing
protected-assets → admission-owner lock order. Thus the ledger records actual
bytes and releases the unused upper bound only after success. Distinct image
descriptors can be admitted sequentially because each successful inventory
becomes the next ledger baseline. A duplicate descriptor attempt or reused
operation identity is refused.

Failures before a write token may release only the exact still-unused
reservation. Once admitted, any exception, host loss, close/invalidation,
failed stream, content/ACL/root drift or inventory mismatch retains the full
upper bound and native file/handle evidence as uncertain; no retry, overwrite,
adoption or cleanup occurs. If admission close has already retained the active
token, the asset writer does not release it again. The stream observation is
not published unless its final admission commit succeeds.

This composes only disposable local characterization. It is not an OS quota or
cross-process lock, does not prove disk availability or power-loss durability,
and does not make the HTTP transport production-ready. Journal writers still
do not consume the ledger; batch promotion admission is described below. No
production roots, Start action, Candidate publication, Project save, Recovery,
cleanup or execution capability is enabled. All production flags remain false
and `authorship=unverified`.

## C2B-8D-17D protected promotion batch admission

`ProtectedDurablePromotionCharacterization.promote_with_capacity_admission_for_characterization()`
is an explicit, disposable-only opt-in that composes one already accepted,
complete protected image batch with the exact
`WindowsProtectedStorageAdmissionCharacterization` holding the same staging
and promoted asset root owners. The existing promotion owner remains the only
copy implementation and receipt issuer. The ordinary
`promote_for_characterization()` path and its behavior remain available without
capacity admission.

Before the first promoted-file `CREATE_NEW`, the integration claims the exact
promotion once, retains a close-aware asset capacity lease, validates the
complete ordered descriptor/source set, and creates one unique admission
operation. It reserves the sum of source byte counts and one promoted entry per
image against the existing shared staging/promoted byte and entry limits. The
pre-existing staging inventory remains charged; promotion does not release or
move staging capacity. The exact operation then receives one write admission.
Over-capacity, identity, freshness, or root failures before creation produce no
destination file. A known cancellation before the writer is entered may
release that exact unused reservation; after a destination writer is entered,
any uncertain result retains the full batch estimate and all file evidence.

Each destination is still created by the asset owner's existing
`CREATE_NEW`/owner-only-ACL writer, with its native handle and identity retained
before byte writes. The short asset lifecycle lock protects only creation and
immediate handle retention; file identity/ACL reads, byte copies, flushes,
decoding, inventory scans, and host-freshness callbacks run without owner
lifecycle locks. Admission and promotion tokens are checked between native
write steps. The asset owner close waits for the batch lease; promotion close,
acceptance invalidation, admission close, or host drift fences final success.

Before commit, the original acceptance owner revalidates the host binding and
all source staging images. The promotion owner re-observes every complete
destination image, and the admission owner scans all writable roots. It requires
that every previously inventoried file is unchanged and the exact inventory
delta consists of precisely the expected N promoted filenames, byte counts,
native identities, and owner-only ACL observations, with no changes in other
roots. It also verifies that each destination's decoded format, dimensions,
size, and SHA-256 match its corresponding accepted source image.

The final in-memory boundary serializes the exact immutable promotion receipt
with ledger completion under the lock order
`protected-assets → acceptance → promotion → admission → ledger`. No successful
receipt is observable before the exact N-file delta has been committed as
observed-used capacity. A rejected commit rolls back the in-memory receipt
publication and retains the full reservation as uncertain. The receipt remains
distinct from legacy `PromotedImage`/`DurableGenerationAssets` custody and
grants no executor, Candidate, Project-save, Journal, Recovery, or cleanup
authority.

This is still process-local characterization, not a quota, cross-process
reservation, disk-space guarantee, power-loss durability guarantee, or
same-user hostile-process isolation. Capacity-owner restart cannot reconstruct
the reservation. No partial copy is deleted, adopted, retried, or rolled back.
All production gates remain closed:
`execution_available=false`, `protected_storage_available=false`,
`promotion_available=false`, `candidate_publication_allowed=false`, and
`authorship=unverified`.

## C2B-8D-17E-A protected Journal replacement capacity contract

`C2B-8D-17E-A` introduced a private Journal-specific preflight and
reconciliation seam on `WindowsProtectedStorageAdmissionCharacterization` for
the existing protected V1 and multi-request Journal writers. At that stage it
was accounting characterization only: neither Journal writer called the
seam, and no writer schema, revision rule, append implementation, or
production capability was changed.

`admit_journal_replacement_for_characterization(operation, journal_owner)`
requires the exact live admission owner, its native `private_journal` root
object, the same root object held by the writable protected Journal owner, one
active protected writer, and the exact operation ID/schema/current writer tip.
For revisions after the first, admission also requires the preceding
owner-observed revision, digest, file identity, native inventory row and
acknowledgement recorded by this ledger. The complete current root inventory
must match its last successful observation and no operation-specific `.lock`
or `.tmp` may already exist. Capacity refusal leaves the successful inventory
and operation state unchanged.

The completed Journal file remains bounded by the original 1 MiB file limit.
Preflight reserves at most 1 MiB for a new full-snapshot TMP and two entries:
one TMP plus one zero-byte exclusive lock. The existing JSON stays charged as
observed-used during a replacement, so a maximum-size old snapshot plus the
maximum TMP reaches, but does not exceed, the existing 2 MiB live-operation
bound. It is counted only once; the lock adds an entry but zero bytes. The
normal `private_journal` steady-state ceiling remains 1 MiB, so the predicted
post-replacement inventory must still fit that ceiling. Free-space sampling
remains observational and is not a disk reservation.

`complete_journal_replacement_for_characterization(...)` publishes accounting
only for the exact live writer and one-shot token after reopening the expected
next revision, matching its digest and file identity to the writer
acknowledgement, and observing the final target's native identity, unchanged
owner-only ACL and bounded byte count. The complete native inventory must be
identical to the prior inventory except for that one added/replaced JSON row;
the exact comparison requires terminal `.tmp` and `.lock` absence and rejects
extra, removed, substituted or changed entries. A replacement must have a new
native identity, while its protected ACL policy remains unchanged. On success,
the prior target's observed bytes and entry are atomically replaced in ledger
accounting by the new target's actual size and one entry. The final file
identity is also required to be unique across inventoried roots.

Once the specialized token is issued, generic write completion cannot settle
it and the generic cancellation API cannot release it without Journal-specific
proof that CREATE_NEW was never attempted. This bounded contract chooses the
conservative path: an unsettled token retains the full 1 MiB and two-entry
upper bound on any writer uncertainty, inventory/identity/ACL/acknowledgement
conflict, close or invalidation. Existing JSON remains separately charged as
observed-used, accounting for old JSON plus a possibly retained TMP or replaced
JSON. No filename disappearance, elapsed time, close, process exit, or later
reopen releases that uncertainty. No retry, adoption, deletion or cleanup is
performed.

Native file I/O and Journal reopen/verification run outside the ledger lock.
The final in-memory accounting commit is serialized under Journal-owner →
admission-owner → ledger locks; admission close cannot turn an unsettled token
into a success. The exact root handle, Journal owner and writer are required
again at completion. This is process-local accounting and native observation,
not a cross-process quota, disk-space guarantee, power-loss guarantee,
cryptographic author authentication, or production Journal authorization.

The ordinary Journal APIs remain available and preserve their existing
behavior. The explicitly selected C2B-8D-17E-B methods on
`WindowsProtectedJournalCharacterization` now compose one exact capacity
admission around each existing V1 or multi-request append. The integration
does not replace or reinterpret either Journal schema, checkpoint/event order,
the V1 eight-checkpoint ceiling, the multi-request 100-request/300-revision
ceiling, or its cumulative-write budget. It creates no alternate writer.

For an integrated append, the protected Journal owner first claims one private
lifecycle lease. A multi-request call first validates its caller-supplied
acknowledged tip against the exact live writer tip; the admission owner then
verifies the shared native root, writer, operation, schema and current
revision, and reserves the full replacement TMP bound and lock entry. Only
after that reservation is committed can the existing writer attempt `.lock`
and `.tmp` creation. The existing writer still
owns CREATE_NEW, flush/fsync, replace, native reopen and its internal
acknowledgement. The integration then reopens and independently checks the
exact next revision/digest/file identity, final protected ACL and byte count,
and the complete expected inventory delta. It reconciles actual used capacity
and clears the reservation before the host-visible acknowledgement is
returned. Each later revision receives a fresh one-shot admission; a prior
capacity operation can continue only for the same exact Journal operation and
writer.

The final ledger commit and publication of the exact acknowledgement share the
lock order `Journal owner → admission owner → ledger`; native observations and
writer/fault callbacks run outside those locks. The lifecycle lease lets a
concurrent Journal-owner Close publish revocation while native I/O or a
callback is blocked, then wait without closing the root underneath the
operation. A reentrant Close from the active writer callback is rejected.
Admission-owner Close or invalidation fences the same final commit. If Close or
invalidation wins before the final commit, no acknowledgement is exposed and
the full replacement upper bound is retained as uncertain. If the exact
accounting/acknowledgement commit wins first, Close waits for the lease to
finish and the completed acknowledgement remains valid.

Pre-admission refusal leaves the writer and inventory untouched and creates
no files. After an admission is issued, the implementation deliberately has no
generic pre-create cancellation: any uncertain CREATE_NEW, write, flush/fsync,
replace, reopen, ACL/identity observation, or ledger-completion outcome
invalidates the integrated writer and retains the full 1 MiB/two-entry upper
bound. The previous JSON remains separately observed-used; partial `.tmp`,
`.lock`, or replaced JSON evidence is preserved. No retry, takeover, cleanup,
replay, automatic capacity release, or later append follows an uncertain
outcome. Successful replacements account the actual new JSON once, replacing
the previous observed JSON charge.

This is still an explicitly opted-in, disposable, offline characterization
seam. It is not connected by default to `GenerationExecutorJournalIntent`,
does not authorize a send, and does not reconstruct authority from reopened
Journal bytes. A host must explicitly choose the integrated append method and
hold the exact capacity operation if it wants this accounting boundary; the
ordinary path remains unchanged. The process-local reservation is not an OS
quota, cross-process exclusion, disk-space guarantee, power-loss durability,
cryptographic author authentication, or production Journal authorization.
All production gates remain closed:
`execution_available=false`, `protected_storage_available=false`,
`promotion_available=false`, `candidate_publication_allowed=false`, and
`authorship=unverified`.

## C2B-8D-19C-A Profile A protected-root placement and capacity policy

This section records the proposed local Windows placement and admission policy
for the adopted **Profile A: Local Single-User Application**. It is a
non-executing policy contract, not a provisioning implementation or activation
decision. Profile A excludes hostile processes running as the same Windows
user, administrators/SYSTEM, and compromised host code from its storage
isolation guarantee. LLM/MCP instructions and returned values remain untrusted
inputs; explicit human Start, Recovery, and Discard authorization, exact source
and review provenance, Project integrity, Candidate idempotence, and save
uncertainty fences remain required. `authorship=unverified` is unchanged.

### Intended Windows placement and current incompatibility

The policy target for app-owned writable evidence is one local, app-specific
scope beneath the user's Local AppData, resolved and checked at runtime:

```text
%LOCALAPPDATA%\PromptGraph\AgentGeneration\v1\
  private_journal\
  temporary_containment\
  retained_uncertain\
  promoted_assets\
```

The names describe four distinct, non-overlapping purpose roots. This is a
target layout only: the current native owner accepts a host-supplied existing
scope and may create only opted-in disposable child roots. It does not create
the production scope, repair an existing directory, adopt its contents, or
change any ACL. A future provisioner must resolve the path to local fixed NTFS,
reject reparse/identity changes, create new app-owned roots exclusively with
the reviewed protected DACL, and stop on any pre-existing conflicting path.
The owner-only DACL model is a bounded observation, not defense against a
same-user process or privileged administrator.

`selected_project_json` is different: it is the exact, independently selected
Project JSON used as a **read-only host reference**, not a storage destination
or a child of the app-owned protected scope. Ordinary Projects must stay at
their user-selected locations; this policy does not move a Project, copy it
into the private scope, or change its ACL.

At the 19C-A policy checkpoint, the five-purpose admission map could not
represent this relationship: it required `selected_project_json` beneath the
same scope and owner-only ACL as the four writable roots, and the original-host
association did not compare that reference with the live Project path. C2B-8D-19C-B
adds a separate four-writable-root characterization and independently captured
read-only Project reference, then binds the normalized reference path to the
exact current original-host Project lifecycle. This closes that specific
characterization gap without moving or re-ACLing user data. It does not enable
production admission or prove Project content integrity; see the 19C-B section
below.

| Selected Project placement | 19C-A behavior / current 19C-B characterization | Profile A policy target |
| --- | --- | --- |
| Ordinary local Project outside the app-owned scope | 19C-A rejected it; 19C-B can observe a separately selected local NTFS JSON and bind its normalized path to the live lifecycle | Keep it in place. Its read-only native identity observation is distinct from protected-root ACL policy. |
| Project JSON placed inside the private scope | 19C-A could admit it as a fifth protected purpose without proving active-Project binding; 19C-B does not require or infer this placement | Do not move or copy a Project to satisfy storage admission. The live host binding remains required. |
| Missing Project file, UNC/mapped/network path, reparse path, or unverified filesystem | 19C-B refuses missing, non-JSON, reparse/linked or non-local-fixed-NTFS references; supported ordinary file DACL structure is observed separately | Unsupported or ambiguous locations fail closed; no creation, repair or ACL change. |

The intended local app-storage placement does not imply that every possible
user-selected Project location is supported. The separate Project-reference
design must define which local filesystems and reparse conditions are accepted;
until then, unsupported or ambiguous locations fail closed.

### Ownership and lifecycle policy

The protected scope belongs to the local PromptGraph installation/user storage
lifecycle, not to one Project, Scene, Streamlit rerun, or ComfyUI endpoint.
Within a live process, same-target reruns may preserve the exact host binding;
Project switch, Save As, activation/epoch or pairing change, disarm, claim
replacement, and runtime close permanently retire the old authorization. A
new Project requires a fresh host binding to the same app-owned storage scope;
it must not recapture a second process-local ledger for the same scope or
inherit the previous Project's authority.

Every operation receives its own non-reusable capacity operation and
reservation. A Worker operation lease remains associated with its exact
request and roots until the call is known quiescent. Close/revocation fences
new work; it does not prove an in-flight write did not occur. An unresolved
write, stream, promotion, or Journal replacement remains uncertain and keeps
its full reserved upper bound. Native owner `close()` releases handles only;
it does not delete roots or files. Process shutdown must not discard uncertain
files or treat handle closure as cleanup.

After restart, native roots and files may be freshly inspected, but live
operation tokens, Worker leases, reservation acknowledgements and original-host
latest-head observations are not reconstructed from paths or Journal bytes.
Existing files are charged as uncertain inventory. Inventory cannot recover a
lost reservation whose write left no file. The adopted Profile A latest-head
policy allows bounded acknowledged live-writer observations only during that
live host/process; absent an independently retained host-observed tip after
restart, latest-head custody is unavailable. Until a separately reviewed
restart/capacity policy supplies that missing evidence, the post-restart
storage path remains inspect-only and new production writes must fail closed.
No automatic replay, rollback repair, reservation release, cleanup, or
Recovery association follows a restart.

Retention is independent of session expiry, Project replacement, Worker close,
root close, and ledger close. Those actions may retire authority or close
handles; none grants deletion. A future Discard operation needs separate human
authorization and current ownership/reference checks. No automatic TTL or
capacity-driven eviction is authorized here.

### Capacity policy represented by the existing ledger

`ProtectedStorageCapacityLimits.validate()` allows a deployment to lower the
compiled ceilings, never raise them. The current defaults and effective
constraints are:

| Purpose | Current policy ceiling | Accounting interpretation |
| --- | --- | --- |
| `private_journal` | 1 MiB aggregate observed bytes across direct files; configured 300 entries, but the native inventory scan stops at 256 direct files per root | Replacements account current inventory, not cumulative write amplification. Journal JSON is separately capped at 1 MiB per file; the multi-request Journal allows 100 requests, 300 revisions, at most 2 MiB old-plus-temporary live bytes, and 128 MiB cumulative writes per operation. V1 remains its existing eight-revision contract. |
| `temporary_containment` + `promoted_assets` | One shared 256 MiB and 16-entry pool | This is one joint limit, not 256 MiB per root. Staging and promoted copies can coexist and compete for the same budget. Existing containment limits also bound one image to 32 MiB, one request to 128 MiB, and one store to 256 MiB. |
| `retained_uncertain` | 256 MiB and 256 entries | Direct files already present in this root are counted as uncertain. A failed write is charged to uncertainty under its original purpose; it is not moved into this root. |
| `selected_project_json` | No writable byte or entry budget | Read-only identity reference only; excluded from writable-root inventory and capacity destinations. The future policy keeps it outside the app-owned scope. |

Across writable purposes, each reservation is bounded to at most 257 MiB and
400 entries, with arithmetic checked before admission. Each writable root's
initial inventory is limited to 256 direct files, and each file is bounded by
the 257 MiB root-file ceiling before the tighter purpose limit is applied.
The 128-scope process-local capture ceiling also applies. These are
implementation ceilings, not recommended user quotas; a product-facing
retention policy and warning UX remain undecided. Because the Journal capacity
setting permits 300 entries while native root scanning stops at 256, the
effective current Journal inventory ceiling is 256 files/root. Do not claim all
300 can be inventoried until that bound is reconciled.

Concurrent reservations within one ledger are summed against the purpose
budgets; only one native write admission may be active at a time. Staging and
promotion share their pool. The sampled free-disk value is only a momentary
preflight observation: another process or the OS can consume space, and
`ENOSPC` remains possible after admission. A partial or unacknowledged write
retains its reservation as uncertain, so future admissions can be refused
before more work is authorized. On initial capture, files already present in
the writable roots are charged as uncertain inventory, never adopted as
successful outputs; reaching a byte or entry ceiling refuses further admission.

The accounting ledger remains process-local; it is not an OS quota or durable
reservation. C2B-8D-19C-B adds a native scope-writer lease for characterization:
the exact scope volume/file identity determines a zero-byte marker name,
created with `CREATE_NEW` and a protected owner-only DACL. The marker is held
without sharing, so another process using either the four-root or legacy
five-purpose capture API cannot create a second admission owner for that
scope. Existing markers are not read, adopted, stolen or timed out. This
excludes competing cooperating PromptGraph admission owners; it does not stop
an unrelated process that ignores the marker and is not an OS quota.

On process exit, process-local reservations disappear. An abandoned lease
marker remains and blocks another admission owner; there is no takeover or
restart authority reconstruction. After an explicit settled close, only that
owner's verified zero-byte marker may be released. Roots and evidence files
are never deleted by scope close. Fresh inventory can observe retained files,
but cannot distinguish settled from uncertain evidence or reconstruct a
no-file reservation. A successful free-space sample or fresh ledger is not
proof that prior reservations settled. Disk free space is never guaranteed by
this accounting contract.

### Production decision and next boundary

The current production decision remains **NO-GO**. The four-root Profile A
root-set, separate read-only Project reference, scope lease, 17B/17C image
writers, 17D promotion writer, and 17E-B Journal replacement methods are all
opt-in disposable characterizations. Journal capacity integration is still
not selected by default by `GenerationExecutorJournalIntent`. There is no
production root provisioning, restart reservation reconciliation,
production Worker/storage writer integration, retention/Discard owner, or
Start path. C2B-8D-19C-C adds only a non-executing Worker/reference association
characterization. All production flags remain false, and
`authorship=unverified`.

The next bounded implementation recommendation after C2B-8D-19C-C is the
C2B-8D-19D Worker-to-protected-writer pre-admission characterization: bind one
exact original-host submission lease to the existing Profile A capacity
ledger, reserve staging capacity, and stop before native writer admission.
The later writer-authorization boundary must validate exact remote output
evidence and fresh host/native state before calling the existing writer
admission. Production provisioning, real transport, activation and actual
write authorization remain separately reviewed gates.

## C2B-8D-19C-B four-root Profile A binding and scope-writer lease

`WindowsProtectedStorageAdmissionCharacterization.capture_profile_a_root_set_for_characterization()`
accepts exactly four writable root owners: `private_journal`,
`temporary_containment`, `retained_uncertain`, and `promoted_assets`. They must
be distinct, non-overlapping native roots under one independently approved
scope. Existing native file identity, owner-only DACL, local fixed NTFS,
reparse and scope checks remain authoritative. This path reuses the existing
`_CapacityLedger` and 17A limits; it does not introduce an independent ledger.
The legacy five-purpose `capture_for_characterization()` remains available
with its original contract and now shares the same per-scope writer exclusion.

`WindowsProjectJsonReferenceCharacterization.capture_for_characterization()`
separately pins an explicitly selected existing JSON on local fixed NTFS. It
rejects links/reparse paths, multiple hard links, identity changes and
unsupported filesystem or ACL structures. Its DACL is observed and rechecked,
but does not need the protected-root owner-only ACL; the handle requests
read-only access. The owner records native file identity, size and last-write
metadata, not Project JSON content or a content hash. This characterizes file
identity and unchanged metadata, not same-user write prevention or content
integrity. The Project file is never moved, copied, written, saved or re-ACL'd.

`ProjectAgentSessionRuntime.bind_generation_profile_a_storage_for_characterization()`
revalidates both native owners outside runtime, route and lifecycle locks,
then rechecks the exact lifecycle generation, Project object, normalized path,
target epoch and tracker before publishing the binding through
`OriginalHostGenerationLifecycle.observe_profile_a_storage_binding_for_characterization()`.
Same-target reruns may retain the reference-only binding. Project/path/epoch,
pairing, claim or session lifecycle retirement clears it permanently; returning
to the old path creates a new lifecycle with no restored binding. Storage
ownership remains separately held and is not automatically closed on target
change. The capacity owner retains a bounded set of exact lifecycle references
for lease-release checks; this prevents runtime garbage collection from hiding
late Worker uncertainty. It refuses a new association while a prior lifecycle
is unsettled and retains at most one lifecycle association.

`WindowsProtectedScopeWriterLease` derives its marker name from the approved
scope's native volume/file identity and acquires a zero-byte owner-only file
with `CREATE_NEW`, no sharing, and native identity/ACL/path checks. All
capacity captures use this lease, so separate PromptGraph processes cannot
silently create competing ledgers when both follow the owner API. An existing
or abandoned marker is not inspected or adopted and causes fail-closed refusal;
there is no timeout, stale takeover, restart recovery or automatic cleanup.
After a settled owner close, the exact pinned marker can be explicitly
released. If an operation is uncertain or an associated host/Worker lifecycle
is still active, the marker is retained. Close never deletes protected roots,
Project data, staged files, promoted assets, Journal files or other evidence.

Windows disposable tests cover four-root capture, Project JSON outside the
scope, DACL and identity checks, path/target mismatch, target replacement
during blocked native readiness, cross-process exclusion, abandoned and
uncertain marker retention, and no binding resurrection. The characterization
still grants no execution, protected write, promotion, Candidate, save,
Recovery or cleanup authority. After restart, neither the lease nor the ledger
reconstructs operation tokens or host authority; pre-existing inventory remains
uncertain and an orphaned marker blocks admission until separately resolved.

## C2B-8D-19C-C Profile A Worker/storage association

The explicit
`ProjectAgentSessionRuntime.bind_generation_profile_a_worker_storage_for_characterization()`
path extends the existing 19B `OriginalHostWorkerStorageIntegration` to four
exact writable purpose-root references, their exact `_profile_a_root_set=True`
capacity owner, the independently captured read-only
`WindowsProjectJsonReferenceCharacterization`, the current 19A lifecycle and
one supplied fresh `HostOwnedHTTPIOWorker`. The legacy binding API remains an
independent five-root path and is not reinterpreted as Profile A.

The Profile A association requires an established 19C-B lifecycle/reference
binding and a live nonterminal Job Claim, Inbox envelope and manifest. Native
capacity and Project-reference readiness are revalidated outside host locks,
then the exact Project object/path, target epoch, activation, pairing,
lifecycle and Claim are checked again before the Worker claim. Final in-memory
publication follows the existing host -> route -> target -> Job Registry ->
Inbox -> lifecycle -> capacity owner -> Worker order. The capacity lock
serializes close against the one-shot Worker ownership claim. The Worker claim
cannot be shared, released for reuse, or reconstructed after lifecycle
retirement.

Correlation, operation admission and result observation recheck exact root-map
identity, owner/lease liveness, and the same separate Project-reference object
and normalized path on the bound lifecycle. This is reference-only freshness.
Native ACL, handle and file-identity readiness is checked at binding; later
reference equality is not a fresh native observation. No native readiness I/O
runs under host locks. Closed/replaced references, root-map drift, revoked
scope lease, retired lifecycle or host invalidation refuse new operations.

Project/Claim/pairing invalidation revokes the Worker and requests a
nonjoining close. An active or uncertain operation retains the exact roots,
capacity owner, Project-reference evidence and scope lease. Project changes
retire only the Project/Worker association; they do not close the app-owned
storage owner or roots. No writer, Journal, Candidate publisher, Project save,
HTTP transport, cleanup or retry is invoked. The association grants no
execution, protected-storage, promotion, Candidate, Project-save or Recovery
authority, and `authorship` remains `unverified`.

The remaining production gates include approved real-user root provisioning,
writer integration and write authorization, production Worker lifecycle and
real ComfyUI interoperability, explicit Human Start/UI activation, Candidate
publication and Project save, and restart/recovery/retention/Discard policy.
The process-local capacity ledger is still not an OS quota or restart-resolved
reservation system; the separate Project reference observes identity and
metadata, not content integrity.

## C2B-8D-19D Profile A Worker-to-protected-writer pre-admission

`ProjectAgentSessionRuntime.pre_admit_generation_worker_staging_for_characterization()`
is an offline preflight for one exact active Profile A `submission` operation
lease. The original `OriginalHostWorkerStorageIntegration` retains the lease
and private reservation tokens; the returned immutable observation exposes
only request index, purpose and the host-supplied byte/entry estimate. One
request may be attempted once, up to the existing 100-request manifest bound.
The estimate is limited to the existing staging batch contract (at most
256 MiB and 16 images), then charged by the existing ledger against
`temporary_containment`, including its shared `temporary_containment` plus
`promoted_assets` limits and retained-uncertain/free-space accounting.

Pre-admission never calls `admit_write` and cannot be converted to a native
write token. It starts or performs no Worker, consumes no output stream, and
creates no image or Journal file. The Worker operation is only the exact
current host registration; a later Worker completion would remain
observational and is not trusted-output evidence or permission to write.
The legacy five-purpose owner remains unchanged and cannot use this Profile A
pre-admission API.

Fresh capacity inventory and Project-reference readiness execute outside
host, Job, Inbox, lifecycle and integration locks. The final in-memory
publication is serialized with exact current Claim, Project/path, activation,
pairing, Worker lease, four-root owner and scope lease custody. Duplicate,
copied, cross-lifecycle, replayed, stale and already-attempted leases fail
closed. Claim, Project or Worker revocation cancels only a provably still
reserved pre-write token. If owner close or invalidation races after reserve,
the existing ledger transfers that estimate to retained-uncertain capacity;
it is not silently released. Native state drift prevents observation
publication. This remains a process-local admission estimate, not a disk
quota, successful-write guarantee or restart-persistent reservation.

C2B-8D-19E-A below adds the metadata-evidence half of this boundary while
stopping before writer admission. The next 19E-B slice must consume the exact
owner-held evidence and same 19D reservation, enforce actual stream byte limits
and verify native destination state through the protected stream writer. It must
preserve one-shot send, output uncertainty, cancellation and close behavior.
Production root provisioning, real transport/ComfyUI interoperability, Human
Start, Candidate/Project publication, restart/recovery, retention and discard
remain NO-GO; all production flags remain false and `authorship=unverified`.

## C2B-8D-19E-A remote-output writer-authorization evidence

The 19E-A characterization adds the metadata-evidence half of the Profile A
Worker-to-writer boundary. The original host storage integration retains the
exact 19D pre-admission observation and reservation together with its frozen
request, accepted submission completion/prompt ID, and one later Worker-issued
history completion and original bounded JSON bytes. The Worker completion is
bound to the exact prepared request object and its latest-result witness;
copying or replacing the completion, substituting another request, or allowing
another Worker result to supersede it prevents publication.

The host validates those history bytes only through the authoritative
`validate_remote_outputs()` owner. Successful output evidence requires the
exact accepted prompt and manifest/request correlation, complete expected
output-node coverage, unique supported descriptors, and an explicit
successful execution status. Status-less or unresolved history cannot become
writer evidence. The new frozen
`GenerationWorkerRemoteOutputWriterEvidence` is separately owned and retained
with the exact `RemoteOutputReceipt`. It records descriptor count, a SHA-256
identity for history/receipt correlation and the already held reservation
bounds, but it grants no write or publication capability.

For this boundary the allowed estimate policy is stricter than the existing
19D reservation limit: 32 MiB per image, at most 128 MiB for one request, and
at most 16 image descriptors. The reservation must have enough entries for
all validated descriptors and enough bytes for the bound implied by image
count. A host-supplied estimate is not a measurement: the history endpoint
contains no image byte count that this stage trusts, and this stage performs
no `/view` request, download, stream or decode. Therefore actual per-image and
aggregate bytes, content format, native file identity and stored bytes remain
unverified until the later writer owns them.

Capacity/root readiness and the separate read-only Project-reference check
are performed before final host publication and outside runtime, Job, Inbox,
lifecycle, integration and Worker locks. The final in-memory commit rechecks
the exact active Claim, Project/path, target epoch, activation, pairing,
four-root references, scope-writer lease, reservation, and Worker-issued
latest history completion. Close, invalidation, stale host state or completion
replacement prevents evidence publication. A provably unused reservation may
be canceled on a definite refusal; uncertain evidence remains retained.

19E-A itself never calls `admit_write`, issues a writer token, downloads or
writes an image, changes Journal state, promotes assets, registers Candidates,
saves a Project, or reconstructs authority after restart. The legacy
five-purpose binding and its owners remain unchanged. C2B-8D-19E-B below adds
the one-image Writer handoff; C2B-8D-19E-C extends that same Profile A path to
one complete multi-image request. All production capability flags remain
false and `authorship=unverified`.

## C2B-8D-19E-B single-image protected Writer handoff

`ProjectAgentSessionRuntime.stage_generation_worker_remote_output_with_protected_writer_for_characterization()`
accepts only the exact `GenerationWorkerRemoteOutputWriterEvidence` privately
retained by its issuing Profile A Worker/storage integration. The integration
also retains the exact successful `RemoteOutputReceipt`, frozen request,
accepted prompt identity, original host/Claim binding, 19D capacity operation
and reservation. The request must contain exactly one validated descriptor;
multiple descriptors are refused before write admission or file creation.

The host creates a distinct disposable Asset Writer that borrows the exact
`temporary_containment` and `promoted_assets` root objects from the same
four-root Profile A capacity owner. It does not upgrade an inspect-only owner
or capture replacement roots. One Writer is pinned to the exact original-host
Worker/storage integration and may be reused for later single-image requests
after each prior handoff settles; another Writer or integration cannot take
over its retained contents. Borrowed Writers close only their own file handles
and never close the application-owned roots. Their direct legacy image
creation and batch-commit entry points refuse use; the one-shot host handoff
uses a private stream path only.

The Writer consumes the existing 19D `temporary_containment` reservation. It
does not begin another capacity operation or reserve a second estimate. For
this one-image contract the existing reservation must cover the fixed 32 MiB
image maximum and one entry. The existing admission owner refreshes actual
root/inventory state and issues its normal `admit_write` token; the token stays
private to the borrowed Writer. The explicit stream provider receives only the
existing bounded `/view` lookup derived from the frozen request and exact
remote descriptor.

Immediately before the host's one-shot CREATE_NEW authorization boundary,
capacity/root and Project-reference readiness are reobserved outside host
locks; the exact write token and held scope-writer lease are checked at the
short in-memory commit gate together with Worker evidence, Claim and host
freshness. The existing Writer rechecks native root/file identity and ACL
outside Host, Job, Inbox and lifecycle locks. Inventory scans, stream callbacks
and image verification also run outside those locks. The Writer enforces the
32 MiB image limit and 128 MiB request limit while streaming, retains the
native handle, decodes the image, checks actual byte count and SHA-256,
rereads stored bytes, and submits the exact one-file inventory delta to the
same capacity ledger.

A successful in-memory result is only a count-only
`protected_image_staged_non_authoritative` observation. The original
integration privately retains the exact verified image observation, and the
capacity ledger records actual bytes and one entry. No local receipt, batch
receipt, Candidate-ready result, promotion, Candidate, Project-save or Journal
authority is issued. The observation does not authenticate authorship.

The handoff remains unresolved between native ledger completion and the final
original-host count-only publication. Closing the capacity owner in that
interval retains the cross-process scope marker even though the ledger write
has reached `completed`. If host publication fails after that commit, the
exact stream observation and committed one-file inventory delta are used to
move the reservation from observed usage to its full retained-uncertain upper
bound; the file remains in place. The compensation is serialized with owner
close, and a fully published `staged_non_authoritative` handoff remains
settleable on clean close. Specific bounded publication failure codes are
preserved for the caller.

Before CREATE_NEW is attempted, the exact reservation/write token is canceled
only when the existing ledger confirms cancellation. Once CREATE_NEW may have
been called, incomplete streams, close, host invalidation, native drift or
accounting failure retain the file/handle evidence and conservative capacity;
there is no retry, overwrite, deletion or automatic cleanup. A writer closed
after CREATE_NEW does not close the borrowed app-owned roots. A verified
pre-create cancellation remains canceled even if an earlier in-memory
authorization callback had begun.

This slice is characterization-only. The native tests use disposable roots
and injected stream bytes, not a live ComfyUI server. It does not prove
production root provisioning, disk-space guarantees, power-loss durability,
cross-process byte quotas, process-restart authority, multi-image atomicity,
production transport/Worker registration, Human Start, promotion, Candidate
publication, Project save, Recovery, retention or Discard. Every production
capability flag remains false and `authorship=unverified`.

## C2B-8D-19E-C multi-image protected Writer handoff

`ProjectAgentSessionRuntime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization()`
accepts the exact host-retained 19E-A evidence only when its successful remote
receipt has 2 through 16 distinct descriptors. The existing single-image API
still requires exactly one descriptor. Both paths use the same 19D operation,
reservation, capacity owner, borrowed protected Writer, and scope-writer lease;
the batch path does not create a second ledger operation or reservation.

For descriptor count `n`, the existing staging reservation must cover
`min(32 MiB * n, 128 MiB)` and `n` entries before native write admission. The
batch obtains one private write token and performs one native CREATE_NEW per
descriptor in exact receipt order. Each file is separately streamed, flushed,
decoded, hashed, reread and bound to its retained native handle/ACL observation.
Only after all descriptors verify does the existing capacity owner compare one
complete inventory delta and complete the ledger once with aggregate actual
bytes and `n` entries. A successful original-host result contains only the
request index, verified image count, and `capacity_accounted`; no path,
descriptor, per-image observation, or write token is exposed.

The result is withheld on a missing/duplicate descriptor, failed stream,
native identity/ACL/byte mismatch, inventory disagreement, Claim or Project
invalidation, capacity/writer close, or failure at the final host publication
boundary. Before any CREATE_NEW may have been attempted, an exact confirmed
pre-write cancellation can release the reservation. Once any CREATE_NEW may
have been attempted, the whole count-based reservation is retained as
uncertain, even if only some files were created; possible files and handles
are not deleted, adopted or retried. If the ledger commits the aggregate delta
but the final host publication fails, the exact batch commit is compensated
back to the full byte-and-entry estimate. The cross-process scope-writer lease
remains held for unresolved evidence. A fully published and settled batch can
release the lease on clean close.

The characterization tests use real disposable Windows-native protected
roots and deterministic injected streams. They cover 2-image and 16-image
success, ordered correlation and native file evidence, a second-image stream
failure, Claim/Project/capacity invalidation between image writes, aggregate
inventory mismatch, insufficient reservation before creation, Writer close
waiting on an in-flight batch without deadlock, and capacity close racing
post-commit compensation. This establishes only the offline Writer/ledger/host boundary.
It does not enable production storage or execution, or prove OS-enforced
quotas, production provisioning, power-loss durability, cross-process quota
accounting, real ComfyUI interoperability, restart authority, promotion,
Candidate publication, Project save, Recovery, retention or Discard. Every
production capability flag remains false and `authorship=unverified`.

## C2B-8D-19F-A staged-image Acceptance bridge

`ProjectAgentSessionRuntime.accept_generation_worker_staged_output_for_characterization()`
accepts only the exact count-only staging observation already published by
the same original Profile A Host integration. The count is a lookup handle,
not authority: the integration resolves it to its private attempt, exact
Worker evidence and ready history completion, accepted `RemoteOutputReceipt`,
frozen request, ordered native image observations, borrowed Writer, four-root
capacity owner, 19D operation/reservation/write token and selected-Project
reference. Copied or substituted observations, another Host/Claim/Writer/root,
or a changed lifecycle cannot begin Acceptance.

Before issuing the existing `VerifiedProtectedImageBatchReceipt` shape, the
protected-assets owner revalidates every ordered descriptor and image binding,
native file identity, owner-only ACL, decoded image, digest and reread bytes.
The capacity owner must still show the exact completed write and its exact
previously recorded delta: one image for the single-image path, or the
aggregate bytes and entry count for the 2–16 image path. This is the original
completed 19D reservation; Acceptance creates no operation, reservation,
write admission, `CREATE_NEW`, or ledger completion. The generic
`commit_verified_remote_image_batch_for_characterization()` refusal for a
Profile A borrowed Writer remains in force. Only the narrow Host-issued
Profile A bridge can register the private receipt binding.

The bridge then uses `ProtectedOutputAcceptanceCharacterization` and its
existing protected-owner → Acceptance-owner joint commit. The callback checks
the exact original Host, Project/path, activation/epoch/pairing, live Job Claim,
Worker history completion and storage binding. Native inspection and callbacks
run outside Host, Job, Inbox, lifecycle and capacity-ledger locks. The result
returned to the caller contains only request index and accepted image count,
with `protected_image_batch_accepted_non_authoritative` status and every
production/publication flag still false. The batch receipt and accepted object
remain privately retained by their issuing owners for a separately reviewed
Promotion boundary; no legacy `LocalOutputReceipt` or Candidate authority is
created.

There are two commit boundaries. First, the protected owner jointly publishes
the exact batch receipt and Acceptance object. Second, the current original
Host publishes the count-only result under its current-claim gate. The final
in-memory commit is serialized against Writer, Capacity and Acceptance close
in the established Writer → Capacity → integration → Acceptance order. If the
Host, Writer, Capacity or Acceptance owner closes or changes between those
points, the caller receives no success; the private Acceptance is invalidated
or remains closed, the attempt becomes retained-uncertain, the completed
staging delta is moved to the reservation's full uncertain bound, and the
files and cross-process scope marker remain. There is no rollback, retry,
deletion or cleanup. A successfully published `accepted_non_authoritative`
result is settled; later clean close does not turn it uncertain and may
release the scope lease under the existing policy.

Native Windows disposable tests characterize complete 1-, 2- and 16-image
Acceptance, unchanged one-write ledger custody, copied-observation refusal,
real file-byte/ACL drift, duplicate calls, concurrent acceptance, Host claim
and Project-path drift during revalidation, Host loss after private commit,
Writer/Capacity close during revalidation, Capacity/Acceptance close at the
final publication boundary, and ordinary clean-close release. These tests do
not enable or prove production Generation,
protected-root provisioning, Worker/HTTP registration, Promotion, Candidate
publication, Project save, Journal/restart recovery, retention/discard,
cross-process quota enforcement or crash durability. No production capability
flag changes and `authorship=unverified` remains unchanged.

## C2B-8D-19F-B Profile A accepted-batch Promotion capacity preflight

`ProjectAgentSessionRuntime.preflight_generation_worker_accepted_output_promotion_for_characterization()`
is the scope-reduced Profile A boundary. It accepts only the exact
count-only Acceptance observation retained by the same original Host/Worker
storage integration, and revalidates the privately held
`AcceptedProtectedOutputBatch`, successful history/remote receipt, frozen
request, ordered source observations, existing completed staging delta,
Acceptance owner, protected-assets owner, four-root capacity owner, scope
writer lease and read-only Project reference. The settled-state Host check is
separate from the in-progress Acceptance check: it binds the same live
Project/path, activation/epoch/pairing, Job/Claim, lifecycle and Worker
completion before native inspection and again at Host publication.

After native source verification and readiness observations outside Host,
Job, Inbox, lifecycle and owner locks, the existing capacity ledger reserves
only the exact source byte total and entry count under `promoted_assets`.
The completed `temporary_containment` source remains observed in that same
ledger, so it is not reserved a second time. A final in-memory Host/owner gate
binds that exact still-reserved destination estimate to one immutable
`GenerationWorkerProtectedPromotionPreflightObservation`. The result exposes
only request index and image count. It contains no paths, images, operation,
reservation, write token or Promotion receipt; capability flags remain false
and `authorship=unverified`.

This boundary deliberately stops before Promotion. It does not issue a
writer token, call CREATE_NEW, copy a file, mutate a promotion inventory,
publish `VerifiedProtectedPromotionReceipt`, or enable the generic Profile A
Promotion constructor. That constructor remains fail-closed with
`profile_a_promotion_host_bridge_required`; the existing legacy Promotion
owner and behavior are unchanged. The exact preflight observation can cancel
only its own still-reserved destination estimate while no write has been
authorized. Close, invalidation, drift or uncertain cancellation does not
release evidence or capacity unsafely.

The current 16-entry shared temporary/promoted policy also means a full
16-image accepted staging batch already occupies every shared asset entry;
reserving a second 16-entry promoted copy is correctly refused with
`shared_asset_capacity_exceeded`. This PR does not raise that policy or claim
that retained source plus destination can always fit. The next Promotion
milestone must separately define bounded retained-source/destination capacity,
then add a narrow Host-issued Profile A CREATE_NEW writer path that copies and
reverifies every image, commits one exact aggregate ledger delta and private
receipt, and serializes final publication with Host/owner close and
invalidation. Any failure after a possible destination create must retain
partial evidence and capacity; it must not overwrite, retry, delete or clean
up. No production capability flag changes.

## C2B-8D-19F-C Profile A dual-custody capacity policy

C2B-8D-19F-C adds an explicit opt-in capacity identity for the four-root
Profile A characterization owner. It resolves the 19F-B 16-image preflight
ceiling without changing `ProtectedStorageCapacityLimits` or the generic
`ContainmentLimits` / `LocalOutputStore` defaults. The immutable
`PROFILE_A_DUAL_CUSTODY_CAPACITY_POLICY` is accepted only by
`capture_profile_a_root_set_for_characterization`; a generic five-root owner,
copied policy object, changed byte ceiling, or ad-hoc Writer limit is refused.
The borrowed Profile A Writer must retain the same policy identity as its exact
capacity owner and root objects.

| Profile A purpose | Per-purpose entries | Shared actual + reserved + uncertain entries | Shared bytes |
| --- | ---: | ---: | ---: |
| `temporary_containment` | 16 | 32 combined with promoted assets | 256 MiB combined with promoted assets |
| `promoted_assets` | 16 | 32 combined with temporary containment | 256 MiB combined with temporary containment |

The separate byte ceiling is not doubled: staging bytes, Promotion-copy
estimates, existing inventory, and retained uncertainty all compete for the
same 256 MiB. Request limits remain 1–16 images, at most 32 MiB per image and
128 MiB per request. Journal, retained-uncertain, generic, and legacy limits
are unchanged. Root capture, ledger reservation, subsequent inventory delta,
native scan, and borrowed-Writer inventory apply the same per-purpose and
combined entry ceilings. Files already present are retained-uncertain
inventory; neither inventory nor reservations are waived to make a later
operation fit.

With this explicit policy, the original-Host 19F-B preflight can reserve one
complete 16-image `promoted_assets` estimate while the exact 16-image staging
source remains observed. The new operation has a reserved estimate only
(`write is None`); the result remains immutable, count-only and
non-authoritative. The staging operation stays completed exactly once. A
default Profile A owner continues to use its recorded shared 16-entry limit
and refuses that same 16+16 preflight. The bounded preflight creates no
destination file, write admission, Promotion receipt or Candidate/Project
authority. The existing Profile A `create_image*` entry points and generic
Promotion factory remain fenced.

This is process-local accounting and an advisory free-space observation, not
an OS quota, guaranteed disk reservation, crash-durable inventory, or
production root lifecycle. Close, stale inventory, identity/ACL drift,
insufficient bytes, a 17th entry in either purpose, invalidation, or uncertain
cancellation still refuses or retains the exact reservation/evidence. No
automatic retry, overwrite, deletion, adoption, or cleanup is added. The next
separate Promotion milestone at this 19F-C checkpoint was the narrow writer
authorization and aggregate private commit; the 19F-D section below records
that offline boundary and the still-deferred Host publication. No production
capability flag changes; `authorship=unverified`.

## C2B-8D-19F-D Profile A original-Host Promotion Writer and private commit

19F-D consumes the exact `GenerationWorkerProtectedPromotionPreflightObservation`
issued by the current Profile A original-Host integration. The Host claims that
observation once, revalidates the selected Project reference, lifecycle, Claim,
Worker evidence, accepted staging batch, four-root identity, and the exact
existing `promoted_assets` reservation from 19F-B. It issues one destination
write admission against that reservation; it does not create a second
operation, reserve again, or reuse the completed 19D staging write token.

For each of the ordered 1–16 accepted descriptors, the original protected
assets owner rereads the verified staging bytes and creates a distinct file in
the already captured `promoted_assets` root with native `CREATE_NEW`. The
existing admitted writer retains the file handle and native identity/ACL
evidence, flushes the bytes, rereads and decodes them, and checks format,
dimensions, byte count and SHA-256 against the accepted staging image. The
aggregate commit rescans all roots and requires exactly the expected new
promoted identities and byte/count delta; the original `temporary_containment`
files and their completed ledger evidence remain unchanged. Promotion receipt
and destination ledger completion are published together as one private owner
transition only after the entire batch verifies.

The caller receives no receipt, destination path, image identity, count or
success claim. The Host method returns only
`protected_promotion_host_publication_deferred` with no result object, while
the exact private `VerifiedProtectedPromotionReceipt` remains held by its
issuing Promotion owner and Host attempt in
`private_committed_host_publication_pending`. This is not the final
original-Host count-only publication, Candidate admission, a legacy
`PromotedImage`, or save authority. 19F-E must separately implement that Host
publication boundary or keep the attempt uncertain; a settled private ledger
and receipt alone are not caller-visible success.

Before a possible `CREATE_NEW`, only the exact still-reserved destination
estimate may be cancelled after a positive pre-create proof. From the first
possible create onward, any partial file, write/flush/readback/ACL/inventory
failure, Host drift, invalidation or close retains the source and every created
destination handle/file, with the full destination upper bound charged as
`retained_uncertain`. There is no rollback, retry, overwrite, cleanup or
automatic capacity release. A close after the private commit changes the Host
attempt to `retained_uncertain`; the cross-process scope marker remains held
while this unresolved state exists.

The characterized limits are the existing opt-in 16 staging + 16 promoted
entry policy and shared 256 MiB byte budget, with the 32 MiB per-image and 128
MiB per-request ceilings. The legacy/default shared 16-entry policy and generic
Profile A `create_image*` and Promotion factory refusals are unchanged. Tests
use disposable Windows-native protected roots; this does not establish an OS
quota, production root provisioning, cross-process accounting, power-loss
durability, restart adoption or live ComfyUI behavior. Execution, protected
storage, promotion, Candidate publication and Project-save flags remain false;
`authorship=unverified`.

## C2B-8D-19F-E Profile A original-Host Promotion publication

19F-E adds the separate Host publication after the 19F-D private Promotion
commit. It accepts only the exact 19F-B preflight observation still held by the
same Original-host lifecycle and attempt, and the exact
`VerifiedProtectedPromotionReceipt` still held by its issuing Promotion owner.
Before publication it revalidates the accepted staging batch, successful
remote-history/Worker evidence, selected Project JSON reference, protected
source and destination files, native identities and ACLs, decoded bytes and
hashes, the complete ordered descriptor correspondence, both completed Ledger
deltas, the four-root capacity binding and the held scope-writer lease. A fresh
native inventory must exactly match the Ledger inventory; additions,
removals, identity/ACL drift, stale Host evidence or changed ownership refuse
publication.

The successful transition is one in-memory Host/owner commit. It creates no
file, reservation, write token, Ledger completion or second Promotion. The
caller receives only the immutable
`GenerationWorkerProtectedPromotionObservation` with the request index and
promoted-image count. The exact private receipt remains inside the original
attempt and Promotion owner. The count observation grants no Candidate append,
Project mutation/save, Recovery, retry or execution authority; all production
capability flags remain false and `authorship=unverified`.

Publication is one-shot. A copied or replayed preflight, host/claim/project
drift, close/invalidation, or any uncertain native or Ledger observation
withholds the count result. If the exact completed destination delta can be
proven, the Ledger moves its observed destination bytes back to the reserved
accounting and retains the full destination upper bound as `retained_uncertain`.
The staging and promoted files, handles, receipt and other evidence are not
deleted. If exact compensation cannot be established, the capacity and
Promotion owners are invalidated and the unresolved attempt keeps the scope
lease from being released. No automatic retry, overwrite, cleanup, replay or
authority reconstruction is provided.

Native scans and Project-reference observations run outside Host, Job, Inbox,
lifecycle and protected-owner locks. Final publication uses the established
Host → lifecycle → protected assets → Acceptance → Promotion → capacity →
Ledger → integration lock order. The Promotion owner's publication boundary
serializes its close against the in-flight observation; Host revocation and
capacity close are rechecked at commit and failures retain the completed
destination evidence. These offline Windows tests do not establish power-loss
durability, a disk quota, production root provisioning, real ComfyUI
interoperability, Candidate registration, Project save, or restart-time
recovery. Candidate publication and Project JSON save remain separate future
boundaries.

## C2B-8D-19G-A Profile A protected Candidate admission preflight

19G-A adds a separate, read-only Host preflight after the exact 19F-E
count-only Promotion observation. It accepts that exact object once from the
same Original-host lifecycle and rechecks its private `VerifiedProtectedPromotionReceipt`
chain, prepared request, successful remote-history evidence, ordered source and
promoted descriptors, four-root capacity owner, completed staging and
promotion ledger deltas, native identities/ACL inventory, decoded image bytes
and hashes. It also rechecks the live route, process/session, Project object
and path, frozen `GenerationPublicationOrigin` source snapshot, pairing, Job
Claim, and selected Project JSON reference. Native reads, hash/decode and root
inventory scans occur outside Host, Job, Inbox and protected-owner commit
locks; a short final commit is serialized against close and invalidation.

The result is an immutable count-only
`GenerationWorkerProtectedCandidateAdmissionPreflightObservation` with
`candidate_eligibility="not_established"`. It issues no legacy
`LocalOutputReceipt` or `PromotedImage`, does not call the existing Candidate
writer, and does not create `remote_outputs_ready` or `outputs_ready` events. A
`GenerationPublicationOrigin` by itself is insufficient: the existing
Candidate admission requires the genuine, host-accepted ordered event pair,
which the current Profile A promotion path does not publish. A copied or
replayed Promotion observation is refused. File, ACL, inventory, Project
snapshot or Host drift withholds the result and retains only downstream
preflight uncertainty; the already-published Promotion receipt, files and
completed ledger records are not rewritten or compensated.

Unresolved Candidate-admission preflight is also part of the common Profile A
capacity-owner retention decision. `in_progress` and `retained_uncertain`
prevent the original Host lifecycle reference from being replaced and cause
capacity close to retain the cross-process scope-writer marker. A completed
`preflight_observed_non_authoritative` result is distinct and does not itself
retain the marker as unresolved evidence. Host close during an in-flight
read-only check is retained as Candidate-admission uncertainty without
rewriting the settled Promotion.

This proves current offline protected Promotion evidence can be rechecked by
its original Host; it does not prove Candidate eligibility or authorize
Candidate mutation, Undo, Project save, retry, Recovery, cleanup or execution.
The next bridge must have the original Host accept the exact Profile A result
through the existing Executor event owner, without fabricating legacy events
or receipts, before the existing single Candidate Admission and Writer can be
considered. Tests use disposable Windows-native roots. They do not establish
power-loss durability, restart authority, cross-process byte quotas, production
root provisioning or live ComfyUI behavior. All production gates remain false
and `authorship=unverified`.

## C2B-8D-19G-B Profile A pre-send Executor event custody

19G-B adds a prospective, explicitly opted-in original-Host seam for the
first Job/Inbox transition only. For an exact active Profile A lifecycle,
accepted envelope, frozen request, Claim and bound Worker integration, the
Host accepts `submission_started` through the existing Job Registry and Inbox
before it registers the exact Worker operation. A failed or unacknowledged
event acceptance does not return an operation lease; the attempted integration
is revoked rather than reopened. If capacity/owner invalidation occurs after
Job/Inbox acceptance but before Worker registration, that accepted record is
retained but is not entered in the Profile A source-bound event map; no Worker
lease is returned and the integration is revoked. A concurrent Host close or
disarm fences later use of the Worker registration.

The source-bound event is retained privately by the original integration.
Previously accepted generic or fake Executor events are not upgraded by
matching event values, sequence numbers or counts. The read-only event-chain
inspection reports accepted Job/Inbox agreement separately from Profile A
source-bound event provenance. It cannot make an old 19G-A count observation
eligible and always reports `candidate_eligibility="not_established"`.

No `submitted`, `awaiting_result`, `remote_outputs_ready`, or `outputs_ready`
event is sourced by this slice. It does not invoke the existing protected
Candidate Admission or Candidate writer and does not mutate Candidates,
Project, Undo, or persistence. The first accepted start event alone proves
neither that an HTTP request was sent nor that ComfyUI accepted it. Later
events must be accepted at their actual original-Host Worker/result/Promotion
boundaries before Candidate eligibility can be considered. All production
capability flags remain false and `authorship=unverified`.

## C2B-8D-19G-C Profile A accepted submission event

19G-C extends the original-Host Profile A event chain only after an exact
19G-B `submission_started` was accepted by the Job Registry and Inbox and
privately bound to the Worker integration. Before observing a returned result,
the Host claims one private attempt only for the exact Worker-issued
`HTTPIOCompletion`, exact frozen prepared request, operation lease, Claim,
manifest, request and source-bound start-event object. Copied completions do
not consume the valid operation.

The Host then observes that same completion. Only a typed accepted
`SubmissionResult` whose actual response contains a validated Prompt ID stored
by the same integration can produce `WorkerEvent(kind="submitted")`. The
original Host sends one count-zero `ExecutorEvent` with no output receipt
through the existing Job Registry and Inbox. It privately binds that same
accepted event object only after both owners confirm the transition to
`awaiting_result`. The Job remains at `registered=0`; this event is evidence of
accepted HTTP submission only, not completed generation or output readiness.

Pre-send rejection produces no `submitted` event. Unknown, timeout, invalid
response, Worker close, or uncertain event acknowledgment is retained as
one-shot uncertainty. If Job/Inbox accepted the event but private source
binding then fails, the event remains visible as accepted-but-unbound and is
never deleted, replayed, or upgraded by matching values. The read-only audit
reports Profile A source kinds `("submission_started", "submitted")` and
requires `remote_outputs_ready` next only when both exact event objects remain
current. An accepted unbound event is not Profile A provenance. A Profile A
history correlation following the source-bound start is withheld until this
submitted event is source-bound, so an accepted Prompt ID alone cannot stand
in for the event.

At the 19G-B boundary itself, no `remote_outputs_ready` or `outputs_ready`
event is created, and no Candidate Admission, Candidate append, Project change
or save occurs. The later 19G-C/D/E boundaries below provide subsequent source
events without changing this pre-send contract. Candidate eligibility remains
`not_established`; all production capability flags remain false and
`authorship=unverified`.

## C2B-8D-19G-D Profile A verified remote outputs ready event

After the 19G-B `submission_started` and 19G-C `submitted` events are both
accepted and retained as exact original-Host source objects, the Host can now
accept `remote_outputs_ready` for that request. It requires the same
Worker-issued History completion and frozen request, a `ready` History result,
the exact accepted prompt ID and correlation, and a fresh
`validate_remote_outputs` receipt with `execution_succeeded is True`. The
complete descriptor tuple must be unique, ordered and within the existing
one-to-sixteen output bound; status-less History and copied or substituted
completions cannot produce the event.

One exact `ExecutorEvent` is sent through the existing Job Registry and Inbox
inside the final original-Host commit. The integration privately binds that
same object only after both owners accept it and confirm the Job moved to
`awaiting_download` with the matching descriptor count and `registered=0`.
Its `OutputReceipt` retains the existing opaque remote receipt identity/count
shape; the identifier is correlation evidence and grants no custody. The event
represents validated remote metadata only. It is not local image containment,
protected staging, Promotion, or the later `outputs_ready` event.

Validation and native readiness observations happen outside the final Job /
Inbox / Host commit locks. An accepted event whose acknowledgment or private
binding is uncertain remains in Job/Inbox history, is excluded from the
Profile A source chain, cannot be replayed, and keeps unresolved capacity
evidence retained. A refused or stale attempt is also one-shot. The audit
reports `("submission_started", "submitted", "remote_outputs_ready")` and
requires `outputs_ready` next only while the exact source event remains current.
If an accepted event is evicted or no longer agrees across owners, the chain
fails closed. This does not itself invoke a protected writer, Promotion,
Candidate admission, Candidate append, Undo, Project save, Recovery, or
execution; candidate eligibility remains `not_established`, all production
capability flags remain false, and `authorship=unverified`.

## C2B-8D-19G-E Profile A protected Promotion outputs-ready event

After 19G-D has emitted and privately bound the exact `remote_outputs_ready`
event, the original Host can publish one genuine `outputs_ready` event for the
same request. The caller supplies only the exact count-only Promotion locator;
the integration retrieves its private `VerifiedProtectedPromotionReceipt`
and revalidates the issuing Promotion, acceptance and protected-assets owners,
the exact envelope/prepared request/remote receipt, complete descriptor order,
staging and promoted image observations, native identity/ACL/content, root
inventory, completed capacity-ledger evidence, Project reference and original
Host freshness.

The existing Job Registry and Inbox must still agree on the source-bound
`submission_started → submitted → remote_outputs_ready` prefix. Only then does
the Host send one count-only `ExecutorEvent(kind="outputs_ready")` through
those owners. Its opaque receipt ID is derived from the Promotion identity for
correlation, while the original integration privately retains the exact event
object and Promotion evidence. Success moves the Job to
`awaiting_host_registration`, records equal remote/output counts, and leaves
Candidate registration at zero. The event does not convert the protected
receipt into legacy `LocalOutputReceipt`, `ContainedOutputStore` custody or
`PromotedImage` custody.

Native file, ACL, byte and full-inventory checks run outside final Host,
Job/Inbox and protected-owner commit locks. Close/invalidation and competing
calls are serialized at the final owner boundary. Any accepted-but-unbound or
otherwise uncertain event is one-shot and retained; no replay, compensation,
Candidate Admission, Candidate append, Undo, Project save, Recovery or
execution follows. The source chain now reports all four event kinds only when
each exact accepted event remains current. Candidate eligibility remains
`not_established`; `execution_available=false`,
`protected_storage_available=false`, `promotion_available=false`, and
`authorship=unverified` remain unchanged.

## C2B-8D-19G-F Profile A genuine protected Candidate Admission evidence

The original Host can now accept only the exact 19G-E count-only
`GenerationWorkerProtectedOutputsReadyObservation` retained by its integration.
It verifies the source-bound `submission_started → submitted →
remote_outputs_ready → outputs_ready` chain against the same active Host,
Job/Claim, manifest, process/session, activation/epoch/pairing, Project
object/path/source snapshot and read-only Project JSON reference. The exact
accepted Inbox objects must still appear once in both the event index and
authority list. The Job remains `awaiting_host_registration` with equal remote
and output counts, `registered=0`, and one-to-sixteen ordered descriptors that
match the privately retained Promotion rows. Late, copied, stale, replaced or
uncertain evidence fails closed.

The bridge reuses `GenerationProtectedCandidateAdmission` and calls its
`admit_for_characterization` with only the original protected Promotion owner,
owner-issued receipt, successful remote receipt and request index. The full
`ProtectedCandidateAdmissionResult` and its private object-bearing observation
remain held by the original Host/integration; callers receive a separate
count-only result with `candidate_eligibility="evidence_observed"`. This
records eligibility evidence only. No protected Candidate commit, Candidate
writer, `registered` update, Gallery/Undo publication or Project save is
invoked.

The bridge is one-shot and keeps the existing 19G-A promotion preflight
independent: 19G-A can be observed before or after G-F without consuming its
attempt. Native verification stays in the existing Admission owner and outside
Host/Job/Inbox locks. Final publication is guarded against Host close and
invalidation, while Promotion and Job/Inbox custody remain current. Duplicate
calls do not expose the private result. Uncertain evidence remains retained;
the already-settled Promotion and capacity ledger entries are never rolled
back. No new capacity record, protected file, receipt type coercion or legacy
custody is produced.

This remains offline characterization. All production execution, protected
storage, promotion and Candidate publication flags stay false, and
`authorship=unverified`. Candidate writing, Gallery/Undo publication, Project
save, restart/recovery, retention and discard remain separate gates.

## C2B-8D-19G-G Profile A Candidate path and capacity custody

The first Profile A Candidate writer now consumes only the exact 19G-F
count-only admission locator retained by the original Host integration. Its
private promoted image paths must still be backed by the same protected-assets
owner and `promoted_assets` native root held by the exact four-root storage
capacity owner, with the approved scope identity, Project JSON reference and
scope-writer lease unchanged. Native root/file readiness is rechecked before
the Gallery commit and is never inferred from Candidate paths or receipt
strings.

The frozen Comfy `output_directory` remains outside the app-private scope;
the two directory trees must not overlap. The new Profile A check is distinct
from the legacy approved-parent policy. It does not change Comfy configuration,
permit writing into that output directory, modify an existing ACL, create a
production root or enable protected storage. The capacity owner issues only a
short in-memory Candidate-publication lease after native checks; it is not a
filesystem write token or a disk-space guarantee. Capacity close or
invalidation prevents a new commit and waits for a Candidate commit that has
already crossed this boundary before finalizing revocation.

The native disposable tests exercise one, two and sixteen promoted images plus
capacity-close serialization. Files remain in the private promoted root and
are not copied, adopted or cleaned up by this step. Project JSON save,
restart/recovery, retention/discard policy and production root provisioning
remain separate gates. All capability flags remain false and
`authorship=unverified`.

## C2B-8D-19G-H read-only Project reference across the app JSON writer

The Profile A Project JSON reference remains a pinned, read-only native handle
through normal readiness and freshness checks. The selected file is still
required to be an ordinary in-scope NTFS JSON file with the original observed
ACL, path and revision. The existing atomic `os.replace` writer cannot replace
the file while this reference is open, so 19G-H permits a narrow, exact
Host-owned close/reopen sequence after the one-shot save claim and all
pre-write checks have succeeded.

The close is bound to the private save authorization issued by the original
Host integration, Publication owner, lifecycle and capacity owner. It is not
available as a public method for arbitrary callers or destinations. The exact
app callback executes once with the already-bound Project object and path. The
reference is then reopened only for that same path, and the owner rechecks NTFS,
ACL, no-reparse/path identity and the newly observed file identity/revision.
An identity change is expected after successful atomic replacement; the new
identity is adopted only for this live one-shot save and is never treated as
cryptographic authorship or as restart authority. If reopen or any post-write
check is uncertain, the save evidence remains `retained_uncertain` and the
callback cannot be retried.

No existing ACL or directory is modified, and no Project writer was added.
The underlying callback remains the established `app.py` writer and
`core.io.save_project_to_json`. The selected Project reference still reports
`project_save_allowed=false`; it observes identity and protection but does not
grant filesystem write capability. This characterization does not establish
power-loss durability, cross-process serialization outside the held Profile A
scope lease, restart recovery, author authentication or production save
authorization. All production capability flags remain false and
`authorship=unverified`.
