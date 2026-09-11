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
| Project management and assets | `render_project_management_workspace`, discovery, import, fork and asset panels | `core.project_discovery`, `core.new_project_workspace`, `core.project_root_import`, `ui.project_root_import_session`, `core.lightweight_fork*`, `core.io`; preview/confirm/apply lifecycle |
| Prompt inspection and editing | syntax diagnostics, source/current diffs, batch previews, line editors | `core.parser`, `core.operations`, `core.batch_preview`; rendering and mutation remain coupled to the app |
| ComfyUI preparation and execution | `build_single_line_workflow`, `_build_focus_line_workflow_preview`, `_run_current_line_comfy_multiple` | Embedded metadata, shared path/settings, Module expansion, `core.comfyui`, execution logs and Candidate ingestion |
| ComfyUI analysis workspace | workflow inspector, LoRA mapping, generation/negative consistency panels | `core.comfy_workflow`, `core.lora_mapping`, analysis modules, `ui.comfyui_analysis_drafts` session draft controller; explicit inspector injection differs from generation binding |
| Candidate and Gallery Variant lifecycle | candidate normalization, prompt adoption/revert, image swap, Variant and alternative Scene creation | Mutable `PromptLine` fields, lineage, paths, session cache, history/autosave; not merely display data |
| Gallery and Scene operations | `render_pro_gallery_mode`, cards, pagination, route actions, generation/adoption/promotion panels | `core.route_operations`, selected-route operation modules, shared scope selection, pending widget resets |
| Import, sequence preview and final export | metadata import, `render_sequence_preview_panel`, `render_gallery_final_image_export` | `core.io`, image paths, explicit export scope and destination; source files must remain intact |
| Graph and Focus editing | graph browser, Focus panels, batch editing, selected-token actions | `core.graph_builder`, `core.graph_edit_illustration_browser`, `ui.graph_edit_browser_controller`, `core.operations`, graph/PromptCloud components, unsaved editor state |
| Module and Attribute management | Authoring/Apply workspaces, library manager, candidate scanner, Inspector, Attribute Group panels | `core.modules`, `core.operations`, `core.module_library_search`, `ui.global_module_library_session`, `ui.project_module_inspector_session`, AnimaDex modules, authoritative Global Library cache and Project-local metadata |
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
3. **Batch preview calculations — `core.batch_preview`.** The read-only
   highlight, token-query, replacement-preview, duplicate-mark, snippet,
   focus-selection and removed-marker calculations now have an importable
   owner. They preserve the existing parser, escaping, matching, ordering,
   falsey/default and direct-exception behavior. Batch preview rendering,
   Streamlit containers, widget/session state and prompt mutation remain in
   `app.py`; the module has no UI, persistence or Project ownership.

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

## Missing-output integration

Following PR #14, tests characterize the retained generator orchestration;
no runtime extraction is warranted. After execution completion/close, the
Execution done. Fetching image... status (0.95) is yielded before polling.
Resuming calls the poller with server address, prompt ID and the same workflow.
The eight required poll-result keys are read directly, then extraction metadata
output_node_ids/output_keys_by_node/image_like_fields is read with existing
defaults. Missing keys and malformed values are not normalized.

Falsey image_infos triggers diagnostic construction with the original poll
objects and workflow, and attempt_count=len(attempt_logs). The generator warns
with `Comfy output missing after polling: %s`, formats the same diagnostic
object and raises ComfyOutputError. Truthy diagnostics retain identity; falsey
diagnostics use the exception's existing empty-dict fallback. No directory
creation, URL building, download, file write or done event occurs on this branch.
Truthy image_infos proceeds toward directory creation without missing-output
diagnostics. Poller/builder/logger/formatter failures propagate directly.

Tests reuse the real diagnostic helpers for integration and mocks for ordering
and short-circuit evidence. Generator lifecycle, polling internals, downloading,
diagnostic wording and app.py remain unchanged. The next candidate is bounded
characterization of download-phase failure/partial-success orchestration using
fake responses and temporary output paths, before considering any extraction.

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

### Download-phase characterization (runtime unchanged)

Offline tests now pin the generator's download phase after truthy polled
`image_infos`. Directory creation (`exist_ok=True`), required filename lookup,
subfolder/type defaults, URL encoding and unique-path selection precede the
per-image exception handler: their failures propagate without download warnings.
The normalized server address is used verbatim; `urlencode` receives filename,
subfolder and type in that order. The URL is recorded before path selection;
paths use the original `file_prefix + "_" + filename` composition.

HTTP open/context entry, response read, binary file open/write and context exit
are inside the handler. Failures produce the existing filename/error warning
and a 0.95 warning event, then processing resumes at the next record. A path is
successful only after both contexts exit; this does not guarantee that failed
attempts leave no local bytes. Partial success emits `done` with the first
successful path and all successful paths, retaining attempted URLs and errors.
Total failure emits the individual warnings before the existing generic
exception with prompt, output metadata, attempted URLs/count and error evidence.

The exact final event includes output metadata, original image records,
attempted URLs, saved paths and errors, plus attempt count/logs and SaveImage
node diagnostics. Polling, generator yields/lifecycle, downloading and file
ownership remain in `generate_image_with_progress`; runtime code and `app.py`
are unchanged. The next smallest candidate is the single-image HTTP response
read/binary-write operation with explicit URL and save-path inputs, characterized
against these context-exit/error contracts before extraction. Keep warning
emission, aggregation, path selection and generator ownership separate.

### Single-image download extraction

`core.comfy_image_download.download_image_to_path(image_url, save_path)` now
owns only HTTP open, response entry/read, binary file open/write and both
context exits. It returns `None` on completion and catches or wraps no exceptions.
The original nested statements were moved unchanged; direct offline tests pin
bytes, ordering and exception identity, including failures from context exits.
The download-phase integration tests remain unchanged.

The generator retains directory creation, record lookup, URL/path construction,
attempted URLs, successful paths, warning text/yields, continuation and all
aggregation. Path registration still follows successful helper return, so a
response-exit failure can leave bytes while producing a warning instead of a
successful path. Partial success, total failure and the final event are unchanged.
`app.py` is untouched. The next small candidate is characterization of the
existing `_unique_save_path` collision/path-selection contract, without moving
it or combining it with download or generator ownership.

### Unique save-path characterization (runtime unchanged)

`_unique_save_path(output_dir, file_name)` remains an appropriately placed small
core helper; characterization alone does not justify moving it. It applies
native `os.path.basename` to `file_name or "comfy_output.png"`, joins that name
to the output directory, and splits the entire candidate with `os.path.splitext`.
It returns the initial candidate if absent; otherwise `_1`, `_2`, etc. are
inserted before the final extension, stopping at the first absent candidate.
Multi-dot and dot-leading names retain native splitext semantics. A trailing
native separator gives an empty basename rather than triggering the fallback.
For the tested string/Path directory inputs the returned path is a string.

`os.path.exists` counts directories as collisions as well as files. Path-operation
exceptions propagate directly; truthy invalid filename types are not normalized.
Selection creates neither files nor directories and reserves nothing: repeated
calls can return the same path, and another writer may create it before download.
This existing non-atomic limitation is documented, not changed.

The generator still creates directories and passes `f"{file_prefix}_{filename}"`
to this helper; the unchanged download-phase tests pin that integration.
Download/write ownership remains with `download_image_to_path`. Runtime code and
`app.py` are unchanged. The next small candidate is characterization of the
existing generator's successful final-event metadata defaults/aliasing and
post-download assembly failures, rather than further path-allocation extraction.
No such follow-up is implemented here.

### Final done-event characterization (runtime unchanged)

Successful-event metadata uses `.get` defaults only for missing extraction keys:
`output_node_ids=[]`, `output_keys_by_node={}`, `image_like_fields=[]`, and final
`save_nodes_with_outputs=[]`. Present falsey values pass through unchanged.
The event reuses supplied metadata containers, attempt logs and SaveImage node
IDs without copying. The retained download tests cover the complete payload,
first successful primary path, shared paths/saved_paths and original images.

Final diagnostics compute `len(attempt_logs)` (not attempt numbers) and retain
the original logs object. This happens after successful download and before
`extraction.get("save_nodes_with_outputs", [])`. A malformed logs value therefore
fails before that final lookup; a lookup failure also propagates unchanged.
Neither failure enters the per-image warning/continue handler or emits a done
event; already-written files remain, with no cleanup. Tests use a download
boundary fake that writes real bytes into temporary files.

Runtime code and `app.py` remain unchanged. The next candidate is design review
of a narrow final-event assembly helper receiving already-collected metadata
and download results, preserving these aliases and evaluation order. Such an
extraction is only worthwhile if it clarifies ownership; no builder or payload
redesign is introduced here.

### Final-event ownership design review

**Recommendation: keep the final event and its success diagnostics inline;
no further extraction is justified here.** The literal is the natural terminal
representation of state already owned or collected by the generator. The
nonempty-success check, first-path selection, warning/continue policy, partial
success, total failure and yield timing remain generator responsibilities.

Candidate A, a whole-event builder, would need **11 independent inputs**. A
concrete signature for comparison (not a planned API) in a hypothetical
`core/comfy_done_event.py` would be:

```python
build_done_event(*, saved_paths, download_errors, attempted_view_urls,
                 prompt_id, output_node_ids, output_keys_by_node,
                 image_like_fields, attempt_logs, save_image_node_ids,
                 extraction, image_infos)
```

| Inputs | Ownership and reference requirements |
| --- | --- |
| `saved_paths` | Generator download result; first element supplies primary path; the same list supplies both paths fields. |
| `download_errors`, `attempted_view_urls` | Generator download evidence containers, passed through unchanged. |
| `prompt_id` | Submission identifier, normally an immutable string; no conversion. |
| `output_node_ids`, `output_keys_by_node`, `image_like_fields` | Extraction metadata already read before downloading; preserve container identity and present falsey values. |
| `attempt_logs` | Polling diagnostic container; retain identity and compute its length. |
| `save_image_node_ids` | Polling/workflow diagnostic metadata; retain container identity. |
| `extraction` | Original extraction mapping, needed for the late success-node lookup. |
| `image_infos` | Polled image records; retain original container identity. |

No socket, clock, UI or other lifecycle input belongs in this builder. Even
keyword-only arguments would merely relocate a dict plus eleven bindings.
Passing the entire poll result or a new context/schema to hide the count would
blur owners. Re-reading the three earlier extraction values in a builder would
also change lookup timing; they must remain separate inputs.

Candidate B is a coherent but marginally useful smaller boundary: a hypothetical
`_build_success_diagnostics(attempt_logs, save_image_node_ids, extraction)` in
`core/comfyui.py` could assemble the four nested fields. These three inputs are
polling/extraction diagnostics, and original containers must pass through. It
would compute `len(attempt_logs)` before the final
`extraction.get("save_nodes_with_outputs", [])`. Precomputing the latter as a
call argument would reverse the pinned failure order. The call would have to
remain at the nested dict's current position, after `saved_paths[0]`, after
successful downloading and outside the per-image catch. There is no branching
or independent policy to remove: a one-use helper for four fields adds a jump
without a meaningful reduction in complexity. Do not extract it now.

Both conceptual helpers would only assemble new outer dictionaries and reuse
inputs, with no intentional mutation, I/O, yields, retries or knowledge of
download-failure policy. They must not catch, wrap or normalize failures.
For ordinary containers they are deterministic/read-only; custom `__len__` or
`get` implementations can raise or have effects, so strict purity cannot be
promised. Candidate A must retain first-path access before length evaluation,
then the final lookup; Candidate B must retain the latter two in that order.
Failures still leave downloaded bytes on disk with no warning or done yield.

Repository Python-source searches for done events, `Completed!`,
`comfy_output_diagnostics` and success-node fields found one production success
event constructor. `app.py` consumes/copies debug fields rather than constructing
the same event. Missing-output diagnostics and polling attempt logs share some
field names but have different shapes and timing; they are not reusable success
builders. Test expectations are not production duplication.

Candidate C therefore wins: keep the literal visible next to its terminal
yield. PR #17's exact payload/partial-success tests and PR #20's defaults,
identity and assembly-failure tests provide sufficient evidence for this review;
no speculative test is added. Runtime and `app.py` are unchanged. There is no
next extraction PR proposed for this final-event boundary. Revisit only if a
real second producer or independent success-diagnostic policy emerges.

### History HTTP fetch extraction

`core.comfy_history_fetch.fetch_comfy_history(server_address, prompt_id)` owns
only `http://{server_address}/history/{prompt_id}` construction, HTTP open,
response context entry/read, JSON decoding and context exit before returning
the decoded value. Interpolation remains raw: no encoding, normalization,
headers, timeout argument or status/result-type validation is added. Decode
occurs inside the response context; exit failures can override a successful
return. Exceptions propagate unchanged with no logging or fallback.

`core.comfyui` imports it as `_fetch_comfy_history`, preserving the private
poller patch seam and unchanged polling tests. Retry counts, sleep, swallowed
fetch errors, logging, history selection, output/status interpretation and
attempt diagnostics remain with the poller and its existing helpers. The body
is moved literally; now-unused json/urllib.request imports are removed from
that module. `app.py`, generator and final-event ownership are unchanged.

The next candidate is a bounded design review of the retained WebSocket
receive/progress lifecycle, checking whether timeout, close and yield ownership
can remain clear without a broad transport abstraction. No extraction there is
assumed or implemented in this PR.

### Receive/progress lifecycle design review

**Recommendation: keep the receive/progress lifecycle inline. No next extraction
PR is justified for this boundary.** `generate_image_with_progress` already
owns suspension and the transition to polling; the read-only protocol decisions
are separately owned by `interpret_progress_message`.

Current timing and asymmetry matter. After connection, `start_time=time.time()`
is recorded once. Each iteration checks `time.time() - start_time > timeout`
before receiving. Expiry closes then raises plain `Exception` with
`ComfyUI execution timeout ({timeout}s exceeded)`; that iteration never receives.
`WebSocketTimeoutException` inside the try retries without closing; the next
iteration checks overall time again. Other `Exception` instances become
`Exception("WebSocket error or execution failed: ...")` with implicit original
`__context__`, no explicit cause, and no socket close. Close/clock failures
outside the try propagate directly. Completion breaks, closes, then yields
`Execution done. Fetching image...`; polling waits for the next resume.

Candidate A could be a nested `wait_for_comfy_execution(ws, prompt_id, timeout,
start_time)` generator with module clock/interpreter dependencies and an outer
`yield from` call. It would have to retain both normal and timeout close policy,
receive retries, translation and suspension, while setup and polling stay outside.
Starting its clock on first iteration instead of at the current point would
require care. Clock/interpreter callbacks are unnecessary extra API; a service
object would obscure the same state. A callback event sink cannot preserve
caller-driven suspension; a buffered event stream delays errors and progress.
A nested generator can forward the same event and resume its loop, but `.throw()`
and `.close()` are delegated by `yield from`: the inner try must still surround
the yield, and neither owner may add a cleanup finally. Exception context and
ordinary timing can be preserved deliberately, but extra frames and delegated
lifecycle add complexity without reuse. Splitting close between two generators
would make ownership harder still.

Candidate B, `receive_execution_update(ws, prompt_id)`, could combine recv and
interpretation. Swallowing receive timeout needs a retry outcome (or conflates
retry with the interpreter's ignored `(False, None)`); yielding, overall timeout,
completion and closing still remain outside. More importantly, moving exception
translation into that helper would exclude exceptions injected at the outer
progress yield. Keeping an outer handler to preserve those semantics largely
retains today's loop and duplicates classification or leaves the helper as just
two calls. This is not a useful new protocol/owner.

| Responsibility | Current / Candidate C | Candidate A | Candidate B |
| --- | --- | --- | --- |
| Socket setup and reference | Outer generator/setup helper | Outer passes socket | Outer passes socket |
| Timeout clock/state | Outer, before each recv | Inner check, explicit start time | Outer unchanged |
| Receive | Outer | Inner | Step helper |
| Receive-timeout retry | Outer | Inner | Helper classifies, outer repeats |
| Message interpretation | Existing interpreter | Same interpreter via inner | Same interpreter via step |
| Event object | Interpreter result passed unchanged | Same object forwarded | Same object returned |
| Event yield | Outer inside try | Inner via outer yield from | Outer, still needs handler |
| Completion decision | Interpreter flag, outer break | Inner consumes flag | Outer consumes flag |
| Normal/expiry close | Outer; no universal cleanup | Must move together to inner | Outer unchanged |
| Exception translation | Outer includes suspended yield | Inner must include yield | Cannot fully move from outer |
| Transition to polling | Outer after fetching-status resume | Outer after delegation | Outer unchanged |

The current suspension points are: Connecting (request prepared, not submitted),
Prompt queued (submitted, socket not constructed), interpreted event (socket
open, inside try), fetching status (socket closed, polling not started), and
later download warning/done events (outside receive lifecycle). Resuming an
interpreted event returns to the loop and its next timeout check. `.close()` at
that yield raises GeneratorExit, outside `Exception`, and performs no socket
cleanup; closing before setup constructs nothing. Preserve that asymmetry,
not a new finally. The added single test pins same-event identity, no extra
receive while suspended, and injected ValueError translation/context without
close. Existing tests cover ordinary retries, completion, errors and early close.

Production searches for recv, interpreter calls, wrapper text and execution
timeout found only this loop (tests excluded). No second producer justifies
sharing lifecycle policy. Candidate C leaves clock, close and suspension visible
together and is simpler than either candidate. Runtime and `app.py` remain
unchanged. Reconsider only for an actual independent execution consumer, not
for line-count reduction; no adjacent cleanup is proposed.

### Batched output interpretation extraction

Three independent small, already-characterized helper clusters now have focused
owners. They are intentionally batched to share one integration/full-suite
validation surface, not to redesign polling or its data model.

- `core.comfy_history_interpretation`: `_history_prompt_record`,
  `_history_outputs`, `_history_prompt_ids_sample`. Dict-only selection first
  uses the exact prompt ID, then the sole value if the direct value is not a
  dict and history has exactly one entry. Record/output dicts retain identity;
  non-dict outputs become empty dicts. Sampling retains insertion order, native
  slicing (including unusual limits/errors), then str conversion; no sorting.
- `core.comfy_workflow_outputs`: `_workflow_output_nodes` and
  `_workflow_save_image_nodes`. Raw/wrapped dict nodes, insertion order and
  str IDs are retained, including duplicate strings from distinct keys.
  Class resolution remains `class_type or type or ""`, then str; exact or
  dotted SaveImage/PreviewImage suffixes are case-sensitive. Save-only excludes
  PreviewImage. Invalid container/entry handling is unchanged.
- `core.comfy_status_interpretation`: `_comfy_status_summary` and
  `_comfy_status_is_failure`. Only a None status_str permits the completed-key
  fallback (including explicitly present None); other falsey values become
  unknown. List messages retain identity. Status failure words are error,
  failed, failure; list/tuple message heads recognize execution_error, error,
  failed after str/lower only. No trimming, mutation or error wrapping is added.

All names remain imported into `core.comfyui`; polling/diagnostic callers and
existing tested patch seams remain intact. The status failure helper resolves
its summary sibling in the new module; no tests patch the old summary symbol.
Bodies are literal moves. Polling retry/error/sleep policy, diagnostic payloads,
receive lifecycle, downloads and final event remain unchanged, as does `app.py`.
Existing polling/diagnostic tests provide most coverage; small direct tests add
only selection/slice, class fallback/ID collision and status vocabulary/alias
edges. No forwarding wrappers or new schemas are introduced.

No next extraction is justified by this move alone. The retained diagnostics
and poller are already coherent owners; revisit only for a concrete maintenance
need. The prior decisions to keep final-event and receive lifecycle inline stand.

### Batched remaining utility owners

Five independent decisions share one repository/context load, one combined
relevant-test pass and one final full-suite run. All five are literal extractions:

- A: `core.comfy_polling_policy` owns the constants 8 attempts and 0.75 seconds.
  Re-exported names preserve imports and definition-time poller defaults; the
  signature remains unchanged. Diagnostics imports the attempts constant here.
- B: `core.comfy_output_diagnostics` owns construction and exact formatting.
  Key order, falsey fallbacks, metadata aliases, first-five message slice,
  last-eight attempt slice, key types and all malformed-input exceptions remain.
  It imports interpretation/policy owners directly, never `core.comfyui`.
- C: `core.comfy_save_path` owns native basename/join/splitext/exists selection,
  falsey filename fallback and first-gap suffixing. No reservation, creation,
  normalization or exception handling is introduced.
- D: `core.comfy_group_prompt` owns node/token traversal, Module stack filtering,
  last-matching close, grouping/value lookup and malformed-marker warnings.
  Existing eager `node.word` default evaluation is unchanged.
- E: `core.comfy_workflow_injection` owns ordered destination aggregation,
  fallback/merge/overwrite, dedup and in-place workflow mutation. Config lookup
  before the per-destination try, warnings and broad caught errors remain at
  their original boundaries; the same workflow object is returned.

All existing entry names are imported back into `core.comfyui`. Workflow
preparation still uses that seam. D/E bind `logging.getLogger("core.comfyui")`,
which is the same logger singleton: name, routing and logger-method patches
remain effective. Replacing the entire comfyui.logger variable would not rebind
these module references; no existing caller/test relies on that replacement.
Likewise diagnostics resolves its helper/constant globals in its new owner;
existing diagnostic entry-point patches and constant imports remain usable.

Existing diagnostics/path tests were sufficient; only small direct D/E tests
were added for actual traversal/injection and shared logging (preparation tests
mock those operations). Poller fetch/time/logger seams, retry policy and
signature, generator/yield/close ownership, app.py and persistence/UI remain
unchanged. No wrappers, callback parameters or new result schemas are added.
Remaining orchestration should stay inline; no next extraction is justified
solely to continue this series.

### Candidate/Gallery inspection boundary

The Candidate/Gallery read-only calculations are now owned by
`core.candidate_inspection`. This is one coherent cluster of small projections
that can be reused without importing `app.py`; the app keeps the existing names
through imports so current callers and test seams remain stable.

The owner contains candidate path selection, prompt metadata/text projection,
original-prompt comparison/status labels, metadata captions, pinned/trashed
partitioning, display ordering, provenance value lookup, swap-lineage metadata
projection, and appended Gallery Variant classification. These helpers retain
their existing field precedence, falsey/default behavior, parser fallback,
stable ordering, container identity and direct exception behavior. The
`_candidate_image_swap_lineage_info` helper only constructs the existing
metadata mapping; it does not perform the swap.

Candidate records, PromptLines, Project mutation, Candidate adoption/swap,
Gallery Variant mutation, session-state synchronization, history/autosave,
filesystem/path resolution, widget ownership and rendering remain in `app.py`
or their existing owners. The new module performs no Streamlit or persistence
work and introduces no semantic Module/Attribute matching or new schema. The
focused tests cover the moved calculations; the app import and relevant
Candidate/Gallery integration tests cover the retained call sites. The next
Candidate/Gallery boundary should be considered only when a similarly pure,
non-mutating owner is evident; no mutation or UI extraction follows from this
cluster alone.

### Graph display calculations

`core.graph_display` owns the complete contiguous six-helper Graph display
cluster: line-node membership, display ordering, wrapped positions, initial
node selection, branch/spine hints, and cooccurrence overlay edges. These
calculations consume existing nodes and line paths and return display data;
they neither construct nor mutate the graph. They share one consumer, the
Graph renderer, and require no imports or callbacks into the app.

The same names remain imported in `app.py`. Stable ties, duplicate handling,
depth/count thresholds, integer position truncation, malformed-input exceptions
and existing edge-limit behavior are preserved. In particular, a zero overlay
edge limit still permits the first eligible edge because the limit is checked
after appending. This extraction does not correct that behavior.

Graph construction, renderer styling, session selection, neighborhood expansion,
Focus navigation and the neighboring status/navigation controls remain in
`app.py` or their existing owners. Module inspection was not selected because
its library lookup can normalize Project state; Gallery scope resolution also
crosses session-dependent selection. Neither belongs in this read-only owner.

### AnimaDex record inspection

`core.animadex_record_inspection` owns the six read-only projections used by the
AnimaDex browser: stable record identity, searchable text, multi-term filtering,
record labels, summary rows, and metadata preview rows. They consume in-memory
record dictionaries and return strings or display rows without importing
`app.py`, touching Project state, or changing the records they inspect.

The app keeps the existing helper names through direct imports, preserving field
precedence, case-folded search, ordering, falsey fallbacks, aliasing and direct
exception behavior. AnimaDex discovery and file access, settings and path
ownership, module-name/preview conversion, mutation and session state, and all
Streamlit rendering remain in their existing owners. This boundary introduces
no new record schema or persistence behavior.

### Prompt-line selection calculations

`core.prompt_line_selection` owns the read-only calculations for selecting and
classifying visible prompt lines: visible ordering, adjacent focus IDs, route
separator detection, workbench detection, and Gallery-operation eligibility.
These helpers consume existing project or line values and return the same lists,
IDs, and boolean classifications without importing `app.py` or mutating their
inputs. Their direct imports preserve the existing app-level helper names and
test seams.

PromptLine and Project mutation, route or workbench editing, session and widget
ownership, Focus navigation state, persistence/history, and Streamlit rendering
remain outside this owner. The module does not select files, change line
ordering in the Project, or introduce a schema or new navigation behavior.

### PromptCloud calculations

`core.promptcloud_calculations` owns the deterministic PromptCloud calculations
for word/frequency sanitization, eligible line-ID lookup, and token-frequency
aggregation. It reuses the prompt-line eligibility predicate directly and
returns the existing strings, mappings, and lists with their original ordering,
deduplication, falsey defaults, and parser behavior. The module has no Streamlit
or `app.py` dependency and does not mutate the project, lines, or prompt text.

PromptCloud rendering, selected-word and widget/session state, graph or Gallery
highlighting, PromptLine/Project mutation, save/load and history, and any other
UI ownership remain in `app.py` or their existing owners. This boundary is a
calculation owner only; it does not change the PromptCloud data model or project
persistence semantics.

### Module scope inspection

`core.module_scope_inspection` owns the read-only `preview_module_scope`
projection used by the Module Inspector. It scans the existing prompt-line
tokens, skips deleted lines, counts inline and ranged Module occurrences,
records malformed marker cases, and returns the existing bounded example rows.
The lazy parser lookup, marker-stack behavior, token ordering, falsey/default
handling and direct exception behavior remain unchanged.

Module selection, edit-scope session state, rename/apply mutation, history,
save/load, and Streamlit rendering remain in `app.py`. This owner does not
normalize Project data, write files, or introduce a Module schema or persistence
format. The extraction is a calculation boundary only; the retained Module
Inspector caller continues to own the UI and edit-scope lifecycle.

### Node selection matching

`core.node_selection_matching` owns the read-only `get_node_match_terms` and
`remap_selected_nodes_for_line` helpers used when Graph selections are carried
into a focused prompt line. The owner preserves literal/display/word/original
terms, parser-derived base-word terms, exact-match precedence, selected-ID
ordering and duplicates, path ordering and fallback deduplication. It does not
mutate the Project, nodes, prompt line, or selection inputs.

`preserve_focus_selection_context` remains the app-level caller and retains
session-state update ordering and the existing selected-node sanitization seam.
Graph rendering, Focus navigation, widget/session ownership, history,
persistence, and prompt mutation remain outside this owner. No schema,
save/load, or navigation behavior is changed by the extraction.

### Graph neighborhood traversal

`core.graph_neighborhood` owns the read-only `get_neighborhood_node_ids`
traversal used to expand a Graph selection around existing edges. It validates
selected node IDs against the existing node map, walks both directions for the
requested number of steps, and returns the same set-or-None results without
mutating the Project, nodes, edges, or selection input.

The owner preserves the existing early returns, eager edge traversal, duplicate
and cycle handling, inclusion of external edge endpoints, step-type behavior,
and direct malformed-edge exceptions. Graph controls, neighborhood-step
session state, selection synchronization, rendering, navigation, and graph
mutation remain in `app.py`. This is a traversal calculation only; it does not
extend `core.graph_display` or change graph persistence.

### Focus token/node projection

`core.focus_token_node_projection` owns the read-only
`get_focus_token_node_pairs` projection used by the Focus token picker and
preview. It preserves token order and identity, positional `node_path`
alignment, marker-prefix exclusions, falsey-ID handling, and membership checks
against the existing Project node map without mutating either input.

Focus widgets, selected-node/session state, navigation, prompt editing, graph
mutation, and rendering remain in `app.py`. This owner supplies a token/node
projection only; selected-node remapping remains in
`core.node_selection_matching`.

### Route snapshot inspection and comparison

`core.route_snapshot_inspection` owns the seven read-only route-snapshot
helpers, including the shared `_short_preview` formatter: snapshot labels,
metadata normalization, image-path fallback, comparison labels, snapshot
comparison, and stable item ordering. These helpers inspect existing snapshot
dictionaries and return display or comparison data without creating, mutating,
persisting, or rendering snapshots.

The extraction preserves score coercion and clamping, falsey path precedence,
duplicate-line replacement and insertion order, equal-path suppression,
malformed-input behavior, and integer/non-integer ordering. Snapshot creation
(including UUIDs and timestamps), append/apply/save operations, history and
session state, image/file handling, and Streamlit storyboard/compare rendering
remain in `app.py`. No route-snapshot schema or persistence behavior changes.

### ComfyUI workflow metadata shape inspection

`core.comfy_workflow_metadata` owns the pure JSON parsing and executable-shape
inspection helpers `_load_json_from_text` and
`_is_executable_comfy_workflow`. The owner preserves the distinction between
non-string/blank/invalid JSON and valid JSON scalars or containers, and treats a
workflow as executable when any dictionary node has dictionary `inputs`. It
performs no metadata selection, filesystem access, workflow mutation, or
generation orchestration.

`_workflow_text_from_line_metadata`, metadata-source precedence, debug status,
session-state fallback, workflow preview/rendering, path resolution, and
submission remain in `app.py` or the existing ComfyUI owners. Direct exception
and short-circuit behavior remain part of the characterization boundary; no
workflow schema or persistence behavior changes.

### LoRA mapping presentation calculations

`core.lora_mapping_presentation` owns the nine read-only LoRA candidate and
mapping presentation helpers: candidate/reference labels, reference grouping,
numeric strength defaults, reference signatures, mapped-option labels, and key
fragment formatting. The owner preserves required-field failures, falsey
fallbacks, case-sensitive grouping with case-insensitive ordering, first
non-empty weights, duplicate signature entries, numeric fallback behavior, and
the existing key-fragment limit.

LoRA directory scanning and reference extraction/matching remain in their
existing owners. `_lora_mapping_file_options` remains in `app.py` because it
owns session-state and filesystem-dependent options; widgets, draft/session
state, workflow injection, and export rendering also remain there. This is a
presentation/calculation owner only and does not change LoRA or workflow
persistence semantics.

### Comma-tag text conversion

`core.comma_tag_text` owns the two pure text-conversion helpers
`_format_comma_tags` and `_parse_comma_tags` used by metadata editing. It
preserves list-only formatting, string conversion and trimming, literal comma
splitting, case-sensitive first-occurrence deduplication, falsey handling, and
direct conversion exceptions without mutating the supplied values.

Metadata editor widgets, session-state synchronization, save/load, schema
interpretation, and Streamlit rendering remain in `app.py`. The module does
not own tag persistence or introduce a tag model.

### ComfyUI candidate presentation

`core.comfy_candidate_presentation` owns the two read-only helpers
`_comfy_candidate_label` and `_candidate_default_index` for labeling and
selecting among text-node candidates found in a ComfyUI workflow. It preserves
required-field failures, falsey preview handling, first role-match precedence,
and the uncoerced fallback index behavior.

Workflow candidate discovery, parser/shape analysis, widget defaults and
session state, workflow editing/injection, and rendering remain in `app.py` or
the existing ComfyUI owners. This is separate from
`core.candidate_inspection`: it presents ComfyUI workflow candidates and does
not inspect or mutate generated Candidate/Gallery records.

### Graph component selection normalization

`core.agraph_selection` owns the read-only `normalize_agraph_selection`
adapter for converting AGraph return values into valid existing Project node
IDs. It preserves string, dictionary, and object-shaped inputs, `id`-before-
`node` precedence, first-occurrence deduplication, falsey short-circuiting,
node-map filtering, and direct malformed-input behavior without mutating the
Project or returned objects.

`sanitize_selected_node_ids`, graph widget/callback handling, session-state
selection ownership, rendering, navigation, and graph mutation remain in
`app.py`. This is an input-shape adapter, separate from graph display
calculations and selected-node matching.

### Nearby line selection

`core.nearby_line_selection` owns the read-only `_get_nearby_lines` helper for
selecting visible PromptLine neighbors around a target line. It filters deleted
lines, preserves the existing current-index ordering and stable ties, applies
the radius slice, and returns the existing line objects without changing the
Project or PromptLines.

Candidate aggregation, pinning and adoption, session state, nearby-candidate
rendering, navigation, and all PromptLine/Project mutation remain in `app.py`
or their existing owners. The owner does not broaden the Candidate/Gallery
inspection boundary.

### Consistency presentation

`core.consistency_presentation` owns the two read-only formatting helpers
`_format_percent` and `_compact_label_list` used by consistency analysis. It
preserves falsey percentage defaults, numeric conversion and one-decimal
formatting, label stringification/filtering, duplicate labels, limit behavior,
and direct conversion exceptions.

Consistency analysis, negative-prompt inspection, session state, table/metric
rendering, and any persistence or mutation remain in `app.py` or their
existing owners. This module formats already-computed values and does not own
the analysis data or schema.

### Generation duration formatting

`core.generation_duration` owns the read-only `_format_duration` helper for
displaying positive generation-time estimates. It preserves the unknown-value
fallback, rounding, Japanese seconds/minutes/hours labels, hour-level seconds
suppression, and direct invalid-value exceptions.

Duration sampling, session history, ETA/average calculations, progress
updates, generation execution, and Streamlit rendering remain in `app.py`.
The owner formats supplied timing values only and does not own timing state or
generation orchestration.

### ComfyUI analysis draft lifecycle

`ui.comfyui_analysis_drafts` is the first stateful-controller extraction from
`app.py`. It owns the durable draft dictionary and the transient Streamlit
widget mirror for the ComfyUI analysis workspace, across the `inspector`,
`prompt_injection`, `lora_mapping`, and `lora_injection` sections. The owner
contains the nine lifecycle helpers `_get_comfyui_analysis_workspace_drafts`,
`_normalize_comfyui_draft_scalar`, the scalar widget prepare/snapshot helpers,
`_comfyui_draft_option_id`, the option prepare/normalize/snapshot helpers, and
`_clear_comfy_workflow_inspector_state`.

This boundary preserves the existing exact session-state keys and section
shape, durable-versus-widget precedence, prepare-before-widget and
snapshot-after-widget ordering, scalar type/default and falsey behavior,
direct exception propagation, candidate identity matching, reorder and
disappearance fallback, explicit empty IDs, invalid/stale durable fallback,
LoRA strength drafts, workspace reopen behavior, and inspector clear behavior.
It also preserves the existing rule that uploaded workflow objects are not
retained in durable drafts. These are lifecycle contracts, including legacy
ordering and odd fallback behavior, rather than a generic session-state
abstraction.

The analysis renderers, widget composition, workflow inspection and display,
LoRA scanning and presentation, consistency analysis, effective workflow
resolution, and workspace routing remain in `app.py` or their existing owners.
Workflow parsing, generation, injection, submission, output handling, and
filesystem/network/generator orchestration are explicitly outside this owner.
`Project`/`PromptLine` mutation, history, save/load, schema, and persistence
also remain outside it. This first stateful extraction stops at the durable
draft/widget-mirror lifecycle so those neighboring application and production
boundaries stay explicit.

### Graph Edit Browser navigation controller

`ui.graph_edit_browser_controller` owns the Graph Edit Illustration Browser's
stateful navigation guard and session-mirror lifecycle. The extracted boundary
covers `reset_graph_edit_illustration_browser_state`,
`get_graph_edit_browser_unsaved_line_ids`,
`block_graph_edit_browser_navigation_if_unsaved`,
`discard_graph_edit_browser_current_page_drafts`, and the browser-specific
page/filter/page-size/input/collapse/reveal callbacks and setters:
`_reset_graph_edit_browser_page`, `_on_graph_edit_browser_filter_changed`,
`_on_graph_edit_browser_page_size_changed`,
`_on_graph_edit_browser_page_input_changed`, `_set_graph_edit_browser_page`,
`_set_graph_edit_browser_collapsed_group_keys`, and
`_reveal_graph_edit_browser_current`. It also owns the browser constants and
the local `get_line_by_id` lookup used by this controller; the existing app
lookup remains for the app's other callers.

The owner controls only the browser's session keys: filter, page, page size,
collapsed group keys, notice, current-page line IDs, and the filter/page-size/
page-top widget mirrors. It preserves detection of unsaved current-page text
and negative-prompt widget drafts, stable ordered/deduplicated IDs, missing or
deleted-line handling, navigation rejection without applying the transition,
widget-mirror rollback, explicit discard without Project mutation, page and
filter/page-size reset ordering, reveal/jump behavior, falsey/default and
exception behavior, and Project-replacement reset behavior. Browser-only
navigation remains separate from Focus/Gallery selection and shared Project
editing state.

The browser renderer, page planner/reconciliation, page registration, display
filters, editor widgets and Save Changes actions remain in `app.py`. Project
loading and reset orchestration remains in the app's shared lifecycle; the
controller does not own Project or PromptLine mutation, history, persistence,
schema, prompt-editing semantics, or filesystem/network/generation work. It
is a Graph Edit Browser controller, not a generic session wrapper or navigation
framework.

### Global Module Library authoritative session lifecycle

`ui.global_module_library_session` owns the authoritative session lifecycle for
the Global Module Library. Its three functions,
`get_session_global_module_library`, `cache_global_module_library_for_session`,
and `save_and_cache_global_module_library`, own the path-keyed
`global_module_library_session_cache` session entry. A cache hit requires the
same resolved library path and a dictionary-valued library; a miss or path
transition performs the existing authoritative load and replaces the cache.

The explicit write owner preserves the existing sequence: load the latest
authoritative library, deep-copy it for the modifier, validate the modifier's
dictionary result, save through the existing `core.io` file writer, reload the
persisted representation, and cache that reloaded object. It preserves cache
identity and replacement behavior, same-path reuse, path transitions,
falsey/default settings handling, modifier/save/reload/path failures,
exception propagation, partial side effects, and the exact ordering of
filesystem and session-cache operations. It is specific to this library's
authoritative session lifecycle, not a generic cache or persistence layer.

`core.io` remains the owner of Global Module Library path resolution, JSON
loading, saving, and filesystem/atomic-write behavior. Conflict detection,
search filtering, manager and authoring UI, AnimaDex transfer, Project-local
Module metadata, Module/Attribute semantics, Project persistence/schema,
history, and all Streamlit composition remain in `app.py` or their existing
owners. The extracted controller does not redesign the Global Module JSON
schema or broaden the library search and authoring boundaries.

### AnimaDex local-path lifecycle controller

`ui.animadex_path_controller` owns the AnimaDex Browser's local-path stateful
lifecycle: `initialize_animadex_browser_path`,
`sync_animadex_browser_path_draft`, `_animadex_local_path_is_available`,
`save_animadex_local_path_default`, and
`clear_animadex_local_path_default`. The owner controls the exact
`animadex_browser_path`, `animadex_browser_path_draft`, and
`animadex_local_path_feedback` session keys, together with the
`settings["animadex_local_path"]` value used for the explicit saved default.
This is a feature-specific controller, not a generic session-state wrapper.

The lifecycle preserves the existing missing-widget versus durable-default
precedence, draft initialization and widget-to-draft callback timing, falsey
path behavior, path normalization, settings-dictionary identity, and the
save-before-session-update-before-availability-probe ordering. Failed default
saves restore the prior settings value and retain the existing session path;
successful saves update the session path and draft and produce the same
success/warning feedback based on the availability probe. Clearing the saved
default keeps the current session path unchanged, and failed clears restore
the prior persisted value. Existing `OSError`, `TypeError`, and `ValueError`
handling from the availability probe and direct exception behavior remain
unchanged. Project and workspace reset flows remain in the app's shared
lifecycle and deliberately preserve this AnimaDex path session state.

`app.py` retains the AnimaDex renderer, text input and buttons, saved-default
display, feedback consumption, record discovery and file scanning, thumbnail
preview, record-to-Module preview, and Global Module import/mutation. The
controller does not own AnimaDex record inspection, Project or PromptLine
mutation, Global Module Library mutation, Project persistence/schema, or
workflow/generation/network orchestration. `core.settings` remains the owner
of path normalization and settings serialization; this extraction preserves
the existing explicit settings-save sequencing without introducing a new
schema or persistence layer.

### Module Rename session lifecycle

`ui.module_rename_session` owns the Module Rename workspace's selection,
name-draft widget mirror, and preview invalidation lifecycle through
`clear_module_rename_preview`, `initialize_module_rename_selection`,
`sync_module_rename_selected_widget`,
`initialize_module_rename_new_name_draft`, and
`sync_module_rename_new_name_widget`. Its exact session keys are
`module_rename_selected`, `_module_rename_selected_widget`,
`module_rename_new_name`, `_module_rename_new_name_widget`, and
`module_rename_preview`.

The owner preserves eager option consumption and first-valid selection
fallback, durable-selection precedence, existing name-widget preservation,
trimming and falsey behavior, direct exception propagation, and preview
identity/removal semantics. It only synchronizes session/widget state; the
rename renderer, confirmation controls, Project transition reset, mutation,
history, save, and rerun ordering remain in `app.py`.

The controller does not own Module semantics, Project or PromptLine mutation,
Project persistence/schema, generic session abstractions, or unrelated Module
Inspector and Attribute workspace state. It is a Module Rename-specific
session owner and does not broaden the existing authoring boundaries.

### Project Module Inspector draft/widget synchronization

`ui.project_module_inspector_session` owns the Project Module Inspector's
durable draft and Streamlit widget-mirror lifecycle through the ten paired
prepare/sync helpers for selection, body, core text, type, and minimum-match
values: `prepare_project_module_inspector_selection_widget_state`,
`sync_project_module_inspector_selection_widget_state`,
`prepare_project_module_inspector_body_widget_state`,
`sync_project_module_inspector_body_widget_state`,
`prepare_project_module_inspector_core_widget_state`,
`sync_project_module_inspector_core_widget_state`,
`prepare_project_module_inspector_type_widget_state`,
`sync_project_module_inspector_type_widget_state`,
`prepare_project_module_inspector_min_match_widget_state`, and
`sync_project_module_inspector_min_match_widget_state`.

The owner controls the exact `project_module_inspector_name`, body, core,
type, and `min_match` durable keys, together with their
`_project_module_inspector_*_widget` mirrors. It preserves durable-before-widget
preparation, callback synchronization, selected-module fallback and empty-list
`IndexError` behavior, falsey body normalization, module-type fallback, minimum
match clamping and callback conversion, evaluation order, direct exceptions,
and partial durable writes when a later widget write fails. These are
feature-specific draft contracts, not a generic session-state abstraction.

`app.py` retains `render_project_module_inspector_section`, all Streamlit
rendering and widget composition, token-inspector display, reset/load and
workspace routing, and the save sequence. Project/PromptLine and Module
mutation, history, graph rebuilding, focus restoration, persistence/schema,
filesystem/network/generator orchestration, and Module/Attribute semantics
remain in `app.py` or their existing owners. The extracted controller only
keeps the Inspector's draft/widget state synchronized; it does not own the
authoring workflow or change Project persistence.

### Project Import session lifecycle

`ui.project_root_import_session` owns the Existing Project Import feature's
session-only input invalidation and deferred confirmation-reset lifecycle. Its
boundary contains `reset_project_root_import_operation_state`,
`_reset_project_root_import_confirmation`,
`_invalidate_project_root_import_preview`,
`_select_project_root_import_source`,
`consume_project_root_import_confirmation_reset`, and
`initialize_project_root_import_name`, together with the exact preview,
result, source, destination-name, confirmation, phrase, and pending-reset
session keys.

The owner preserves conditional result retention, preview invalidation,
deferred widget clearing, falsey pending-reset consumption, missing-only and
lazy destination-name initialization, source normalization before assignment,
parent-directory name derivation, empty-name preservation, callback ordering,
result/preview identity, partial source assignment, and direct exception
propagation. It is a Project Import-specific controller, not a generic
session-state or confirmation abstraction.

`app.py` retains the Existing Project Import renderer and widget composition,
recent-source and external-path resolution, preview construction and display,
copy/apply execution, result finalization, filesystem and persistence work,
Project transitions, error handling, and rerun orchestration. `core.project_root_import`
remains the owner of import-path normalization, name sanitization, preview,
and apply primitives. Project/PromptLine mutation, schema, save/load, and
unrelated Project Assets or navigation lifecycles remain outside this owner.

### Project Directory Browser session lifecycle

`ui.project_directory_browser_session` owns the Project Directory Browser's
refresh generation, discovery-cache publication, and root-scoped selection
helpers: `request_project_directory_discovery_refresh`,
`_get_project_directory_discovery_snapshot`, and
`_normalize_project_directory_browser_selection`. The owned session keys are
`project_directory_discovery_refresh_generation`,
`project_directory_discovery_cache`, `project_directory_selection_root`, and
`project_directory_selected_path`.

The lifecycle preserves falsey and integer refresh-generation coercion, cache
identity and success-only replacement, raw discovery-context forwarding,
root-change selection clearing before entry evaluation, first non-empty entry
ordering, duplicate evaluation behavior, empty-selection removal, and direct
exception propagation. `core.project_discovery` remains the owner of
filesystem discovery and path normalization; the session owner publishes a
resolved cache entry only after the existing resolver succeeds.

`app.py` retains the sidebar renderer, refresh/open controls, Project loading
and opening, Project creation/fork/duplicate refresh sequencing, and all
filesystem, persistence, Project/schema, and UI composition behavior. This
controller does not own Project mutation or persistence, a generic cache or
repository abstraction, or unrelated navigation/session lifecycle.

### Gallery Selected Routes session lifecycle

`ui.gallery_selected_routes_session` owns the multi-route Gallery selection
session lifecycle: `_gallery_selected_route_widget_key`,
`_initialize_gallery_selected_route_widget`,
`_clear_gallery_selected_route_widget_keys`,
`reset_gallery_selected_route_session_state`,
`_apply_pending_gallery_selected_route_widget_reset`,
`_sanitize_gallery_selected_route_session_state`,
`_on_gallery_route_selection_changed`, and
`_set_gallery_selected_route_ids_after_structure_change`, together with the
`SELECTED_ROUTE_WIDGET_PREFIX` constant. The owner controls the session-owned
`gallery_selected_route_ids` list, its
`pro_gallery_route_selected_` widget mirrors, the deferred
`gallery_selected_route_widget_pending_reset` payload, and the dependent
selected-route swap/preview cleanup performed when Project state is reset.
It is specific to the Gallery Selected Routes feature rather than a generic
session-state abstraction.

The lifecycle preserves existing-widget precedence during widget
initialization, durable-selection reconciliation, Project-order and
deduplication behavior, list-copying and falsey semantics, route-keyed widget
callbacks, stale-widget cleanup, deferred sorted/deduplicated resets after
route structure changes, and the exact partial-update and exception behavior.
Project replacement clears the selected-route IDs, pending reset, widget
mirrors, and dependent selected-route preview state in the same order as
before; Undo-style structure changes retain an existing pending reset until
the renderer applies it.

`app.py` retains Gallery rendering and composition, select-all/clear/invert
actions, route cards and separator controls, and all selected-route consumers
for generation, export, adoption, promotion, Module/Attribute swaps, and
lightweight forks. Single-route selectors remain separate from this
multi-route lifecycle. `core.route_operations` remains the owner of the
underlying selection sanitization and toggle operations. The controller does
not own Project or PromptLine mutation, history, persistence/schema,
generation or filesystem/network orchestration, or the feature-specific
operation plans and writes.

## Residual responsibility audit / extraction phase exit criteria

The experiment #10 audit reviewed the residual `app.py` responsibility map
after the stateful and read-only extraction series. The audit classified
responsibility clusters rather than individual functions and found that the
remaining file is mostly intentional application composition or work that
needs a broader design decision.

### A — Terminal shell / wiring (3 clusters)

The following are valid terminal responsibilities for `app.py`:

- Streamlit startup, page configuration, workspace launchers, and top-level
  workspace composition.
- Integration and transition ordering across existing owners, including
  Project loading, Undo, and cross-feature reset publication.
- Rendering and explicit action dispatch that connects existing owners to
  visible controls, including Gallery and Module/Attribute workspace
  composition.

These clusters are application-level composition, not failed extractions.

### B — Broad-design required (5 clusters)

These areas might move in a later product or architecture phase, but are not
small behavior-preserving extraction PRs:

- Project lifecycle and persistence, including Save As, load, Undo, settings,
  asset resets, and discovery refresh.
- Candidate, Variant, and Route mutation, adoption, promotion, and save/history
  sequencing.
- Generation execution, including workflow preparation, progress, output paths,
  Candidate registration, execution logs, and save behavior.
- Filesystem production workflows such as assets, fork materialization, and
  final export, where previews, validation, writes, and publication interleave.
- Shared editing and Module/Attribute authoring, where Global Library authority,
  Project-local replacement, history, graph rebuilding, and Focus restoration
  cross feature boundaries.

Moving these areas requires explicit ownership, persistence, dependency, or
product decisions. They should not be disguised as generic controllers.

### C — Still-safe extraction candidates (2 clusters)

Two bounded, feature-specific draft/widget lifecycles remain candidates for a
separate reviewable extraction:

1. **Module Candidate Selection draft/widget synchronization** — exactly
   `prepare_module_candidate_selection_widget_state`,
   `sync_module_candidate_selection_widget_state`,
   `prepare_module_candidate_core_tokens_widget_state`,
   `sync_module_candidate_core_tokens_widget_state`,
   `prepare_module_candidate_min_match_widget_state`, and
   `sync_module_candidate_min_match_widget_state`. Existing tests cover
   hydration, repair, normalization, independent drafts, handoff, preview
   freshness, apply, and transition ownership. Pending-created-Module handoff,
   previews, rule writes, application, resets, and rendering remain outside it.
2. **Apply-workspace Attribute Group Swap draft/widget synchronization** — the
   prepare/sync pairs for `from_widget_state`, `to_widget_state`,
   `scope_widget_state`, `selected_route_widget_state`, and
   `require_full_match_widget_state`. Existing tests cover defaults, callbacks,
   valid equal groups, invalid-value repair, selected-route retention, and
   hidden-widget reconstruction. Preview, confirmation/reset, target resolution,
   apply/history/save, and Gallery swap ownership remain outside it.

These are candidates because their helpers are feature-specific, call no other
app-defined functions, have existing characterization coverage, and can leave
their renderers and mutation orchestration in `app.py`. They are not a proposal
for a shared widget abstraction.

### D — Legacy / mixed / low-value to extract (3 clusters)

Presentation microhelpers, residual pagination/collapse plumbing, and snapshot
mutation/compatibility fragments remain mixed with their renderers or are too
small to establish a useful independent lifecycle. Earlier pure/read-only
owners already cover the substantial calculations, while the remaining
fragments would mostly distribute glue and legacy sequencing. Leaving these in
`app.py` is reasonable.

### Terminal-shell judgment and exit criteria

The audit judgment is **MOSTLY YES — one or two clearly safe extractions
remain**. The exact remaining Category C boundaries are the two draft/widget
lifecycles above. This is an exit point for open-ended residual discovery:
future extraction work should choose at most one of these bounded candidates
under an explicit request, then reassess. Project/persistence workflows,
Candidate/Route mutation, generation, filesystem production, shared authoring,
generic session/draft/cache/navigation frameworks, tiny formatters, and
recombined existing owners should not be extracted next.

At the audit snapshot, `app.py` was approximately 22,685 lines with 475
top-level functions, compared with the documented initial 24,900 lines and
634 functions. The two Category C candidates span approximately 190 source
lines and 16 helpers in total. The net difference includes intervening product
development and is not an extraction-only measurement; coherent ownership and
behavior preservation remain the objective rather than line-count reduction.
