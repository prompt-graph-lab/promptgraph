# PromptGraph Pro 1.0.0 User Guide

## What PromptGraph Pro does

PromptGraph Pro is a Gallery-first Windows workspace for building and reviewing
AI illustration sequences. It keeps editable prompts, imported metadata,
current main images, generated Candidates, Variants, and workflow references
available while you decide what belongs in the final sequence.

It is designed around explicit review. Generation creates Candidates first;
the application does not silently replace an Illustration's main image.

PromptGraph Pro 1.0.0 public-release documentation is intentionally text-only. Old
development screenshots were removed because they did not represent the
current Gallery-first interface. Release validation compares this guide with the
real application and the selected source tree.

## First setup and launch

PromptGraph Pro 1.0.0 supports Windows 11 x64 with CPython 3.14.x x64.

1. Obtain an official PromptGraph Pro 1.0.0 source checkout or release
   package in a new directory.
2. Run `setup.bat` once.
3. If setup reports that an existing `.venv` does not exactly match the lock,
   rename or remove that application-local `.venv` and run setup again.
4. Run `run.bat` for normal use.
5. Open the local address shown by Streamlit in current Edge or Chrome at 100%
   zoom.

The primary distribution is a clean public Git source checkout. A convenience
archive is optional and, if offered, uses the same reviewed source bytes.
Python, ComfyUI, and an installer are not bundled. See the
[Supported Environment](supported-environment.md).

## Where user data lives

- Projects normally live under the configured default Project root. Each saved
  Project has its own directory and Project JSON.
- The Global Module Library defaults to
  `%USERPROFILE%\PromptGraph\modules\global_modules.json`. The
  `global_module_library_dir` setting can override its directory.
- Application preferences and path references live in application-local
  `.editor_settings.json`.
- Final Images Export writes derived output under the active Project.
- Candidate/Variant files may be external until Project Assets localizes them.
- A main/source image, workflow, or other reference can remain outside the
  Project directory.

Back up external references as well as the Project directory. Project Assets
does not automatically collect or relink every external asset.

## User interface map

### Daily Sidebar

The Sidebar owns current Project status, Project discovery and Recent Projects,
Quick Save, Advanced direct JSON Open and Save As, Project Assets, daily
Workflow Preset/effective ComfyUI status, common history controls, and
contextual launchers. Project Assets remains in the Sidebar for Pro v1.

### Main editing modes

- **Gallery** is the primary production surface for Illustration review,
  prompt editing, Scene organization, generation, Candidate/Variant work,
  Sequence Preview, and Final Images Export.
- **Graph Edit** provides Project-wide prompt structure, PromptCloud, search,
  batch and graph-assisted editing. Graph-only controls appear here and in
  Focus Edit where applicable, not in Gallery.
- **Focus Edit** edits one Illustration while retaining Project-wide graph
  context.
- **Trash** shows deleted Illustrations and supports restore without deleting
  the referenced source image file.

### Management workspaces

- **Project Management** owns the default Project root, New Project, Duplicate
  Project, and safe Existing Project Import. It does not own Project Assets in
  Pro v1.
- **Module / Attribute Authoring** owns the Global Module Library, AnimaDex
  import, Project Module creation/editing and inspection, Rename Module, and
  standalone Attribute Group management.
- **Module / Attribute Apply** owns Module Toggles, Saved Module Reference
  Insertion, Module Candidate Selection, and Attribute Group Swap.
- **ComfyUI Settings** owns endpoint/shared-workflow configuration plus read-only
  workflow inspection, prompt/LoRA export helpers, LoRA mapping, Negative Prompt
  Consistency, Global Negative/Delta Preview, and Generation Settings
  Consistency. Workflow Preset selection and generation execution remain with
  the daily Sidebar and Gallery/Focus Edit.

Gallery Operations keeps generation, scoped Candidate adoption, prompt/Module/
Attribute operations, and Variant promotion with the production context they
act on. Each operation's own scope remains authoritative.

## Create or open a Project

Open Project Management to set the default root, create a Project, duplicate a
complete Project directory, or safely import an existing Project into the root.
The Sidebar provides normal Project discovery, Recent Projects, direct JSON
Open under Advanced, and Save As.

New Project and Duplicate Project are different from a Derived Project. A
duplicate copies the Project directory; a Derived Project materializes a
reviewed final sequence into a new editable baseline.

## Gallery-first production loop

1. Create or open a Project.
2. Import images/metadata or create prompt-only Illustrations.
3. Review the Gallery and edit positive or negative prompts.
4. Generate Candidates for one Illustration or an available Gallery scope.
5. Explicitly adopt, swap, or insert useful Candidate images.
6. Keep close alternatives as Candidates or Variants.
7. Use Workbench for scratch exploration outside the main sequence.
8. Add and arrange Scene separators.
9. Review Sequence Preview for prompt/image alignment and ordering.
10. Use Final Images Export to write ordered copies.

Review prompt and image together after prompt-only or image-only operations.
The application does not infer that a changed prompt still describes the
selected image.

## Illustrations and Scenes

An Illustration is one editable sequence item with prompt, image, metadata,
Candidate, and Variant context. A Scene is the current user-facing grouping
bounded by a Scene separator. Scenes are sequence organization, not a separate
cross-Project object.

Workbench Illustrations and deleted Illustrations are outside the normal final
sequence. Scene-based scopes include only eligible Illustrations owned by the
selected Scene; All Illustrations can also include eligible items outside
separator-bounded Scenes.

## Candidates and main-image adoption

Generation adds Candidates first. It does not silently replace the main image.
You can review a Candidate and then:

- set it as the main image for an image-less Illustration;
- swap it with the current main image, keeping the prior main image as a
  Candidate;
- insert it as a new Illustration near its source or at the current Scene end;
- adopt its positive prompt without changing the image reference.

Candidate image adoption and Candidate Prompt Adoption are separate. Ordinary
adoption does not move or delete source or Candidate files.

## Variants

Variants are nearby alternative Illustration records that can be reviewed and
promoted through Gallery Operations. Promotion creates normal Gallery
Illustrations from eligible Variants; it does not consume the source Variant or
silently rewrite the parent Illustration.

## Workbench

Workbench is a per-Illustration scratch area for exploratory generation and
Candidate review. It keeps source linkage, notes, and its own Candidate pool,
but it is excluded from the normal graph, batch, Gallery-wide generation, main
sequence, Derived Project, and Final Images Export targets.

## Sequence Preview and Final Images Export

Sequence Preview is read-only. It shows the same resolved main-image order used
by Final Images Export and excludes Scene separators, Workbench, deleted, and
image-less Illustrations.

Final Images Export writes new ordered copies. It never rewrites source images.
Optional metadata stripping affects exported PNG copies only. Its manifest uses:

```text
manifest_version: 2
path_contract: portable-relative-v1
```

Moving the complete export directory preserves manifest-relative output
references. External source provenance is reduced to the current portable
privacy contract, but prompts and Scene labels remain user-authored content.
Final Export is not a Project backup, an import format, anonymization, or a
publishing system.

## Graph Edit

Graph Edit visualizes prompt structure and supports graph-assisted Focus Edit,
PromptCloud, search, batch changes, and Module/Attribute analysis. Its
Illustration Browser can filter Scenes, collapse groups, and page Illustration
editors without changing Project data or limiting Project-wide save/export
semantics.

Save unsaved per-Illustration drafts before changing Graph Edit browser pages,
filters, or collapsed groups.

## Modules and Attribute Groups

Project Modules provide reusable prompt blocks inside one Project. The Global
Module Library copies reusable Module definitions between Projects. Attribute
Groups store named alternatives that can be previewed and applied with the
supported scope.

Author definitions in Module / Attribute Authoring. Use preview-first
production changes in Module / Attribute Apply or the applicable Gallery
Operation. Negative Attribute metadata remains preview information unless the
specific operation explicitly owns a negative-prompt change.

The Global Module Library is written as a complete normalized JSON document to
a same-directory temporary file and atomically replaces the authoritative file
only after a successful write. This is not history, synchronization, backup,
or multi-process conflict merging.

## ComfyUI generation

ComfyUI is optional for Project editing, import, review, save/reopen, and Final
Images Export. Generation requires an explicitly configured compatible endpoint
and a usable workflow source.

PromptGraph Pro can resolve embedded workflow metadata, a Project override, a
Workflow Preset/shared path, or forced shared workflow according to current
settings. Generated outputs return as Candidates. Test configuration against a
disposable endpoint before production use; Pro 1.0.0 does not guarantee every
third-party node or workflow family.

## Project Management

Project Management owns:

- Default Project root;
- New Project;
- Duplicate Project;
- safe Existing Project Import.

Saving/resetting the default root does not create directories or move existing
Projects. A New Project can override the parent directory for that creation.

## Module / Attribute Authoring and Apply

Authoring owns the Global and Project libraries, AnimaDex import, Project Module
creation/editor/inspector, Rename Module, and Attribute Group management. Apply
owns Module Toggles, Saved Module Reference Insertion, Module Candidate
Selection, and Attribute Group Swap. Module usage analysis and persistent Module
Edit Scope remain contextual Sidebar analysis.

Preview/apply tools can reject a stale preview when prompts, images, scope,
library data, or Project structure changed after preview. Build a fresh preview
instead of bypassing that guard.

## ComfyUI Settings

Use this workspace for ComfyUI URL, fallback workflow path, force-shared
workflow, workflow inspection/export helpers, LoRA mapping, and consistency
analysis. These analysis tools are read-only. Normal workflow selection and
generation execution stay in their daily editing owners.

## Project Assets

Project Assets remains a single Sidebar owner in Pro v1. It previews and copies
external Candidate and Variant references into the active Project while
deduplicating repeated source references and avoiding overwrites. Preview does
not create directories, copy files, or change the Project.

It does not move or delete source files, redesign `generated/`, or guarantee
localization of a main/source image, arbitrary workflow, or other external
asset. Verified Duplicate Cleanup only removes eligible generated-source
duplicates after retained Candidate copies are verified; it is not general
filesystem cleanup.

## Sequence Snapshots and Derived Projects

A Sequence Snapshot stores the current Project-wide main-image selection for
later apply/compare/storyboard review. It is not automatic Project version
history and does not capture every file or setting.

A Derived Project materializes the reviewed resolved image sequence into a new
editable Project while leaving the source Project and source files unchanged.
It can create a new derived baseline or append eligible not-yet-materialized
Scenes to a compatible Derived Project. It is not a generic cross-Project merge
or automatic backup system.

Derived Project is the user-facing name for the existing internal Lightweight
Fork implementation.

## Save, Save As, and persistence safety

Quick Save and normal Project-save owners serialize the complete Project JSON
to a temporary file in the destination directory, flush and close it, then use
atomic replacement. A failed write does not intentionally replace the previous
valid Project JSON, and temporary files are cleaned where possible. Atomic save
is not backup or version history.

Save As uses one click when the destination is new. If it would overwrite an
occupied Project JSON, the UI shows the normalized destination and requires an
acknowledgment plus a separate explicit overwrite confirmation. Changing the
source Project, destination directory, or filename invalidates confirmation.

Application-local `.editor_settings.json` stores preferences and path
references. Its writer is not atomic. Settings are not primary Project data and
are not a substitute for backup.

## Backup before upgrade

Before an upgrade, back up:

- the complete directory of every important Project;
- every required image, workflow, or other asset referenced outside it;
- the resolved Global Module Library;
- settings when recreating preferences/paths would be inconvenient.

Keep the previous application directory and use a separate directory for the
new version. Do not copy `.venv`. Follow the full
[Backup, Upgrade, Rollback, and Recovery Guide](backup-upgrade-rollback.md).

## Common recovery cases

- **Project image is missing:** restore the external file to its original
  resolved path, or use a supported localization action before loss. Do not
  treat manual Project JSON editing as the normal repair path.
- **Project JSON open fails:** preserve the malformed file and open a known-good
  backup from another path. Do not overwrite the only copy while diagnosing it.
- **Global Module Library appears empty:** preserve the library file; malformed
  content can fail closed to an empty-looking state. Restore or inspect a
  backup before saving.
- **Save As target already exists:** verify the shown normalized path and use
  the separate confirmation only when replacement is intentional.
- **Settings are lost:** Projects and the Global Module Library remain separate
  data, but path preferences may need to be configured again.

## Terminology

| User-facing term | Meaning |
| --- | --- |
| Illustration | One editable Gallery sequence item. |
| Scene | A separator-bounded group in the current Project sequence. |
| Graph Edit | Graph-assisted structural editing mode. |
| Derived Project | A new editable baseline materialized from reviewed final images. |
| Sequence Snapshot | A stored Project-wide main-image selection for review/apply. |

Compatibility note: Illustration is represented internally by `PromptLine`;
Scene uses separator-based internal `route_*` structures; Derived Project uses
the internal `lightweight_fork` implementation; and Sequence Snapshot uses the
internal `route_snapshots` representation. These identifiers remain for saved
data and implementation compatibility and do not introduce a separate current
Route object.

## Known limitations

- Supported distribution is Windows 11 x64 and CPython 3.14.x x64; Python,
  ComfyUI, and an installer are not bundled.
- There is no automatic Project backup, version history, cloud synchronization,
  automatic external-asset collection, or arbitrary JSON repair.
- Project and Global Module Library writes are atomic at their documented file
  replacement boundaries; settings writes are not atomic.
- Project compatibility is validated against the release fixtures, not every
  unknown third-party extension field.
- Final Export is derived output, not a Project backup.
- Prompts, images, metadata, external paths, and workflows may be sensitive.
  Inspect Projects, exports, and backups before sharing.
- Exact source-tree, browser/DPI, current-UI, disposable ComfyUI, backup,
  rollback, exposure, and release-candidate checks remain part of release QA.
  Exact-archive checks apply only if a convenience archive is selected.

## License and content provenance

PromptGraph-authored source code, documentation, and synthetic examples or
fixtures are released under the repository's [MIT License](../LICENSE),
Copyright (c) 2026 PromptGraph Lab., unless a file states otherwise. The
runtime packages in `requirements.txt` are installed separately by `setup.bat`
and are not copied into this source tree. User Projects, external images, and
Global Libraries remain external/user data and are not part of the source
release. No `workflows/*.json` files are tracked in the current source tree;
future workflow sample inclusion requires a separate provenance review, without
assuming that workflow rights are user-owned. The dependency and sample-content
audit, including the decision not to add a repository-level NOTICE file for
source-only distribution, is in the
[public OSS release process](release-process.md#license-and-attribution-audit).

See the [PromptGraph Pro 1.0.0 release notes](releases/1.0.0.md) for the full
release boundary.
