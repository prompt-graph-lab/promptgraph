# Pixiv Publish Skill: Primitive and Workflow Plan

Status: direction-setting roadmap only. This document describes a future
agent-assisted workflow; it does not claim that the workflow or its missing
operations are implemented, and it does not make a release or product-tier
commitment. Each implementation slice must still fit PromptGraph's current
product boundaries and operation owners.

The practical target is to give a local agent such as the user's multimodal
Qwen 3.8 Flash Next a safe way to coordinate a character/Scene recast and
prepare a Pixiv publication set through PromptGraph-owned operations. The agent
should be able to inspect the active Project and images through bounded
interfaces, propose choices, and request the next operation without editing
Project files or exploring arbitrary filesystem paths.

## Target workflow

The user's working flow is:

```text
source Project / Scene
  -> preview and import reusable Scene structure into a target Project
  -> replace source-character Module references with the target character
  -> regenerate the target Scene
  -> compare prompts and images with the source Scene
  -> review and adopt useful Candidates
  -> choose an appealing, SFW cover source
  -> preview and create a separate crop-derived title image
  -> select and order the publication images within 200 MB
  -> preview and export the final set
```

The 200 MB package ceiling reflects the user's stated Pixiv publishing
constraint, not an arbitrary performance target. The cover is part of that
package budget. PromptGraph should account for the actual bytes in the planned
export; the implementation must define the precise byte conversion that
matches the user's upload limit rather than relying on rounded display sizes.

This is a target workflow, not current MCP capability. The desired result is
that a Skill coordinates these steps while PromptGraph remains the owner of
the Projects, domain operations, image handling, review plans, freshness
checks, and persistence.

## Current baseline and terminology

The current logical MCP surface contains:

- `promptgraph_capabilities`
- `promptgraph_project_summary`
- `promptgraph_list_scenes`
- `promptgraph_list_illustrations`
- `promptgraph_search_illustrations`
- `promptgraph_get_illustration`
- `promptgraph_list_candidates`
- `promptgraph_get_candidate`
- `promptgraph_preview_generation`
- `promptgraph_preview_batch_replace`
- `promptgraph_preview_scene_module_swap`
- `promptgraph_request_scene_module_swap_review`

The [Candidate metadata contract](agent-candidate-metadata-observation.md)
adds persistent-record observation without paths, image bytes, generation or
adoption authority. Session-only Candidate records are excluded.

The [Generation Preview-first contract](agent-generation-preview.md) adds
offline preflight for one explicit Scene with the host-configured shared
workflow. It submits no job and creates no human-review custody; Generation
review requests and UI remain a later slice.

This is useful for read-only Project, Scene, Illustration, Candidate, and prompt
inspection, plus reviewed Batch Replace and single-Scene Module Swap Previews.
Neither operation exposes Apply to the agent. The current MCP surface does not
provide the complete Scene recast, image audit, cover, or byte-budget export
workflow described above.

MCP dogfooding showed that prompt-match counts had been approximated with
Batch Replace Preview. The merged Illustration search tool gives that read-only
task a dedicated operation; the remaining gap is the larger recast and
publication workflow, not another reason to use a mutation Preview as search.

PromptGraph already has separate application/domain owners for operations such
as Module Swap, Gallery generation, Candidate review/adoption, and Final Images
Export. The agent can now inspect a bounded single-Scene Module Swap Preview
through the existing core planner and safe Agent Facade projection. It still
cannot Apply the swap; human approval, Project publication, Undo/history, and
save remain host-owned. The explicit review request, session custody, complete
Agent Review surface, and human **Approve and Apply** action are implemented
in PR-A/B/C. PR-D adds focused integration coverage, including the official
stdio launcher and real Windows Named Pipes through full-app review and
autosave; it does not implement later Pixiv workflow steps. Other operations
are not agent-callable merely because
they have application/domain owners; future agent-facing access should reuse
those owners and preserve their existing Preview, review, and persistence
behavior.

Several existing PromptGraph terms have specific meanings that this plan keeps:

- **Scene** is a separator-bounded group of Illustrations in a Project; it is
  not currently a first-class Project-schema object.
- **Derived Project** is the existing final-sequence materialization
  operation. It copies the reviewed resolved main-image sequence into a new
  editable Project and clears transient Candidate/Variant state. It is not a
  structure-only Scene transfer.
- **Global Scene Template** is a related user-level reusable asset design. Its
  note describes image-less Scene structure materialized with fresh IDs, but
  marks that feature as design-only. A reusable template and a direct
  Project-A-to-Project-B Scene import solve related but different workflows.
- **Candidate adoption** chooses a generated or alternate image for a main
  Illustration image reference. It is separate from prompt adoption.

The user may describe the recast step as “forking a Scene”. In PromptGraph
documentation, call the desired cross-Project operation **Scene transfer** or
**Scene import** so it is not confused with the implemented Derived Project /
Lightweight Fork behavior. Internal names such as `route_*` remain compatibility
details; user-facing concepts continue to say Scene.

## Ownership boundary

PromptGraph domain primitives should own deterministic behavior and its safety
contracts, including:

- active Scene and Illustration observation;
- preview-first Scene transfer/import and image-less materialization;
- Module replacement and generation operations;
- Candidate and selected-image observation, review, and adoption;
- prompt/structure comparison and freshness validation;
- bounded image observation for multimodal review;
- crop preview and creation of a separate derived cover asset;
- truthful byte accounting, budget plans, ordering, and final export; and
- persistence, source-file preservation, and stale-plan handling.

An MCP adapter should expose only supported PromptGraph operations and preserve
their JSON, Preview, and approval contracts. It should not become the owner of
Scene, Project, image, or export semantics.

The Pixiv Skill should own workflow policy and judgment: which source Scene to
use, which target Module to select, what anomalies to inspect, which Candidates
look promising, which image is a suitable SFW cover, what crop to propose, how
to balance coverage and redundancy within the budget, when to ask the user,
and which PromptGraph primitive to call next. It should not implement domain
mutations through shell commands or ad-hoc Project-file edits.

The model may recommend and sequence operations. Mutations and exports should
remain explicit PromptGraph operations with Preview, review, freshness, and
host approval where warranted. An uncertain visual or semantic judgment should
be shown to the user rather than presented as objective truth. This roadmap
does not loosen the current MCP Apply restriction.

## Scene portability direction

The target recast starts from reusable Scene structure, not the source Scene's
finished images or generation history. A future transfer should consider
carrying:

- ordered active Illustration structure;
- authored positive and negative prompts;
- the Scene label and color where appropriate; and
- prompt-side Module references or other portable prompt structure.

It should not assume that the target needs source image paths, generated or
selected images, Candidates, Gallery Variants, Workbench content, Trash or
deleted records, source-specific generation history, or source IDs. Fresh
target identities are the preferred direction. Preview must make unresolved
target Module references visible rather than silently materializing dangling
references.

Scene import should eventually be a general Project-A-to-Project-B operation,
not a special “return to parent” action. Useful directions include child to
parent, child to sibling, parent to child, and transfer between unrelated but
compatible Projects. Source and target Projects should remain independently
owned; a transfer should not imply ongoing synchronization.

Global Scene Template remains related but distinct: it is a reusable
user-level asset, while Scene import transfers structure between active
Projects. A first template or transfer version may be image-less and use fresh
identities, but this plan does not settle slot/binding rules or prescribe a new
Project schema. Before implementation, decide how source-to-target
Illustration correspondence can support later comparison when target IDs are
fresh, without treating source IDs as target identity. The repository-backed
[Scene Portability Foundation Audit](scene-portability-foundation.md) records
the owner comparison, persistence-compatible correspondence, and current
implementation boundaries. Human Project-to-Project image-less Scene Import
is implemented through Gallery Operations, from Preview and explicit
confirmation through in-memory Apply and host publication. Agent-facing Scene
Import remains unimplemented; this does not change the existing MCP mutation
restriction.

## Prompt and visual audit

The recast should compare the imported/derived target with its source while
allowing the intended character change. Prompt and structure review should
help find accidental source-character references, missing target references,
unexpected prompt drift, malformed tags or weights, and differences that need
human review. It should report evidence and differences rather than labeling a
Project or Scene “broken” from names or counts alone.

Image review needs a bounded PromptGraph-controlled observation path for the
selected main images and, later, relevant Candidate images. This avoids making
arbitrary filesystem access the normal way for the agent to see images. The
agent may compare source and target images for possible character leakage,
obvious image defects, intended-character consistency, composition drift, and
cover-crop suitability. Those observations are proposals: subjective quality
and SFW judgments are not hard product truths, and the user remains able to
review them.

## Cover and publication budget

The user's current cover practice is to select an appealing face from the set,
use only an SFW crop, save it as a separate first/title image, and leave the
source image unchanged. A future lightweight PromptGraph cover operation should
support source selection, a crop rectangle, positioning/scale as needed, an
output size or aspect-ratio preset, a non-destructive derived asset, and Preview
before creation. The resulting cover should be placeable as the first Final
Export item. A multimodal agent may propose a source and crop; PromptGraph
should perform the deterministic image operation. This calls for a focused
cover tool, not a general-purpose image editor.

The publication plan should expose enough information for the Skill to make a
reviewable selection:

- total package bytes and per-item bytes;
- required and optional images, including cover bytes;
- likely redundant or visually similar images;
- Scene/story coverage and final order; and
- eligible Candidate substitutions where supported.

PromptGraph owns actual byte measurement and the final budget/export plan. The
Skill may suggest a quality, coverage, and redundancy tradeoff, but the plan
must show what was omitted and why. Compression or transcoding is not assumed
by this direction; any such policy needs a separate product decision and
Previewable implementation.

## Recommended phases

This is a recommended sequence, not a commitment that every item will ship.
Each phase should remain a separately reviewable slice and be re-evaluated
against current owners and product boundaries before implementation.

1. **Scene portability foundation.** Implemented. The audit and source-side
   pure projection define structure-only transfer/materialization,
   Module-reference handling, source/target mapping, and preservation
   boundaries while keeping existing final-image Derived Project semantics.
2. **Human Scene import between Projects.** Implemented through Gallery
   Operations: explicit source Project and Scene selection, Fresh Preview,
   human confirmation, stale-safe in-memory Apply, Undo/Gallery publication,
   and normal host autosave. The transfer uses fresh target identities and
   excludes source images, Candidates, Variants, Workbench, Trash, and
   generation state. Agent-facing Scene Import is not implemented.
3. **Agent access to existing operations.** Started / partially implemented:
   the agent can inspect a bounded reviewed Preview for an explicit Scene,
   source Module, and target Module through
   `promptgraph_preview_scene_module_swap` in `strict` or `loose` mode. No
   Module Swap Apply tool is exposed. An explicit review request now queues a
   freshly recomputed Preview in the originating browser session, and the
   human can review every affected Illustration, acknowledge review, and
   explicitly select **Approve and Apply**. The dedicated host lifecycle
   revalidates custody, publishes one replacement with Undo history, and
   autosaves through the existing persistence owner. PR-D characterizes this
   composed path and its failure boundaries. Continue only by reusing existing
   operation owners and preserving host-only approval and publication; do not
   duplicate domain logic in the adapter.
4. **Generation and Candidate review.** The repository-backed
   [Agent Generation and Candidate Review audit](agent-generation-candidate-audit.md)
   maps existing owners, approval boundaries, job-lifecycle gaps, and a
   metadata-only first implementation slice. Let the agent request supported
   generation work, observe job/results, and propose Candidate review or
   adoption through explicit Preview/approval boundaries.
5. **Multimodal image observation.** Provide bounded access to selected and
   Candidate images for visual inspection without exposing arbitrary Project
   filesystem access.
6. **Cover/title-image operation.** Add a focused, non-destructive crop Preview
   and derived cover asset that can be ordered first in Final Export.
7. **Pixiv size-budget planning.** Plan the complete ordered output, including
   the cover, against the user's 200 MB limit; validate the final measured
   package before export.
8. **Repository-local Pixiv Skill.** Add the workflow instructions once the
   required primitives are reliable enough that the Skill does not need to
   fill product gaps with direct file operations.

The implemented Scene portability foundation began with an audit of current
owners and keeps the existing image-carrying Derived Project operation intact.

## Future Skill set

Pixiv is the first priority and should establish where PromptGraph primitives
end and publication-specific Skill policy begins. A repository-local Skill
set may later include Pixiv, Patreon, X, or character/Scene recast workflows.
Those audiences and publication rules are not specified here; do not infer
their requirements from the Pixiv plan.

## Explicit non-goals

This document adds no Scene Import implementation, Derived Project behavior
change, MCP tool, generation or Candidate API, image transport, crop code,
export change, live Skill, Pixiv API upload/posting, Patreon/X workflow,
dependency, or new Apply authorization. Those require their own bounded
implementation decisions and validation.

## Related design notes

- [LLM Operator Facade and MCP Binding](llm-agent-facade.md) — current
  observation and Preview boundary.
- [Scene Operations Design](route-operations.md) — separator-backed Scene
  ownership and current Scene operations.
- [Derived Project / Final Sequence Materialization](lightweight-fork-final-sequence.md)
  — current image-carrying Derived Project behavior.
- [Global Scene Template Design](global-route-template.md) — related,
  image-less reusable Scene-structure design.
- [Product Boundaries](product-boundaries.md) — existing product-tier and
  future-work boundaries.
