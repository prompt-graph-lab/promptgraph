# Scene Batch Candidate Adoption Design

Compatibility note: the filename, engine names, `route_*` fields, and serialized scope values such as `selected_routes` remain unchanged. The user-facing operation is **Scene Batch Candidate Adoption**; **Scene** means the current separator-bounded block, while **Route** is reserved for a future multi-Scene concept not implemented in Pro v1.

Status: Pro v1 implementation completed for the Scene Batch Candidate Adoption source/scope matrix and its unified Gallery operation-panel presentation. The Gallery UI includes dry-run preview for scoped target resolution, before/after image-reference inspection, skip reasons, counts, and the mandatory drift warning. Preview and apply support latest/first active Candidate source and latest appended Gallery Variant source across Selected Illustrations, Current Scene, Selected Scene, Selected Scenes, and All Illustrations. Selected Scenes uses the session-only Gallery selection in physical Project order and applies one atomic multi-Scene plan; All Illustrations apply is guarded by a fresh preview signature, the existing confirmation checkbox, and the exact `APPLY ALL` phrase.

This is an image-adoption operation, not prompt rewriting. It updates `selected_candidate_path` together with the adopted image's `source_generation_info` and `lineage_info`; it does not rewrite editable prompt text, overwrite `generated_image_path`, overwrite `image_path`, edit image files, or automatically run Candidate Prompt Adoption. Gallery Variant apply does not mutate `gallery_variants` and does not materialize Gallery Variant images into `generated_candidates`. Only previous-main-image retreat records may be added to `generated_candidates` when needed.

Remaining future work is explicitly separate: Candidate Prompt Adoption integration, consolidation with the existing `Batch Adopt Gallery Candidates` UI, deeper lineage rewrite / semantic prompt rewrite, save/load schema changes if ever needed, AI/VLM prompt-image consistency checks, and Attribute State / LineBinding integration.

Scene Batch Candidate Adoption is the Scene/Batch version of the existing per-Illustration Candidate card action `本編画像に設定`. It adopts Candidate or Gallery Variant images as resolved main images for a scoped set of Gallery Illustrations in one preview-first operation.

This is one unified design. Scene-level Variant Swap and Batch Candidate Adoption are not separate features: “swap this Scene's main images with their chosen Candidate/Gallery Variant images, keeping the old main images as Candidates” is the same operation as scoped batch adoption with main-image retreat. Designing them separately would create two UI paths that change the same Illustration fields with different rules.

## Relationship To Current Implemented Behavior

Pro v1 already has related implemented pieces. This design builds on them and must not silently change them:

- The per-line Candidate card action `本編画像に設定` adopts one candidate as the line's resolved main image. For image-present lines this is a reversible swap: the previous main image retreats into the candidate list. Prompt text is not rewritten.
- `Batch Adopt Gallery Candidates` exists as a Gallery operation. Its current replace mode adopts the latest or first active candidate per line. As currently implemented, it does not retreat the previous resolved main image into the candidate list, and it writes both `selected_candidate_path` and `generated_image_path`.
- `Batch Promote Variants` promotes appended Gallery Variants into normal Gallery routes. It creates new lines; it does not change existing lines' main-image references.
- Route-aware scope selection (All lines / Selected Lines / Current Route / Selected Route) is already the established targeting model for Gallery-wide generation, Batch prompt editing, Candidate Route creation, and Final Images Export.
- Main-image resolution order is `selected_candidate_path -> generated_image_path -> image_path`, shared by Gallery display, Sequence Preview, and Final Images Export.

The unified design intentionally follows the per-line `本編画像に設定` semantics, not the current batch replace behavior. The existing batch replace path skips the previous-main-image retreat; the unified engine should make retreat the default for image-present lines so batch adoption stays reversible like the single-line action. Reconciling the current `Batch Adopt Gallery Candidates` behavior with this design is an explicit implementation-phase task, not a silent side effect.

## 1. Operation Semantics

One batch adoption run does the following for each eligible target line:

- The chosen Candidate or Gallery Variant image becomes the line's resolved main image.
- If the line already had a resolved main image, that previous main image retreats into the Candidate side as a normal candidate record. It is not deleted, and it can be re-adopted later.
- Prompt text (positive and negative) is not changed automatically.
- Candidate Prompt Adoption remains a separate explicit operation. A later design may add an explicit opt-in option inside the same preview, but automatic prompt rewriting is never the default.
- No image file is deleted, moved, or overwritten. Adoption changes line-level references only.
- Adopting the image that is already the resolved main image is a no-op and is reported as skipped, so repeated runs are idempotent.

Adoption source per line is one of:

- latest active candidate (current batch default);
- first active candidate;
- the per-line selected candidate, when a line-level selection exists;
- latest appended Gallery Variant image (this is the Route-level Variant Swap case).

Gallery Variant adoption uses the variant's image as the adoption target exactly like a candidate image. It does not remove the variant record, and it does not interact with `Batch Promote Variants`, which stays a separate line-creating operation.

## 2. Scope

Scope reuses the established Route-aware targeting model, with the same wording as Gallery-wide generation and Batch prompt editing:

- All
- Selected Lines
- Current Route
- Selected Route
- Selected Routes (session-only Gallery selection, normalized into physical Project order)

Route scopes resolve route separators into the Prompt Lines belonging to those routes, then apply eligibility filtering. Scope resolution itself must not have adoption-specific rules; it should share the same resolver behavior as the other Route-aware Gallery operations so that "Current Route" always means the same line set everywhere.

## 2.1 Source / Scope Matrix

Current Pro v1 support:

| Source | Selected Lines | Current Route | Selected Route | Selected Routes | All | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| latest active Candidate | Apply supported | Apply supported | Apply supported | Apply supported | Apply supported | Marks the adopted Candidate record and may add previous-main retreat records. |
| first active Candidate | Apply supported | Apply supported | Apply supported | Apply supported | Apply supported | Marks the adopted Candidate record and may add previous-main retreat records. |
| latest appended Gallery Variant | Apply supported | Apply supported | Apply supported | Apply supported | Apply supported | Updates `selected_candidate_path` to the variant image path, does not mutate `gallery_variants`, does not materialize the variant image into `generated_candidates`, and may add previous-main retreat records. |

## 3. Excluded Targets

The following are never adoption targets. Exclusions are reported in the preview with reasons, not silently dropped:

- Route separator lines.
- Workbench lines and Workbench candidates. Workbench stays a scratch boundary; batch adoption operates on main-sequence lines only.
- Deleted lines.
- Image-less lines that have no adoption target (nothing to adopt). Image-less lines that do have an adoption target are eligible: adoption sets their first main image, with no retreat record because there is no previous main image.
- Trashed candidates. Trash state excludes a candidate from source selection entirely; "latest active candidate" never resolves to a trashed candidate.
- Candidates or Gallery Variants whose image file is missing or unresolvable. A missing file is a skip with reason, never a reference written anyway.

## 4. Preview-First Behavior

Batch adoption is preview-first and apply requires explicit confirmation, consistent with Module Swap and the other Gallery operations. The implemented flow always builds a preview model before apply, then enables apply only when the current preview signature still matches the selected source, scope, selected Route, selected lines, current Route anchor, Selected Routes structure/source state, and All-scope line set where relevant. Selected Routes apply re-resolves immediately before apply, validates Candidate file existence/stat and prompt/generation drift inputs, applies the complete plan to a clone, and commits only when every planned adoption succeeds; failures leave the original Project unchanged.

The preview must show:

- the resolved scope and the target line list (or a bounded example list plus counts for large scopes);
- per line: the current resolved main image and the adoption-target image, as thumbnails or path/metadata summaries;
- per line: whether this adoption is a first main image (image-less line) or a swap with retreat (image-present line);
- skipped lines with reasons (separator, workbench, deleted, no adoption target, trashed-only candidates, missing file, already adopted / no-op);
- total counts: targeted, adopted, first-image adoptions, swaps, skipped.

The preview must display this warning verbatim before apply:

```text
This operation changes image references in batch. Prompt text is not rewritten automatically. Review whether displayed images still match prompt meaning before applying. Run Candidate Prompt Adoption separately when needed.
```

When scope is All, the UI treats the preview as project-wide safety preparation. All apply is available for latest/first Candidate and latest appended Gallery Variant sources only when all of the following are true:

- the preview is fresh;
- the preview signature matches the current source, scope, and project-wide target line ids;
- the existing confirmation checkbox is checked;
- the exact `APPLY ALL` phrase is entered.

The All preview signature includes project-wide target line ids and count. If the target line set changes after preview, the preview becomes stale and apply must be re-previewed.

## 5. Image/Prompt Drift Policy

Pro v1's central production invariant is:

```text
Displayed image and associated prompt should not drift apart.
```

The per-line `本編画像に設定` action is protected by human attention: the user looks at one image and one prompt. Batch adoption removes that per-line attention, so a Route-scope run can produce drift across an entire Route in one click. The design treats this as the operation's primary risk:

- The drift warning above is mandatory in the preview, not optional UI text.
- The preview should make the image-reference-only nature of the operation visually explicit (image changes, prompt column unchanged).
- Prompt Adoption is intentionally not auto-executed with image adoption. Reasons:
  - Candidate generation prompt metadata may be absent, partial, or wrong; batch-applying it silently would corrupt editable prompt text at scale with no per-line review.
  - Image adoption is reference-only and reversible via retreat records. Prompt rewriting overwrites user-edited text and is only recoverable through Prompt Revert per line, so its blast radius is larger.
  - Keeping image operations and prompt operations separate is an existing Pro v1 boundary (`本編画像に設定` vs Prompt Revert / Candidate Prompt Adoption). Batch scope must not blur a boundary that the single-line UI deliberately keeps.
- A future explicit option may run Batch Candidate Prompt Adoption from the same preview, but it must be a separate opt-in with its own per-line preview of prompt changes, and it is out of scope for the first implementation.

## 6. Data Update Rules

These rules describe the implemented Candidate-source and Gallery Variant source apply paths. They stay consistent with the shared main-image resolution order `selected_candidate_path -> generated_image_path -> image_path`. All source/scope combinations use the same rules.

Per adopted line:

- Set `selected_candidate_path` to the adoption-target image path. This alone changes the resolved main image because `selected_candidate_path` has top resolution priority.
- Do not overwrite `generated_image_path`. The current legacy batch replace mode writes it, but the Route-scope apply engine intentionally differs: under the resolution order, updating `selected_candidate_path` is enough for display/export, and preserving `generated_image_path` keeps the line's generated-output record intact.
- Never modify `image_path`. It remains the imported/source image fact.
- Retreat record: when the line had a previously resolved main image and that image is not already present in the candidate list, append a candidate record for it to `generated_candidates`, marked as a retreated main image (following the record shape the existing single-line swap already produces). If it is already in the candidate list, do not duplicate it.
- Candidate records for the adopted image are not removed. A candidate that became the main image stays in the pool as adoption history, consistent with the current candidate model.
- Candidate metadata (generation prompt metadata, trash fields, timestamps) is preserved as-is. Adoption does not edit candidate metadata other than adding retreat records.
- Rebuild `source_generation_info` from the exact adopted Candidate or Gallery Variant source record, preserving its image path, generation prompt, negative prompt, settings, and raw metadata where available.
- Rebuild `lineage_info` from that same source record before changing `selected_candidate_path`, so `parent_image_path` records the previous resolved main image. Editable `current_text` and `negative_prompt` remain unchanged and may intentionally differ from the adopted image's source snapshot.
- Trash state is untouched: adoption neither trashes nor restores any candidate, and retreat records enter the pool as active (non-trashed) candidates.

Gallery Variant adoption follows the same image-reference rules with the variant image path as the target. The variant record itself is not modified, removed, marked adopted, or materialized into `generated_candidates`; only previous main-image retreat records may be added to `generated_candidates` when needed.

## 7. Consistency With Final Export And Fork

Three consumers resolve the same main-image references and must stay in agreement:

- **Final Images Export** exports the resolved main image per eligible line using the shared resolution order, and skips trashed candidates that match a resolved main-image source. After a batch adoption run, export must produce exactly the sequence the adoption preview showed as the "after" state. The implementing PRs should include tests asserting adoption-then-export parity, including trash-fallback cases.
- **Sequence Preview** uses the same resolution and exclusions; a batch adoption followed by Sequence Preview is the intended human verification step and must show the adopted images.
- **Lightweight Fork / Final Sequence Materialization** (future, design in [PromptGraph Domain Model Notes](domain-model.md) and [`docs/pro-v1.md`](../pro-v1.md)) materializes the resolved sequence into a new project. Because batch adoption typically makes `selected_candidate_path` point into the candidate pool for many lines at once, fork materialization must resolve and copy those images rather than pruning candidate pools naively. Batch adoption must not create reference states that only Gallery display can resolve: any reference it writes must resolve through the same shared order that export and fork use, so candidate paths do not become stale or dangling in downstream operations.

Batch adoption itself never deletes candidate files, so it cannot create dangling paths directly. The risk it creates is concentration: after a Route-scope run, most of a Route's main images live in `candidates/` storage. Fork and any future cleanup features must treat candidate-backed main images as first-class, which is why fork is specified as materialization rather than candidate deletion.

## 8. UI Placement

- The operation lives in Gallery operations, next to the existing `Batch Adopt Gallery Candidates` section, as its scoped evolution — not as a new parallel section. Its Phase 3 launcher opens the operation on request inside the same single-active-operation panel used by the other Route production phases; the body is not rendered while inactive and is not wrapped in a second owner expander.
- Scope, source, selected Route, and adoption-mode drafts plus fresh Previews remain in same-Project session state across close/reopen and operation switching. Temporary widget mirrors are reconstructed from those durable values after hidden-widget cleanup. Confirmation checkboxes and the exact `APPLY ALL` phrase remain one-shot and are cleared when the panel closes or another operation opens. Successful Project replacement clears drafts and Previews; failed replacement does not.
- The scope selector reuses the existing Route-aware scope UI (All / Selected Lines / Current Route / Selected Route) and adds the session-only Selected Routes set without a second selector. The existing single `Selected Route` scope remains independent.
- The Candidate card is not duplicated. Per-candidate actions (`本編画像に設定`, `この画像のプロンプトを使う`, `削除`) stay the precise single-image path; batch adoption does not add per-candidate controls, and the Candidate card does not grow batch controls.
- `Batch Promote Variants` remains its own section. If it later gains the same Route-aware scope selector, that is a separate small change sharing the same resolver.

## 9. Implementation Completion Note

The Pro v1 source/scope matrix is completed through small, preview-first, independently reviewable steps:

- **PR-A: docs + preview model.** Implemented as documentation and a read-only preview model contract.
- **PR-B: scope resolver + dry-run preview.** Implemented as a Gallery dry-run preview using the shared Route-aware scope resolver, with mandatory drift warning.
- **PR-C: apply engine for Selected Lines / Current Route.** Implemented for latest/first active candidates. The unified adoption engine uses retreat semantics, updates `selected_candidate_path`, does not overwrite `generated_image_path`, and leaves the existing `Batch Adopt Gallery Candidates` behavior unchanged.
- **PR-D: Selected Route / All scopes + Gallery Variant source.** Selected Route apply is implemented for latest/first active candidates, Gallery Variant source is implemented for dry-run preview plus Selected Lines / Current Route / Selected Route apply, Candidate-source All apply is implemented, and Gallery Variant source All apply completes the source/scope matrix. All apply uses fresh-preview, checkbox, and `APPLY ALL` phrase guards.
- **Completion docs polish.** This note now treats the source/scope matrix as implemented Pro v1 behavior and separates the remaining future work below.

Candidate adoption behavior and anything touching line reference semantics is Full Template work under the development policy; the UI-only steps can use the Mini Template.

## 10. Future / Polish

The following remain future work or polish, separate from the completed source/scope matrix:

- Candidate Prompt Adoption integration. This would be an optional explicit second step, not automatic, and must keep image/prompt drift visible.
- Existing `Batch Adopt Gallery Candidates` consolidation. The legacy-compatible UI remains separate for now; a future pass may consolidate it into the Route-scope engine.
- Deeper lineage graph/event modeling or semantic prompt rewrite. The current operation records the adopted image's existing Candidate-derived provenance only.
- AI/VLM prompt-image consistency checks. These may help detect mismatches later, but they are not a Pro v1 requirement.
- Lightweight Fork / Final Sequence Materialization. This is the next likely work item, should use the final main-image resolution order `selected_candidate_path -> generated_image_path -> image_path`, and is tracked in [Lightweight Fork / Final Sequence Materialization Design](lightweight-fork-final-sequence.md).
- LLM/VLM candidate quality checks or automatic candidate ranking (Exp first).
- State-aware swap or any Attribute State / StateDomain-driven adoption logic.
- Attribute State / LineBinding creation, update, or migration; batch adoption neither reads nor writes any future LineBinding metadata.
- Illustration Set Re-assembly / multi-set workflows.
