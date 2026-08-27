# PromptGraph Domain Model Notes

Status: future-facing architecture notes. This document describes conceptual object boundaries only. It does not define a project JSON schema, migration plan, runtime behavior, or UI.

PromptGraph Pro currently stores practical prompt-editing metadata around Illustrations, Project Modules, Global Modules, Attribute Labels, Attribute Groups, Candidates, separator-bounded Scenes, Workbench cards, lineage snapshots, and export state. Those implemented structures remain the source of truth for Pro v1 behavior.

This note records the future Illustration Set Description Language / ISDL direction and the narrower Attribute State direction so later Exp / Desktop work can evolve the model without overloading existing Pro v1 storage.

## Long-Term ISDL Boundary

Illustration Set Description Language / ISDL is a long-term design idea for describing the structure, differences, state transitions, reuse knowledge, and lineage of an illustration set.

It is not the Pro v1 implementation driver. Pro v1's primary boundary remains:

```text
Pro v1 can produce useful reviewed project data for future Exp/Desktop workflows, but its primary boundary remains practical illustration-set production.
```

In Japanese terms, do not frame Pro v1 as a "teacher-data creation tool" as its main purpose. It can create useful reviewed project data as a side effect of real production, but Pro v1 should stay focused on helping users finish illustration-set work safely.

ISDL belongs to future Exp / Desktop / LineageEditor / Re-assembly / state-aware workflow planning. Pro v1 may document the vocabulary and prepare safe metadata foundations, but it should not add ISDL-specific schema, inference, or UI until those workflows have a preview-first implementation plan.

## Terminology Map

The same words can mean different things in current Pro v1 and in future ISDL design. Use this table when writing docs:

```text
Canonical concept             Current Pro v1 concept / status
Illustration                  User-facing name for internal `PromptLine`
Scene                         Separator PromptLine + positionally owned Illustrations
Graph Edit                    User-facing name for the former Overall Edit mode
Derived Project               User-facing name for internal Lightweight Fork materialization
Sequence Snapshot             User-facing name for serialized `route_snapshots`
Route                         Future multi-Scene higher-level concept; not implemented in Pro v1 runtime
Module                        Global Module / Project Module
Attribute                     Current project-level Attribute Label / Attribute Group
Lineage                       Existing lineage metadata and future lineage views
Attribute State               Future design only; not implemented in Pro v1
LineBinding                   Future design only; not implemented in Pro v1
State Timeline                Future derived view from LineBinding; not saved in Pro v1
Candidate                     Production work artifact / candidate pool, not core ISDL element
Workbench                     Scratch work area, not core ISDL element
```

Candidate and Workbench should not be described as core ISDL elements. They are production workflow containers: Candidates are per-Illustration image alternatives and adoption history, while Workbench cards are scratch spaces for generation and review. Future ISDL may reference accepted choices or provenance derived from these areas, but the working pools themselves should not become the center of the long-term language.

The aliases above are display and documentation vocabulary only. Compatibility identifiers including `PromptLine`, `prompt_lines`, `route_*`, `line_*`, `lightweight_fork`, `route_snapshots`, scope values such as `all_lines` / `selected_routes`, widget keys, manifest operations, and filenames are intentionally unchanged.

## Term Collision Notes

`Variant` is already used in Gallery workflows, including Gallery Variant, Append Variant, and Promote Variant to Route. Future Attribute Variant is a different concept: it means a prompt realization family for an AttributeSlot.

When writing future docs, avoid unqualified `Variant` if the context could be confused:

- Use **Gallery Variant** for generated or appended image alternatives tied to an Illustration (`PromptLine` internally).
- Use **Attribute Variant** only for future AttributeSlot realization families.
- Use **StateDomain** for temporal states such as `fullset`, `topless`, `bottomless`, or `naked`.

State should not be encoded into Attribute Variant names.

## Current Attribute Metadata

Current Attribute metadata is project-wide:

```text
Attribute Label
    normalized token/base-word key
    shared semantic label

Attribute Group
    group name
    normalized slot
    token/base-word keys[]
    optional negative-side metadata
```

This layer is useful for manual labeling, Module Inspector rows, Attribute Group Inspector rows, and future compatibility analysis. It is intentionally not occurrence-level line state.

## Future Attribute State Model

The future model separates identity, compatibility, realization, and temporal state:

```text
Module
    identity boundary

AttributeSlot
    compatibility boundary

AttributeVariant
    prompt realization family

StateDomain
    allowed temporal states

LineBinding
    per-line slot + attribute_variant + state assignment
```

The conceptual object shape is:

```text
StateDomain
    id
    states[]

AttributeSlot
    id
    state_domain

AttributeVariant
    slot
    realization[state]

LineBinding
    line
    slot
    attribute_variant
    state
```

This means `underwear_set` is an AttributeSlot, `black` is an Attribute Variant, and `fullset` / `topless` / `bottomless` / `naked` belong to a StateDomain. State should not be encoded into Attribute Variant names such as `underwear_set.black.fullset`.

## Storage Boundary

Future LineBinding should be Illustration-level metadata:

```text
Illustration (`PromptLine` internally)
    LineBinding[]
```

It should not be stored in the same layer as project-wide Attribute Labels because a token label is shared wherever that token appears, while state changes are occurrence-specific across a sequence.

For example, one Scene may move from `fullset` to `topless` to `naked`. That progression belongs to the Illustration sequence. It should not make the token `panties` globally mean one state everywhere in the project.

## Timeline Boundary

A future State Timeline should be derived from LineBinding data in Scene or sequence order. The timeline itself should not be persisted first. Persisting only per-Illustration state assignments keeps the source of truth small and avoids drift between a timeline view and the underlying Illustrations.

## Future Operation Boundaries

Scene Batch Candidate Adoption and Derived Project / Final Sequence Materialization may affect how Illustration-level image references and future LineBinding metadata are carried forward. They should be designed after the current terminology boundary is stable.

Scene Batch Candidate Adoption should be modeled as scoped image-reference adoption with explicit prompt-drift preview. It should not automatically rewrite prompt text, and Candidate Prompt Adoption should stay a separate explicit operation unless a later design adds an option. The detailed design is [Scene Batch Candidate Adoption Design](route-batch-candidate-adoption.md).

Derived Project should be modeled as final sequence materialization, not as deleting candidate pools from a copied Project. It resolves each Illustration's main image using the same order as Sequence Preview and Final Images Export, copies that resolved image into the new Project, and avoids stale Candidate or old-Project lineage references. The focused design note is [Derived Project / Final Sequence Materialization Design](lightweight-fork-final-sequence.md).

Scene-level structural operations stay separator-based in Pro v1: a Scene block is resolved positionally from the separator `PromptLine`, the separator line id is the internal Scene handle, and no first-class Scene or Route object enters the Project schema before the Desktop Project Object Model phase. The compatibility boundary, including the internal `RouteBlock` resolver and `Selected Scenes` display scope (`selected_routes` internally), is [Scene Operations Design](route-operations.md). Reusable Scene prompt structure is a user-level asset boundary, not a Project schema extension: see [Global Scene Template Design](global-route-template.md), which also keeps templates state-free until LineBinding exists.

## Relationship To Module Attribute Design

The detailed Module / Attribute design direction is maintained in [Module Attribute / Semantic Slot Design](module-attribute-design.md). This domain note only names the conceptual boundaries that future Exp / Desktop work may use.

Current Pro v1 should continue to use the implemented manual metadata model until state-aware behavior has a preview-first design and migration story.
