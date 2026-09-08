# Incremental app extraction

The initial extraction (PR #2) was implemented against public
`prompt-graph-lab/promptgraph` main commit
`8462a54cbbf4984e1f224e07041b53df00209d22`. That baseline's `app.py` has
24,900 lines and 634 top-level functions. That change moved 11 functions into
two responsibility-specific modules; `app.py` remains the Streamlit entry point.

## Responsibility and dependency map

The complete top-level function/import inventory and startup block identify
these current owners. Function names are navigation anchors rather than a
proposed new package hierarchy.

| Responsibility in app.py | Representative owners | Dependencies and coupling |
| --- | --- | --- |
| Startup and UI composition | top-level state initialization, page configuration, Sidebar and main workspace dispatch | `core.settings`, `core.startup`, `core.version`, Streamlit; executes on every rerun |
| Editing context and navigation | `open_management_workspace`, `reset_*_session_state`, graph selection, Focus navigation | Shared session keys, widget mirrors, pending resets, Project switching |
| Undo and persistence orchestration | `push_history`, `undo`, `load_project_json_into_session`, Save As confirmation helpers | `Project.clone`, `core.io`, settings, filesystem snapshots, rerun/reset ordering |
| Project management and assets | `render_project_management_workspace`, discovery, import, fork and asset panels | `core.project_discovery`, `core.new_project_workspace`, `core.project_root_import`, `core.lightweight_fork*`, `core.io`; preview/confirm/apply lifecycle |
| Prompt inspection and editing | syntax diagnostics, source/current diffs, batch previews, line editors | `core.parser`, `core.operations`; pure calculations are mixed with rendering and mutation callbacks |
| ComfyUI preparation and execution | `build_single_line_workflow`, `_build_focus_line_workflow_preview`, `_run_current_line_comfy_multiple` | Embedded metadata, shared path/settings, Module expansion, `core.comfyui`, execution logs and Candidate ingestion |
| ComfyUI analysis workspace | workflow inspector, LoRA mapping, generation/negative consistency panels | `core.comfy_workflow`, `core.lora_mapping`, analysis modules, session draft widgets; explicit inspector injection differs from generation binding |
| Candidate and Gallery Variant lifecycle | candidate normalization, prompt adoption/revert, image swap, Variant and alternative Scene creation | Mutable `PromptLine` fields, lineage, paths, session cache, history/autosave; not merely display data |
| Gallery and Scene operations | `render_pro_gallery_mode`, cards, pagination, route actions, generation/adoption/promotion panels | `core.route_operations`, selected-route operation modules, shared scope selection, pending widget resets |
| Import, sequence preview and final export | metadata import, `render_sequence_preview_panel`, `render_gallery_final_image_export` | `core.io`, image paths, explicit export scope and destination; source files must remain intact |
| Graph and Focus editing | graph browser, Focus panels, batch editing, selected-token actions | `core.graph_builder`, `core.graph_edit_illustration_browser`, `core.operations`, graph/PromptCloud components, unsaved editor state |
| Module and Attribute management | Authoring/Apply workspaces, library manager, candidate scanner, Inspector, Attribute Group panels | `core.modules`, `core.operations`, `core.module_library_search`, AnimaDex modules, authoritative Global Library cache and Project-local metadata |
| UI infrastructure | profiling, thumbnails, keyboard shortcuts, HTML compatibility wrapper | timing/session state, disk cache/Pillow, iframe JavaScript; context and lifecycle must remain explicit |

`core.project` owns the persisted domain objects; `core.io` owns Project
serialization, metadata and asset/export I/O; `core.operations` owns most token,
Module and Attribute transformations. Existing focused operation modules already
provide preview/apply boundaries. The remaining app-level coupling is chiefly
session state, history/save ordering, filesystem resolution and UI rendering.
Importing `app.py` executes the UI, so extracting functions by importing the app
back into a new module would create the wrong dependency direction.

## Initial extraction (PR #2)

1. **Prompt inspection — `core.prompt_inspection`.** Structural statistics,
   Module reference names, suspicious NovelAI fragments and source/current token
   differences now have an importable, read-only owner. The app still formats
   warnings, captions and preview widgets. The parser is unchanged. In particular,
   the display diff continues to split literal commas, count duplicate occurrences
   and compare case-sensitively; it has not been replaced by syntax-aware parsing.
   Structural statistics still use `core.operations.get_display_tokens_from_text`.
2. **Workflow prompt binding — `core.comfy_prompt_binding`.** The generation
   path's sampler/upstream text-node traversal, CLIP fallback replacement and
   submitted-prompt diagnostics now share one owner. This module has no imports,
   Streamlit state, filesystem access or network execution. Replacement still
   mutates the caller-supplied workflow in place and returns assignment count;
   debug inspection is read-only. File/metadata selection, Module expansion,
   JSON parsing, group mapping, placeholders, settings and submission stay with
   their existing owners. Existing internal function names are retained.

These boundaries avoid moving widget ownership or Project mutation. App imports
the extracted functions directly; there are no forwarding wrappers, callbacks
back into app, service containers or new persistence formats. The moved function
ASTs match the baseline exactly; the remaining app AST matches after excluding
the new imports. The net app reduction is 230 lines, not the acceptance criterion.

The similar helpers in `core.comfy_workflow` are deliberately not merged here:
that inspector accepts additional wrapper shapes and offers explicit node
selection, whereas the generation path traverses upstream connections and has
its own metadata/single-CLIP fallback rules. Unifying them would require a
separate behavior decision.

## Initial extraction validation

- `setup.bat`: fresh application-local CPython 3.14.4 environment on Windows 11
  build 26200; all 54 locked runtime packages match, `pip check` passes.
- 18 direct regression tests cover duplicate/case/order/Unicode/empty prompt
  diagnostics, literal-comma diff behavior, sampler roles, upstream cycles and
  missing links, wrapped nodes, metadata/single-node fallback, ambiguous no-op,
  empty replacement prompts, shared nodes and read-only debug output. These
  same tests also pass against the original main function definitions.
- Five app-caller integration tests use the actual extracted imports with the
  retained renderer/builders. They cover warning rendering, JSON placeholder
  escaping, group-map routing, embedded workflow priority, Module expansion and
  a legacy Project load/preview/save/reopen round trip without changes to its
  serialized data, line objects or workflow source file.
- `.venv/Scripts/python.exe -m unittest discover -s tests -v`: 969 tests in
  232.970 seconds, no failures, eight existing skips for unavailable Windows
  symlink privileges (961 passed). The runtime lock still matches after testing.
- Browser smoke test on the running locked Streamlit app, using disposable
  synthetic images, prompts and a local workflow: direct JSON Open, Gallery
  Scene expansion and Candidate display, Graph Edit to Focus Edit, Module-name
  and NovelAI diagnostics, shared-workflow preview with expanded positive and
  negative prompts, manual prompt edit/Save Changes and Project save. The
  persisted JSON contains the edited prompt and unchanged negative prompt.
  Only the Codex in-app browser was available; Edge/Chrome were not verified.
  No live ComfyUI generation was submitted.

## Module token rules extraction

The next step starts from public main `3e944c1` (the merge of PR #2). Seven
read-only helpers move to `core.module_token_rules`: rule-text parsing,
rule/body formatting, body tokenization, match keys, match-key sets and
Inspector deduplication. The only dependency is the existing `core.parser`.
`app.py` imports the same names directly; the moved function ASTs and the
remaining app AST are unchanged apart from this import. This step reduces the
app from 24,670 to 24,633 lines and from 623 to 616 top-level functions.

These helpers serve the Global Library editor, Project Module editor, Module
Inspector, Module-match preview, core-token draft initialization and Attribute
Group token input. Their shared responsibility is translating between editable
token text and comparison keys. They do not own Module graph normalization,
validation, application to Illustrations, or stored Module entries.

The distinction between rule parsing and Inspector deduplication is intentional:
rule input retains `smile` and `(smile:1.2)` as different literal forms, while
Inspector deduplication compares parser base words and retains the first form.
Both continue using `lower()`, not `casefold()`. Body parsing and formatting
preserve duplicates and order. Structural Module markers keep their fallback
keys, while the unchanged preview renderer excludes them from highlighting.

All renderers, draft/widget keys, Project mutations, history, attribute updates,
save/load and ComfyUI preparation remain in their existing owners. Moving the
entire Inspector would also move those stateful responsibilities; this step
stops at the token boundary.

Validation adds 11 direct regression tests and five retained-renderer integration
tests covering weighted/Unicode/duplicate/empty inputs, first-form retention,
non-mutating helpers, core highlighting, Add Token and Update Body draft behavior,
preview escaping and Attribute Group input. The direct tests also pass against
the original main definitions. Two existing workspace-state test loaders now
execute the real app import instead of extracting the moved definitions; their
14 draft/navigation/save/reset tests continue to pass.

The full suite (`.venv/Scripts/python.exe -m unittest discover -s tests -v`)
runs 985 tests in 237.336 seconds: 977 pass, eight existing Windows symlink
privilege skips, no failures. The same 54-package runtime lock and `pip check`
also pass. Browser results for this step are recorded in its PR.

The browser smoke test uses an isolated synthetic Project in the running locked
app: open Authoring from Gallery, inspect weighted Core rows, Update Body From
Inspector, Add Token, and Back/reopen with unsaved body/Core drafts intact.
Save Project Module applies the draft to the in-memory Project; the Sidebar
save writes the Project JSON. These remain separate existing actions.

## Workflow preparation extraction

Starting from public `main` commit `2301030a63e0d99a53e6de900ae424f5c1fdb80d`,
`core.comfy_workflow_preparation` now owns the pure text-to-workflow step
`_build_line_workflow_from_text`. It preserves the existing three branches:
group mapping delegates to `build_prompt_by_group` and
`inject_prompt_to_workflow`, `__PROMPT__` replacement keeps the existing JSON
escaping, and ordinary API workflows use the existing CLIP binding helper and
warning. The new module does not import `app.py`.

`build_single_line_workflow` and `_build_focus_line_workflow_preview` remain
the callers. They still own metadata/file selection, shared settings and
session state, active-token expansion, and preview source labels. ComfyUI
submission, Candidate handling, Project mutation, history, and persistence
remain outside this boundary. The extraction therefore does not change the
Project schema, save/load behavior, or UI/session ownership.

Focused regression tests cover the extracted helper's group mapping,
placeholder escaping, missing-binding warning, retained single-line caller,
retained Focus preview caller, and the legacy Project preview/save round trip.
The clean full suite run at the implementation commit runs 994 tests in
239.376 seconds: 986 pass, eight existing Windows symlink privilege skips,
and no failures. A later rerun at `ebaf9e9` was captured in
`tmp/workflow-preparation-full-suite.log` and exhausted the Windows Python
process memory while Streamlit-heavy tests read or compiled `app.py`: it ran
989 tests and ended with seven errors plus eight skips. The affected checks
were the two Project Save As UI cases
(`test_path_change_invalidates_confirmation_without_writing_either_target`
and `test_successful_project_open_clears_pending_confirmation`), the Save As
snapshot setup, four release-runtime contract checks
(`test_active_app_has_no_removed_width_keyword`,
`test_common_x86_64_architecture_label_is_supported`,
`test_direct_requirements_are_exactly_the_six_validated_pins`, and
`test_exact_runtime_lock_environment_passes`); the traceback for each ends in
`MemoryError` while reading/compiling source or constructing the affected UI.
The clean result remains the authoritative full-suite evidence for this
application-only change. The Codex in-app browser smoke uses a disposable synthetic
Project and workflow: it auto-opens the Project, enters Graph Edit and Focus
Edit for `smoke.png`, and expands the workflow preview. The preview shows
positive `smoke, prompt`, negative `old negative`, and unchanged sampler
links. Editing the prompt to `smoke, verified`, saving the Focus changes,
using the Sidebar Project save, and reloading preserves the edited token and
the unchanged negative prompt in the disk JSON. No generation is submitted.
Edge/Chrome and a live ComfyUI endpoint are not verified.

## Remaining risks and next boundaries

There is no Project schema or save/load change. This does not establish support
for every third-party ComfyUI node graph. For example, a node connected to both
positive and negative roles still receives the negative assignment last and
counts twice; this existing behavior is characterized, not corrected here.
The literal-comma display diff also retains its existing grouping limitations.

Execution preparation around the retained single-line callers has now been
characterized without moving code. Focus generation and the legacy single-line
builder still combine workflow source selection, active-token expansion, and
the call into the pure text-to-workflow builder. The multi-run caller combines
settings/session fallback resolution, progress UI, live submission, output
capture, Candidate mutation, persistence, and execution logging. The focused
characterization tests pin the settings fallback, missing-workflow error,
copied injection line, per-run file-prefix ordering, and warning/logging
contracts. There is no natural extraction left in this slice without crossing
one of those owners or introducing a callback-only wrapper, so the callers
remain in `app.py` until a separate execution request or submission owner is
designed. Any panel extraction must document and test its session/widget keys
and history/reset contract through navigation tests.

## Prompt request construction

Following PR #7, the next coherent boundary is inside `core.comfyui`, rather
than another app wrapper. `core.comfy_prompt_request.prepare_prompt_request`
accepts an already prepared workflow dictionary and server address, and returns
the normalized address, generated client ID, and an unsent urllib Request.
It preserves in-place numeric seed randomization (including bool/float values),
iteration order, JSON encoding, URL normalization and preparation exceptions.
It does not unwrap workflow nodes or expand prompts. This is request construction,
not a pure function: UUID/random generation and workflow mutation are intentional.

`generate_image_with_progress` calls it lazily before its first status yield.
HTTP submission, connection errors, WebSocket progress and output capture remain
in that generator. All app callers, source selection, active-token expansion,
session/UI ownership, Candidate handling and Project persistence remain unchanged.
The moved statements and remaining core AST are equivalent after inlining the
helper; app.py is byte-for-byte unchanged. Deterministic tests cover request
bytes, mutation, wrapped workflows, failure order and generator laziness.

## HTTP prompt submission

Following PR #8, `core.comfy_prompt_submission.submit_prompt_request` accepts
the already constructed urllib Request and normalized server address (used in
error text), and returns the response's truthy `prompt_id` without coercion.
It owns only `urlopen(req)`, context-managed response reading, JSON decoding,
ID lookup and validation. The original `URLError` translation covers the same
try block, including context exit; malformed JSON and non-object response
errors still propagate. Falsey IDs fail only after the response context exits.

Request preparation remains before the Connecting status yield; submission
remains between that yield and Prompt queued. Both yields, generator laziness,
WebSocket creation/lifecycle, progress, timeout, history polling and output
capture remain in `generate_image_with_progress`. `app.py` is unchanged.
Mocked transport tests establish success, exact request identity, context
lifetime, exception ordering, ID semantics and the generator event sequence.
The moved statements and remaining core AST match after helper inlining.

## WebSocket connection setup

Following PR #9, `core.comfy_websocket_setup.connect_progress_socket` accepts
the normalized server address and client ID and returns the connected socket
after `settimeout(1.0)`. Construction remains outside the setup try block;
constructor exceptions propagate unchanged, while connect/settimeout failures
retain the existing `Failed to connect to ComfyUI WebSocket: ...` wrapping.
The exact URL and call order are unchanged. Setup happens only when iteration
resumes after the Prompt queued yield, following HTTP submission.

Cleanup remains in `generate_image_with_progress`. It closes on normal
execution completion and execution timeout. It does not close on setup failure,
receive-loop failure, execution_error, or early generator close during execution.
Closing the generator before setup constructs no socket. A receive timeout
retries until the existing execution timeout policy applies. These asymmetric
contracts are characterized on the baseline before extraction, not repaired.
Receive interpretation, progress, completion detection, timeout policy and
output polling/capture remain unchanged, as does app.py. Fake-socket tests and
AST inlining checks verify the boundary without a live server.

## Received-message interpretation

Following PR #10, `core.comfy_message_interpretation.interpret_progress_message`
accepts one received payload and the submitted prompt ID. It returns
`(completed, event)`: ignored payloads return `(False, None)`, completion
returns `(True, None)`, and status/progress messages return the existing event
dictionary. It performs no socket operations and mutates no inputs.

Baseline characterization pins non-string payloads being ignored, malformed
JSON/non-object failures, unknown types, completion ID/node comparisons,
progress defaults and the existing unclamped 0.1 + ratio * 0.8 scaling.
Execution errors retain their text/defaults. Parsing and interpretation errors
still reach the generator's original exception wrapper; no validation or
broader catching was added. The AST matches when helper returns are converted
back to the original yield/break statements and the adapter is inlined.

`generate_image_with_progress` still owns recv, receive-timeout retries,
execution timeout, status yielding, socket close, lifecycle and output polling.
app.py is unchanged. Existing early-close and failure cleanup semantics remain.
## History/output polling contract

Following PR #11, `_poll_comfy_output_history` remains in its existing core
owner; this step adds characterization only. Its inputs are server address,
prompt ID, workflow, and keyword-only max_attempts (default 8) and
interval_seconds (default 0.75). It already delegates history lookup, image
extraction and failure-status interpretation to focused helpers, so another
move would not establish a useful smaller responsibility.

Each attempt fetches history, interprets it and appends a log containing
attempt (one-based), history_found (truthiness of the resolved record),
outputs_keys (ordered extraction output_node_ids), and
save_image_nodes_with_outputs. Images take precedence over failure status;
either ends polling. Success/non-failure status without images retries.
Sleep receives the interval unchanged only between continuing attempts, never
after success, failure-status exit or the final attempt. Nonpositive integer
attempt counts perform no fetch; invalid attempt types are not normalized.

Only history-fetch exceptions are swallowed: history becomes {}, the exception
string is recorded/logged, and normal interpretation/retry continues. A later
successful fetch clears the error even when its result has no images.
History interpretation, extraction, status checking and sleep exceptions
propagate. Diagnostic formatting is unchanged.

The result keys are history, prompt_history, outputs, extraction, image_infos,
attempt_logs, last_history_fetch_error and save_image_node_ids. History and its
resolved record/outputs retain their existing references; image_infos aliases
extraction.images. Returned state describes the final attempted fetch, with all
attempt logs retained. Zero attempts return initialized empty state plus the
workflow's SaveImage node IDs.

`generate_image_with_progress` still owns the surrounding lifecycle, missing
image diagnostics and subsequent image downloading/path saving. No runtime or
app.py change is made. The next natural step is characterization of the existing
image-record extraction helper's precedence, deduplication and compatibility
rules, rather than a broad history/transport abstraction.

## Image-output extraction

Following PR #12, three deterministic helpers move unchanged to
`core.comfy_image_outputs`, with their original names still imported by
`core.comfyui`. Recognition accepts nonempty string filenames whose lowercased
splitext extension is png/jpg/jpeg/webp/gif/bmp; it does not validate paths.
Collection traverses dictionaries/lists in insertion order. An images/gifs list
is treated as terminal records, not recursively searched. Records keep filename,
subfolder (default empty), type (default output) and exact indexed _debug_path.

Extraction inspects string-normalized configured SaveImage IDs first. Any images
there suppress fallback; otherwise all dictionary output nodes are scanned.
Output keys themselves are not normalized for lookup: numeric keys can miss the
SaveImage pass but be found in fallback, retaining numeric _node_id. Diagnostics
stringify output IDs and can collapse numeric/string key collisions.

Deduplication uses (filename, subfolder, type), retaining the first record and
its node/path; diagnostic image_like_fields retains duplicates. Explicit field
values are not sanitized; unhashable subfolder/type values still raise TypeError.
The six result keys remain images, image_like_fields, save_nodes_with_outputs,
save_node_output_keys, output_node_ids and output_keys_by_node. Inputs are not
mutated. Baseline characterization passes before movement; moved and remaining
ASTs match. app.py is unchanged.

History fetch/selection, polling/retry/sleep, status interpretation, diagnostics,
download and path saving remain in their existing owners. Next, characterize
the existing output-diagnostic construction/formatting contract before deciding
whether it needs a separate owner; do not combine it with transport or polling.

## Output-diagnostic contract

Following PR #13, diagnostic construction/formatting is characterized in place.
The builder depends on existing history sampling, status interpretation and
workflow classification helpers. Moving it now would require moving excluded
owners, importing back from comfyui, or dependency plumbing; this step therefore
changes tests/docs only. app.py and all runtime code remain unchanged.

The ordered diagnostic keys remain queued_prompt_id, history_prompt_ids_sample,
target_history_found, target_status, target_status_messages, target_outputs_keys,
save_image_node_ids, save_image_outputs_found, save_image_nodes_with_outputs,
save_image_node_output_keys, workflow_node_count, workflow_save_image_node_ids,
workflow_output_node_ids, attempt_count, last_history_fetch_error and attempts.
History sampling keeps the first eight stringified keys. Status messages keep
the first five; attempts keep the final COMFY_OUTPUT_POLL_ATTEMPTS records.
Both slices copy the container but retain record references. SaveImage ID lists,
extraction node lists and node-output-key dictionaries are stored directly.

Status and raw/wrapped workflow compatibility remain with existing helpers.
Output keys retain insertion order and original types. Presence flags use
truthiness; the error field uses `value or "none"` without coercion. Formatting
retains the exact multiline wording, order, punctuation, no trailing newline,
Python representations and yes/no truthiness. Missing fields and explicit None
format as None; extra keys are ignored. Malformed inputs and failing str/repr
operations propagate rather than being caught. Neither operation mutates inputs.

Polling/generator owners still assemble inputs and decide when diagnostics are
used; transport, image extraction, status/classification semantics and download
remain outside this step. Next, review the existing generator-to-diagnostic
integration for missing-output failure evidence before considering any further
owner change; do not force another extraction solely to reduce file size.

Candidate normalization is a later candidate: first separate its path
resolution, record compatibility and session-cache dependencies from adoption
mutations.
Moving all Gallery or all Module UI at once would cross too many of those owners.

Unrelated observations: the locked Streamlit runtime emits an existing
`st.components.v1.html` deprecation warning. The keyboard/clipboard iframe
compatibility owner is unchanged; replacing it is outside this extraction.
The Module token rules smoke test also reports a `gallery_page_size` warning
about assigning both a widget default and session state. Its unchanged Gallery
pagination owner is outside this extraction as well.
The synthetic save check also exposes an existing compatibility limitation:
Project Module Editor calls `core.operations.set_module_entry`, which replaces
the entry and drops unknown extension fields (reproduced with a synthetic
`extension` key). The same unchanged core function reproduces this on the base
main revision. This differs from the metadata-preserving Global Module editing
path and is recorded for separate investigation, not changed or generalized
as part of token extraction.
