# Incremental app extraction

Implemented against public `prompt-graph-lab/promptgraph` main commit
`8462a54cbbf4984e1f224e07041b53df00209d22`. That baseline's `app.py` has
24,900 lines and 634 top-level functions. This change moves 11 functions into
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

## Implemented steps

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

## Validation

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

## Remaining risks and next boundaries

There is no Project schema or save/load change. This does not establish support
for every third-party ComfyUI node graph. For example, a node connected to both
positive and negative roles still receives the negative assignment last and
counts twice; this existing behavior is characterized, not corrected here.
The literal-comma display diff also retains its existing grouping limitations.

Next, extract the Module rule/token normalization helpers as another read-only
boundary, or extend workflow preparation into a module with explicit workflow
text and settings inputs. Keep metadata/file selection separate from execution.
Only then consider moving a complete UI panel, with its session/widget keys and
history/reset contract documented and exercised through navigation tests.
Candidate normalization is a later candidate: first separate its path resolution,
record compatibility and session-cache dependencies from adoption mutations.
Moving all Gallery or all Module UI at once would cross too many of those owners.

Unrelated observation: the locked Streamlit runtime emits an existing
`st.components.v1.html` deprecation warning. The keyboard/clipboard iframe
compatibility owner is unchanged; replacing it is outside this extraction.
