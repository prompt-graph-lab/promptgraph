# Astra-MSC orchestration protocol

This document is the operational baseline for future Astra-MSC rounds in the
public PromptGraph repository. It consolidates the procedure that completed
Round 6 end to end without an orchestration failure.

It is a repository-facing operating procedure, not a claim about private
Codex, ChatGPT, or OpenAI implementation. Current repository and GitHub state
must be refreshed before every round. The historical experiment log remains
the authority for what happened in each completed round; this document
describes how a future round should be run.

## Status vocabulary

The labels below describe the strength and purpose of a rule:

- **STABLE:** a safety or accounting rule supported by direct or repeated
  evidence in the Astra-MSC runs and adopted as the normal operating gate.
  Stable here means stable for this PromptGraph procedure; it does not mean a
  universal platform contract.
- **PROVISIONAL:** a useful procedure or interpretation supported by limited
  observations, or dependent on a platform surface that is not documented as a
  public API.
- **HISTORICAL-ONLY:** an incident response or diagnostic result that remains
  useful for understanding past failures but is not part of the normal round
  path.

Round 6 demonstrated the complete flow from task audit through product merge
and post-round protection. It did not establish universal reliability, causal
effects of context persistence, or private platform semantics.

## Standard round lifecycle

Run the following stages in order. A failed gate stops the round or moves it
to the explicitly named non-valid classification; it must not be silently
treated as an implementation-quality result.

1. **Task audit:** inspect current `origin/main`, the relevant callers and
   tests, and the architecture boundary. Confirm that the proposed seam is
   still unimplemented and bounded.
2. **Contract freeze:** write down the exact responsibility, inclusions,
   exclusions, behavior-preservation requirements, acceptance tests, and
   delivery boundaries.
3. **Exact frozen base:** fetch the authoritative remote and record one exact
   `origin/main` SHA. All arms use that SHA. Do not silently advance it after
   launch.
4. **Launch preflight:** verify task suitability, repository provenance,
   candidate isolation, and all Fresh and Persistent gates without sending a
   conversational readiness probe.
5. **Fresh provisioning:** create exactly the required Fresh resources and
   verify durable addressability, project/repository/origin, exact base, clean
   Worktree, and candidate isolation before branch setup.
6. **Persistent continuity gate:** verify the retained conversation identity,
   prior-round history, absence of unintended intervening task content, and
   direct addressability without messaging the worker.
7. **Same-Worktree base transition:** preserve and push the previous evidence
   branch, transition the existing Persistent Worktree to the exact new base,
   create the new neutral branch, and verify registration, origin, base,
   branch, and clean state. Do not replace or rebind the Worktree.
8. **Neutral sealed mapping:** generate the Fresh Minimal, Fresh Handoff, and
   Persistent Warm assignment; write it to restricted durable experiment-
   private storage; read it back successfully; then bind prepared packets and
   resources from that authoritative record. Keep the mapping out of worker
   prompts and reviewer-facing pre-reveal reports.
9. **Task delivery:** after every Stage 1/2/3 and Persistent gate passes,
   send exactly one frozen implementation packet to each valid worker. The
   coordinator must not send the packet to itself.
10. **Implementation completion verification:** verify the worker's durable
    identity, branch, commit count, changed-file scope, validation evidence,
    pushed ref, and final Worktree state. Separate launch failures and
    validation gaps from implementation defects.
11. **Blind review:** review neutral candidates using only the permitted
    candidate-level evidence. Do not use condition identity, resource age, or
    lifecycle clues as quality evidence.
12. **Frozen review:** freeze the comparison text and any ranking before the
    sealed mapping is revealed. Do not revise the frozen review after reveal.
13. **Mapping reveal:** reveal the mapping only after the frozen review is
    recorded. Record descriptive condition observations separately from the
    pre-reveal technical review.
14. **Experimental accounting:** classify execution validity, contamination,
    blindness limitations, implementation findings, and ranking eligibility
    separately. Do not convert a protocol failure into a quality score.
15. **Product integration validation:** evaluate a proposed product PR only
    as product code. Do not use experiment rank or condition identity as an
    acceptance reason.
16. **Product merge:** merge only after the independent product validation
    decision and human authorization. Product integration does not authorize
    experiment-resource cleanup.
17. **Non-selected PR housekeeping:** close non-selected PRs only after
    verifying their reviewed heads and refs. Preserve branches, commits,
    Worktrees, conversations, and evidence unless a separate cleanup decision
    authorizes their removal.
18. **Protected-resource post-round verification:** re-read the Persistent
    thread without messaging it and verify the same Worktree, branch, commit,
    registration, origin, and protection state. Record the next-round boundary;
    do not begin the next round implicitly.

Orchestration validity and experiment-quality evaluation are separate axes.
An implementation can be technically sound while a round is invalid because
of provisioning, contamination, mapping, or blindness problems.

## STABLE operating rules

These are the normal gates for this repository's Astra-MSC procedure.

### Evidence and identity

- Treat `SELF_REPORTED_STATE != INDEPENDENTLY_OBSERVED_STATE`. A worker or
  coordinator summary is not evidence of an independently running worker.
- Before coordinator execution, record `ROLE_BINDING: PASS` and establish
  `CURRENT_EXECUTION_ROLE: LUNA_HQ_G2_COORDINATOR` when the current task is a
  Luna HQ/G2 coordinator task. In that task context, "Luna", "Luna HQ", "G2",
  and "coordinator" refer to the current coordinator; a task addressed to
  that role is executed directly rather than described as something to send
  to Luna. This is an orchestration-layer safety rule, not a claim about
  private platform roles.
- The coordinator must never self-dispatch. Before every thread send, resolve
  the current coordinator identity and target identity; if they are equal,
  stop and classify the attempt as `SELF_DISPATCH_BLOCKED`.
- Current and target worker identities must be distinct before dispatch.
- Conversation identity and execution identity are separate gates. A durable
  conversation is not a valid Persistent resource without its bound,
  verified execution environment, and a Worktree is not bound merely because
  it exists elsewhere.

### Provisioning and branch setup

- A clean detached HEAD may be a valid initial Managed Worktree state. It is
  not itself a provisioning failure.
- When a named experiment branch is required, coordinator-owned branch setup
  occurs only after exact-base, clean-state, repository, origin, and isolation
  checks pass.
- Implementation starts only after the explicit Stage 1/2/3 gates pass.
- A provisioning failure or launch retry is recorded as
  `orchestration_launch_retry_count`, not as an implementation failure. A
  worker that never received a valid implementation task is not a failed
  implementation candidate.

### Persistent resources and safety

- A retained Persistent resource preserves both the durable conversation and
  the bound Worktree identity.
- Persistent Worktree transition uses the same existing Worktree. Preserve
  and push the prior evidence branch before transitioning it.
- Never use `reset --hard`, `git clean`, force operations, speculative path
  recreation, or private-state edits as a normal recovery mechanism.
- Record the exact base and verify the resulting branch, clean state,
  registration, repository, and origin after every transition.

### Blindness and product boundaries

- Seal the condition mapping from workers and the blind reviewer until the
  review text and ranking are frozen.
- Lifecycle and protection metadata must not expose condition identity through
  a reviewer-facing side channel.
- Product merge choice is independent of experiment ranking. A product PR is
  accepted or rejected from its own callers, behavior, architecture, tests,
  and delivery evidence.
- Closing a PR is independent of deleting its branch, commit, Worktree,
  conversation, or experiment evidence.

### Mapping durability

Mapping durability is a **STABLE** safety gate for scored rounds:

- `MAPPING_DURABLE_WRITE: PASS` is required after randomized mapping
  generation and before treatment delivery.
- `MAPPING_DURABLE_READBACK: PASS` is required before packet binding and
  delivery.
- The durable record must be restricted experiment-private storage. Its
  contents must remain unavailable to workers and the reviewer until the
  frozen review is recorded.
- If a mapping is lost before treatment and all resources remain
  treatment-naive, mark that epoch `VOID`, record mapping recovery, independently
  rerandomize, durably write/read back the replacement epoch, and proceed only
  with the replacement.
- If a mapping is lost after any treatment, stop. Do not infer or reconstruct
  it from worker, branch, resource, or creation-order identity.

This is a procedure-level safety rule. It does not describe private platform
storage semantics.

### Treatment reveal gate

`TREATMENT_REVEAL_GATE` is a **STABLE** procedural gate for scored rounds.
Before mapping or cost may be revealed, the coordinator must verify and record
all required pre-reveal freezes. When the round design requires common product
validation before reveal, the minimum gate is:

```text
BLIND_QUALITY_REVIEW_FROZEN: YES
COMMON_PRODUCT_VALIDATION_COMPLETE: YES
PRODUCT_INTEGRATION_PREFERENCE_FROZEN: YES
MAPPING_REVEALED: NO
COST_REVEALED: NO
```

If any required gate is false, stop and do not reveal the mapping or cost. If
a round intentionally uses a different sequence, that sequence must be frozen
in the round design before treatment begins. This is a procedural rule only;
it does not retroactively invalidate a round whose deviation is recorded.

### Execution-role binding

Execution-role binding is a **STABLE** orchestration-layer gate. Conversation
identity, narrative role, and execution role are distinct:

```text
conversation identity != narrative role != execution role
```

Coordinator task headers should declare the current execution role explicitly.
The role binding must be resolved before any coordinator action, and a send to
the current coordinator itself must be classified `SELF_DISPATCH_BLOCKED`.

### Quiet Test Mode

**QUIET TEST MODE** is a **STABLE** worker-side operating rule for long-running
test commands:

1. After starting a long-running test, do not emit conversational progress
   chatter merely because the process is still running.
2. Do not repeatedly reason or report "still running", "waiting for tests",
   "checking again", or equivalent non-actionable status.
3. Do not use short-interval polling solely to determine completion when a
   longer blocking/wait operation is available.
4. Prefer the longest practical blocking/wait operation supported by the tool
   environment.
5. Re-engage model reasoning when the process completes, fails, reaches a
   meaningful timeout/error, or requires intervention.
6. Intermediate test chatter is not evidence of progress or quality.

The rule is an operational efficiency measure supported by Round 8
observations. It does not claim that conversational output maps one-to-one to
quota or token cost.

### Heavy-task validation ownership

For **HEAVY** tasks, the following is a **PROVISIONAL / OPERATIONAL**
recommendation:

- Astra should inspect, implement, run focused/contract validation needed for
  local correctness, run `git diff --check`, commit, push, and report.
- Luna HQ should run common cross-candidate regression, broad/full pytest, and
  product-integration validation.

This avoids redundant full-suite runs across multiple workers and provides a
neutral shared product gate. Exceptions are allowed when the task contract
requires worker-local full validation or when coordinator validation cannot
reproduce the worker environment. This recommendation does not retroactively
alter prior-round scoring.

### Task complexity guidance

Task complexity is a lightweight **PROVISIONAL / OPERATIONAL** label:

```text
TASK_COMPLEXITY: LIGHT | MEDIUM | HEAVY
```

- LIGHT/MEDIUM tasks may use three workers when a scored three-arm comparison
  is desired.
- HEAVY product work may use one or two Astra workers when experimental
  comparison is not the primary goal.
- A deliberate three-arm HEAVY comparison remains allowed, but its
  quota/resource cost must be treated as an explicit experiment cost.

Do not add complexity labels to historical ranking mathematics without a
separate design decision.

## PROVISIONAL rules and interpretations

The following remain useful but must not be presented as universal platform
contracts:

- A direct client-to-durable-thread discovery fallback may be needed when
  supported discovery does not expose a newly created resource. Prefer the
  supported API; if a read-only local binding lookup is necessary, preserve
  the raw request/response, timestamps, mapping source, and independent
  durable-thread verification. The local `client-thread-bindings-v1` surface
  must never be mutated or treated as a stable API.
- `list_threads` visibility and durable addressability may differ in the
  observed coordinator environment. `NOT LISTED != NOT ADDRESSABLE` is a
  scoped operational qualification, not a universal discovery guarantee.
- The observed same-Worktree transition succeeded in Round 6, but future
  reliability and the semantics of any thread/workspace API remain
  provisional. Reverify every round.
- Persistent context may affect quality, efficiency, or task interpretation,
  but the current observations do not establish a causal performance effect.
- Pooled Warm v1 and Warm v2 observations may be reported descriptively, but
  their aggregate is across distinct lineages and must not be interpreted as
  evidence that persistence or lineage caused a rank.
- A new conversation is not called Persistent Warm at creation time.
  Persistence is earned only after surviving the seed round and passing the
  next-round continuity and execution gates.

## HISTORICAL-ONLY procedures

The following findings and recovery paths remain in the history, but are not
normal round steps:

- arbitrary existing-thread to arbitrary-Worktree rebind attempts;
- historical-point fork recovery, because the tested ordinary fork exposed
  latest-state semantics rather than a historical selector;
- manual UI edit-branch recovery as a substitute for an independently
  addressable successor;
- replacement of a Warm conversation or Worktree while claiming the same
  Persistent condition;
- conversational readiness, memory, acknowledgement, or marker probes by
  default in a scored round;
- reviewer-facing protected-resource identity before the blind review is
  frozen.

These procedures may be investigated again only as explicitly disposable,
read-only or separately authorized incident work. They must not be smuggled
into the normal launch path.

## Blindness standard

Before frozen review, reviewer-facing reports may contain only neutral
candidate-level evidence such as:

- Candidate A/B/C labels;
- neutral branch and PR references;
- commit and changed-file facts;
- test and validation results;
- factual implementation deviations and their observed consequences.

They must not expose:

- Fresh Minimal, Fresh Handoff, Warm, or other condition labels;
- durable or client thread IDs;
- cwd or Worktree paths;
- resource age, reuse status, or prior-round status;
- protected-resource identity;
- prior-round branch lineage;
- any lifecycle or protection metadata that lets a reviewer infer the mapping.

The mapping reveal occurs only after the review text and ranking are frozen.
If lifecycle metadata leaks a role, record the limitation explicitly; do not
pretend that complete three-arm blindness was preserved.

## Persistent Warm minimum standard

An arm may be classified `WARM_V2_PERSISTENT` only after all of the following
are verified.

### Conversation continuity

- the durable conversation identity is unchanged;
- the prior-round task and history are present;
- no unintended intervening implementation task or contamination turn exists;
- the conversation is directly readable/addressable.

### Execution continuity

- the same bound Worktree is present;
- its filesystem path exists and is readable;
- it is registered as the expected Worktree;
- repository and origin are correct;
- the previous evidence branch and commit are preserved;
- the Worktree is clean before transition.

### Round transition

- the previous branch is committed and pushed;
- the existing Worktree is detached or otherwise moved to the exact new
  frozen base through the supported local Git transition;
- the same Worktree identity is verified after the transition;
- a new neutral branch is created at the exact base;
- branch, HEAD, clean state, registration, repository, and origin are
  reverified.

No conversational memory probe is required in the normal scored flow. The
continuity gate is an orchestration check, not a quality claim.

## Resource retention and cleanup

Every resource must be classified into one of these categories before cleanup:

- `DISPOSABLE_FRESH` — no retained experiment obligation remains;
- `PRESERVE_EXPERIMENT_EVIDENCE` — branch, commit, Worktree, conversation, or
  validation evidence is still needed for the record;
- `PROTECTED_WARM_V2` — a retained Persistent lineage and its bound Worktree;
- `HUMAN_DECISION_REQUIRED` — the dependency or binding cannot be established
  from authoritative evidence.

Before deleting or unregistering a Codex-managed Worktree, verify all of the
following:

- no preserved thread currently reports that path as its cwd;
- no active experiment depends on it;
- local and remote evidence-retention requirements are satisfied.

If a preserved thread references the path, classify it `PRESERVE`. If the
reference is uncertain, classify it `HUMAN_DECISION_REQUIRED`. Git-level
dispensability alone is insufficient. `SAFE_TO_DELETE` is allowed only when
there is no preserved-thread reference and no active experiment dependency.

This protocol does not authorize cleanup by itself; it defines the evidence
gate for a separately authorized cleanup task.

## External atomic creation rule

For the current supported external worker-creation surface, resource creation
and the first model turn are atomic. There is no supported zero-turn paused
stage between managed Worktree creation and the first worker prompt.

Therefore the current valid Fresh-worker workflow is:

- treat the automatically created managed Worktree as the isolation boundary;
- accept detached HEAD at the exact frozen base as the valid initial state;
- require the first worker actions to verify repository, origin, frozen base,
  and clean tracked state;
- stop before source inspection or implementation when that environment gate
  fails;
- forbid worker-side repair, branch switching, reset, clean, rebase, or
  checkout repair;
- do not require a local implementation branch;
- allow the coordinator to pre-create a neutral remote evidence branch at the
  frozen base;
- allow the worker to create exactly one detached implementation commit and
  push it with `HEAD:refs/heads/<neutral-evidence-branch>`;
- include the identical environment bootstrap in the measured worker cost for
  every experimental arm.

This rule describes the currently observed supported surface only. It makes no
claim about future product capability.

## Internal disposable worker limitation

The current internal multi-agent topology is not the default for PromptGraph
Astra experiments because the supported launch surfaces do not provide:

- a prebound isolated Worktree or cwd; or
- complete task token, rollout, and Worktree evidence.

This is a current orchestration limitation, not an implementation-quality
finding and not a claim about future capability. Internal workers must not be
used for a scored PromptGraph comparison unless those evidence and isolation
gates are independently satisfied.

## Next-round readiness boundary

Round 10 is complete, and no subsequent Phase 2 round has started as part of
this closeout. Before the next scored round can begin, the coordinator still
must:

- choose a new bounded task;
- freeze its contract and exclusions;
- fetch and freeze the exact post-Round-10 `origin/main` base;
- preserve the protected Warm v2 conversation and Worktree as historical
  evidence; do not use it for Phase 2;
- provision two Fresh external workers at the same base using the atomic
  creation rule above;
- create, durably write/read back, and seal a fresh neutral condition mapping;
- verify each managed Worktree's initial environment in the first turn;
- complete the launch preflight before delivering any further task material.

This closeout deliberately performs none of those next-round actions.

## Evidence boundary

The protocol is grounded in the completed R3-R6 records, with the end-to-end
orchestration path directly demonstrated by Round 6. The classifications are
operational guidance for this repository, not claims about private backend
implementation. Preserve the historical round records and report any future
deviation instead of silently rewriting this baseline.
