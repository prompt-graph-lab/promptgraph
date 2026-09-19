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
8. **Neutral sealed mapping:** assign Fresh Minimal, Fresh Handoff, and
   Persistent Warm to neutral candidates internally. Keep the mapping out of
   worker prompts and reviewer-facing pre-reveal reports.
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

## Round 7 readiness boundary

Round 7 has not started as part of this consolidation. Before it can begin,
the coordinator still must:

- choose a new bounded task;
- freeze its contract and exclusions;
- fetch and freeze the exact post-R6 `origin/main` base;
- reverify the protected Warm v2 conversation and Worktree;
- transition that same Worktree to the new base;
- provision two Fresh workers at the same base;
- create and seal a fresh neutral condition mapping;
- complete the launch preflight before delivering any task.

This document deliberately performs none of those actions.

## Evidence boundary

The protocol is grounded in the completed R3-R6 records, with the end-to-end
orchestration path directly demonstrated by Round 6. The classifications are
operational guidance for this repository, not claims about private backend
implementation. Preserve the historical round records and report any future
deviation instead of silently rewriting this baseline.
