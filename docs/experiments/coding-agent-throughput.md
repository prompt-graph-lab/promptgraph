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
| [PR #27](https://github.com/prompt-graph-lab/promptgraph/pull/27) Luna | Luna Max Fast; landing and delivery phase | 68/26 → 66/25 | -2% | -1% | 5m54s | broader/full validation, docs, review, push, PR; 1099 passed / 8 skipped / 552 subtests / 241.53s |
| [PR #27](https://github.com/prompt-graph-lab/promptgraph/pull/27) combined | Astra implementation plus Luna landing | 100/31 → 66/25 | -34% | -6% | 10m04s | sequential total |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) Astra | Astra Low; batch-edit preview cluster | 66/25 → 43/22 | -23% | -3% | 4m16s | focused validation only; 8 helpers / ~8 mini-boundaries; **noise: Auto compact** |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) Luna | Luna Max Fast; landing and delivery phase | 43/22 → 42/22 | -1% | 0% | 5m42s | broader/full validation, docs, review, push, PR; 1107 passed / 8 skipped / 552 subtests |
| [PR #28](https://github.com/prompt-graph-lab/promptgraph/pull/28) combined | Astra implementation plus Luna landing | 66/25 → 42/22 | -24% | -3% | 9m58s | sequential total; **noise: Auto compact** |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) Astra | Astra Low; Graph display calculation cluster | 42/22 → 20/18 | -22% | -4% | 3m56s | focused 29 passed; 6 helpers; AST and diff checks; **noise: interrupted suite startup** |
| [PR #29](https://github.com/prompt-graph-lab/promptgraph/pull/29) Luna | Luna Max Fast; landing and delivery phase | 20/18 → 17/18 | -3% | 0% | 6m02s | broader Graph tests 49; 1115 passed / 8 skipped / 552 subtests / 236.42s full suite; AST and diff checks |
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
| Current Global Module Library orchestration | Luna Max non-Fast immediate dispatch → Astra Low boundary+implementation → Luna landing; Global Module Library authoritative session lifecycle | 100/70 → 81/67 | -19% | -3% | 15m00s | parent Fast mode off; one Astra invocation; no manual human handoff; no parent-side detailed boundary discovery; no Auto compact; Astra reported two unsuccessful navigation/path checks corrected; no Luna correction after handoff and no test-failure retry; PR #39 comparison is suggestive only, not causal; no per-model or token inference; empirical observation only |
| Current autonomous-boundary orchestration | Luna Max non-Fast immediate dispatch → Astra Low autonomous boundary discovery → one boundary implementation → Luna landing; AnimaDex local-path lifecycle | 81/67 → 66/65 | -15% | -2% | 13m22s | one Astra invocation; Astra implemented one boundary rather than stopping; no manual human handoff; no Luna correction; no test-failure retry; no Auto compact; focused 24 passed, broader 58 passed / 19 subtests, full suite 1221 passed / 8 skipped / 603 subtests / 239.21s; whole-run quota and timing are externally observed; empirical observation only |
| Current autonomous-boundary experiment #5 | Luna Max non-Fast immediate dispatch → Astra Low bounded autonomous FIRST-SAFE-BOUNDARY discovery → one implementation → Luna landing; Gallery Selected Routes session lifecycle | 66/65 → 51/63 | -15% | -2% | 12m50s | one Astra invocation; discovery stopped at the first sufficiently safe/coherent boundary; focused 46 passed; broader 198 passed / 91 subtests; full-suite process completed but final pytest count/runtime was not retained by the command wrapper and was not rerun; no Luna correction; no retry; no manual human handoff; no Auto compact; externally observed quota and timing; empirical observation only |

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

### PR #31: clean AnimaDex record-inspection implementation phase

Astra Low selected one natural coherent AnimaDex record-inspection cluster and
moved six helpers covering record identity, search text, filtering, labels,
summary rows, and metadata preview rows. Focused validation passed with 7
tests. The observed UI quota changed from 100/16 to 85/14 over 2m24s, a 5h
delta of -15% and a weekly delta of -2%. This is an empirical observation from
this implementation-only run, not evidence of a stable accounting change or a
model-wide efficiency improvement.

### PR #31: Luna landing and combined measurement

Luna Max Fast completed the AnimaDex landing phase after Astra's implementation
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

This is orchestration experiment #3. The parent remained Luna Max with Fast
mode off and performed only immediate-dispatch preparation; it did not perform
detailed implementation-boundary discovery before delegation. Astra Low was
invoked exactly once to discover, characterize, and implement the Global
Module Library authoritative session lifecycle. Luna then reviewed the
implementation, ran broader Module Library validation and one full-suite run,
updated documentation, and prepared delivery. No manual Astra-to-Luna human
handoff was required.

The externally observed quota changed from 100/70 to 81/67 over 15m00s, an
observed whole-run delta of -19% and -3%. This was Luna Max with Fast mode off;
the rest of the orchestration shape matched the PR #39 immediate-dispatch
pattern. Luna did not perform detailed pre-delegation boundary discovery,
Astra was invoked exactly once, no Auto compact occurred, no manual handoff
was required, no Luna correction was needed after Astra returned, and no
test-failure retry occurred.

For empirical context, PR #39 used Luna Max Fast with 53/78 → 2/70, an
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

This run used Luna Max with Fast mode off. Luna confirmed the latest main and
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

This run repeated the autonomous-boundary workflow with Luna Max and Fast mode
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

## Findings

### Strong empirical observations

1. Running multiple closely related extraction boundaries in one Astra context
   was substantially more efficient than running several earlier micro-PRs
   separately.
2. Full-suite validation repeatedly took around four minutes, making it a
   substantial fixed component of short refactor runs.
3. In PRs #27–#29 and #31, Luna Max Fast used very little observed 5h quota while
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
