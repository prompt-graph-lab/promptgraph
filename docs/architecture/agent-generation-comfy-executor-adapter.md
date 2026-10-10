# Frozen ComfyUI executor and remote output receipts

Phase 4-C2B-4 characterizes a synchronous executor seam with injected fakes.
**Production execution remains unavailable.** There is no transport default,
worker thread, ComfyUI connection, download, output file, Candidate/history
mutation, save, Start control or MCP execution tool. All executor entry points
require explicit characterization owners. The existing
[C2B-3 handoff](agent-generation-executor-handoff.md), Executable Review and
exact human confirmation remain the custody authority; characterization is
not permission to enable production execution.

## Exact frozen request preparation

`core.comfy_prompt_request.prepare_frozen_prompt_request` receives the accepted
envelope's manifest and exact member `FinalizedRequest`, plus an executor-owned
client UUID. It verifies physical indices, unique request IDs, workflow SHA-256,
the finalizer's manifest content identity, per-workflow and aggregate bounds.
It prepares `{"prompt": <exact workflow bytes>, "client_id": <UUID>}` without
prompt injection, Module expansion, workflow planning, rewriting or seed
randomization. Both `seed` and `noise_seed`, including zero, stay exactly as
reviewed. This reuses C2B-1's frozen content and existing ComfyUI output-node
recognition, rather than planning a second workflow.

The private immutable `FrozenPromptRequest` carries request/index/digest/client
correlation, encoded body, destination and expected standard image nodes.
The destination comes only from frozen `comfyui_endpoint`; HTTP(S) host and
optional port are supported, without credentials, query, fragment or non-root
path. No independent workflow, endpoint or output-directory argument exists.
Preparation performs no DNS lookup, HTTP call or file operation.

Legacy `prepare_prompt_request`, `comfy_prompt_submission`, `comfyui` and Gallery
callers retain their existing behavior, including submission-time random seeds.
The new executor must not call that legacy request randomizer. The real legacy
submission/download owners are not called or wired by this slice.

## Private executor integration seam

`ui.agent_generation_comfy_executor.ComfyExecutorAdapter` takes one C2B-3 offer
through the existing inbox, exactly once. It checks job binding and the ordered
registry requests before invoking callbacks. The adapter owns one accepted
envelope and one submission attempt per physical request; it cannot take a
second envelope or resubmit a consumed claim.

Only injected synchronous `fake_transport(prepared)` and
`fake_result_provider(prepared, prompt_id)` callbacks run, outside owner locks.
The transport returns typed `SubmissionResult`; the provider returns typed
`ExecutionResult` with exact request and prompt IDs and bounded `ComfyProgress`.
The original host's event sink delivers `ExecutorEvent` through C2B-3's target
and pairing gate. The adapter receives no Project, Streamlit state or widget.
An eventual worker belongs at the external submit/progress/result seam before
Gallery ingestion, with the same private input and original-host event delivery.
There is no production callback registration or worker creation here.

The existing registry remains the only state owner. Its narrow added transitions
are `awaiting_result -> awaiting_result` for count-only `execution_progress`
and `execution_timeout`,
`awaiting_result -> awaiting_download` for `remote_outputs_ready`, and
`awaiting_download -> awaiting_host_registration` for the existing local
`outputs_ready` event. Remote counts have their own public `remote_output_count`;
local output counts and registered counts remain zero at the remote boundary.
Progress emits no remote diagnostics or raw step payload, at most four events
per request. Existing job event limits, sequence checks and job-before-inbox
lock order are unchanged.

Timeout emits a distinct count-only `execution_timeout` at most once per
request, while provider uncertainty remains `execution_outcome_unknown` and
ordinary pending remains `awaiting_remote_result`. Repeated timeout cannot
renew the original job lease, retry submission or advance to the next request.

A remote receipt can resolve remote execution ownership. It does **not** settle
download/containment/registration ownership. `advance_for_characterization`
pauses at `awaiting_download` and can submit the next request only after separate
original-host characterization of local outputs and publication settles that
request as completed, partially failed or failed. Tests exercise fake registry
counts only; no Candidate is created. This conservative sequencing also keeps
unresolved submissions from overlapping later requests.

## Ambiguity and no retry

`submission_started` is accepted by the host before transport runs. A trusted
`rejected_before_submission` classification proves no send and settles that
request as failed; a missing reply, thrown exception, timeout, malformed response
or duplicate/invalid prompt ID is `submission_outcome_unknown`. Accepted prompt
IDs must be canonical UUIDs and unique within the envelope. Unknown submission
is terminal for automatic scheduling, leaves later requests unsent, and pins
consumed custody. Deadline cleanup is not evidence of remote cancellation and
does not grant another take or attempt.

After valid prompt acceptance, an execution timeout/unknown result remains
`awaiting_result`, not a definite failure or a new submission. Only an explicit
later exactly correlated result can resolve that accepted execution. No polling
loop, retry or auto-advance runs. A trusted definitive execution failure can
settle the request; a remote metadata receipt pauses for future containment.
Duplicate or conflicting terminal results cannot overwrite a receipt or fail
the next request. Callback reentry cannot create a second submission.

Normal completed/partially-failed/failed progress before handoff returns retains
the original observed acceptance, as in PR #150 FIX-1. Target switch, Save As,
pairing replacement, disarm, close, lost ownership and unknown submission retain
their invalidation fences. Late metadata may enter a private bounded quarantine,
but never becomes authoritative remote/local/publication progress.

## Remote metadata trust boundary and limits

`core.comfy_remote_output_receipts.validate_remote_outputs` checks the frozen
prepared request again and produces immutable private `RemoteOutputReceipt` and
`RemoteImageDescriptor` values. Every identity includes job, claim, manifest,
request/index/digest, prompt and expected node plus remote lookup components.
SHA-256 identities remain stable across JSON object/image ordering. They are
private correlation identities, not content hashes or evidence of downloaded
image bytes.

Validation is all-or-nothing. The history must contain exactly the accepted
prompt and all expected standard SaveImage/PreviewImage nodes, with matching
output/temp buckets and nonempty image lists. When status is present it must
confirm successful completed execution. Duplicate JSON keys, non-JSON numbers,
unexpected nodes/fields, missing images, duplicate lookup descriptors, malformed
or unsafe filename/subfolder components, unknown formats and oversized batches
are quarantined without retaining or exposing rejected raw data. Formats reuse
the existing image-recognition owner: png, jpg/jpeg, webp, gif and bmp. File
extension recognition is not validation of local image contents.

Each raw submission/history payload is limited to 64 KiB; parsing also limits
JSON nodes to 2,048 and text to 64 KiB. Each batch holds at most 16 images,
filenames at most 255 characters and subfolders at most 1,024. Receipt retention
has a conservative 512 KiB aggregate encoded-size budget; capacity exhaustion
leaves the request unresolved and blocks later submission. Authoritative
receipts are never silently evicted. Late receipts have a separate maximum of
16 batches under the same aggregate budget. The envelope retains C2B-3's
100-request, 1,000,000-byte workflow and 8 MiB aggregate limits.

Remote components are private lookup metadata only. Absolute paths, traversal,
control characters, URL/drive separators, percent escapes, reserved Windows
names and ambiguous trailing dots/spaces are rejected. Even a valid remote name
is never used as a local destination. Public job events carry bounded counts
and opaque correlation only: no filename, subfolder, endpoint, URL, raw history
or transport exception detail.

## Remaining gates

A separate authorized slice must implement host-approved contained download
destinations, bounded actual downloads, local image validation, cleanup and
original-host publication/save receipts. It must preserve the target/pairing
gate and define explicit human recovery for unknown or lost ownership. A later
slice must then authorize real transport/worker lifecycle and explicit Start UI,
with exact review confirmation retained. MCP execution remains unavailable.
This adapter alone cannot download, register, save, reopen a proposal or enable
production Start.
