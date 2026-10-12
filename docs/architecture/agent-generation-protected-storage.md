# Agent Generation protected-storage characterization (C2B-8C-1)

`core/generation_protected_storage.py` characterizes the protected-storage policy
required by the [Ownership Journal](agent-generation-ownership-journal.md),
[containment](agent-generation-output-containment.md), durable asset promotion
and [Human Recovery](agent-generation-human-recovery.md). It has **no production
call site**. `execution_available` and every execution, association, publication,
save and cleanup status remain false. Recovery remains inspect-only.
`core/generation_windows_protected_storage.py` adds a separate opt-in native
Windows observation owner for narrowly supported disposable roots. It does not
wire the existing journal, containment, promotion or Recovery owners.

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

The writable scope must **already** have a protected current-user-only DACL.
No existing scope is repaired. `provision_journal_for_characterization` chooses
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
The descriptor and identity are rechecked before returning the private owner;
each readiness call rechecks native ACL, filesystem and original identity.

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

## Validation and remaining production gates

Focused disposable tests cover explicit/unapproved/overlapping purposes, Windows
and non-Windows fail-closed status, redaction, scope/root/file substitutions,
symlink/reparse ancestor/file observations, actual hardlinks, unsafe/inherited
principals, modeled/unmodeled ACLs, fsync failure, old/new file interruptions,
ambiguous acknowledgment, digest-valid forgery, rollback and Human Recovery
inspect-only behavior. True native Windows tests separately cover atomic secured
private-journal creation, same-handle descriptor/identity inspection, read-only
existing-root inspection, live scope/root rename refusal, actual Everyone and
inheritance ACL changes, unsupported/mapped filesystems, absent dependencies,
unapproved paths and retained evidence after post-creation interruption.
Synthetic ACL/reparse samples are distinguished from these native tests. The
existing publication symlink test may skip when Windows disallows symlink creation;
no successful native junction or general hostile-race guarantee is inferred.

Before production activation, separately review and integrate protected-root
ownership for journal/containment/promotion, approved scope provisioning and
child-file ACL propagation; expand native substitution/ACE/race validation in
the locked Windows environment and define supported long-lived handle lifecycles;
establish file/replacement/directory durability; define authenticated ownership
and independently trusted latest-head custody; and re-establish fresh human
recovery authorization. Quota/retention, approved cleanup, real transport,
worker lifecycle, Human Start and original-host publication/save gates from
C2B-7 still apply. This characterization grants none of them.
