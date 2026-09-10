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

## GitHub record

On 2026-09-10, GitHub metadata was checked for the listed PRs. PRs #17 through
#25 and #27 through #29 were reported as merged into `main`; the local
`origin/main` was fetched through the PR #29 merge commit. GitHub PR metadata
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
| [PR #27](https://github.com/prompt-graph-lab/promptgraph/pull/27) Luna | Luna Max Fast; landing and delivery phase | 68/26 → 66/25 | -2% | -1% | 5m54s | broader/full validation, docs, review, push, PR; 1099 passed / 8 skipped / 552 subtests / 241.53s |
| [PR #27](https://github.com/prompt-graph-lab/promptgraph/pull/27) combined | Astra implementation plus Luna landing | 100/31 → 66/25 | -34% | -6% | 10m04s | sequential total |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) Astra | Astra Low; batch-edit preview cluster | 66/25 → 43/22 | -23% | -3% | 4m16s | focused validation only; 8 helpers / ~8 mini-boundaries; **noise: Auto compact** |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) Luna | Luna Max Fast; landing and delivery phase | 43/22 → 42/22 | -1% | 0% | 5m42s | broader/full validation, docs, review, push, PR; 1107 passed / 8 skipped / 552 subtests |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) combined | Astra implementation plus Luna landing | 66/25 → 42/22 | -24% | -3% | 9m58s | sequential total; **noise: Auto compact** |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) Astra | Astra Low; Graph display calculation cluster | 42/22 → 20/18 | -22% | -4% | 3m56s | focused 29 passed; 6 helpers; AST and diff checks; **noise: interrupted suite startup** |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) Luna | Luna Max Fast; landing and delivery phase | 20/18 → 17/18 | -3% | 0% | 6m02s | broader Graph tests 49; 1115 passed / 8 skipped / 552 subtests / 236.42s full suite; AST and diff checks |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) combined | Astra implementation plus Luna landing | 42/22 → 17/18 | -25% | -4% | 9m58s | sequential total; **noise: interrupted suite startup** |

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
Luna. Luna Max Fast handled broader validation, the full suite, architecture
documentation, final review, push, and PR delivery. The full validation result
was 1099 passed, 8 skipped, and 552 subtests in 241.53 seconds. The combined
sequential wall time was 10m04s.

This was the first strong evidence in the series that Astra could stop after
implementation and focused validation while Luna handled broad validation and
delivery at a much lower observed 5h quota delta.

### PR #28: natural batch-preview cluster

Astra Low selected the read-only batch-edit preview calculation cluster. It
naturally contained 8 helpers, or approximately 8 mini-boundaries. Focused
validation passed and Astra did not run the full suite. Luna Max Fast handled
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

Luna Max Fast then ran the broader Graph tests (49 passed), the full suite
(1115 passed, 8 skipped, 552 subtests, 236.42 seconds), AST equivalence, and
`git diff --check`, followed by documentation, final review, push, and PR
delivery. The combined sequential wall time was 9m58s.

## Findings

### Strong empirical observations

1. Running multiple closely related extraction boundaries in one Astra context
   was substantially more efficient than running several earlier micro-PRs
   separately.
2. Full-suite validation repeatedly took around four minutes, making it a
   substantial fixed component of short refactor runs.
3. In PRs #27–#29, Luna Max Fast used very little observed 5h quota while
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

**Luna Max Fast**

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
