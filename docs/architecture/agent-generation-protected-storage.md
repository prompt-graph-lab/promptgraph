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
acceptance under the protected owner's lock. Close or invalidation that wins
before this commit withholds acceptance. A later close or invalidation fences
further inspection while retaining all evidence.

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
Candidate or Project publication. The next explicit handoff must be a separate
protected durable-promotion owner that verifies accepted evidence and owns the
promoted bytes. Promotion, executor settlement, publication approval and save
remain distinct authority steps. No protected promotion or integration is
implemented here. `execution_available=false`,
`protected_storage_available=false`, `authorship=unverified`, Human Start,
Recovery execution, Candidate/Project/Journal mutation and cleanup remain
disabled.

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

Stored-byte verification uses the existing bounded reread/decode implementation;
it is not a constant-memory decoder. Synchronous injected callbacks rely on their
own deadline/interrupt contract; the HTTP characterization wire supplies its
existing read budget. This owner adds no thread cancellation or hard wall-clock
guarantee. Transient changes restored between checks, hostile same-user writers,
directory durability, crash/power-loss atomicity and cross-file transactions
remain unproven. Close failures fence observations and retain evidence; they do
not establish that every underlying OS handle actually closed.

Host scope provisioning, receipt/publication integration, durable promotion,
latest-head custody, fresh human authority, approved retention/discard, production
transport registration, worker lifecycle and Human Start remain separate gates.
`execution_available=false`, `protected_storage_available=false`,
`authorship=unverified`, Recovery inspect-only, and Candidate/Project/Journal/MCP
execution and cleanup remain unchanged.
