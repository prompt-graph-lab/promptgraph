# Astra-MSC Worktree and branch-attachment postmortem

Status: historical engineering postmortem, updated 2026-09-16.

This document records the Astra-MSC Round 3 Worktree incident and the later
evidence that qualified its initial interpretation. It is intentionally not a
blame document and does not claim a private Codex backend mechanism. The goal
is to preserve the chronology, distinguish direct observations from inference,
and define a repeatable setup protocol for later experiments.

## Executive summary

Round 3 remains **TERMINAL-BLOCKED / PROTOCOL-DEVIATED**. It has no valid
three-way implementation ranking. The Fresh Minimal workers stopped before
implementation at a provenance gate that required a named experiment branch
to be checked out.

The later forensic audit established a narrower conclusion than the original
incident diagnosis:

- at least one current Codex Desktop Managed Worktree path legitimately starts
  as a clean detached HEAD;
- successful Astra-MSC runs reached named branches through explicit worker-side
  or coordinator-side Git setup in some cases;
- coordinator-facing APIs did not always expose resources that the human UI
  later showed;
- therefore detached HEAD alone does not prove provisioning failure, and it
  does not prove normality either;
- branch attachment must be treated as a separate, path-dependent setup step
  whenever the experiment requires a named branch.

The final classification is:

**MIXED SEMANTICS / CONTEXT-DEPENDENT**

## Scope and evidence discipline

The incident covers Astra-MSC Round 3 through the 2026-09-16 forensic audit.
The public PromptGraph repository and committed Git state are authoritative for
repository facts. Human-visible UI evidence is authoritative only for the UI
and Worktree state directly observed there. Coordinator API absence is recorded
as non-observability, not as proof that a resource did not exist.

The evidence categories used here are:

- **Direct observation:** a state shown by Git, the human UI, a retained worker
  report, or a retained coordinator command/result;
- **Historical inference:** the explanation used at the time, based on the
  evidence then available;
- **Corrected interpretation:** the narrower conclusion supported after later
  evidence was added;
- **Remaining uncertainty:** private platform behavior or missing historical
  request/command data that cannot be reconstructed safely.

## Chronology

### 1. Round 3 Fresh Minimal resources

The Fresh Minimal resources MSC-R3-M9Q6 and MSC-R3-T6H3 were later shown in
the human Codex UI to have:

- a real worker thread;
- a project-local PromptGraph Worktree;
- the correct public repository and origin;
- the exact requested base commit;
- a clean Worktree;
- detached HEAD; and
- no checkout of the expected experiment branch.

Both workers stopped at the provenance gate before implementation. The initial
classification, **TERMINAL-BLOCKED / PROTOCOL-DEVIATED**, remains valid because
the three-arm implementation comparison never became complete. What changed is
the explanation: the result is not proof that the platform provisioning itself
failed, because the selected Worktree path may have legitimately begun
detached and the coordinator had not completed a separate branch-attachment
step.

### 2. Coordinator observability correction

During the bounded inspection, coordinator-facing list/thread APIs did not
expose M9Q6 or T6H3. The human UI later showed both resources. The durable
distinction is therefore:

> **NOT OBSERVABLE THROUGH LUNA during the inspected interval** does not mean
> **RESOURCE DID NOT EXIST**.

PR #57 preserved this distinction. This postmortem keeps it and adds the
branch-semantics qualification below; it does not rewrite the earlier report as
careless or fraudulent.

### 3. Sanity q4m7

The Fresh provisioning sanity resource sanity-q4m7 was accepted through
`create_thread`. Its retained request included a branch-oriented
`startingState` with:

- `branchName = experiment/sanity-q4m7`; and
- `onMissing = create-branch`.

Human-visible evidence later showed a real thread and project-local Worktree
with the correct origin, requested base, and clean state, but detached HEAD.
This reinforced the original branch-attachment interpretation at the time. It
did not, however, expose the private semantics of the create path or establish
that `startingState` promised a non-detached final Worktree.

### 4. Worktree/resource cleanup

Durable evidence was preserved before disposable public PromptGraph Worktrees
were removed. The cleanup preserved the active G2 coordinator, the Warm
Persistent Astra resource, experiment branches and commits, merged PRs/docs,
and selected evidence Worktrees.

The cleanup was intentionally performed before another sanity test so that a
resource-accumulation hypothesis could be observed without deleting the
durable experiment record. The result did not establish that cleanup caused or
failed to cause any provisioning change.

### 5. Post-cleanup u7n5 attempt

The post-cleanup sanity attempt using `experiment/sanity-u7n5` never reached
resource acceptance. Two create requests returned `INVALID_ARGUMENTS`; no
client resource, thread, or Worktree was created. This is a pre-provisioning
argument failure and must remain separate from the detached-Worktree evidence.
It provides no evidence about branch attachment. The resource-accumulation
hypothesis was neither proven nor disproven by this attempt.

### 6. Human UI test using the existing checkout

An earlier manual Fresh Astra test was first launched using the existing local
checkout rather than a new Worktree. The worker correctly reported the normal
PromptGraph checkout, its current feature branch, and the known untracked
`.editor_settings.json` item. This was a test-setup mistake, not a provisioning
failure, and clarified an important distinction:

> **Fresh thread is not the same thing as Fresh Worktree.**

### 7. Human UI Managed Worktree test c007

The follow-up manual test explicitly selected the public `promptgraph` Project,
“New local Worktree,” starting branch `main`, and Fresh Astra Low. The resulting
Worktree was:

- `C:/Users/monid/.codex/worktrees/c007/promptgraph`;
- origin `https://github.com/prompt-graph-lab/promptgraph.git`;
- HEAD `f529fb3115fa647c224d24d357a778eb8b94f1a4`;
- clean; and
- without a current branch, i.e. detached HEAD.

No repair or branch creation occurred. This directly establishes that at least
one current Codex Desktop Managed Worktree path legitimately begins detached.
It does not establish that every project-local `create_thread` path has the
same contract.

### 8. Branch-attachment forensic audit

The later audit reconstructed the following successful-run evidence:

#### R2 X — worker-side attachment

The worker directly ran:

```text
git switch -c experiment/r2-x4pk ef7189214391dccb6ad0dd5f801baf49c797b8b0
```

before editing. This is direct evidence that the worker created and checked out
the named branch after startup. The resulting commit was
`8178bb1ff24321871fa17cf2376de3a6fa7bfcc8`.

#### R2 Z — coordinator-side attachment

The coordinator directly ran an equivalent of:

```text
git worktree add -b experiment/r2-n8vd <target> ef7189214391dccb6ad0dd5f801baf49c797b8b0
```

before delivering the implementation task. The resulting commit was
`a44b90bd446e3e45496cfdc2da1bf04912f61897`.

#### R3 Warm — coordinator-side attachment

The coordinator directly ran an equivalent of:

```text
git worktree add -b experiment/r3-p7w2 <target> b62a8db837422d6151c28882e66111d8c406c8f5
```

before worker execution. The worker's first observed command saw the named
branch already checked out. The resulting commit was
`da9ef79cdac0290bfb266fb16850b47e6bbbaf25`.

#### R2 Y and R3 Fresh Handoff

R2 Y reached `experiment/r2-q7m2` after create-thread acceptance and before its
completed commit, but the exact actor and command were not retained. R3 Fresh
Handoff K4N8 reached `experiment/r3-k4n8` and completed at
`7d2fcef2737f23b6db58d0451e425addd9557b59`, but the exact attachment actor and
timing were also not retained.

These successful final states must not be used to infer that the backend
attached a branch atomically during creation.

## Final interpretation

The evidence supports all of the following:

- detached HEAD can be a normal initial state for at least one Codex Managed
  Worktree path;
- named branch attachment occurred through explicit worker-side or
  coordinator-side Git setup in successful Astra-MSC runs;
- coordinator API visibility and actual UI resource existence can diverge for a
  bounded interval; and
- the orchestration path and explicit setup steps matter.

The evidence does not support any of the following stronger claims:

- all Round 3 detached Worktrees were definitely broken provisioning;
- all detached Worktrees are normal;
- resource accumulation caused the observed results;
- cleanup fixed or failed to fix provisioning; or
- a universal private backend contract for `create_thread` Worktree setup.

The narrow supported classification is:

**MIXED SEMANTICS / CONTEXT-DEPENDENT**

## Corrected Round 3 classification

Round 3 remains **TERMINAL-BLOCKED / PROTOCOL-DEVIATED** with no valid
three-way implementation ranking. The Fresh Minimal results are:

- not implementation-quality failures;
- not proven platform provisioning failures;
- pre-implementation orchestration/provenance-gate failures under the
  then-used protocol; and
- not a quality NO-GO candidate.

No conclusion should be invented about what either Fresh Minimal worker would
have implemented if the task had continued.

## Corrected staged protocol

The protocol separates initial Worktree provenance from experiment branch setup.

### Stage 1 — initial Worktree provenance

After a Fresh resource is created, verify where observable:

- the correct Project and public repository;
- the authoritative origin;
- the exact requested base commit;
- a clean, isolated Worktree; and
- no cross-candidate contamination.

A detached HEAD is permitted at this stage if the selected provisioning path
legitimately creates Managed Worktrees detached.

### Stage 2 — explicit experiment branch setup

If the experiment requires a named branch, the coordinator should explicitly
create and attach the deterministic experiment branch from the exact verified
base before implementation begins. Coordinator-owned setup is preferred for
Astra-MSC comparisons so Git setup skill is not mixed into implementation-quality
comparisons.

Record where available:

- branch name;
- base SHA;
- actor;
- command or orchestration action; and
- timestamp.

Do not rely on implicit backend attachment.

### Stage 3 — post-setup provenance gate

Before sending the implementation task, verify:

- the expected branch is checked out;
- HEAD is not detached;
- the branch points to the intended base before candidate edits;
- the Worktree is clean; and
- candidate isolation remains intact.

Only at this stage should missing named-branch attachment be treated as a
setup failure for an experiment that requires a named branch.

### Stage 4 — implementation

Send Astra the implementation task only after coordinator-controlled environment
setup is complete. Do not ask a worker to repair its own environment unless
branch setup is intentionally part of the experimental condition and is recorded
as such.

## Future create-call evidence rule

For every future Fresh external create attempt, preserve the full observable
request shape and response where possible:

- project/target;
- environment type;
- `startingState`;
- `branchName`;
- `onMissing`;
- model;
- thinking;
- title;
- clientThreadId; and
- resulting Worktree path and state.

This evidence is required because missing request bodies materially complicated
the reconstruction of this incident.

## Impact on existing guidance

The guidance introduced around PR #57 required the expected branch to be checked
out and HEAD not to be detached before Fresh implementation. That remains a
valid safety rule for a path whose contract explicitly includes named-branch
attachment, but it is too broad as a universal rule for every Codex Managed
Worktree.

The corrected interpretation is:

- initial detached state may be valid for a generic Managed Worktree path;
- a named branch must be attached explicitly before implementation when the
  experiment requires one; and
- detached HEAD alone is not proof of a provisioning failure.

The corresponding operational guidance is updated in
`docs/operations/chat-codex-handoff.md`, and the experiment log is updated in
`docs/experiments/coding-agent-throughput.md`.

## Follow-up: Fresh thread addressability reproduction

Round 4 remained **NOT STARTED** when a separate, implementation-free A2
addressability reproduction was run on 2026-09-18. This was not another
implementation candidate and did not change the Round 3 classification.

The A2 resource used the recovered successful `create_thread` request shape.
It was accepted, received a client identifier, and immediately acquired a
durable thread identity in the local Codex state. The client identifier itself
was not accepted by `read_thread`, while the resolved durable identity was
readable. A single follow-up probe sent through that durable identity succeeded
and returned the expected `ADDRESSABLE` response. A valid `list_threads` call
still omitted the resource.

The resulting classification was:

**DIRECT_ADDRESSABLE_DISCOVERY_GAP**

This separates two concerns that had previously been conflated:

- **Git/Worktree readiness:** the Round 4 preflight demonstrated that an
  initially detached Managed Worktree can pass coordinator-owned branch setup
  and that the worker can observe the resulting named branch, exact base, and
  clean state; and
- **thread discovery:** the A2 resource was directly readable and messageable
  through its durable identity even though it was absent from `list_threads`.

This is direct evidence for the tested resource and coordinator environment
only. It does not establish why discovery omits the resource, that the local
binding representation is stable, or that Round 4 can complete end to end.
The local client-to-durable binding is therefore documented as a **PROVISIONAL
FALLBACK**, **NOT A STABLE API CONTRACT**, and must be inspected read-only.
The concrete client and session identifiers remain in the source experiment
report rather than this public postmortem.

The provisional operating procedure is maintained in
[`docs/operations/chat-codex-handoff.md`](../operations/chat-codex-handoff.md):
preserve the exact create request, resolve and verify a durable identity, keep
`list_threads` visibility separate from direct addressability, complete staged
Worktree/branch provenance, and only then deliver implementation work.

## Remaining uncertainty

### Directly observed

- c007 was clean and detached through the human UI Managed Worktree path;
- q4m7 was accepted with a branch-oriented starting state and later visible as
  clean but detached;
- R2 X's worker ran `git switch -c` itself;
- R2 Z and R3 Warm had coordinator-side `git worktree add -b` setup before task
  execution;
- M9Q6 and T6H3 were human-visible clean detached Worktrees and stopped before
  implementation; and
- u7n5 failed before resource acceptance.

### Strongly supported inference

- R2 Y's named branch was created after `create_thread` acceptance and before
  completion, but its actor is unknown;
- successful runs used more than one explicit branch-setup pattern; and
- the observed outcomes cannot be attributed solely to Worktree count or
  resource accumulation.

### Unresolved private behavior

- the backend semantics of `startingState` for each project-local path;
- the exact attachment actor and timing for R2 Y and K4N8;
- whether M9Q6/T6H3 were intended to be named-branch Worktrees at creation time
  or were normal detached initial Worktrees whose explicit attach step never
  occurred; and
- the relationship between coordinator API visibility delay and Worktree
  provisioning.
