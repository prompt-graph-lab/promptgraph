# Agent Generation and Candidate Review: Architecture Audit

Status: repository-backed design for Pixiv Publish Skill Phase 4, audited at
`fe103fdb4f3744b2813e290f28944735cc6b0bd5`. No runtime feature is added by this
document. Proposed tool names below are not advertised MCP capabilities.
The [Pixiv roadmap](pixiv-publish-skill-plan.md) owns the overall workflow;
this audit covers generation requests, job observation, and Candidate review.

## Current owners and gaps

| Responsibility | Current owner and evidence | Reuse boundary |
| --- | --- | --- |
| Workflow selection and preparation | [app.py](../../app.py): `resolve_effective_comfy_workflow_path`, `_build_focus_line_generation_workflow`, `_build_selected_routes_gallery_generation_plan`; [workflow preparation](../../core/comfy_workflow_preparation.py) and [generation prompt](../../core/comfy_generation_prompt.py) | Keep configured endpoint, preset precedence, Module resolution, negative prompts and workflow preparation host-owned. Accept Scene/Illustration handles, never client workflow JSON or paths. |
| Selected Scenes generation plan | [gallery_generation.py](../../core/gallery_generation.py): `build_selected_routes_generation_plan`, `validate_selected_routes_generation_submit` | Reuse physical ordering, eligibility, whole-plan preflight, input/workflow signatures and frozen request construction. Raw plans contain model objects and workflows; project a safe JSON envelope rather than returning the plan. |
| Execution and output routing | [app.py](../../app.py): `_execute_selected_routes_gallery_generation_plan`; [gallery_generation.py](../../core/gallery_generation.py): `execute_gallery_generation_plan`, `ingest_gallery_generation_outputs`, `resolve_gallery_generation_result_target` | Existing execution is sequential and synchronous, with per-request partial failures. Route real unique outputs by stable source Line ID; do not auto-adopt them. A new host job lifecycle must wrap this behavior before asynchronous MCP start is possible. |
| ComfyUI submission/progress/download | [comfyui.py](../../core/comfyui.py): `generate_image_with_progress`, `_poll_comfy_output_history`; [submission](../../core/comfy_prompt_submission.py), [message interpretation](../../core/comfy_message_interpretation.py), [download](../../core/comfy_image_download.py) | Progress is a generator consumed by the UI, not a durable job service. Completion polls history and downloads outputs into the host-selected directory; `done` includes paths and `prompt_id`. Do not equate queued/execution-done with Candidate registration. |
| Candidate storage and UI synchronization | [app.py](../../app.py): `_make_generated_candidate_record`, `_get_persistent_line_candidates`, `_get_line_generated_candidates`, `_append_line_generated_candidates`; [normalization](../../core/candidate_record_normalization.py) | Persistent `line.generated_candidates` and session `line_generated_candidates` are existing owners. `_get_line_generated_candidates` merges and writes state, so it is unsuitable as a read-only MCP observer. Observe a captured copy of persistent records; resolve session-only reconciliation in the host separately. |
| Candidate inspection | [candidate_inspection.py](../../core/candidate_inspection.py): `get_candidate_prompt_text`, `_candidate_prompt_metadata`, `_active_candidates`, `_sort_candidates_for_display`; [presentation](../../core/comfy_candidate_presentation.py) | Reuse prompt-source gates, metadata priority, stable pinned ordering, Trash handling and missing-value behavior. Metadata availability is not proof of prompt/image semantic consistency. |
| Single image and prompt adoption | [app.py](../../app.py): `set_candidate_as_main_image`, `swap_line_main_image_with_candidate`, `set_candidate_as_empty_line_image`, `apply_candidate_prompt_to_current_text_from_ui` | Image adoption and prompt adoption are separate human actions. Retain previous-main retreat/lineage semantics. Never expose these UI mutation functions directly as MCP tools. |
| Scoped image adoption | [route_batch_candidate_adoption.py](../../core/route_batch_candidate_adoption.py): `build_selected_routes_candidate_adoption_preview`, `apply_selected_routes_candidate_adoption`; [publication lifecycle](../../ui/selected_routes_candidate_adoption_lifecycle.py): `apply_and_publish_selected_routes_candidate_adoption` | Reuse atomic clone planning, fresh signatures, source/file validation, history, graph/focus/text synchronization and save ordering. Existing `latest`/`first` selection is not arbitrary per-Candidate selection. |
| Existing agent observation and routing | [agent_facade.py](../../core/agent_facade.py), [MCP adapter](../../agent_adapters/mcp_adapter.py), [request bridge](../../ui/project_agent_request_bridge.py), [session pump](../../ui/project_agent_session_pump.py) | Current Illustration observation exposes image references and Candidate counts, not a Candidate listing or generation service. Keep JSON schemas/projection in facade/adapter, full-run capture and host service in bridge/pump. |
| Human review precedent | [review lifecycle](../../ui/agent_scene_module_swap_review_lifecycle.py), [approval lifecycle](../../ui/agent_scene_module_swap_approval_lifecycle.py), [Apply lifecycle](../../ui/agent_scene_module_swap_apply_lifecycle.py) | Scene Module Swap already has session custody, exact preview revalidation, one-shot human approval and publication/save outcomes. Reuse this authority pattern; its operation-specific custody is not automatically a generic generation/adoption service. |

The existing [Scene Batch Candidate Adoption design](route-batch-candidate-adoption.md)
also documents the legacy `Batch Adopt Gallery Candidates` differences: that
replace path writes `generated_image_path` and does not perform main-image
retreat. A new agent review flow must deliberately select the unified scoped
engine, not silently substitute the legacy path. Image adoption preserves
editable positive/negative text; prompt adoption remains separate.

## Identity and authority contracts

Use the existing explicit paired browser-session route, process incarnation,
pairing generation, target epoch, capacity-one mailbox and full-run capture
boundaries described in [session pairing](mcp-session-registration-pairing.md),
[session pump](mcp-session-mailbox-pump.md) and
[Project capture](mcp-project-capture.md). A route is not a Project identity;
pairing survives Project switches while old-epoch work is rejected. Target
epochs are activation guards, not content freshness proofs.

Proposed host job identity binds an opaque job handle to session/process,
origin target epoch, captured Project activation, immutable input/workflow
fingerprints, source Illustration IDs and per-request/run identities. Do not
use filename, list position, `prompt_id`, `plan_id`, or Project path alone as
authorization. Existing `gallery_generation:<line-id>:<run-index>` IDs identify
requests within one plan; they are not globally unique job IDs or cross-call
idempotency keys. Candidate records can be legacy strings or path-keyed dicts;
an opaque observation handle must bind record identity/fingerprint to an
Illustration and target revision without adding duplicate persisted records.

| Proposed surface | Authority | Required host behavior |
| --- | --- | --- |
| `promptgraph_list_candidates` / `promptgraph_get_candidate` | Read-only | Bounded active normal Illustration scope; allowlisted metadata, selection/pin/Trash state, missing-image state, ordering and truncation. No mutation, arbitrary file reads, raw workflow/exception dumps or image bytes. |
| `promptgraph_preview_generation` | Read-only planning | Bounded explicit Scene scope and run count; resolve host configuration, show target/order/counts and warnings, return safe fingerprinted envelope. No submission, downloads or Candidate append. Workflow reading, if needed, is host-configured only. |
| `promptgraph_request_generation_review` | Generation intent only | Queue a fresh preview in host custody. Human reviews endpoint/preset summary, prompts, counts, output side effects and warnings, then explicitly starts. Successful request means queued for review, not approved or submitted. |
| `promptgraph_get_generation_job` | Read-only job observation | Return bounded counts, monotonic event revision, partial results and distinct terminal outcomes for a session-owned job. Polling cannot start, resume, retry or adopt. |
| `promptgraph_preview_candidate_adoption` / `promptgraph_request_candidate_adoption_review` | Read-only preview / review intent | Show before/after image references, retreats, prompt drift warning and skips through existing scoped planner. Human host approval is the only Apply authority. Initially restrict to supported scoped `latest`/`first` sources. |

All names and schemas are proposals. Advertise each only when implemented with
its complete authorization tests. A future direct generation-start tool would
need a separately defined host-issued, narrow, one-shot authorization; it is
not part of this plan. Client-supplied `approved: true` or a returned plan ID
must never confer generation-start or adoption authority.

For generation: Preview -> host custody -> human Start -> immediate target and
input/workflow freshness validation -> submit once -> observe -> guarded output
registration. Generation starts external work and writes output/Candidate state;
it deserves approval independently of later image adoption. For adoption:
Preview -> host custody -> human Approve and Apply -> immediate fresh exact-plan
and file validation -> core clone -> host publication/history/save. Distinguish
applied-but-save-failed from persisted success; do not claim rollback of already
published data or downloaded files.

Selection proposals may contain the agent's reasoning and uncertainty, but the
host independently resolves every handle and displays the authoritative plan.
The Skill owns visual judgment and sequencing. An image transport primitive
belongs to Phase 5 and must bind observation to a registered asset with bounded
size/type and path containment; this phase grants no arbitrary filesystem MCP
capability. Existing path strings are references, not permission to fetch files.

## Job lifecycle and concurrency requirements

There is no reusable durable MCP job registry, cancellation API or restart
reconciliation service in the audited generation path. Introduce the smallest
session-host job owner when asynchronous execution is implemented, not in the
transport adapter. It should keep immutable request intent, bounded status and
correlation only; Project Candidate records remain authoritative results.
Network execution may run outside Streamlit only after separating the current
UI callbacks. Background workers must never read/write `st.session_state` or
mutate live Project objects. Deliver immutable events/results to the host for
serialized validation and publication. Do not execute a long generator inside
the capacity-one MCP request mailbox; acknowledge review promptly and poll a
separate host job snapshot through normal request service.

- Serialize start claims, output registration and adoption publication per
  session/target; initially allow one active generation job per session. Bound
  run count, total requests, job retention, polling payload and review lifetime.
- Persist an in-memory one-shot start claim before external submission. Scope
  idempotency to pairing/session, target and normalized intent; same-key/same-
  intent returns the original receipt, changed intent rejects. Mailbox request
  correlation alone does not deduplicate generation across calls. Never retry
  an ambiguous network submission automatically; report submission-unknown.
- Preserve per-request partial failures and multiple real outputs. Completion
  distinguishes external execution, download, Candidate registration and save.
  Existing path deduplication is not external-request exactly-once assurance.
- Revalidate origin activation before each registration and resolve stable
  source IDs using the existing engine. If Project switches, Save As, target
  deletion/ambiguity or incompatible prompt/workflow change occurs, do not
  attach late outputs to the new active Project. Mark stale/unregistered and
  retain host-controlled recovery information; do not delete real outputs.
  In-Project reorder may route by ID only if the agreed freshness policy allows
  it. A new Project with copied IDs is never the original job target.
- Client disconnect is not cancellation or permission to transfer a job to
  another pairing. Host observation may continue; no automatic resubmission,
  re-pair, route fallback or adoption. Session/process loss has an explicit
  unavailable/unknown outcome, rather than a fabricated failed/completed job.
- First cancellation support should stop unsent requests through human host
  control. A submitted ComfyUI task can continue: mark cancel-requested versus
  confirmed-canceled truthfully. Do not use global interrupt/queue-clear APIs
  that could cancel another user's job. Remote cancellation is deferred until
  exact-job ownership and ComfyUI semantics are verified.
- Pending previews expire and become stale on target/content change. Approval
  and start are consumed once, including double-click/concurrent claims. No
  terminal job or rejected approval silently returns to runnable state.

These are future acceptance requirements, not assertions that current
synchronous generation already enforces all of them.

## Small PR sequence and first useful slice

1. **Candidate metadata observation only.** Add bounded list/get facade
   projections and MCP catalog/bridge wiring over captured persistent records.
   This independently helps an agent inspect available alternatives and propose
   human review through existing Gallery UI, without job infrastructure or new
   mutation authority. Report availability honestly; no bytes or visual-quality
   claims. Capability discovery must explicitly say no generation/adoption.
2. **Generation preview and human review custody.** Reuse Selected Scenes
   planner/preflight and configuration owners; add complete host review with
   expiry/freshness, initially leaving execution in the existing human UI.
   Preview/request success must not imply a job exists.
3. **Host generation job lifecycle and observation.** Separate UI progress
   callbacks from execution, implement serialized one-shot starts, result
   registration and job snapshots, then expose job observation. Keep supported
   scope narrow (one Scene, bounded run count, configured ComfyUI workflow).
4. **Candidate adoption preview and human Apply.** Bind supported scoped
   source selection to fresh signatures and host approval/publication. Defer
   arbitrary per-Illustration Candidate mappings until a core planner supports
   them; do not pretend `latest` means the visually recommended Candidate.

First-slice acceptance tests must cover:

- list/get through facade, adapter, bridge and paired route; strict bounded JSON
  schemas, deterministic order, limits/truncation and unknown handles;
- legacy records, missing metadata, seed zero, pinned order, Trash exclusion,
  manual-import metadata source gates, unavailable files and same-path records;
- absent Project, deleted/separator/Workbench targets, ambiguous Illustration
  IDs, target switch between capture and reply, expired handle and old pairing;
- immutable live Project, persistent records, session Candidate cache, settings
  and filesystem across repeated observation, including failures; never call
  the mutating `_get_line_generated_candidates` during read-only capture;
- no workflow parsing/network generation, save/history, Candidate append,
  prompt adoption, image adoption or arbitrary-path/bytes endpoint; standalone
  provider and paired host preserve the same domain projection semantics.

Use existing characterization as compatibility evidence:
[generation plan tests](../../tests/test_gallery_generation_selected_routes.py)
cover physical order, stale signatures, resolved workflow changes, partial
failure, routing and duplicate output paths;
[inspection tests](../../tests/test_candidate_inspection.py) cover source gates,
falsey values, ordering and record identity;
[scoped adoption tests](../../tests/test_route_batch_candidate_adoption_selected_routes.py)
cover atomic clones, drift/file freshness and rollback;
[publication tests](../../tests/test_selected_routes_candidate_adoption_lifecycle.py)
cover callback order and partial publication failures. Future generation tests
must add concurrent duplicate starts, ambiguous submission, disconnect, Project
switch, late output, cancellation and save-failure scenarios with fake bounded
execution; existing tests do not establish those asynchronous guarantees.

## Non-goals and unresolved decisions

No runtime implementation, dependency/schema change, full-suite run, generation
execution, new live Skill, image transport, crop/export/upload, automatic
Candidate/prompt adoption or Astra-MSC experiment is part of this audit.

Before the respective implementation PR, decide:

- Candidate opaque-handle lifetime and duplicate-path disambiguation, plus how
  host capture reconciles session-only records without making reads mutating;
- exact review/job retention, capacities, receipt schema and polling revision;
- job behavior on browser inactivity/session loss/process restart, and whether
  restart reconciliation is deliberately unsupported in the first job slice;
- which prompt/config changes after submission quarantine outputs, and how a
  human can recover unregistered files through a bounded host action;
- whether safe `prompt_id`/seed provenance must be retained in Candidate records
  (the selected-routes UI currently consumes output paths rather than retaining
  the entire `done` event), and the smallest compatible metadata extension;
- generic versus operation-specific review custody without changing the shipped
  Scene Module Swap contracts, and separately authorized cancellation semantics;
- exact per-Candidate selection planning beyond existing source selectors, and
  bounded image observation needed before the agent can make visual judgments.
