# Agent Candidate metadata observation

The first [Phase 4 audit slice](agent-generation-candidate-audit.md) exposes
`promptgraph_list_candidates` and `promptgraph_get_candidate`. Both are read-only
and require one explicit active normal `illustration_id`. They observe captured
persistent `PromptLine.generated_candidates` only; session-only cache entries
are excluded. They do not reconcile/normalize records or infer focus/selection.

## Contract and metadata

List accepts `illustration_id`, optional `limit` (integer 1–100, default 100),
and optional `include_trashed` (boolean, default false). Get accepts
`illustration_id`, `candidate_handle` and optional `include_trashed`. Unknown
arguments, types and bounds are rejected before Project capture. Unknown or
ambiguous Illustration IDs, deleted/separator/Workbench targets and malformed
Candidate records fail closed with bounded reasons.

List returns `candidates`, `total_count`, `truncated`, and
`persistent_records_only: true`. Pinned records come first, with stable persisted
order inside each group. Trash is excluded by default. This slice exposes
explicit truncation, not page continuation. Legacy path strings produce
metadata-empty rows; same-path duplicates remain separate observations.

Internal processing accepts at most **1,000 persistent records** per
Illustration, including Trash, independent of the public result limit.
Collections above that cap fail closed with `candidate_collection_too_large`.
The complete private revision snapshot also has an aggregate budget of 20,000
JSON nodes and 1,000,000 string characters (including keys and unknown metadata),
with the existing depth limit of 32. Excess fails closed with
`candidate_observation_bounds_exceeded`; no partial revision or handles are
issued. Accepted collections retain full revision coverage, accurate filtered
counts and stable order even when the public result is truncated. List/Get
validation and signing scan at most the capped collection; no persistent
Candidate index or cache is added.

Each row contains only its opaque handle, Illustration ID, pinned/trashed/selected
flags, legacy-record flag, a small known source classification (otherwise
`unknown`), integer seed (including zero; null when absent), bounded
positive/negative prompt text and `image_availability: "unknown"`. Text uses the
facade's 4,000-character bound with length/truncation fields. Existing Candidate
inspection owns prompt-field priority and the manual-import metadata source
gate. Workflow-shaped JSON prompt values are suppressed. Nested/raw metadata,
workflow/lineage objects, image paths and workflow filenames are not projected.

Known generation sources include the actual `app.py` producers
`single_generate`, `multi_generate`, `gallery_generate`, and
`gallery_global_generate`; unrecognized source strings remain `unknown`.

No visual quality or prompt/image consistency is inferred. `selected` compares
references using existing selected/generated Candidate precedence; it does not
prove file existence. Generation, image/prompt adoption, history and save are
unavailable through these tools.

## Handle scope and lifetime

[Signing owner](../../core/candidate_observation_handles.py) retains only a
process secret and weak Project identity nonces, never Candidate records or
filesystem state. Handles are keyed HMACs over private binding, full persistent
Candidate collection snapshot, relevant Illustration prompt/main-reference/
provenance state, Project line identity/order/type/deletion structure, persisted
record index and a five-minute monotonic clock window. Raw paths stay private
fingerprint inputs; neither paths nor plain path hashes cross the boundary.

The paired host binding also includes the explicit registered session route,
Project path, target
epoch and pairing generation, using the original Project's weak identity across
fresh request-scoped clones. Standalone calls bind to the supplied Project
object; replacing it with a clone invalidates handles. Remaining lifetime is at
most 300 seconds: expiry is at the next process-clock window boundary. Restart,
binding change or snapshot change invalidates a handle. Re-list after expiry.

Handles are content-bound observations, not durable record IDs. Removing,
reordering, pinning, Trashing or editing records invalidates current handles;
restoring the exact snapshot within the same window can reproduce the same
handle. Get re-resolves the explicit Illustration and recomputes current
handles. Unknown/stale handles share one bounded error. Trash observations still
require `include_trashed: true` at Get. Handles grant no file/adoption authority.

## Host and filesystem safety

The existing facade -> adapter/catalog -> SDK -> paired host request route is
reused. The adapter retains no Project, Candidate or handle results; its binding
provider is a trusted host seam, not a tool argument. Validation precedes the
single request capture, the bridge checks current run/Project before reply, and
the session mailbox guards target-epoch/pairing freshness around service and
publication. Transport never reads Streamlit state.

Availability is always `unknown`: no safe host containment resolver is used
here. There are no filesystem probes, reads, downloads or file-serving endpoints,
including for traversal, outside-root absolute paths, Windows drive-relative,
rooted/UNC paths or symlinks. A reference is not containment evidence or access
permission. Verified contained availability and bounded image observation are
later work. These tools do not promise to count every transient Gallery card.

[Focused tests](../../tests/test_agent_candidate_observation.py) cover bounded
metadata, order/Trash/legacy/duplicates/source gates, falsey and malformed values,
unknown/stale identities, schema-before-capture, forbidden file probes,
repeated-call immutability, official SDK calls and paired release/re-pair.
Existing facade/adapter/bridge/SDK and transport tests provide compatibility
coverage. No generation/job service, adoption preview/Apply, image transport,
Gallery redesign, export or new persistence schema is added.
