# Agent assignment record schema

This schema records one durable experimental record per Astra assignment or
consultation. It is designed for observed orchestration evidence, not internal
token accounting. Unknown or unobserved fields should remain `null` or
`unknown`; they should not be reconstructed from elapsed time or quota.

Continuity changes between specialist identities or Luna generations are
recorded separately in the [agent succession event schema](agent-succession-schema.md).

## Record shape

The following YAML-like shape is illustrative. A future log may use Markdown,
JSON, or another repository-compatible representation, but the field meanings
and ordering rules should remain stable.

```yaml
experiment_id: example
expert_name: ExampleSpecialist
fresh_or_reused: fresh          # fresh | reused
previous_task_domain: null
current_task_domain: "bounded design consultation"
luna_routing_rationale: "Illustrative routing rationale recorded before contact"
astra_self_reported_relevant_context: null
context_match: not_applicable   # not_applicable for fresh; high | medium | low for reused

task_type: consultation         # consultation | audit | design | implementation | review
lab: "Example Lab"
current_main_sha: null
result_outcome: null
implementation_commit: null
pull_request: null

wall_time: null
observed_5h_quota_delta: null
observed_weekly_quota_delta: null
auto_compact:
  occurred: unknown           # yes | no | unknown
  relative_timing: unknown
orchestration_launch_retry_count: 0
implementation_retry_count: 0
luna_correction: null
manual_human_handoff: unknown

notes: null
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
- `context_match`: `high`, `medium`, or `low` after comparison for a reused
  expert; `not_applicable` for a fresh expert.

For a fresh specialist, `previous_task_domain` and
`astra_self_reported_relevant_context` are `null`, and `context_match` is
`not_applicable`. A reused expert's self-report must be recorded before the
current repository refresh. The routing rationale must be recorded before
contacting either a fresh or reused expert.

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

`context_match` applies only to reused experts. A fresh expert has no previous
agent history to match, so its value is `not_applicable`. For a reused expert,
the rating is task-relative and is assigned only after comparing the self-report
with historical evidence and the current repository:

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

1. Luna routing rationale is recorded before contacting either a fresh or reused
   Astra.
2. For reused Astra only, the pre-refresh retained-context probe and
   self-report are captured before current repository refresh. A fresh Astra
   has no prior-context probe: use `null` for its previous task domain and
   self-report, and `not_applicable` for `context_match`.
3. For reused Astra only, current evidence is inspected and compared with the
   self-report.
4. For reused Astra only, `context_match` is assigned after that comparison.
5. Design or implementation ownership is assigned only after the applicable
   comparison.

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
