# PromptGraph AI Lab Organization v1

This is a lightweight routing organization for future PromptGraph work. It is
an experimental operating model, not a permanent team structure and not a
claim that agents are autonomous employees. Labs describe durable
responsibility domains; individual specialists may affiliate with more than
one lab and may change assignment over time.

The organization starts after PR #48 completed the final audited Category-C
extraction. Category C is zero. The remaining meaningful `app.py` work is
primarily Category A terminal shell/wiring, Category B broad-design work, and
Category D mixed/legacy/low-value glue. A new task should not default to
another small extraction cruise.

## Operating principles

- Route by relevant prior responsibility and retained context, not only by
  model type.
- Keep one primary lab for each task and name supporting labs only when their
  boundary is concrete.
- Treat historical specialist affiliations as provisional and task-relative.
- Keep current repository evidence authoritative over retained context.
- Keep Luna as coordinator and GPT as an independent architecture/review
  layer.
- Prefer a fresh specialist when the task is genuinely outside the retained
  expertise or when an independent second opinion is intentional.

## Labs

### 1. Project State and Persistence Lab

**Responsibility domain:** Project replacement, load/import/duplicate/fork
transitions, Save As/Undo boundaries, settings and recent-project state,
discovery/cache refresh, and the ordering between session reset, persistence,
and publication.

**Current concerns covered:** Category-B Project lifecycle and persistence,
including Project replacement, history/save ordering, Project Import boundary,
directory discovery/cache publication, asset-reset timing, and failure-safe
transitions.

**Should route here:**

- the Project replacement and transition contract design spike;
- load/import/duplicate/fork/Undo/Save As ordering questions;
- Project-bound session clearing and failed-transition preservation;
- recent-project/settings updates and discovery refresh timing;
- Project Import or Directory Browser work involving persistence or refresh
  ordering.

**Should not route here:**

- pure token, Route, or presentation calculations;
- Module/Attribute mutation design without a Project transition question;
- ComfyUI workflow generation or output production;
- a generic transaction/session framework proposal.

**Likely historical specialists:** Ramanujan, Banach, Mencius, and Dalton.

**Provisional lead:** Ramanujan for cross-feature architecture; Banach and
Mencius are supporting specialists for Directory/refresh and Import/filesystem
boundaries respectively. Dalton is an affiliate for Project-local draft and
save-order behavior.

**Fresh-specialist condition:** recruit fresh when the task introduces a new
Project schema, cross-project merge semantics, or a persistence product
decision not represented in the historical work, or when no resumed expert
reaches a task-relative medium/high context match.

**Dependencies:** every feature lab can depend on Project replacement and
publication. Keep `core.io`, discovery, filesystem primitives, and UI session
owners as separate boundaries until an explicit design assigns otherwise.

### 2. Candidate, Route, and Scene Operations Lab

**Responsibility domain:** Candidate/Variant/Route/Scene operation semantics,
selection scope, adoption/promotion, operation eligibility, provenance, and
history boundaries for these operations.

**Current concerns covered:** Category-B Candidate, Variant, and Route
mutation, adoption, promotion, selected-route operation planning, and the
relationship between structural Route resolution and operation-specific
eligibility.

**Should route here:**

- Candidate adoption, promotion, or provenance design;
- Route/Scene structural resolution and selected-route operation contracts;
- operation-specific scope/eligibility questions;
- design of a snapshot or operation-plan handoff before mutation.

**Should not route here:**

- a universal Candidate lifecycle combining generation, export, and
  persistence;
- Project replacement or JSON schema work;
- Module/Attribute authoring semantics that do not involve Route eligibility;
- pure read-only Route formatting or inspection.

**Likely historical specialists:** Ramanujan, Newton, Goodall, and Plato for
bounded seam review.

**Provisional lead:** Ramanujan for the architectural boundary; Newton and
Goodall are supporting specialists for Module Candidate and selected-route
operation context. Plato is consultation-only unless a task matches its
retained seam-rejection context.

**Fresh-specialist condition:** recruit fresh for a new Route/Scene schema,
cross-project merge model, or product-level Candidate lifecycle redesign.

**Dependencies:** Project State and Persistence for history/save and Project
replacement; Module/Attribute Authoring for operation inputs; Generation and
Production for generated Candidate registration.

### 3. Module and Attribute Authoring Lab

**Responsibility domain:** Global Library authority, Project-local Module and
Attribute authoring, Inspector and Candidate draft/apply lifecycles, Attribute
Group operations, graph/focus consequences, and feature-specific
draft/widget state.

**Current concerns covered:** Category-B shared Module/Attribute authoring,
including Global Library authority, Project-local replacement, history,
graph rebuilding, focus restoration, and Apply-workspace operation contracts.
The completed session owners remain narrow feature owners, not a shared lab
runtime framework.

**Should route here:**

- Module/Attribute authoring or application design;
- Project Module Inspector or Module Candidate apply-lifecycle studies;
- Attribute Group operation contracts and their draft/preview/apply boundary;
- Global Library authority versus Project-local metadata questions.

**Should not route here:**

- generic session/cache/navigation abstractions;
- Project persistence/schema redesign without an authoring-specific question;
- ComfyUI workflow execution;
- collapsing Apply-workspace and Gallery operation state.

**Likely historical specialists:** Dalton, Newton, Goodall, Ramanujan, and
Plato.

**Provisional lead:** Dalton for Inspector and Project-local draft/save
behavior. Newton supports Candidate draft/apply work; Goodall supports
Attribute Group and selected-route state; Ramanujan provides architecture
review. Plato is useful for ambiguous-boundary consultation.

**Fresh-specialist condition:** recruit fresh for state-aware Attribute models,
schema migration, new authoring product semantics, or a redesign that crosses
Global Library, Project metadata, and graph/focus ownership.

**Dependencies:** Project State and Persistence for mutation/history/save;
Candidate/Route Operations for selected-route eligibility; UI rendering and
feature-specific session owners remain explicit at the application boundary.

### 4. Generation and Production Lab

**Responsibility domain:** ComfyUI workflow preparation and execution,
progress/output handling, Candidate ingestion, assets, forks, final export,
filesystem safety, and post-success publication.

**Current concerns covered:** Category-B generation execution and filesystem
production workflows, where workflow preparation, progress, paths, validation,
writes, Candidate registration, logs, and persistence interleave.

**Should route here:**

- workflow preparation/execution and output lifecycle design;
- generation progress and Candidate ingestion contracts;
- asset, fork-materialization, or final-export safety;
- staging, validation, atomic publication, and source-preservation questions.

**Should not route here:**

- UI draft/widget synchronization;
- Project replacement coordination;
- Route schema or Module/Attribute authoring semantics;
- pure presentation or inspection helpers.

**Likely historical specialists:** Mencius is the closest supporting specialist
for filesystem and persistence boundaries. Ramanujan has audit-level context;
no historical worker has yet established a dedicated generation specialist
identity.

**Provisional lead:** currently unassigned. Use GPT/Luna architecture review
and recruit a fresh specialist when a real generation/production design task
begins, unless a new expert first develops sufficient retained context.

**Fresh-specialist condition:** normally recruit fresh for ComfyUI execution,
output security, or production/export design because the current historical
roster has no direct implementation owner for that domain.

**Dependencies:** Project State and Persistence for publication and settings;
Candidate/Route Operations for generated Candidate registration and scope;
ComfyUI/core and filesystem primitives must remain separate from UI session
controllers.

## UI/session routing rule

There is intentionally no universal UI/session lab. The Category-C extraction
phase is complete, and the retained owners are feature-specific. Route a UI or
session question to the lab that owns the underlying feature, while keeping
rendering, app-level wiring, cross-feature reset publication, mutation,
history, persistence, and rerun order explicit. Do not create a generic UI
lab merely to collect session-state helpers.

## Current specialist assignments

These are provisional routing affiliations based only on documented prior
work. They are not permanent typecasts.

| Expert | Known prior domains | Provisional affiliation(s) | Role | Evidence and uncertainty |
| --- | --- | --- | --- | --- |
| Banach | Module Rename; Project Directory Browser | Project State and Persistence | supporting | Direct refresh/cache/selection and Project transition context; no direct generation or schema-design evidence. |
| Dalton | Project Module Inspector | Module and Attribute Authoring; Project State and Persistence | lead candidate / supporting | Direct Inspector draft and save-order context; broader persistence redesign remains untested. |
| Mencius | Project Import lifecycle | Project State and Persistence; Generation and Production affiliate | supporting | Direct Import/filesystem boundary context; no direct ComfyUI execution ownership. |
| Plato | Rejected residual safe-boundary discovery | consultation-only, currently unassigned | consultation | Useful seam-rejection and ambiguity context; continuity was partial and no durable implementation domain was established. |
| Ramanujan | Residual architecture audit | Project State and Persistence; cross-lab architecture | lead candidate | Direct Category-B audit and transition-boundary context; no implementation ownership is implied. |
| Goodall | Attribute Group Swap lifecycle | Module and Attribute Authoring; Candidate, Route, and Scene Operations affiliate | supporting | Direct draft/widget and selected-route context; no broad Route or persistence ownership. |
| Newton | Module Candidate Selection lifecycle | Module and Attribute Authoring; Candidate, Route, and Scene Operations | supporting | Direct Candidate draft/apply context; no Project persistence or generation ownership. |

Generation and Production has no current lead candidate. A fresh specialist
should normally be recruited when that domain receives its first substantive
design or implementation task.

## Fresh versus reused specialist policy

Use a reused/resumed specialist when the current task is a small continuation
of its prior domain, when the expert can provide relevant retained constraints,
or when rediscovering known local behavior would be the main cost.

Use consultation-only reuse when the specialist has useful historical context
but should not own the design or implementation. Record its self-report and
context match, then keep Luna/GPT or another specialist as the owner.

Recruit a fresh specialist when no historical expert has relevant context, the
task is materially outside the existing domains, context match is low, an
independent second opinion is intentional, or a new durable domain deserves a
new pseudonymous identity. Do not recruit fresh merely because a historical
expert is available but the task is a direct continuation of its expertise.

The routing and assignment record must be created before contacting a reused
expert. The memory probe must happen before current-repository inspection, and
the context-match grade must be assigned only after comparison with historical
and current evidence. Current repository evidence always wins.
