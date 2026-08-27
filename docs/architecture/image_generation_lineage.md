# Image Generation Lineage Principle

Status: design principle plus Lineage v1 source/candidate metadata. This document records the intended lineage model for PromptGraph-Pro image-generation workflows. It does not claim that visual lineage graphs, bulk candidate add, image-level parent ids, negative-prompt restore/adoption, or complete workflow/settings snapshots are implemented.

## Core Rule

An image must remain paired with the exact generation information that produced it.

Prompt editing should create a new working state, not erase the production facts for an existing image. If an imported or generated image was made from prompt/settings A, PromptGraph should preserve that A information even when the user edits the working prompt toward A' for a new generation attempt.

## Working Definitions

**Source / imported generation info** means the generation facts attached to an existing image when it enters the project:

- positive prompt text.
- negative prompt text.
- generation settings such as seed, model, sampler, CFG, steps, size, hires settings, VAE, and version when available.
- raw metadata such as PNG text fields, JPEG EXIF fields, A1111 / Forge parameters, NovelAI EXIF prompt clues, or ComfyUI prompt/workflow metadata.
- source image path and file metadata.

**Working / current prompt** means the editable prompt state used for the next generation attempt. This is the line text the user is actively changing.

**Derived / generated generation info** means the snapshot of the working prompt, negative prompt, settings, workflow, and related metadata at the moment a new image is generated or accepted as a new line.

**Lineage relationship info** means metadata about how a PromptLine entered the sequence. In Lineage v1 this is intentionally minimal: it records candidate insertion relationships such as parent line id and candidate image path, not a full visual graph.

## Example

```text
Image A
-> generation info A

User edits working prompt from A to A'

Generated Image B
-> generation info B, based on A' and current settings

User edits from B to C

Generated Image C
-> generation info C
```

Image A must still retain generation info A. Image B must retain generation info B even after B becomes the basis for later edits. Editing a line should not silently rewrite the historic generation facts attached to an existing image.

## Current Implemented State

PromptGraph-Pro already has several pieces of this foundation:

- image metadata import preserves practical raw metadata where currently supported.
- `PromptLine.source_generation_info` preserves an imported image metadata snapshot when PromptLines are created from image metadata.
- candidate-derived new lines also receive a `source_generation_info` snapshot with `source_kind = derived_candidate`.
- candidate-derived new lines store minimal `lineage_info` such as parent line id and candidate image path.
- selected lines can show source prompt, source negative prompt, source generation settings, source raw metadata, and source image path as read-only provenance.
- selected lines can show read-only Source vs Current diffs for both positive and negative prompts.
- per-line `negative_prompt` persistence exists and can be edited from the Selected Line Panel.
- generation settings can be analyzed read-only across visible lines.
- Comfy workflow metadata can be inspected and used by conservative generation/export helpers.
- After ComfyUI queue completion, PromptGraph polls Comfy history briefly for `SaveImage` outputs before treating a generation as missing output. If no image output is found, diagnostics include prompt id, history/output keys, SaveImage node ids, and polling attempts.
- Gallery generation creates candidates first instead of automatically replacing source images.
- image-less prompt lines can explicitly adopt one of their own candidates as the line's main Gallery image for review/export, while lines with existing source/reference/after images remain protected from candidate replacement.
- lines with an existing main image can use a reversible candidate swap: the candidate becomes the main Gallery/export image, and the previous main image is added back to the candidate list instead of moving, deleting, or overwriting source/reference files.
- Gallery display, Gallery editor, Sequence Preview, and Final Images Export resolve the current main image in the same order: `selected_candidate_path` -> `generated_image_path` -> `image_path`.
- Gallery editor prompt-safety controls can revert the editable positive prompt to the preserved source prompt, or apply a candidate generation positive prompt to the editable current prompt, without changing the selected image reference. Negative Prompt revert/adoption remains out of scope unless a later PR adds it explicitly.
- Gallery-wide generation can target all lines, the current Route, a selected Route, selected lines, or the Gallery-wide session-only Selected Routes set. Selected Routes generation resolves active normal Lines in physical Project order, uses a cheap input signature during normal UI reruns, and performs full per-Line workflow preflight only for Fresh Preview and immediately before the first ComfyUI submission. Real output files are routed back by stable source Line id and checked for existence before Candidate registration. Route separators, Workbench, deleted, non-selected, and ambiguous Lines are excluded. Generated images remain Candidates; `selected_candidate_path`, `generated_image_path`, `image_path`, editable prompts, `source_generation_info`, and `lineage_info` are not changed by generation.
- Gallery-wide generation and Route-scope Batch Candidate Adoption open explicitly inside the Route production workflow's shared single-active-operation panel. Inactive bodies do not render. Same-Project session drafts and fresh Previews survive panel close/reopen, but one-shot confirmation controls are cleared. This presentation/state-lifecycle change does not alter generation submission, Candidate registration, adoption, source-generation snapshots, lineage construction, history/save ownership, or Project storage.
- Gallery card `分岐` actions create a default Route separator immediately after the image/prompt line, and the separator card remains the place to edit route label/color. Gallery shows all routes by default, with separator collapse as the lightweight way to manage route-heavy projects. Separator lines are not generation targets.
- Gallery Workbench cards (`line_type = workbench`) can be inserted after a source line as a per-line scratch area. They keep source-line linkage, notes, and their own candidate pool, but are not main-sequence prompt lines: graph construction, PromptCloud, Module Swap, Batch Edit, Module Candidate scanning, Gallery-wide generation targeting, and Final Images Export exclude them.
- adding a generated or manual candidate as a new line can place it immediately after the source line or at the end of the current Route. Workbench candidates use their `workbench_source_line_id` parent line as the Route anchor. Inserted Workbench candidates become normal main-sequence PromptLines and should not carry workbench-only fields.
- Final Images Export writes project-local ordered copies under `exports/final`, plus an `export_manifest.json`; it can target all lines, the current Route, a selected Route, or Selected Routes, always excluding Route separators, Workbench, deleted, and image-less lines. Its read-only Preview stats each resolved source and planned output, sums source bytes per planned item (including repeated use of one source), classifies the destination, reports planned image/manifest overwrites, and queries free space once through the nearest existing destination parent. It does not recursively scan directories, hash/read image contents, decode metadata, create folders, or write files.
- Final Export keeps its internal Preview/result paths absolute for source validation, collision protection, copying, and UI reporting, but projects a separate public manifest with `manifest_version: 2` and `path_contract: portable-relative-v1`. The manifest directory is `output_dir: "."`; output files are manifest-relative, Project-local source provenance is Project-relative, external provenance is basename-only, and `source_original_filename` is filename-only. Real-path containment prevents a Project-internal symlink that resolves outside the Project from being described as Project-local. Output references survive moving the complete export directory; source provenance is descriptive and need not resolve elsewhere. Prompt and Route/Scene content remains unsanitized user-authored data.
- Final Export capacity is advisory. Source bytes can differ from final output bytes when optional PNG metadata stripping re-saves exported copies, and the estimate excludes manifest/filesystem overhead. Timestamp subfolders are recommended; the shared `exports/final` root receives a visible overwrite warning. Capacity/profile values remain Preview-only, do not disable Export, do not enter `export_manifest.json`, and volatile filesystem usage does not make a Selected Routes Preview stale.
- Optional PNG metadata stripping applies only to exported copies and does not mutate project-linked source/candidate images or lineage metadata. The size/destination profile does not alter source resolution, output naming/order, copy behavior, metadata stripping, manifest schema, Project state, Candidate/Variant state, or history.
- The read-only `本編プレビュー` / Sequence Preview uses Final Export's resolved image list so users can step through the final sequence before writing files. It excludes Route separators, Workbench cards, deleted lines, and image-less lines in the same way as Final Export.
- project-local folders keep refs, candidates, routes, exports, and workflows organized for practical review.

These are not yet a complete lineage model. Imported source snapshots, candidate-derived snapshots, and minimal parent metadata are separate from the editable working prompt and working negative prompt, but graph visualization and richer relationship tracking remain future work.

## Candidate Adoption And Swap Semantics

PromptGraph does not treat generated images as automatic replacements for a line's source/reference image. Generated images first enter a line-local candidate pool. Adoption is explicit:

- setting a candidate on an image-less line fills an empty main image slot.
- swapping a candidate on an image-present line makes the candidate the current main Gallery/export image.
- candidate insertion creates a new PromptLine from the candidate.
- variants and nearby/pinned candidates keep useful alternates available without rewriting the current line.

Candidate swap is intentionally not destructive replacement. The previous main image is added back to the line's candidate list, while the selected candidate becomes the current main image pointer used by Gallery display and Final Images Export. Source/reference image files, candidate files, imported metadata, and source/reference generation facts are not moved, deleted, or overwritten by this operation.

This preserves traces of trial, rejection, adoption, and retreat. A line can show which image is currently selected for the final sequence while still keeping the alternatives and previous main image available for review or reversal.

The main-image pointer is distinct from prompt text. `本編画像と入れ替え` changes which image is resolved as the current main image. `比較用Afterに設定` sets the comparison After image. Candidate Prompt Adoption copies candidate generation positive prompt metadata into the editable current prompt without changing the image reference. Prompt Revert copies the preserved source positive prompt back into `current_text`, also without changing the image reference.

Final export and preview share the same resolved main-image sequence. They use `selected_candidate_path` first, then `generated_image_path`, then `image_path`; exclude Route separators, Workbench cards, deleted lines, and image-less lines; and only copy resolved images into the project-local export folder.

## Lineage v1 Data

Lineage v1 uses two separate PromptLine metadata fields:

- `source_generation_info` answers: what generation information produced this image?
- `lineage_info` answers: where did this line/image come from?

`source_generation_info` is used for both imported images and candidate-derived images:

- Imported metadata lines use `source_kind = imported_image_metadata`.
- Candidate-derived lines use `source_kind = derived_candidate`.
- Imported snapshots may include source prompt, source negative prompt, parsed generation settings, raw metadata, and source image path when available.
- Candidate-derived snapshots may include the candidate prompt, candidate negative prompt, candidate settings/metadata when available, and the candidate image path. If candidate metadata is sparse, PromptGraph falls back to the source line's current working prompt and negative prompt at insertion time.

`lineage_info` is currently only minimal relationship metadata for candidate insertion. Typical fields include:

- `lineage_kind = candidate_insert`.
- `parent_line_id`.
- `parent_line_index`.
- `parent_line_label`.
- `parent_image_path`.
- `candidate_image_path`.
- `candidate_origin_line_id`.
- `candidate_origin_line_index`.
- `created_from`.
- `candidate_created_at`.

`lineage_info.candidate_image_path` follows project-local candidate copying and save-time path relativization. `lineage_info.parent_image_path` is relativized when it already points inside the project folder. PromptGraph does not copy external parent/import images into lineage metadata.

## Read-Only UI

The Selected Line Panel can show:

- **Source vs Current Prompt Diff**: read-only comparison between preserved `source_generation_info.source_prompt` and editable `current_text`.
- **Source vs Current Negative Prompt Diff**: read-only comparison between preserved `source_generation_info.source_negative_prompt` and editable `negative_prompt`.
- **Source Generation Info**: source prompt, source negative prompt, generation settings, source image path, and raw metadata preview when present.
- **Lineage Info**: parent/candidate relationship metadata when present.

The two diff previews use exact comma-separated token comparison. They preserve duplicate token occurrences, show added and removed tokens, and shorten long prompt/token displays so the Selected Line Panel remains usable with large prompts. They do not perform semantic matching, fuzzy matching, normalization beyond comma splitting and trimming, or automatic prompt repair.

These panels are read-only. Editing the working prompt or per-line negative prompt does not overwrite imported source provenance, derived candidate snapshots, or lineage relationship metadata. Rendering the diff previews does not mutate `source_generation_info`, `lineage_info`, `current_text`, or `negative_prompt`.

## Module Swap And Route Scope

Module Swap remains a prompt/module text operation. It can target All prompt lines, a Line Group, the existing Route scope, or the Gallery-wide session-only Selected Routes set. Selected Routes resolves active normal Lines in physical Project order and reuses the existing Module matching, marker replacement, Prompt parsing, and graph rebuild semantics. It does not directly edit Gallery images, generated candidates, appended variants, route metadata, `source_generation_info`, or `lineage_info`.

Attribute Group Swap has the same image/provenance boundary. Its Selected Routes scope resolves active normal Lines in physical Project order, requires source and replacement Groups to share a normalized Attribute Slot, and reuses the existing full/partial match, shared-token replacement, Prompt parsing, and graph rebuild behavior. The current implementation changes positive Prompt text only: per-line negative Prompt stays unchanged and Attribute Group negative metadata remains preview-only. Main image references, Candidates, Gallery Variants, `source_generation_info`, and `lineage_info` are preserved even when the preview reports image / Prompt Drift.

Gallery-wide generation follows the same route-separator boundary for `Current Route`: a route starts at its separator and ends before the next separator, while the separator line itself is not generated. The generation result remains candidate-first and does not directly mutate Route or Lineage metadata.

The workflow stays preview-first. Selected Routes preview shows per-Route and per-Line positive Prompt changes, the current unchanged negative Prompt, no-op Lines, and image / Prompt Drift risk. Immediately before apply, PromptGraph re-resolves physical Route order and revalidates full Prompt/token state, Module Library state, selected Modules, options, disabled Modules, and Project identity. The complete change is applied to a clone and committed as one undo unit only after all Prompt, token, and non-Prompt invariants pass. If validation or apply fails, the source Project remains unchanged; no-op-only plans do not rebuild, autosave, or add history.

## Prompt Revert And Candidate Prompt Adoption

Prompt Revert and Candidate Prompt Adoption are Gallery safety controls for positive prompts. They mutate only editable working prompt text:

- Prompt Revert copies `line.original_text` into `line.current_text` when a preserved original/source prompt is available.
- Candidate Prompt Adoption copies candidate generation positive prompt metadata into `current_text` when candidate prompt metadata is available.

These controls must never modify the preserved source snapshot. They must not mutate `source_generation_info`, `lineage_info`, source image metadata, raw metadata, parent/child lineage metadata, candidate relationship metadata, source/reference image paths, candidate image paths, or the resolved main image pointer. They must not silently overwrite working prompts just because a line is selected, imported, loaded, or rendered.

Negative Prompt revert/adoption is not part of the current v1 implementation. If it is added later, it should be explicit and separately controlled rather than bundled into image adoption or positive prompt adoption.

## Example Flow

```text
Image A imported
  source_generation_info.source_kind = imported_image_metadata
  source_generation_info.source_prompt = prompt that produced A, when detected
  source_generation_info.source_negative_prompt = negative prompt that produced A, when detected
  current_text = editable working prompt
  negative_prompt = editable working negative prompt

User edits A current_text / negative_prompt

Selected Line Panel
  Source vs Current Prompt Diff shows added/removed positive tokens
  Source vs Current Negative Prompt Diff shows added/removed negative tokens

Candidate B generated or manually registered from the edited working state

Line B inserted from Candidate B
  source_generation_info.source_kind = derived_candidate
  source_generation_info.source_prompt = prompt used for B, when available
  source_generation_info.source_image_path = B image path
  lineage_info.lineage_kind = candidate_insert
  lineage_info.parent_line_id = A.id
  lineage_info.candidate_image_path = B image path
```

Image A keeps its imported source snapshot. Line B gets its own derived source snapshot and immediate parent/candidate metadata. PromptGraph does not infer a full graph from this metadata yet.

## Future Implementation Candidates

Future work should separate source facts, working edits, and derived generation snapshots more completely. Possible fields or equivalent structured records include:

- `source_workflow_metadata`.
- `derived_generation_settings`.
- `parent_image_id` or equivalent image-level derivation references.

Useful future behavior:

- preserve candidate-to-source and derived image relationships.
- enrich derived candidate snapshots with fuller workflow/settings context where available.
- visualize lineage relationships from the existing metadata.
- add image-level parent identifiers or image identity records.
- add source restore/apply controls after explicit preview.
- add rollback previews after explicit review.
- add richer lineage-aware comparisons and semantic/fuzzy diffs if they become necessary.
- eventually support candidate pools and bulk candidate add without breaking image-to-generation-info pairing.
- add project-level Global Negative Prompt and line-specific Negative Delta persistence when the data model is ready.

## Boundaries

Current PromptGraph-Pro does not yet implement:

- full workflow/settings snapshots for every newly generated image.
- visual parent-child lineage graph tracking.
- image-level parent ids.
- source restore/apply controls.
- rollback controls.
- semantic or fuzzy diffing.
- project-level Global Negative Prompt persistence.
- line-specific Negative Delta persistence.
- candidate pool.
- bulk candidate add.
- hidden lineage inference.

Lineage work should remain explicit and reviewable. PromptGraph should not infer or overwrite generation facts invisibly just because a prompt line is edited.
