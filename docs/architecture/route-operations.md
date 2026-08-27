# Scene Operations Design

Compatibility note: the filename and internal implementation names (`RouteBlock`, `route_*`, `selected_routes`, separator handles, widget keys, and manifest fields) remain unchanged. User-facing Pro v1 terminology calls a separator-bounded block a **Scene** and reserves **Route** for a possible future higher-level concept spanning multiple Scenes; that future object is not implemented here.

Status: design note plus implementation checkpoint. The internal `RouteBlock` resolver, Scene separator quick-action dispatch, Scene block Move Up/Down, Scene remove with atomic Scene-level restore, Duplicate Scene as Baseline, the session-only Selected Scenes foundation, and the Selected Scenes consumers in Final Images Export, Derived Project, Scene Batch Candidate Adoption, Scene Generation, Module Swap, Attribute Group Swap, and Batch Promote Variants described here are implemented. Other multi-Scene operation connections and deferred scopes remain design-only. No Project schema change is proposed.

Scene Operations covers: the internal `RouteBlock` resolver, Scene separator quick actions, Scene move up/down, Scene remove with atomic Scene-level restore, Duplicate Scene as Baseline, the session-only Selected Scenes foundation, and the existing `selected_routes` consumers. The serialized values and operation engines are compatibility names, not the user-facing domain vocabulary.

The companion asset design is [Global Scene Template Design](global-route-template.md).

## 1. Scene Definition In Pro v1

Pro v1 does not promote Scene to a first-class object in the Project schema. A Scene remains a positional structure:

- a `PromptLine` with `line_type == "separator"`;
- the Illustrations (`PromptLine` internally) from immediately after that separator up to (not including) the next separator;
- including Workbench lines positioned immediately after their source lines, as part of the same contiguous block.

Recommended terminology:

- **Scene block**: the separator plus its positionally-owned Illustrations (including Workbench lines).
- **Scene handle**: the separator `PromptLine`'s stable line id; internal code still calls this a Route handle.
- **Scene Actions**: the Scene operation group on the separator card.

Do not use the term "Scene ID" in Pro v1 user docs. It suggests that a dedicated Scene object exists in the Project schema, which is not the case: the handle is an ordinary `PromptLine` id on the separator line.

## 2. Why Scene Is Not A First-Class Schema Object In Pro v1

- Positional membership is derived from `prompt_lines` order and separator boundaries alone. It cannot desynchronize, because there is no second source of truth to disagree with.
- Adding a per-Illustration `route_id` would create a new inconsistency class: list order and declared membership could diverge, and every insert, move, duplicate, Derived Project, and restore path would have to maintain both.
- The separator line id already works as an internal Scene handle in practice: the Gallery scope UI and Derived Project manifest both use it.
- Every operation in this design — move, remove, duplicate, quick actions — is expressible as a contiguous block operation over the existing list.
- A first-class Scene object, and any future multi-Scene Route object above it, belong to the Desktop Project Object Model phase, not Pro v1.
- When that migration happens, the RouteBlock resolver introduced below is the migration boundary: consumers already talk to the resolver, so replacing positional resolution with object-backed resolution is localized.

## 3. The Implicit Head Block

When PromptLines exist before the first separator, that head block has no Route handle.

Pro v1 policy:

- no implicit Route object is introduced for it;
- if the user wants Route Actions for those lines, they insert a separator at the top, which turns the block into a normal Route;
- the head block without a separator is not a Route Actions target.

## 4. RouteBlock Resolver

The first implementation slice adds a pure core-side RouteBlock resolver. Given a separator id, it resolves:

- the separator line itself;
- member PromptLines;
- Workbench lines inside the block;
- the previous and next separators (block boundaries);
- line count;
- Candidate count;
- Gallery Variant count;
- Workbench count;
- deleted state;
- diagnostics (missing separator, deleted separator, empty block).

The resolver reports structural members, active members, deleted members, Workbench lines, Candidate counts, and Gallery Variant counts without mutating the Project. It does not decide generation, export, adoption, Module Swap, or Lightweight Fork eligibility.

### Resolver Boundary

The RouteBlock resolver is strictly structural. Operation-specific eligibility must not be mixed into the resolver:

- Generation target eligibility;
- Export target eligibility;
- Candidate Adoption target eligibility;
- Module Swap target eligibility;
- Fork target eligibility.

The intended structure is:

```text
resolve_route_block(...)
    -> structural Route block (separator, members, workbench, boundaries, counts, diagnostics)

operation-specific target resolvers
    -> generation exclusions
    -> export exclusions
    -> adoption exclusions
    -> fork exclusions
```

The RouteBlock resolver must not grow into a universal do-everything resolver. Operations consume its structural output and apply their own existing eligibility rules on top.

## 5. Existing Scope Resolver Debt

Design docs describe a "shared scope resolver", but the implementation is not fully shared: `selected_route` / `current_route` style scope branches are duplicated in many places across `app.py` (generation, batch prompt editing, candidate route creation, adoption, export, fork, Module Swap and others). This is existing design debt, and Route Operations must not amplify it.

Pro v1 policy:

- new Route Actions use the RouteBlock resolver;
- new features do not add another copy of the scope-branch pattern;
- the 15+ existing duplicated branches are not all refactored at once;
- existing operations migrate to the shared resolver incrementally, starting from the ones Route Actions touch;
- the session-only Selected Routes foundation currently connects to Final Images Export, Lightweight Fork, Route-scope Batch Candidate Adoption, Gallery Generation, Module Swap, Attribute Group Swap, and Batch Promote Variants; shared scope migration remains future work before broader Multi-Route operation support.

## 6. Route Separator Quick Actions

The first implementation slice adds a `Route Actions` expander to active Route separator cards. The UI groups actions inside the expander or popover on the separator card, following the existing Candidate card `追加` expander pattern; it does not place a row of bare buttons on the card.

Primary shortcuts:

- generate all lines in the Route;
- Route Candidate Adoption;
- Final Images Export for the Route;
- Lightweight Fork.

Each shortcut only dispatches to the existing operation panel with `Selected Route` and the separator line id preselected. It does not execute generation, adoption, export, or fork creation inside the separator card.

These shortcuts do not duplicate any apply logic inside the separator card. A shortcut only:

- sets the target Route handle;
- opens the existing operation panel;
- pre-selects the scope as Selected Route;
- delegates to the existing preview / apply / confirmation UI.

All existing safety mechanisms remain in force unchanged:

- Generation's existing target resolution;
- Candidate Adoption's preview signature;
- the mandatory drift warning;
- the separation from Candidate Prompt Adoption;
- Export preview;
- Lightweight Fork's fresh-preview requirement;
- confirmation checkboxes;
- All-scope typed phrases (`APPLY ALL`, `FORK FINAL`);
- destination conflict validation;
- no-overwrite behavior.

The Gallery Operations launcher remains available; separator shortcuts are an additional entry point, not the only one. Its Route-based production order is Prompt / structure operations, Gallery Generation, then Batch Candidate Adoption. Each phase now has an explicit launcher and renders through the same session-only `gallery_operations_active` panel contract directly below that phase. Only one operation body is active at a time, and inactive Generation / Adoption bodies are not called. The panel's shared header, context caption, and close action do not mutate the Project, history, selection, pagination, expanded Route, or Focus. Generation / Adoption draft values use durable same-Project session keys with temporary widget mirrors so hidden-widget cleanup does not erase them; fresh Previews remain available across close/reopen, while confirmation checkboxes and exact phrases are cleared on close or operation switching. Successful Project replacement clears the operation state and Previews, while failed replacement preserves them. Route separator Generation / Adoption shortcuts select the same unified panels and preselect their existing `Selected Route` scope. The Line / Workbench workflow remains unchanged. Operation engines, scope options, Preview signatures, history/save behavior, Project storage, lineage, and schema semantics do not move. Migration to a shared Gallery scope resolver remains a Pro v1.1 candidate.

The stable Operation Scope panel exposes the existing `gallery_selected_route_ids` owner without promoting it into a universal scope. Its count and bounded label summary reuse the already-sanitized Scene state. Select All, Invert, Clear, and separator checkboxes retain their existing keys and Project-order identities. Scene-based scopes exclude Illustrations outside separator-owned blocks; All Illustrations can include eligible outside-Scene Illustrations according to the owning engine. Each operation still owns its machine values, single-Scene selector, selected-Illustration source, target resolution, Preview signature, and blocking behavior. `core/gallery_operation_scope_presentation.py` is deliberately display-only metadata for the collapsed support matrix and active-panel capability copy; no core planner imports it. Shared resolver/state migration remains Pro v1.1 work.

## 7. Route Move Up / Down

Route move is approved for Pro v1.

Semantics:

- moves the contiguous Route block from the separator up to (not including) the next separator;
- never moves the separator alone;
- never splits member lines from their Route;
- never separates Workbench lines from their source lines;
- Candidates, Gallery Variants, and metadata stay inside their lines and move with them;
- no source image or Candidate image file is moved or deleted;
- no project schema change;
- reversible through the existing undo history.

UI:

- `Move Route Up` / `Move Route Down` inside Route Actions;
- after a move, focus/scroll is restored using the separator handle so the user does not lose the Route they just moved.

Implementation checkpoint:

- the move helper reorders one contiguous `prompt_lines` slice from the target separator to the next separator;
- separator, normal members, Workbench members, deleted members, Candidates, Gallery Variants, prompts, lineage, and metadata move together;
- the first explicit Route never crosses the unowned head block, and deleted separators are not move targets or adjacent move destinations;
- only `current_index` is reindexed after a successful move; no Route object, per-line `route_id`, or new schema field is added;
- Route-order-dependent Gallery previews are cleared after a successful move so Candidate Adoption and Lightweight Fork require a fresh preview.

Route move changes the Gallery line structure, so any stored preview signatures (Candidate Adoption, Lightweight Fork, and other signature-guarded operations) become stale and must require a fresh preview before apply.

## 8. Route Remove / Restore

Route remove is approved for Pro v1.

Removal semantics:

- sets the existing `deleted` flag on the separator and all member lines;
- Workbench lines in the block are deleted as part of the same Route block;
- Candidates and Gallery Variants remain attached to their (deleted) lines;
- no physical image deletion;
- no Candidate file deletion;
- no new Route Trash schema or container;
- reuses the existing Trash / undo mechanisms.

Because flag-based deletion preserves list positions, restore is structurally simple. But Route-level remove requires Route-level restore, and a bare `deleted` boolean is not enough to make that restore correct after save and reload: if a member line was already individually deleted before the Route remove, flipping every flag back would silently resurrect it, and nothing in per-line state records which lines belonged to the same remove operation.

Decided persistence design: each Route remove writes a **Route removal record** into the existing `project_metadata` dict (an existing Project field, so this adds no project schema field). The record contains:

- a removal operation id;
- the Route handle (separator line id);
- the affected line ids (separator + member lines + Workbench lines);
- the pre-remove deleted mask (which of those lines were already deleted before this operation);
- a removed-at timestamp.

Restore semantics built on that record:

- a removed Route block is restorable atomically: separator + member lines + Workbench lines together;
- Route-level restore un-deletes only the lines that were active before the remove, according to the pre-remove deleted mask; lines that were already individually deleted before the Route remove stay deleted and are not silently resurrected;
- restoring only the separator, or only some member lines, must not produce a broken half-Route;
- Route-level restore works after save and reload, because the removal record persists in `project_metadata`;
- individual line restore remains allowed on lines belonging to a removed Route: it un-deletes that line only and leaves the removal record in place; a later Route-level restore skips lines that are already active and applies the mask to the rest;
- after a successful Route-level restore, the removal record is consumed in place (`status: "consumed"` and `restored_at` are recorded) rather than removed, so the operation history and unknown record fields remain intact;
- no dedicated Route Trash container is introduced; instead, the existing Trash view gains a minimal Route-level Restore action or Route grouping for deleted separator blocks, driven by the removal records.

Remove preview shows, with a confirmation checkbox:

- target line count;
- Candidate count;
- Gallery Variant count;
- Workbench count;
- separator label.

A typed confirmation phrase is intentionally not required, because Route remove:

- performs no physical deletion;
- is undoable;
- is restorable.

Required safety and verification points for the implementation:

- a deleted separator does not appear in Route selectors;
- a deleted Route is not a Generation target;
- a deleted Route is not an Export target;
- a deleted Route is not a Module Swap target;
- a deleted Route is not a Candidate Adoption target;
- a deleted Route is not a Fork target;
- Route-level restore reproduces the original order and membership;
- Route-level restore respects the pre-remove deleted mask: a line individually deleted before the Route remove stays deleted after Route restore;
- a line individually restored after a Route remove stays active after a later Route-level restore;
- Route removal records in `project_metadata` survive save and reload, and are consumed by a successful Route-level restore;
- stored preview signatures become stale after Route remove/restore.

Implementation checkpoint:

- `remove_route_block(...)` sets the existing `deleted` flag on the separator and every structural member in the resolved block, including Workbench and already-deleted members.
- The operation appends a record under `project_metadata["route_removals"]` with the Route handle, affected line ids, the pre-remove deleted mask, changed-to-deleted ids, and timestamps. The project schema and PromptLine schema remain unchanged.
- Trash shows an atomic Route-level restore action. Restore clears `deleted` only for lines that were active before the removal; a line that was individually restored while in Trash is left active, and a line that was already deleted before removal remains deleted.
- A successful Route restore consumes its active removal record in place (`status: "consumed"`); malformed removal metadata is diagnosed without being overwritten, and unknown project metadata remains intact through save/load. No source, Candidate, Gallery Variant, or project asset file is deleted, moved, or copied.
- Duplicate removal ids and multiple active removal records for one Route handle are treated as ambiguous metadata: they are diagnosed, excluded from the normal Route Trash restore list, and rejected by restore lookup without rewriting the records.

## 9. Duplicate Route as Baseline

Duplicate Route as Baseline is implemented for Pro v1.

Role: a lightweight in-project Route duplication used as the starting point for variations of an existing Route — a different character, location, outfit, body type, breast-size variation, expression set, or other Route variation — while keeping the original Route untouched.

Boundary against Lightweight Fork:

- **Duplicate Route as Baseline**: same project, one Route, the starting point for variation production;
- **Lightweight Fork**: separate project, materializes a completed final sequence.

Both share the same non-destructive materialization semantics; the duplicate is conceptually an in-project, single-Route application of the fork line shape.

Duplication behavior:

- inserts a new contiguous Route block immediately after the source block;
- gives the new separator a user-confirmed label (the UI defaults to `<source label> Baseline`) and preserves its color;
- keeps each line's current positive prompt;
- keeps each line's negative prompt;
- fresh separator id;
- fresh PromptLine ids;
- includes the separator, normal members, Workbench members, and members that were already deleted;
- preserves each member's structural `deleted` state;
- uses the resolved main image as the baseline, resolved through `selected_candidate_path -> generated_image_path -> image_path`;
- reuses the resolved path as the new line's `image_path`, even when the file is currently missing;
- when `selected_candidate_path` is active, rebuilds `source_generation_info` from the matching Candidate record so the adopted image keeps its Candidate prompt, negative prompt, settings, and metadata provenance;
- when that Candidate record is missing, keeps a minimal `derived_candidate` snapshot with the adopted path and current prompt/negative fallback and reports a diagnostic;
- clears `selected_candidate_path`;
- clears `generated_image_path`;
- clears `generated_candidates`;
- clears `gallery_variants`;
- duplicates Workbench lines and remaps `workbench_source_line_id` to the new line id;
- clears Workbench candidate, variant, selection, and experimental preview/apply state while preserving its prompt, note, and title;
- does not carry Candidate Trash state;
- clears candidate-derived or experimental generation state while preserving generic generation metadata;
- preserves existing lineage/metadata and adds duplicate provenance through `duplicated_from` and `lineage_info`;
- does not modify the source Route;
- does not modify source images;
- leaves `project_metadata["route_removals"]` and removal history untouched, and rejects an active source Route removal.

No image, Candidate, Gallery Variant, or project asset files are copied, moved, renamed, deleted, or recompressed. The operation is an in-project structural baseline, so there is no destination folder or overwrite path to validate.

## 10. Duplicate Route Provenance

Provenance must not contradict the zero-schema-change policy, and it must reuse fields that already exist on PromptLine: `duplicated_from` and `lineage_info` are both existing PromptLine fields.

Assignment:

- each duplicated normal line sets the existing `duplicated_from` field to its source line id;
- the duplicated separator sets the existing `duplicated_from` field to the source separator id;
- the existing `lineage_info` dict preserves semantic lineage and receives an additive operation-level provenance event.

Example `lineage_info` semantics (illustrative, not final):

- `operation: duplicate_route_as_baseline`
- `source_route_handle`
- `new_route_handle`
- `source_line_id`
- `duplicated_at`

No new PromptLine field is added; `duplicated_from` and `lineage_info` already exist in the schema.

Rules:

- do not mechanically rewrite unknown ids inside arbitrary metadata;
- transient candidate lineage and experimental state are cleared, while existing semantic lineage and generic metadata are preserved;
- provenance is additive metadata, never a data path that operations depend on.

## 11. Selected Routes Foundation

The Selected Routes foundation is implemented as a session-only selection of existing active separator handles. It does not add a Route object, a per-line `route_id`, a Project field, or `project_metadata` persistence. The project `prompt_lines` order remains the source of truth.

The pure resolver normalizes selected handles into Project order and exposes structural summaries for each selected Route: block and active line counts, normal main-line count, Workbench count, deleted-member count, Candidate count, Gallery Variant count, and Route labels. It excludes missing, deleted, non-separator, malformed, and ambiguous duplicate separator ids, with diagnostics for rejected input. Select All, Clear, Invert, and per-Route toggle operations are duplicate-free and do not mutate their input lists.

Gallery exposes the session-only foundation above the Route cards with a summary, Select All/Clear/Invert controls, and a separator-keyed checkbox for each selectable Route. The existing single-Route selectors remain independent. Selection is sanitized after graph changes: Move preserves selected handles and reorders them by physical Project order; Remove excludes the removed handle; Restore and Duplicate do not auto-select a Route; and pagination and collapse state remain independent.

This slice is connected to Final Images Export, Lightweight Fork, Route-scope Batch Candidate Adoption, Gallery Generation, Module Swap, Attribute Group Swap, and Batch Promote Variants as its first multi-Route consumers. All seven use the selected handles as a logical session source, normalize them in physical Project order, exclude non-selected Routes, and require a fresh preview before mutation, file output, or generation submission. Export records selected Route handles, labels, counts, and summaries in its manifest. Lightweight Fork preserves selected Route boundaries while materializing the same resolved final-image order into a new project, clears Candidate/Variant state in the fork copy, and leaves the source project and source assets unchanged. Candidate Adoption reuses the existing latest/first Candidate and latest Gallery Variant semantics, previews prompt/generation drift without changing prompt text, and applies the complete selected-Route image/provenance plan atomically so failure leaves the current Project unchanged. Gallery Generation reuses the existing workflow, ComfyUI submission, output naming, and Candidate registration semantics. Its generated images remain Candidates: main image references, editable prompts, `source_generation_info`, and `lineage_info` are unchanged. Generation previews and submit preflight resolve Route/Line order physically and route completed outputs back by stable Line id. Module Swap reuses the existing Module matching, marker replacement, Prompt parsing, and graph rebuild semantics. Attribute Group Swap reuses the existing full/partial matching, shared-token replacement, Prompt parsing, and graph rebuild semantics, and permits Selected Routes apply only when source and replacement Groups have the same normalized Attribute Slot. Both Prompt-changing consumers preview positive Prompt diffs, the current unchanged negative Prompt, and image / Prompt Drift risk, revalidate current Route/Line/Prompt/image/library state immediately before apply, and commit one atomic undo unit. Batch Promote Variants selects the latest/first appended Variant for each eligible Line, supports Current Route, one Selected Route, Selected Routes, Selected Lines, and All Gallery Lines, and revalidates Route/Line/Variant/file state before atomically adding fresh normal Gallery Lines. Its `end` placement inserts at the active Gallery tail before deleted lines; `after_parent` inserts immediately after each parent Line. It creates no separator, does not consume or mutate source Variants, and does not alter source Lines, Candidates, image references, or files. Main images, Candidates, Gallery Variants, `source_generation_info`, and `lineage_info` remain unchanged on source Lines. Attribute Group negative metadata remains preview-only. The existing single Route scopes remain independent. Selected Routes is not connected to Candidate Prompt Adoption, Route Candidate Review, or Route remove. Shared scope migration and the remaining Multi-Route operation support remain future v1.1 work.

**Append Selected Routes to Existing Fork** reuses the same session handles after initial Fork creation. It appends only source Route handles not already recorded in the same-source Fork manifest, preserves every existing Fork Route and edit, and materializes fresh-id Route blocks at the physical tail through a fresh preview and atomic filesystem transaction. It does not turn Routes into schema objects or connect Selected Routes to a cross-project merge operation.

The shared scope model for v1.1 is:

```text
scope:
  all_lines | selected_lines | current_route | selected_routes
selected_routes: list of separator line ids
```

The existing single `selected_route` scope remains an independent compatibility path; `selected_routes` reads the Gallery-wide session selection instead of replacing that selector.

Design distinction to keep:

- **scope**: resolves the operation's target line set;
- **Route handle operation**: structural operations (Route move / remove / duplicate) that take separator ids directly and are not line-set scopes.

The implemented Selected Routes consumers cover Final Images Export, Lightweight Fork, preview-first atomic Route-scope Batch Candidate Adoption, preview-first Candidate generation, preview-first atomic Module Swap, preview-first atomic Attribute Group Swap, and preview-first atomic Batch Promote Variants. Broader shared scope migration and other Multi-Route operation connections remain v1.1 work.

## 12. Route Candidate Review / Route Take (Not In Pro v1)

Not implemented in Pro v1.

The v1.1 reduced candidate is: add "per-line selected Candidate" as a Batch Candidate Adoption source, with a review surface where each line can be set to Main / Candidate / Variant / Skip. The adoption design already reserves the per-line selected candidate source.

The full Route Take concept — choosing a per-line image sequence and sending it to the current Route, materializing it as a new Route, or sending it to a Lightweight Fork — is a new pipeline concept and belongs to Desktop / Pro v2.

The term "Route Take" is not formally reserved at this time. If the v1.1 reduced version ships, it should be named around Route Candidate Review, and the send-target concept should be re-derived from the existing adoption / new-Route / fork operations rather than introduced as a new noun first.

## 13. Implementation Sequence

```text
0. docs PR: route-operations.md + global-route-template.md (this design)
1. RouteBlock resolver + unit tests
2. Route separator quick actions (dispatch into existing panels)
3. Route move up/down (implemented)
4. Route remove + atomic Route restore (implemented)
5. Duplicate Route as Baseline (implemented)
6. Selected Routes foundation (implemented; session-only, no schema change)
7. Selected Routes -> Final Images Export (implemented; preview-first, no schema change)
8. Selected Routes -> Lightweight Fork (implemented; preview-first, no schema change)
9. Selected Routes -> Route-scope Batch Candidate Adoption (implemented; preview-first atomic apply, no schema change)
10. Selected Routes -> Gallery Generation (implemented; preview-first Candidate generation, no schema change)
11. Selected Routes -> Module Swap (implemented; preview-first atomic Prompt apply, no schema change)
12. Selected Routes -> Attribute Group Swap (implemented; slot-compatible preview-first atomic Prompt apply, no schema change)
13. Selected Routes -> Batch Promote Variants (implemented; preview-first atomic normal-Line addition, no schema change)
14. Global Route Template v1 (may slip to early v1.1 depending on RC status)
15. v1.1: remaining Selected Routes operation connections (with existing operations migrating to the shared resolver)
16. v1.1: per-line Candidate source / Route Candidate Review reduced version / slot binding for templates
17. Desktop: full Route Take pipeline / Project Object Model / ISDL integration
```

The first implementation PR should be: RouteBlock resolver (core helper plus tests) together with the separator card Route Actions expander and the four shortcuts dispatching into existing panels. This pairs the new resolver with its first consumer and delivers the highest-friction fix (Route operation entry distance) with near-zero apply-path risk. RouteBlock resolution is shared structural behavior, so the resolver and the structural operations (move / remove / duplicate) are Full Template work; pure dispatch UI on top of an existing panel is Mini Template work when shipped separately.

The implementation keeps the structural design above while leaving only the deferred scopes for later slices.

## 14. Safety Invariants

- The source project is never destroyed or silently rewritten by Route operations.
- Source images are never modified, moved, or deleted.
- Candidate images are never modified, moved, or deleted.
- Route remove performs no physical deletion of any file.
- Route-level restore never resurrects lines that were individually deleted before the Route remove; the pre-remove deleted mask in the `project_metadata` removal record is authoritative.
- Duplicate Route as Baseline reuses existing image paths and creates no asset destination.
- Route shortcuts never duplicate apply engines; they dispatch into existing preview/apply workflows.
- Preview-first operations reuse their existing previews, signatures, warnings, and confirmation controls unchanged.
- Stored preview signatures become stale after any Route structure change (move, remove, restore, duplicate).
- Workbench lines are never separated from their source lines by Route operations.
- Route operations do not change the project schema.
