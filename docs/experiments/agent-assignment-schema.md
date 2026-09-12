# Agent assignment record schema

This schema records one durable experimental record per Astra assignment or
consultation. It is designed for observed orchestration evidence, not internal
token accounting. Unknown or unobserved fields should remain `null` or
`unknown`; they should not be reconstructed from elapsed time or quota.

## Record shape

The following YAML-like shape is illustrative. A future log may use Markdown,
JSON, or another repository-compatible representation, but the field meanings
and ordering rules should remain stable.

```yaml
experiment_id: "#12"
expert_name: Goodall
fresh_or_reused: reused        # fresh | reused
previous_task_domain: "Attribute Group Swap lifecycle"
current_task_domain: "Attribute Group Swap lifecycle"
luna_routing_rationale: "Relevant retained state/widget lifecycle context"
astra_self_reported_relevant_context: "..."
context_match: high            # high | medium | low

task_type: implementation       # consultation | audit | design | implementation | review
lab: "Module and Attribute Authoring"
current_main_sha: "13c3c809e1cc8b8255c907c1399062277ab55f01"
result_outcome: "..."
implementation_commit: "..."
pull_request: "..."

wall_time: "14m28s"
observed_5h_quota_delta: "-12 percentage points"
observed_weekly_quota_delta: "-1 percentage point"
auto_compact:
  occurred: yes               # yes | no | unknown
  relative_timing: before_astra_invocation
orchestration_launch_retry_count: 1
implementation_retry_count: 0
luna_correction: none
manual_human_handoff: no

notes: "..."
protocol_deviations: null
```

## Mandatory fields

Every assignment or consultation record must include:

- `experiment_id` or run identifier;
- `expert_name`, a stable pseudonymous identity such as `Ramanujan`;
- `fresh_or_reused`, either `fresh` or `reused`;
- `previous_task_domain`;
- `current_task_domain`;
- `luna_routing_rationale`;
- `astra_self_reported_relevant_context`;
- `context_match`, rated `high`, `medium`, or `low` after comparison.

`previous_task_domain` may be `null` for a fresh specialist. A reused expert's
self-report must be recorded before current repository refresh. The routing
rationale must be recorded before contacting that expert.

## Operational fields

The following fields are recommended when observable:

- `task_type`: `consultation`, `audit`, `design`, `implementation`, or `review`;
- `lab` or routing group;
- current base/main SHA;
- result or outcome;
- implementation commit and PR when applicable;
- wall time;
- observed 5h quota delta;
- observed weekly quota delta;
- Auto compact occurrence and timing relative to expert invocation;
- orchestration launch retry count;
- implementation retry count;
- Luna correction;
- manual human handoff yes/no;
- notes and protocol deviations.

Quota fields are observations of displayed UI percentages. They may be strings
for phase-wise or reset-window measurements; do not force a simple delta when a
rolling window reset occurred. Do not add token counts, model-internal usage,
or scheduler/accounting claims.

Retry fields distinguish failure classes:

- `orchestration_launch_retry_count`: failed subagent/thread creation before
  implementation began;
- `implementation_retry_count`: a second implementation attempt after work
  began;
- `luna_correction`: any post-handoff correction, or `none` when none occurred.

An unsuccessful launch must not be counted as a second implementation
invocation. Auto compact timing should use an explicit phase-relative value
such as `before_astra_invocation`, `during_astra`, `during_luna`, `after_run`,
`not_observed`, or `unknown`.

## Context-match rubric

`context_match` is task-relative and is assigned only after comparing the
self-report with historical evidence and the current repository:

- **high:** before current-repository inspection, the resumed expert correctly
  identifies the relevant prior responsibility and recalls non-trivial
  constraints, lifecycle behavior, or design reasoning corroborated by
  history;
- **medium:** the expert recalls the general prior area and some useful
  concrete context, but important task detail requires reconstruction;
- **low:** the response is mostly generic, uncertain, or incorrect, or useful
  continuity cannot be established without repository inspection.

This rating is not a model-quality score. A specialist may have high
historical continuity but low match for an unrelated current task.

## Required event ordering

The record must preserve this order:

1. Luna routing rationale is recorded before the Astra response.
2. The reused Astra self-report is captured before current repository refresh.
3. Current evidence is inspected and compared with the self-report.
4. `context_match` is assigned after that comparison.
5. Design or implementation ownership is assigned only after the comparison.

This ordering prevents retrospective routing explanations and memory-probe
contamination.

## Research questions

Over multiple records, this schema can support empirical questions such as:

- Does reused versus fresh status correlate with wall time or observed quota?
- Does `context_match` correlate with task success or correction rate?
- Does same-domain reuse differ from cross-domain reuse?
- Does Luna's routing rationale predict high context match?
- Does continuing design into implementation with the same expert reduce
  repeated discovery work?
- When does stale retained context become harmful?

These are research questions only. Existing observations are too small and
confounded to establish causality, stable quota economics, or universal
orchestration cost.
