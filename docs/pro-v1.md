# PromptGraph Pro v1 Notes

This compatibility note summarizes the current Pro v1 Image Metadata Import,
Gallery Edit, and Module workflow updates. Historical roadmap planning remains
outside the public source tree.

PromptGraph Pro v1 uses application version `1.0.0`. The release tag, if used,
is `v1.0.0`; any GitHub Release follows release-candidate validation and the provenance contract in
[Release Process](release-process.md). The authoritative machine-readable
version remains `core/version.py`.

## Canonical user-facing terminology

Pro v1 UI and current-user documentation use **Illustration** for one editable image/prompt item, **Scene** for a separator-bounded Illustration block, **Graph Edit** for the former Overall Edit surface, **Derived Project** for final-sequence materialization, and **Sequence Snapshot** for the existing snapshot/storyboard feature. **Route** is reserved for a future concept that may span multiple Scenes; no such runtime object is introduced in Pro v1. Internal compatibility identifiers (`PromptLine`, `line_*`, `route_*`, `selected_routes`, `lightweight_fork`, `route_snapshots`), serialized values, widget keys, manifest operations, and filenames remain unchanged.

## Graph Edit Illustration Browser

Graph Edit now pages its existing Illustration editor list through a display-only Browser. All, outside-Scene, and individual-Scene filters use the existing separator-based RouteBlock membership internally; duplicate Scene labels remain distinct by stable separator handle. All-view Scene visibility is applied before pagination, while a specific Scene or outside-Scene filter ignores the all-view collapse state. Page sizes are 12, 24, and 48, default to 12, and intentionally omit `All`. Only the current page is dispatched to the existing editor renderer, so page-out and collapsed records do not execute that editor's thumbnail or editing work.

The Browser changes no production scope. Graph, PromptCloud, Batch Edit, Module / Attribute operations, Project save, and export continue to use the full Project. Its filter, page, page size, collapse state, and notice are session-only and separate from every Gallery control. They survive same-Project mode/workspace transitions and reset through the canonical Graph session reset only after successful Project replacement; a failed Open preserves them. When the authoritative highlighted Illustration is hidden, the Browser reports that state and changes filter/page only after the user explicitly requests reveal. No Project, PromptLine, settings, scope, history, save, reason, or diagnostic contract changes. See [Graph Edit Illustration Browser](architecture/graph-edit-illustration-browser.md).

## Module workflow milestone

The first practical Module workflow is now complete enough for end-to-end character-structure editing.

The supported flow is:

1. Import an image set and recover editable prompt lines.
2. Create or edit reusable Global Modules with body tokens, Core Tokens, type, and match settings.
3. Optionally use AnimaDex Browser to import local AnimaDex-style character records as trigger-first Global Modules.
4. Use the Candidate Scanner to find matching Global Modules in the current project.
5. Import selected Global Modules into the Project Module Library.
6. Preview and apply detected module candidates so matched raw prompt tokens become Module References such as `<mod:Nijitsuji Milk>`.
7. Use Module Inspector to review module tokens, Core / Optional state, and token Attribute Labels.
8. Use Module Swap to replace raw source module body tokens or existing source Module References with a target Project Module.
9. Regenerate through ComfyUI while preserving unrelated scene, composition, camera, background, and pose tokens.

This makes Module more than a saved prompt fragment. In the current Pro workflow, a Module is an editable and swappable structural unit. For example, a project can convert a Nijitsuji Milk character token structure into `<mod:Nijitsuji Milk>`, swap it to `<mod:Shiromiya Tomato>`, and keep the surrounding scene prompt intact.

Global Modules remain portable reuse records. Attribute Labels are stored as current-project token metadata, not in the Global Module Library format. Project Modules remain the active source for Module Reference insertion, Module Swap, generation, and export.

`Module Library / Creation` makes those ownership boundaries explicit without changing Module behavior. Its Global section keeps AnimaDex and the explicit Project → Global and Global → Project copy operations; the Project section separates Blank Project Module creation from creating a Module out of Prompt content with optional replacement. `Replace with Existing Module` follows as a distinct operation and never creates a new Module. Blank creation does not rewrite Prompt lines.

The Global Module Library now has one session-only free-text search shared by `Global → Project` and `Manage Global Modules`. It searches the already-loaded Module name, category, prompt content, descriptions/notes, and existing Attribute Group / Variant metadata with Unicode NFKC, case-folding, and whitespace-term AND matching. Manager category filtering is combined with that query as an AND condition. `Project → Global` remains unfiltered because it selects Project-owned Modules, and the AnimaDex record search remains independent. The query survives workspace and Project transitions during the current app session, but it is not written to editor settings, Project JSON, or Global Module metadata and starts empty after an app restart.

This search does not rescan the filesystem or build a persistent index, and it changes no Module schema, JSON format, directory layout, or history. Passive query reruns reuse the session cache. Explicit Global Library writes first reload the latest JSON, apply only the requested mutation, normalize and serialize the complete library to a uniquely named same-directory temporary file, flush and close it, then atomically replace `global_modules.json`. The persisted canonical representation is reloaded into the cache only after replacement succeeds. This prevents a stale session from reverting unrelated changes, keeps the in-session search/manager view identical to a post-restart load, and leaves both the previous valid file and cache unchanged when serialization, flush, or replacement fails. This is write-failure protection, not backup, version history, synchronization, conflict locking, or automatic stale-temp recovery. Folders, tags, custom collections, and category expansion remain Pro v1.1 or later work.

Global Modules can now be organized by category: Character, Quality / Header, Location, Outfit, Pose / Action, Lighting, Camera / Composition, Style, Negative, or Other. Outfit Modules can be kept as reusable cross-character outfit templates, and when an outfit should become a character-specific variation it can be copied into a selected Character Module as an Attribute Group. This is a one-time copy operation, not live synchronization between the Outfit Module and the Character Module.

Project Attribute Groups can also be managed from the sidebar. Users can create groups, edit group names, slots, and tokens, add currently selected graph nodes to an existing group, and delete groups without opening the deeper Module inspector. Negative Attribute metadata remains preserved by these lightweight name/slot/token edits.

Attribute Group Swap lets users replace one project-local Attribute Group with another across All Illustrations, the Current Scene, a Selected Scene, the Gallery-wide session-only Selected Scenes set, Selected Illustrations, or the focused Illustration. Selected Scenes are resolved in physical Project order and require source/replacement Groups to have the same normalized Attribute Slot. The operation preserves existing full/partial match and `require full match` behavior, previews per-Scene positive Prompt diffs, metadata-only negative impact, and image / Prompt Drift, then revalidates and applies the complete multi-Scene change atomically as one undo unit. The v1 swap only edits positive Prompt tokens; negative Prompt, images, Candidates, Gallery Variants, `source_generation_info`, and `lineage_info` remain unchanged.

Gallery Attribute Group Swap exposes the same preview/apply engine inside Gallery operations, so users can review image Routes and selected Gallery lines while swapping outfit, expression, pose, or other Attribute differences.

Attribute Group Inspector can manually add tokens to a selected Attribute Group and optionally propagate the newly added tokens to matching existing lines. This helps patch incomplete Attribute Groups after production use, such as adding a missing clothing, expression, or pose token to lines that already contain the earlier group tokens.

AnimaDex Browser v1 makes a local character library part of this module workflow. It can discover local SQLite, CSV, or thumbnail/data directories, search normalized character records, preview thumbnails when available, and import one selected record as a Global Module after explicit confirmation. One file or directory path can be explicitly saved as the editor-wide `animadex_local_path` default in `.editor_settings.json`; it is not stored in Project JSON, and a currently unavailable external or network path may still be retained. Saving or clearing that default does not scan the path, and clearing it does not erase the current session input. New sessions default the Search/display limit to 500 while keeping 100, 500, and 1000 available as session-only choices. Imported AnimaDex modules use trigger-first mapping, `type: "character"`, optional `core_tags` in the module body, and `animadex_metadata` for local source details. It is local-only and manual; it does not batch import, sync remotely, call Civitai, download assets, or rewrite prompt lines. Rich card browsing remains a Pro v1.1/Desktop boundary; multiple roots and an OS-native picker are not part of this Pro v1 slice.

## Current Pro Direction: Module / Gallery / Lineage Workflow

PromptGraph-Pro is shifting from a prompt editor toward a practical lineage/module editor. The current Pro workflow is intended to help users take an existing image collection, recover its prompt structure, replace reusable character or concept modules, and produce a new curated route without losing the original sequence.

The intended workflow is:

```text
Existing image collection
-> import metadata/images
-> structure lines/routes
-> identify or import modules
-> optionally import character modules from AnimaDex
-> swap modules
-> batch generate
-> append variants
-> batch promote variants
-> export final collection
```

The current Gallery-to-export production loop can also start from prompt-only lines:

```text
Import / prompt-only line creation
-> Gallery review
-> Candidate generation
-> Candidate adoption:
   - image-less line: set candidate as the line image
   - image-present line: swap candidate with the current main image
   - useful alternate: insert candidate as a new line
   - close alternate: keep as variant / candidate history
-> Route organization
-> Final Images Export
-> project-local exports/final output
```

The same loop can be described as the practical ComfyUI production loop that Pro v1 is now supporting:

```text
Generate
-> choose from Candidates
-> use the selected image as the next differential generation source
-> choose from Candidates again
-> organize scene order when needed
-> export ordered files with PNG metadata stripping
-> publish to pixiv or another destination
```

ComfyUI remains the image generation engine. PromptGraph-Pro handles the production steps around generation that become tedious in a small illustration set: choosing accepted candidates, tracking which image should seed the next scene or differential generation, cleaning up sequence order, isolating unwanted images, stripping PNG metadata only on exported copies, renaming final images in order, and exporting only the resolved main images. This is a practical production role, not a claim that PromptGraph replaces the generation model or fully automates editorial judgment.

In this model, Gallery lines are not only text rows. They are route-aware image/prompt records with source metadata, generated candidates, appended variants, and lineage notes. PromptGraph Pro v1 is a production tool for editing a sequence of image/prompt records, generating and reviewing alternatives, adopting or swapping candidates deliberately, organizing the resulting sequence, and exporting the final image set.

Long-term ISDL / Illustration Set Description Language may describe reusable illustration-set structure, state transitions, and lineage in a more formal way. That is future Exp / Desktop / LineageEditor direction, not the Pro v1 implementation driver. Pro v1 can produce useful reviewed project data for future workflows, but its primary boundary remains practical illustration-set production.

Candidate is a per-line image pool, not only a bucket for unused output. A candidate may be an exploratory generated image, a manually added alternate, an adopted-image history record, or a previous main image retreated by a reversible swap. Generated images remain candidates until the user explicitly adopts, appends, swaps, or promotes them. For prompt-only or otherwise image-less lines, a candidate can be set as that line's main Gallery image. For lines that already have a main image, a reversible swap can make a candidate the main image while preserving the previous main image as a candidate. Useful candidates can be inserted either immediately after their source line or at the end of the current Route; Workbench candidates use their source line as the Route anchor. Source/reference image files, source metadata, and candidate image files are not destructively replaced.

Candidate image operations and prompt operations stay deliberately separate. The Candidate card's `本編画像に設定` action updates the resolved main image: the selected candidate becomes the resolved main image, and when a previous main image exists it retreats into the candidate list, but prompt text is not automatically rewritten. Prompt Revert / Candidate Prompt Adoption controls are positive-prompt safety actions: Prompt Revert restores editable positive prompt text from preserved source metadata, and Candidate Prompt Adoption applies candidate generation prompt metadata while leaving the image reference unchanged. Negative Prompt revert/adoption is intentionally outside this v1 scope unless a later PR adds it explicitly.

The central production invariant is:

```text
Displayed image and associated prompt should not drift apart.
```

In Japanese docs, the intent is: 表示されている画像と、それに対応するPromptの意味がズレないようにする。

If the visible image and its editable prompt drift apart, regeneration, Module Swap, Prompt Revert, Candidate Prompt Adoption, lineage inspection, and Final Images Export all become less trustworthy. Workbench, Prompt Revert, and Candidate Prompt Adoption are therefore safety tools for keeping image and prompt correspondence reviewable; they are not a promise of automatic correction.

Gallery Edit Mode is the primary production workspace. Its upper layout is grouped into Illustration Import / Source, Gallery Operations, and Gallery regions so import state, operation panels, and image browsing remain distinct. A stable **Operation Scope / 操作対象** panel always shows the sanitized session-only Selected Scenes count, bounded Project-order label summary, and the existing Select All / Invert / Clear controls. Selected Scenes is a shared selection owner, not a universal execution scope: it affects an operation only when that operation's own Target / Scope is set to Selected Scenes. All Illustrations may include eligible Illustrations outside separator-owned Scenes, while Current Scene, Selected Scene, and Selected Scenes include only Illustrations owned by those separators. The collapsed operation-support matrix and active-panel capability line are static display metadata; they do not resolve targets, validate Preview, or enable Apply. Gallery pagination stays immediately before the image/Route list. Inside Gallery Operations, **Route-based derivation / recomposition** follows the production order: Prompt / structure operations, Gallery Generation, then Route-scope Batch Candidate Adoption. All three phases use explicit launcher buttons and the same single-active-operation panel contract, with the active panel rendered directly below its owning phase; opening another operation replaces the previous body rather than stacking windows. Generation and Adoption bodies are not rendered while inactive. Their same-Project session drafts and fresh Previews survive close/reopen and operation switching through durable state plus temporary widget mirrors, while final confirmation checkboxes and exact phrases are one-shot and must be entered again. Successful Project replacement clears this state; failed replacement preserves the current Project and session state. **Line / Workbench-based authoring / expansion** keeps Batch Promote Variants with Candidate Route Creation, Prompt Revert, and Module Candidate scanning and now states when the shared Scene selection is not used; Batch Promote Variants remains the existing explicit Selected Scenes-capable exception. Operation engines, serialized scope values, Preview signatures, history/save behavior, lineage, storage, and schemas are unchanged. Shared Gallery execution scope resolution and state migration remain Pro v1.1 candidates.

Production-mode Sidebar ownership now distinguishes common history from Graph context. Undo remains available for a loaded Project in Gallery Edit, Trash, Overall Edit, and Focus Edit, with the existing history, Focus restoration, rerun, and keyboard-shortcut behavior. `Graph / 表示`, Neighborhood Steps, Merge Identical Prompts, Connect Mode, and Path Filter render only in Overall Edit and Focus Edit; Gallery and Trash do not prepare these widgets or run their Graph-only comparisons and rebuild path. Temporary widget keys are reconstructed from durable session values or `project.merge_by_word_only`, so Graph settings survive Gallery / Trash round trips without a schema or save change.

Sidebar Project Open now starts with a Fork-aware Project Directory Browser backed by the existing effective `projects_root_directory`. It performs one bounded initial discovery of direct-child `<root>/<project>/*.json` files plus the known `<root>/<project>/forks/<fork>/project.json` layout, validates the minimum PromptGraph Project JSON shape, and keeps the resulting snapshot in session until explicit Refresh, a root change, or successful app-owned Project creation requests a refresh. Custom Project JSON filenames and multiple valid JSON files in one Project directory remain visible. A missing root is not created by browsing, and unbounded recursion, image scanning, hashing, Project loading, graph building, watchers, and persistent indexes are not used. Normal and Fork entries both open through the existing authoritative `load_project_json_into_session()` path, so successful and failed Project-transition contracts remain unchanged. Recent Projects stays below the Browser for historical and external paths; Advanced direct JSON Open remains the recovery/external route. Browser cache and selection are session-only, with no Project, settings, Recent, or Fork manifest schema change. Native OS pickers and multiple roots remain Desktop/later boundaries.

The next UI-clarity direction is documented in [Sidebar / Workspace Separation Design](architecture/sidebar-workspace-separation.md). It inventories the current Sidebar and defines a staged separation between Daily Operations, Settings / Configuration, and Authoring / Maintenance.

Slices 1 through 4B-2B establish the exclusive workspace shell and relocate Project creation/duplication, ComfyUI configuration, standalone Module / Attribute authoring, and Rename Module while preserving their existing state and operation contracts. Slice 5A gives the existing Apply Sidebar block one named owner. Slices 5B-1 through 5B-3B establish the Apply workspace and relocate Module Toggles, Saved Module Reference Insertion, and Module Candidate Selection after their state boundaries are made workspace-safe. Slice 5B-4A gives Attribute Group Swap durable same-Project drafts and temporary widget mirrors, Slice 5B-4B relocates its single renderer after Candidate Selection, Slice 5B-5 settles persistent Module Edit Scope ownership in Sidebar Analysis, Slice 5C-1A makes Project Module Inspector drafts relocation-safe, and Slice 5C-1B moves the editor's sole render owner into Module / Attribute Authoring.

The Apply workspace now owns exactly Module Toggles, Saved Module Reference Insertion, Module Candidate Selection, and Attribute Group Swap in that order. The compact `Open Apply Workspace` launcher remains inside the retained Sidebar Apply section; it is not added to the general management/configuration launcher group or Gallery Operations, and the Sidebar section now renders no operation. Each operation retains its established durable/temporary state, preview, stale-guard, Apply, and successful Project-transition cleanup boundaries. Module usage inspection and session-only Module Edit Scope remain under Sidebar Analysis ownership because Edit Scope is persistent editing context used by daily editing surfaces, not a preview/apply operation. Broader contextual Apply inspection has not moved, and Slice 5 is not complete. Contextual selected-token authoring remains in PromptCloud. ComfyUI Settings owns Generation Settings Consistency, Negative Prompt Consistency, and the read-only Workflow Inspector composite. Workflow Preset selection, configured endpoint and effective workflow source/path status, and compact Force shared status remain in the daily Sidebar; Gallery and Focus Edit retain generation execution. Future Global Attribute Groups belong to Authoring rather than the Apply workspace. Workflow / Preset Authoring is a later slice. No connection probe or new setting was added, and production modes, Project/settings schemas, matching, Swap, Apply, history, Focus, synchronization, persistence, workflow resolution, generation, and save/load behavior remain unchanged.

Slice 5B-2A separates Saved Module Reference Insertion's durable same-Project inputs from temporary rendered-widget keys. Slice 5B-2B moves the renderer from the Sidebar to a main-area expander in the Apply workspace, where it follows Module Toggles. Back now hides the insertion controls while preserving the current filter, Module, target Line, scope, position, conditional learned-neighbor fallback, conditional token-index anchor, and preview; reopening the workspace reconstructs any cleaned-up widget keys. Dynamic option changes normalize invalid choices without regenerating or deleting the preview, so the existing signature decides whether it is current or stale. Successful Project transitions clear the operation inputs, widgets, and preview, while failed transitions preserve them. Module Candidate Selection now follows insertion in the Apply workspace; Attribute Group Swap remains in the Sidebar pending its own durability audit. No preview, Apply, history, Focus, synchronization, save/load, Project/settings schema, or Global Attribute Group behavior changed.

Slice 5B-3A prepares Module Candidate Selection for relocation by separating durable same-Project state from temporary underscore widget keys. Slice 5B-3B moves the unchanged renderer from the Sidebar to a main-area expander after Module Toggles and Saved Module Reference Insertion. Back hides Candidate Selection while preserving its selected Module, unsaved per-Module drafts, Candidate preview, and Apply preview; reopening reconstructs temporary widget state. Matching `module_name` / `core_tokens` / `min_match_tokens` signatures remain current, while changed or normalized inputs remain stale and cannot Apply. Successful Project transitions clear only the Candidate Selection operation state; failed transitions and Back preserve it. Pending newly-created-Module selection still applies once, Save Rules remains the only rule-metadata mutation, and Confirm Apply retains one history entry, one Apply, Focus restoration, text synchronization, preview cleanup, and no explicit save. Attribute Group Swap remains in the Sidebar pending its own audit.

Slice 5B-4A completes that Attribute Group Swap durability audit without relocating the renderer. The five public operation keys are durable same-Project drafts, and five temporary underscore widget keys reconstruct From Group, To Group, scope, selected Route, and Require Full Match after hidden-widget cleanup. The single normal/Selected Routes preview state survives; matching signatures remain current, while changed inputs, target context, or common Selected Routes leave it stale and blocked. Selected Routes confirmation remains intentionally temporary. Successful Project transitions clear the exact Sidebar operation state; failed transitions and Back preserve it. Gallery Attribute Group Swap keeps separate state. Normal Apply and atomic Selected Routes Apply retain their existing history, Focus, synchronization, preview cleanup, autosave, and rerun boundaries. Slice 5B-4B remains the actual relocation; Module Edit Scope, contextual Apply analysis, and a future Global Attribute Group Library remain separate work, so Slice 5 is not complete. No core, schema, scope, save, matching, replacement, image, Candidate, Variant, source-generation, lineage, or negative-metadata behavior changed.

Slice 5B-4B completes the render-owner relocation. Attribute Group Swap now uses a main-area expander as the fourth operation in the Apply workspace, after Module Toggles, Saved Module Reference Insertion, and Module Candidate Selection. The Sidebar Apply section retains only `Open Apply Workspace`. Back preserves the five durable drafts and preview, reopening reconstructs missing temporary widgets, and Selected Routes confirmation does not survive being hidden. Normal and atomic Selected Routes Apply, notices, Gallery-owned swap state, Project-transition reset boundaries, matching, history, Focus, synchronization, autosave, schema, and persistence behavior remain unchanged. Contextual Apply analysis and a future Global Attribute Group Library remain separate work.

Slice 5B-5 settles Module Edit Scope ownership. It remains in Sidebar Analysis rather than moving into the Module / Attribute Apply workspace, because it continues to constrain editing after the user returns to Gallery, Overall Edit, or Focus Edit. Keeping the status visible in the daily Sidebar avoids an invisible constraint after Back. The section shows the sanitized active `module_edit_scope_name`, keeps it distinct from the current Inspector selection, and provides one direct clear action. The scope is same-session current-Project context, not Project data: Back, collapse, and other workspaces preserve it; successful Project replacement clears it; failed transitions preserve it. No schema, Project save, autosave, history, prompt-filtering, Module parsing, or Apply-workspace operation changes.

Slice 5C-1A prepares Project Module Inspector for relocation from Sidebar Analysis to Module / Attribute Authoring. Unlike the read-only Module Attribute Table, the Inspector edits and explicitly saves Project Module body, type, Core Tokens, and Minimum Matched Tokens. Its selected Module and independent per-Module drafts now survive hidden-widget cleanup and workspace Back through durable same-Project keys, while temporary underscore widget mirrors reconstruct from those drafts. Successful Project replacement clears the exact Inspector state, preventing a same-name Module in the next Project from inheriting an old draft; failed transitions preserve the current Project and drafts. Save retains its existing validation, one history entry, Project mutation, graph rebuild, Focus restoration, text synchronization, candidate-scan cleanup, and success feedback without autosave, an explicit Project JSON save, or schema changes. That durability slice intentionally left the renderer in its sole Sidebar Analysis owner before the follow-up relocation.

Slice 5C-1B completes the relocation and presents the panel as Project Module Editor. Its sole render owner is now Module / Attribute Authoring, after Module Library / Creation and before Rename Module; Attribute Groups and Attribute Group Inspector follow. Back/reopen reconstructs temporary widgets from the unchanged Slice 5C-1A durable same-Project drafts, Module-specific drafts remain independent, shared token-Inspector actions remain draft-aware, and successful versus failed Project transitions retain their established reset boundary. Sidebar Analysis retains Module Attribute Table, Module usage inspection, and Active Edit Scope. Apply remains exactly Module Toggles, Saved Module Reference Insertion, Module Candidate Selection, and Attribute Group Swap. Save, Project/Module schema, autosave, explicit Project JSON save, parsing, and persistence behavior remain unchanged.

Gallery Workbench cards provide a non-mainline scratch area for one source line. A normal Gallery card can create a `workbench` line immediately after itself; the Workbench keeps its own title, note, prompt, negative prompt, candidates, and source-line reference. Workbench candidates can be generated and reviewed manually, but Workbench lines are intentionally excluded from graph construction, PromptCloud, Module Swap, Batch Edit, Module Candidate scanning, Gallery-wide generation targets, and Final Images Export.

Project Management owns Project Defaults, New Project, and Duplicate Project in that order. The global `projects_root_directory` setting controls only the default parent shown by future New Project forms. An empty stored value resolves to the portable built-in `<APP_ROOT>/projects`, so moving the PromptGraph installation does not persist a stale machine-specific built-in path. A manual custom parent can still be entered for each Project, and `Use default Project root` restores the configured default. Saving or resetting the root creates no directory, moves no existing Project, and writes no Project JSON; a missing root is created only when a Project is actually created there. This setting is not a filesystem sandbox: Recent Projects, startup auto-open, Advanced direct JSON Open, Save As, Quick Save, Duplicate Project, Lightweight Fork, and Projects outside the root retain their existing behavior. There is no Project schema change.

The New Project form separates the parent destination folder, Project name, and JSON filename, validates that the Project name cannot escape its parent, and shows the resolved collision-safe destination before creation. On a fresh app session, PromptGraph attempts to open the saved `last_project` once; a missing or invalid Project leaves the app available for Recent Projects or manual JSON selection instead of retrying on every Streamlit rerun. Recent Projects is the primary manual Project Open path in the sidebar, while direct JSON path selection and Save As remain available under the collapsed Advanced section for recovery, external Projects, older Projects, and special validation. Save As writes the current Project to another JSON path and switches the current save target to that JSON. A missing destination retains that one-click flow. An occupied regular file instead arms a session-only confirmation, displays the exact normalized absolute target, and requires both an acknowledgment and a separate destructive button; cancel changes neither file nor current target. Editing the path, changing/replacing/removing the destination, changing its file type, or switching the source Project invalidates the stored SHA-256-backed snapshot and requires a fresh first step. Quick Save remains the one-click action for the current Project path. Save As does not create a snapshot while remaining on the original Project, and it does not duplicate the full Project directory; use Project duplication for a complete directory copy. Existing projects can still be opened and saved from their current locations, and project-local exports remain under each project's own `exports/` directory. Project duplication now copies the current project directory rather than only writing a second JSON file, so refs, candidates, routes, exports, workflows, and other project-local files stay available in the copied project. Thumbnail/cache-only folders such as `.promptgraph_cache` are excluded and regenerated as needed; arbitrary absolute paths embedded in project JSON are not rewritten in this v1 duplication flow. This completed the persistent Project-root settings slice after the workspace-separation work was verified.

Normal Project JSON persistence is atomic by default. Quick Save, autosave-owned operations, Advanced Save As, New Project creation, and Duplicate Project's pre-copy source save serialize the complete payload to a uniquely named `.tmp` file beside the requested final JSON, flush and close it, then use `os.replace()` to commit. Project-relative Candidate, Variant, and lineage paths are still calculated against the final Project JSON path rather than the temporary filename. Serialization, flush, close, or replace failure cleans the temporary file and leaves an existing destination byte-identical; success-side current-path, Recent/settings, folder-layout, and feedback updates run only after the atomic writer returns. A confirmed Save As overwrite uses this same writer after one final destination revalidation. The narrow confirmation detects changes before the writer call but does not add cross-process locking or eliminate a theoretical filesystem race after that check. This guarantee is not Project version history or automatic backup, and no pre-overwrite recovery copy is created.

Older Projects outside the configured root can now be migrated from Project
Management through **Import Existing Project into Project Root**. The operation
is preview-first and copy-only: it inventories the full source directory on an
explicit Preview, rewrites only registered Project/Fork path fields in hidden
staging, validates staged Projects and same-source Fork relationships, and
atomically commits one direct child below the effective root. The source is
never moved or deleted, external absolute dependencies remain unchanged with
warnings, raw unknown JSON fields and arbitrary JSON remain intact, and no
destination is overwritten or merged. Success adds the imported primary JSON
to Recent Projects and refreshes the Project Directory Browser without changing
`last_project` or the open Project; opening the copy remains an explicit action.
See [Safe Existing Project Import](architecture/project-root-import.md).

Project Assets remains a single Sidebar-owned Project-wide operation in Pro v1;
its relocation to Project Management remains a Pro v1.1 boundary. The
user-facing section is now **Candidate / Variant画像をProjectへ取り込む**, with
`Project Assets` retained as a technical caption. It copies referenced
`generated_candidates` and `gallery_variants` into Project `candidates/`,
updates their paths and matching lineage/source-generation references, and
never moves or deletes source images. This is not a ComfyUI output mover:
ordinary PromptGraph generation already writes downloads into the current
Project's `generated/` directory. Under the preserved current semantics,
Candidate/Variant references from `generated/` are still eligible for a second
copy into `candidates/`. The separate **Verified Duplicate Cleanup** operation
can later reclaim only a verified duplicate source from `generated/`; it does
not change this copy/reference-update behavior.

Before Apply, a read-only Preview shows referenced record count, unique source
count, planned copies, copy-not-needed records, Project-inside/outside source
counts, estimated copy bytes, missing/unreadable sources, and collision/rename
plans. The estimate sums readable file sizes per planned copy and does not scan
file contents or infer hard-link/inode savings. Preview performs no filesystem
or Project mutation. Apply requires explicit confirmation and revalidates a
signature covering the Project path, Candidate/Variant references, source
size/mtime state, and planned destinations. Stale input refreshes Preview and
clears confirmation. Copying uses a cloned Project, cleans up files created by a
failed attempt, and saves through a temporary JSON beside the current Project
JSON before atomically replacing the destination. Copy, serialization,
encoding, or replace failure removes the temporary JSON and newly copied
images, restores the in-memory Project and Candidate cache, and leaves the
previous Project JSON bytes untouched. The operation preserves the existing
one-save/no-history owner, synchronizes the Candidate session cache, and adds
no explicit success rerun. Successful
Apply clears stored Preview state and schedules confirmation reset for the next
normal rerun. Same-Project Sidebar collapse, Back, and ordinary reruns preserve Preview; successful
Project replacement clears it, while failed load preserves the current Project
and operation state. No Project, PromptLine, Candidate, Variant, or lineage
schema field is added.

Verified Duplicate Cleanup is not a general orphan-file cleaner or an external
ComfyUI output cleaner. It recursively scans image files only below the current
saved Project's `generated/` and `candidates/` directories. A `generated/`
source is eligible only when SHA-256 and size match at least one `candidates/`
copy that remains referenced in the normal serialized Project representation,
while the source is completely unreferenced across that same nested
serialization. Path comparison uses normalized real Project-local paths;
outside paths, traversal escapes, symlinks, non-image files, unreadable files,
and ambiguous inputs fail closed. `candidates/` files are never deletion
targets.

Cleanup is preview-first and reports eligible/protected files, retained copies,
duplicate groups, and reclaimable source bytes. Apply requires a fresh
filesystem/Project signature, an explicit checkbox, and the exact
`DELETE VERIFIED DUPLICATES` phrase. Every eligible source and retained copy is
revalidated before the first deletion. The operation then completely deletes
only the verified `generated/` source files so disk space is reclaimed; it does
not use Project Trash or the OS Recycle Bin, and PromptGraph cannot restore
those source paths. A byte-identical referenced copy remains in `candidates/`.
Project objects, Project JSON bytes, history, Candidates, Variants, lineage,
and schemas are unchanged. If a later single-file delete fails, processing
stops immediately and reports the already-deleted file list, failed file, and
remaining eligible files instead of hiding the partial result.

Module References make character and concept replacement repeatable. A line can move from raw character tokens to `<mod:Nijitsuji Milk>`, then Module Swap can replace that reference with `<mod:Shiromiya Tomato>` while leaving scene, pose, camera, background, and composition tokens intact where practical.

Module Swap is preview-first and can target All lines, a Line Group, the existing Route scope, or Gallery-wide Selected Routes. Selected Routes uses the session-only separator selection, resolves Routes and Lines in physical Project order, previews positive Prompt changes and the current unchanged negative Prompt per Line, and marks image / Prompt Drift risk. Apply revalidates Route structure, full Prompt/token state, Module Library state, options, and Project identity, then commits the complete Prompt-only change atomically as one undo unit. It does not mutate Gallery images, generated candidates, appended variants, route metadata, `source_generation_info`, or `lineage_info`.

Gallery variant workflows let the user keep the original Line and attach new generated outcomes as appended variants. `Batch Promote Variants` can target the Current Route, one Selected Route, the session-only Selected Routes set, Selected Lines, or All Gallery Lines. It resolves Routes and Lines in physical Project order, selects the latest or first appended Variant per Line, and adds each valid result as a new normal Gallery Line either at the Gallery tail or immediately after its parent Line. It does not create a Route separator or independent Route, consume the Variant, or change the source Line, its Candidates, Gallery Variants, adopted image references, or image files. Route- and Line-level Fresh Preview includes missing/invalid images; apply revalidates Project structure, full parent metadata, Variant selection, and image file state, then commits the complete promotable plan from a clone as one undo/save unit. This adds no Project, PromptLine, Candidate, or Gallery Variant schema field.

In Gallery Edit Mode, the per-image `分岐` button is the primary lightweight way to start a new route: it inserts a default Route separator immediately after that image card. Route label and color edits stay on the separator card after creation. Gallery defaults Route sections to collapsed for lighter initial browsing; users can open needed Routes or use Gallery controls to close or reopen all active Route sections at once, and larger story splits can be handled as separate projects.

Route-level operations are tracked in [Route Operations Design](architecture/route-operations.md). Pro v1 keeps Routes separator-based: a Route block is the separator PromptLine plus its positionally-owned lines, the separator line id is the Route handle, and no first-class Route object enters the project schema. The implemented Route Operations slice includes a pure structural RouteBlock resolver, active-separator Route Actions that dispatch generation, Candidate Adoption, Final Images Export, and Lightweight Fork into their existing panels with `Selected Route` and the separator id preselected, Route block Move Up/Down that reorders the contiguous separator-owned block without moving files or changing PromptLine identity, non-destructive Route remove with atomic restore backed by a `project_metadata` removal record, and Duplicate Route as Baseline. Duplicate Route inserts a fresh-id block after the source, preserves prompts, metadata, adopted image references, and deleted state, clears Candidates/Gallery Variants and experimental state, remaps Workbench sources, and reuses existing image paths without copying files. When the adopted image comes from `selected_candidate_path`, its Candidate prompt/settings snapshot is rebuilt into `source_generation_info`; missing Candidate records use a diagnostic fallback. The Selected Routes foundation is also implemented as a Project-order, session-only selection of active separator handles with summary and Select All/Clear/Invert controls. Selected Routes now connects to Final Images Export, Lightweight Fork, Route-scope Batch Candidate Adoption, Gallery Generation, Module Swap, Attribute Group Swap, and Batch Promote Variants. These consumers resolve selected handles in physical Project order and require a fresh preview. Export records selected Route metadata in its manifest; Fork preserves selected Route boundaries, materializes resolved images into a new project, and clears Candidate/Variant state only in the fork copy; Candidate Adoption previews per-Route image/prompt drift and commits one atomic image-reference-only plan while leaving positive/negative prompt text and image files unchanged; Generation preflights the existing ComfyUI requests before submission and appends real outputs as Candidates without changing main image references, prompts, or image provenance; Module Swap previews per-Route Prompt diffs and Drift risk, then commits a revalidated atomic Prompt-only plan while preserving image and provenance state; Attribute Group Swap additionally validates normalized slot compatibility, preserves existing full/partial matching, shows negative metadata as preview-only, and commits one atomic positive-Prompt-only undo unit; Batch Promote Variants adds fresh normal Gallery Lines from latest/first appended Variants without creating separators or changing source records/files. Generated results are routed by stable source Line id rather than completion order. The existing single Route scopes remain separate. Selected Routes does not connect to Candidate Prompt Adoption or other remaining Multi-Route operations; those connections, Multiple Routes Fork, and Route Candidate Review remain v1.1 candidates. The full Route Take pipeline is Desktop / Pro v2.

Global Route Template is a conditional Pro v1 candidate designed in [Global Route Template Design](architecture/global-route-template.md): a slot-free, single-Route, user-level portable JSON asset that saves a Route's ordered positive/negative prompts with embedded Module snapshots and no absolute paths, and materializes into a project as a fresh image-less Route using only existing schema. Same-name but different-definition Module conflicts block Add rather than resolving silently, and character/location/outfit replacement is delegated to the existing Route-scope Module Swap. Slot binding, Template Packs, and state-aware templates are v1.1+ work.

Gallery-wide generation keeps this candidate-first behavior. Generation scope can target all lines, the current Route, a selected Route, or selected lines. Route separators are excluded from generation targets, and generated images are still added as candidates on the targeted lines; the operation does not directly rewrite Gallery images, Route metadata, or Lineage metadata. Batch prompt editing follows the same Route-aware targeting model for prompt-add/replace/remove operations.

Route-scope Batch Candidate Adoption is an implemented Pro v1 Gallery operation and an extension of the current per-line `本編画像に設定` behavior, not prompt rewriting. Dry-run preview and apply are implemented for latest active Candidate, first active Candidate, and latest appended Gallery Variant sources across Selected Lines, Current Route, Selected Route, Selected Routes, and All. Selected Routes is session-only, resolves Routes and Lines in physical Project order, displays per-Route drift/no-op/skip summaries, requires a full fresh-preview signature, and applies on a Project clone so any failure leaves the current Project unchanged. Adoption updates `selected_candidate_path` and rebuilds `source_generation_info` / `lineage_info` from the exact adopted record before the reference changes, so lineage keeps the previous main image as parent. Existing main images retreat into the Candidate side where appropriate, `generated_image_path` and `image_path` are preserved, editable prompt text is not changed automatically, and Candidate Prompt Adoption remains a separate explicit operation. Gallery Variant apply does not mutate `gallery_variants` or materialize the variant image into `generated_candidates`.

The implemented workflow is preview-first. Preview resolves scope, target images, first-image adoption, swap-with-retreat, no-op, skipped lines, counts, and the mandatory drift warning. Apply is available only when the current preview signature matches an implemented source/scope pair.

All apply requires the current preview signature, the existing confirmation checkbox, and the exact `APPLY ALL` confirmation phrase. The Gallery UI shows extra All-scope safety warnings and target/adoption/skip counts. The All preview signature includes the project-wide target line set so a changed Gallery line structure makes the preview stale before apply.

Batch image adoption must make image/prompt drift explicit. A preview should show which image references will change, that prompt text will not be rewritten automatically, whether separate Candidate Prompt Adoption is needed, and whether the displayed image still matches the prompt meaning before apply. The detailed unified design, including the source/scope matrix, scope resolution, excluded targets, retreat semantics, data update rules, and export/fork consistency, is [Route-scope Batch Candidate Adoption Design](architecture/route-batch-candidate-adoption.md). Route-level Variant Swap is part of that same design, not a separate feature.

Remaining future work around this area is deliberately separate from the completed source/scope matrix: optional Candidate Prompt Adoption integration, consolidation of the legacy-compatible `Batch Adopt Gallery Candidates` UI, deeper lineage or semantic prompt rewrite, and AI/VLM image-prompt consistency checks.

Final Images Export closes the Pro v1 output loop from Gallery Edit Mode. It previews exportable/skipped main-sequence lines, per-item source size, and the source-byte total that will be copied, writes ordered copies under the project-local `exports/final` folder, can use timestamp subfolders, writes `export_manifest.json`, and applies PNG metadata stripping only to exported copies. Duplicate source paths are counted once per planned output item because Final Export writes each item separately. Preview classifies the destination as the shared Final Export root, a Project-local timestamp/custom subfolder, an outside path, or unknown; it also reports planned image collisions, an existing manifest, and free space from the nearest existing destination filesystem. These checks are read-only and use file stats plus one disk-usage lookup—no recursive scan, hash, image decode, directory creation, or file write.

The public `export_manifest.json` uses `manifest_version: 2` and `path_contract: "portable-relative-v1"`. Its `project_path` / `project_name` values are the Project JSON filename only, `output_dir` is `"."`, and each `items[].output_path` resolves relative to the manifest directory with `/` separators. Project-local source provenance is stored relative to the Project directory with `source_image_scope: "project"`; an external source stores only its basename with scope `external`, and an unavailable reference fails closed as an empty `unknown` value. `source_original_filename` is also filename-only. The running Preview and export result retain their real absolute paths for validation, copying, and UI reporting, but those internal values are not serialized into the public manifest. Moving the complete export directory therefore keeps output references valid; source references are descriptive provenance and are not guaranteed to resolve on another machine.

The portable manifest still contains prompt text, negative prompts, Route/Scene labels, ordering, skipped-item information, warnings, and metadata-strip status. It removes machine-local path hierarchy, not arbitrary user-authored content, and does not provide anonymization, encryption, backup, upload, publishing integration, or a private diagnostic manifest.

The source-byte total is an input estimate, not a guaranteed final export size. PNG metadata stripping re-saves exported copies, and filesystem allocation, compression, manifest bytes, and other overhead can change the final disk usage. Insufficient or unknown capacity and shared-root overwrite risk are informational warnings only; they do not change Export button eligibility or copy behavior. Timestamp subfolders remain recommended because writing directly into the shared `exports/final` root can overwrite same-name images and `export_manifest.json`. Destination capacity/profile fields remain Preview-only and are not added to the portable manifest.

Final Images Export exports the main image currently resolved by each eligible Gallery line after candidate adoption or swap, using `selected_candidate_path` -> `generated_image_path` -> `image_path`. Export scope can target all lines, the current Route, a selected Route, or the session-only Selected Routes set. Selected Routes resolve active normal PromptLines in physical Project order, exclude separators, Workbench, deleted, image-less, and missing/invalid lines, preserve continuous filenames across Route boundaries, and add selected Route handles, labels, counts, and summaries to the manifest. Selected Routes export requires a fresh preview after selection, Route, or export-setting changes. Volatile disk total/used/free and capacity status are excluded from that freshness signature, while scope, selected Routes, planned filenames, source paths/sizes, numbering, and metadata-strip settings remain relevant. Final Export does not rewrite source images, candidates, variants, lineage metadata, or project JSON.

Lightweight Fork / Final Sequence Materialization is a separate design note from simple project duplication or candidate cleanup. Its purpose is to start a new editable project from a completed final/main sequence while leaving temporary production pools behind. Pro v1 now has a user-facing Gallery workflow backed by a preview model and core materialization helper that match Sequence Preview and Final Images Export resolution, using `selected_candidate_path -> generated_image_path -> image_path`. Preview shows planned fork image destinations and skipped reasons without creating files. Create Fork requires a saved source project, a fresh preview, explicit confirmation, destination conflict validation, and exact `FORK FINAL` confirmation for All scope. **Append to Existing Fork** can then add only unmaterialized Routes from that same saved source Project to the existing Fork tail, targeting either one shared Single Route (including the Route Actions shortcut target) or the Gallery session's Selected Routes set. Create and Append share this target state within the current Project session; Project transitions reset it. Append mode discovers matching Forks from the source Project's direct `forks/*` children, rejects a discovery root that resolves outside that Project directory, reports actual materialized Route counts rather than selection history, provides lightweight manifest summaries and explicit Refresh, and keeps `Browse another Fork...` as the manual path fallback; Fresh Preview remains the authoritative full validation. It preserves all existing Fork edits, continues image numbering, issues fresh IDs, clears Candidate/Variant/transient provenance only on new Lines, appends manifest history, and uses a rollback-safe directory transaction. Core apply revalidates source and destination state immediately before commit without mutating the source Project or source images. Successful Create registers the Fork in Recent Projects without auto-opening it, and successful Append refreshes that Recent entry and the discovery cache. Cross-project append, Route replacement/update, and duplicate Route versions remain unsupported. The source stays open until the user explicitly chooses `Open Created Fork` or opens the Fork from Recent Projects. The design is tracked in [Lightweight Fork / Final Sequence Materialization Design](architecture/lightweight-fork-final-sequence.md).

A created fork carries forward:

- final/main illustration sequence;
- prompt text;
- Route structure;
- relevant Module / Attribute definitions;
- project-level settings needed for continued editing;
- enough provenance to know the new project was forked from another project.

A created fork does not carry forward:

- `generated_candidates`;
- Workbench lines or Workbench candidates;
- temporary candidate pools;
- Trash candidate state;
- detailed source lineage that points into the old project;
- stale candidate paths.

The implemented materialized line shape is:

```text
selected_candidate_path: cleared
generated_image_path: cleared
generated_candidates: cleared
image_path: materialized final image copy
```

This uses only existing PromptLine fields, so no project schema change was required. Fork provenance lives in the fork `manifest.json`; any future promotion of provenance into project JSON remains a separate Full Template decision.

The same Final Export context includes a read-only `本編プレビュー` / Sequence Preview. It steps through the resolved final image sequence with previous/next controls before export, using the same image resolution and exclusions as Final Images Export: Route separators, Workbench cards, deleted lines, and image-less lines are not shown.

Trash remains a manual safety container in Pro v1. It is used for deleted lines that can be restored, and in real production it often becomes the place where clearly broken or unwanted examples accumulate. That gives Trash a future design role as a possible Failure Memory / Negative Example Pool, but Trash Analysis, negative prompt mining, AI-assisted failure pattern scans, and automatic failure-memory extraction are not implemented in Pro v1.

Recent performance work supports this direction by making large Gallery projects more usable: pagination and page jump limit visible card rendering, thumbnail cache avoids repeated full-resolution image loads, and lazy variant rendering keeps collapsed cards lightweight.

Near-term Pro work should remain preview-first and manual-confirmed. Manual candidate adoption, reversible candidate/main-image swap, Trash as a manual failure container, Final Images Export, and non-destructive source/reference preservation belong to the Pro v1 production track. Trash Analysis, Failure Pattern Scan, negative prompt suggestion, Candidate-vs-Trash comparison, AI-assisted prompt anti-pattern extraction, and automatic failure-memory mining belong first in Future / Exp until the review and safety boundaries are clearer.

## Existing Illustration Set Reuse

Pro v1 can use an existing image archive as editable production material when enough metadata is available. The intended workflow is:

```text
Existing illustration set
-> import PNG/JPEG metadata and source images
-> recover editable prompt lines
-> review image/prompt correspondence
-> regenerate all lines or selected routes
-> use Module Swap for character, outfit, or composition changes
-> review candidates and adopt only useful results
-> export a new final image sequence
```

The practical strengths are:

- PNG/JPEG metadata can recover prompt text and source generation facts when available.
- An existing illustration set can become a Gallery editing target without retyping every prompt.
- All lines, selected lines, or Routes can be regenerated through the normal candidate-first flow.
- Global Modules and Project Modules can be used with Module Swap for repeated character, outfit, style, or composition replacement.
- Routes with small Attribute changes are usually easier to convert in one pass than routes with heavy state transitions. Future Attribute State / StateDomain design should model those transitions as per-line LineBinding metadata rather than Variant naming conventions.

The limitations are just as important:

- If the original image worked because of a lucky generation draw, the same prompt may collapse or drift when regenerated.
- Unstable or contradictory prompt text still needs manual cleanup.
- If image/prompt correspondence is already wrong, regeneration, Swap, Revert, Adoption, and Export become less reliable.
- Workbench, Prompt Revert, and Candidate Prompt Adoption reduce image/prompt drift, but they do not eliminate the need for review.
- Pro v1 is a human-reviewed IDE for re-editing illustration sets, not a fully automatic conversion system.

## Candidate and Workbench Management

This section separates the implemented Candidate management hardening from future design notes. Route Workbench remains future work.

### Implemented Candidate paging and lightweight display

Large production projects can accumulate many Workbench candidates and image candidates. Pro now avoids rendering every Candidate card at once in the normal Candidate and Workbench Candidate views:

- normal Candidate lists are paged;
- Workbench Candidate lists use the same paging behavior because Workbench cards store candidates on the same line-level Candidate model;
- page controls show the displayed range and page count when the list is larger than the page size;
- Candidate cards use display thumbnails through the existing thumbnail cache where possible;
- original image files remain the source for adoption, comparison, Route insertion, Prompt adoption metadata, and Final Images Export.

### Implemented Candidate Trash / Restore

Unwanted candidates now have a safer isolation path before any permanent deletion feature exists. The Candidate card shows this as `削除`, but internally it is non-destructive Trash:

- Candidate cards can send an item to Trash through the `削除` action.
- Normal candidate views exclude trashed candidates.
- Trash view can inspect trashed candidates.
- Restore returns a trashed candidate to the normal Candidate list.
- Image files are not deleted.
- Candidate metadata, lineage metadata, and prompt metadata are preserved.
- Final Images Export skips a trashed Candidate when it matches any resolved main-image source for the same line, then falls back to the next available source in `selected_candidate_path -> generated_image_path -> image_path` order.
- Internally, Trash starts from non-destructive fields such as `candidate["trashed"] = true` and `candidate["trashed_at"]`.
- Empty Trash / Delete permanently remains future work.

Candidate card wording is intentionally production-facing. The always-visible actions are reduced to `本編画像に設定`, `この画像のプロンプトを使う`, and `削除`, while insertion actions such as `次の画像として追加` and `ルート末尾に追加` live under an `追加` expander. `本編画像に設定` covers both image-less lines and replacing an existing resolved main image; the previous main image is kept as a Candidate when a swap is needed. The older comparison/reference-style Candidate card actions are not shown in the normal Candidate card because they can affect the resolved main image or source-image correspondence.

### Route Workbench

Current Workbench cards are still line-level or image-level scratch spaces. A future Route Workbench may be useful when a route needs one shared work area:

```text
Route Workbench:
- one shared workspace per Route
- select the active target Line
- generate from that Line's prompt / image / metadata
- accumulate candidates in the Route Workbench
- adopt back to the target Line or append to the Route end
```

The risk is that too many unrelated results in one workspace become hard to understand. A future design should keep these categories distinct:

```text
Variants = regeneration alternatives tied to a Line
Candidates = working alternatives inside the Workbench
Groups = organization inside a Route Workbench
```

Batch regenerate results should not all be mixed into a Route Workbench by default. They should normally remain as each Line's Variants, with explicit replacement or adoption into the main sequence when the user chooses.

Selected Line / Workbench integrated panels that combine Module, Attribute, State, semantic summaries, and State Timeline controls are v1.1+ design material, not Pro v1 scope. Pro v1 should keep the current preview-first dedicated sections and preserve the Workbench boundary: Workbench is a scratch area, not a main sequence line, and remains excluded from Export, Module Swap, Batch Edit, and Gallery-wide generation targets.

Possible Route Workbench grouping keys:

- `source_line_id`
- `generation_run_id`
- active target Line
- adopted / unadopted / trashed
- collapsed groups
- future manual group names and group moves

## Prompt Stability Inspector Future Note

After local AI assistance such as Qwen is integrated, Pro may add a review-first inspector for prompt instability. Possible names include Prompt Stability Inspector, Prompt Consistency Inspector, Image-Prompt Consistency Check, or Swap Residue Inspector.

The inspector should be advisory. It may detect prompts that are likely to collapse on regeneration, image/prompt correspondence drift, old character/outfit/accessory residue after Module Swap, and Attribute timeline contradictions inside a Route. It should not automatically apply repairs; users should review and adopt suggestions.

Possible phases:

1. Prompt Stability Check: detect conflicting tags, image/prompt drift, and regeneration risk.
2. Swap Residue Check: warn about old character, outfit, accessory, or related tokens left outside the intended Module boundary.
3. Attribute Timeline Check: estimate how Attributes change inside a Route, including transitions such as `full -> partial -> removed`. Future design should derive this timeline from per-line Attribute State / StateDomain bindings rather than persisting a separate timeline first.
4. Repair Suggestions: propose removable tokens, Attribute splits, or more stable prompt organization for human approval.

## Beyond Pro v1: Illustration Set Re-assembly

Pro v1 remains scoped as a stable single-illustration-set release. The goal is to organize and harden the existing Metadata Import, Gallery, Candidate, Route, Lineage, Global Module, Attribute Group, Batch Edit, ComfyUI generation, and Export workflows around one active project/set.

Loading, comparing, and recombining multiple illustration sets at the same time is out of scope for Pro v1. That direction would change assumptions across the Project Model, Gallery, Module system, Lineage, Metadata, Save Format, and UI, so it should not be folded into the current web Pro v1 stabilization work.

Illustration Set Re-assembly / Know-how Mashup remains a future design
direction. The concept treats existing image sets as reusable structure:
Modules, Attribute Groups, Routes, Lineage, Metadata, Gallery variants, and
candidate adoption history can become Source Set material for a later Derived
Set. This is not plain prompt merging; it is a proposed way to re-use the
know-how embedded in an illustration set's structure and generation history.

After Pro v1, Pro v1.1 can prepare foundations such as internal model refactoring, AI-assist integration points, local/Qwen-assisted summaries, Module candidate classification, Attribute Group inference, Attribute State extraction, exchangeable-region suggestions, and generation or diff-edit proposal workflows. Full multi-set Re-assembly is better treated as a Desktop / Pro v2 candidate where local image assets, caches, ComfyUI integration, resident models, MCP/API integrations, and richer Project Object Model concepts can be assumed.

## Image Metadata Import workflow

Image Metadata Import can now start from either a manual Image Directory or from an Image Root Directory plus Image Set selection.

- **Image Root Directory** is the stable top-level archive folder.
- **Image Set** is a relative folder under the Image Root Directory.
- Image Sets are listed only when the folder contains supported image files.
- Nested Image Sets are discovered under the Image Root Directory up to a conservative maximum scan depth.
- Existing immediate-child Image Set values remain compatible because `image_set` is still stored as a relative path string.
- The manual Image Directory field remains the fallback when no Image Set is selected or the selected Image Set cannot be resolved.

## Gallery Edit metadata behavior

Gallery Edit keeps imported source metadata separate from editable working prompt fields.

- A1111 / Forge / WebUI parameters and NovelAI EXIF prompt data continue to populate editable prompt fields when available.
- ComfyUI workflow/API JSON stored in PNG `prompt` metadata is treated as workflow metadata, not as positive prompt text.
- Raw workflow metadata remains available for inspection and workflow-aware regeneration.
- If Comfy prompt text cannot be resolved safely, the editable positive prompt should remain empty rather than showing JSON.

## Comfy workflow prompt extraction

Comfy prompt extraction starts from KSampler positive/negative links and resolves linked text-producing graphs conservatively.

Supported common structures include:

- direct CLIPTextEncode text
- linked Text String / Text Multiline nodes
- Text Concatenate-style nodes
- `PCLazyTextEncode`
- Schedule Prompt-style nodes when text is available through direct or linked text inputs
- Anima / Prompt Control-style text graphs such as `KSampler -> PCLazyTextEncode -> Text Concatenate -> Text Multiline`

The extractor does not guess positive/negative roles from multiple unrelated text nodes by list order.

## Workflow Presets

Workflow Presets are reusable shared ComfyUI workflow templates. Effective workflow resolution stays conservative:

1. embedded line ComfyUI workflow metadata when usable and not forced off
2. project workflow path when configured and present
3. selected Workflow Preset when available
4. shared workflow path fallback

Workflow Presets do not mutate imported metadata, source generation snapshots, editable prompt fields, or project save/load schema.
