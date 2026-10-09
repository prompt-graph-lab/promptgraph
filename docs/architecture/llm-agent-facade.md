# LLM Operator PoC-0, PoC-1a, and PoC-1b: Facade and MCP Binding

`core.agent_facade` is a small transport-neutral boundary shared by the MCP SDK
binding and a later internal LLM harness. It provides observations and reviewed
Preview envelopes for Batch Replace and single-Scene Module Swap. A separate
explicit MCP request can ask the host to retain a fresh Module Swap Preview for
human review; the adapter and facade do not own that session-local custody.
`app.py` remains the terminal application shell.

The near-term workflow direction for these primitives is documented in the
[Pixiv Publish Skill plan](pixiv-publish-skill-plan.md). Current MCP tools
include the read-only and Preview surface plus an explicit host-review request;
human decision, Apply, and publication remain host-owned.

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
approved envelope. Authentication, human authorization, and recording that
decision belong to a host UI and session lifecycle, not the core facade or MCP
gateway. The explicit Scene Module Swap review-request route and its current
session-local custody boundary are documented in
[Agent Scene Module Swap approval custody](agent-scene-module-swap-approval-custody.md).
That route only queues a fresh proposal. It does not collect a human decision,
Apply a plan, or publish a Project.

## Versioned observation surface

All agent results use `contract_version: "promptgraph.agent-facade.v1"`.

| Function | Result |
| --- | --- |
| `discover_capabilities()` | Supported observations and search bounds, Batch Replace modes, and single-Scene Module Swap modes/requirements |
| `summarize_project(project)` | Illustration, Scene, baseline, deleted-line, Workbench and active Candidate/Variant counts; bounded Module and Attribute Group names |
| `observe_scenes(project, limit=100)` | Active separator-backed Scenes in Project order, explicit order, labels, color and bounded Illustration IDs |
| `list_illustrations(project, scene_id=None, limit=100)` | Normal active Illustrations in Project order, optionally filtered by Scene; filename, sequence index, Scene label, edited state, prompt text, stored image references and active Candidate/Variant counts |
| `search_illustrations(project, query_text, match_mode="exact_token", scene_id=None, limit=100)` | Read-only count and bounded ID/Scene/sequence results for active Illustration prompt matches |
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
`contains_token`, `literal` and `token_set` are supported. Find and Replace must
both be non-empty for every mode, matching the Batch Editing product-level
validation. Existing core token validators are authoritative. Token-set mode
forces effective weight preservation to false and retains PR #113 semantics:
all Find bases must match, all matching occurrences are removed, and the
authored replacement sequence is inserted once at the earliest match.

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
ordinary exceptions. A valid no-op Preview returns zero affected count for
observation, but Apply rejects it with `no_changes` before cloning or calling
the Batch Apply core, matching the UI's disabled Apply boundary. Approval,
history, autosave, persistence, UI publication and rerun remain outside this
owner.

## Explicit non-goals

PoC-0 adds no MCP server, LLM harness/model integration, UI or session plumbing,
generation, ComfyUI execution, image/asset access, filesystem persistence,
Candidate adoption/promotion, Scene mutation, Module or Attribute mutation,
semantic inference, autonomous editing or generalized transaction framework.
It neither implements a first-class Scene schema nor merges Route organization
with Snapshot state. Future adapters share this boundary and must preserve its
reviewed-intent and host-only publication responsibilities.

## PoC-1a: MCP-facing adapter seam

`agent_adapters.mcp_adapter` owns the small MCP-facing logical tool catalog,
transport argument shape checks, host Project-provider boundary, and bounded
adapter errors. It is deliberately outside `core`: it delegates every domain
observation and reviewed Preview to `core.agent_facade`, which continues to
own Scene/Illustration semantics, prompt validation, explicit target resolution,
transforms, freshness, fingerprints, digests, and reviewed-envelope construction.
The adapter is not a generic plugin registry or service container.

The stable logical tool names and effects are:

| Tool | Effect | Facade operation |
| --- | --- | --- |
| `promptgraph_capabilities` | Read-only | `discover_capabilities()` mapped to the adapter tool surface |
| `promptgraph_project_summary` | Read-only | `summarize_project(project)` |
| `promptgraph_list_scenes` | Read-only | `observe_scenes(project, ...)` |
| `promptgraph_list_illustrations` | Read-only | `list_illustrations(project, ...)` |
| `promptgraph_search_illustrations` | Read-only | `search_illustrations(project, ...)` |
| `promptgraph_get_illustration` | Read-only | `get_illustration(project, illustration_id)` |
| `promptgraph_preview_batch_replace` | Reviewed Preview | `preview_batch_replace(project, request)` |
| `promptgraph_preview_scene_module_swap` | Reviewed Preview | `preview_scene_module_swap(project, request)` |

The catalog is a deterministic, inspectable JSON description with explicit
schemas. It contains no Apply tool. Batch Replace targets remain explicit
Illustration IDs; Scene Module Swap requires one explicit active Scene and
explicit source and target Module names. The adapter adds no semantic scopes
or target inference. The facade Preview envelope is returned as-is rather than
reconstructed by the adapter. Scene Module Swap delegates to the existing
Selected Routes Module Swap planner, then returns a bounded safe projection:
the full projection digest covers every target while visible prompt rows cap
at 100. Module snapshots/bodies, Module metadata, reference assets, Project
and image paths, and raw planner diagnostics do not cross the agent boundary.
The tool supports the existing `strict` and `loose` match modes and explicitly
reports that Negative Prompts remain unchanged. It creates no Apply or host
approval authority. Illustration search supports `exact_token`, `contains_token`, and
`literal`; its result list is capped at 100 while `total_count` covers every
matching active Illustration. It shares the list operation's active target,
Scene ownership, and baseline `scene_id: null` rules, and returns no prompt text.
The token modes reuse the parser-backed Batch Replace matcher: exact mode uses
one token base, contains mode searches within token bases, and both skip
structural Module markers. Literal mode searches the raw prompt substring,
including marker text and any query whitespace.

The host supplies the active Project through a provider callback when it creates
the adapter. Capabilities discovery does not need a Project; each other tool
call asks the provider for the current Project and does not cache it. The
adapter does not discover, load, save, or globally retain Projects, Previews,
approval state, or results. Missing providers, invalid Projects, and provider
exceptions return bounded JSON-safe errors without exception text, paths,
reprs, stack traces, or type details. Argument and result boundaries contain
ordinary JSON primitives and containers; Project, PromptLine, graph/session
objects, callables, and arbitrary metadata never enter agent-facing results.

Reviewed Previews are the only mutation-related capabilities exposed to an
agent. The distinct Scene Module Swap review-request tool asks the trusted host
to retain a fresh safe envelope for human review; it has no mutation or
approval authority. The session runtime owns this transient custody, while the
host remains responsible for human approval and any later Apply. A `plan_id` is
a content identifier and integrity check, not an authorization token. The
model cannot prove approval by echoing an envelope, setting an `approved` flag,
or supplying a plan ID. The adapter adds no Apply wrapper, approval registry,
or mutable adapter-global Preview store. PR-A, PR-B, and PR-C implement
session custody, the Agent Review UI, and the dedicated host-only Scene Module
Swap Apply lifecycle. PR-D characterizes their composed path through the
official stdio launcher, real Windows Named Pipes, full `app.py` Streamlit
runs, human widget actions, and the existing Project persistence owner; see
the custody document for coverage and remaining manual boundaries.
`core.agent_facade.apply_batch_replace` remains callable only by a trusted
host.

This adapter imports no MCP package and does not implement MCP wire behavior.
There is no MCP SDK/runtime dependency, server process, authentication, stdio,
HTTP, or SSE activation in PoC-1a, and the exact runtime dependency lock is not
changed. A later official SDK/transport activation is a separate bounded slice
that must reconcile the SDK's supported Python/runtime and dependency audit with
PromptGraph's release contract. The internal LLM harness and UI integration
remain later layers. Neither an MCP transport nor a harness becomes a domain
owner; both must call this adapter/facade boundary while core behavior remains
authoritative.

## PoC-1b: official MCP SDK binding

`agent_adapters.mcp_sdk_binding` binds the PoC-1a logical tool catalog to the
official MCP Python SDK `Server` API. It uses the SDK's public low-level
`Server` interface so PromptGraph controls the exact existing JSON input
schemas and can characterize the registered tool surface without duplicating
facade behavior. The SDK wrapper delegates every tool call to
`agent_adapters.mcp_adapter`; that adapter continues to validate transport
shape before asking the host Project provider, and `core.agent_facade` remains
the owner of domain validation and observations.

The binding registers the nine logical tools from the adapter catalog:

- `promptgraph_capabilities`
- `promptgraph_project_summary`
- `promptgraph_list_scenes`
- `promptgraph_list_illustrations`
- `promptgraph_search_illustrations`
- `promptgraph_get_illustration`
- `promptgraph_preview_batch_replace`
- `promptgraph_preview_scene_module_swap`
- `promptgraph_request_scene_module_swap_review`

Read-only, reviewed-Preview, and host-review-request effects are carried as MCP
tool annotations and PromptGraph metadata. The review-request tool is
successful only through the trusted app-side bridge and returns queue status;
a standalone logical-adapter or SDK call refuses before Project-provider
access. Results preserve the adapter's JSON object as MCP
`structuredContent` and include deterministic JSON text content. Project and
all provider state remain host-owned; each Project-dependent call asks the
adapter's provider for the current Project. The SDK binding retains no active
Project, proposal, human decision, Apply authority, or authorization state.

The SDK low-level server does not validate incoming call arguments against the
published input schema. The adapter's existing transport-shape validation
therefore remains required and runs before Project access; the app-side bridge
also validates the host-review request before capture. Domain Preview
semantics remain in the facade. The binding does not add its own validation or
rebuild Preview envelopes.

There is deliberately no agent-callable Apply tool. The host must retain the
exact Preview envelope approved by a human and may call the trusted facade
Apply path only under its own approval-custody policy. A `plan_id` identifies
content; it is not authorization. The MCP SDK binding neither asks the model
to assert approval nor interprets any tool argument as approval.

PoC-1b adds the pinned direct dependency `mcp==2.2.0` and regenerates the exact
runtime lock under the supported Windows/CPython 3.14 wheel-only procedure.
Dependency versions, package metadata, license groupings and lock digest are
recorded in `requirements.txt`, `docs/supported-environment.md`, and
`docs/release-process.md`. The MCP SDK's dependency footprint is part of that
explicit runtime audit.

This binding only constructs an in-process SDK `Server` for a host to register
and test. It does not call the SDK run loop or activate stdio, HTTP, SSE,
authentication, process lifecycle, or application startup. A later transport
host must decide and implement those responsibilities as a separate slice.
No internal LLM harness, UI, Streamlit/session access, or Project persistence
is added. MCP remains a transport boundary; it does not become a PromptGraph
domain owner.
