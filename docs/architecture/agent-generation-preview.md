# Agent Generation Preview

This is the read-only Preview-first split of the
[Phase 4 audit](agent-generation-candidate-audit.md). The shipped operation is
`promptgraph_preview_generation`. The subsequent
[Generation review custody](agent-generation-review-custody.md) adds an explicit
request tool and isolated session custody. The
[host Generation Review UI](agent-generation-review-ui.md) provides fresh
inspection and Reject/Dismiss only.
There is no Start/Apply action or job receipt.
The existing host generation UI remains the only execution path.

## Request and projection

Arguments are one explicit active separator-backed `scene_id` and optional
integer `run_count` (1–5, default 1). Client workflows, paths, endpoint/config
overrides, approval flags and unknown arguments are rejected before capture or
host configuration access. Normal targets must produce at most 100 planned
requests; Project observation is limited to 1,000 physical lines. Missing,
unknown, empty and over-limit targets return bounded refusal codes. No Gallery
selection/focus is inferred or changed.

The facade reuses `build_selected_routes_generation_plan` with exactly one Scene
and full preflight. Physical ordering, Workbench/deleted exclusions, eligibility,
workflow request construction, input/workflow fingerprints and all-or-nothing
preflight follow the existing planner. One blocked Illustration makes `valid`
false and request/output estimates zero. No partial generation is submitted.

Successful JSON includes Scene identity/label, ordered Illustration IDs and
authored/resolved positive/negative prompt summaries, per-Illustration
eligibility/blockers, workflow node/SaveImage-node counts, warning codes, target
and request counts, skipped records/counts, and a content `plan_id`. Prompt text
is bounded to 4,000 characters with length/truncation fields. At most 100 skipped
records are shown; `skipped_truncated` makes omission explicit. Raw workflow JSON,
node input values, local paths, endpoint strings, settings, exception messages
and arbitrary metadata are never projected.

`expected_image_count` follows the current planner's one-image-per-request
estimate. `expected_output_node_count` counts supported image-output nodes using
the existing SaveImage/PreviewImage and custom suffix classifier. Per-Illustration
`image_output_node_count` includes both classes; `save_image_node_count` remains
SaveImage-only. Node counts do not imply exact output-file counts;
neither promises actual downloaded-image counts, since workflow batching/runtime
behavior can differ. `valid` means offline preflight passed, not that the server
is connected or will accept every node/link. Seeds are not randomized/committed
by Preview. The injected active prompt summary is not a dump of every workflow
node; rows explicitly label it `active_illustration_inputs` and set
`workflow_binding_verified: false`. The summary does not certify that each
workflow text slot actually received those inputs. Grouped mappings or
unverified prompt injection require human inspection
and emit `prompt_binding_requires_review`.

## Configured workflow and ownership

The app supplies `_prepare_agent_generation_context` lazily at the existing
full-run service points. It uses the existing effective configured/preset path
resolver and `_selected_routes_generation_options` owner. It reads only the
host-selected shared workflow, at most 1 MiB, then reuses
`prepare_generation_injection_line` and `_build_line_workflow_from_text` for
Module expansion and prompt binding. Image-derived embedded workflows are
excluded from this initial agent operation; the existing host execution paths
retain their source-selection behavior.

The shared options owner accepts a precomputed file signature to avoid its
otherwise unbounded legacy read on this new path. Ordinary Gallery generation
keeps its existing behavior. Preview performs no network request, seed mutation,
download, Candidate append, Project publication, history, save, generation-session
mutation or review-custody insertion. Ordinary idle service/reruns do not read
workflows; a valid explicit Preview call is required. Standalone adapters without
an explicit trusted host context provider return `generation_host_unavailable`.

Private semantic/config snapshots and each prepared workflow have budgets of
20,000 JSON nodes and 1,000,000 aggregate string characters, depth 32. Aggregate
prepared workflow serialization is bounded to 8 MiB per plan; exhausted plans
block without issuing a partial actionable Preview. Host file errors are reduced
to `generation_preflight_unavailable`; preflight-row failures use safe blocker
codes. This does not expose filesystem access through MCP.

## Freshness and future review boundary

Configuration and selected file content/signature are read again after
preflight. Changed options or Project path reject the result. Facade semantic
state is compared before/after planning; the trusted bridge additionally compares
the captured and live Project's semantic state before replying. Existing run,
Project identity, session route, target epoch and pairing-generation boundaries
remain in force. Plan identity binds complete core plan content to the originating
Project/session/target/pairing. Project/prompt/Module/config/workflow changes alter
identity; target switches and in-place live changes during preflight reject the
reply. A plan ID is observation identity, never approval or execution authority.

Operation-specific Generation custody and request freshness now live in the
[custody-first slice](agent-generation-review-custody.md). Complete paginated
[human review](agent-generation-review-ui.md) now adds fresh verification and
Reject/Dismiss, separate from Scene Module Swap and with no Start/Apply action.

[Focused tests](../../tests/test_agent_generation_preview.py) cover real planner
and app preparation owners, order/counts/limits, invalid/missing/oversized files,
privacy, Module/prompt/workflow/config freshness, no network or mutation, SDK,
captured paired full-run service and unavailable review requests. The existing
Windows Named Pipe/stdio integration also calls the new Preview through a paired
host context. Generation execution, jobs, adoption and full-suite validation are
outside this slice.
