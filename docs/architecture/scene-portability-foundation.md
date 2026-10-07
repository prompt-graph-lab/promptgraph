# Scene Portability Foundation Audit

Status: repository-backed design audit at `6534b35dadebdcf049c75654744bf9796e1d3917` (PR #128 merge). The audit records current owners and the first implementation boundary for image-less Project-to-Project Scene transfer. The pure source projection, target Preview, and in-memory core Apply are implemented in [`core.scene_portability`](../../core/scene_portability.py) and [`core.scene_import`](../../core/scene_import.py). The user-facing Scene Import workflow and Global Scene Template remain unimplemented.

## Decision

Do not extract a generic materialization kernel from either Derived Project or Duplicate Scene as Baseline. They materialize different products and preserve different state. Reuse the existing structural Scene resolver, then introduce a separate pure source-projection owner for the portable Scene payload. Keep target mutation, persistence, and UI out of that first slice.

The portable v1 shape should contain the selected separator's label and color, plus active non-Workbench Illustration members in physical Scene order with their current positive and negative prompt text verbatim. It should have no image references or generated state. It should include portable snapshots for Module definitions required by positive-prompt Module references, under the rule in [Module portability](#module-portability). An explicitly selected empty Scene remains valid; its separator is still meaningful structure.

## Current ownership and evidence

| Concern | Current owner | What it establishes |
|---|---|---|
| Scene membership | [`core.route_operations.resolve_route_block`](../../core/route_operations.py) and the `RouteBlock` model | A Scene is a separator `PromptLine` followed by contiguous members up to the next separator. Membership is positional; the resolver distinguishes active, deleted, and Workbench members. Scene is not a separate Project-schema object. |
| Duplicate Scene as Baseline | [`core.route_operations._prepare_route_baseline_duplicate`](../../core/route_operations.py) and `duplicate_route_as_baseline` | A same-Project, in-place duplicate which keeps the entire block shape, including deleted and Workbench lines, and resolves a main image path for each copied line. It is deliberately image-carrying. |
| Derived Project / Lightweight Fork | [`core.lightweight_fork.build_lightweight_fork_project`](../../core/lightweight_fork.py), `materialize_lightweight_fork`, and append owner [`core.lightweight_fork_append`](../../core/lightweight_fork_append.py) | A new editable Project containing materializable final-image rows. It copies resolved image files and writes Project JSON plus a manifest. This is final-sequence materialization, not image-less Scene transfer. |
| Project persistence | [`core.project.PromptLine` / `Project`](../../core/project.py) and [`core.io.save_project_to_json` / `load_project_from_json`](../../core/io.py) | `PromptLine` already has `duplicated_from` and `lineage_info`; Project JSON serializes dataclass fields and the loader preserves JSON dictionaries in those existing fields and in `project_metadata`. There is no stable Project UUID field in the current model. |
| Module portability | [`core.module_container_policy`](../../core/module_container_policy.py), Global Module import in [`core.operations.import_global_modules_to_project`](../../core/operations.py), and selected-Scene Module Swap in [`core.module_swap_selected_routes`](../../core/module_swap_selected_routes.py) | Current prompt-only container projection removes `reference_assets`; Global-to-Project import copies from the Global library, not from another Project. Module Swap requires both Module names to exist in the target Project library. |
| Global Scene Template | [`docs/architecture/global-route-template.md`](global-route-template.md) | Design only. Its portable Module snapshot and same-name conflict rules are useful precedent, but no Template implementation or reusable snapshot function exists. |

Relevant characterization is in [`tests/test_route_duplicate_baseline.py`](../../tests/test_route_duplicate_baseline.py), [`tests/test_lightweight_fork_materialization.py`](../../tests/test_lightweight_fork_materialization.py), [`tests/test_module_swap_selected_routes.py`](../../tests/test_module_swap_selected_routes.py), and the Global Module import/policy tests. The route ownership and duplicate contract are also described in [`docs/architecture/route-operations.md`](route-operations.md); the Derived Project contract is in [`docs/architecture/lightweight-fork-final-sequence.md`](lightweight-fork-final-sequence.md).

## Operation comparison

| Dimension | Derived Project / Lightweight Fork (implemented) | Duplicate Scene as Baseline (implemented) | Global Scene Template (design only) | Cross-Project Scene Import (proposed) |
|---|---|---|---|---|
| Purpose / target | Materialize a final image sequence in a new Project. | Make an image-carrying baseline beside a Scene in the same Project. | Save a reusable user-level prompt-structure asset. | Transfer reusable Scene structure from an explicitly selected source Project into an explicitly selected target Project. |
| Rows and state | Includes eligible active rows with a resolved final image; skips deleted, Workbench, and no-image rows. Candidate/Variant/generation transient state and line lineage start empty. | Deep-copies the whole contiguous block, including deleted and Workbench rows. Clears Candidate and Variant collections and image overrides, but retains the resolved main image as `image_path`; remaps Workbench source references. | Stores ordered positive and negative prompt structure; excludes images and transient Project state. | Includes only active, non-Workbench Illustration rows in source order. Excludes deleted/Workbench rows, Candidate/Variant state, source-generation history, and transient UI state. |
| Prompts / Scene properties | Copies current positive and negative prompts; creates new separators for included source Scenes. | Copies current positive and negative prompts; creates a fresh separator, label, and color. | Stores Scene label/color and prompt text by design. | Copies current positive and negative prompts verbatim and carries separator label/color. Target `original_text` is initialized from transferred current positive text; tokens are rebuilt by normal target Project logic. |
| Images / files | Resolves selected → generated → baseline image; copies files under the new Project and points new rows to those copies. | Resolves selected → generated → baseline image and points the duplicate at that same path; copies or changes no files. | Image-less by design. | Image-less: does not copy or retain image paths, image bytes, Candidate records, or image-derived generation metadata. |
| IDs | New separator and Illustration IDs; manifest maps source IDs to new IDs. | Fresh IDs for every copied member; `duplicated_from` and `lineage_info` record same-Project provenance. | Fresh target IDs on Add by design; no source row IDs in template structure. | Fresh target separator and Illustration IDs. Source IDs appear only in advisory correspondence metadata, never as target IDs or lookup keys in the target Scene. |
| Modules | Copies the Project Module library through the prompt-only container policy; strips `reference_assets`. | Leaves the same Project Module library in place; does not copy Modules. | Proposed portable snapshots, unresolved-source blockers, and same-name definition conflict blockers. | Carry prompt-only snapshots needed to resolve positive-prompt Module references. Reuse identical target definitions, import missing definitions, and block unresolved source references or differing same-name definitions. Never copy Module asset files or `reference_assets`. |
| Provenance | External `manifest.json` records source/fork line correspondence and source paths; fork PromptLines begin with empty lineage. | Existing `duplicated_from` plus additive `lineage_info`; `project_metadata` stays unchanged. | Source Project name is descriptive design metadata; Add does not create an ongoing link. | Persist a namespaced transfer receipt in existing target Project metadata, with an operation id, source Scene fingerprint, and per-line source→fresh-target map. Treat it as a receipt, never as Scene ownership or an authority to load the source. |
| Ordering / destination | Creates a separate Project and preserves source physical order for selected materializable rows; append extends only a same-source Derived Project. | Inserts the new block immediately after the source block. | Add position is a design choice, normally end of Scene list or an explicit position. | V1 should append one new block at the physical end of the target `prompt_lines`; no implicit reordering or replacement. |
| Preview and side effects | Preview is read-only; Apply stages image copies, Project JSON, and manifest then commits a new directory. | No separate reviewed Preview envelope; mutation inserts rows in memory. No files are copied. | Save/Add previews and user-level Template file are design-only. | Source projection and target Preview are pure/read-only. The reviewed core Apply revalidates and mutates the target in memory; the host lifecycle publishes Undo history, Gallery state, and autosave after success. Visible UI wiring remains future work. |

The closest existing *structural* behavior is `resolve_route_block`; the closest existing *fresh-ID, ordered separator/member construction* is the duplicate preparer, but it intentionally copies all rows and their resolved image references. The closest existing *portable, fresh-ID Project materialization* is Lightweight Fork, but it requires final images and makes a new Project. There is no existing shared Scene-import materializer to extract without changing those operations' contracts.

## Structure-only transfer contract

The eventual Preview/Apply operation should:

- require an explicit source Project and active separator-line handle; never infer “current Scene” or select a Scene by label;
- preserve the source Scene's physical member order, separator label/color, and each active Illustration's current positive and negative prompt strings exactly;
- create a fresh target separator id and fresh Illustration ids, disjoint from all target ids; never reuse the source separator/line ids as target identity;
- omit deleted lines, Workbench lines, images and paths, Candidates, Gallery Variants, selection state, generation metadata, and unrelated Project metadata;
- include an empty Scene when explicitly selected rather than interpreting it as corruption;
- append as a new Scene at the target's physical end in v1; leave existing target rows and Scene ordering unchanged;
- resolve source Module references into portable Module snapshots and preview target conflicts before Apply, under the rule below;
- preview all rows, snapshots, skipped source state, target insertion position, ID allocation, and conflicts before the host applies; revalidate source and target state at Apply;
- mutate only the target Project after a fresh reviewed plan. Source Project and source image files remain untouched. Saving/history publication remain with the existing Project host.

This is a one-time copy, not synchronization. Subsequent edits to either Project do not propagate to the other.

## Module portability

Use one prompt-only snapshot rule, aligned with the design in [Global Scene Template §5–6](global-route-template.md#5-module-identity-and-snapshots):

1. Scan active positive prompt Module markers and recursively follow Module markers in each referenced Module body using current prompt expansion semantics. Resolve every definition in the source Project and preserve marker text verbatim. If any reference in that closure has no source definition, block Preview/Apply with the unresolved name; do not create a dangling target marker.
2. Carry a portable snapshot of every source Module in that reference closure. A Module snapshot includes its normalized semantic definition and supported portable metadata, but no local assets.
3. In the target, reuse a same-name Module only when the normalized portable definitions are equal. Import a missing Module snapshot. A different same-name definition is a conflict and blocks Apply; v1 does not overwrite, silently substitute, or auto-rename.
4. Strip known local-path metadata recursively, exclude any unknown metadata containing machine-local absolute paths, and always exclude `reference_assets`; if the snapshot cannot be made demonstrably portable, block it. Do not copy files under `refs/modules/`.

The current `module_library_for_prompt_only_container()` is not by itself a complete cross-Project snapshot sanitizer: it removes `reference_assets` but intentionally preserves other fields, including unknown values that may contain local paths. The Global Scene Template path-filter/equality policy remains design-only and must be implemented and tested before being reused. Module Swap remains its existing separate operation, requiring the source and replacement definitions to be available in the target Project.

Negative prompts remain verbatim data; v1 Module resolution and Module Swap remain positive-prompt-only as they are today. Do not attempt to bind or rewrite Module references in negative text.

## Source-to-target correspondence

Use the existing JSON-persisted `Project.project_metadata` container for an additive, namespaced `scene_transfers` receipt rather than setting `PromptLine.duplicated_from` across Projects. A receipt groups one import with an opaque operation id, a digest of the exact portable source Scene snapshot, and a list of source separator/Illustration ids paired with fresh target ids. It may include a source display name for people, but must not include an absolute source path or rely on it to reopen the source.

This fits current persistence without a new Project/PromptLine field: `_project_to_serializable_data()` serializes `project_metadata`, `_normalize_project_metadata()` preserves unknown JSON keys, and the loader restores the dictionary. By contrast, `duplicated_from` is a bare line id with no source-Project namespace; alone it is ambiguous across Projects. `lineage_info` is line-local and existing Candidate Adoption replaces it, so it is not a reliable owner for a whole transfer correspondence map.

Target `PromptLine.id` remains the only identity used by Scene membership and operations. Source ids in a receipt are historical provenance only and must never be resolved against the target Project. A later comparison must require the user-selected source Project and verify the stored portable Scene fingerprint; a changed/missing source Scene makes the receipt stale or unverifiable, not a reason to guess. There is no stable Project UUID in the current model, so the receipt proves content correspondence to the captured Scene snapshot, not an immutable Project identity. This is an explicit limit, not a dependency on paths or matching Project names.

Receipts are advisory and no operation may require them for normal Scene ownership. The initial source-projection slice below does not write receipts because it creates no target. Before a later Apply is delivered, its caller audit must cover how Project materialization operations such as Derived Project creation retain, clear, or re-map receipts when they assign fresh target IDs; this audit does not change those existing callers.

## FIRST-SAFE-BOUNDARY

Implement one pure domain seam before any cross-Project Apply:

| Contract | First slice |
|---|---|
| Owner | New `core.scene_portability` module, using `resolve_route_block` for positional membership. Do not move code out of Duplicate Scene, Lightweight Fork, app.py, or the Template design. |
| Input | Explicit source `Project` and active source separator-line handle. No target Project, path, Streamlit state, or filesystem dependency. |
| Output | A versioned JSON-safe portable payload containing Scene label/color, ordered active Illustration source records (source line id as provenance, current positive/negative text), referenced portable Module snapshots, a source Scene fingerprint, and bounded diagnostics/blockers. No Python Project/PromptLine objects escape. |
| Identity | No target id generation or target identity changes in this slice. Source ids are carried only as payload provenance. Target IDs are assigned by a later target-side Preview/Apply operation. |
| Side effects | Read-only. No Project mutation, graph rebuild, Project save, filesystem read/write, history publication, session state, MCP tool, or UI. |
| Initial caller | The source projection is exercised by focused tests and the pure target Preview below. There is no app/session/MCP production caller yet. |
| Not migrated | `duplicate_route_as_baseline`, `build_lightweight_fork_project`, Derived Project append, Global Scene Template (still design-only), and existing Module Swap stay on their current owners and semantics. |
| Tests | Source projection tests cover explicit separator resolution, empty Scene, source physical ordering, verbatim positive/negative prompts, exclusion of deleted/Workbench/image/Candidate/Variant/generation state, required Module snapshot closure and portability filtering, unresolved source Module and unsafe metadata blockers, JSON-safe output, source Project immutability, and stable fingerprint sensitivity to transferred content. Target same-name compatibility and target-side freshness are covered by the Preview tests below. |
| Risk rationale | This proves exactly what crosses the Project boundary before introducing target mutation, review custody, history, or persistence. It prevents accidental reuse of the richer image-carrying or final-sequence operations. |

The pure target Preview implemented below adds target conflict analysis, fresh target ID planning, target freshness binding, and a planned correspondence receipt without applying it. The core Apply below revalidates the complete reviewed Preview and performs an atomic in-memory mutation. The host lifecycle described below owns history/undo and save integration. The existing `duplicate_route_as_baseline` and Derived Project callers should not be migrated to the new owner unless a later behavior-preserving audit proves a common contract.

### Implemented source projection contract

The entry point is `project_scene_portability_payload(project, separator_id)`. It returns contract version `promptgraph.scene-portability.v1`. A valid result contains the resolved source separator id, Scene label/color and physical index, Illustration records, portable Module snapshots, and a `sha256:` fingerprint. Each Illustration record carries its source line id as provenance, the zero-based physical `prompt_lines` index, its zero-based order among included Illustrations, and the exact current positive and negative prompt strings. An explicitly selected empty Scene is valid.

The selected separator id and every included Illustration id must each be unique across the whole source Project before they are emitted as provenance. Duplicate ids that are unrelated to the selected Scene do not by themselves block projection.

The Module closure is discovered from positive prompts with the existing prompt parser and Module matching rules, then normalized through the existing Module library helpers. Traversal is breadth-first and bounded to 20 levels and 256 distinct Module snapshots. If the required closure exceeds either bound, projection blocks with `module_closure_limit_exceeded`; it never returns a partial snapshot set as valid. Cycles that the existing Module rules tolerate remain deterministic. Unresolved or malformed referenced Modules also block the projection. Snapshots omit `reference_assets` and known local path fields recursively; unknown metadata containing local absolute paths is filtered, and a path in semantic Module body text or Scene metadata blocks the projection. Portable URLs and other JSON-safe extension metadata are retained. Negative prompts are copied verbatim but are not used to discover Modules.

The fingerprint is SHA-256 over canonical JSON containing the contract version, source separator id, Scene label/color/physical index, ordered projected Illustration records, and portable Module snapshots. Image/Candidate/Variant/generation state and other excluded Project data do not affect it. Failure results contain bounded reason-code diagnostics without exception details. This projection allocates no target ids and has no target compatibility or Apply behavior. The target Preview below calls it as its source-side authority; neither owner has a UI, MCP, or persistence caller.

## Follow-on order

1. Pure source Scene portability projection (implemented above).
2. Pure Project-A→Project-B Scene Import Preview (implemented below).
3. In-memory core Scene Import Apply (implemented below).
4. Host Scene Import lifecycle for source reload, Preview custody, successful Undo/Gallery publication, and autosave (implemented below).
5. Human Scene Import panel in Gallery Operations (implemented below); agent-facing exposure remains future work and must preserve the human review boundary.
6. Agent-facing exposure only after its approval/custody boundary is defined; keep Module Swap as its existing operation.
7. Pixiv Publish Skill workflow only after the deterministic primitives and review boundaries exist.

This audit did not implement agent-facing exposure or the Pixiv Publish Skill workflow.

## Evidence index

- Scene structure and Duplicate Scene contract: `core/route_operations.py` (`resolve_route_block`, `_prepare_route_baseline_duplicate`, `duplicate_route_as_baseline`); `tests/test_route_duplicate_baseline.py` (`test_duplicates_contiguous_route_with_fresh_ids_and_preserved_source`, `test_clears_candidate_state_but_retains_resolved_main_path_and_metadata`, `test_round_trip_retains_duplicate_structure_and_metadata`).
- Derived Project eligibility, preview, ID generation, materialization, and manifest: `core/lightweight_fork.py` (`resolve_selected_routes_fork_plan`, `build_lightweight_fork_preview`, `build_lightweight_fork_project`, `build_lightweight_fork_manifest`, `materialize_lightweight_fork`); `tests/test_lightweight_fork_materialization.py` (`test_successful_materialization_round_trips_project_and_manifest`, `test_selected_lines_include_needed_route_separators_once`).
- Append-only/same-source behavior: `core/lightweight_fork_append.py`; `docs/architecture/lightweight-fork-final-sequence.md` (“Append Selected Routes to Existing Fork”).
- Current Project and PromptLine schema/persistence: `core/project.py`; `core/io.py` (`_project_to_serializable_data`, `_normalize_project_metadata`, `load_project_from_json`).
- Module import, prompt-only container, Module Swap requirements: `core/operations.py` (`import_global_modules_to_project`, `preview_module_swap`), `core/module_container_policy.py`, `core/module_swap_selected_routes.py` (`_module_validation`); `tests/test_module_swap_selected_routes.py` (`test_empty_invalid_and_duplicate_selections_fail_closed`, `test_preview_is_source_immutable`).
- Design-only reusable Module snapshot policy: `docs/architecture/global-route-template.md` (“Status: design note only”, §5–6). Product/Skill boundary and scene-transfer goals: `docs/architecture/pixiv-publish-skill-plan.md`.

## Implemented Scene Import Preview

`core.scene_import.preview_scene_import(source_project, separator_id, target_project)` returns contract `promptgraph.scene-import-preview.v1` and operation `scene_import`. It requires explicit Project objects and an explicit source separator id. Passing the exact same Project object as both source and target is rejected. The source side is always obtained through `project_scene_portability_payload`; an invalid source projection is returned as a bounded Preview blocker rather than partially planned.

The Preview appends one complete block at the physical end of `target_project.prompt_lines`: one fresh separator followed by every projected Illustration in source order. It exposes the exact target `PromptLine` fields, including verbatim current positive/negative text, rebuilt tokens, neutral `original_file_name` values, physical indices, and empty image, Candidate, Variant, generation, lineage, and Workbench state. An explicitly empty source Scene plans only its separator. It never returns Python model objects or copies source filesystem names.

Target IDs are SHA-256-derived from the Preview contract, source Scene fingerprint, target freshness fingerprint, source provenance id, row kind, and Scene order. A deterministic bounded counter resolves collisions against all existing target IDs, all source provenance IDs, and earlier planned IDs. The operation/transfer id uses the same deterministic collision-counter approach against valid existing `scene_transfers` receipt ids. Neither identifier authorizes Apply.

For each source portable Module snapshot, target compatibility uses `project_portable_module_definition`, the same sanitization and normalization path used by source projection. A missing name is `import` and its full portable definition is present in that action; a normalized portable definition equal to the source snapshot is `reuse`; a different same-name definition is `conflict` and makes the Preview ineligible. A relevant malformed target Module blocks the plan. Unrelated target Modules are not normalized or included in the freshness fingerprint. `reference_assets` and local path metadata are filtered by the shared portable-definition policy.

The `target_freshness_fingerprint` hashes physical target PromptLine order and the structural/prompt fields used by this plan, normalized relevant same-name target Module definitions (including missing-name state), and the current `project_metadata["scene_transfers"]` namespace. Image paths, Candidate/Variant state, generation state, filesystem metadata, `source_directory`, unrelated Modules, and unrelated Project metadata are excluded. The Preview does not mutate or normalize either Project.

The planned advisory receipt contains a deterministic `transfer_id`, source Scene fingerprint and separator provenance id, fresh target separator id, ordered source-to-target Illustration pairs, and an optional source display label. It contains no Project reference or path and is returned with the append index; it is not persisted. A malformed existing receipt namespace blocks Preview so a later Apply cannot silently replace it.

`projection_digest` covers the complete materialization projection: insertion position, every planned row, Module actions, correspondence map, and receipt. `plan_id` hashes the complete deterministic Preview envelope excluding only its own `plan_id` field. Both are content identities, not approval or authorization. The Preview remains read-only.

## Implemented Scene Import Apply (core)

`core.scene_import.apply_scene_import(source_project, separator_id, target_project, reviewed_preview)` implements contract `promptgraph.scene-import-apply.v1`. It requires the complete JSON-safe v1 Preview envelope, validates its contract and digest fields, and recomputes the Preview from the current explicit source and target. Apply proceeds only when the complete reviewed and recomputed envelopes are equal; IDs or digests alone never authorize an operation. A stale, malformed, tampered, conflicted, or otherwise ineligible Preview returns a bounded failure without changing either Project.

After review equality, Apply uses only the recomputed plan. It deep-copies the target, constructs exact `PromptLine` instances from the planned rows, applies only the planned Module actions, appends the planned receipt at its reviewed index, rebuilds the staged Project graph with `core.graph_builder.build_graph`, and verifies rows, Modules, receipt, and graph postconditions. Only then does it commit the staged state to the existing target object. A failed stage or postcondition leaves the target unchanged. Existing target row objects and physical order are retained; graph-derived `node_path` values may be refreshed by the graph rebuild. A second Apply of the same Preview is stale and does not duplicate the Scene.

The Apply result is bounded JSON-safe evidence of an in-memory operation. It does not prove persistence. Core Apply does not save the Project, publish history/undo, decide human approval, or expose an agent/MCP tool.

## Implemented Scene Import host lifecycle

`ui.scene_import_lifecycle` owns the host-side publication boundary without rendering widgets or wiring a visible panel into `app.py`. `build_scene_import_preview_from_source(...)` normalizes and stores the explicit source path and separator selection, rejects a normalized source path equal to `session_state.current_project_path`, loads the source through an injected `core.io.load_project_from_json` callback, and stores the complete core Preview envelope. Ineligible Preview envelopes are retained for review. The loaded source Project stays local to the call; Preview does not mutate the active target, history, Gallery state, or saved file.

`apply_and_publish_scene_import(...)` requires the same complete Preview object held in the session operation state, rechecks the explicit source/target path boundary, clones the active target before core Apply, and reloads the source Project immediately before calling `core.scene_import.apply_scene_import`. Core stale/non-applied outcomes and host failures clear the one-shot Preview and publish bounded feedback/result state without adding Undo history, synchronizing Gallery state, or saving. Changing the source path or separator invalidates the stored Preview.

After core Apply succeeds, the lifecycle appends the pre-Apply clone to the existing Undo history with the app's 20-entry cap, synchronizes existing Gallery selected-Route state, restores/sanitizes prior focus through the existing app callback, stores the unchanged core result, clears the consumed Preview, and calls the existing save callback exactly once with `Scene Import applied`. Core Apply already rebuilds the graph, so the lifecycle does not rebuild it again. A later autosave failure does not roll back the successful in-memory operation or its Undo entry.

## Implemented human Scene Import panel

`ui.scene_import_panel` is wired into the `scene_import` single-active operation in Gallery Operations under `1. Prompt／構造を編集`. It accepts an explicit source Project JSON path, discovers active non-deleted source separators through `core.operations.get_gallery_route_options`, and displays each Scene label with its Illustration count, including empty Scenes. The Project used for selector discovery is transient and is never stored in session state; Fresh Preview and Apply reload their own source Project through `ui.scene_import_lifecycle`.

The panel uses separate Streamlit widget mirrors for source path, source separator, and human confirmation. Path or Scene changes synchronize through the lifecycle setters and clear the confirmation; a fresh Preview also clears confirmation. It renders the stored Preview's Scene summary, planned Module actions, ordered positive/negative prompts, append position, blockers, and optional technical content identities. Apply is available only for a stored valid and eligible Preview with the explicit one-Scene confirmation. The panel delegates Apply, Undo publication, Gallery synchronization, focus sanitation, and autosave to the lifecycle; it does not repeat those operations.

Successful Apply feedback describes the in-memory operation and directs the user to the app's existing autosave feedback for persistence status. The new Scene is appended to the current Project tail while the lifecycle preserves and sanitizes existing Gallery selection/focus; pagination and collapse state are not changed. The public panel provides no MCP/agent mutation surface or approval token.
