# PromptGraph agent guidance

PromptGraph is a practical, behavior-preserving workflow tool. For ownership
and product boundaries, consult [app extraction](docs/architecture/app-extraction.md),
[Module and Attribute design](docs/architecture/module-attribute-design.md), and
[product boundaries](docs/architecture/product-boundaries.md). Treat current
runtime behavior and relevant characterization tests as the compatibility
baseline unless a change explicitly intends to alter them.

## Code Review Rules

These rules are for review findings. Keep reviews high-signal and do not turn
them into a general refactoring or test-expansion plan.

### Finding threshold

Report a finding only when the PR introduces a concrete, actionable problem
that a maintainer would reasonably want fixed before merge. Zero findings is a
valid and preferred result when no such problem exists. Prefer a few
high-confidence findings over exhaustive observations.

Each finding should identify the supported triggering scenario, concrete
consequence, why this PR introduces it, and the smallest practical remediation.
Do not report hypothetical malformed objects unless a supported producer,
persisted boundary, public input, or realistic runtime path can produce them.

### Highest-priority targets

Prioritize concrete issues involving:

- correctness regressions, data loss, destructive behavior, or filesystem side effects;
- Project save/load, persistence, schema, or unknown-field preservation;
- session-state, widget lifecycle, rerun/callback ordering, or mutation ordering;
- Candidate/Gallery adoption and lineage, Route/Snapshot semantics, or
  Module/Attribute/Swap semantics;
- ComfyUI workflow preparation, generation, output handling, or security; and
- user-visible behavior unintentionally changed by a refactor.

### Behavior-preserving refactors

For a refactor that claims behavior preservation, existing observable behavior
is authoritative. Characterization tests that retain odd legacy behavior are
intentional. Do not request cleanup merely because a cleaner behavior seems
possible.

Treat evaluation order, eager/lazy behavior, falsey/default handling, ordering,
stable sorting, duplicate handling, identity/aliasing, exception propagation,
and exact persisted values as compatibility contracts. Flag a difference only
when the PR accidentally changes such a contract. Do not turn a refactor review
into a redesign proposal.

### Architecture boundaries

Flag an architecture change only when it creates a concrete ownership or
behavior problem. In particular, do not casually merge:

- Module Graph structure with flat-token Swap behavior;
- Candidate/Gallery records with ComfyUI workflow candidates;
- Route/Scene organization with Snapshot state;
- read-only/presentation owners with session-state lifecycle owners; or
- pure core calculations with Streamlit/application controllers.

Do not flag an architecture issue merely because another abstraction could be
imagined. Use the linked architecture and product-boundary docs as context,
not as a reason to demand speculative restructuring.

### Scope discipline

Review the actual diff, relevant callers, and relevant tests. Do not audit
unrelated neighboring code, require unrelated fixes, or demand repeated full
suite runs and documentation expansion without a concrete reason.

For extraction/refactor PRs, verify that callers reach the same behavior, the
moved ownership is coherent, stateful behavior did not enter a pure owner,
mutation/persistence/session ordering did not change, and important observable
contracts have appropriate characterization coverage.

### Normally omit

Do not normally report naming or formatting preferences, comment wording,
speculative maintainability concerns, unrelated cleanup, pre-existing bugs,
broad redesign suggestions, unsupported input cases, generic requests for more
validation or tests, tiny abstraction preferences, or differences explicitly
characterized as legacy behavior. If a concern is not worth changing or
blocking the current PR, prefer not to emit a finding.
