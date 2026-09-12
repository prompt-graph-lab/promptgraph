# Agent succession policy

This policy is a lightweight continuity mechanism for PromptGraph's finite
context windows. It preserves decision-relevant organizational knowledge when
an Astra specialist session or a Luna Landing coordination window can no
longer continue safely. It is an engineering operating policy, not a claim
that agents are employees or autonomous organizational actors.

The policy distinguishes durable responsibility domains and roles from the
individual context-bearing sessions that temporarily carry them. Current
repository and runtime evidence remains authoritative. Current lab boundaries
are documented in the [agent organization](agent-organization.md). The
related records are defined in the
[assignment record schema](../experiments/agent-assignment-schema.md) and the
[succession event schema](../experiments/agent-succession-schema.md).

## Identity model

| Concept | Durable identity | Context-bearing instance |
| --- | --- | --- |
| Specialist responsibility | Lab or responsibility domain, such as Project State and Persistence | One Astra specialist session and its current worktree/context |
| Astra specialist | Stable pseudonymous expert identity, such as Ramanujan | A particular session generation carrying that identity |
| Coordination | Luna Landing department/role | One Luna/Codex window generation, such as Luna Landing G2 |

A successor Astra receives a new expert pseudonym. The predecessor's name is
never transferred to a fresh successor, because records must distinguish a
same-agent resume from knowledge transfer to a different agent. A resumed
predecessor remains the same expert identity and is recorded as reused under
the assignment schema.

Luna Landing may retain its durable department name while its window changes
generation. Public records use compact generation identifiers, not raw
platform, thread, or session identifiers. A generation identifier is a
continuity label, not a claim about model identity or internal storage.

## Authority and evidence order

Succession decisions and handoff verification use this authority order:

1. current repository and runtime evidence;
2. durable repository architecture and experiment documentation;
3. a verified handoff package;
4. retained agent memory or self-report;
5. unsupported recollection or inference.

An older specialist or a handoff package may explain why a decision was made,
but neither overrides current code or current documented behavior. Unknown,
stale, and disputed information is recorded as uncertainty rather than
silently reconstructed.

## Specialist lifecycle

The following states describe the operational lifecycle of a historical Astra
specialist. They are routing states, not employment statuses.

### Active

The specialist may be assigned work in its recorded domain. Its retained
context is still useful for the current task, and current repository evidence
has been refreshed before design or implementation ownership is assigned.

### Handoff Due

Evidence indicates that continuing in the current session may increase
continuity or correctness risk. Luna records the reason, preserves the latest
known repository state, and prepares a handoff package before hard failure
where practical. The specialist may finish a bounded safe task, but should not
silently accumulate a new broad responsibility while this state is unresolved.

### Successor Onboarding

A fresh specialist with a new pseudonym is being brought into the same lab or
responsibility domain. The successor reads the durable package, states its
understanding and uncertainties, refreshes against current `main`, and
compares the package with current evidence before taking design or
implementation ownership.

### Emeritus

The specialist is retained for historical consultation: explaining old
decisions, disputed constraints, legacy quirks, or differences between a
predecessor's and successor's interpretations. Emeritus status does not
restore implementation ownership automatically. If resumed, the assignment
is recorded as a reused consultation and current evidence remains authoritative.

### Archived

The specialist is no longer an active routing option. Its handoff package,
assignment records, and known uncertainty remain durable historical context.
An archived identity is not silently reused as a fresh successor.

Temporary inactivity, reassignment to another lab, and consultation-only use
are not retirement by themselves. A specialist with no current task remains
eligible for later routing unless a handoff or archival decision is recorded.

## Handoff-due signals

Succession is context- and responsibility-driven. There is no fixed age,
number of PRs, number of turns, quota threshold, or invented context-window
budget. The following observable signals may indicate that a handoff is safer:

- the platform reports that the session cannot continue;
- an explicit continuation or context limit is approaching;
- increasingly broad historical reconstruction is required for ordinary work;
- retained context is stale or conflicts with current repository state;
- task-relative context match degrades on adjacent work;
- accumulated responsibility is too broad to remain a useful specialty;
- the next work materially changes domain;
- a clean architectural boundary makes a fresh successor safer than a long
  continuation.

Auto compact alone does not prove degradation. It may be recorded as an
observable event and a possible confounder, but it is not a retirement rule.
Likewise, elapsed time, displayed quota changes, or an individual correction
do not establish hidden context usage or a stable succession cost.

When a signal appears, Luna records the reason and the affected responsibility,
checks whether the current task has a clean stopping point, and chooses among
continuation, temporary inactivity, reassignment, consultation, planned
succession, or emergency retirement. The decision should be proportionate to
the risk and should not turn an ambiguous signal into a factual claim about
the platform.

## Emergency retirement

If a session reaches a hard limit before a planned handoff:

1. mark the event as emergency or otherwise record that the planned package
   was incomplete;
2. treat current repository state and existing durable docs as authoritative;
3. recover only the handoff facts that are actually observable;
4. record missing fields and uncertainty explicitly;
5. create a successor with a new Astra pseudonym, or a new Luna generation;
6. require current-main refresh and discrepancy review before ownership;
7. keep the predecessor's identity available only as historical/emeritus
   context when the record supports that use.

The procedure does not pretend that inaccessible conversational context can be
reconstructed exactly. A missing package is a continuity gap, not permission
to invent predecessor decisions.

## Specialist handoff package

Before a planned successor begins, the departing specialist or Luna should
produce a concise structured package. It should contain, when observable:

- predecessor `expert_name` and current lab affiliation(s);
- owned and recently handled responsibility domains;
- relevant PRs, commits, architecture docs, and experiment records;
- important invariants and behavior that is easy to break;
- known legacy quirks and dangerous lifecycle/order dependencies;
- responsibilities intentionally left elsewhere;
- unresolved questions, rejected approaches, and why they were rejected;
- assumptions that may now be stale;
- the current architecture boundary and recommended successor scope;
- current `main` SHA at handoff;
- uncertainty and confidence notes.

The package is a durable decision summary, not a transcript dump. Fields that
cannot be reliably recovered remain `null`, `unknown`, or an explicit gap.
The package path and handoff SHA are recorded in the succession event when
available.

## Successor onboarding

The normal specialist succession sequence is:

1. produce or recover the handoff package;
2. Luna records why succession is occurring before contacting the successor;
3. Luna creates a fresh Astra with a new expert pseudonym;
4. the successor reads the package and states its understanding,
   uncertainties, and suspected stale areas;
5. the successor refreshes against current `main`;
6. the successor compares package claims with current repository evidence;
7. Luna/GPT verifies material discrepancies;
8. only then does the successor assume design or implementation ownership.

The successor is `fresh`, not `reused`, under the assignment schema. Its
`previous_task_domain` and retained-context self-report are `null`, and its
`context_match` is `not_applicable`. If continuity quality is measured later,
use a separate `handoff_fidelity` observation for reconstruction against the
package and current evidence; do not overload `context_match`, which measures
task-relative retained history for a reused expert.

## Luna Landing department succession

The durable coordination role is Luna Landing. A particular Luna/Codex window
is only one generation of that department. For example, `Luna Landing G1`
may hand off to `Luna Landing G2` while the department name and routing
responsibility remain stable.

### Luna handoff triggers

Luna should prepare departmental succession when observable evidence indicates
that the current window is becoming unsafe to continue, including:

- an explicit platform warning about continuation limits;
- substantial organizational state that can no longer be summarized reliably;
- routing or history that requires repeated broad reconstruction;
- a major architecture phase transition with a clean handoff boundary;
- repeated compacting or context reconstruction that creates operational risk;
- planned maintenance or a clean-window reset.

These are evidence-based triggers, not numerical thresholds. Prefer a handoff
before hard failure where practical.

### Luna department handoff package

The package should summarize organizational state rather than every chat turn:

- coordinator generation ID and observable handoff date/time;
- current `main` SHA and architecture phase;
- current labs and responsibility boundaries;
- active, inactive, and emeritus specialist roster;
- each specialist's latest relevant domain and latest assignment records;
- open design investigations and active PR/task state;
- routing rules, protocol deviations, and unresolved architecture questions;
- current experimental hypotheses and caveats;
- pending human decisions;
- knowledge that should not be rediscovered unnecessarily;
- known stale or uncertain information;
- recommended next task.

The next Luna generation must verify current `main` and open repository state;
the package is not assumed current forever. Repository docs are durable
organizational memory, while chat context is working memory.

### Luna succession procedure

1. read the latest Luna handoff package;
2. read the agent organization and assignment schema;
3. refresh current `main` and open PR state;
4. compare repository state with the package and record discrepancies;
5. reconstruct the active specialist roster;
6. identify the pending human decision or next task;
7. acknowledge takeover as the new active Luna generation.

If the predecessor window is still usable, one bounded clarification round is
allowed. Indefinite overlap is not required. After acceptance, the new
generation is the active coordinator and the predecessor is archived
organizational context, not a second authoritative PM.

## Succession event records

Record each actual planned or emergency succession in the
[succession event schema](../experiments/agent-succession-schema.md). Record
observable facts only: identity changes, package paths, SHAs, verification
results, known gaps, first post-handoff work, corrections, intervention, and
observed timing or quota when available. Do not expose raw platform IDs or
infer token accounting, hidden scheduler behavior, or causal handoff cost.

For specialist succession, predecessor and successor pseudonyms must differ.
For Luna succession, the Luna Landing role remains the same while the
generation/instance ID changes. A future `handoff_fidelity` field is optional
and separate from `context_match`; it measures successor reconstruction, not
same-agent retained context.

## Research questions

Future records may examine, without presuming an answer:

- how long a reused specialist remains useful before succession;
- whether planned handoff differs from emergency replacement;
- whether structured handoff reduces rediscovery relative to unrelated fresh
  discovery;
- how much specialist knowledge survives package-based onboarding;
- whether emeritus consultation changes successor correction rates;
- how often successor review reveals stale predecessor assumptions;
- whether Luna department succession preserves routing quality;
- how much human intervention is required immediately after succession.

These remain empirical questions. Current observations do not establish
causality, stable quota economics, stable orchestration cost, or infinite
continuity.
