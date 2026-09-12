# Agent succession event schema

This schema records one observable succession event for an Astra specialist or
the Luna Landing coordination department. It complements the
[assignment record schema](agent-assignment-schema.md): assignment records
describe who was routed to a task, while succession records describe a
continuity change between context-bearing sessions or generations.

Unknown or unrecovered values remain `null` or `unknown`. The record must not
be used to infer internal token usage, hidden context-window state, scheduler
behavior, or a stable cost of succession.

## Illustrative record shape

The following YAML-like record is fictional and contains no measured run:

```yaml
succession_id: example
succession_type: specialist       # specialist | luna_department
predecessor_id: ExamplePredecessor
successor_id: ExampleSuccessor
lab_or_role: "Example responsibility domain"
reason: "Illustrative continuity boundary"
planned_or_emergency: planned     # planned | emergency | unknown
handoff_package_path: null
handoff_main_sha: null
successor_fresh_or_reused: fresh  # fresh | new_generation | not_applicable
overlap_occurred: unknown         # yes | no | unknown
verification_result: null
known_gaps: []
first_post_handoff_task: null
first_post_handoff_result: null
luna_correction: null
manual_human_intervention: unknown
wall_time_if_observed: null
quota_delta_if_observed: null
handoff_fidelity: not_yet_assessed # optional; separate from context_match
notes: null
protocol_deviations: null
```

## Field meanings

- `succession_id`: stable public identifier for the event or run.
- `succession_type`: `specialist` for an Astra identity change, or
  `luna_department` for a new Luna Landing generation.
- `predecessor_id` and `successor_id`: public expert pseudonyms or Luna
  generation identifiers. Do not store raw platform, thread, or session IDs.
- `lab_or_role`: the durable responsibility domain or coordination role that
  continues across the change.
- `reason`: observable reason for succession, including uncertainty where
  appropriate; do not state an unobserved internal context limit as fact.
- `planned_or_emergency`: whether the handoff was prepared before the limit or
  recovered after a hard interruption.
- `handoff_package_path`: repository-relative path or another durable public
  reference when one exists.
- `handoff_main_sha`: the current `main` SHA recorded when the package was
  prepared, if observable.
- `successor_fresh_or_reused`: use `fresh` for a new specialist pseudonym;
  use `new_generation` for a new Luna department window; use `not_applicable`
  when the event has no such distinction. A successor specialist must not be
  recorded as `reused` merely because it enters the predecessor's lab.
- `overlap_occurred`: whether predecessor and successor were both available
  for a bounded clarification or verification period.
- `verification_result`: concise evidence that package claims were compared
  with current repository state, including material discrepancies.
- `known_gaps`: missing, stale, disputed, or unrecoverable information.
- `first_post_handoff_task` and `first_post_handoff_result`: the first bounded
  task after onboarding and its observable result.
- `luna_correction`: a post-handoff correction by Luna, or `none` when none
  occurred and that fact was observed.
- `manual_human_intervention`: whether a person had to transfer context,
  resolve a discrepancy, or otherwise intervene.
- `wall_time_if_observed`: elapsed wall time only when measured and attributable
  to the recorded event.
- `quota_delta_if_observed`: displayed quota observation, including a
  phase-wise/reset-window description when a simple delta would mislead.
- `handoff_fidelity`: optional future observation of successor reconstruction;
  values may be `high`, `medium`, `low`, or `not_yet_assessed`. It is not the
  assignment schema's `context_match` field.
- `notes` and `protocol_deviations`: additional observable facts and departures
  from the planned procedure.

## Identity constraints

For `succession_type: specialist`:

- `predecessor_id` and `successor_id` must be different expert pseudonyms;
- the successor is fresh under the assignment schema;
- its `previous_task_domain` and retained-context self-report are `null`, and
  its `context_match` is `not_applicable`;
- any continuity claim is evaluated through the handoff package and current
  evidence, not same-agent identity reuse.

For `succession_type: luna_department`:

- the durable role remains Luna Landing;
- the predecessor and successor IDs are different generation identifiers;
- the successor generation verifies current `main`, open PR state, and the
  handoff package before becoming authoritative;
- no raw platform/session identifier is published.

## Recording order

When the event is planned, record the reason and predecessor state before
contacting or creating the successor. Then record the package and current
`main` SHA, create the new identity or generation, and capture the successor's
initial uncertainties. Refresh current repository state, compare it with the
package, record discrepancies and verification, and only then record the
first post-handoff ownership/result.

For an emergency event, preserve the same ordering as far as observable and
mark the missing steps in `known_gaps` or `protocol_deviations`. Do not rewrite
an emergency event as a planned handoff after the fact.

## Evidence and interpretation limits

This schema is for empirical continuity records. A recorded wall time or
displayed quota change is an observation of that run, not a per-model or
per-phase accounting result unless phases were explicitly observed. A compact,
failed spawn, correction, or manual intervention may be a confounder; none
alone establishes causality, degradation, or stable orchestration cost.
