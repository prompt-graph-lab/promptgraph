# Comfy Workflow and Metadata Analysis

Status: implemented conservative bridge features plus future design notes. This document describes what PromptGraph-Pro can currently inspect or export, and what remains future work.

PromptGraph-Pro is using imported image metadata and ComfyUI workflow JSON as production clues, not as a fully automatic workflow reconstruction system. The current direction is intentionally cautious: preserve source metadata, inspect it, map obvious references, export rewritten JSON for manual testing, and avoid hidden project or workflow mutation.

ComfyUI Settings is the exclusive render owner for Generation Settings Consistency, Negative Prompt Consistency, and the Comfy Workflow Inspector composite. These tools run only while that workspace is active. They inspect the authoritative Project-wide visible Illustration collection rather than the current Gallery page, Graph Edit Browser page/filter/collapse state, selected Scenes, selected Illustrations, or Candidate page. With no Project, both consistency panels show compact empty states while Workflow Inspector upload and paste remain available. Workflow Preset selection and compact effective-workflow status stay in the daily Sidebar, and Gallery / Focus Edit retain generation execution. Inspector text, prompt-injection choices, LoRA directory mapping input, and LoRA-injection choices/strengths use one session-only non-widget draft owner so Back and reopen can reconstruct cleaned Streamlit widget state. Option drafts store stable line, node, source, or LoRA-name scalars and normalize against current choices; they are never written to Project/settings/Workflow JSON, and uploaded file objects are not retained.

## Implemented Bridge Features

The current Comfy / metadata bridge includes:

- **Comfy Workflow Inspector**: read-only inspection of API-style and UI-style Comfy workflow-like JSON, including prompt, negative prompt, sampler, checkpoint, LoRA, VAE, and save-node hints.
- **Prompt Injection Export**: export-only injection of one PromptGraph line into selected existing API-style text encode fields. It can inject positive prompt text and, when selected, negative prompt text. It downloads rewritten workflow JSON instead of mutating the project or calling ComfyUI.
- **LoRA Directory Mapping**: read-only extraction of LoRA references from visible prompt lines and filename-only matching against a local LoRA directory. It scans filenames and relative path stems; it does not inspect model contents.
- **LoRA Loader Injection Export**: export-only update of one existing API-style `LoraLoader` node. It does not add new LoRA nodes, chain multiple loaders, or rewire the workflow graph.
- **Per-line negative prompt persistence**: imported metadata and explicit line edits can populate `PromptLine.negative_prompt`. The Selected Line Panel can edit the stored per-line negative prompt.
- **Negative Prompt Consistency Check**: read-only analysis across visible PromptGraph lines. It summarizes whether detected negative prompts are identical, mostly shared, or line-specific; it also surfaces common and line-specific comma-separated negative tokens.
- **Global Negative / Delta Preview**: read-only preview that suggests an all-line common negative candidate and per-line negative deltas when they can be derived from visible lines. It does not persist global or delta fields.
- **Source vs Current Prompt Diff**: read-only selected-line comparison between preserved source positive prompts and editable working prompts.
- **Source vs Current Negative Prompt Diff**: read-only selected-line comparison between preserved source negative prompts and editable working negative prompts.
- **Generation Settings Consistency Check**: read-only analysis across visible PromptGraph lines for common generation settings such as steps, sampler, schedule type, CFG scale, seed, size, model, model hash, denoising strength, clip skip, hires settings, VAE/module, and version.
- **Gallery candidate insertion context**: when a generated or manual candidate is inserted as a new prompt line, the source line remains active/expanded so multiple useful candidates from the same generation session can be inserted without navigating back.
- **Lineage v1 metadata**: imported image lines can preserve source generation info separately from editable working prompts. Generated/manual candidates inserted as new lines receive derived source-generation snapshots where available and minimal parent/candidate lineage metadata.

These features are conservative import, review, edit, and export helpers. They should not be treated as automatic generation profile management yet.

## Intended Analysis Workflow

The current intended workflow is:

1. Import images, PNG metadata, JPEG EXIF metadata, or A1111 / Forge-style parameter blocks.
2. Inspect prompts, stored per-line negative prompts, LoRA references, Comfy workflow metadata, and generation settings.
3. Check whether negative prompts are common across the set or scene-specific.
4. Check whether generation settings are stable, mostly stable, partial, varied, or missing across visible lines.
5. Map LoRA references against a local LoRA directory using filename and relative-path matching.
6. Inject selected prompt, negative prompt, or LoRA values into existing API-style ComfyUI workflow JSON fields.
7. Download the rewritten workflow JSON for manual ComfyUI testing.

The workflow is designed to keep archive analysis separate from irreversible project changes. It prepares information for future generation profile work without adding Generation Profile persistence or hidden workflow mutation.

## Current Boundaries

Current implemented behavior is deliberately limited:

- Workflow inspection is read-only.
- Prompt injection writes a downloadable JSON copy; it does not alter project JSON.
- LoRA mapping reads local filenames and paths only; it does not load or inspect LoRA weights.
- LoRA injection updates one existing `LoraLoader` node only.
- No automatic LoRA node insertion, multiple LoRA chaining, or workflow rewiring exists yet.
- Negative Prompt Consistency is read-only analysis.
- Global Negative / Delta Preview is read-only analysis.
- Source vs Current Prompt Diff is read-only analysis.
- Source vs Current Negative Prompt Diff is read-only analysis.
- Generation Settings Consistency is read-only analysis.
- Source/current diff previews use exact comma-separated token comparison only; they are duplicate-aware, preview long displays for usability, and do not provide semantic/fuzzy diffing or restore/apply controls.
- Future source restore/apply, if implemented, should be a PromptGraph working prompt edit only. It should not rewrite raw metadata, source snapshots, lineage metadata, or Comfy workflow JSON.
- There is no project-level Global Negative Prompt field yet.
- There is no persisted line-specific Negative Delta model yet.
- There is no Generation Profile persistence or export yet.
- There is no sampler, checkpoint, or generation-settings injection yet.
- Existing ComfyUI generation behavior is separate from these export-only tools.
- Candidate insertion is single-candidate and manual; candidate pools and bulk candidate add are future work.
- Full Comfy workflow/settings snapshot capture for every generated image remains future work.
- PromptGraph Lite is not changed by this Pro documentation or these Pro features.

## Metadata Analysis Status

Image metadata import currently preserves and analyzes practical generation metadata:

- PNG text metadata.
- selected JPEG EXIF fields.
- A1111 / Forge / WebUI `parameters`.
- NovelAI EXIF prompt clues.
- ComfyUI `prompt` and `workflow` metadata.
- positive prompt text and per-line `negative_prompt` text when available.
- generation parameters such as steps, sampler, CFG scale, seed, size, model, hires settings, version, and extension-specific fields.

Recent analysis features add several important cross-line checks:

- LoRA references can be collected from visible prompt lines and mapped to local filenames.
- Source vs Current positive and negative prompt diffs can compare imported or candidate-derived source snapshots against the current editable line text.
- Negative prompts can be compared across visible prompt lines to identify common templates and line-specific additions.
- Global Negative / Delta Preview can display a read-only common negative candidate and per-line delta preview without writing project fields.
- Generation Settings Consistency can compare visible-line settings and show whether each field is `constant`, `mostly constant`, `partial constant`, `partial mostly constant`, `partial`, `varied`, or `missing`.

Source/current prompt diffs are selected-line inspection helpers. They compare `source_generation_info.source_prompt` with `current_text`, and `source_generation_info.source_negative_prompt` with `negative_prompt`. Both use exact comma-separated tokens, preserve duplicate token occurrences, show added/removed tokens, and shorten long prompt/token displays so large metadata imports remain readable. They do not persist Global Negative Prompt data, line-specific Negative Delta data, or any source-to-current rewrite.

Future source restore/apply controls would copy preserved source prompt text back into editable working prompt fields only after explicit preview and confirmation. They should not alter imported raw metadata, Comfy workflow metadata, source image metadata, `source_generation_info`, or `lineage_info`.

Generation Settings Consistency currently considers common WebUI-style fields including:

- Steps.
- Sampler.
- Schedule type.
- CFG scale.
- Seed.
- Size.
- Model.
- Model hash.
- Denoising strength.
- Clip skip.
- Hires upscale.
- Hires steps.
- Hires upscaler.
- VAE / Module.
- Version.

Missing fields are part of the consistency decision. A setting that appears on only one visible line is not treated as a strict common profile candidate, even if that one detected value is unique.

Future metadata analysis candidates include:

- checkpoint/model directory mapping.
- richer workflow source comparison.
- richer workflow/settings capture for derived candidate source snapshots.
- generation profile export that combines prompt, negative prompt, LoRA, checkpoint, sampler, seed, and batch settings.

## Negative Prompt Design Insight

Negative prompts should be treated as structured production data, not only as a global quality filter.

In real illustration sets, negative prompts can represent:

- global quality or safety filters.
- creator intent about failure modes.
- scene-specific suppression.
- composition failure-mode suppression.
- suppression of attributes that a LoRA tends to reintroduce.

This matters because removing a positive token is sometimes not enough. In LoRA-heavy workflows, a character LoRA may reintroduce accessories such as a ribbon or hairclip even when the positive prompt no longer includes those tags. The prompt may need explicit negative tags to suppress that attribute in a particular scene.

## Common Negative Prompt vs Negative Delta

The consistency check points toward a future split:

- **Global Negative Prompt**: the shared negative template used across many or all lines.
- **Line-specific Negative Delta**: scene-specific suppressions or failure-mode corrections added only to some lines.

For example, an imported set may share:

```text
low quality, bad anatomy, watermark
```

while a bathroom scene adds:

```text
ribbon, hairclip
```

In that case, the common template and the scene-specific delta should eventually be represented separately. The current Global Negative / Delta Preview only analyzes and displays the pattern. It does not persist a Global Negative Prompt or line-specific Negative Delta fields.

## Module / Attribute / NegativeAttribute Implication

The module model should eventually allow stable identity modules while letting positive and negative attributes toggle per scene.

Conceptual split:

- **Module Core**: stable identity, such as character LoRA, face/body identity, key character tags, or other recognition anchors.
- **Attribute**: optional positive traits, such as accessories, outfit components, pose, expression, camera, or context tags.
- **NegativeAttribute**: tags used to suppress disabled or context-inappropriate traits.

Example:

```text
Module Core:
- character LoRA
- face identity
- body identity

Normal scene Attribute ON:
- positive: ribbon, hairclip

Bath scene Attribute OFF:
- remove positive: ribbon, hairclip
- add negative: ribbon, hairclip
```

The character Core remains stable. The accessory Attribute changes state by scene, and the NegativeAttribute may become active when the positive Attribute is disabled.

This is especially useful for prompt sets that use clean Positive / Negative separation instead of brute-force weighted positive tags. Clean separation makes the set easier to inspect, reconstruct, and migrate to stricter prompt-understanding models. Heavily weighted brute-force prompts may still work, but they are harder to migrate and may later require intent reconstruction.

The current implementation supports Attribute Group negative metadata and read-only NegativeAttribute Preview. It does not apply NegativeAttribute behavior, persist preview output, rewrite prompts, or alter Comfy workflow export.

## Future Implementation Candidates

The following are future candidates, not current behavior:

- Clarify future storage boundaries for line negative prompt source metadata where needed.
- Extend Lineage v1 beyond current source/imported snapshots, derived candidate snapshots, and minimal parent metadata. See [Image Generation Lineage Principle](architecture/image_generation_lineage.md).
- Add a project-level Global Negative Prompt.
- Add line-specific Negative Delta support.
- Add checkpoint/model directory mapping.
- Map multiple LoRA references to multiple existing `LoraLoader` nodes.
- Add integrated Generation Profile Export.
- Add sampler/checkpoint/settings injection into workflow exports.
- Add explicit, undo-safe source restore/apply controls for editable working prompts.
- Apply Module Core / Attribute / NegativeAttribute expansion after explicit preview.

These should remain preview-first and conservative. PromptGraph should not silently rewrite prompts, add hidden workflow nodes, or infer semantic intent without visible review.
