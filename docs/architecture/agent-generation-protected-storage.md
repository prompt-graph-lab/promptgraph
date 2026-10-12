# Agent Generation protected storage and trust design (C2B-8C-1..3)

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
| Trusted latest head (unavailable here) | Independently retained revision/digest can detect a valid older prefix | Authentication without separately trusted head custody |
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

## Proposed product trust profiles (C2B-8C-3; decision pending)

This section is design only. Neither profile is adopted product policy, and no
runtime trust flag changes. The current owners still report
`execution_available=false`, `protected_storage_available=false` and unverified
authorship; reopened Recovery remains inspect-only. Earlier requirements for
authenticated ownership must be resolved explicitly against the chosen threat
profile, rather than implemented by renaming a digest or ACL observation.

| Question | Profile A: local single-user application | Profile B: process-isolated authorship |
| --- | --- | --- |
| Security boundary | Verified owner-only Windows ACLs constrain ordinary other-user access on supported local storage. | A separately protected signer/key custodian or distinct Windows identity/service must constrain hostile same-user clients as well. |
| Exclusions | Same-user malicious processes, administrators/SYSTEM, compromised host code and hardware failure remain outside the guarantee. ACL checks are bounded snapshots, not continuous file isolation. | Administrator/SYSTEM or compromise of the trusted service/key custodian remains outside any proposed guarantee unless separately designed. Isolation from ordinary same-user processes must be demonstrated. |
| Journal evidence | Schema, hashes and original live producer observations support corruption detection and reconciliation. They do not independently authenticate the author. | Author verification needs an independently pinned verifier identity and protected key custody. A signature identifies an authorized producer, not the truth/completeness of its observations or current action authority. |
| Latest revision | An independently retained host tip can detect accidental prefix rollback within its stated lifetime; loss of that tip leaves freshness unknown. Same-user rewriting of both stores remains out of scope. | Latest-head custody must also resist same-user rewrite/rollback, independently of the journal and signing key. A valid old signature alone is insufficient. |
| Operational cost | Native root/file policy, truthful uncertainty, fresh human review, retention and current publication gates are still required. | Also requires installation/IPC authorization, verifier provisioning, service availability, migration, rotation/revocation/loss and restart/head reconciliation policy. |

**Recommendation:** use Profile A as the minimum viable target for PromptGraph's
local single-user workflow. A human product/security decision must explicitly
accept its same-user/privileged/compromised-host exclusions and the inspect-only
treatment of missing lineage or latest-head evidence before it becomes policy.
If authenticated authorship against hostile same-user processes is a requirement,
Profile A is no-go; review Profile B's custody and operational design first.
This recommendation grants no production activation or Recovery permission.

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
mean exactly that even if a human later accepts Profile A's scope.

| Axis / current owner | Current observation and limitation | After process loss | Prerequisite for a future effect |
| --- | --- | --- | --- |
| Root ACL and file identity / native storage | Pinned handles, local NTFS, modeled owner-only DACLs and before/after identity checks; no hostile same-user content-I/O proof. | Bytes/ACLs may remain; handles and original live observation do not. Fresh native verification must compare independently selected roots and retained provenance, not recapture journal-supplied authority. | Separately approved Journal, staging, promoted-asset and Project scopes; fresh file/ancestor checks at use. Journal protection does not protect asset roots. |
| Schema/revision/digest / Journal | Strict complete chain and bounded correlation checks detect malformed/inconsistent bytes. | Surviving bytes can be revalidated; a valid prefix/recomputed chain can still pass. | Complete necessary evidence and current integrity; never a claim or permission. |
| Original producer / live writer | Exact live owner, expected predecessor and acknowledged append are observations. Process/session IDs in reopened records are assertions. | Owner object, lock custody and knowledge of acknowledgment do not survive. A retained lock is evidence, not a transferable lease. | Host-owned lineage under approved profile; no reconstruction of the old writer/claim. |
| Trusted latest revision | No head custodian implemented. `expected_revision/digest` compares a supplied tip, without authenticating its provenance or asserting directory durability. | Only a separately retained tip may remain; its custody, completeness and durability must be established afresh. | Adopted latest-head policy; missing/conflicting tip remains unknown. Never derive the expected tip from the journal being checked. |
| Authenticated authorship | Unverified; SHA-256/ACL/file identity are not a signature. | Nothing can upgrade authorship on reopen. Profile B would require surviving independently protected verification/custody evidence. | Profile A's explicit limitation decision or separately implemented Profile B verification; neither authorizes an action. |
| Original Project/source/review provenance | Journal correlations and saved JSON are inspectable evidence. Source/review fingerprints cannot establish their own trusted origin. | Files may survive; original Project object, exact source/review carrier and approval custody do not. | Independently verified original lineage, explicit unique Illustration targets, source/Scene/Module state and exact reviewed evidence. Changed/missing lineage blocks Recovery association. |
| Fresh session/activation/pairing/human review | RecoveryContext strings and review intentions are observations; no current capability. | Session, activation epoch, pairing generation, ACK and pending intention are not restored from disk. | A new exact host context and explicit human action under the future Recovery contract; switching back never revives old authority. |
| Candidate publication/save | Current JSON may show exact/partial/absent/conflicting association; callback and persistence outcome remain separate. | Saved bytes may remain; appender/publisher one-shot indexes and runtime attempts do not. | New host-only publication/save custody, idempotent reconciliation and immediate stale gate. Exact saved Candidates are not appended again. |
| Retention/discard | Inventory and counters are bounded; ownership, saved-reference and external-operation completeness can be unknown. | Files and unresolved observations may remain; no deletion approval survives. | Independent explicit discard authorization plus complete ownership/reference checks. Association approval does not grant discard or vice versa. |

## Rollback, rewrite and failure interpretation

The distinction below is part of the proposed decision, not a new classifier.
Existing [Journal](agent-generation-ownership-journal.md) and
[Human Recovery](agent-generation-human-recovery.md) states remain authoritative.

| Scenario | Detectable observation / limit | Required interpretation |
| --- | --- | --- |
| Malformed JSON, missing middle revision, wrong digest or request correlation | Existing bounded schema/chain checks reject it. | Detectable inconsistency; retain evidence, no reconstruction or retry. |
| Digest-valid older prefix | Detectable only against an independently retained expected tip. With no tip, it is indistinguishable from a journal that stopped there. | Latest-state/completeness unknown; no inference of unsent requests or absent later effects. |
| Same-user rewrite with recomputed digests | Can pass schema, chain and owner-only ACL observations. A rewritten same-user tip store can also agree. | Indistinguishable authorship attack under Profile A and outside its proposed guarantee. Profile B must protect both producer and latest-head custody. |
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
Recovery under either profile.** Categories below distinguish a human decision
(D), required implementation (I), required Windows/operational validation (V)
and an unsupported guarantee (U). Completing one row does not clear the rest.

| Gate | Category | Action required before go |
| --- | --- | --- |
| Journal lifecycle | I, V | Integrate bounded intent-before-effect/observed-outcome recording, exclusive writer retirement and truthful unknown states; disposable C2B-8C-2 alone is insufficient. |
| Protected roots and assets | I, V | Approve/provision production scopes and native Journal, staging, promoted-file and original Project use; validate ACL/identity/reparse behavior throughout. Never repair existing Project ACLs implicitly. |
| Threat scope/authorship | D; B also I, V | Human adopts Profile A's exclusions or requires Profile B's independent producer/key/service custody. Same-user/privileged resistance remains U under A. |
| Latest-head policy | D, I, V | Define tip provenance, survival/loss and conflicting-head behavior. A host tip only detects rollback within its custody scope; same-user-resistant custody is U under A. |
| Crash/durability | D, I, V; current guarantees U | Approve supported filesystem and unknown-outcome policy, characterize restart ordering and any chosen durability barrier. File fsync/replacement supplies no power-loss or cross-file transaction guarantee. |
| Recovery and retention | D, I, V | Review the separate fresh association/discard contracts, idempotence, quotas/reference completeness and original-host publication/save. Current intentions grant nothing. |
| Transport, worker and Human Start | I, V | Review truthful bounded real transport, one-shot worker/host event lifecycle, loss/shutdown and exact fresh human Start; policy adoption cannot enable them. |
| Operational validation | D, V | Separately authorize disposable real ComfyUI/Project restart/failure/capacity exercises only after implementation gates. Fake/offline success is not activation approval. |

**Recommended next PR:** a bounded offline trust-evidence inspection projection
composing the existing native Journal and Human Recovery observations. Expose
separate root/file, chain, observed-producer, expected-tip provenance/lifetime,
source/review and current-context states with fixed redacted reasons. A supplied
tip must remain explicitly host-supplied observational context; the slice must
not implement a trusted head store or claim authenticated authorship. Exercise
valid prefix/rewrite, missing tip, closed handles, changed source and conflicting
evidence; keep every permission false and Recovery inspect-only. This can make
the decision matrix visible and testable without assuming Profile A/B adoption,
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
establish an explicit file/replacement/directory durability policy; adopt the
threat/ownership profile and define latest-head custody within that scope;
implement independent authentication if Profile B is required; and establish fresh human
recovery authorization. Quota/retention, approved cleanup, real transport,
worker lifecycle, Human Start and original-host publication/save gates from
C2B-7 still apply. This characterization grants none of them.
