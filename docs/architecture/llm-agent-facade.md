# LLM Operator PoC-0: Agent Facade

`core.agent_facade` is a small transport-neutral boundary for a later MCP adapter
and an internal LLM harness. PoC-0 provides observations and one reviewed mutation
family, Batch Replace. It integrates neither transport nor model. `app.py` remains
the terminal application shell.

## Layering and trust boundary

An adapter supplies the host's active `Project` to facade functions. Agent-facing
arguments and results contain ordinary JSON primitives only. Project,
PromptLine, PromptNode, graph sets, arbitrary metadata, callables and session
objects do not cross this boundary. The facade does not import Streamlit, MCP,
model SDKs or `app.py`, perform network/filesystem/subprocess work, persist state,
or own a service container. It delegates prompt validation, Preview, transforms,
Module structure guards and Apply to `core.operations`.

The host owns approval and retains the exact envelope that was approved. SHA-256
identifies content and detects changes; it is not a signature or authorization
token. An agent must not substitute a newly constructed valid plan for the
approved envelope. Authentication, authorization and recording human approval
belong to the future adapter/harness. Apply itself validates and materializes
the supplied reviewed envelope, without prompting or publishing it.

## Versioned observation surface

All agent results use `contract_version: "promptgraph.agent-facade.v1"`.

| Function | Result |
| --- | --- |
| `discover_capabilities()` | Supported observations, Batch Replace modes and bounds |
| `summarize_project(project)` | Illustration, Scene, baseline, deleted-line, Workbench and active Candidate/Variant counts; bounded Module and Attribute Group names |
| `observe_scenes(project, limit=100)` | Active separator-backed Scenes in Project order, explicit order, labels, color and bounded Illustration IDs |
| `list_illustrations(project, scene_id=None, limit=100)` | Normal active Illustrations in Project order, optionally filtered by Scene; filename, sequence index, Scene label, edited state, prompt text, stored image references and active Candidate/Variant counts |
| `get_illustration(project, illustration_id)` | One stable-ID Illustration's observation plus bounded tokens |

Scene IDs are the existing separator PromptLine IDs. Scene observation reuses
`get_gallery_route_options`, including empty Scenes and the Gallery's active
separator semantics: deleted separators do not create active Scene boundaries.
Separators, deleted lines and Workbench cards are excluded from Illustration
lists. Normal Illustrations before the first active separator remain visible
as baseline Illustrations with `scene_id: null`; they are not silently assigned
an invented Scene. An omitted Scene filter lists all normal Illustrations.
Unknown filters and missing/ambiguous IDs fail with structured diagnostics.
Duplicate IDs anywhere in the Project fail closed, including deleted records,
because ID resolution must be unambiguous.

Observations do not normalize metadata, rebuild the graph, or mutate domain
objects. Row and token lists are bounded to 100. Text is represented as
`{text, truncated, length}` with at most 4,000 displayed characters. Counts and
truncation flags describe omitted data. Stable IDs are at most 200 characters;
invalid persisted IDs fail clearly. Detail results intentionally omit arbitrary
Candidate, image, lineage, Module and Attribute metadata in this first contract.
Sequence indices and Scene order are zero-based; Illustration sequence indices
count normal active Illustrations and remain stable across filtered listings.
Image references report only stored strings, without checking or resolving files.
Candidate/Variant counts use active path-bearing records, with appended Gallery
Variant classification matching existing Gallery/Route conventions. Module and
Attribute observations read names only, not entry values. A missing/malformed
host Project returns bounded structured diagnostics.

## Batch Replace request and reviewed envelope

```python
request = {
    "illustration_ids": ["illustration-stable-id"],
    "find_text": "white shirt, red skirt",
    "replace_text": "black dress, white apron",
    "match_mode": "token_set",
    "preserve_weights": False,
}
plan = preview_batch_replace(project, request)
```

`illustration_ids`, `find_text` and `replace_text` are required. The mode defaults
to `exact_token`; weight preservation defaults to true. Only `exact_token`,
`contains_token`, `literal` and `token_set` are supported. Existing core token
validators are authoritative. Token-set mode forces effective weight
preservation to false and retains PR #113 semantics: all Find bases must match,
all matching occurrences are removed, and the authored replacement sequence is
inserted once at the earliest match. Literal mode permits an empty replacement,
as the existing Batch Replace does; an empty Find is always rejected.

Requests permit no scope, selection, focus, visible-list or object-reference
targets. Empty targets, duplicate requested IDs after trimming, unknown IDs,
ambiguous persisted IDs and deleted/separator/Workbench targets are invalid.
Only the documented keys are accepted. IDs are normalized into Project sequence
order, matching Batch core traversal. Find/Replace strings retain authored text;
requests are bounded to 1,000 targets and 10,000 characters per text field.
JSON checks reject non-built-in objects, custom mappings, sets, nonfinite
numbers, cyclic values, invalid Unicode and excessive nesting/size without
stringifying or invoking supplied object hooks.

The JSON envelope contains contract version, operation, normalized request,
validity/reason/diagnostics, deterministic `plan_id`, `source_fingerprint`,
`projection_digest`, explicit target IDs, target/affected/skipped/unchanged
counts, and at most five examples. Examples include effective Before/After,
proposed After, changed/skipped flags and Module guard state. Text bounds apply
to examples too. Invalid requests return a JSON-safe ineligible envelope;
they never fall back to All scope or partial target resolution.

The fingerprint binds the normalized request, Project line order and exact IDs,
line type/deleted state, positive prompts, stored tokens, embedded prompt Module
structure and graph merge policy. All lines are bound,
including untargeted lines, since successful core Apply rebuilds the graph.
This deliberately conservative gate may stale a plan after unrelated prompt
changes. Batch Replace and its graph rebuild do not use the Module library, so
library metadata is not read or hashed for freshness. In particular,
`reference_assets` stays opaque under the existing public compatibility policy;
the clone preserves it without asset access or interpretation. Other host
publication context is the host's responsibility.

The projection digest binds **every target** in order, with full untruncated
Before/After/proposed After, changed/skipped flags and Module guard state.
It is independent of the five displayed examples. SHA-256 uses canonical JSON
(sorted keys, compact separators, UTF-8, no nonfinite floats). The plan ID hashes
the whole deterministic envelope excluding its own ID, including request,
fingerprint, full projection digest and displayed review fields. No Python
`hash`, random identifiers, timestamps or process-local plan registry are used.

## Preview → Approval → Freshness → Apply

1. Preview resolves exact targets, validates the request and builds the complete
   projection through the authoritative Batch core. It changes no Project state.
2. The host shows the envelope and obtains approval for that exact intent.
3. Apply validates JSON, shape, version, operation and envelope integrity, then
   recomputes a fresh plan from the current Project and embedded request. It
   compares the entire envelope, including fingerprint, complete projection
   digest and deterministic identity. Changed targets, prompts, tokens, types,
   deleted state, order or embedded prompt Module structure reject the reviewed
   plan as stale.
4. Only after this gate, Apply deep-copies the Project and calls existing
   `apply_batch_text_edit` with explicit IDs. Core retains its Module structure
   guard and graph rebuilding. The facade verifies all materialized prompts,
   tokens, edited flags, IDs, types and deleted state against the full fresh projection;
   mismatches or ordinary exceptions discard the clone.

```python
result = apply_batch_replace(project, approved_plan)
agent_payload = result.agent_result  # JSON-safe; send only this across transport
if agent_payload["ok"]:
    replacement = result.updated_project  # host-only Project, independent copy
    # Host decides whether/how to publish replacement, history, graph/UI and save.
```

`AgentApplyResult` is explicitly a host-only wrapper, not an agent response.
Failures return `updated_project=None` with JSON-safe diagnostics; exception
details are not exposed. The caller's Project, line identities, graph, library
and Attribute Groups stay unchanged on success, failure, stale plans and
ordinary exceptions. A valid no-op returns an independent clone with zero
affected count; the host may choose not to publish it. Approval, history,
autosave, persistence, UI publication and rerun remain outside this owner.

## Explicit non-goals

PoC-0 adds no MCP server, LLM harness/model integration, UI or session plumbing,
generation, ComfyUI execution, image/asset access, filesystem persistence,
Candidate adoption/promotion, Scene mutation, Module or Attribute mutation,
semantic inference, autonomous editing or generalized transaction framework.
It neither implements a first-class Scene schema nor merges Route organization
with Snapshot state. Future adapters share this boundary and must preserve its
reviewed-intent and host-only publication responsibilities.
