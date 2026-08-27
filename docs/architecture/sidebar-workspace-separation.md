# Sidebar / Workspace Separation Design

Terminology note: current user-facing surfaces say **Illustration**, **Scene**, **Graph Edit**, **Derived Project**, and **Sequence Snapshot**. Historical slice names and compatibility identifiers such as `PromptLine`, `line_*`, `route_*`, `selected_routes`, `lightweight_fork`, and `route_snapshots` remain in this implementation inventory where exact code/state ownership matters. The future multi-Scene **Route** concept is not implemented in Pro v1.

Status: **Slice 1 workspace shell, Slice 2A Project creation / duplication relocation, Slice 3 ComfyUI Settings relocation plus ComfyUI Analysis & Inspection consolidation, Slice 4 Module / Attribute Authoring ownership through Slice 4B-2B, Slice 5A Apply Sidebar responsibility extraction, Slice 5B-1 Module Toggle relocation, Slice 5B-2A saved-insertion state durability, Slice 5B-2B saved-insertion relocation, Slice 5B-3A Candidate Selection state durability, Slice 5B-3B Candidate Selection relocation, Slice 5B-4A Attribute Group Swap state durability, Slice 5B-4B Attribute Group Swap relocation, Slice 5B-5 Module Edit Scope Sidebar ownership, Slice 5C-1A Project Module Inspector state durability, Slice 5C-1B Project Module Editor relocation, the final persistent default Project root, and Graph-only Sidebar mode separation implemented; later migration slices proposed**.

This document is an implementation inventory and migration plan for the
workspace-separation slices and their focused ownership follow-ups. The
session-only exclusive workspace shell is implemented. Project creation and duplication live in Project Management; ComfyUI environment configuration plus read-only Analysis & Inspection live in ComfyUI Settings; Module / Attribute creation and Project Module editing live in Authoring; preview-first production operations live in Apply. The daily Sidebar retains current Project status,
Quick Save, Project discovery and Recent Projects, Advanced direct JSON Open /
Save As, Project Assets, Workflow Preset selection, compact effective ComfyUI status,
Module / Attribute Analysis, and persistent Module Edit Scope. ComfyUI analysis no longer renders or executes from the passive Sidebar. Gallery, Graph Edit,
Trash, Focus Edit, Project transition, settings persistence, generation,
history, save/load, and schema boundaries remain owned by their existing paths
unless a later slice explicitly says otherwise.

Slice 5B-2A makes Saved Module Reference Insertion safe to hide behind the exclusive workspace router. Existing operation input names own durable same-Project state, while temporary underscore widget keys are reconstructed when the Apply workspace returns. Slice 5B-2B completes the relocation without redesigning that state boundary. Back preserves inputs and preview; successful Project transitions clear both durable and temporary operation state. Preview, Apply, scope, history, and persistence semantics are unchanged.

Slice 5B-3A makes Module Candidate Selection safe to hide behind the exclusive workspace router without relocating it. Its selected Module and Module-specific unsaved Core Tokens and Minimum Match drafts are durable same-Project state, while three temporary underscore widget-key families reconstruct when the Sidebar returns. Candidate and Apply previews remain current only while their unchanged signatures match. Back and failed transitions preserve the operation; successful Project transitions clear its fixed keys, dynamic drafts, temporary widgets, previews, and pending-Module handoff state.

Slice 5B-3B completes that render-owner relocation. The Apply workspace now renders Module Toggles, Saved Module Reference Insertion, and Module Candidate Selection in that order. Candidate Selection uses one main-area expander; the Sidebar Apply section retains its launcher and only Attribute Group Swap.

Slice 5B-4A separates the Sidebar Attribute Group Swap operation's durable same-Project drafts from its temporary Streamlit widget keys. From Group, To Group, scope, selected Route, Require Full Match, and preview state can therefore survive future Apply-workspace Back/reopen cycles. Normal and Selected Routes previews remain current only while their existing signatures match; changed inputs or external target context leave the stored preview stale and blocked. Selected Routes confirmation remains intentionally temporary and must be checked again after the control is hidden. Successful Project transitions clear only the Sidebar operation state, while failed transitions and Back preserve it. Gallery Attribute Group Swap remains a separate state owner. The Sidebar remains the sole render owner in this slice; actual relocation is deferred to Slice 5B-4B.

Slice 5B-4B completes that render-owner relocation. The Apply workspace now renders Module Toggles, Saved Module Reference Insertion, Module Candidate Selection, and Attribute Group Swap in that order. Attribute Group Swap uses one main-area expander, while the retained Sidebar Apply section owns only the compact launcher. Back preserves the durable drafts and preview, reopening reconstructs missing temporary widget state, and Selected Routes confirmation must be checked again. Gallery Attribute Group Swap remains independent.

Slice 5B-5 settles Module Edit Scope ownership. It remains in Sidebar Analysis rather than moving into the Module / Attribute Apply workspace because it is persistent editing context used after returning to Gallery, Overall Edit, and Focus Edit. Placing it only inside an exclusive management workspace would allow an active constraint to become invisible after Back. Sidebar Analysis therefore shows the active `module_edit_scope_name`, keeps it distinct from `module_inspector_selected`, and provides one direct clear action. The scope remains session-only: Back, section collapse, and other management workspaces preserve it, successful Project replacement clears it, and failed transitions preserve it. No Project schema, save, autosave, history, prompt-filtering, or Module-parsing behavior changed.

Slice 5C-1A prepares Project Module Inspector for relocation from Sidebar Analysis to Module / Attribute Authoring. Unlike Module Attribute Table, the Inspector edits and saves Project Module body, type, core-token, and minimum-match definitions. Its same-Project selection and per-Module drafts are now stored separately from temporary rendered-widget state, and successful Project replacement clears the exact Project-bound Inspector state. Back and hidden-widget cleanup can reconstruct the widgets without falling back to saved Project values. Same-name Modules in a replacement Project cannot inherit old drafts. That durability slice intentionally left the renderer in Sidebar Analysis for the follow-up relocation.

Slice 5C-1B completes that render-owner relocation. Project Module Editor now renders once in Module / Attribute Authoring after Module Library / Creation and before Rename Module. Back/reopen reconstructs its temporary widgets from the Slice 5C-1A durable same-Project drafts, while successful and failed Project transitions retain their established reset boundary. Sidebar Analysis retains Module Attribute Table, Module usage inspection, and Active Edit Scope. Apply remains a separate four-operation workspace, and no schema, save, autosave, parsing, or persistence behavior changes.

The Graph-only Sidebar separation gives the visible Undo action its own common Production-surface owner and limits `Graph / 表示`, Neighborhood Steps, Merge Identical Prompts, Connect Mode, and Path Filter to Overall Edit and Focus Edit. Gallery Edit and Trash keep Undo but do not render or prepare those Graph controls. Neighborhood Steps, Path Filter, Connect Mode, graph layout, and co-occurrence display use durable session values with temporary rendered-widget mirrors, while Merge Identical Prompts continues to use `project.merge_by_word_only`. Hiding the widgets therefore does not reset their values, mutate the Project, add history, save, or run a Graph-only build. Management workspaces and the no-Project surface continue to stop before both Production sections.

PromptGraph Pro currently places daily production controls, Project management, Module / Attribute authoring, analysis, and ComfyUI environment tooling in one Streamlit sidebar. The individual tools are useful, but their combined information density makes the primary Gallery workflow harder to scan and makes ownership of settings and reusable assets unclear.

Related public boundaries are defined in [Product Boundaries](product-boundaries.md),
[Module Attribute / Semantic Slot Design](module-attribute-design.md), and [Route
Operations Design](route-operations.md). Historical app-refactor and roadmap
planning remain outside the public source tree.

The target information architecture separates controls by intent:

1. **Daily Operations**
2. **Settings / Configuration**
3. **Authoring / Maintenance**

The sidebar should become a compact daily control surface. Infrequent multi-step work should move to dedicated main-area workspaces in small, reversible PRs.

## Problem

- The sidebar mixes frequently used production controls with infrequent configuration and reusable-asset authoring.
- Project, Module, Attribute, analysis, and ComfyUI controls compete for the same narrow vertical surface.
- Some panels mix read-only inspection, preview state, and persistent mutation.
- Adding more controls to the current single sidebar would increase discoverability and Streamlit state risks at the same time.

## Goals

- inventory the live Sidebar and adjacent entry points from the current implementation;
- classify each responsibility by frequency, scope, persistence, and mutation behavior;
- define a minimal daily Sidebar and coherent destinations for Project, Module / Attribute, ComfyUI, and analysis work;
- preserve current Project, Gallery, generation, Apply, save/load, and session semantics;
- define migration slices small enough to review, test, and roll back independently.

## Non-goals

- moving controls beyond the explicitly named staged migration slice;
- replacing the session-only shell with tabs, dialogs, deep links, or Streamlit multipage navigation;
- duplicating a moved control in both the Sidebar and a workspace;
- changing Project, Module, Attribute, workflow, preset, or manifest schemas, or adding settings beyond the explicit global `projects_root_directory`;
- changing Gallery, Module / Attribute, ComfyUI, save/load, or Desktop runtime behavior;
- performing broad `app.py` decomposition;
- implementing Attribute State, LineBinding, AI authoring, multi-Project workspaces, or Illustration Set Re-assembly.

## 1. Design Constraints

- Gallery Edit remains the primary Pro v1 production workspace.
- The existing Gallery / Overall Edit / Trash mode behavior must remain stable during migration.
- No new Project, PromptLine, workflow, Module, Attribute, or navigation schema is implied by this design. The final persistent-root slice adds only the backward-compatible global `projects_root_directory` settings field.
- Project directory remains the Project identity center. A JSON filename is a save target, not the user-facing Project identity.
- Save As writes another Project JSON and switches the current save target. Duplicate Project copies the Project directory. Lightweight Fork materializes a reviewed final sequence. These operations must not be conflated.
- Selected Routes remains session-only and must be reset on Project transition.
- Existing preview-first and apply semantics remain owned by the operation being moved.
- A render function must not appear in both the sidebar and a workspace during the same Streamlit run. Duplicate widget keys and split state ownership are release blockers.
- Illustration Set Re-assembly is a future Desktop / Pro v2 direction. It is not an implemented Pro v1 workspace or analysis feature.

## 2. Classification

### 2.1 Daily Operations

Daily Operations are controls used repeatedly while producing the current illustration set:

- current Project identity and save state;
- Quick Save and Recent Projects;
- production mode and active selection summaries;
- the active generation preset and endpoint status;
- Undo;
- short launchers into Generation, Export, Module / Attribute Apply, Project Management, and Settings.

They should have low visual weight, expose immediate state, and usually complete in one action or open the relevant workspace.

### 2.2 Settings / Configuration

Settings / Configuration defines environment or Project behavior that changes less frequently:

- Project paths and save defaults;
- autosave and export defaults;
- ComfyUI endpoint and external directories;
- selected workflow or preset references;
- generation defaults;
- thumbnail and paging preferences;
- reset-to-default behavior.

Every setting must identify whether it is global, Project-local, filesystem-owned, or session-only. An Apply operation is not a setting.

### 2.3 Authoring / Maintenance

Authoring / Maintenance creates, edits, validates, or organizes reusable assets:

- Project and Global Modules;
- Attribute Groups, slots, labels, tokens, and negative metadata;
- workflow and preset inspection or authoring;
- LoRA and node mapping;
- Project recovery and validation;
- analysis that informs a later authoring decision.

These workflows are usually multi-step and should not be permanently expanded in the sidebar. Library mutation, preview, apply, and analysis must remain visibly distinct.

## 3. Current Sidebar Inventory

Frequency describes expected production use, not implementation importance. Code locations name stable render functions or the current top-level `app.py` sidebar block instead of relying only on line numbers that will drift.

| Area | Current UI label | Render function / code location | Purpose | Typical frequency | Scope | Persistence | Preview / Apply | Existing alternative entry point | Proposed destination | Release target | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Project status | Current Project / save status / autosave | top-level sidebar block in `app.py` after startup auto-open | Show current JSON path, saved time, autosave, and folder readiness | High | Project / Session | `current_project_path` and session status; filesystem | Status only | startup auto-open; Recent Projects | Sidebar / Daily Operations | Pro v1 | Keep compact; Project directory should be the primary identity shown |
| Project save | Quick Save | top-level sidebar Project block | Save the current Project to its current JSON target | High | Project | Project JSON / filesystem | Immediate apply | autosave; keyboard shortcut behavior remains separate | Sidebar / Daily Operations | Pro v1 | Keep one clear save action and save feedback |
| Project discovery / open | Projectディレクトリから選択 | `render_project_directory_browser()` in the top-level `プロジェクトを開く` expander | Discover and open current normal/Fork Projects under the effective Project root | Medium | Global / Project / Session | session-only bounded discovery snapshot and selection; Project JSON on Open | Explicit Refresh; immediate Open through the existing loader | Recent Projects; Advanced direct JSON Open | Sidebar / Daily Operations | Pro v1 | Scans only direct Project children and known `forks/<fork>/project.json`; custom JSON filenames are supported |
| Project history / open | 最近のプロジェクト | top-level `プロジェクトを開く` expander below the Directory Browser | Open a remembered Project, including external and historical paths | Medium | Global / Project | `.editor_settings.json` recent list; Project JSON | Immediate apply after selection | startup auto-open; Project Directory Browser | Sidebar / Daily Operations | Pro v1 | Remains separate from current filesystem discovery and may duplicate a Browser path |
| Project recovery | JSONファイルを直接指定して開く | top-level `Advanced` expander | Open an external, old, or recovery Project JSON | Low | Global / Project | filesystem; recent settings after success | Immediate apply | Recent Projects | Advanced | Pro v1 | Keep collapsed and clearly recovery-oriented |
| Project save target | Project JSONを別名で保存 | top-level `Advanced` expander | Save to another JSON and switch the current save target | Low | Project | Project JSON, recent projects, `last_project` | Immediate apply | Quick Save | Advanced / Project Management | Pro v1 | Not a snapshot and not a Project directory duplicate |
| Project default root | Project Defaults | `render_project_defaults_management_section()` in Project Management | Set the default parent used by future New Project forms | Low | Global | `.editor_settings.json` (`projects_root_directory`) | Explicit Save / Reset | per-Project parent override in New Project | Project Management | Pro v1 | Empty setting means built-in `<APP_ROOT>/projects`; Save/Reset create no directories and move no Projects |
| Project creation | 新規プロジェクト | `render_new_project_management_section()` in Project Management | Create a Project directory and Project JSON | Low | Global / Project | filesystem, Project JSON, recent settings | Preview destination then apply | Project Management Sidebar launcher | Project Management | Pro v1 | Relocated in Slice 2; parent folder, Project name, and JSON filename remain distinct |
| Project copy | プロジェクトを複製 | `render_duplicate_project_management_section()` in Project Management | Copy the full Project directory and open the duplicate | Low | Project | filesystem, Project JSON, recent settings | Destination validation then apply | Lightweight Fork is a different Gallery operation | Project Management | Pro v1 | Relocated in Slice 2; preserve full-directory semantics and collision safety |
| Existing Project import | 既存ProjectをProject rootへ取り込む | `render_existing_project_import_section()` in Project Management | Safely copy one external Project directory into a direct child of the effective Project root | Medium | Global / external Project / Session | copied filesystem tree; registered raw JSON paths; Recent Projects on success | Explicit Preview, checkbox, exact `COPY PROJECT`, staging validation, atomic commit | Current external Project, external Recent Projects, manual JSON path | Project Management | Pro v1 | Copy, not move; source retained; no overwrite/merge/auto-open; Browser refresh after success; see [Safe Existing Project Import](project-root-import.md) |
| Project assets | Candidate / Variant画像をProjectへ取り込む | `render_project_assets_sidebar_section()` in the top-level Sidebar | Localize referenced Generated Candidates and Gallery Variants into the Project `candidates/` folder; independently remove only verified unreferenced duplicates from Project `generated/` | Low | Project / all active non-separator Lines | Project JSON and filesystem | Copy and cleanup have separate read-only previews, confirmations, and stale guards; cleanup additionally requires SHA-256 identity and an exact phrase | Candidate cards and Gallery import | Project Management | Pro v1.1 | Project-wide and does not depend on selected Lines; copy updates Candidate/Variant paths and related lineage references; Verified Duplicate Cleanup never deletes `candidates/` or changes Project data; relocation remains v1.1 |
| Help | Help / Shortcuts | top-level sidebar expander | Explain primary workflows and shortcuts | Low | Global | none | none | in-context captions | Advanced or compact help launcher | Pro v1 | Avoid repeating feature descriptions in the daily surface |
| Graph display | グラフ設定 / Neighborhood Steps | `render_graph_sidebar_controls()` in Overall / Focus only | Control graph neighborhood display | Medium in Overall Edit / Focus Edit | Session / Focused Line | durable `graph_neighborhood_steps`; temporary widget mirror | Immediate display update | Overall Edit graph controls | Keep at current workflow location | Pro v1 | Hidden in Gallery / Trash; the durable value survives mode changes |
| Graph display | Merge Identical Prompts | `render_graph_sidebar_controls()` in Overall / Focus only | Change graph merge behavior | Low | Project | Project JSON (`merge_by_word_only`); temporary widget mirror | Immediate graph rebuild | Overall Edit | Project Settings or graph-local control | Pro v1.1 | Hidden modes neither compare nor mutate the Project value |
| Graph edit | Connect Mode | `render_graph_sidebar_controls()` in Overall / Focus only | Connect selected graph nodes | Medium in Focus / Overall Edit | Session / Focused Line | durable `connect_mode` / `connect_nodes`; temporary widget mirror | Immediate apply | Focus Edit / Overall Edit | Keep at current workflow location | Pro v1 | Preserve Lite/Pro gating and existing explicit transition resets |
| History | Undo | `render_common_undo_sidebar_section()` | Restore the previous Project snapshot | High while editing | Project / Session | history in `session_state`; Project save remains separate | Immediate apply | keyboard shortcut | Sidebar / Daily Operations | Pro v1 | Available in Gallery, Trash, Overall, and Focus; Redo is future unless separately implemented |
| Graph filter | Path Filter | `render_graph_sidebar_controls()` in Overall / Focus only | Limit graph display to selected paths | Medium in Overall Edit | Session | durable `graph_path_filter_enabled`; temporary widget mirror | Immediate display update | Overall Edit | Keep at current workflow location | Pro v1 | Hidden in Gallery / Trash and restored unchanged on return |
| Module authoring | Module Library / Creation | `render_create_module_from_scratch_section()` | Copy Modules between Global and Project libraries, create Project Modules, and replace Prompt content with Project Module references | Low to medium | Global / Project / Selected Lines | Global module JSON and Project JSON | Explicit copy or multi-step preview / mutation | PromptCloud selected-token flow | Module / Attribute Authoring | Pro v1 / Slice 4A | One outer expander with distinct Global, Project creation, and existing-Module replacement sections |
| Module discovery | AnimaDex Browser | `render_animadex_browser_section()` inside Module Library / Creation | Discover local AnimaDex data and explicitly import one reviewed Character record as a Global Module | Low | Global editor environment / Session | optional `animadex_local_path` in `.editor_settings.json`; current path, limits, and discovery summary in session | Explicit default save/clear; explicit Discover; explicit import | Global Module Library | Module / Attribute Authoring | Pro v1 | One file or directory default survives Project/workspace transitions; no Project schema, automatic scan, multi-root, or card UI |
| Attribute authoring | Attribute Groups | `render_attribute_group_sidebar_manager()` | Create and edit Project Attribute Groups | Low to medium | Project / Selected Lines | Project JSON | Library mutation | PromptCloud selected-token flow | Module / Attribute Authoring | Pro v1 / Slice 4A | Relocated; preserve unknown metadata and pure read paths |
| Attribute authoring | Attribute Group Inspector | `render_attribute_group_inspector_section()` | Edit group name, slot, tokens, labels, and negative metadata | Low | Project | Project JSON | Inspect then explicit apply | selected-token and group manager flows | Module / Attribute Authoring | Pro v1 / Slice 4A | Relocated as a non-resident multi-step editor |
| Module execution | Module Toggles | top-level Module / Attribute Apply block | Enable or disable existing Module References for active prompt / generation | High when modules are in use | Project / Session | `disabled_modules` in `session_state` only | Immediate preview behavior | Gallery generation resolves active prompt | Sidebar / Daily Operations or Module / Attribute Apply | Pro v1 | Keep a compact status/launcher; do not imply Project persistence |
| Module execution | Insert Saved Module Reference | `render_insert_saved_module_reference_section()` | Insert an existing Project Module reference into selected prompt context | Medium | Project / Selected Lines / Focused Line | Project JSON after apply | Preview / apply | Focus Edit / PromptCloud context | Module / Attribute Apply | Pro v1 | Prefer context-aware entry over permanent sidebar form |
| Module execution | Module Candidate Selection | `render_module_candidate_selection_section()` | Scan lines and preview/apply detected Module references | Medium during conversion | Project / Selected Lines | preview in session; apply to Project JSON | Preview / apply | Gallery Operations launcher | Module / Attribute Apply | Pro v1 | Analysis and mutation must remain visibly separate |
| Attribute execution | Attribute Group Swap | `render_attribute_group_swap_section()` | Swap compatible project-local Attribute Groups | Medium during route editing | Project / Route / Selected Routes / Selected Lines / Focused Line | preview in session; apply to Project JSON | Preview / atomic apply | Gallery Operations | Module / Attribute Apply | Pro v1 | Existing Gallery entry is the production-oriented path |
| Module analysis | Module Attribute Table | `render_module_attribute_table_section()` | Inspect Module tokens and Attribute Labels | Low | Project | none beyond source Project data | Read-only | Module Inspector | Sidebar Analysis | Pro v1 / Slice 5C-1B | Retained as read-only Analysis while Project Module editing moves to Authoring |
| Module authoring / inspection | Project Module Editor | `render_project_module_inspector_section()` | Edit and save Project Module body, type, Core Tokens, and Minimum Matched Tokens | Low | Current Project / Session | unsaved same-Project drafts in session; explicit Save mutates the Project Module entry | Direct edit / explicit save | Module authoring library | Module / Attribute Authoring | Pro v1 / Slice 5C-1B | Slice 5C-1A makes drafts relocation-safe; Slice 5C-1B moves the sole render owner |
| Module analysis / persistent editing context | Module Inspector / Active Edit Scope | `render_module_inspector_edit_scope_section()` with usage inspection, active-scope summary, and Edit Scope controls | Inspect usage and choose or clear the session-only edit scope | High while active | Current Project / Session | edit scope in session; inspection is read-only | Mixed read / explicit session selection | Daily prompt editing surfaces | Sidebar Analysis | Pro v1 / Slice 5B-5 | Inspector selection and active Edit Scope are distinct; successful Project replacement clears the scope |
| Module authoring | Rename Module | `render_module_rename_authoring_section()` and `render_module_rename_controls()` | Preview and rename a Module and its Line markers | Low | Project / Session | Rename mutates the active Project in memory; draft/preview are session-only | Preview / explicit apply | Module Inspector | Module / Attribute Authoring | Pro v1 / Slice 4B-2B | Authoring owns a dedicated selector; no explicit Project JSON save was added |
| Comfy settings | ComfyUI URL / Workflow JSON fallback path / Force shared workflow | `render_comfyui_settings_workspace()` | Configure the existing global endpoint and shared workflow inputs | Low | Global / Project context | `.editor_settings.json`; external workflow reference | Explicit widget change | ComfyUI Settings Sidebar launcher | ComfyUI Settings | Pro v1 | Existing logical keys; one settings write per explicit change; passive render does not save |
| Comfy daily selection | Workflow Preset / configured endpoint / resolved source and path / Force shared status | `render_comfyui_daily_sidebar_section()` | Select the active preset and inspect the effective generation configuration | High for preset; read-only for status | Global / Project context | preset in `.editor_settings.json`; status from existing session values and resolver | Explicit preset change; otherwise read-only | Gallery Generation and Focus Edit generation | Compact ComfyUI Sidebar expander | Pro v1 | No analysis, Workflow Inspector, workflow parsing, or generation execution owner |
| Workflow inspection | Comfy Workflow Inspector | `render_comfy_workflow_inspector()` | Load, paste, inspect, and validate workflow JSON | Low | Session / external workflow | raw/source plus `comfyui_analysis_workspace_drafts` in session; external file | Read-only / export helpers | Raw workflow metadata inspection | ComfyUI Settings / Analysis & Inspection | Pro v1 | Back/reopen reconstructs existing widget keys from scalar-only drafts; UploadedFile is not retained and inspected JSON is not stored in Project/settings |
| Workflow export | Prompt injection export | `render_comfy_workflow_inspector()` helpers | Export a workflow copy with prompt text injected | Low | Session / external workflow | downloaded file | Preview / export only | generation path uses its own resolver | ComfyUI Settings / Analysis & Inspection | Pro v1 | Remains export-only and does not alter production workflow selection |
| LoRA inspection / export | LoRA Directory Mapping / LoraLoader injection | `render_comfy_workflow_inspector()` helpers | Match filenames and export one mapped loader change | Low | Global / Session / external workflow | directory, scalar choice/strength drafts, and inspection results are session-only; output is filesystem/download | Preview / export only | none | ComfyUI Settings / Analysis & Inspection | Pro v1 | Back/reopen restores the directory and exposes matching retained scan results without rescanning; no new LoRA switching UI or persistence |
| Analysis | Generation Settings / Negative Prompt / Global Negative Delta | `render_comfy_workflow_inspector()` analysis helpers | Compare imported metadata and prompt settings | Low to medium | Project-wide visible Illustrations | read-only source Project data | Read-only | Gallery line metadata and diff panels | ComfyUI Settings / Analysis & Inspection | Pro v1 | Independent of Gallery/Graph Edit pages, filters, collapse, selection, and Candidate page |
| Diagnostics | 状態 / デバッグ and UI profiling | top-level sidebar debug block and `render_ui_profile_panel()` | Inspect edition, focus/edit scope, and render timing | Low | Session | `session_state` only | Read-only / clear focus action | development diagnostics | Advanced | Pro v1 | Keep collapsed and unavailable from the normal daily hierarchy |

The current inventory contains 32 user-visible responsibility groups: 10 Project/help, 5 graph/history, 10 Module/Attribute, 6 ComfyUI/workflow/analysis, and 1 diagnostics group. Several rows contain more than one widget because they share one render owner and one migration boundary.

## 4. Target Sidebar

The intended daily sidebar is:

```text
Project
  Current Project
  Save status
  Quick Save
  Project Directory Browser
  Recent Projects
  Open Project

Workspace
  Current production mode
  Active Route / Selected Lines summary
  Current generation preset

Quick Actions
  Undo
  Open Generation / Export
  Open Module / Attribute Apply
  Open Project Management
  Open ComfyUI Settings

Advanced
  Direct JSON open
  Save As JSON
  Recovery / validation
  Diagnostics
```

### Pro v1 placement

- Keep current Project, save status, Quick Save, Project Directory Browser, Recent Projects / Open, mode, selection summary, current preset, Undo, and short workspace launchers in the sidebar.
- Keep direct JSON open and Save As under collapsed Advanced.
- Keep common Undo visible in Gallery, Trash, Overall Edit, and Focus Edit.
- Keep Graph-only controls at their existing workflow location in Overall Edit and Focus Edit; do not render them in Gallery or Trash.
- Reconstruct temporary Graph widgets from durable session / Project values after a mode change.
- Keep already context-appropriate Gallery operations in Gallery Operations.
- Keep New Project and Duplicate Project exclusively owned by Project Management.

### Fork-aware Project Directory Browser

The normal Sidebar Open path uses the effective root from `default_projects_dir()` and displays its normalized absolute path. Discovery is intentionally bounded to direct-child `<root>/<project>/*.json` candidates and the known `<root>/<project>/forks/<fork>/project.json` layout. Candidate JSON is parsed only far enough to require the existing minimum PromptGraph shape (`dict` with a `prompt_lines` list); discovery does not reuse that payload as a loaded Project. The Open button always rechecks containment, regular-file status, and symlink safety before calling `load_project_json_into_session()` exactly once.

The Browser accepts custom Project JSON filenames and keeps separate entries when one Project directory contains multiple valid Project JSONs. Valid Fork `manifest.json` metadata may enrich labels with Fork name, Route/Line counts, and date, but a missing, malformed, unsupported, or source-mismatched manifest does not make an otherwise valid Fork Project JSON unopenable. Unsafe paths, Project JSON symlinks, root escapes, malformed/non-Project JSON, workflow/settings/export manifests, and duplicate real paths fail closed. Missing Fork images are diagnostic because the existing Project loader remains authoritative.

One initial bounded scan is cached in session under the normalized effective root plus a Refresh generation. Ordinary reruns, collapsed Sidebar reruns, Project path changes, and selection changes reuse the snapshot. `一覧を更新` increments the generation and performs one new discovery; root changes naturally use a new cache key. Successful New Project, Duplicate Project, Lightweight Fork creation, and a new Save As target inside the effective root request a refresh for the next Sidebar render, while failures do not. The cache and selection are never written to settings or Project/Fork JSON.

Recent Projects remains below the Browser because it owns history, including external/custom locations. Advanced direct JSON Open remains a separate recovery/external path, and Save As remains in the same closed Advanced sibling. A missing root is not created by browsing. No native picker, multiple-root input, arbitrary recursion, image scan, graph build, background watcher, persistent index, schema change, or Project Management relocation is part of this slice.

### Project Assets safety preview

The first Project Assets implementation slice keeps Project Assets in its single
Sidebar owner and makes its existing copy semantics explicit. It is not a
ComfyUI output mover: normal PromptGraph generation already downloads images
into the active Project's `generated/` directory. Project Assets scans
`generated_candidates` and `gallery_variants` across all active non-separator
Lines, copies eligible referenced image files into per-Line folders below
`candidates/`, and updates Candidate/Variant paths plus matching lineage and
source-generation references. It never moves or deletes source images.

`generated/` references remain eligible for copying. Copy and reference update
semantics are unchanged; the UI states this behavior directly instead of
describing all inputs as external. Cleanup is an independent later operation,
not an optimization inside the copy transaction.

The explicit Preview is filesystem-read-only and reports reference count,
unique source count, planned copy count, copy-not-needed count, Project-inside
and Project-outside unique source counts, estimated copy bytes, missing or
unreadable sources, and destination collision/rename count. Estimated size is
the sum of readable source sizes for each planned copy, so the same source may
contribute more than once when current semantics copy it for more than one Line.
Preview creates no directory, copies no file, mutates no Project/lineage state,
pushes no history, saves nothing, and does not rerun.

Apply requires both a stored Preview and explicit confirmation. A signature over
Project identity, Candidate/Variant references, source size/mtime state, and
planned destinations is rebuilt immediately before copying. A changed Project,
source file, missing state, or destination collision refreshes the Preview,
clears confirmation, and blocks Apply. Copying runs against a cloned Project;
copy failure removes files created by that attempt and leaves the current
Project unchanged. Project JSON is first serialized to a temporary file in the
same directory and reaches the configured path only through `os.replace()`.
Any copy, serialization, encoding, or replace failure removes the temporary
JSON and newly copied images, restores the in-memory Project and Candidate
cache, and preserves the previous Project JSON bytes. Successful Apply keeps
the existing one-save/no-history contract, synchronizes the Candidate session
cache, clears Preview and confirmation state for the next normal rerun, and
adds no explicit success rerun. Successful Project replacement clears the
operation state, while failed load and ordinary Sidebar collapse/Back/rerun
preserve the same-Project Preview.

### Verified Project Asset duplicate cleanup

Verified Duplicate Cleanup scans only image files below the current saved
Project's `generated/` source directory and `candidates/` retained-copy
directory. It is not a Project-root orphan scan, a `candidates/` deduplicator,
or an external ComfyUI output cleanup. The current Project is converted through
the normal save serialization on a clone, then nested dictionaries, lists,
tuples, and future metadata are recursively inspected for normalized
Project-local `generated/` and `candidates/` path references.

A source becomes eligible only when it is a normal non-symlink file inside
`generated/`, at least one normal non-symlink `candidates/` file has the same
size and SHA-256 and is referenced by the serialized Project, and the source
has zero serialized references. Real-path containment rejects traversal and
symlink escape. Preview is mutation-free and separates eligible, protected, and
skipped files while summing only source bytes that would be deleted.

Apply requires the stored Preview, a fresh signature covering Project path,
serialized Project/reference digests, ordered eligible sources, and
source/retained path, size, mtime, and SHA-256 state, plus the checkbox and exact
`DELETE VERIFIED DUPLICATES` phrase. Every target is revalidated before any
delete starts. Apply uses single-file removal only for the eligible
`generated/` sources; it never changes `candidates/`, Project objects, Project
JSON, history, Candidate/Variant records, lineage, directories, or schemas.
Deletion is complete rather than Trash/Recycle Bin based, so PromptGraph cannot
restore a removed source path. A mid-delete IO failure stops immediately and
reports completed, failed, and remaining files; validation failure deletes
nothing. Project transition, Project Assets copy Apply, successful cleanup, and
partial cleanup clear the cleanup Preview, while ordinary production-mode
switches do not.

### Pro v1.1 placement

- Move remaining Project maintenance and diagnostic forms into Project Management only when their existing behavior and ownership are explicit.
- Move Project Assets localization into Project Management.
- Move Module / Attribute libraries and editors into Authoring.
- Keep read-only workflow inspection and mapping in ComfyUI Settings; move only future preset/workflow mutation into ComfyUI Workflow / Preset Authoring.
- Keep only active state and launchers in the sidebar.
- Split UI modules only after behavior and state ownership are covered by focused tests.

## 5. Project Management Workspace

One Project Management workspace is sufficient for the first migration. Project Defaults, New Project, Duplicate Project, and Safe Existing Project Import are now exclusively rendered there in that order. Project Defaults owns the global `projects_root_directory` setting; an empty stored value resolves to the portable built-in `<APP_ROOT>/projects` fallback. Existing Project Import is a Preview-first copy operation for external Projects: it stages and validates registered raw JSON/Fork path rebasing before an atomic direct-child commit, preserves the source and external dependencies, and updates Recent/Browser discovery without auto-opening. The same effective root is browsed from the Sidebar, but the Browser does not move root editing or Project creation into the open flow. The other entries below remain the target information architecture rather than a claim that they have already moved. The workspace may later split into Management and Settings if density justifies it.

```text
Project Management

Defaults
  Default Project root

Daily
  Current Project summary
  Save state
  Quick Save
  Recent Projects
  Open Project
  New Project

Management
  Project directory and JSON target
  Duplicate Project
  Import Existing Project into Project Root
  Project assets
  Lightweight Fork links and related Projects
  exports and workflows directories
  metadata inspection
  recovery / backup / validation
  direct JSON open
  Save As JSON
```

Semantics that must remain explicit:

- The Project directory is the identity center.
- The configured Project root is the default for future New Project forms and the bounded Sidebar discovery root. It is not a filesystem sandbox: a per-Project parent override remains supported, external Projects remain openable through Recent/Advanced, and existing Projects are never moved.
- Saving or resetting the root writes only global settings and creates no directory. A missing configured root is created only by actual New Project creation.
- The Project JSON filename is the active save target.
- Save As switches the save target.
- Duplicate copies the directory and opens the copy.
- Existing Project Import copies an external directory through hidden staging, rewrites only explicit known path fields, leaves the source untouched, and opens the imported copy only on a separate explicit action.
- Lightweight Fork is final-sequence materialization and remains a Gallery operation, with Project Management showing only discoverability or relationship information.
- successful open/create/duplicate updates Recent Projects and `last_project` according to existing rules;
- startup auto-open is attempted once per session;
- Project transition resets Project-bound session state and stale previews;
- an unsaved Project must not be silently replaced by navigation.

## 6. Module / Attribute Apply Versus Authoring

### Apply

Apply uses existing assets against current production content:

- Module Toggles;
- Insert Saved Module Reference;
- Module Candidate scan and detected reference apply;
- Module Swap;
- Attribute Group Swap;
- current Project Module / Attribute status relevant to the chosen target;
- preview and apply for focused Line, selected Lines, Route, or Selected Routes.

The main production entry should remain Gallery Operations or another context-aware Apply panel. A sidebar entry should be a status summary or launcher, not a second copy of the full form.

### Authoring

Authoring changes reusable assets:

```text
Module / Attribute Authoring

Library
  Project Modules
  Global Modules
  Attribute Groups

Editor
  selected asset details
  body tokens
  Core / Optional state
  type and match rules
  slot and labels
  negative metadata
  validation

Usage / Analysis
  usage counts
  matching Lines
  related Groups
  read-only previews
```

Global Module Library records and Project Module records must remain different assets. Copying between them is explicit; there is no live synchronization. Attribute Groups, custom labels, and usage counts remain Project-owned. Analysis may inform authoring but must not mutate the library merely because the workspace rendered.

The current `Module Library / Creation` hierarchy presents Project → Global as a copy to the user-level library and Global → Project as a copy into the current Project. Blank Project Module creation changes only the Project Module Library. Creating a Module from Prompt content may optionally replace selected targets after preview, while `Replace with Existing Module` uses a saved Project Module and creates no new Module. The Global Module Library heading owns one session-only free-text search shared by Global → Project and Manage Global Modules. It uses NFKC + case-folded whitespace-term AND matching over already-loaded Module names, categories, prompt content, descriptions/notes, and existing Attribute / Variant metadata; Manager category filtering is an additional AND condition. Project → Global remains unfiltered because it selects Project-owned Modules, and AnimaDex search remains independent. The query and in-memory library cache survive workspace/mode/Project transitions but are never persisted. Passive search performs no filesystem rescan or persistent indexing. Explicit writes reload the latest JSON before mutation and reload the normalized persisted Library afterward, so unrelated concurrent changes survive and the cache remains authoritative; failed saves retain the previous cache. No schema, storage format, history, focus restoration, or save contract changes. Folders, tags, custom collections, and category expansion remain Pro v1.1 or later slices.

Slice 4A implements the three already-standalone authoring panels: Persistent Module Library / Create Module, Attribute Groups, and Attribute Group Inspector. Slice 4B-1 gives the complete mixed Module Inspector / Edit Scope / Rename Module block one named render owner while leaving the panel in the Sidebar. Slice 4B-2A splits its implementation into responsibility-specific child renderers. Slice 4B-2B then relocates only Rename Module into Module / Attribute Authoring through `render_module_rename_authoring_section()`. Rename has an Authoring-owned selector plus Project-bound durable selection, new-name draft, and preview state. Conditional widget keys mirror those durable values so Back preserves same-Project work; successful Project transitions clear both durable and temporary keys. Module usage inspection remains under Sidebar Analysis ownership, and Slice 5B-5 formalizes session-only Module Edit Scope there as persistent daily editing context. Rename validation, preview, history, disabled-state and Edit Scope migration, Focus restoration, synchronization, and in-memory Project mutation are unchanged, and no explicit Project JSON save is added. Existing selected-token Attribute Label, Attribute Group, Core / Optional, and Module creation entry points remain contextual to PromptCloud rather than being duplicated in the workspace.

## 7. ComfyUI Separation

### Daily generation selection

Keep close to Gallery generation:

- active Workflow Preset;
- configured endpoint text;
- effective workflow source;
- effective workflow path;
- compact Force shared workflow status;
- only generation defaults that are changed routinely.

This layer selects existing configuration and displays state already available from the current settings and resolver. It does not probe the network, report a last connection result, author a workflow, parse Workflow JSON, or run analysis. Workflow Inspector and both consistency panels render only in ComfyUI Settings.

### Settings / Environment

Slice 3 moves these existing controls to ComfyUI Settings:

- endpoint;
- workflow JSON fallback path;
- Force shared workflow.

The workspace also shows the active preset and resolved source/path as read-only status, then owns an Analysis & Inspection section containing Generation Settings Consistency, Negative Prompt Consistency, and the existing Comfy Workflow Inspector composite. It does not add connection testing, polling, timeouts, output directory settings, reset/default actions, Project-local settings, or preset authoring. Global settings and Project-local references remain separate ownership domains, and no new schema is introduced.

### Analysis & Inspection

ComfyUI Settings owns the existing read-only composite:

- workflow JSON upload, paste, shape inspection, and node summaries;
- Generation Settings Consistency across the Project-wide visible Illustration collection;
- Negative Prompt Consistency and Global Negative / Delta Preview across the same authoritative collection;
- positive / negative text encode, KSampler, checkpoint, LoRA, VAE, and save-node inspection;
- existing export-only Prompt and LoRA helpers.

Current workflow files remain external JSON. Settings store selected references, not an embedded replacement workflow. Uploaded or pasted inspection values remain session-only. Invalid, empty, and unsupported JSON produces a local warning/error without changing Project, settings, production workflow selection, or generation state. Future preset create/rename/delete and actual Workflow editing remain separate Workflow / Preset Authoring work.

## 8. Analysis Placement

Analysis should stay near the decision it supports:

| Analysis | Pro v1 placement | Future placement |
| --- | --- | --- |
| Source/current Prompt and Negative Prompt drift | Gallery line context | Gallery / Lineage detail |
| Candidate and Module matching | Module / Attribute Apply | Apply workspace |
| Module Attribute Table | Sidebar Analysis | Sidebar Analysis |
| Module usage and Active Edit Scope | Sidebar Analysis | Sidebar Analysis |
| Project Module editing and inspection | Module / Attribute Authoring | Module / Attribute Authoring |
| Generation Settings Consistency | ComfyUI Settings / Analysis & Inspection | Generation Profile authoring only if later implemented |
| Negative Prompt Consistency / Global Negative Delta | ComfyUI Settings / Analysis & Inspection | Persistent Global Negative design only if later implemented |
| Workflow shape and node mapping | ComfyUI Settings / Analysis & Inspection | Workflow editing remains future Authoring work |
| LoRA mapping and export helper | ComfyUI Settings / Analysis & Inspection | LoRA switching/library redesign remains future work |
| recovery and malformed-state diagnostics | Advanced | Project Management diagnostics |

Pro v1 should not add a standalone Analysis workspace. The current analyses are supporting views, not a coherent independent daily task. Illustration Set analysis, state extraction, reconstruction, and Re-assembly remain future work.

## 9. Navigation Options

### Option A: Extend the current mode selector

Add Project Management, Module / Attribute Authoring, and ComfyUI Settings beside Gallery / Overall Edit / Trash.

Benefits:

- one visible navigation model;
- straightforward exclusivity between screens.

Costs:

- production modes and maintenance destinations become mixed concepts;
- existing mode state and reset behavior become more fragile;
- the primary mode selector becomes crowded.

### Option B: Sidebar launcher plus session-only workspace target

Keep Gallery / Overall Edit / Trash unchanged. A compact launcher opens one exclusive main-area management or authoring workspace. Closing it returns to the prior production mode.

Benefits:

- smallest Pro v1 navigation change;
- preserves existing production mode semantics;
- supports exclusive rendering and gradual migration;
- does not require schema persistence.

Costs:

- needs a clearly owned session key and reset behavior;
- back/close behavior must be obvious;
- deep links are not persistent.

### Option C: Streamlit multipage

Move management and authoring into Streamlit pages.

Benefits:

- strongest visual separation;
- potentially cleaner long-term navigation.

Costs:

- highest migration risk for the current single-script session model;
- hidden-widget cleanup, shared Project state, history, and rerun behavior need broader redesign;
- likely duplicates or bypasses existing render ownership during transition.

### Recommendation

Use **Option B** for Pro v1 staged implementation. Introduce one session-only workspace target and render either the production mode or one dedicated workspace, never both copies of the same panel. Re-evaluate Option A or C only after the workspace boundaries and service APIs are stable.

## 10. State Ownership

| State / Asset | Current owner | Proposed owner | Persistence | Reset trigger | Migration concern |
| --- | --- | --- | --- | --- | --- |
| Current Project path | `st.session_state.current_project_path` | Project session coordinator | session-only pointer to filesystem | Project open/create/duplicate | Navigation must not replace it implicitly |
| Recent Projects | settings helpers | Project Management / startup service | `.editor_settings.json` | successful Project operation | Preserve order, deduplication, and maximum count |
| Last Project | settings helpers / startup auto-open | startup service | `.editor_settings.json` | successful operation according to existing `remember_project` policy | Fork registration may update recent without changing last |
| Project root / new parent | Project Defaults and New Project UI through `default_projects_dir()` | Project Management | global `.editor_settings.json` key `projects_root_directory`; empty means `<APP_ROOT>/projects`; form parent remains session-only | explicit root Save/Reset or manual per-Project change | Root is a default, not a sandbox; no Project JSON, Recent Projects, startup, or filesystem mutation on root Save/Reset |
| Autosave state | top-level app/session save flow | Project session coordinator | Project JSON plus session timestamps/status | Project transition | One save owner; workspace render must not autosave by itself |
| Project Module Library | `Project.module_library` | Module / Attribute Authoring | Project JSON | Project transition | Preserve unknown fields and active Module Reference semantics |
| Global Module Library | `core.io` global library helpers | Module / Attribute Authoring | global filesystem JSON | explicit load/save/copy | Never imply live sync with Project Modules |
| Attribute Groups | `Project.attribute_groups` | Module / Attribute Authoring | Project JSON | Project transition | Read-only rendering must not normalize/mutate live data |
| Custom Attribute Labels | Project token metadata fields | Module / Attribute Authoring | Project JSON | Project transition | Keep separate from Global Module records |
| Attribute usage counts | Project attribute metadata | Module / Attribute Authoring / analysis | Project JSON | Project transition or explicit update | Define recomputation separately from rendering |
| ComfyUI endpoint | settings and workspace widget | ComfyUI Settings; compact status in Daily | `.editor_settings.json` | explicit settings change | Avoid writing on unrelated reruns |
| Workflow path | settings and workspace widget | ComfyUI Settings | `.editor_settings.json` reference to external JSON | explicit settings change | Path reference is not workflow ownership |
| Force shared workflow | settings and workspace widget | ComfyUI Settings; compact status in Daily | `.editor_settings.json` | explicit settings change | Preserve embedded Line workflow behavior and existing resolver precedence |
| Workflow JSON | external file or imported line metadata | filesystem / source metadata; editor only by explicit export | external workflow / Project metadata where already imported | file selection or Project transition | Do not silently persist uploaded/pasted inspection JSON |
| Selected Workflow Preset | settings and sidebar widget | Daily selection; read-only status in ComfyUI Settings | `.editor_settings.json` | explicit selection | Keep effective workflow fallback order unchanged |
| LoRA directory | workflow inspector widget | ComfyUI Settings or Authoring | currently `session_state` only | Project/session reset unless persistence is designed | Do not invent settings persistence during UI move |
| Node mapping / inspected workflow | workflow inspector session state | ComfyUI Settings / Analysis & Inspection | `session_state` only or exported file | workflow change / Project transition | Avoid stale mapping against another workflow; no production workflow mutation |
| Generation defaults | distributed generation widgets/settings | Generation / ComfyUI Settings | existing settings or session keys, depending on control | Project transition or explicit reset | Inventory each key before moving; do not merge owners |
| Current Gallery selections | Gallery widgets | Gallery | `session_state` only | Project transition and structural sanitization | Hidden widget cleanup must not erase durable logical selection |
| Selected Routes | `gallery_selected_route_ids` plus temporary checkbox keys | Gallery | `session_state` only | Project transition; sanitize after structural changes | Must remain session-only; logical state and widget state stay separate |
| Gallery operation scope presentation | static capability metadata plus the existing Selected Routes owner | Gallery Operations | no new durable state | ordinary render | Display-only matrix; each operation remains authoritative for scope, Preview, and Apply |
| Preview plans | operation-specific session keys | owning operation workspace | `session_state` only | input change, Project transition, successful apply | Reset all moved preview keys; stale guards remain operation-specific |
| Active Gallery operation | `gallery_operations_active` | Gallery Operations | `session_state` only | Project transition / close | Do not reuse as a global workspace router |
| Current authoring selection | multiple Module/Attribute/workflow widget keys | owning Authoring workspace | `session_state` only unless asset mutation is explicitly applied | Project transition / asset removal | Hidden widget cleanup requires durable logical state where selection must survive |
| History / Undo | app session history | Project session coordinator | `session_state` only | Project transition | One successful multi-step apply should create one history entry |

## 11. Staged Migration

Each slice should be independently revertible and should not combine behavior refactoring with UI relocation.

### Slice 1: Workspace shell (implemented)

- User-visible change: add compact Project Management, Module / Attribute Authoring, and ComfyUI Settings launchers with a close/back action.
- Moved functions: none.
- Retained entries: all current sidebar panels.
- State keys: `active_management_workspace` is the only new logical state. Existing Gallery / Overall Edit / Trash / Focus Edit state remains unchanged, so no previous-production-mode key is needed.
- Rendering: a valid target renders one placeholder shell before production mode controls and stops the run before the production main view. Invalid targets normalize to inactive.
- Project transition: successful open, startup auto-open, new Project, duplicate Project, and prompt import transitions reset the workspace target. Failed open/create paths do not reset it.
- Risks: navigation loop, stale workspace after Project switch.
- Tests: launcher routing, allowed targets, exclusive rendering, production-state preservation, Project-transition reset, and documentation boundaries.
- Rollback: remove launcher and workspace shell only.

### Slice 2: Project Management (implemented)

- User-visible change implemented: Project Management owns Project Defaults, New Project, and Duplicate Project in that order; the Project Management launcher is their Sidebar entry point.
- Renderers: `render_project_defaults_management_section()`, `render_new_project_management_section()`, and `render_duplicate_project_management_section()` are exclusive workspace owners.
- Settings boundary: `projects_root_directory` is global and backward-compatible. Empty means built-in `<APP_ROOT>/projects`; explicit Save/Reset writes settings once, creates no directory, and does not move or save a Project. New Project keeps its manual parent override and can explicitly restore the configured default.
- Retained entries: Daily Project summary, Quick Save, Project Directory Browser, Recent Projects / Open, Advanced direct JSON and Save As, and the existing Project Assets Sidebar entry until the Pro v1.1 relocation. Direct JSON remains the current recovery path and also handles external locations; bounded root discovery is the normal current-filesystem path.
- State keys: existing Project form widget keys and current path/status keys are preserved; `_projects_root_directory_widget` is temporary editor state, while Project Assets widget and localization behavior remain owned by the current Sidebar entry.
- Risks: double-rendered keys, altered Save As semantics, missed Project transition reset.
- Tests: root settings helpers, Save/Reset isolation, open/new/save-as/duplicate behavior, Recent/last rules, startup auto-open, and exclusive widget ownership.
- Rollback: remove the settings key/helpers and Project Defaults renderer, restore `<APP_ROOT>/projects` initialization, and keep Project data untouched.
- The final persistent-root item is implemented in code and was verified with
  the workspace-separation slices.

### Slice 3: ComfyUI Settings (implemented)

- User-visible change: the existing ComfyUI URL, workflow JSON fallback path, and Force shared workflow controls render exclusively in the Environment section of ComfyUI Settings. The workspace read-only status shows the active preset plus the resolved workflow source/path. Analysis & Inspection owns Generation Settings Consistency, Negative Prompt Consistency, and the existing Comfy Workflow Inspector composite.
- Moved functions: `ensure_comfy_settings_session_state()`, `update_comfy_settings()`, and `render_comfyui_settings_workspace()` own initialization and explicit global settings changes. `render_comfy_workflow_inspector()` retains its composite implementation and existing widget keys but now has one workspace call owner rather than a Sidebar owner. Generation execution did not move.
- Retained entries: `render_comfyui_daily_sidebar_section()` keeps Workflow Preset selection, configured endpoint text, effective workflow source/path, and compact Force shared status. It does not render analysis, Inspector upload/paste, workflow parsing, or generation execution.
- State keys: `comfy_url`, `comfy_workflow_path`, `comfy_workflow_preset`, and `force_shared_comfy_workflow` remain the widget/session keys. Persistence remains `comfyui_url`, `comfyui_workflow_path`, `comfyui_workflow_preset`, and `force_shared_comfy_workflow` in `.editor_settings.json`.
- Persistence: initialization and normal rendering do not save. Each explicit widget change updates the existing settings object from the new widget values and calls `save_settings()` once. Project JSON is not written.
- Analysis scope: both consistency panels use the existing Project-wide `get_visible_prompt_lines(project)` collection. They do not follow Gallery/Graph Edit page, Scene filter/collapse, selected Scene/Illustration, or Candidate-page state. With no Project they render compact empty states while Workflow Inspector upload/paste remains available.
- Preserved behavior: `resolve_effective_comfy_workflow_path()` and embedded Illustration, force-shared, configured path, and preset fallback precedence are unchanged. Gallery and Focus Edit generation continue to consume the existing session keys. Workflow Inspector remains read-only/export-only and keeps upload/paste precedence and session lifecycle.
- Not added: connection probe/last-result status, polling, new settings, preset authoring, Project-local configuration, workflow/schema mutation, generation relocation, or LoRA switching UI.
- Remaining later slice: Workflow / Preset Authoring for actual preset or Workflow mutations; analysis and inspection are no longer waiting for that slice.
- Tests: routing, one render owner per widget/composite, passive Sidebar zero-call behavior, initialization and render-time no-save behavior, explicit persistence, no-Project rendering, Project-wide scope, invalid/empty Workflow handling, unchanged resolver/generation wiring, Back/Project transition preservation, and documentation boundaries.
- Rollback: restore the composite's former Sidebar call owner and remove its workspace call; Environment settings, schemas, and core models need no rollback.

### Slice 4: Module / Attribute Authoring (implemented)

Implemented in Slice 4A:

- User-visible change: the Module / Attribute Authoring launcher opens a real exclusive workspace. With no active Project it shows a safe informational state and does not create or open one.
- Moved functions: `render_create_module_from_scratch_section()`, `render_attribute_group_sidebar_manager()`, and `render_attribute_group_inspector_section()` now have one render owner in `render_module_attribute_authoring_workspace()`.
- Ownership: Project Modules, Attribute Groups, custom labels, usage counts, negative metadata, and Project-specific Module metadata remain Project-owned. Global Module Library files and their configured directory remain global/user-owned, and every copy remains explicit.
- State keys: Project-specific Module creation/replacement drafts and previews plus Attribute Group manager/inspector selections, edits, previews, and confirmations reset only after successful Project transitions. Existing `selected_node_ids` cleanup remains in the Project transition coordinator. Global Module Manager selection/drafts, the selected Global Module to load, the session-only Global Module Library search query/cache, global settings, and ComfyUI settings are not cleared. Back changes only the workspace target.
- Mutation boundary: normal workspace rendering and preview remain non-mutating for Project data and do not write Project JSON or Global Module files. Explicit create/edit/delete/copy actions retain their existing history and save behavior. Unknown Module and Attribute Group metadata is preserved; negative metadata and NegativeAttribute preview do not modify Line negative prompts.

Retained in this slice:

- Module / Attribute Apply, including Module Toggles, saved reference insertion, Module Candidate Selection, and Attribute Group Swap, remains in the Sidebar / Gallery.
- Module usage inspection and the other Module / Attribute Analysis panels remain in the Sidebar.
- At this Slice 4B-2A stage, session-only Module Edit Scope remained in the Sidebar pending the later ownership decision.
- Contextual selected-token Attribute Label, Attribute Group, Core / Optional, and Module authoring remains with PromptCloud.
- No schema, matching, Module Candidate Apply, Module Swap, Attribute Group Swap, persistence, or parsing semantics changed.

Implemented in Slice 4B-1:

- The complete mixed Module Inspector / Edit Scope / Rename Module block now has one named render owner: `render_module_inspector_edit_scope_section()`.
- The renderer remains in the Sidebar in the same render order; there is no user-visible relocation.
- All existing widget keys, state, preview, Apply, history, focus restoration, synchronization, and rename semantics remain unchanged.
- The extraction provides a stable boundary for later ownership decisions.

Implemented in Slice 4B-2A:

- `render_module_inspector_edit_scope_section()` remains the only outer Sidebar owner of the unchanged expander, Project branches, report construction, sorted Module list, missing-scope cleanup, shared `module_inspector_selected` selector, separators, and no-Module behavior.
- `render_module_usage_inspection()` owns read-only usage metrics, library and affected-Line details, malformed warnings, and the 20-Line limit.
- `render_module_edit_scope_controls()` owns the Free/Pro gate, session-only Edit Scope actions and preview, metrics, examples, and the 10-example limit.
- `render_module_rename_controls()` owns the Free/Pro gate, stale-preview and validation guards, preview/confirm/cancel flow, history, disabled/scope migration, focus restoration, synchronization, cleanup, and reruns.
- The three child renderers receive the same selected Module from one shared selector. The outer expander, Sidebar position, display order, wording, widget/session keys, behavior, preview, Apply, history, parsing, and persistence remain unchanged.

Implemented in Slice 4B-2B:

- `render_module_rename_authoring_section()` owns the Rename expander, the unchanged `inspect_modules()` universe, the sorted Module list, no-Module state, and dedicated `_module_rename_selected_widget` selector.
- `module_rename_selected`, `module_rename_new_name`, and `module_rename_preview` are durable same-Project logical state. `_module_rename_selected_widget` and `_module_rename_new_name_widget` are conditional widget mirrors.
- Back changes only the workspace target, so Rename selection, draft, and preview survive reopening. Successful Project transitions clear all five durable/temporary Rename keys.
- `render_module_inspector_edit_scope_section()` now renders only the shared Sidebar selector, usage inspection, one separator, and Module Edit Scope. It no longer renders Rename.
- Rename validation, stale-preview handling, preview metrics/examples, one history entry, one `rename_module()` call, Edit Scope and disabled-state migration, Focus restoration, text-area synchronization, Cancel behavior, and reruns remain unchanged.
- Rename continues to mutate the active Project in memory after explicit confirmation. It does not add `save_project()`, autosave, or another Project JSON persistence path.

- Risks: live Project mutation during render, Global/Project library confusion, widget cleanup.
- Tests: source Project deep-equality before explicit apply, no render-time filesystem writes, unknown metadata preservation, successful Project-switch cleanup, Back preservation, one Rename render owner, widget-key uniqueness, and unchanged Rename confirm order.
- Rollback: restore the Rename child call and second separator in the Sidebar outer renderer, remove `render_module_rename_authoring_section()`, restore the direct Rename widget state, remove Rename keys from Authoring Project-transition cleanup, and revert focused tests/docs. No schema, Project migration, core-operation, or settings rollback is required.

### Slice 5: Module / Attribute Apply and contextual analysis

Implemented in Slice 5A:

- The complete existing Module / Attribute Apply Sidebar block now has one named render owner: `render_module_attribute_apply_sidebar_section()`.
- The renderer owns the unchanged Apply subheader and caption, the `Module Toggles` expander, its session-only `disabled_modules` actions, and exactly one call each to `render_insert_saved_module_reference_section(project)`, `render_module_candidate_selection_section(project)`, and `render_attribute_group_swap_section(project)` in that order.
- The surrounding Sidebar separators remain top-level owners, and the section remains immediately before Module / Attribute Analysis.
- Module iteration, checkbox labels, dynamic `mod_toggle_{mod_id}` keys, enabled/disabled meaning, no-Project/no-Module messages, and rerun behavior are unchanged.
- No user-visible relocation occurred. No widget key or session-state key changed, and no Apply, preview, history, Focus, scope, parsing, schema, save/load, or persistence semantics changed.
- Module Edit Scope and supporting Analysis remain outside this renderer in their current Sidebar ownership.
- Rollback is limited to inlining the renderer body at the existing top-level call site and reverting focused tests/docs. No schema, Project, core-operation, settings, or session-state migration is required.

Implemented in Slice 5B-1:

- `module_attribute_apply` is a session-only exclusive workspace target that continues to use `active_management_workspace` as the only routing state.
- The compact `Open Apply Workspace` launcher is owned only by the retained Sidebar Apply section. It is disabled without a Project and is not added to the general management/configuration launcher group (Project Management / Module / Attribute Authoring / ComfyUI Settings) or Gallery Operations.
- `render_module_attribute_apply_workspace()` renders focused production guidance and calls `render_module_toggle_controls(project)` as the only Module Toggle render owner.
- Module Toggles moved from the Sidebar to a main-area `st.expander()` with the same label, order, dynamic `mod_toggle_{mod_id}` keys, messages, and enable/disable behavior.
- `disabled_modules` remains the sole logical Toggle state. Conditional checkbox widgets derive their values from it each time the workspace opens; no parallel state, Project field, or settings key was added.
- Back changes only `active_management_workspace`, preserving disabled Modules, Gallery / Trash / Focus state, highlighted and selected content, Selected Routes, Gallery operation focus, existing Apply previews, Module Edit Scope, history, and the current Project/path.
- Successful Project transitions continue to close the exclusive workspace through the existing coordinator. Failed validation/load paths do not gain a new reset.
- The retained Sidebar Apply section continues to render saved Module reference insertion, Module Candidate Selection, and Attribute Group Swap in the same order with unchanged preview, history, Focus, scope, Free / Pro, and persistence behavior.
- Module usage inspection and Module Edit Scope remain under Sidebar Analysis. Gallery Operations and Authoring gain no Apply launcher or Toggle copy.
- No schema, Project migration, history/save ownership, settings, or persistence change is part of the relocation.
- Rollback removes the target, shell route, workspace wrapper, and compact launcher, then inlines the unchanged Toggle block back into the Sidebar Apply renderer. No schema, Project, settings, core-operation, preview-state, or session-state migration is required.

Implemented in Slice 5B-2A:

- Saved Module Reference Insertion remains in the retained Sidebar Apply section in the same position and child order. No user-visible relocation occurred.
- `insert_module_reference_type_filter`, `insert_module_reference_name`, `insert_module_reference_line_id`, `insert_module_reference_scope`, `insert_module_reference_position`, `insert_module_reference_learned_neighbor_fallback`, and `insert_module_reference_anchor` now own durable same-Project input state. `insert_module_reference_preview` remains the durable preview owner.
- The seven rendered controls use matching temporary `_insert_module_reference_*_widget` keys. `prepare_insert_module_reference_widget_state()` reconstructs missing widget state and normalizes invalid dynamic options to the existing defaults.
- Module filter changes, Module rename/deletion, target-Line changes, unavailable scopes, reduced position options, fallback hide/show, and anchor changes retain their existing option universes while invalid durable values safely normalize.
- Back changes only `active_management_workspace`, so the durable inputs and matching preview survive. Reopening the Sidebar reconstructs temporary widget state without silently regenerating or clearing a stale preview.
- `reset_insert_module_reference_project_session_state()` clears the seven durable inputs, preview, and seven temporary widget keys only at the existing successful Project load/create/import transition points. Failed transitions and Back preserve them.
- Preview signatures, stale-preview blocking, one history entry, one core Apply call, Focus restoration, text-area synchronization, successful preview cleanup, Free / Pro gates, and Sidebar ownership are unchanged.
- No Project/settings schema, filesystem persistence, save/autosave, core insertion algorithm, Module/Attribute schema, or Global Attribute Group behavior changed.
- Rollback restores the direct widget keys, removes the binding/reset helpers and successful-transition calls, and reverts focused tests/docs. No schema, Project, settings, prompt-data, or preview-data migration is required.

Implemented in Slice 5B-2B:

- `render_insert_saved_module_reference_section(project)` moved from the retained Sidebar Apply section into `render_module_attribute_apply_workspace()` and now renders through one main-area `st.expander()`.
- The Apply workspace obtains the current Project once and renders exactly Module Toggles followed by Saved Module Reference Insertion. It does not render Module Candidate Selection, Attribute Group Swap, Module Edit Scope, or analysis/authoring controls.
- The retained Sidebar Apply section still owns the single contextual `Open Apply Workspace` launcher and now renders only Module Candidate Selection followed by Attribute Group Swap.
- The seven durable inputs, seven temporary widget keys, `prepare_insert_module_reference_widget_state()`, `reset_insert_module_reference_project_session_state()`, and all successful Project-transition reset calls from Slice 5B-2A are unchanged.
- Back hides the insertion operation without clearing durable inputs or `insert_module_reference_preview`. Reopening reconstructs temporary widget state; a matching preview remains current, while a mismatching preview remains stale and cannot Apply.
- The preview signature, target/scope resolution, stale guard, one history entry, one bulk Apply call, Focus restoration, text-area synchronization, successful preview cleanup, and durable input preservation after Apply are unchanged.
- No Project/settings schema, filesystem persistence, explicit Project save, autosave, core insertion algorithm, Module Toggle behavior, Global Attribute Group behavior, or general/Gallery launcher was added.
- Rollback restores `st.sidebar.expander()` in the insertion renderer, removes its Apply-workspace call, restores its Sidebar call before Candidate Selection, and reverts guidance, ownership tests, and docs. The Slice 5B-2A durable state and reset helpers remain intact; no schema or data migration is required.

Implemented in Slice 5B-3A:

- Module Candidate Selection remains the first retained child in the Sidebar Apply section, immediately before Attribute Group Swap. Its renderer still uses `st.sidebar.expander()` and does not render in the Apply workspace.
- `module_candidate_selection_name` remains the durable selected Module. `module_candidate_core_tokens_{module_name}` and `module_candidate_min_match_tokens_{module_name}` remain durable unsaved per-Module drafts.
- `_module_candidate_selection_name_widget`, `_module_candidate_core_tokens_widget_{module_name}`, and `_module_candidate_min_match_tokens_widget_{module_name}` are the rendered controls. Missing widget state reconstructs from durable values before rendering.
- An explicitly empty Core Tokens draft stays empty across Module switching and workspace Back. Partially invalid selections keep valid survivors in their existing order; a formerly non-empty selection with no survivors falls back to the current saved Core Tokens rather than silently broadening the draft. Minimum Match normalizes to an integer in `1 .. len(module_tokens)` and is not clamped to the Core Token count.
- `module_candidate_preview` and `module_candidate_apply_preview` keep their existing `module_name`, `core_tokens`, and `min_match_tokens` signatures. Hidden-widget cleanup does not regenerate or clear either preview. Matching previews remain current; changed or normalized inputs make them stale, stale Candidate preview blocks Apply-preview controls, and stale Apply preview cannot confirm.
- `pending_module_candidate_selection` still selects a newly created valid Module once through `module_candidate_pending_applied`; normal user selection wins afterward, and Preview Candidates retains its existing pending-key cleanup.
- Save Rules still owns one history entry and one `set_module_candidate_rules()` call, with no rerun, preview cleanup, explicit Project save, or autosave. Confirm Apply still owns one history entry, Focus capture/restoration, one `apply_module_candidates()` call, text-area synchronization, both preview removals, and one rerun. Durable selection and per-Module drafts survive both actions.
- `reset_module_candidate_project_session_state()` clears only Candidate Selection fixed keys, dynamic durable drafts, dynamic temporary widgets, previews, and pending handoff state. It runs beside the insertion reset at the existing successful Project load/create/import transition points. Back, failed transitions, normal reruns, selection changes, Save Rules, previews, and Confirm Apply do not call it.
- No Candidate matching or replacement algorithm, preview payload, Project/settings schema, Project JSON persistence, settings write, save/autosave path, Candidate scope, Line selection, Route support, or generic workspace-state framework changed.
- Rollback restores the three direct widget keys, removes the Candidate hydration/reset helpers and successful-transition calls, and reverts focused tests/docs. Candidate core operations, saved rules, preview payloads, Project/settings schema, and prompt data require no migration or rollback.

Implemented in Slice 5B-3B:

- `render_module_candidate_selection_section(project)` moved from the retained Sidebar Apply section into `render_module_attribute_apply_workspace()` and now renders through one main-area `st.expander()`.
- The Apply workspace obtains the current Project once and renders exactly Module Toggles, Saved Module Reference Insertion, then Module Candidate Selection.
- The retained Sidebar Apply section still owns the single contextual `Open Apply Workspace` launcher and now renders only Attribute Group Swap.
- The Slice 5B-3A durable state, temporary underscore widget keys, two preview signatures (`module_name`, `core_tokens`, `min_match_tokens`), stale guards, pending-Module handoff, and `reset_module_candidate_project_session_state()` remain intact.
- After a selected-token Module is created, `Use this module in Candidate Selection` preserves the existing pending-Module state and opens `module_attribute_apply`, so the relocated control is immediately visible. The pending Module is still applied once, and later manual selection still wins.
- Back hides Candidate Selection without clearing its durable drafts or previews. Reopening reconstructs missing temporary widgets; matching previews stay current, while changed or normalized inputs keep the existing stale-preview blocks.
- Save Rules still owns one history entry and one rule mutation. Confirm Apply still owns one history entry, Focus restoration, one Apply, text-area synchronization, preview cleanup, and one rerun. Neither adds an explicit Project save.
- No Candidate matching or replacement algorithm, Project/settings schema, persistence, scope, Line/Route selection, core operation, or general/Gallery launcher changed.
- Rollback restores `st.sidebar.expander()` in the Candidate renderer, removes its Apply-workspace call, restores its Sidebar call before Attribute Group Swap, and reverts guidance, ownership tests, and docs. Slice 5B-3A state/reset helpers remain intact; no schema or data migration is required.

Implemented in Slice 5B-4A:

- `attribute_group_swap_from`, `attribute_group_swap_to`, `attribute_group_swap_scope`, `attribute_group_swap_selected_route_id`, and `attribute_group_swap_require_full_match` are durable same-Project drafts. The five corresponding `_attribute_group_swap_*_widget` keys are temporary rendered controls reconstructed from normalized durable values.
- Missing or invalid From repairs to the first sorted Group; To repairs to the first current Group different from the resolved From; valid equal From/To remains a visible validation case. Invalid scope repairs to `all_lines`, selected Route repairs only when its widget is needed, and non-Boolean Require Full Match repairs to `False`.
- `attribute_group_swap_preview` remains the single normal/Selected Routes preview owner. Hidden-widget reconstruction does not recalculate or clear it. Unchanged signatures stay current; changed inputs, target Lines, Routes, or common `gallery_selected_route_ids` leave the preview stored but stale and unable to Apply.
- `attribute_group_swap_selected_routes_confirm` is intentionally non-durable. Fresh Preview resets it, successful Apply clears it, and hidden/reopened controls require confirmation again.
- `reset_attribute_group_swap_project_session_state()` clears only the five durable drafts, five temporary widget keys, preview, confirmation, and notice at successful JSON load, new workspace Project, directory import, and single-TXT import transitions. Failed transitions and Back preserve them.
- The Sidebar Apply section remains the only render owner through `st.sidebar.expander()`. Gallery continues to own its separate `gallery_attribute_group_swap_*` state, and the Apply workspace still renders exactly Module Toggles, Saved Module Reference Insertion, then Module Candidate Selection.
- Normal Apply retains one history entry, Focus restoration, one core Apply, preview cleanup, autosave, and one rerun without text-area synchronization. Selected Routes retains atomic core Apply before history commit, Focus restoration, text-area synchronization, preview/confirmation cleanup, autosave, and one rerun.
- No core operation, signature, scope, Project/settings schema, explicit save, autosave, matching, replacement, image, Candidate, Variant, source-generation, lineage, negative-metadata, Candidate Selection, or Saved Insertion behavior changed.
- Rollback restores the five direct widget keys, removes the ten preparation/synchronization helpers and the exact Project-bound reset, and reverts focused tests/docs. No schema, Project, prompt-data, or preview-data migration is required.

Implemented in Slice 5B-4B:

- `render_attribute_group_swap_section(project)` moved from the retained Sidebar Apply section into `render_module_attribute_apply_workspace()` and now renders through one main-area `st.expander()`.
- The Apply workspace obtains the current Project once and renders exactly Module Toggles, Saved Module Reference Insertion, Module Candidate Selection, then Attribute Group Swap.
- The retained Sidebar Apply section still owns the single contextual `Open Apply Workspace` launcher and no longer renders an operation.
- The Slice 5B-4A durable keys, temporary underscore widget keys, preparation/synchronization helpers, preview signatures, stale guards, reset helper, and successful Project-transition cleanup remain intact.
- Back hides Attribute Group Swap without clearing its durable drafts or preview. Reopening reconstructs missing temporary widgets; matching previews stay current, changed context stays stale, and Selected Routes confirmation must be checked again.
- Normal and atomic Selected Routes Apply retain their existing history, Focus, synchronization, preview cleanup, autosave, notice, and rerun boundaries. Gallery continues to own its separate `gallery_attribute_group_swap_*` keys and renderer.
- No core operation, signature, scope, Project/settings schema, save/load, matching, replacement, image, Candidate, Variant, source-generation, lineage, negative-metadata, Candidate Selection, or Saved Insertion behavior changed.
- Rollback restores `st.sidebar.expander()` in the renderer, removes its Apply-workspace call, restores its Sidebar call, and reverts guidance, ownership tests, and docs. Slice 5B-4A state/reset helpers remain intact; no schema or data migration is required.

Implemented in Slice 5B-5:

- Module Edit Scope remains under the single `render_module_inspector_edit_scope_section()` owner in Sidebar Analysis. The Apply workspace still renders exactly its four established operations.
- The collapsed section is titled `Module Inspector / Active Edit Scope`. After missing-Module sanitization, it shows `Active Edit Scope: none` or a visible active status and explanation sourced from `module_edit_scope_name`, not the Inspector selector.
- The prior clear control is consolidated into one `Clear Active Edit Scope` action. It calls `clear_module_edit_scope()` and reruns once without Project mutation, history, autosave, text synchronization, or unrelated session-state resets.
- `module_inspector_selected` remains independent: inspecting another Module does not activate, replace, or clear the current Edit Scope.
- Back, section collapse, and opening another management workspace preserve the same-session current-Project scope. Successful Project replacement clears the exact `module_edit_scope_name` key after the replacement input loads; failed transitions preserve the current scope.
- No Project/settings schema, save/load persistence, history, autosave, prompt-filtering, Module parsing, Apply operation, Gallery, Route, Candidate, Attribute Group Swap, or lineage behavior changed.
- Rollback restores the former title and clear-control presentation, removes the active summary and exact Project-transition reset, restores prior workspace metadata wording, and reverts focused tests/docs. No data migration is required, and Slice 5B-4A/5B-4B remains intact.

Implemented in Slice 5C-1A:

- Project Module Inspector is classified as Authoring because it edits and saves Project Module body, type, Core Tokens, and Minimum Matched Tokens. Module Attribute Table remains true read-only Sidebar Analysis.
- `project_module_inspector_name` is the durable same-Project selection. Body, Core Token text, Module type, and Minimum Match retain independent durable `project_module_inspector_*_{module_name}` drafts.
- The rendered controls use temporary `_project_module_inspector_*_widget` keys. Selection and field prepare/sync helpers reconstruct hidden widgets from durable state without overwriting existing unsaved drafts from the saved Project.
- `render_module_token_inspector()` receives the current durable body/Core draft keys, so its Update Body and Add Token actions remain draft-aware and the next rerun reconstructs the rendered text widgets from those edits.
- Per-Module drafts remain independent across selection changes. Missing or renamed selections normalize to the first current Module without transferring stale draft content.
- `reset_module_attribute_authoring_project_session_state()` clears the exact selection, durable draft prefixes, temporary field-widget prefixes, and Project Module Inspector child-widget prefixes at existing successful Project replacement call sites. Failed load/import paths and workspace Back do not call that reset, so they preserve the current Project drafts.
- Same-name Modules across Projects cannot inherit prior drafts. A replacement Project initializes from its own saved Module entry after the successful-transition reset.
- Save retains validation, one history push, one `set_module_entry()` call, graph rebuild, Focus restoration, text-area synchronization, candidate-scan cleanup, and existing success feedback. It adds no autosave, explicit Project JSON save, rerun, schema change, or new persistence.
- At the Slice 5C-1A boundary, the renderer still used `st.sidebar.expander()` with exactly one top-level Sidebar Analysis call. Authoring kept its four existing operations, Apply kept its four existing operations, and Module Attribute Table was unchanged.
- Rollback restores direct widget-bound Inspector state, removes the prepare/sync helpers and Inspector reset entries, restores prior metadata/docs wording, and reverts focused tests. No Project data migration or rollback of earlier Slice 5 work is required.

Implemented in Slice 5C-1B:

- The sole `render_project_module_inspector_section(project)` call moves from top-level Sidebar Analysis into `render_module_attribute_authoring_workspace()`. Its outer container is now the main-area `Project Module Editor` expander.
- Authoring renders Module Library / Creation, Project Module Editor, Rename Module, Attribute Groups, and Attribute Group Inspector in that order without a duplicated Editor heading.
- Back/reopen uses the unchanged Slice 5C-1A durable selection and per-Module drafts to reconstruct temporary underscore widget keys. Module switching and shared token-Inspector updates remain draft-aware.
- Successful Project replacement still clears the exact Inspector state and prevents same-name leakage; failed transitions preserve the current Project and drafts.
- Save retains validation, one history push, one Project Module mutation, graph rebuild, Focus restoration, text synchronization, candidate-scan cleanup, and success feedback. No explicit Project JSON save, autosave, extra rerun, schema, parsing, or persistence change is added.
- Sidebar Analysis retains Module Attribute Table plus Module Inspector / Active Edit Scope. Apply remains exactly Module Toggles, Saved Module Reference Insertion, Module Candidate Selection, and Attribute Group Swap.
- Rollback restores the Sidebar expander and top-level call, removes the Authoring call, and reverts order/copy/docs/tests. Slice 5C-1A state and reset work requires no rollback or data migration.

Still remaining after Slice 5C-1B:

- Broader contextual Apply inspection has not moved, and Slice 5 is not complete.
- Possible Sidebar Analysis structural cleanup remains future work.
- A user-level Global Attribute Group Library remains future Authoring work.
- Preserve scopes, Selected Routes, preview/confirm keys, stale-preview guards, and one history/save owner per successful Apply.

After Apply ownership is stable, consider a user-level Global Attribute Group Library with explicit copy/import into Project-local Attribute Groups and no live synchronization. This is future Authoring work, not part of the Apply workspace and not an implemented schema or workflow.

### Slice 6: Workflow / Preset Authoring (inspection relocation implemented; mutation future)

- Implemented user-visible change: workflow upload/paste, read-only inspection, prompt/LoRA export, and mapping tools moved out of the daily Sidebar into ComfyUI Settings / Analysis & Inspection.
- Implemented owner: `render_comfy_workflow_inspector()` and its existing UI-only child panels retain one workspace call owner and their widget/session keys.
- Retained entries: daily effective preset and workflow status; Focus Edit and Gallery generation.
- State keys: inspected workflow, upload/paste mode, LoRA directory, node choices, and export preview remain session-only.
- Preserved risks/boundaries: no inspected JSON persistence, no production workflow mutation, and no passive Sidebar analysis/parsing cost.
- Future work: actual preset create/rename/delete, Workflow editing, node rewiring, and new LoRA switching/library behavior still require a separate Authoring design.
- Rollback: restore the composite's former Sidebar call owner and remove its workspace call; no schema or settings migration is involved.

### Slice 7: UI module extraction

- User-visible change: none.
- Moved functions: only stable workspace renderers into `ui/streamlit/` modules.
- Retained entries: same workspace routing and labels.
- State keys: unchanged.
- Risks: import cycles, hidden reliance on globals, changed render order.
- Tests: focused AppTest coverage plus full suite and Streamlit smoke.
- Rollback: move functions back without changing service/core behavior.

## 12. Migration Safety Rules

### Widget keys

- Never render old and new copies in the same run.
- Preserve existing keys during pure relocation.
- If a temporary widget key is conditional, keep durable logical state separate.
- Clear both durable and temporary keys on the correct Project transition only.

### Project transitions

Every open, new, duplicate, explicit Fork open, and startup auto-open path must use the same Project transition coordinator. At minimum it must reset:

- Selected Routes and route checkbox keys;
- active Gallery operation and Route action dispatch;
- operation previews and confirmations;
- Lightweight Fork preview/apply state;
- focus, highlight, expansion, and invalid edit scopes;
- authoring selections that reference assets absent from the new Project.

### Save ownership

- Rendering a workspace must not mutate or save the Project.
- Preview must not mutate or save the Project.
- Apply owns history and save exactly once after successful validation.
- settings writes and Project JSON writes must remain separate.
- filesystem asset operations require their existing explicit confirmation and path safety.

### Global versus Project libraries

- Global Module Library is a user-level filesystem asset.
- The optional AnimaDex local path is a user-environment Global Editor Setting in `.editor_settings.json`, not Project or Module Library data.
- Project Module Library and Attribute metadata live in Project JSON.
- Import/copy between them is explicit.
- UI relocation must not normalize, synchronize, or delete unknown fields.

### Performance

- Opening Gallery must not precompute authoring previews.
- Closed workspace panels must not scan workflows, candidates, variants, or files.
- Preview-first tools should retain cheap input signatures and build expensive plans only on Fresh Preview and pre-apply revalidation.

## 13. Release Boundary

### Pro v1

- this inventory and design;
- a session-only exclusive workspace shell;
- compact sidebar daily state and launchers;
- Project Management ownership of the global default Project root, New Project, and Duplicate Project, plus ComfyUI settings ownership of endpoint, fallback path, and Force shared workflow;
- Module / Attribute Authoring ownership, including Module creation/library maintenance, Rename Module, and Attribute Group management/inspection;
- Project Module Editor ownership in Module / Attribute Authoring with relocation-safe same-Project drafts;
- preservation of all current Project, Gallery, Apply, and save semantics;
- focused regression tests around routing and state reset.

### Pro v1.1

- Module / Attribute Apply and Edit Scope ownership reorganization;
- Workflow / Preset Authoring;
- deeper Project Settings separation;
- state-owner cleanup backed by pure helpers;
- narrow `app.py` UI extraction after behavior is stable.

### Desktop / Exp / Pro v2

- persistent multi-workspace navigation if justified;
- service-backed settings and authoring APIs;
- richer asset browsers and workflow mapping;
- multi-set Illustration Set analysis and Re-assembly.

Illustration Set Re-assembly is not implemented in Pro v1. This design must not be used as evidence that multi-set loading, state extraction, reconstruction, or Recipe-based Re-assembly exists.

## 14. Open Questions

- Is the effective ComfyUI Workflow Preset global, Project-local, or a global default with a Project override?
- Which generation defaults are routine enough to remain near Gallery Generation?
- Should Module Toggles remain globally visible when the current Project contains Module References?
- Which authoring selections should survive temporary workspace closure but reset on Project transition?
- Should Project Management eventually split into Project Settings and Project Maintenance?
- When should `lora_mapping_directory` become persisted, and in which owner?
- What is the minimum AppTest surface needed before the first render relocation?

## 15. Acceptance Criteria For Implementation PRs

- The sidebar remains usable with one active Project and a large Gallery.
- Production mode state is preserved while opening and closing a dedicated workspace.
- A moved control has exactly one render owner per run.
- Project transitions clear Project-bound previews and selections.
- Selected Routes remains session-only and pagination-independent.
- Preview and Apply semantics do not change merely because a panel moved.
- Project JSON, settings, workflow files, and global library ownership remain distinct.
- no implementation PR claims Illustration Set Re-assembly as available.
- each migration slice lists changed widgets, state keys, validation, and rollback in its PR body.
