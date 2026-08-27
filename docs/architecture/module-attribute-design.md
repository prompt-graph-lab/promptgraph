# Module Attribute / Semantic Slot Design

Status: current manual metadata model plus future design direction. This document describes the implemented Attribute / Group / Core Module workflow and the future direction for module evolution. It does not claim that attribute-based swap, automatic labeling, or prompt rewriting already exists.

PromptGraph modules currently work as reusable prompt assets with project-local storage, optional global-library copying, Core Tokens, Minimum Match Thresholds, candidate discovery, preview, and preview-first apply. The next conceptual step is to let modules describe meaning more explicitly: not only "these tokens belong together", but "these tokens represent named attributes that can be recognized, disabled, replaced, or swapped safely."

The key principle:

```text
Module boundaries are less important than meaning-preserving swap conditions.
```

A module can contain swappable attribute groups. A swappable group can also exist outside the module or across modules. Swapping should be allowed when the semantic slot matches and the parent module's intended identity is preserved. Physical nesting should not be the deciding factor.

Production use has added a second practical rule:

```text
Module should generally be cut broadly.
Internal differences should be handled through Attributes where possible.
```

In Japanese terms: Moduleはなるべく大きく切る。細部の差分はAttributeで扱う。

This means a Module should be treated as a prompt-level unit that carries character, outfit, state, and local context together where they are needed for a clean swap. It should not be reduced to a small word replacement set too early. If a character module is cut too narrowly, old-character residue such as clothing, accessories, hair ornaments, or context-specific tokens can remain outside the swapped region and survive into the new character route. Attributes are the safer place for internal differences once the broad module boundary is stable enough to preserve meaning.

## Current Implemented Model

The current workflow is manual and metadata-first:

```text
Token
-> Attribute Label
-> Attribute Group / Slot
-> Core / Optional role
-> Module
-> Module Candidate Apply
-> <mod:name>
```

Attribute Labels are stored per normalized token key. The same token shares the same Attribute Label wherever it appears, including selected-token tables, Module Attribute Tables, and Attribute Group Inspector rows. They can be edited from the selected-token Attribute Label table and from the Attribute Group Inspector.

Attribute Groups are named project metadata groups. A group contains normalized token keys and a normalized slot, and it can be edited after creation. The Attribute Group Inspector can rename groups, change slots, add/remove token membership, delete groups, and edit the shared Attribute Labels shown for group rows. Attribute Groups do not own local label overrides.

Attribute Groups can also store metadata-only negative-side fields: `negative_tags`, `negative_when_disabled`, and `negative_notes`. These fields are for future NegativeAttribute / disabled-state suppression work. They do not currently rewrite positive prompts, edit per-line negative prompts, or affect Comfy workflow export.

The Attribute Group Inspector can preview what a disabled-state NegativeAttribute expansion would look like for the selected line. This preview shows positive removal candidates and negative prompt additions, but it does not apply or persist the preview output.

Attribute Group Swap is implemented as a preview-first positive Prompt operation. It preserves existing full/partial match and shared-token semantics, and source/replacement Groups must have the same normalized Attribute Slot for the Selected Routes scope. Selected Routes are resolved in physical Project order and applied atomically as one undo unit after a fresh preview. Per-line negative Prompt remains unchanged; `negative_tags`, `negative_when_disabled`, and `negative_notes` are displayed as metadata impact only. Main images, Candidates, Gallery Variants, and image provenance are not rewritten, so image / Prompt Drift is shown explicitly.

Core / Optional token selection is module creation metadata. Core tokens are stored in module metadata as `core_tokens`. Optional tokens remain in the module body, but are not stored as Core Tokens. The current selected-token module creation flow records this metadata without changing candidate matching behavior.

Modules still keep a prompt-token body. Creating a module does not rewrite existing prompt lines. Module Candidate Apply is required to insert `<mod:name>` references, and module toggles affect the active prompt only for lines that already contain those references.

The Global Module Library has a session-only free-text search over the Module
name, category, prompt content, existing description/notes, and existing
Attribute Group / Variant metadata. Search text is normalized with Unicode
NFKC, `casefold()`, and collapsed whitespace; every whitespace-separated term
must be present. Results keep the existing alphabetical order and combine with
the Global Module Manager category filter using AND semantics. The same result
set scopes `Global → Project` and `Manage Global Modules`, while
`Project → Global` remains Project-owned and unfiltered. AnimaDex discovery and
record search remain independent.

The query and loaded-library cache are session-only global UI state. They
survive Authoring, mode, and Project transitions, are never stored in Project
JSON, editor settings, or Global Module metadata, and reset with a new app
session. Filtering uses the already-loaded JSON data: it performs no directory
scan, JSON reload per query, persistent indexing, database access, or network
access. An explicit Global Library mutation is different: it reloads the latest
JSON, rebases only that operation, saves through the existing normalization
contract, and reloads the persisted canonical representation into the cache.
This preserves unrelated writes from other sessions and gives search,
Global → Project, and Manager the same representation they see after restart.
A failed save does not replace the existing cache. The Module and Attribute
schemas and Global Library storage format are unchanged. Folders, tags, and
custom collections remain Pro v1.1 or later directions.

The current UI groups Module / Attribute work by intent:

- **Authoring**: selected-token Attribute Labels, Attribute Groups, Attribute Group Inspector, Core / Optional selection, blank module creation, and selected-token module creation.
- **Apply**: module toggles, saved module reference insertion, Module Candidate Selection, preview apply, and confirm apply.
- **Analysis**: Module Attribute Table, Module Inspector / Edit Scope, Attribute Group metadata, and read-only NegativeAttribute Preview.

The Selected Token Attribute Table is optimized for manual labeling: the current label appears as a small hint and the New Label selector has more horizontal room. This is UI-only; it does not change how Attribute Labels are stored.

## 1. Module as Attribute Group

A module should not only be treated as a flat token set. It can be understood as a group of prompt tokens with semantic attributes.

Example character module:

```text
name: nijitsuji milk
skin_color: a dark-skinned girl
breast_size: medium breasts
hair_color: black hair
hair_color_sub: rainbow tips
hair_shape: high twintails
hair_accessory: rainbow hairband
eye_shape: jitome
```

The module body may still preserve the prompt-token order needed for generation, but the module can also carry a table-like view that explains what each token means.

Recommended first targets:

- Character modules
- Hair style modules
- Outfit modules
- Expression modules
- Camera / composition modules

Behavior and action modules are likely more complex because they interact strongly with pose, composition, and scene intent. They should be treated as a later-stage extension.

## 1.1 Practical Module Boundary Guidance

For production Module Swap, start with a broad module boundary and narrow it only after previewing real before/after lines.

Recommended direction:

- Keep character identity, signature outfit parts, character-linked accessories, hair details, and important local context inside the same Module when they usually move together.
- Use Attributes for internal differences such as outfit state, expression, pose detail, accessory on/off, damage, wetness, dirt, or scene-specific variants.
- Treat a Module as a meaningful prompt region, not a bag of isolated replacement words.
- Preview broad swaps first, then split Attributes only when the preview shows a stable repeated difference.

This guidance does not make Module Swap automatic. It is a design heuristic for the existing preview-first workflow.

## 2. Attribute Labels

Each node or token can have an Attribute Label. In the current implementation, labels are stored per normalized token key, not per occurrence and not per Attribute Group row.

Common examples:

- name
- skin_color
- body_type
- breast_size
- breast_shape
- hair_color
- hair_color_sub
- hair_shape
- hair_accessory
- eye_shape
- eye_color
- outfit
- pose
- expression
- behavior
- effect
- camera
- composition

The current implementation supports user-defined labels through project custom suggestions while also offering suggested labels. Usage counts surface frequent labels near the top of dropdowns. User-defined labels are important because prompt sets vary, but suggested labels help avoid naming drift such as `hairColor`, `hair_color`, `hair-colour`, and `main_hair_color` all meaning the same thing.

## 3. Attribute Groups / Semantic Slots

Several attributes can form a swappable group. The group can be represented as a semantic slot.

Example:

```text
Module: Milk Normal Hair Style
slot: hair_style

hair_shape: high twintails
hair_accessory: rainbow hairband
```

This can be swapped with:

```text
Module: Milk Bathroom Hair Style
slot: hair_style

hair_shape: semi-long hair
hair_accessory: nothing
```

The current implementation can create and edit metadata-only Attribute Groups. The future swap condition should be semantic slot compatibility, not physical nesting. A `hair_style` group can live inside a character module, outside it as a standalone module, or across multiple module references. The important question is whether replacing one `hair_style` group with another preserves the intended parent identity and prompt meaning.

## 4. Identity Core vs Output Attributes

Identity Core and output tokens are different concepts.

Identity Core means attributes used to recognize or preserve the identity of a module. These attributes are not necessarily tokens that must always be emitted into every generation prompt.

Important distinction:

```text
identity_core != always_output_tokens
```

For example, a body close-up or lower-body close-up may need to disable face or eye attributes. Some image models may try to render a face if face, eye shape, or eye color tokens are present, even when the intended image is a cropped body detail.

This is especially important for Anima / Qwen-style generation behavior, where identity or face tokens can strongly pull the output toward a face composition.

## 5. Recognition Profile vs Generation Profile

Modules may eventually need two related but separate profiles:

- Recognition profile / match profile
- Generation profile / output profile

Recognition profile answers:

```text
Does this prompt line represent this module?
```

Generation profile answers:

```text
What tokens should be emitted for this line, route, or scene?
```

These may differ. For example, `name: nijitsuji milk` may help recognize the character module, but the name token may be disabled in a body close-up generation preset if it makes the model over-emphasize face identity.

The current Core Token and Minimum Match Threshold system is an early recognition mechanism. It should not be treated as a full generation-profile system.

## 6. Line / Route / Scene Overrides

Module expansion may need context-specific overrides.

Examples:

```text
Route: body_closeup
disable:
- face
- eye_shape
- eye_color
- hair_accessory
```

```text
Route: bathroom
replace:
- hair_style -> Milk Bathroom Hair Style
```

Overrides should be non-destructive. Disabling an attribute for a line, route, scene, or line group should not delete it from the module. It should only change how the module is expanded or applied in that context.

## 7. NegativeAttributes and Disabled-State Suppression

Negative Prompt Consistency analysis showed that negative prompts are not only global quality filters. They can also express creator intent, scene-specific suppression, composition failure-mode suppression, and suppression of attributes that a LoRA tends to reintroduce.

This affects module design. Some optional positive attributes may need paired negative tags when disabled. Removing the positive tag is not always enough, especially when a character LoRA strongly reintroduces accessories or identity-linked details.

PromptGraph-Pro now persists per-line `negative_prompt` text and lets the Selected Line Panel edit that stored text. That is a practical foundation for studying positive/negative separation in imported prompt sets, but it is still line-level text storage, not module-linked NegativeAttribute behavior.

Example:

```text
Module Core:
- character LoRA
- face identity
- body identity

Normal scene:
- Attribute ON: ribbon, hairclip
- Positive output: ribbon, hairclip

Bath scene:
- Attribute OFF: ribbon, hairclip
- NegativeAttribute ON: ribbon, hairclip
```

The Module Core remains stable. The Attribute state changes by scene/context, and a future NegativeAttribute runtime may emit `negative_when_disabled` tags when the positive Attribute is disabled.

This implies three related but separate future concepts:

- **Common Negative Prompt**: shared quality/failure-mode template across the project or route.
- **Line-specific Negative Delta**: scene-specific additions to the negative prompt.
- **NegativeAttribute**: module-linked negative tags used to suppress disabled or context-inappropriate attributes.

Clean Positive / Negative separation can make illustration sets easier to analyze, reconstruct, and migrate to stricter prompt-understanding models. Brute-force weighted positive prompts may still be valid generation tactics, but they are harder to migrate because intent and suppression are mixed into one flat text field.

This section remains future design for runtime behavior. PromptGraph-Pro does not yet persist Global Negative Prompt, Line-specific Negative Delta, or executable NegativeAttribute state. Current negative prompt features are per-line negative prompt persistence, selected-line editing, metadata preservation, Comfy export support, read-only Negative Prompt Consistency analysis, read-only Global Negative / Delta Preview, metadata-only Attribute Group negative fields, and a read-only Attribute Group NegativeAttribute Preview.

## 8. Override Priority

A future system needs predictable priority. Proposed order:

```text
Project defaults
-> Module defaults
-> Route overrides
-> Scene / Line Group overrides
-> Line overrides
-> Manual token edits
```

This priority matters because PromptGraph needs explainable prompt changes and predictable lineage. A user should be able to understand why a token was emitted, disabled, or replaced without guessing which layer won.

## 8.1 Attribute State / StateDomain

Attributes are powerful when a semantic slot stays mostly stable, but production routes often contain state changes over time. Clothing and accessory states are common examples:

```text
Line 1: bra, panties
Line 2: bra, panties
Line 3: panties
Line 4: no bra, panties
Line 5: no underwear
```

This should not be solved by expanding Attribute Group names until every possible timeline state is encoded in a variant name. A name such as `underwear_set.black.fullset` mixes three different concepts:

- **AttributeSlot**: the compatible semantic position, such as `underwear_set`.
- **Variant**: the prompt realization family, such as `black` or `green`.
- **StateDomain**: the temporal state set, such as `fullset`, `topless`, `bottomless`, or `naked`.

State must not be encoded into Attribute Variant names. A future model should treat Attribute Variant and StateDomain as independent dimensions:

```text
Slot
  underwear_set

Attribute Variant
  black
  green

StateDomain
  fullset
  topless
  bottomless
  naked
```

The intended separation is:

- **Module owns identity.** A Module preserves the reusable character, outfit, style, or scene identity needed for meaningful prompt reuse.
- **AttributeSlot owns compatibility.** A slot says which semantic position can be compared or swapped.
- **Attribute Variant provides prompt realization.** An Attribute Variant supplies the concrete tags or text used to express a slot.
- **State represents temporal progression.** A state says which phase of the slot is active on a specific line.

This is a future conceptual model only. Pro v1 does not implement state-aware swap, state inference, timeline UI, JSON schema changes, or project migration.

### Conceptual Object Model

The future Attribute State model can be described as:

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
    variant
    state
```

Example:

```text
StateDomain: underwear_state
    states: [fullset, topless, bottomless, naked]

AttributeSlot: underwear_set
    state_domain: underwear_state

AttributeVariant: black_underwear
    slot: underwear_set
    realization:
        fullset: black bra, black panties
        topless: black panties
        bottomless: black bra
        naked: no underwear

LineBinding:
    line: line_004
    slot: underwear_set
    variant: black_underwear
    state: topless
```

The important design choice is that `black_underwear` remains the Attribute Variant while `topless` is a state assignment for one prompt line. This avoids encoding semantic relationships into dotted naming conventions and makes future review tools easier to explain.

`Variant` already has a Gallery meaning in Pro v1, including appended variants and Promote Variant to Route. Future docs should say **Attribute Variant** when discussing AttributeSlot realization so it does not collide with Gallery Variant / Append Variant terminology.

### Storage Responsibility

Current Attribute Labels and Attribute Groups are project-wide metadata. Attribute Labels are keyed by normalized token/base-word keys, and Attribute Groups collect normalized token keys into project-level semantic slots. That storage is appropriate for reusable labeling and inspection.

Future LineBinding is different. It is per Prompt Line metadata because it describes which Attribute Variant and State apply to one line in the illustration sequence. It cannot share the current project-wide Attribute Label storage layer without losing occurrence-level meaning:

```text
Current Attribute Labels
    project-wide
    token/base-word keyed
    shared wherever the token appears

Future LineBinding
    per Prompt Line
    slot + attribute_variant + state keyed by line occurrence
    source of truth for stateful progression
```

For example, the token `panties` may appear in several lines, but the state transition from `fullset` to `topless` to `naked` belongs to the line sequence, not to the global token label. Storing it globally would make one token imply the same state everywhere, which is exactly the drift the StateDomain model is meant to avoid.

### State Timeline

A future State Timeline should initially be a derived view, not persisted data. The source of truth should be per-line state assignments through LineBinding. A Timeline can then be rendered by reading each line's `slot + attribute_variant + state` binding in route or sequence order.

This keeps timeline UI optional and rebuildable. It also avoids a second persisted timeline layer that could drift from line-level state metadata.

Pro v1 should continue to treat this as a manual-review design constraint, not as a solved automatic mapping problem. Current recommended handling:

- Routes with large Attribute timeline changes should assume manual review.
- Attribute Groups are useful, but they should not imply perfect temporal state tracking.
- Safety tools and preview-first adoption are the Pro v1 answer for now.
- Pro v1.1 / Exp / Desktop work can explore Attribute State, StateDomain, LineBinding, Stateful Attribute Swap, state extraction, Illustration Set analysis, and Illustration Set reconstruction after the object model is validated.

## 9. Attribute Conflict / Dependency Rules

Attribute groups may conflict or imply dependencies.

Examples:

- `bathroom_hair` may disable `hair_accessory`.
- `swimsuit` may conflict with `school_uniform`.
- `body_closeup` may disable `face`, `eye_shape`, `eye_color`, and `expression` groups.

This does not require a full rule engine yet. The near-term design goal is to acknowledge conflicts and make future preview output able to show them. PromptGraph should avoid silent destructive swaps.

## 10. Unassigned Tokens

Not every token will have an attribute label. It would be unsafe to assume that every unassigned token automatically belongs to the previous token or previous group.

Possible future handling:

- Unassigned
- Attach to previous group
- Keep as extra
- Ignore during swap
- Require manual assignment

This should be explicit in preview. If a swap ignores or preserves unassigned tokens, the user should be able to see that decision.

## 11. Prompt Order Preservation

Prompt token order may matter. Attribute-based modules should preserve original module body order by default.

Future systems may need order rules, anchors, or before/after constraints, but those should not be implemented prematurely. The first implementation should preserve the existing body order unless the user explicitly previews and accepts an order change.

## 12. Safety and Preview-First Principle

Attribute-based swap must remain preview-first.

Preview should show:

- before
- after
- removed attributes
- added attributes
- disabled attributes
- unmatched attributes
- conflicts

Do not allow destructive automatic module swaps without preview. This is consistent with PromptGraph Pro's current manual-first editing philosophy and with the existing module candidate apply workflow.

## 13. Suggested Implementation Path

This path is partly implemented and still cautious:

1. Node Attribute Label v1 - implemented.
2. Module Attribute Table v1 - implemented as read-only inspection.
3. Attribute Group / Slot v1 - implemented as editable metadata.
4. Core / Optional Token Selection for module creation - implemented as module metadata.
5. Module Expansion Preset v1 - future work.
6. Line / Route Override v1 - future work.
7. Attribute Group Swap v1 - implemented for existing scopes and session-only Selected Routes; Attribute-based Module Swap remains future work.
8. NegativeAttribute / `negative_when_disabled` preview - implemented as read-only inspection.
9. Module / Attribute UI organization - implemented as Authoring / Apply / Analysis sections.
10. Attribute State / StateDomain / LineBinding - future conceptual design only; no schema or runtime behavior yet.

The first useful implementation should probably focus on character, hair style, outfit, expression, camera, and composition modules. Behavior/action modules should wait until the simpler attribute and slot model is validated.

## Current Boundaries

Current limitations:

- No save/load format changes are required for the current metadata workflow.
- No automatic tag normalization.
- No AI/LLM automation requirement.
- Attribute Group Swap is implemented for project-local Groups; its Selected Routes scope requires compatible normalized slots, while broader attribute-based Module Swap remains future work.
- No Attribute Group Compare yet.
- Selected Routes does not introduce cross-slot swap; incompatible or malformed slots fail closed in that scope, while existing scopes keep their established behavior.
- No automatic Attribute Label inference.
- No AI/WD14Tagger labeling.
- No negative Prompt rewriting from Attribute Group metadata; current Attribute Group Swap changes positive Prompt tokens only.
- No occurrence-level Attribute storage.
- No Attribute State, StateDomain, Attribute Variant realization map, LineBinding, or State Timeline persistence.
- No Global Negative Prompt persistence.
- No Line-specific Negative Delta persistence.
- No NegativeAttribute or `negative_when_disabled` behavior.
- No full NovelAI parser.
- Current Core Tokens and Minimum Match Thresholds remain the active v1 recognition tools; selected-token Core / Optional metadata does not yet change candidate matching behavior.
- Current module apply remains preview-first and replaces matched tokens with module references without inserting missing tokens.
