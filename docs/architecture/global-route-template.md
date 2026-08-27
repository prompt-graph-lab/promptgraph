# Global Scene Template Design

Compatibility note: this filename and proposed persistence terms retain `global-route-template` / `route_*` for backward compatibility. User-facing documentation and UI use **Global Scene Template**; Pro v1 does not implement the future multi-Scene **Route** concept.

Status: design note only. This document fixes the Pro v1 design decisions for Global Scene Template before implementation. Nothing described here is implemented yet. The file format described below is a pre-implementation draft: the concrete module snapshot fields must be aligned with the existing module schema and normalize/preservation logic during the implementation PR.

The companion structural design is [Scene Operations Design](route-operations.md).

## 1. Purpose And Concept Boundaries

A Global Scene Template is a user-level reusable asset that stores a Scene's prompt structure — not its finished images. It lets a Scene sequence built with one character be reused with another character, another location, or another outfit, by adding it to a Project as a fresh image-less Scene and then using the existing production loop:

```text
Add from Global Scene Template
-> existing Scene-scope Module Swap
-> Scene Generation
-> Candidate Adoption
```

Concept boundaries:

- **Global Module**: reusable part (character / location / outfit / etc.).
- **Global Scene Template**: an ordered set of Illustrations describing a Scene.
- **Duplicate Scene as Baseline**: in-Project, image-carrying variation starting point (see Scene Operations Design).
- **Derived Project**: materializes a completed final image sequence into a separate Project (`lightweight_fork` internally).
- **Illustration Set Re-assembly**: multi-set knowledge composition; Desktop / Pro v2.
- **Sequence Snapshot**: the existing `route_snapshots` comparison feature in the Project model. It is unrelated to Global Scene Template; do not conflate the two.

## 2. Pro v1 Minimal Scope

Global Scene Template is a conditional Pro v1 candidate:

- it comes after the Scene Operations implementation;
- it must not delay RC stabilization;
- if the schedule tightens, the implementation slips to the top of v1.1;
- the design doc and the file format are fixed during Pro v1 either way.

Pro v1 does not implement slot binding. The v1 minimal workflow is:

```text
Save Scene as Global Scene Template
-> Add from Global Scene Template
-> existing Scene-scope Module Swap
-> Scene Generation
-> Candidate Adoption
```

## 3. Save Scene as Template

Save operates on a single Scene only.

Saved:

- `template_format_version`;
- name;
- description;
- created_at;
- optional source project provenance (project name only);
- Scene label;
- Scene color;
- ordered Illustrations;
- each Illustration's positive prompt;
- each Illustration's negative prompt;
- detected Module references;
- a module snapshot for each detected Module reference (see section 5).

Not saved:

- images;
- `selected_candidate_path`;
- `generated_image_path`;
- `generated_candidates`;
- Gallery Variants;
- Workbench lines or Workbench candidates;
- Trash state;
- `source_generation_info`;
- old lineage;
- project-specific PromptLine ids;
- project-specific separator ids;
- absolute paths;
- generation history;
- Candidate file paths;
- internal Scene membership ids.

**Portable asset invariant: a template file contains no absolute paths of any kind.** This is what makes a template shareable between machines and projects, and it must be enforced by tests in the implementation PR.

Save preview shows:

- Scene label;
- Illustration count;
- positive / negative prompt preview;
- detected module references;
- module snapshot availability per reference (an unresolvable snapshot blocks Save; see section 5);
- a summary of excluded data;
- the destination file;
- name conflicts.

Same-name templates are never overwritten:

- no silent overwrite;
- no automatic suffixing;
- the user explicitly renames or cancels;
- a future explicit "replace template" operation is a separate feature, not part of v1 save.

## 4. Add from Template

Add materializes the template into the target project as:

- a fresh separator PromptLine;
- fresh PromptLine ids;
- the template's Route label / color;
- each line's positive prompt;
- each line's negative prompt;
- no `image_path`;
- no `selected_candidate_path`;
- no `generated_image_path`;
- no Candidates;
- no Gallery Variants;
- no Workbench lines;
- no Trash state.

Insertion position: at the end of the Route list, or at an explicitly chosen position defined by the implementation.

Add uses only the normal existing project schema. No new Route Template field is added to project JSON; a materialized template Route is indistinguishable in schema terms from a manually created image-less Route.

## 5. Module Identity And Snapshots

Cross-project Module identity is the most important safety problem of Global Route Template.

A `<mod:Name>` token in a prompt is a reference to a project-local Module definition. If a template stored only the token string, adding the template to a project that lacks that Module definition would create a dangling reference: module toggles, expansion, Module Swap, and export all assume references that resolve against the library. Dangling references are silent inconsistencies and must not be created.

Therefore the template embeds a module snapshot for every detected Module reference. Snapshot candidates:

- module name;
- body;
- type / category;
- `core_tokens`;
- negative metadata;
- unknown metadata fields that pass the portable snapshot policy below;
- any fields required by the existing normalize / preservation policy.

Snapshot handling must follow the Global Module Library unknown-metadata preservation policy: editing or serializing known fields must not silently drop source metadata, extension fields, or agent-added notes. Inside a template, that preservation policy is bounded by the portable snapshot policy: portability wins over verbatim preservation.

**Save blocks on unresolvable snapshots.** If a detected `<mod:...>` reference cannot be resolved to a project Module definition at save time, Template Save is blocked, not saved with a snapshot-less reference. The save preview's "module snapshot availability" is a hard requirement, not informational: a template with a missing snapshot could not honor the Add-time guarantee that every materialized reference resolves against the project library.

### Portable Snapshot Policy

Embedding module metadata verbatim would conflict with the no-absolute-paths invariant. Existing module metadata explicitly contains local filesystem paths — for example AnimaDex module metadata carries `thumbnail_path`, `image_path`, and `source_path`. A verbatim snapshot of such a module would leak machine-local absolute paths into the template.

The policy:

- the semantic Module definition (name, body, type/category, `core_tokens`, negative metadata) is saved;
- local provenance paths are not saved: fields such as `thumbnail_path`, `image_path`, and `source_path` are stripped from the snapshot;
- portable URLs such as `source_url` may be saved;
- unknown metadata fields are kept only after passing an absolute-path inspection; unknown fields carrying local paths are stripped like the known ones;
- the inspection is recursive over nested metadata structures; if an absolute path still remains anywhere in the snapshot after filtering, Template Save is blocked rather than saved with the leak;
- Module equality comparison (section 6) excludes local path / provenance metadata, so the same AnimaDex module imported from two different local directories does not produce a false same-name conflict.

## 6. Same-Name Module Conflicts

A same-name Module in the target project is not automatically assumed to be the same Module.

Example:

```text
Template snapshot:
  name: Beach
  body: beach, ocean, sand, sunset

Project Module:
  name: Beach
  body: indoor pool, hotel, tiled floor
```

Silently reusing the existing project Module here would quietly change the template's meaning.

Add-time policy:

1. No same-name Module exists: import the snapshot as a project-local Module.
2. A same-name Module exists and its normalized definition is identical: reuse the existing project Module.
3. A same-name Module exists and the definition differs: this is a conflict. The preview shows it explicitly, nothing is auto-resolved, and Add is blocked.

Future resolution options (not v1):

- use the existing project Module;
- import the snapshot under a different name;
- save the snapshot as a Global Module first, then import;
- cancel the Add.

If even a minimal conflict-resolution UI grows too large for the Pro v1 slice, the safe reduction is: block Add on any differing same-name Module conflict, let the user rename or reorganize Modules first, and never auto-overwrite or auto-substitute.

Module equality is decided on normalized definitions, reusing the existing normalize logic in the implementation PR. **Never compare by name alone.** Equality comparison excludes local path / provenance metadata (see the Portable Snapshot Policy in section 5): two imports of the same module that differ only in `thumbnail_path`, `image_path`, `source_path`, or similar local provenance are the same module, not a conflict.

## 7. Slot-Free v1

The Pro v1 template deliberately excludes:

- `slot_id`;
- required slots;
- optional slots;
- category-based binding;
- Add-time Module binding UI;
- `<slot:...>` prompt syntax;
- unresolved slot states;
- optional-slot removal;
- automatic comma cleanup;
- automatic Module selection.

In v1, template Module references materialize as fixed references exactly as saved. Character / location / outfit replacement is delegated to the existing Route-scope Module Swap after Add.

Reasons:

- an Add-time binding UI would re-implement the existing Module Swap;
- most of the feature value is already delivered by template Add plus Module Swap;
- slot identity per category is insufficient: one line can contain multiple Modules of the same category (for example two characters), so slots must bind to individual reference tokens, which needs design that should not be rushed into v1;
- required / optional semantics would need to be defined and enforced;
- v1.1 can add slots by raising the template format version without breaking v1 files.

## 8. v1.1 Slot Design Reservation

Forward-compatibility rules for the future v1.1 slot extension (recorded now, implemented later):

- a slot binds to an individual Module reference token, not to a category;
- `slot_id` is user-named per reference;
- category is display/filter metadata only;
- an unresolved required slot blocks materialization;
- unresolved slot tokens are never written into normal PromptLines;
- slot resolution operates on tokens;
- partial string replacement is forbidden;
- optional-slot removal is a token-list operation;
- no new slot syntax is added to the parser for normal project use;
- only the resolved result is materialized into PromptLines.

## 9. Token-Level Replacement

Module reference detection, comparison, and replacement operate at token level, using the existing parser and Module Swap comma-token model.

Forbidden:

- raw string replace;
- partial matching;
- any processing where `<mod:Milk>` can falsely match `<mod:Milk Tea>`.

When the same Module reference appears in multiple lines, it is treated as one semantic unit, consistent with existing Module Swap behavior: replacing it affects all occurrences.

## 10. File Format

Global Route Templates do not live in the Global Module Library's `global_modules.json`. Reasons:

- different lifecycle: modules are small, frequently-added assets; templates are larger, low-frequency assets;
- `normalize_module_library` must never touch template data;
- avoids single-file write contention;
- one file per template is easy to share manually;
- one file per template is the natural unit for a future Template Pack.

Storage:

- a user-level `route_templates` directory;
- one template = one JSON file;
- the directory path is overridable through a setting of the same rank as the Global Module Library directory setting.

Conceptual location:

```text
<user-data>/route_templates/<sanitized-template-name>.json
```

`template_format_version: 1` is required from the first release. This is a new user-level format, so versioning costs nothing now and guards every later extension (slots, state metadata).

Conceptual schema example (pre-implementation draft; the implementation PR must align module snapshot fields with the exact existing module schema field names):

```json
{
  "template_format_version": 1,
  "name": "Beach Sequence",
  "description": "...",
  "created_at": "...",
  "source_project_name": "...",
  "route_label": "Beach Sequence",
  "route_color": null,
  "lines": [
    {
      "positive": "<mod:Remilia Scarlet>, <mod:Beach>, standing, sunset",
      "negative": "..."
    }
  ],
  "module_references": [
    {
      "reference_token": "<mod:Remilia Scarlet>",
      "module_name": "Remilia Scarlet",
      "category": "Character",
      "module_snapshot": {
        "...": "normalized module definition"
      }
    }
  ]
}
```

## 11. Negative Prompt Handling

Negative prompts are saved per line, verbatim:

- no whitespace trimming;
- no automatic normalization;
- the design must not slot-ify positive prompts while ignoring negative prompts.

Pro v1 decision: the existing Module reference and Module Swap workflows are positive-prompt-centric (the v1 swaps edit positive prompt tokens only, and NegativeAttribute runtime behavior is not implemented). Therefore, in Pro v1, template negative prompts are stored and materialized verbatim and are not Module binding or Swap targets. If a future NegativeAttribute runtime changes that boundary, the template format version gates the extension.

## 12. Attribute State / LineBinding / ISDL Boundary

Global Route Template v1 is not state-aware. It does not introduce:

- AttributeSlot;
- Attribute Variant;
- StateDomain;
- LineBinding;
- State Timeline.

State progression inside a template is stored implicitly as ordinary prompt text. For example:

- Line 1 prompt contains full-outfit tokens;
- Line 2 prompt contains a topless token;
- Line 3 prompt contains a bottomless token.

In v1 this is nothing more than prompt text.

Forbidden:

- new conventions that encode state into names, such as `underwear_set.black.fullset`;
- template-specific state naming conventions;
- pseudo-LineBinding metadata;
- state-aware Swap.

When LineBinding is introduced later, the template format version is raised and per-line state/binding metadata can be added to `lines` without breaking v1 templates. That boundary must stay clean: v1 templates must not anticipate the state model with informal encodings.

## 13. Future Boundaries

Not implemented in Pro v1:

- slot binding UI;
- required / optional slots;
- automatic Module selection;
- multiple-Route templates;
- Template Pack;
- Know-how Pack;
- nested templates;
- remote sharing;
- version control;
- dependency resolver;
- image thumbnails;
- generated preview images;
- automatic generation;
- Candidate Review integration;
- Route Take integration;
- Attribute State;
- StateDomain;
- LineBinding;
- AI / VLM / Qwen inference;
- automatic abstraction;
- Illustration Set Re-assembly.

## 14. Safety Invariants

- A template file never contains absolute paths; snapshot filtering is recursive, and Save is blocked if an absolute path would remain.
- Save is blocked when any detected Module reference cannot be resolved to a snapshot.
- Saving a template never modifies the source project, its Modules, or its images.
- Same-name template files are never overwritten silently.
- Same-name but different-definition Modules are never adopted silently; conflicts block Add.
- Module equality excludes local path / provenance metadata, so local import location differences never create false conflicts.
- Add never creates dangling `<mod:...>` references: every materialized reference resolves against the project library, via reuse or snapshot import.
- Add uses only the existing project schema; no template-specific fields enter project JSON.
- No slot tokens or unresolved placeholders are ever written into normal PromptLines.
- Module snapshot serialization preserves unknown metadata fields within the bounds of the Portable Snapshot Policy: local provenance paths are stripped, portable metadata is kept.
