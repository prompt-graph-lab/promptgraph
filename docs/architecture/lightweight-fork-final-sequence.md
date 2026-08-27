# Derived Project / Final Sequence Materialization Design

Compatibility note: the filename, `lightweight_fork*` functions/session keys, `forks/` directory, manifest operation names, confirmation phrase `FORK FINAL`, and serialized Route fields remain unchanged. The canonical user-facing term is **Derived Project / 派生Project**.

Status: preview model, core materialization apply, Gallery UI Derived Project creation, and **append Selected Scenes to an existing Derived Project** are implemented. Pro v1 can create a new Derived Project or append not-yet-materialized Selected Scenes to one made from the same saved source Project, without changing Project schema, source Project data, or source image files. Append mode can discover same-source Derived Projects from the saved source Project's direct `forks/*` children, while retaining manual path selection for moved or nonstandard destinations.

Derived Project / Final Sequence Materialization turns the currently resolved final image sequence into a new lightweight editable Project. It is the next practical step after Scene Batch Candidate Adoption: adoption chooses or swaps main images by updating `selected_candidate_path`, while Derived Project creation materializes the resolved result into a new baseline Project.

## 1. Concept

The operation creates a new project from the source project's reviewed final/main sequence.

Goals:

- remove dependencies on Candidate, Gallery Variant, Workbench, Trash, and older generated state;
- make the current resolved final image sequence the starting point for the next edit/export/share step;
- safely materialize the result of Scene Batch Candidate Adoption;
- keep image/prompt drift visible through preview before Derived Project creation.

This is not:

- Candidate Prompt Adoption;
- automatic prompt rewriting;
- Lineage rewrite;
- semantic regeneration;
- image file editing or deletion;
- Gallery Variant promotion;
- full project clone;
- multi-set Re-assembly;
- ISDL materialization.

## 2. Main Image Resolution Rule

Derived Project materialization resolves each eligible Gallery Illustration's final main image using the same order as Gallery display, Sequence Preview, and Final Images Export:

```text
selected_candidate_path -> generated_image_path -> image_path
```

Preview shows the resolved final image path and source field for each target Illustration. This keeps Derived Project behavior aligned with Final Images Export and prevents Candidate-backed main images from being lost after Scene Batch Candidate Adoption.

## 3. Output Project Semantics

Derived Project creation is non-destructive. The source Project is not modified, and source images, Candidate images, Gallery Variant images, and Workbench data are not deleted or moved.

For each materialized Illustration (`PromptLine` internally) in the new Project:

- copy the resolved final image into the fork project;
- set the copied image path as the new line's `image_path`;
- clear `selected_candidate_path`;
- clear `generated_image_path`;
- clear `generated_candidates`;
- clear `gallery_variants`;
- do not carry Candidate Trash state;
- do not carry Workbench state;
- do not carry stale candidate lineage or old generated state;
- copy `current_text` unchanged;
- copy `negative_prompt` unchanged;
- preserve line order;
- preserve Route separators / Route structure;
- either generate new fork-local line ids or preserve source ids only as fork-origin metadata.

The fork project should reference only copied images inside the new project. It should not keep its final/main sequence dependent on old project candidate pools.

## 4. File Layout

The preferred layout is project-local:

```text
forks/<fork_name>/
forks/<fork_name>/project.json
forks/<fork_name>/images/
forks/<fork_name>/manifest.json
```

Implementation should define:

- timestamped fork names;
- optional user-specified fork names;
- conflict handling;
- filename sanitization;
- duplicate final image path handling;
- missing file skip handling;
- manifest records containing source project path/name, source line id, source line index, source image field, original resolved path, copied image path, route info, and fork operation name.

The manifest can carry provenance without forcing a project schema change. Any future schema field should be justified by a later implementation PR.

## 5. Preview-First Behavior

Lightweight Fork must be preview-first.

The implemented preview shows:

- target scope;
- target line count;
- exportable/materializable line count;
- skipped line count;
- skipped reasons;
- per-line preview examples;
- source field: `selected_candidate_path`, `generated_image_path`, or `image_path`;
- resolved image path;
- destination image path;
- route info;
- prompt preview;
- drift warning;
- missing file warning;
- duplicate source path handling;
- whether prompt text will be copied unchanged.

Preview does not create `forks/<fork_name>/`, `project.json`, `manifest.json`, image copies, or any other filesystem output. Planned destination paths stay informational until the core materialization helper is explicitly called. Gallery UI Create Fork is available only after a fresh preview, explicit confirmation, saved source project, destination validation, and the exact `FORK FINAL` phrase for All scope.

Core apply requires:

- current preview / stale guard;
- fork name input;
- destination conflict rejection;
- safe planned destination paths;
- existing source images with unchanged size / modified time metadata.

Gallery UI enablement adds confirmation controls before calling core apply, and All scope requires the exact phrase `FORK FINAL`.

The implemented Gallery UI passes both stored and current previews to core apply, displays materialization results, keeps the source project open, and offers `Open Created Fork` only as an explicit immediate switch. Successful creation registers the new Fork `project.json` in Recent Projects without making it the current or last Project and requests a refresh of the session-only Project Directory Browser snapshot. The Sidebar Browser discovers the known `<project>/forks/<fork>/project.json` layout, so a created Fork remains discoverable from the configured root even after it leaves Recent history. It does not auto-save an unsaved source project, auto-switch to the fork, or overwrite an existing destination.

## 6. Scope

Lightweight Fork should reuse the existing Route-aware scope model:

- All
- Current Route
- Selected Route
- Selected Routes (session-only Gallery selection)
- Selected Lines

It should use the same target resolution assumptions as Route-scope Batch Candidate Adoption and Final Images Export where practical.

Selected Routes resolves `gallery_selected_route_ids` through the shared session-only Selected Routes foundation. Handles are sanitized and ordered by the physical `project.prompt_lines` order; raw checkbox click order is not used. The Fork preview preserves selected Route separators and boundaries, excludes non-selected Routes, Workbench Lines, deleted members, image-less Lines, and missing final images, and records selected Route labels, order, and exclusion counts. The existing single `Selected Route` scope remains unchanged.

Excluded or skipped targets:

- Route separators are preserved as project structure, but are not image materialization targets;
- deleted lines are excluded;
- Workbench lines are excluded;
- image-less or unresolved final-image lines are skipped;
- missing resolved image files are skipped;
- unsupported file types should either be skipped or handled as copy-only, with behavior documented before implementation.

## 7. Image / Prompt Drift Policy

Lightweight Fork copies prompt text unchanged by default.

Therefore:

- Fork does not prove image/prompt consistency;
- Candidate Prompt Adoption remains separate;
- if the selected image and prompt are semantically out of sync, fork preserves that drift unless the user resolves it first;
- preview must warn about this;
- future AI/VLM consistency checks may help, but are not a Pro v1 requirement.

## 8. Data Update Rules

Fork project generation should keep:

- `current_text`;
- `negative_prompt`;
- Route separator / route metadata;
- line order;
- human-readable filenames when safe;
- existing prompt module references when they are part of the prompt text model.

Fork project generation should reset or clear:

- `selected_candidate_path`;
- `generated_image_path`;
- `generated_candidates`;
- `gallery_variants`;
- Workbench state;
- Candidate Trash state;
- transient preview/cache state;
- stale adoption preview state;
- Comfy generation run state;
- old `source_generation_info` when it points to old candidates/generated outputs.

Fork project generation should add provenance outside the destructive data path:

- source project path/name;
- created_at;
- source line id;
- source line index;
- source image field;
- source image path;
- copied image path;
- fork operation name;
- optional fork parent project id.

Lineage rewrite is future/polish. A fork provenance manifest is expected; whether any provenance also belongs in project JSON should be decided by the implementation PR.

## 9. Relationship To Final Images Export

Final Images Export:

- is output-only;
- copies final images to `exports/final`;
- writes an export manifest;
- does not create an editable project;
- does not reset candidates or variants.

Lightweight Fork / Final Sequence Materialization core apply:

- creates a new editable project;
- copies resolved final images into the fork project;
- sets copied images as new baseline `image_path` values;
- clears candidate / variant / generated transient state;
- keeps prompt text unchanged;
- preserves route/order structure;
- is used as the next editing baseline.

The current core implementation writes through a staging directory and renames the staged fork into place only after image copies, `project.json`, and `manifest.json` succeed. Existing fork destinations are never overwritten. Failure cleans staging where possible and leaves the source project and source images unchanged.

On Windows, the final staging-directory commit and failed-staging cleanup use bounded retries for recognized transient filesystem locks such as Access Denied (`winerror == 5`), Sharing Violation (`winerror == 32`), and Lock Violation (`winerror == 33`). Each commit attempt rechecks the final destination, and existing destinations are still treated as conflicts rather than overwritten. Non-retryable errors fail immediately; retry exhaustion still attempts staging cleanup without touching the source project, source images, or final destination.

### Append Selected Routes to Existing Fork

Append mode is an append-only continuation of materialization, not a Fork rebuild. Its Target Routes control supports **Single Route**, using the shared Lightweight Fork Route selector and Route Actions shortcut target, and **Selected Routes**, using the session-only Gallery Route checkbox set. Single Route is passed to the existing Selected Routes resolver and Append core as a one-item Route handle list; both modes are resolved in physical source Project order. The target scope and single Route selection are shared with Create New Fork, survive switching between Create and Append in the same Project session, and reset on Project transition. Preview validates the destination's v1 Lightweight Fork manifest, normalizes the current and manifest `source_project_path` values, and classifies each resolved Route as appendable, already materialized, or blocked. Only Forks created from the same saved source Project are accepted. A Fork that is currently open is rejected because an external disk update could overwrite session-only edits.

When a whole external Project is copied through [Safe Existing Project Import](project-root-import.md), supported Fork manifests are rebased together with their Fork Project JSON. Registered source/destination and Append-history paths follow the imported primary Project and Fork locations, preserving the normalized same-source check for later Append. Relative copied-image paths remain relative; malformed or unsupported manifests are retained unchanged with a warning rather than rewritten heuristically.

The Append UI performs a lightweight discovery scan of direct child directories under `<source-project-directory>/forks`. The discovery root itself must resolve inside the source Project directory; an external custom root or a `forks` symlink/junction that escapes that directory is rejected before listing children or loading manifests. Discovery reads only supported `manifest.json` summaries whose normalized `source_project_path` matches the current saved source Project and whose sibling `project.json` and `images/` paths remain inside the candidate directory. Path or symlink escapes, malformed/unsupported manifests, missing members, and duplicate resolved candidates are excluded. The displayed Route count is the number of distinct Routes proven by `materialized_entries`, created Route separators, and corresponding append-history records, not the historical `selected_route_count`. Results are session-cached until explicit Refresh, Project switch/reset, Create success, or Append success. The selectbox is only a convenience: Fresh Preview still performs the authoritative full Project, manifest, source, currently-open, Route-materialization, image-inventory, and stale-signature checks. `Browse another Fork...` preserves the existing manual path fallback.

The operation preserves every existing Fork PromptLine and its raw JSON fields, prompts, image references, Candidates, Gallery Variants, modules, attributes, project metadata, and provenance. Only new Route blocks are added at the physical tail. New separators and normal Lines receive fresh IDs that exclude all existing Fork IDs. New Lines use the same materialization semantics as Create Fork: prompt and negative prompt text are copied unchanged, the resolved image is copied into `images/`, and Candidate, Gallery Variant, selected/generated override, `source_generation_info`, and `lineage_info` state starts empty. Image numbering continues after the highest existing numeric prefix and does not rename or fill gaps in existing files.

The manifest keeps its original operation, version, `created_at`, and unknown fields. Its cumulative Route/materialization fields are extended, `updated_at` is recorded, and `append_history` stores each append snapshot and the previous manifest digest. Duplicate detection uses Routes proven to exist by `materialized_entries` or an actually created Route separator; selection-only `selected_route_ids` and `source_route_blocks` are not treated as materialization evidence. An older manifest that cannot identify its materialized Routes is rejected instead of guessing. Cross-source append, Route replacement, Route update, duplicate Route versions, and conflict merge remain unsupported.

Apply re-reads the saved source Project, destination `project.json`, manifest, image inventory, and source image stats immediately before work and again before commit. It clones the entire Fork into a sibling staging directory, adds images and JSON there, validates the staged Project, then swaps the directory through a temporary backup with bounded Windows retries. Any pre-commit failure removes staging; a swap or backup-cleanup failure restores the previous Fork. The current source Project, its history, dirty state, and autosave are not touched.

After successful Append, the destination Fork is promoted in Recent Projects and the discovery cache is invalidated so Route, Line, append-history, and update-time summaries can be refreshed. Failed Create or Append does not change Recent Projects. Neither success path auto-opens the Fork or changes the source Project session.

## 10. Relationship To Route-Scope Batch Candidate Adoption

Route-scope Batch Candidate Adoption chooses or swaps main images by updating `selected_candidate_path`. Adoption is reversible/history-preserving inside the source project.

Lightweight Fork materializes the resolved result into a new project. Fork is non-destructive, but it creates a new baseline with copied final images as `image_path`. Fork should happen only after the user has reviewed image/prompt drift.

## 11. Relationship To Future ISDL / Re-Assembly

Lightweight Fork is a practical Pro v1 production workflow, not ISDL materialization and not multi-set Re-assembly. It may produce useful reviewed data for future Exp/Desktop workflows, but it should not introduce ISDL schema, Attribute State / LineBinding behavior, or multi-set composition.

## 12. Future Work

The following remain future work:

- Candidate Prompt Adoption integration;
- AI/VLM consistency checks;
- Lineage rewrite / semantic provenance graph;
- Attribute State / LineBinding integration;
- ISDL materialization;
- Re-assembly / multi-set workflows;
- desktop-specific file packaging;
- archive/zip export;
- external sharing package;
- automatic prompt regeneration;
- destructive cleanup of old candidates.
