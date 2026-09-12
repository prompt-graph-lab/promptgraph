# Agent orchestration handoff

This document records the transition from PromptGraph's behavior-preserving
stateful extraction phase to broader architectural investigation. It is a
durable handoff for future Luna, GPT, and Astra work; it does not replace the
current architecture boundaries in [app-extraction.md](app-extraction.md).
The provisional routing organization is documented in
[agent-organization.md](agent-organization.md), with durable assignment
record fields in
[agent-assignment-schema.md](../experiments/agent-assignment-schema.md).
Finite-window continuity and successor identity rules are documented in the
[agent-succession-policy.md](agent-succession-policy.md).

## Current architecture phase

PR #48 completed the final audited Category-C extraction:

- residual Category C count: zero;
- current stateful extraction phase: end;
- remaining meaningful `app.py` work: Category A terminal shell/wiring,
  Category B broad-design architectural work, and Category D mixed/legacy/
  low-value glue.

Further open-ended small extraction cruises should not be the default. A new
extraction requires an explicit architectural or product decision.

## Historical subagent resume experiment

The interview/resume experiment was a no-implementation orchestration run.
Its externally observed measurement was:

- start quota: 41 / 48;
- end quota: 36 / 47;
- observed delta: -5 / -1;
- wall time: 22m31s;
- Auto compact: none;
- implementation: none;
- file changes: none;
- tests/full suite: not run;
- commit/push/PR: none.

The requested interview maximum was six. Seven historical workers were
actually interviewed: no further interviews were performed. This cap
deviation is recorded as an orchestration fact, not as a quota or efficiency
interpretation.

Interviewed workers and continuity grades:

| Worker | Prior area | Continuity |
| --- | --- | --- |
| Banach | Module Rename / Project Directory Browser | A |
| Dalton | Project Module Inspector | A |
| Mencius | Project Import lifecycle | A |
| Plato | Rejected residual safe-boundary discovery | B |
| Ramanujan | Residual architecture audit | A |
| Goodall | Attribute Group Swap lifecycle | A |
| Newton | Module Candidate Selection lifecycle | A |

Einstein, Wegener, Nash, and Meitner were not present in the exposed
inventory. The overall empirical conclusion was that historical resume
preserved strong, useful prior context. This is an observation about the
responses, not a claim about any internal memory or storage mechanism.

## Retained specialist knowledge

The resumed workers retained concrete, non-trivial local knowledge including:

- durable/widget precedence and exact lifecycle keys;
- reset and publication ordering;
- per-Module draft isolation;
- falsey and coercion behavior;
- partial writes and direct exception behavior;
- preview/result/pending-reset separation;
- hidden-widget reconstruction;
- selected-route repair and preview freshness;
- pending-created-Module handoff;
- reasons for keeping mutation, history, persistence, Project replacement,
  cross-feature reset publication, and rerun orchestration in `app.py`.

## Emerging orchestration model

The role split is:

- **Human:** external client and final approval;
- **GPT:** external architect and independent reviewer;
- **Luna:** persistent front desk, project manager, expertise router, and
  integration layer;
- **Astra:** resumable high-cost specialist.

Route work by prior expertise and work history, not only by model type.
Historical Astra workers can be retained as specialist identities when useful;
they should not automatically be discarded after one PR.

### Recommended resume procedure

1. Resume the former specialist.
2. Ask what it remembers before repository inspection.
3. Separate retained knowledge, uncertainty, and new inference.
4. Refresh against current `main`.
5. Provide only relevant current files and documents.
6. Compare prior understanding with the current state.
7. Continue with the same specialist only when the task remains in its area of
   expertise.
8. Keep Luna/GPT as independent management and review layers.

Historical worktrees may be stale. Current repository state must be explicitly
refreshed before design or implementation.

## Cross-cutting architecture warnings

The interview consensus supports these constraints:

- Preserve exact lifecycle semantics where behavior matters: session keys,
  precedence, callback order, falsey/default behavior, exception propagation,
  aliasing/copy behavior, partial writes, hidden-widget reconstruction, and
  rerun behavior.
- Keep feature-specific draft state separate from preview, mutation, history,
  persistence, focus restoration, Project replacement, cross-feature reset
  publication, and rerun orchestration unless an explicit redesign assigns
  those responsibilities together.
- Avoid premature generic session, cache, navigation, transaction, or
  application-context frameworks.
- AST equivalence alone is insufficient for stateful redesign; lifecycle
  characterization is required.
- Do not casually collapse Apply-workspace and Gallery behavior.
- Keep operation-specific Route/Scene eligibility local rather than creating
  one universal lifecycle.

## Next recommended Category-B design investigation

The strongest convergence was around a **Project replacement and transition
contract**. Banach, Dalton, Mencius, and Ramanujan independently encountered
parts of the same cross-feature ordering boundary.

This should be a design-only investigation covering:

- successful Project replacement;
- failed Project replacement;
- reset/publication ordering;
- history boundaries;
- persistence ordering;
- discovery/cache refresh timing;
- recent-project and settings updates;
- Back/Undo interactions where replacement state is involved.

Expected no-code deliverables:

- state/event transition table;
- ownership matrix;
- failure and partial-update contract;
- invariants;
- explicit app-level responsibilities;
- go/no-go decision for implementation.

Do not begin with a generic transaction framework. Preserve the existing
separation between Project transitions, persistence, filesystem primitives,
workspace rendering, and feature-specific session owners.

## Suggested expert organization

- **Ramanujan:** natural lead candidate because it performed the residual
  architecture audit;
- **Banach:** supporting expert for Project Directory, cache, refresh, and
  selection behavior;
- **Mencius:** supporting expert for Project Import, filesystem, and
  persistence boundaries;
- **Dalton:** supporting expert for Project-local drafts, save order, and
  partial-write behavior;
- **Luna:** coordinates specialists and integrates the result;
- **GPT:** remains the independent architecture reviewer.

## Operating hypothesis

An empirical working hypothesis is that reusing a historical specialist may
avoid repeatedly paying the fixed context-reconstruction and discovery cost for
the same repository area. Future experiments may compare a fresh Astra with a
resumed prior specialist on adjacent tasks.

This hypothesis does not establish stable quota economics, token accounting,
model behavior, or a universal orchestration cost.
