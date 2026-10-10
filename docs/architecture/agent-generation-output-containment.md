# Agent Generation contained local output custody

Phase 4-C2B-5 bridges [validated remote receipts](agent-generation-comfy-executor-adapter.md)
to private verified local image evidence. Production execution remains disabled:
there is no default downloader, HTTP call, worker/thread, Start UI, MCP execution,
Candidate ingestion, Project/history mutation or autosave. Tests inject fake
`DownloadStream` providers and use temporary filesystem fixtures. The legacy
Gallery downloader is unchanged.

## Original host and execution evidence

The adapter uses only the exact remote receipt admitted from its accepted
C2B-3 envelope. The containment owner revalidates C2B-4 correlation and descriptor
identities: job, claim, manifest, request/index, workflow digest, accepted prompt,
expected output nodes/buckets and remote lookup components. One store binds to
one accepted envelope; another job cannot reuse its storage.

C2B-4 intentionally permits history without an explicit success status. The
private remote receipt now records `execution_succeeded` only when the validator
observed `status.completed: true` and `status.status_str: success`. The receipt
privately retains the bounded original validated history bytes; containment
revalidates that history and compares the resulting receipt's execution status,
correlation fields and descriptors. Changing only the summary boolean cannot
authorize execution success. A status-less
receipt remains valid **remote metadata**, but cannot download or produce local
`outputs_ready`: containment records `quarantined / execution_success_unproven`
without invoking the provider. `ExecutionResult.status: ready`, outputs presence,
or a filename alone never supplies success evidence. There is no independent
host success-override contract in this slice; adding one needs separate approval.

`local_output_custody_current_for_characterization` runs on the original host
before and after containment. Under the existing publication gate, route
operation lock, job lock and inbox lock order it checks current session/process
incarnation, exact accepted envelope/job/claim/manifest, activation/target epoch,
pairing generation, ordered request correlation and `awaiting_download` state.
After staging it checks the exact remote/local request, prompt, receipt identity
and complete verified image count. Disk I/O, stream callbacks, hashing and Pillow
decode all run after these locks release. The usual original-host event sink
rechecks freshness when recording the count event; a race there quarantines the
local evidence as well.

The local count event moves only to `awaiting_host_registration`. Candidate
registration and persistence remain zero/not attempted. It never calls
`ingest_gallery_generation_outputs`. Later requests cannot automatically run
until the existing host registration contract separately settles the preceding
request. Test multi-run settlement uses registry counts only.

## Storage owner and filesystem boundaries

`core.comfy_output_containment.ContainedOutputStore.create_for_characterization`
is the sole factory. It requires explicit characterization mode and creates an
exclusive application-prefixed root in the host's canonical OS temporary
directory. There is no caller destination/root parameter, Project path, Gallery
path or export path. The host owns this private object and must keep the OS
temporary directory application controlled. This seam does not create a shared
root in Project storage or accept a preexisting root as evidence of ownership.

Each request directory and each image filename is a new application UUID. A
remote filename/subfolder is used exclusively as a remote lookup; neither
participates in a local path. Directory creation is exclusive, image files use
`O_EXCL` and `O_NOFOLLOW` where supported, and file handles retain their original
device/inode identity. Ancestors, root, request directory and file are checked
with `lstat`, including Windows reparse attributes, before and after writes.
The root's canonical path and filesystem identity must remain unchanged.
Traversal, junction/symlink ancestors, substituted roots and unexpected existing
directories/files fail closed without overwriting or deleting the existing path.

Checks detect substitution and refuse unsafe cleanup. They are not a production
ACL sandbox against a hostile process with permission to rewrite the host's
temporary directory; deployment-specific protected-root/ACL policy remains a
gate before real transport. Public jobs and MCP have no storage path, endpoint,
filename, content hash or raw exception field. Private receipts contain opaque
storage IDs; paths stay solely in the store's private index.

## Download and validation bounds

The injected provider receives one frozen `ImageDownloadLookup`: validated
filename, subfolder, bucket, descriptor identity, and the host-approved endpoint
origin derived from the frozen prepared request. It receives no destination or
arbitrary caller URL. A future transport must build ComfyUI `/view` on that exact
origin and refuse uncontrolled cross-origin redirects. No real transport is
implemented or registered here.

`DownloadStream` declares an exact positive content length, `read(max_bytes)`
and `close()`. Every read is at most 64 KiB, including the final one-byte overrun
probe. Received bytes are counted incrementally; non-byte/oversized chunks,
missing/invalid lengths, short reads, overrun, interruption and close failure
cannot complete a request. No ambiguous attempt is retried. Failures use fixed
safe codes without callback exception text.

| Bound | Default maximum |
| --- | ---: |
| Images per request | 16 |
| Encoded bytes per image | 32 MiB |
| Encoded bytes per request | 128 MiB |
| Retained encoded bytes per store, including quarantine | 256 MiB |
| Image width or height | 8,192 pixels |
| Image pixel count | 16,777,216 |
| Request receipts per accepted envelope | 100 |

These ceilings cover ordinary SDXL outputs. Host test limits may be lower, never
higher than defaults. Quarantined files consume the same aggregate budget; there
is no silent eviction to free capacity.

Pillow recognizes the actual signature/format, verifies the file, then reopens
and fully decodes it. The verified format must match the remote extension,
dimensions must be positive and within both dimension and pixel ceilings, and
only one frame is accepted. Decompression-bomb warnings become failures. This
owner never changes Pillow's global pixel limit or truncated-image option; it
fails closed if global truncated decoding has already been enabled. SHA-256
covers the actual stored and decoded bytes and is checked against the streamed
digest. A repeated receipt additionally checks file identity, size and content
hash without downloading again.

Supported: single-frame PNG (`png`), JPEG (`jpg`/`jpeg`), WebP (`webp`) and BMP
(`bmp`). Unsupported: GIF, animated PNG/WebP, TIFF, ICO, SVG, AVIF and all other
formats. C2B-4 may recognize a GIF remote descriptor; C2B-5 explicitly refuses it.
There is no extension-based reinterpretation or conversion.

## Atomic batches, quarantine and retention

The store inserts a `verified` receipt only after **all** images download,
decode, hash and pass the final containment checks. Intermediate verified files
never form a successful batch. The immutable local receipt includes original
job/claim/manifest/request/index/workflow/prompt correlation, remote receipt ID,
local receipt ID, state, safe failure code, downloaded/verified counts, retained
storage IDs, and per-image SHA-256, format, dimensions, byte count and storage ID.
Remote metadata readiness, byte download, local verification, Candidate
publication and Project persistence are separate stages.

| State | Ownership and cleanup |
| --- | --- |
| `verified` | Complete atomic local evidence held by the original host; no publication authority. Retained until separately authorized recovery/retention work. |
| `incomplete` | No complete downloaded image; remove only partial files still proven to belong to this root and identity. The failed attempt remains pinned; no automatic retry. |
| `quarantined` | Success unproven, partial batch, corrupt complete bytes, changed storage integrity, or stale host custody. Retain complete bytes and bounded metadata; never advance local output counts. |
| abandoned filesystem work | Process interruption may leave the application-created root/directory without a receipt. Retain it for explicit human inventory/recovery; absence of a commit receipt never implies success. |

Complete downloaded bytes are retained even if decoding fails or another image
fails. Partial bytes may be removed only after root/directory/file identity and
reparse checks; uncertain cleanup stays isolated and budgeted. Empty attempt
directories may remain as abandoned markers. There is no `TemporaryDirectory`
finalizer, session-close deletion, expiry deletion, recursive cleanup, storage
overwrite or restart-time auto-adoption. Recovery here means retained inspectable
private evidence, not durable automatic receipt reconstruction or publication;
the recovery/retention UI and a process-restart inventory are future work.

An exact repeat returns the original receipt without another download. Conflicting
remote receipt data for an attempted request is rejected. Changed bytes or path
identity behind a committed receipt are quarantined without overwrite. The
adapter binds one store and pins callback reentry, preventing double download,
submission or local count delivery. Failed/quarantined attempts cannot be turned
into success by reprocessing the same receipt.

Project switch, Save As, pairing change, disarm, close, lease expiry and lost
session/process ownership cannot grant Candidate authority. If invalidation
occurs during I/O, complete verified bytes stay quarantined. Returning to the
old Project never restores the old activation. Late remote metadata remains
private remote quarantine and is not automatically downloaded in the new target.
Expiry is not remote cancellation; nothing resubmits or regenerates work.

## Remaining gates

A separately authorized slice must add original-host Candidate publication,
exact receipt/storage acceptance, Project persistence receipts, explicit human
recovery and bounded retention/cleanup policy. A later production slice must
approve a protected filesystem root, real `/view` transport and redirect policy,
worker lifecycle, network submission, Start UI and exact human review/confirmation.
`execution_available` remains false and MCP execution remains unavailable.
