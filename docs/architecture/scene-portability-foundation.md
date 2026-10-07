# Scene Portability Foundation Audit

Status: repository-backed design audit at `6534b35dadebdcf049c75654744bf9796e1d3917` (PR #128 merge). The audit records current owners and the first implementation boundary for image-less Project-to-Project Scene transfer. The pure source projection in that boundary is now implemented in [`core.scene_portability`](../../core/scene_portability.py); Scene Import and Global Scene Template remain unimplemented.

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
| Preview and side effects | Preview is read-only; Apply stages image copies, Project JSON, and manifest then commits a new directory. | No separate reviewed Preview envelope; mutation inserts rows in memory. No files are copied. | Save/Add previews and user-level Template file are design-only. | First slice is a pure, read-only source projection. Later Preview/Apply owns target conflicts, freshness, history, and persistence. No operation in this audit writes a target Project. |

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
| Initial caller | Focused unit tests only. A later Scene Import Preview becomes the first production caller after its contract is separately reviewed. |
| Not migrated | `duplicate_route_as_baseline`, `build_lightweight_fork_project`, Derived Project append, Global Scene Template (still design-only), and existing Module Swap stay on their current owners and semantics. |
| Tests | Cover explicit separator resolution, empty Scene, source physical ordering, verbatim positive/negative prompts, exclusion of deleted/Workbench/image/Candidate/Variant/generation state, required Module snapshot closure and portability filtering, unresolved source Module and unsafe metadata blockers, JSON-safe output, source Project immutability, and stable fingerprint sensitivity to transferred content. Target same-name compatibility belongs to the later target Preview/Apply tests. |
| Risk rationale | This proves exactly what crosses the Project boundary before introducing target mutation, review custody, history, or persistence. It prevents accidental reuse of the richer image-carrying or final-sequence operations. |

Only after this seam is reviewed should a separate Scene Import Preview/Apply slice add target conflict analysis, fresh-ID allocation, staleness checks, correspondence receipt persistence, normal app history/save integration, and user approval. The existing `duplicate_route_as_baseline` and Derived Project callers should not be migrated to the new owner unless a later behavior-preserving audit proves a common contract.

### Implemented source projection contract

The test-only entry point is `project_scene_portability_payload(project, separator_id)`. It returns contract version `promptgraph.scene-portability.v1`. A valid result contains the resolved source separator id, Scene label/color and physical index, Illustration records, portable Module snapshots, and a `sha256:` fingerprint. Each Illustration record carries its source line id as provenance, the zero-based physical `prompt_lines` index, its zero-based order among included Illustrations, and the exact current positive and negative prompt strings. An explicitly selected empty Scene is valid.

The Module closure is discovered from positive prompts with the existing prompt parser and Module matching rules, then normalized through the existing Module library helpers. Unresolved or malformed referenced Modules block the projection. Snapshots omit `reference_assets` and known local path fields recursively; unknown metadata containing local absolute paths is filtered, and a path in semantic Module body text or Scene metadata blocks the projection. Portable URLs and other JSON-safe extension metadata are retained. Negative prompts are copied verbatim but are not used to discover Modules.

The fingerprint is SHA-256 over canonical JSON containing the contract version, source separator id, Scene label/color/physical index, ordered projected Illustration records, and portable Module snapshots. Image/Candidate/Variant/generation state and other excluded Project data do not affect it. Failure results contain bounded reason-code diagnostics without exception details. This projection allocates no target ids, has no target compatibility or Apply behavior, and is not yet called by production code.

## Follow-on order

1. Pure source Scene portability projection (implemented above; no production caller yet).
2. Preview/apply for explicit Project-A→Project-B Scene Import, including target Module conflicts, fresh target IDs, durable advisory correspondence, stale-source/target checks, and normal host-owned history/save.
3. Agent-facing exposure only after the human approval/custody boundary is defined; keep Module Swap as its existing operation.
4. Pixiv Publish Skill workflow only after the deterministic primitives and review boundaries exist.

This audit does not authorize or implement any of those later slices.

## Evidence index

- Scene structure and Duplicate Scene contract: `core/route_operations.py` (`resolve_route_block`, `_prepare_route_baseline_duplicate`, `duplicate_route_as_baseline`); `tests/test_route_duplicate_baseline.py` (`test_duplicates_contiguous_route_with_fresh_ids_and_preserved_source`, `test_clears_candidate_state_but_retains_resolved_main_path_and_metadata`, `test_round_trip_retains_duplicate_structure_and_metadata`).
- Derived Project eligibility, preview, ID generation, materialization, and manifest: `core/lightweight_fork.py` (`resolve_selected_routes_fork_plan`, `build_lightweight_fork_preview`, `build_lightweight_fork_project`, `build_lightweight_fork_manifest`, `materialize_lightweight_fork`); `tests/test_lightweight_fork_materialization.py` (`test_successful_materialization_round_trips_project_and_manifest`, `test_selected_lines_include_needed_route_separators_once`).
- Append-only/same-source behavior: `core/lightweight_fork_append.py`; `docs/architecture/lightweight-fork-final-sequence.md` (“Append Selected Routes to Existing Fork”).
- Current Project and PromptLine schema/persistence: `core/project.py`; `core/io.py` (`_project_to_serializable_data`, `_normalize_project_metadata`, `load_project_from_json`).
- Module import, prompt-only container, Module Swap requirements: `core/operations.py` (`import_global_modules_to_project`, `preview_module_swap`), `core/module_container_policy.py`, `core/module_swap_selected_routes.py` (`_module_validation`); `tests/test_module_swap_selected_routes.py` (`test_empty_invalid_and_duplicate_selections_fail_closed`, `test_preview_is_source_immutable`).
- Design-only reusable Module snapshot policy: `docs/architecture/global-route-template.md` (“Status: design note only”, §5–6). Product/Skill boundary and scene-transfer goals: `docs/architecture/pixiv-publish-skill-plan.md`.
