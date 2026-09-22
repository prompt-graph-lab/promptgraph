# Coding-agent throughput experiments

Measurement window: September 2026.

This log records empirical observations from this repository and these
development sessions. It does not make claims about stable OpenAI pricing,
token accounting, model-internal token usage, or general model performance.
Subscription usage accounting may change over time. Percentages below are
observed UI quota deltas, not measured tokens. Some runs contain known
experimental noise; those runs are marked explicitly.

The `start/end` values preserve the UI's displayed `5h / weekly` percentage
pair where it was recorded. A delta is the observed change shown for that run.
These values are useful for comparing this experiment series, with the limits
described above.

## Why this log exists

The purpose of this document is to guide future PromptGraph agent
orchestration and preserve evidence instead of relying on conversational
memory. It records the shape of the work, the validation split, and the
observed UI deltas so later sessions can compare a concrete repository history
with their own results.

The current operational baseline extracted from the successful Round 6 flow is
maintained separately in the [Astra-MSC orchestration
protocol](../operations/astra-msc-orchestration-protocol.md). This experiment
log remains the authority for historical observations and does not replace the
protocol's distinction between stable operating gates, provisional procedures,
and historical-only recovery paths.

## Effort terminology

Use these effort labels consistently in this log:

- low = 軽
- medium = 中
- high = 高
- xhigh = 極高
- max = 最大
- ultra = ウルトラ

Older experiment notes sometimes used “Luna Max” colloquially for the normal
long-running coordinator configuration that was actually Luna xHigh. Those
historical coordinator references are corrected to Luna xHigh below. This
correction does not rewrite genuine max effort levels, explicit
thinking=max experiments, or generic descriptions of possible effort levels.

## Unresolved G2 Max/Medium observation

The fresh G2 creation explicitly requested model=gpt-5.6-luna and
thinking=max. The human UI displayed GPT-5.6 Luna and 中 / Medium. Current
thread metadata did not expose the effective reasoning effort, normalized
effort, or fallback/default information.

The repository-local public promptgraph checkout contained no Codex config that
explained Medium. The applicable user-level Codex config contained
model_reasoning_effort = "xhigh". This observation remains unresolved. It
must not be explained away as the historical Luna Max/xHigh terminology
correction: requested effort, effective effort, and human UI display remain
separate observations.

## Repository provenance requirement

A task prompt naming a repository or SHA is not sufficient evidence that a
worker actually inspected that repository. Before an agent experiment or
architecture/implementation task, record or verify:

- Codex Project identity;
- authoritative local repository/workspace;
- branch;
- HEAD SHA;
- whether the worker inherited the parent Project/workspace;
- any remote or GitHub access path used instead; and
- whether legacy or secondary repositories were inspected.

Current repository/runtime evidence outranks an agent's self-reported
repository SHA. Internal subagents may inherit the parent environment unless a
different target is explicitly and verifiably provided.

## Beauvoir pilot status

The first real-task internal Astra run using Beauvoir is an INVALID benchmark
candidate / pilot:

- internal Astra name: Beauvoir;
- fresh Astra Low;
- the architecture task completed;
- the attached execution environment was promptgraph-pro;
- inspection of public promptgraph was not verifiable;
- the reported public SHA appeared only in self-report; and
- classification: MIXED_OR_CONFOUNDED.

Its substantive result must not be used as evidence of current public
PromptGraph behavior and must not be compared with the future external
candidate as the real topology A/B result. Retain operational observations
only where they are already known, label missing measurements explicitly, and
do not invent a quota delta for Beauvoir.

## Active coordination baseline

The active/new HQ is Luna研究推進部 本部 G2.

- Codex Project: public promptgraph;
- primary authoritative repository: prompt-graph-lab/promptgraph;
- promptgraph-pro and other visible sibling/secondary sources are reference
  material only; and
- current-behavior investigations use public promptgraph. Legacy repositories
  are not used unless historical comparison is explicitly requested.

The G2 bootstrap verified the promptgraph repository, branch main, and
repository provenance. The working tree had a pre-existing untracked
.editor_settings.json; that file is not part of these documentation changes
and must not be touched.

For this documentation update, refreshed origin/main and the feature base at
the start of editing were 3c7597a75a352416fe31d707e1b08d3c008f72c5.

## Fresh external-thread target capability

The observed create_thread capability supports fresh project-backed threads
only for exposed or registered Codex Project targets. Observed target
categories included:

- registered project;
- projectless; and
- chatgptWorkCloud.

A fresh external Astra can therefore receive equivalent repository access for
the future topology A/B once both candidates use the same registered public
promptgraph Project. The thread API does not expose arbitrary repository
registration or binding; project registration was performed through the human
UI.

## ASTRA-MSC Round 3 postmortem correction

The full chronology and the later branch-semantics audit are recorded in
[`Astra-MSC Worktree and branch-attachment postmortem`](astra-msc-worktree-branch-postmortem.md).
The section below preserves the original Round 3 evidence while qualifying its
initial readiness interpretation.

Round 3 remains **TERMINAL-BLOCKED / PROTOCOL-DEVIATED**. No valid three-way
blind implementation ranking was completed. The recovered human-visible Codex
UI evidence corrects the earlier coordinator-facing interpretation of the
Fresh Minimal and provisioning-sanity resources.

The earlier records accurately described what the coordinator-facing
list_threads and related inspection APIs exposed during their bounded checks.
They must not be read as proof that the underlying thread or Worktree did not
exist. The durable distinction is:

- **not observable through the coordinator-facing API at the time**; versus
- **directly shown later in the human-visible UI or in the worker's own
  preflight report**.

### Recovered Fresh-resource evidence

The three resources below were supplied as human-visible postmortem evidence.
They all used the public PromptGraph repository and
b62a8db837422d6151c28882e66111d8c406c8f5 as the intended base.

| Resource | Coordinator-facing observation | Recovered human-visible / worker evidence | Result |
| --- | --- | --- | --- |
| MSC-R3-M9Q6 / experiment/r3-m9q6 | No matching real thread or Worktree was exposed during the bounded inspection | Thread and Worktree existed; origin and base were correct; Worktree was clean but on detached HEAD, with the expected branch not checked out | Worker stopped at PROVENANCE_GATE_FAILED; no implementation, tests, diff, commit, or push |
| MSC-R3-T6H3 / experiment/r3-t6h3 | No matching real thread or Worktree was exposed during the bounded inspection | Thread and Worktree existed; origin and base were correct; Worktree was clean but on detached HEAD, with the expected branch not checked out | Worker stopped at the provenance gate; no implementation, tests, diff, commit, or push |
| sanity-q4m7 / experiment/sanity-q4m7 | No matching real thread or Worktree was exposed during approximately 80 seconds of bounded polling | Neutral-bootstrap sanity thread and Worktree existed; origin and base were correct; Worktree was clean but on detached HEAD | No implementation or file change occurred; readiness was not achieved |

For M9Q6 and T6H3, the expected local branch refs were later observed at
the correct base SHA, but the corresponding Worktrees remained detached rather
than attached to those branches. The same branch-ref-versus-detached-Worktree
shape was observed for sanity-q4m7. These are separate observations of
repository state; they do not expose the private provisioning mechanism.

The directly observed state for these Fresh resources was a mismatch with the
then-required project-local readiness protocol: the worker reached a Worktree
with the correct repository, origin, base, and clean state, but not with the
required expected branch checked out. A separate observability discrepancy
existed because the human-visible UI exposed resources that the
coordinator-facing thread/list APIs did not expose at the time. Later evidence
showed that detached HEAD can be a normal initial state for at least one
Codex Managed Worktree path, so this state is not by itself proof of a platform
provisioning failure.

### Experimental consequence

The two Fresh Minimal executions reached pre-implementation provenance checks
and stopped before implementation. Their implementation_retry_count remains
zero; the orchestration/provisioning history remains recorded separately.
Fresh Minimal must not be ranked as a third implementation candidate or as a
quality NO-GO result.

The completed Round 3 results remain preserved:

- Fresh Handoff: experiment/r3-k4n8 at
  7d2fcef2737f23b6db58d0451e425addd9557b59; implementation completed, with
  the previously recorded information-condition deviation.
- Warm Persistent: experiment/r3-p7w2 at
  da9ef79cdac0290bfb266fb16850b47e6bbbaf25; implementation completed, but
  the retained-context probe body is unrecoverable, so no clean
  context_match is assigned.

### Interpretation limits and readiness recommendation

The three resources provide direct evidence of repeated detached-Worktree
states under the then-used readiness protocol and a coordinator-API visibility
discrepancy. The later forensic audit classified branch behavior as
**MIXED SEMANTICS / CONTEXT-DEPENDENT**: detached HEAD is normal for at least
one Managed Worktree path, while successful Astra-MSC runs also used explicit
worker-side or coordinator-side branch setup. The evidence does not establish
a race condition, registry saturation, thread or Worktree limit, resource
exhaustion, indexing bug, or any other private backend mechanism. Accumulated
resources, eventual consistency, provisioning degradation, and API visibility
limitations remain hypotheses.

Before sending implementation work to a newly provisioned Fresh project-local
Astra, use the staged protocol in the operations guidance: first verify thread,
Worktree, origin, exact base, clean state, and isolation; then explicitly create
and attach the deterministic experiment branch from that verified base when a
named branch is required; then verify the named branch, non-detached HEAD,
intended base, clean state, and isolation before task delivery. A detached HEAD
is permitted during the initial stage when that path creates Managed Worktrees
detached. Missing named-branch attachment is a setup failure only after the
explicit branch-setup stage for a protocol that requires it. Do not ask the
candidate to repair its own provisioning as part of the experimental task.
This is an operational recommendation, not a claim about platform internals.

### Current Fresh thread addressability qualification

A separate A2 reproduction on 2026-09-18 tested Fresh thread identity without
implementation work. It confirmed a **DIRECT_ADDRESSABLE_DISCOVERY_GAP** for
that resource: the resolved durable identity was readable and accepted one
follow-up probe, while a valid `list_threads` result omitted the resource.

This does not change the Round 3 **TERMINAL-BLOCKED / PROTOCOL-DEVIATED**
classification and does not establish Round 4 success. It adds a provisional
operational qualification: `list_threads` visibility must be recorded
separately from direct thread addressability, and a read-only local binding
fallback may be used only as a compatibility measure when supported discovery
does not expose the Fresh identity. The fallback is not a stable API contract.
The detailed staged procedure is maintained in
[`docs/operations/chat-codex-handoff.md`](../operations/chat-codex-handoff.md),
and the incident-specific follow-up is recorded in the
[`Astra-MSC Worktree and branch-attachment postmortem`](astra-msc-worktree-branch-postmortem.md).

## Astra-MSC Round 4 closeout — incomplete three-arm experiment

Round 4 used the exact frozen base
`bc9b1d44863ebb36edf9e4ffe4270f4bff5a25a0` and was intended to retry the
three-arm Round 3 comparison. It is closed as:

**INCOMPLETE / NO_VALID_THREE_ARM_RANKING**

Two Fresh candidates completed valid implementations from the frozen base.
Their branches, commits, Worktrees, implementation evidence, and focused
validation results remain preserved for later forensic or qualitative review.
The candidate-to-condition mapping remains withheld from this public record and
from blind ranking. The two neutral validation records were:

- one focused run: 30 passed with 40 subtests;
- one focused run: 32 tests, `OK`.

Those Fresh results are not included in an Astra-MSC quality ranking because the
Warm arm did not reach implementation.

The Warm arm is recorded on two independent axes:

- **Conversation/context:** `CONTAMINATED`. The retained-context memory-probe
  response was present in durable rollout persistence but omitted from the
  coordinator-facing `read_thread` projection. Separately, an unintended human
  message was persisted, its turn began and was interrupted, and no assistant
  output from that accidental turn was observed in persistence.
- **Execution environment:** `ENVIRONMENT_STALE`. The canonical Warm thread
  pointed to the missing `6db4` Worktree path, while the historical Round 3
  Warm Worktree remained separately registered and clean at `a2f8` on
  `experiment/r3-p7w2` at `da9ef79cdac0290bfb266fb16850b47e6bbbaf25`.

Warm implementation quality was **NOT OBSERVED**. The Warm outcome is an
orchestration and experimental-integrity failure, not a quality failure. The
canonical Warm conversation and historical Worktree are preserved as forensic
evidence; this closeout does not repair the stale binding, edit or delete the
accidental turn, create a successor, or attach a new Worktree.

Round 4 is therefore not added to the Round 1/2 quality averages. The retained
averages remain based on `n=2`. No three-way ranking, candidate reveal, or
implementation merge was performed.

### Follow-up: rebind, fork, and manual edit evidence

The post-Round 4 disposable probes further narrowed the available recovery
paths for the historical Warm lineage. An existing disposable conversation was
not rebound to an explicitly selected manually created Worktree #2. The
available supported surfaces established only the following bounded result:

**AMBIGUOUS_SUPPORTED_SURFACE**

`create_thread` creates a new resource, `send_message_to_thread` changes
conversation activity, and `handoff_thread` did not expose an arbitrary target
Worktree identity or path for this probe. This does not establish that arbitrary
rebind is impossible; it establishes only that an explicit supported
arbitrary-target rebind surface was not demonstrated.

The tested ordinary `fork_thread` surface produced a distinct child conversation
and Worktree, but exposed no historical fork-point selector. The child inherited
both pre-fork and post-marker history, so the observed result was:

**LATEST_STATE_FORK_ONLY**

This does not establish that every UI or private surface lacks historical fork
selection. It records the behavior of the supported surface tested here.

A human UI edit of the accidental Warm message produced a new visible
conversation branch. The resulting Astra response recalled the required Round 3
context and reported no memory of the replaced message or later old-branch
content. However, the forensic audit found no distinct successor durable ID or
successor-specific client identifier; the edited rollout remained associated
with the original durable thread and its missing `6db4` cwd. The original
lineage still retained the accidental message and interrupted turn. The
classification is therefore:

**MANUAL EDIT-BRANCH ISOLATION: INSUFFICIENT_EVIDENCE**

The UI observation is useful evidence about the model-visible conversational
path, but it does not establish an independently addressable clean experimental
resource. The execution classification remains:

**SUCCESSOR_ENVIRONMENT_MISSING**

These findings do not alter the Round 4 closeout or create a valid Warm arm.
They imply only that a future Warm v2 should be designed as a new seed lineage,
with its conversation identity and bound execution environment created and
verified together. It should not be called persistent at creation time, and
the Round 5 design was outside the scope of this Round 4 recovery record; the
formal Round 5 closeout is recorded below.

## Astra-MSC Round 5 formal closeout — Warm v2 Seed round

Round 5 was a **WARM_V2_SEED_ROUND**, not a valid three-way Persistent Warm
comparison. The round was formally closed after the blind Fresh review was
frozen and the sealed condition mapping was revealed. It remains separate from
the product-code integration decision described below.

### Authoritative state and execution record

The round used the frozen base
`361b95d05e243eee6050754fe34263d7f6ce2c27`. The merged PR #62 recovery and
manual-edit documentation was present in `origin/main` before closeout, and
the active resource registry was Issue [#63](https://github.com/prompt-graph-lab/promptgraph/issues/63).

Three valid implementations were produced. Each passed the Fresh Worktree
Stage 1/2/3 gates, used the same frozen base, completed one implementation
commit, pushed a matching remote branch, and changed only:

- `app.py`;
- `core/gallery_variant_promotion.py`; and
- `tests/test_gallery_variant_promotion_preparation.py`.

The neutral execution records were:

| Candidate | Branch | Commit | PR |
| --- | --- | --- | --- |
| A | `experiment/r5-k7m4` | `e4f65fb5d541db5aef609d1eaf546cc92403cfd2` | [#66](https://github.com/prompt-graph-lab/promptgraph/pull/66) |
| B | `experiment/r5-p2x8` | `26c496ff7a4fdbdbc6f3bf2818718020881b11c3` | [#64](https://github.com/prompt-graph-lab/promptgraph/pull/64) |
| C | `experiment/r5-v9q3` | `04e9ae6edde463a2bade7fb3aa996a84f74011f4` | [#65](https://github.com/prompt-graph-lab/promptgraph/pull/65) |

The different focused-test counts are validation facts, not a quality score.
All three candidates received a neutral technical review classification of
`NO_FINDING`; no observed correctness defect was identified. Full-suite and
live-UI validation were not run in this review.

### Blindness accounting

The correct accounting is:

```text
THREE_ARM_CONDITION_BLINDNESS: PARTIALLY_COMPROMISED_BY_LIFECYCLE_METADATA
FRESH_PAIR_CONDITION_BLINDNESS: PRESERVED_THROUGH_FROZEN_COMPARISON
WORKER_MAPPING_EXPOSURE: NO
WORKER_CONTAMINATION: NO
```

The earlier execution report identified Candidate C as the neutral protected
candidate. Because the Warm v2 Seed was the only resource intended for
long-lived protection, an informed reviewer could infer Candidate C's
lifecycle role. This did not expose the Minimal/Handoff identities of
Candidates A/B, and it is not evidence of worker contamination or an
implementation-quality effect.

The Fresh-only comparison was finalized before the mapping reveal and must be
treated as frozen evidence. It used neutral labels and no numeric score:

- **Fresh Candidate X:** the narrower helper extraction, with the existing
  app-side normalizer retained; 31 focused tests passed and no unresolved
  correctness defect was identified.
- **Fresh Candidate Y:** helper extraction plus centralization of the
  main-sequence normalizer and its existing caller import; 38 focused tests
  plus 10 candidate-inspection tests passed and no unresolved correctness
  defect was identified.

The observed difference is normalizer ownership and scope breadth, not a
demonstrated behavioral failure. No Fresh candidate was ranked as superior.

### Revealed mapping and Fresh observation

After the Fresh-only comparison was frozen, the sealed mapping was revealed:

```text
Candidate A -> Fresh Minimal
Candidate B -> Fresh Handoff
Candidate C -> Warm v2 Seed

Fresh Candidate X -> Candidate B -> Fresh Handoff
Fresh Candidate Y -> Candidate A -> Fresh Minimal
```

The resulting Fresh observation is descriptive only:

- **Fresh Minimal / Candidate A** performed the helper extraction and also
  centralized main-sequence normalizer ownership into core, giving it broader
  task-adjacent scope.
- **Fresh Handoff / Candidate B** performed the narrowest helper extraction,
  retained the existing app-side normalizer, and duplicated equivalent reset
  semantics in the new helper.

This single Round 5 observation does not establish that either condition
caused the observed scope difference or that either condition was superior.
It is not added to the historical three-way ranking averages.

### Warm v2 Seed record

Candidate C is classified only as:

**WARM_V2_SEED_EVIDENCE_ONLY**

It is not a Persistent Warm performance observation. The protected lineage was
recorded in Issue #63 after the Fresh-only blind comparison had been frozen:

- durable thread: `01a0b28e-6056-7d80-817a-5edd47b21820`;
- client thread: `client-new-thread:2dba4d1b-db3b-47e1-8940-0e5bf1f0e768`;
- Worktree: `C:\Users\monid\.codex\worktrees\6268\promptgraph`;
- branch: `experiment/r5-v9q3`;
- commit: `04e9ae6edde463a2bade7fb3aa996a84f74011f4`;
- PR: [#65](https://github.com/prompt-graph-lab/promptgraph/pull/65).

At closeout, the conversation was readable and preserved, the Worktree was
registered and clean, the recorded branch and commit remained present, and the
remote branch was preserved. Issue #63 records:

```text
lineage: WARM_V2
phase: SEED
protection: PROTECTED_WARM_V2
```

Round 6 was the first round in which this lineage could become
`WARM_V2_PERSISTENT`. That classification required, and passed, the retained-
context and execution-environment gates. No rebind, Worktree switch, or repair
was implied by this transition.

### Historical accounting

Round 6 was eligible for the historical three-way ranking: execution validity
and mapping integrity remained intact through the frozen blind review, and the
condition mapping was revealed only after the review was finalized. The
condition ranks are recorded descriptively below; they are not causal evidence
about topology.

| Round | Fresh Minimal | Fresh Handoff | Warm | Classification |
| --- | ---: | ---: | ---: | --- |
| 1 | 3 | 1 | 2 | valid three-way ranking |
| 2 | 1 | 2 | 3 | valid three-way ranking |
| 3 | not ranked | not ranked | not ranked | `TERMINAL-BLOCKED / PROTOCOL-DEVIATED` |
| 4 | not ranked | not ranked | not ranked | `INCOMPLETE / NO_VALID_THREE_ARM_RANKING` |
| 5 | seed only | seed only | seed only | `WARM_V2_SEED_ROUND` |
| 6 | 2 | 3 | 1 | valid three-way ranking |
| 7 | 2 | 1 | 3 | valid with recorded external interruption |

Across the four valid ranked rounds (`n=4`), the simple average rank is:

- Fresh Minimal: `(3 + 1 + 2 + 2) / 4 = 2.0`;
- Fresh Handoff: `(1 + 2 + 3 + 1) / 4 = 1.75`;
- Warm: `(2 + 3 + 1 + 3) / 4 = 2.25`.

The Warm aggregate spans two persistent lineages: Warm v1 in Rounds 1–2 and
Warm v2 Persistent in Rounds 6–7. It is therefore a descriptive aggregate
across lineages, not evidence that persistence or lineage caused any rank.

Round 3, Round 4, and the Round 5 Seed result remain excluded from this ranked
average. Round 5 remains seed evidence only; it is not a Persistent Warm
performance observation.

### Astra-MSC Round 6 reveal

Round 6 used the frozen base
`4c355707e35a00c0a5c2ec2eb5ef358a84777c88` and the bounded embedded ComfyUI
workflow source-selection extraction task. The blind review was frozen before
the sealed mapping was revealed, and the ranking did not change after reveal:

```text
Candidate A -> Fresh Handoff
Candidate B -> Fresh Minimal
Candidate C -> Warm v2 Persistent
```

The resulting condition ranking was:

1. Warm v2 Persistent (Candidate C);
2. Fresh Minimal (Candidate B);
3. Fresh Handoff (Candidate A).

Candidate C had no observed correctness finding. Candidate B had no observed
correctness finding; its remaining notes concern pure-core API shape. Candidate
A had a concrete repository test-integration regression: the unchanged
`tests/test_app_extracted_prompt_integration.py` AST harness failed `1 failed,
6 passed` with `NameError: name 'select_embedded_workflow_source' is not
defined` because its import allowlist did not include the new core module.
This is classified as `TEST_INTEGRATION_REGRESSION` and
`VALIDATION_COVERAGE_GAP`, not as an observed application-runtime regression.
Candidate A's branch was not modified or repaired during the reveal.

The Warm v2 Persistent observation remained valid: retained Round 5 history,
the same durable conversation identity, the same bound Worktree, and the
post-transition repository/origin/base/clean-state gates were independently
verified. No worker received the condition mapping before reveal.

### Product-code integration boundary

Product-code selection is separate from experiment-condition interpretation.
The current technical integration observations are:

- [PR #64](https://github.com/prompt-graph-lab/promptgraph/pull/64) is the
  narrowest viable extraction, with overlapping normalizer semantics as a
  follow-up consideration.
- [PR #65](https://github.com/prompt-graph-lab/promptgraph/pull/65) is viable
  but retains duplicate normalizer ownership; it also carries the protected
  Warm v2 Seed artifact and must not be cleaned up as part of product
  integration.
- [PR #66](https://github.com/prompt-graph-lab/promptgraph/pull/66) is viable,
  centralizes normalizer ownership in core, and is broader than the minimum
  extraction while remaining coherent.

PR #66 is the leading product-code integration candidate because it leaves the
cleanest single normalizer ownership. This is a product integration preference,
not an experiment ranking. PR #66 was subsequently merged separately; the
Round 6 candidate review does not select product code by experiment rank.

### Round 6 product boundary and registry state

Candidate A requires a follow-up correction before product integration because
of the existing integration-test harness regression. Candidates B and C had no
currently identified correctness blocker at reveal. No candidate branch was
modified and no implementation PR was merged during the reveal task.

Issue #63 was updated after reveal to record the protected Warm v2 resource as
`phase: PERSISTENT`, `round: 6`, with the Round 6 branch and commit. Its
conversation, same Worktree, Round 5 evidence, Round 6 evidence, and remote
refs remain preserved. The resource is not cleanup-eligible.

### Astra-MSC Round 7 result and post-merge boundary

Round 7 used the frozen base
`dbba98fd537cc8c399c9a51a6a763c631453dec2` and the bounded Project Save As
overwrite snapshot/freshness preparation task. The experiment crossed the
`POST_2026_09_19_CODEX_UPDATE` harness epoch; the directly observed local
version was `codex-cli 0.155.0-alpha.9.2`, while the app-server version was not
observable through the supported local surfaces. The harness epoch is metadata
only and is not interpreted as a quality result or causal explanation.

The three implementation turns were interrupted by the same external weekly
usage-limit error. The interruption was recorded separately from implementation
quality, then all three existing resources resumed from their preserved
working-tree state with one identical resume instruction:

```text
ROUND_7_RANKING_ELIGIBILITY: VALID_WITH_RECORDED_EXTERNAL_INTERRUPTION
EXTERNAL_QUOTA_RESUME_COUNT: 1
IMPLEMENTATION_RETRY_INCREMENT: NO
REPLACEMENT_WORKER: NO
SAME_RESOURCE_RESUME: YES
HARNESS_VERSION_CHANGED_DURING_SUSPENSION: NO
```

The blind review was frozen before the sealed mapping was revealed. The neutral
candidate records and final product-PR state were:

| Candidate | Revealed condition | Branch | Commit | PR / final state |
| --- | --- | --- | --- | --- |
| A | Warm v2 Persistent | `experiment/r7-q6m4` | `de297ed529d5a754bc669dd44c2bf881cefd6823` | [#74](https://github.com/prompt-graph-lab/promptgraph/pull/74), closed non-selected |
| B | Fresh Handoff | `experiment/r7-z2p6` | `b9fe316614ba7830f9d1c582fb2dcf6188e24a9b` | [#75](https://github.com/prompt-graph-lab/promptgraph/pull/75), merged |
| C | Fresh Minimal | `experiment/r7-a8k5` | `64eb8dfbb52e57d5705342bc87aa07a99c87c326` | [#73](https://github.com/prompt-graph-lab/promptgraph/pull/73), closed non-selected |

The frozen blind ranking was:

1. Fresh Handoff (Candidate B);
2. Fresh Minimal (Candidate C);
3. Warm v2 Persistent (Candidate A).

The ranking is descriptive only. The quota interruption/resume was not used as
a ranking criterion, and the result does not establish a causal advantage for
Handoff, Minimal, or Persistent context.

The Warm v2 Persistent observation remained valid. The retained lineage
completed the R5 Seed -> R6 Persistent -> R7 Persistent sequence using the
same durable conversation and the same registered Worktree, with the R5, R6,
and R7 evidence branches and commits preserved. No rebind, replacement,
branch reset, cleanup, or metadata repair occurred.

### Round 7 product integration

Product selection was evaluated independently of the revealed condition and
the experiment ranking. The three implementations preserved the same four
core safety-preparation function bodies and the same app-owned Save As
lifecycle boundary. The selected implementation was [PR #75](https://github.com/prompt-graph-lab/promptgraph/pull/75), because its product-side validation provided the strongest balance of actual `app.py` import-boundary coverage, direct SHA-only freshness characterization, and full-suite validation. It merged into `main` at
`7679e3be9968d032e804be55892d0035f64a78e5`.

PRs #73 and #74 were closed only after #75 merged. Their reviewed commits,
remote branches, Worktrees, conversations, and experiment evidence remain
preserved. Closing non-selected PRs did not authorize experiment-resource
cleanup. Issue [#63](https://github.com/prompt-graph-lab/promptgraph/issues/63)
retains the post-reveal Warm v2 Round 7 registry entry and the post-merge
protection note.

Round 7 is complete. The Round 8 closeout follows below.

### Astra-MSC Round 8 result and closeout

Round 8 used the frozen base
`349f006953f33c3393d773b3f0d6bcb93243ecc0` and the bounded Final Export
target-scope resolution planning task. The directly observed harness version
remained `codex-cli 0.155.0-alpha.9.2`; no app-server version was observable
through the supported local surfaces. The harness version is experiment
metadata only and is not interpreted as a quality result.

The pre-treatment Mapping Epoch 1 was created but lost before any packet was
delivered. All three resources were still treatment-naive, so Epoch 1 was
classified `CREATED_BUT_LOST_BEFORE_TREATMENT / VOID`. A separately randomized
Mapping Epoch 2 was durably written and read back before delivery, remained
sealed through the blind review, and was the only mapping used for treatment.
The mapping recovery was recorded separately from implementation quality.

The three implementation turns were interrupted by the same external usage
limit while broader validation was in progress. The same resources resumed
with one identical short message; no technical packet was resent, no
implementation retry was counted, and no replacement worker was created:

```text
ROUND_8_RANKING_ELIGIBILITY: VALID_WITH_RECORDED_ORCHESTRATION_AND_EXTERNAL_INTERRUPTION
ORCHESTRATION_LAUNCH_RETRY_COUNT: 1
ORCHESTRATION_MAPPING_RECOVERY_COUNT: 1
EXTERNAL_QUOTA_RESUME_COUNT: 1
IMPLEMENTATION_RETRY_INCREMENTED: NO
REPLACEMENT_WORKERS_CREATED: NO
SAME_RESOURCE_RESUME: YES
```

The blind review was frozen before Mapping Epoch 2 was revealed. The final
candidate records were:

| Candidate | Revealed condition | Branch | Commit | PR / final state |
| --- | --- | --- | --- | --- |
| A | Fresh Minimal | `experiment/r8-p4x8` | `67f36960d493023dd3d1deb41cc6495fd4e5a858` | [#78](https://github.com/prompt-graph-lab/promptgraph/pull/78), closed non-selected |
| B | Fresh Handoff | `experiment/r8-n6q2` | `9cf4ab4dbb672791bbc46e5dc156042b3726ff6d` | [#79](https://github.com/prompt-graph-lab/promptgraph/pull/79), merged |
| C | Warm v2 Persistent | `experiment/r8-j7k4` | `91196374cf31a487ed0a971ee9fa3c6bb4a8de39` | [#77](https://github.com/prompt-graph-lab/promptgraph/pull/77), closed non-selected |

The frozen blind ranking was:

1. Candidate B;
2. Candidate A;
3. Candidate C.

The ranking is descriptive only. It does not establish stable superiority,
causal advantage, or a universally best condition. The Round 8 result was
added to the valid ranked-round table:

| Round | Minimal | Handoff | Warm |
| --- | ---: | ---: | ---: |
| R1 | 3 | 1 | 2 |
| R2 | 1 | 2 | 3 |
| R6 | 2 | 3 | 1 |
| R7 | 2 | 1 | 3 |
| R8 | 2 | 1 | 3 |
| **Mean, n=5** | **2.00** | **1.60** | **2.40** |

Round 3 remains excluded as protocol-deviated, Round 4 as incomplete, and
Round 5 as Warm v2 Seed evidence rather than a scored Persistent comparison.
The Warm aggregate spans Warm v1 and Warm v2; R6/R7/R8 are the scored
observations after the Warm v2 Seed lineage began.

The Warm v2 Persistent observation remained valid through Round 8. The
retained lineage completed `R5 Seed -> R6 Persistent -> R7 Persistent -> R8
Persistent` using the same durable conversation and the same registered
Worktree. No rebind, replacement, branch reset, cleanup, or metadata repair
occurred. The resource remains protected for possible future continuation.

### Round 8 product integration and validation

Product selection was evaluated independently of the revealed condition and
the experiment ranking. Luna HQ ran the same common validation sequence
sequentially in each candidate Worktree:

| Candidate | Focused | `-k final_export` | Full pytest | Diff check |
| --- | --- | --- | --- | --- |
| A / [#78](https://github.com/prompt-graph-lab/promptgraph/pull/78) | 31 passed | 169 passed, 1 skipped, 6 subtests | 1470 passed, 9 skipped, 712 subtests | PASS |
| B / [#79](https://github.com/prompt-graph-lab/promptgraph/pull/79) | 31 passed | 315 passed, 1 skipped, 6 subtests | 1616 passed, 9 skipped, 712 subtests | PASS |
| C / [#77](https://github.com/prompt-graph-lab/promptgraph/pull/77) | 31 passed | 50 passed, 1 skipped, 300 subtests | 1351 passed, 9 skipped, 1006 subtests | PASS |

All three candidates passed the common product validation without an observed
correctness blocker. Candidate B was selected for product integration because
it provided the narrowest prepared-input planner boundary: `app.py` retained
preparation, session-anchor selection, and export lifecycle ownership, while
core owned deterministic target planning and reused the existing lower-level
selected-route resolver. This is a product-code decision, not a consequence
of Candidate B's revealed experiment condition or blind rank.

PR #79 was merged by the human at
`1ad221904c8f6f8773ba0bba00c306745d5fed45`. PRs #77 and #78 were closed after
the selected implementation merged. Their reviewed commits, remote branches,
Worktrees, conversations, and experiment evidence remain preserved. Closing
the non-selected PRs did not authorize resource cleanup.

### Round 8 usage observations and limitations

During the three-Astra same-resource resume, the user observed the primary
five-hour allowance near 98% remaining before resume and approximately 22%
remaining after the resumed workers completed validation, commit, push, and
report work. The observed change was approximately 76 percentage points of
remaining allowance. This is an observation only, not a decomposition of cost.
It may include model reasoning, context processing, tool activity, test-output
handling, waiting/status activity, reporting, and other opaque platform
accounting. No precise component cost is inferred.

For the later Luna-owned common validation, direct observations were:

```text
before Candidate A: primary 0% used / weekly 34% used
after Candidate A:  primary 1% used / weekly 34% used
after Candidate B:  primary 2% used / weekly 34% used
after Candidate C:  primary 2% used / weekly 34% used
```

This supports investigating whether long-running Astra turns and repeated
model/tool interaction are operationally more expensive than coordinator-owned
test execution. It does not prove an internal billing, quota, context, or
token-accounting mechanism, and it does not alter the historical ranking.

Round 8 is complete. The next work starts from post-#79 `main`; no next round
is started implicitly by this closeout.

### Astra-MSC Phase 2: Fresh Context Efficiency — Round 9

Round 9 begins a separate two-arm observation series. It is not appended to
the Phase 1 three-arm arithmetic means or to the historical Warm averages.

```text
ASTRA_MSC_PHASE_2: FRESH_CONTEXT_EFFICIENCY
PHASE_2_VALID_ROUNDS: 1
ROUND_9_TASK: Project directory duplication preflight planning
ROUND_9_FROZEN_BASE: bf1db72d2cca791d6b195de4eac6e32c725c35c2
ROUND_9_VALID_EXECUTION: ATTEMPT_4
```

The first three launch attempts were orchestration findings rather than
implementation failures:

- Attempt 1: `INVALID_PREIMPLEMENTATION_INTERNAL_TOPOLOGY`. The supported
  internal multi-agent surface could not prebind an isolated Worktree/cwd and
  did not provide complete task token, rollout, and Worktree evidence.
- Attempt 2: `INVALID_PREIMPLEMENTATION_OVERCONSTRAINED_PREBIND_GATE`. A
  correctly isolated external managed Worktree at detached exact-base HEAD was
  initially rejected by an over-constrained prebind requirement.
- Attempt 3: `PROVISIONING_CAPABILITY_DISCOVERY_ONLY`. The supported external
  creation surface atomically creates the resource and first model turn; it
  does not expose a zero-turn paused setup stage.
- Attempt 4: `VALID`. The worker performed the identical environment gate in
  its first turn, used detached exact-base HEAD as the isolation boundary, and
  pushed its single implementation commit to a pre-created neutral remote
  evidence ref.

The revealed mapping and frozen technical assessment were:

- Candidate A: `FRESH_HANDOFF`
- Candidate B: `FRESH_MINIMAL`
- blind quality: Candidate B > Candidate A
- correctness blockers: none
- product preference: Candidate B, frozen before treatment/cost reveal and
  justified by planner ownership/API boundary and common validation

Coordinator-owned common validation passed for both candidates. Candidate A
completed with 1,635 passed, 9 skipped, and 2,038 subtests; Candidate B
completed with 1,899 passed, 9 skipped, and 712 subtests. Both diff checks
passed. PR #82 was selected for product integration and merged at
`82af9c339f8c2114d4e2e1dd4548f19538898fd5`; PR #81 was closed without merge.
The candidate branches, commits, Worktrees, and experiment evidence remain
preserved.

The task-window token evidence used the final cumulative `turn_token_usage`
record for each single worker task turn:

| Condition | Input | Cached input | Uncached input | Output | Reasoning output | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fresh Minimal | 717,376 | 628,608 | 88,768 | 9,374 | 1,142 | 726,750 |
| Fresh Handoff | 1,174,819 | 1,120,512 | 54,307 | 12,327 | 1,828 | 1,187,146 |

The Handoff-minus-Minimal difference was `+460,396` total tokens, or
`1.6335x` / `+63.35%` relative to Minimal. Handoff had `34,461` fewer
uncached input tokens but substantially higher cumulative input and total
tokens. This is a hypothesis-generating accounting observation; it does not
establish that handoff context causes higher usage.

Directly observed worker activity was also higher for Handoff in this
realization:

- rollout-level custom tool calls: Minimal 13, Handoff 19;
- nested shell/command invocations: Minimal 14, Handoff 21;
- test commands: Minimal 1, Handoff 2;
- observed worker wall time: Minimal 399.061 seconds, Handoff 458.892
  seconds.

Repository-search calls, file-read counts, and distinct-file counts were not
normalized reliably from the compound shell records and remain unknown. The
visible common packet was 2,096 bytes (rough heuristic 524 tokens), and the
additional Handoff layer was 1,485 bytes (rough heuristic 372 tokens). The
heuristic sizes are not actual model tokenization.

The descriptive Round 9 cost result is:

```text
ROUND_9_COST_RESULT: MINIMAL_LOWER_TOTAL_COST
ROUND_9_OBSERVED_ALIGNMENT: QUALITY_AND_COST_FAVOR_SAME_CONDITION
ROUND_9_CAUSAL_CLAIM: NOT_ESTABLISHED
PHASE_2_CURRENT_EVIDENCE: ONE_VALID_ROUND
PHASE_2_OPERATIONAL_DEFAULT: NOT_YET_DECIDED
PHASE_2_MORE_ROUNDS_REQUIRED: YES
```

Round 9 therefore provides one observation in which Fresh Minimal was both
the lower-total-token condition and the condition assigned to the higher-rated
candidate. This is not evidence of universal superiority. At least three
valid Phase 2 rounds are recommended before an operational default decision,
with five preferred if task supply and quota permit.

## Future topology A/B gate

Before the next internal-vs-external Astra comparison begins task execution,
verify all of the following:

- same Codex Project;
- same authoritative repository;
- same branch/base SHA;
- same task prompt;
- fresh Astra;
- same explicit Astra reasoning effort;
- same Fast condition; and
- no access to the other candidate's result.

The Beauvoir pilot does not satisfy this gate.

## GitHub record

On 2026-09-10, GitHub metadata was checked for the listed PRs. PRs #17 through
#25 and #27 through #32 were reported as merged into `main`; the local
`origin/main` was fetched through the PR #32 merge commit. GitHub PR metadata
does not contain the interactive quota observations, so the values below are
retained from the development-session record rather than replaced with empty
or inferred values.

## Measured run comparison

| Run / phase | Model and work shape | Start/end (`5h / weekly`) | 5h delta | Weekly delta | Wall time | Validation or note |
| --- | --- | --- | --- | --- | --- | --- |
| [PR #17](https://github.com/prompt-graph-lab/promptgraph/pull/17) | Astra standalone; download phase | not recorded | -27% | -5% | 8m30s | single-boundary run |
| [PR #18](https://github.com/prompt-graph-lab/promptgraph/pull/18) | Astra standalone; image-download owner | not recorded | -18% | -2% | 6m26s | single-boundary run |
| [PR #19](https://github.com/prompt-graph-lab/promptgraph/pull/19) | Astra standalone; unique-save-path characterization | not recorded | -18% | -3% | 6m05s | single-boundary run |
| [PR #20](https://github.com/prompt-graph-lab/promptgraph/pull/20) | Astra standalone; final-output-event characterization | not recorded | -20% | -3% | 6m07s | single-boundary run |
| [PR #21](https://github.com/prompt-graph-lab/promptgraph/pull/21) | Astra standalone; final-event ownership review | not recorded | -26% | -4% | 6m01s | single-boundary run |
| [PR #22](https://github.com/prompt-graph-lab/promptgraph/pull/22) | Astra standalone; history-fetch owner | not recorded | -27% | -4% | 6m13s | single-boundary run |
| [PR #23](https://github.com/prompt-graph-lab/promptgraph/pull/23) | Astra standalone; receive-lifecycle ownership review | not recorded | -31% | -5% | 6m04s | single-boundary run |
| [PR #24](https://github.com/prompt-graph-lab/promptgraph/pull/24) | Astra Low; 3 related ComfyUI boundaries | 100/43 → 63/37 | -37% | -6% | 7m26s | 1085 passed / 8 skipped / 552 subtests / ~242.05s full suite |
| [PR #25](https://github.com/prompt-graph-lab/promptgraph/pull/25) | Astra Low; 5 related ComfyUI utility boundaries | 63/37 → 22/31 | -41% | -6% | 7m55s | 1089 passed / 8 skipped / 552 subtests / 240.79s full suite |
| [PR #27](https://github.com/prompt-graph-lab/promptgraph/pull/27) Astra | Astra Low; Candidate/Gallery inspection cluster | 100/31 → 68/26 | -32% | -5% | 4m10s | focused tests only; 21 helpers; ~10 old-micro-PR-equivalent boundaries |
| [PR #27](https://github.com/prompt-graph-lab/promptgraph/pull/27) Luna | Luna xHigh Fast; landing and delivery phase | 68/26 → 66/25 | -2% | -1% | 5m54s | broader/full validation, docs, review, push, PR; 1099 passed / 8 skipped / 552 subtests / 241.53s |
| [PR #27](https://github.com/prompt-graph-lab/promptgraph/pull/27) combined | Astra implementation plus Luna landing | 100/31 → 66/25 | -34% | -6% | 10m04s | sequential total |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) Astra | Astra Low; batch-edit preview cluster | 66/25 → 43/22 | -23% | -3% | 4m16s | focused validation only; 8 helpers / ~8 mini-boundaries; **noise: Auto compact** |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) Luna | Luna xHigh Fast; landing and delivery phase | 43/22 → 42/22 | -1% | 0% | 5m42s | broader/full validation, docs, review, push, PR; 1107 passed / 8 skipped / 552 subtests |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) combined | Astra implementation plus Luna landing | 66/25 → 42/22 | -24% | -3% | 9m58s | sequential total; **noise: Auto compact** |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) Astra | Astra Low; Graph display calculation cluster | 42/22 → 20/18 | -22% | -4% | 3m56s | focused 29 passed; 6 helpers; AST and diff checks; **noise: interrupted suite startup** |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) Luna | Luna xHigh Fast; landing and delivery phase | 20/18 → 17/18 | -3% | 0% | 6m02s | broader Graph tests 49; 1115 passed / 8 skipped / 552 subtests / 236.42s full suite; AST and diff checks |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) combined | Astra implementation plus Luna landing | 42/22 → 17/18 | -25% | -4% | 9m58s | sequential total; **noise: interrupted suite startup** |
| PR #31 Astra phase | Astra Low; AnimaDex record-inspection cluster | 100/16 → 85/14 | -15% | -2% | 2m24s | clean implementation-only run; 6 helpers; focused 7 passed; empirical observation only |
| [PR #31](https://github.com/prompt-graph-lab/promptgraph/pull/31) Luna | Luna landing and delivery phase | 85/14 → 82/13 | -3% | -1% | 6m21s | full suite 1122 passed / 8 skipped / 552 subtests / 236.52s; empirical observation only |
| [PR #31](https://github.com/prompt-graph-lab/promptgraph/pull/31) combined | Astra implementation plus Luna landing | 100/16 → 82/13 | -18% | -3% | 8m45s | sequential total; empirical observation only |
| PR #32 Astra phase | Astra Low; two-cluster prompt-line selection and PromptCloud calculations | 82/13 → 53/9 | -29% | -4% | 3m23s | Cluster A: 5 helpers; Cluster B: 4 helpers; 9 helpers total; independent checkpoint commits; focused 4 passed and 3 passed; no Auto compact; empirical observation only |
| PR #32 handoff-confusion noise | Luna mistakenly treated the Astra handoff as remaining work | 53/9 → 52/8 | -1% | -1% | 54s | explicit workflow noise; not part of normal Luna landing; empirical observation only |
| PR #32 Luna phase | Normal Luna landing and delivery phase | 52/8 → 50/8 | -2% | 0% | 8m03s | Auto compact shortly after the initial git/repository check; broader relevant validation 33 passed; full suite 1129 passed / 8 skipped / 552 subtests / 236.30s; empirical observation only |
| PR #32 combined | Observed end-to-end including handoff-confusion noise | 82/13 → 50/8 | -32% | -5% | 12m20s | includes the separate 54s handoff-confusion interval; do not interpret as a clean combined phase; empirical observation only |
| Current readonly-clusters Astra phase | Astra; Module scope inspection plus Node selection matching | 50/8 → 30/5 | -20% | -3% | 4m04s | 3 helpers across 2 natural clusters; commits `6a56ffd` and `c3ffebc`; focused 5 and 7 passed; baseline characterization passed; no Auto compact; empirical observation only |
| Current three-cluster Astra phase | Astra; Graph neighborhood traversal, Focus token/node projection, and Route snapshot inspection/comparison | 100/100 → 78/97 | -22% | -3% | 3m52s | 3 natural clusters; 9 functions total; commits `2920761`, `d0a16d0`, and `1a7c187`; focused 4, 5, and 7 passed; baseline characterization passed; no Auto compact; empirical observation only |
| [PR #33](https://github.com/prompt-graph-lab/promptgraph/pull/33) Luna | Luna landing and delivery phase | 30/5 → 27/5 | -3% | 0% | 10m06s | empirical observation only |
| Current four-cluster Astra phase | Astra; ComfyUI workflow metadata, LoRA mapping, comma-tag text, and ComfyUI candidate presentation | 76/96 → 55/93 | -21% | -3% | 3m54s | 4 natural clusters; 15 helpers total; commits `faffeef`, `f12534f`, `524b5db`, and `7da4585`; focused 10, 6, 4, and 4 passed; baseline characterization passed; no Auto compact; empirical observation only |
| [PR #34](https://github.com/prompt-graph-lab/promptgraph/pull/34) Luna | Luna landing and delivery phase | 78/97 → 76/96 | -2% | -1% | 7m22s | no Auto compact; empirical observation only |
| Current readonly-projections Astra phase | Astra; AGraph selection normalization, nearby line selection, consistency presentation, and generation duration formatting | 52/92 → 29/89 | -23% | -3% | 3m23s | asked for up to 5 clusters; intentionally stopped at 4 because the fifth Core/Optional classification boundary was not cleanly separable from the shared label set; 5 helpers total; commits `306fdee`, `cdef4f8`, `0098f2d`, and `15c820c`; focused 3, 4, 3, and 2 passed; baseline characterization passed; no Auto compact; empirical observation only |
| [PR #35](https://github.com/prompt-graph-lab/promptgraph/pull/35) Luna | Luna landing and delivery phase | 55/93 → 54/93 | -1% | 0% | 6m04s | no Auto compact; empirical observation only |
| [PR #37](https://github.com/prompt-graph-lab/promptgraph/pull/37) Luna | Luna-only Codex review-rule governance task | not recorded → 93/84 | not calculated | not calculated | 2m45s | ending quota was user-observed; start quota was not recorded; empirical observation only |
| Current draft-lifecycle orchestration | Luna parent → Astra Low subagent → Luna landing; ComfyUI analysis draft lifecycle | 93/84 → 53/78 | -40% | -6% | 13m56s | one end-to-end observed run; one Astra invocation; no manual human handoff; Auto compact occurred near the beginning and is a confounder; no phase/model attribution or token inference; first stateful-controller extraction, not directly equivalent to prior pure/read-only cluster runs; empirical observation only |
| Current Graph Edit Browser orchestration | Luna immediate dispatch → Astra Low boundary+implementation → Luna landing; Graph Edit Browser navigation controller | 53/78 → 2/70 | -51% | -8% | 11m03s | one Astra invocation; no manual human handoff; no Auto compact; Luna did not perform detailed pre-delegation boundary discovery; whole-run delta was larger than PR #38's observed delta, but no cause is inferred; different potentially more complex stateful work, not a controlled equal-work comparison; no per-model or token inference; empirical observation only |
| Current Global Module Library orchestration | Luna xHigh non-Fast immediate dispatch → Astra Low boundary+implementation → Luna landing; Global Module Library authoritative session lifecycle | 100/70 → 81/67 | -19% | -3% | 15m00s | parent Fast mode off; one Astra invocation; no manual human handoff; no parent-side detailed boundary discovery; no Auto compact; Astra reported two unsuccessful navigation/path checks corrected; no Luna correction after handoff and no test-failure retry; PR #39 comparison is suggestive only, not causal; no per-model or token inference; empirical observation only |
| Current autonomous-boundary orchestration | Luna xHigh non-Fast immediate dispatch → Astra Low autonomous boundary discovery → one boundary implementation → Luna landing; AnimaDex local-path lifecycle | 81/67 → 66/65 | -15% | -2% | 13m22s | one Astra invocation; Astra implemented one boundary rather than stopping; no manual human handoff; no Luna correction; no test-failure retry; no Auto compact; focused 24 passed, broader 58 passed / 19 subtests, full suite 1221 passed / 8 skipped / 603 subtests / 239.21s; whole-run quota and timing are externally observed; empirical observation only |
| Current autonomous-boundary experiment #5 | Luna xHigh non-Fast immediate dispatch → Astra Low bounded autonomous FIRST-SAFE-BOUNDARY discovery → one implementation → Luna landing; Gallery Selected Routes session lifecycle | 66/65 → 51/63 | -15% | -2% | 12m50s | one Astra invocation; discovery stopped at the first sufficiently safe/coherent boundary; focused 46 passed; broader 198 passed / 91 subtests; full-suite process completed but final pytest count/runtime was not retained by the command wrapper and was not rerun; no Luna correction; no retry; no manual human handoff; no Auto compact; externally observed quota and timing; empirical observation only |
| Current multi-boundary cruise experiment #6 | Luna xHigh non-Fast immediate dispatch → one Astra Low invocation → multi-boundary cruise with separate implementation commits → Luna landing | 51/63 → 26/59 | -25% | -4% | 15m51s | target 2 achieved; Module Rename session lifecycle and Project Directory Browser session lifecycle; focused 57 passed / 8 subtests and 44 passed / 1 skipped; Luna broader 100 passed / 1 skipped / 8 subtests; full suite 1245 passed / 8 skipped / 607 subtests / 281.33s pytest (306.47s wrapper); no third boundary attempted; no Luna correction; no retry; no manual human handoff; no Auto compact; externally observed quota and timing; empirical observation only |
| Current end-of-window bounded cruise experiment #7 | Luna xHigh non-Fast → one Astra Low invocation → FIRST-SAFE-BOUNDARY selection → Luna landing; Project Module Inspector draft/widget synchronization | 26/59 → Astra handoff at 14% 5h → 5h window reset to 100% → 99/57 | 13% phase-wise (12% before reset + 1% after reset) | -2% | 13m42s | one boundary implemented in `ui.project_module_inspector_session`; commit `8b443c8`; optional second boundary not attempted because no independently safe boundary was immediately apparent; Astra focused 12 passed; Auto compact before Astra invocation; empirical observation only |
| Current fresh-window multi-boundary cruise experiment #8 | Luna xHigh non-Fast → one Astra Low invocation → sequential FIRST-SAFE multi-boundary cruise → Luna landing; Project Import session lifecycle | 99/57 → 88/55 | -11% | -2% | 11m46s | one boundary completed in `ui.project_root_import_session`; commit `402e787`; target 3 not reached; optional #4 not attempted; Astra focused 14 passed plus 7 baseline characterizations; broader 47 passed / 2 skipped / 2 subtests; full suite 1255 passed / 8 skipped / 607 subtests / 257.53s; no Luna correction or retry; no manual human handoff; no Auto compact; externally observed measurement; empirical workflow observation only |
| Current repeat bounded autonomous cruise experiment #9 | Luna xHigh non-Fast → one Astra Low invocation → fresh-context repeated bounded autonomous cruise | 86/55 → 77/53 | -9% | -2% | 1m54s | zero boundaries; target 3, maximum 4; no implementation, docs, runtime, or test changes; no PR from the run; focused/broader/full tests not run; stopped because no independently coherent sufficiently safe boundary was apparent without broader investigation; no Luna correction or retry; no manual human handoff; no Auto compact; clean worktree and `git diff --check` passed; zero-boundary result informed the move to residual-responsibility audit; empirical observation only |
| Current residual responsibility audit experiment #10 | Luna xHigh non-Fast → one Astra Low audit → Luna documentation landing; residual `app.py` classification and extraction-phase exit criteria | 77/53 → 64/51 | -13% | -2% | 5m23s | audit-only; one Astra invocation; no implementation, tests, or runtime changes; A/B/C/D clusters 3/5/2/3; terminal judgment MOSTLY YES; exact Category C candidates are Module Candidate Selection and Apply-workspace Attribute Group Swap draft/widget synchronization; no manual human handoff; no Auto compact; externally observed measurement; empirical workflow observation only |
| Current explicit residual Category-C extraction #1 experiment #11 | Luna xHigh non-Fast → exactly one Astra Low → explicit audited Category-C boundary → Luna landing; Module Candidate Selection session lifecycle | 64/51 → 54/50 | -10% | -1% | 10m24s | one boundary; no autonomous discovery; owner `ui.module_candidate_selection_session`; commit `15a94e8`; focused 17 passed / 4 subtests before and after extraction; broader 72 passed / 16 subtests; full suite 1255 passed / 8 skipped / 607 subtests / 281.74s; no Luna correction or retry; no manual human handoff; no Auto compact; remaining Category C is Apply-workspace Attribute Group Swap draft/widget synchronization; externally observed measurement; empirical workflow observation only |
| Current explicit residual Category-C extraction #2 experiment #12 | Luna xHigh non-Fast → exactly one Astra Low → explicit audited Category-C boundary → Luna landing; Apply-workspace Attribute Group Swap session lifecycle | 53/49 → 41/48 | -12% | -1% | 14m28s | one boundary; no autonomous discovery; owner `ui.attribute_group_swap_session`; commit `6e04f8d`; focused 16 passed / 8 subtests before and 19 passed / 53 subtests after extraction; broader 46 passed; full suite 1258 passed / 8 skipped / 255.98s pytest (277.09s wrapper); first Astra spawn failed at the occupied subagent/thread limit before implementation started; old inactive threads were closed and Goodall then ran exactly one successful Astra Low implementation; orchestration launch retry 1; implementation retry 0; no Luna correction; no manual human handoff; Auto compact occurred before the successful Astra invocation; residual Category C count zero; extraction-phase terminal judgment YES — current stateful extraction phase should end; empirical workflow observation only |

## Canonical run notes

### PRs #17–#23: earlier single-boundary Astra runs

These were roughly micro or single-boundary refactor runs. Their repeated
fixed validation and context cost appeared large relative to the amount of
code moved, which helped motivate batching related work.

### PR #24: first 3-boundary batch

The Astra Low batch covered three related ComfyUI extraction boundaries:
history interpretation, workflow output classification, and status
interpretation. The full suite was included: 1085 passed, 8 skipped, 552
subtests, with an approximately 242.05-second runtime. Compared with PRs
#21–#23 performed separately, the recorded observation was substantially lower
aggregate quota use and wall time for the three-boundary batch.

### PR #25: 5-boundary batch

The Astra Low batch covered five related ComfyUI utility ownership boundaries:
polling policy constants, output diagnostics, unique save path, group prompt
construction, and workflow injection. The full suite was included: 1089
passed, 8 skipped, 552 subtests, in 240.79 seconds. The implementation and
extraction work was largely complete around 2m30s into the run; much of the
remaining wall time was validation and delivery overhead. This observation
helped motivate separating expensive implementation work from cheaper
validation and delivery work.

### PR #27: first deliberate Astra implementation / Luna landing split

Astra Low selected and extracted the Candidate/Gallery read-only inspection
cluster, covering approximately 10 old-micro-PR-equivalent boundaries and 21
helpers. Astra ran focused tests only and intentionally left the full suite to
Luna. Luna xHigh Fast handled broader validation, the full suite, architecture
documentation, final review, push, and PR delivery. The full validation result
was 1099 passed, 8 skipped, and 552 subtests in 241.53 seconds. The combined
sequential wall time was 10m04s.

This was the first strong evidence in the series that Astra could stop after
implementation and focused validation while Luna handled broad validation and
delivery at a much lower observed 5h quota delta.

### PR #28: natural batch-preview cluster

Astra Low selected the read-only batch-edit preview calculation cluster. It
naturally contained 8 helpers, or approximately 8 mini-boundaries. Focused
validation passed and Astra did not run the full suite. Luna xHigh Fast handled
broader and full validation, documentation, final review, push, and PR
delivery. The full validation result was 1107 passed, 8 skipped, and 552
subtests. Auto compact occurred during the Astra phase; there is not enough
data to conclude whether it improved or worsened quota efficiency.

The combined sequential wall time was 9m58s.

### PR #29: first explicit “one natural cluster” experiment

Astra Low selected the Graph display read-only calculation cluster and moved
six helpers: membership, ordering, positions, initial selection, branch hints,
and cooccurrence edges. The combined focused validation was 29 passed; AST
equivalence and `git diff --check` passed.

This run contains known experimental noise. The original instruction still
asked Astra to run the full suite, the correction initially failed to reach the
task, and Astra began full-suite startup before receiving the corrected
instruction and stopping. The interrupted startup makes this implementation
measurement slightly noisier than a clean implementation-only run.

Luna xHigh Fast then ran the broader Graph tests (49 passed), the full suite
(1115 passed, 8 skipped, 552 subtests, 236.42 seconds), AST equivalence, and
`git diff --check`, followed by documentation, final review, push, and PR
delivery. The combined sequential wall time was 9m58s.

### PR #31: clean AnimaDex record-inspection implementation phase

Astra Low selected one natural coherent AnimaDex record-inspection cluster and
moved six helpers covering record identity, search text, filtering, labels,
summary rows, and metadata preview rows. Focused validation passed with 7
tests. The observed UI quota changed from 100/16 to 85/14 over 2m24s, a 5h
delta of -15% and a weekly delta of -2%. This is an empirical observation from
this implementation-only run, not evidence of a stable accounting change or a
model-wide efficiency improvement.

### PR #31: Luna landing and combined measurement

Luna xHigh Fast completed the AnimaDex landing phase after Astra's implementation
checkpoint. The observed UI quota changed from 85/14 to 82/13 over 6m21s, a 5h
delta of -3% and a weekly delta of -1%. The full suite passed with 1122 passed,
8 skipped, 552 subtests, in 236.52 seconds. The combined Astra-plus-Luna run
changed from 100/16 to 82/13 over 8m45s, a 5h delta of -18% and a weekly delta
of -3%. These are empirical observations only.

### PR #32: two-cluster Astra implementation phase

Astra Low completed two independently committed natural clusters in one
implementation phase: five Illustration-selection helpers in
`core.prompt_line_selection` and four PromptCloud-calculation helpers in
`core.promptcloud_calculations`. The observed UI quota changed from 82/13 to
53/9 over 3m23s, a 5h delta of -29% and a weekly delta of -4%. Focused tests
passed 4 and 3 respectively. No Auto compact occurred. No intermediate quota or
wall-time measurement was recorded at the Cluster A checkpoint, so the data
does not support inferring the marginal cost or benefit of Cluster B. This is an
empirical observation and hypothesis about this run, not evidence of stable
accounting behavior or a model-wide efficiency improvement.

### PR #32: handoff noise, Luna landing, and combined measurement

After the PR32 Astra phase ended at 53/9, a separate 54-second interval moved
from 53/9 to 52/8, an observed 5h delta of -1% and a weekly delta of -1%.
Luna mistakenly treated the Astra handoff as work remaining. This is explicit
workflow noise, not part of the normal Luna landing phase.

The normal PR32 Luna landing then moved from 52/8 to 50/8 over 8m03s, an
observed 5h delta of -2% and a weekly delta of 0%. Auto compact occurred
shortly after the initial git/repository check. Broader relevant validation
passed 33 tests, and the full suite passed with 1129 passed, 8 skipped, 552
subtests, in 236.30 seconds.

The observed end-to-end run, including the handoff-confusion noise, moved from
82/13 to 50/8 over 12m20s, an observed 5h delta of -32% and a weekly delta of
-5%. The clean Astra plus normal Luna wall-time sum is 11m26s, but no clean
combined quota delta is presented because the intervening handoff noise
consumed 1%/1%. All of these are empirical observations only; they do not
establish stable accounting behavior.

### Readonly-clusters Astra implementation phase

Astra completed two independently committed natural read-only clusters in one
implementation phase: `core.module_scope_inspection` with one helper and
`core.node_selection_matching` with two helpers. The observed UI quota changed
from 50/8 to 30/5 over 4m04s, a 5h delta of -20% and a weekly delta of -3%.
Focused validation passed with 5 and 7 tests respectively, baseline
characterization passed, and no Auto compact was observed. This is an
empirical observation from the implementation-only handoff, not evidence of
stable accounting behavior or a model-wide efficiency improvement.

### Current three-cluster Astra implementation phase

Astra completed three independently committed natural read-only clusters in
one implementation phase: `core.graph_neighborhood`,
`core.focus_token_node_projection`, and `core.route_snapshot_inspection`.
The observed UI quota changed from 100/100 to 78/97 over 3m52s, an observed 5h
delta of -22% and a weekly delta of -3%. Focused validation passed with 4, 5,
and 7 tests respectively, baseline characterization passed, and no Auto
compact was observed. This is an empirical observation from the
implementation-only handoff, not evidence of stable accounting behavior or a
model-wide efficiency improvement.

### PR #33 Luna landing phase

The PR #33 Luna landing and delivery phase moved from 30/5 to 27/5 over
10m06s, an observed 5h delta of -3% and a weekly delta of 0%. This is an
empirical observation from that landing phase only; it does not establish
stable quota accounting behavior or generalize to other runs.

### Current four-cluster Astra implementation phase

Astra completed four independently committed natural read-only clusters in one
implementation phase: `core.comfy_workflow_metadata`,
`core.lora_mapping_presentation`, `core.comma_tag_text`, and
`core.comfy_candidate_presentation`. The observed UI quota changed from 76/96
to 55/93 over 3m54s, an observed 5h delta of -21% and a weekly delta of -3%.
Focused validation passed with 10, 6, 4, and 4 tests respectively, baseline
characterization passed, and no Auto compact was observed. This is an
empirical observation from the implementation-only handoff, not evidence of
stable accounting behavior or a model-wide efficiency improvement.

### PR #34 Luna landing phase

The PR #34 Luna landing and delivery phase moved from 78/97 to 76/96 over
7m22s, an observed 5h delta of -2% and a weekly delta of -1%. No Auto compact
was observed. This is an empirical observation from that landing phase only; it
does not establish stable quota accounting behavior or generalize to other
runs.

### Current readonly-projections Astra implementation phase

Astra was asked for up to five clusters and completed four natural,
independently committed read-only clusters: `core.agraph_selection`,
`core.nearby_line_selection`, `core.consistency_presentation`, and
`core.generation_duration`. Astra intentionally stopped at four because the
fifth Core/Optional classification boundary could not be cleanly separated from
the shared label set. The observed UI quota changed from 52/92 to 29/89 over
3m23s, an observed 5h delta of -23% and a weekly delta of -3%. Focused
validation passed with 3, 4, 3, and 2 tests respectively, baseline
characterization passed, and no Auto compact was observed. This is an empirical
observation from the implementation-only handoff, not evidence of stable
accounting behavior or a model-wide efficiency improvement.

### PR #35 Luna landing phase

The PR #35 Luna landing and delivery phase moved from 55/93 to 54/93 over
6m04s, an observed 5h delta of -1% and a weekly delta of 0%. No Auto compact
was observed. This is an empirical observation from that landing phase only; it
does not establish stable quota accounting behavior or generalize to other
runs.

### PR #37 Luna-only governance task

The immediately preceding PR #37 Luna-only Codex review-rule task took 2m45s.
The ending user-observed quota was 93/84, while the starting quota was not
recorded. No quota delta or token accounting is inferred from this partial
observation.

### Current ComfyUI analysis draft-lifecycle orchestration experiment

This is one end-to-end observed orchestration run: Luna parent inspection and
task framing, exactly one Astra Low implementation subagent, then Luna review,
broader validation, one full-suite run, documentation, and delivery. The
observed quota changed from 93/84 to 53/78 over 13m56s, an observed delta of
-40% and -6%. These are whole-run observations only; the delta is not
attributed to Luna or Astra separately, and no phase-level quota values,
per-model split, token usage, or stable accounting behavior is inferred.

Auto compact occurred near the very beginning of the run and is an explicit
confounder. This was also the first stateful-controller extraction, so the
run is not directly equivalent work to the prior pure/read-only cluster runs.

The Astra-to-Luna transition required no manual human handoff; the parent
received the subagent's committed implementation directly and continued the
landing workflow. This is an empirical workflow observation only, not a claim
about stable orchestration or accounting behavior.

### Current Graph Edit Browser immediate-dispatch orchestration experiment

This run changes the previous orchestration shape to Luna immediate dispatch,
then Astra Low boundary discovery, characterization, and implementation, then
Luna landing. The parent did not perform a competing pre-delegation boundary
audit. Astra was invoked exactly once and chose the Graph Edit Browser
navigation-controller boundary. Luna then reviewed the commit, ran broader
Graph Edit validation and one full-suite run, updated documentation, and
prepared delivery.

The externally observed quota changed from 53/78 to 2/70 over 11m03s, an
observed whole-run delta of -51% and -8%. Unlike PR #38, this run had no Auto
compact, and Luna intentionally did not perform detailed boundary discovery
before delegation. The observed whole-run delta was nevertheless larger than
PR #38's observed delta; this record does not conclude why and does not
attribute quota use to Luna or Astra separately.

The Graph Edit Browser controller was a different, potentially more complex
stateful extraction, so this is not a controlled equal-work comparison with
PR #38. No per-model quota use, token accounting, Fast-mode inheritance, or
stable orchestration cost is inferred. Astra was invoked once, no correction
was made after its handoff, and no manual human handoff was required.

### Current Global Module Library non-Fast immediate-dispatch orchestration experiment

This is orchestration experiment #3. The parent remained Luna xHigh with Fast
mode off and performed only immediate-dispatch preparation; it did not perform
detailed implementation-boundary discovery before delegation. Astra Low was
invoked exactly once to discover, characterize, and implement the Global
Module Library authoritative session lifecycle. Luna then reviewed the
implementation, ran broader Module Library validation and one full-suite run,
updated documentation, and prepared delivery. No manual Astra-to-Luna human
handoff was required.

The externally observed quota changed from 100/70 to 81/67 over 15m00s, an
observed whole-run delta of -19% and -3%. This was Luna xHigh with Fast mode off;
the rest of the orchestration shape matched the PR #39 immediate-dispatch
pattern. Luna did not perform detailed pre-delegation boundary discovery,
Astra was invoked exactly once, no Auto compact occurred, no manual handoff
was required, no Luna correction was needed after Astra returned, and no
test-failure retry occurred.

For empirical context, PR #39 used Luna xHigh Fast with 53/78 → 2/70, an
observed delta of -51% and -8% over 11m03s, also without Auto compact. The
observed PR #40 whole-run delta was materially lower than PR #39's. This
comparison is suggestive only and does not establish that Fast mode caused the
difference. The two PRs extracted different stateful responsibilities, so
they are not a controlled equal-work comparison. No per-model quota use,
token accounting, Fast-mode propagation to Astra, internal scheduler behavior,
or stable orchestration cost is inferred.

Astra reported two unsuccessful navigation/path checks that were corrected
during its implementation. This remains an empirical workflow record only.

### Orchestration experiment #4: autonomous boundary discovery

This run used Luna xHigh with Fast mode off. Luna confirmed the latest main and
the safe worktree state, then dispatched immediately without selecting a
candidate list, exact function set, or destination module. Astra Low was
invoked exactly once and was responsible for inspecting the current app,
choosing one boundary, characterizing it, implementing it, and committing it.

Astra selected the AnimaDex local-path lifecycle: draft restoration, widget
synchronization, default save/clear, and saved-path availability feedback. The
implementation extracted one coherent feature-specific stateful controller,
`ui.animadex_path_controller`, and did not stop without changes. Luna found no
correction necessary after the handoff, no test-failure retry occurred, and no
manual human Astra-to-Luna handoff was required. No Auto compact was observed.

The focused result reported by Astra was 24 passed. Luna's broader relevant
validation passed with 58 tests and 19 subtests; the one full-suite run passed
1221 tests, skipped 8, covered 603 subtests, and reported 239.21 seconds in
pytest (261.38 seconds measured by the local command wrapper). Astra did not
report additional candidates intentionally left untouched; that absence is
not evidence that no other boundaries remain.

The externally observed quota changed from 81/67 to 66/65 over 13m22s, an
observed whole-run delta of -15% and -2%. No Auto compact occurred. These are
empirical observations for the complete orchestration run; they do not
attribute work to Luna or Astra separately and do not infer per-model quota
use, token accounting, internal scheduler behavior, Fast-mode propagation, or
stable orchestration cost. Because Astra autonomously selected a different
stateful responsibility, this run is not a controlled equal-work comparison
with the preceding stateful extractions.

### Orchestration experiment #5: repeat autonomous first-safe-boundary discovery

This run repeated the autonomous-boundary workflow with Luna xHigh and Fast mode
off. Luna confirmed latest main and a safe worktree, then dispatched
immediately without selecting a candidate list, exact function set, or owner
module. Astra Low was invoked exactly once and was explicitly instructed to
use a bounded FIRST-SAFE-BOUNDARY strategy: stop discovery after the first
boundary that clearly crosses the safety/coherence threshold, rather than
performing an exhaustive architecture audit.

Astra selected the Gallery Selected Routes session lifecycle and extracted
`ui.gallery_selected_routes_session`. The boundary owns multi-route selection
IDs, route-keyed widget mirrors, Project-reset cleanup, and deferred widget
reset behavior. Discovery stopped after this first sufficiently safe and
coherent boundary; no additional areas were investigated. Luna found no
correction necessary after the handoff, no retry occurred, no manual human
Astra-to-Luna handoff was required, and no Auto compact was observed.

Astra reported 46 focused tests passed. Luna's broader relevant validation
passed with 198 tests and 91 subtests. The full-suite pytest process completed
and produced no failure cache, but the command wrapper did not retain its
final count or runtime; the full suite was not rerun. This limitation is
recorded explicitly rather than replaced with an inferred result.

The externally observed quota changed from 66/65 to 51/63 over 12m50s, an
observed whole-run delta of -15% and -2%. No Auto compact occurred. This
remains an empirical workflow record only. It does not infer per-model quota
use, token accounting, Fast-mode propagation, internal scheduler behavior,
causal effects, or stable orchestration cost.

### Orchestration experiment #6: multi-boundary cruise

This run used Luna xHigh with Fast mode off and the multi-boundary cruise shape:
one Astra Low invocation followed by Luna landing. Luna confirmed latest main
and a safe worktree, then dispatched without selecting boundaries or designing
owner modules. Astra used FIRST-SAFE-BOUNDARY discovery independently for each
boundary and committed each extraction separately.

The target of two boundaries was achieved. Boundary one was the Module Rename
session lifecycle in `ui.module_rename_session`, committed as
`4ef06796bb88632404f1354fba65bf2aa3a25243`, with 57 focused tests and 8
subtests passed. Boundary two was the Project Directory Browser session
lifecycle in `ui.project_directory_browser_session`, committed as
`0206bbd5b9f308b11f490722cfd5c83fbe07d675`, with 44 focused tests passed and
1 environment-limited symlink test skipped. The implementation commits
remain separate. No third boundary was attempted; Astra considered the
optional stopping decision but did not establish a third boundary without
further discovery.

Luna's broader relevant validation passed with 100 tests, 1 skipped test, and
8 subtests. The one full-suite run passed 1245 tests, skipped 8, covered 607
subtests, and reported 281.33 seconds in pytest (306.47 seconds measured by
the local command wrapper). No Luna correction or retry occurred, and no
manual human Astra-to-Luna handoff was required. No Auto compact was observed.

The externally observed quota changed from 51/63 to 26/59 over 15m51s, an
observed whole-run delta of -25% and -4%. No Auto compact occurred. This
remains an empirical workflow record only. It does not infer per-model quota
use, token accounting, Fast-mode propagation, internal scheduler behavior,
causal efficiency, or stable cost per boundary.

### Orchestration experiment #7: end-of-window bounded cruise

This run used Luna xHigh with Fast mode off and an end-of-window bounded-cruise
shape. Luna confirmed latest `main`, the root `AGENTS.md`, and a clean feature
worktree, but did not perform detailed app inspection, boundary discovery,
candidate ranking, or owner design before delegation. Astra Low was invoked
exactly once with a FIRST-SAFE-BOUNDARY strategy: target one safe boundary,
allow at most two only when a second was immediately apparent from the warmed
context, and stop when no additional safe boundary was evident.

Astra selected one coherent Project Module Inspector draft/widget
synchronization boundary and extracted `ui.project_module_inspector_session`.
The owner contains the ten prepare/sync helpers for selection, body, core,
type, and minimum-match state. Astra committed the implementation as
`8b443c80c96e3d3b868025f6cf077f1cc23a417c` and reported 12 focused tests
passing before and after extraction. A second boundary was not attempted:
none was immediately apparent without meaningful new discovery, so the
first-safe stopping rule was applied.

Luna's first broader relevant validation found 71 passed and 12 subtests, plus
one failure in the existing authoring-relocation test loader. The loader still
expected the ten helpers to be defined in `app.py` after their move. Luna made
the small test-harness correction to import and patch the new owner; the
affected caller test then passed 5 tests. The one full-suite run passed 1248
tests, skipped 8, covered 607 subtests, and reported 259.11 seconds in pytest.
No Astra re-invocation or full-suite retry occurred. No manual human
Astra-to-Luna handoff was required.

The externally observed quota sequence was:
`26/59 → Astra handoff at 14% 5h → 5h window reset to 100% → final 99/57`.
The pre-reset phase consumed 12 percentage points of the old 5h window, and
the post-reset Luna landing phase consumed 1 percentage point of the new 5h
window, for an effective phase-wise observed 5h consumption of 13 points.
The weekly quota changed from 59 to 57, an observed change of -2 points, and
the wall time was 13m42s. Auto compact occurred before the Astra Low
invocation. This is an empirical phase-wise observation; it must not be read
as a simple `26 → 99` 5h delta. No per-model token counts, internal quota
accounting, Fast-mode propagation, causal compact effect, or stable
orchestration cost is inferred.

### Orchestration experiment #8: fresh-window multi-boundary cruise

This run used Luna xHigh with Fast mode off and a fresh-window multi-boundary
cruise shape. Luna confirmed latest `main`, the root `AGENTS.md`, and a clean
feature worktree, then dispatched immediately without performing competing
boundary discovery or candidate design. Astra Low was invoked exactly once and
was asked to use sequential FIRST-SAFE discovery: target three independent
safe boundaries, allow an optional fourth only when immediately apparent, and
stop whenever the next boundary would require broad new investigation.

Astra selected one coherent Existing Project Import session boundary and
extracted `ui.project_root_import_session`. The owner contains the six
session/reset helpers for input invalidation, deferred confirmation reset,
source selection, and destination-name initialization. Astra committed the
implementation as `402e78778523d7a13772397b2ada47fd01e91132` and reported 14
focused tests passed across the session and UI tests, plus 7 baseline
characterizations. Target 3 was not reached; optional boundary #4 was not
attempted. Astra stopped after the first boundary because nearby Project
Assets reset helpers did not form a complete independent lifecycle and the
remaining candidates required wider investigation. No Luna correction was
needed and no retry occurred.

Luna's broader Project Import validation passed with 47 tests, 2 skipped tests,
and 2 subtests. The one full-suite run passed 1255 tests, skipped 8, covered
607 subtests, and reported 257.53 seconds in pytest. No manual human
Astra-to-Luna handoff was required, and no Auto compact was observed.

The externally observed quota changed from 99/57 to 88/55 over 11m46s, an
observed 5h change of -11 percentage points and weekly change of -2 percentage
points. This is an empirical workflow record only; it does not infer
per-model token counts, internal quota accounting, Fast-mode propagation,
scheduler behavior, causal efficiency, or stable orchestration cost.

### Orchestration experiment #9: repeat bounded autonomous cruise

This was a real no-implementation run using Luna xHigh with Fast mode off and
exactly one Astra Low invocation from a fresh context. The protocol repeated
the bounded autonomous cruise with a target of three boundaries and a maximum
of four. Astra completed zero boundaries and made no implementation, docs,
runtime, or test changes; no PR was created from the run itself.

Astra stopped because no independently coherent, sufficiently safe boundary
was apparent without broader investigation. Focused, broader, and full-suite
tests were not run. The worktree was clean and `git diff --check` passed; no
Luna correction, retry, or manual human handoff occurred, and no Auto compact
was observed.

The externally observed quota changed from 86/55 to 77/53 over 1m54s, an
observed 5h change of -9 percentage points and weekly change of -2 percentage
points. This zero-boundary result was one empirical reason for moving from
repeated extraction discovery to the residual-responsibility audit in
experiment #10. It does not establish stable discovery cost or infer internal
token usage or quota accounting.

### Orchestration experiment #10: residual `app.py` responsibility audit

This was an audit-only run using Luna xHigh with Fast mode off and exactly one
Astra Low invocation. Luna confirmed latest `main`, the root `AGENTS.md`, and
a clean worktree, then delegated immediately without pre-selecting candidates
or performing a competing architecture audit. Astra made no implementation,
test, runtime, commit, push, or PR changes.

The audit classified the residual architecture into 3 Category A terminal
shell/wiring clusters, 5 Category B broad-design-required clusters, 2
Category C still-safe extraction candidates, and 3 Category D legacy/mixed/
low-value clusters. Category A covers startup/workspace composition,
existing-owner integration and transition ordering, and rendering/action
dispatch. Category B covers Project lifecycle/persistence,
Candidate/Variant/Route mutation, generation execution, filesystem production,
and shared editing/authoring.

The exact Category C candidates are:

1. Module Candidate Selection draft/widget synchronization: the six
   `prepare_module_candidate_selection_widget_state`,
   `sync_module_candidate_selection_widget_state`,
   `prepare_module_candidate_core_tokens_widget_state`,
   `sync_module_candidate_core_tokens_widget_state`,
   `prepare_module_candidate_min_match_widget_state`, and
   `sync_module_candidate_min_match_widget_state` helpers.
2. Apply-workspace Attribute Group Swap draft/widget synchronization: the five
   prepare/sync pairs for `from_widget_state`, `to_widget_state`,
   `scope_widget_state`, `selected_route_widget_state`, and
   `require_full_match_widget_state`.

The terminal-shell judgment is **MOSTLY YES — one or two clearly safe
extractions remain**. These two candidates are bounded decisions, not a reason
to continue indefinite discovery. Presentation microhelpers,
pagination/collapse plumbing, snapshot mutation fragments, generic
session/draft/cache/navigation frameworks, and broad Project/Gallery/
ComfyUI/Module workflows should remain in their current owners unless a later
product or architecture decision changes the boundary.

The static audit counted approximately 22,685 lines and 475 top-level
functions in `app.py`, versus the documented initial 24,900 lines and 634
functions. The audit used AST parsing, targeted `rg` searches, file inventories,
source reads across `app.py`, `ui/`, architecture docs, and relevant tests,
plus status and diff checks. No tests or full suite were run. No manual human
Astra-to-Luna handoff was required, and Auto compact was not observed.

The externally observed quota changed from 77/53 to 64/51 over 5m23s, an
observed 5h change of -13 percentage points and weekly change of -2 percentage
points. Auto compact was not observed. All statements are empirical
observations from this run; they do not infer per-model token counts, internal
accounting, stable audit/discovery cost, scheduler behavior, causal efficiency,
or stable orchestration cost.

### Orchestration experiment #11: explicit residual Category-C extraction #1

This run used Luna xHigh with Fast mode off and exactly one Astra Low invocation.
There was no autonomous boundary discovery: the already-audited Module
Candidate Selection draft/widget synchronization boundary was specified
directly. Astra moved exactly the six audited helpers into
`ui.module_candidate_selection_session` and committed the implementation as
`15a94e813830e7f955b78089fb016efd87eee7c7`.

Astra's focused result was 17 passed with 4 subtests both before and after the
extraction. Luna's broader Module Candidate/Attribute validation passed 72
tests with 16 subtests. The one full-suite run passed 1255 tests, skipped 8,
covered 607 subtests, and reported 281.74 seconds in pytest. No Luna
correction or retry occurred, no manual human Astra-to-Luna handoff was
required, and Auto compact was not observed.

After this extraction, the residual audit has one explicit Category-C
candidate remaining: Apply-workspace Attribute Group Swap draft/widget
synchronization. The externally observed quota changed from 64/51 to 54/50
over 10m24s, an observed 5h change of -10 percentage points and weekly change
of -1 percentage point. Auto compact was not observed. This is an empirical
workflow record only; it does not infer internal token usage, stable
implementation cost, discovery-versus-implementation causal cost, scheduler
behavior, or Fast-mode propagation.

### Orchestration experiment #12: explicit residual Category-C extraction #2

This run used Luna xHigh with Fast mode off and exactly one successful Astra Low
implementation invocation. There was no autonomous boundary discovery: the
final audited Category-C boundary was specified directly. The first attempt to
create the Astra subagent failed because the existing subagent/thread limit was
occupied; implementation had not started. Luna closed old inactive subagent
threads, after which the Astra Low child named Goodall was created and ran the
implementation successfully. This is one orchestration launch retry, not a
second Astra implementation invocation. The ten audited Apply-workspace
Attribute Group Swap draft/widget synchronization helpers were moved into
`ui.attribute_group_swap_session` and committed as
`6e04f8dd63d4e676b9ccdd404ab4b6db0f416f22`.

Astra's focused result was 16 passed with 8 subtests before the extraction and
19 passed with 53 subtests afterward. Luna's broader Attribute Group Swap
validation passed 46 tests. The one full-suite run passed 1258 tests, skipped 8,
and reported 255.98 seconds in pytest; the wrapper runtime was 277.09 seconds.
No Luna correction or implementation retry occurred, and no manual human
Astra-to-Luna handoff was required. Auto compact occurred before the successful
Astra invocation. The orchestration launch retry count was 1, while the
implementation retry count was 0.

The residual audit's two Category-C candidates are now both extracted, so the
residual Category-C count is zero and the extraction-phase terminal judgment is
**YES — current stateful extraction phase should end**. The externally observed
quota changed from 53/49 to 41/48 over 14m28s, an observed 5h change of -12
percentage points and weekly change of -1 percentage point. This is an
empirical workflow record only; it does not infer internal token usage, stable
implementation cost, causal effect of Auto compact or the failed spawn,
scheduler behavior, stable orchestration cost, or Fast-mode propagation.

## Findings

### Strong empirical observations

1. Running multiple closely related extraction boundaries in one Astra context
   was substantially more efficient than running several earlier micro-PRs
   separately.
2. Full-suite validation repeatedly took around four minutes, making it a
   substantial fixed component of short refactor runs.
3. In PRs #27–#29 and #31, Luna xHigh Fast used very little observed 5h quota while
   performing broader or full validation, documentation, final review, push,
   and PR delivery.
4. The Astra/Luna split therefore appears useful for this repository: Astra
   handles architecture, implementation, and focused validation; Luna handles
   broader validation, documentation, and delivery.
5. Natural coherent clusters appear more meaningful than targeting an
   arbitrary function or boundary count. PR #28 naturally contained 8 helpers
   and PR #29 naturally contained 6, while both produced very similar overall
   throughput measurements.
6. Checkpoint commits and focused characterization tests make it safer to hand
   the branch from Astra to Luna.

### Current operating protocol

This is the current experimental workflow:

**Astra Low**

1. Inspect the latest repository state.
2. Select **one** natural coherent responsibility cluster.
3. Characterize behavior where necessary.
4. Implement the extraction.
5. Run focused validation.
6. Run `git diff --check`.
7. Inspect the implementation diff once.
8. Commit.
9. Stop.

**Luna landing agent (mode recorded per run)**

1. Inspect Astra's branch and diff.
2. Run broader relevant tests.
3. Run the full suite once.
4. Update architecture documentation.
5. Review the final diff.
6. Push.
7. Create the PR.
8. Do not merge.

This protocol is an empirical workflow optimization for this experiment
series, not a permanent architectural requirement.

### Hypotheses / insufficient evidence

The following remain hypotheses rather than conclusions:

- Repository or context startup may be a significant fixed cost.
- Helper count itself may be a poor predictor of quota usage.
- Coherent-cluster complexity may matter more than helper count.
- Auto compact may reduce subsequent context-processing cost.
- Auto compact may instead introduce reconstruction overhead.
- Observed quota percentage may depend on factors other than token count.
- Luna's very low observed landing cost may be workload-specific.

No undocumented OpenAI accounting internals are inferred from this log.

## Known measurement noise

- PR #28 includes an Auto compact event. The data does not identify whether it
  improved or worsened efficiency.
- PR #29 includes an interrupted full-suite startup after an instruction
  correction, so its Astra phase includes startup noise.
- The UI percentages are coarse observations, and the displayed deltas are not
  token measurements.
- Model and platform accounting, including subscription usage accounting, may
  change over time.
