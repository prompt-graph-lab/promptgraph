# Backup, Upgrade, Rollback, and Recovery

This guide describes the supported PromptGraph Pro 1.0.0 Windows process for
an official public source checkout or release package. It does not provide
automatic backup, migration, downgrade compatibility, repair, or version
history. A convenience archive is optional; if selected, it uses the same
reviewed source bytes and provenance.

> Before opening important existing data in a new PromptGraph version, close
> PromptGraph and make an ordinary filesystem copy of the complete Project
> directory, every Project-referenced image/workflow/other required asset
> outside that directory, and the resolved `global_modules.json` file.

## Where data lives

### Projects

A normal Project is one Project JSON plus its containing Project directory.
The current folder-layout owner creates these standard directories beside the
Project JSON:

```text
refs/
candidates/
routes/
exports/
workflows/
```

The complete directory may also contain generated images and other
Project-owned files referenced by Candidates, Variants, lineage records, or
workflows. Variants are records/asset references; there is no separate standard
`variants/` directory. The safest backup unit is the complete Project directory,
not only `project.json`. Project JSON can also retain external absolute paths to
main/source images, workflows, or other required assets. In that case, the
Project directory alone is a partial backup; a complete backup also preserves
every required externally referenced asset.

Projects are external user data and are excluded from the application
source/release package.

### Global Module Library

The default directory is:

```text
%USERPROFILE%\PromptGraph\modules
```

The default file is:

```text
%USERPROFILE%\PromptGraph\modules\global_modules.json
```

`global_module_library_dir` can override the directory. The authoritative file
is the resolved directory shown/configured in Module / Attribute Authoring plus
`global_modules.json`. Back up that resolved file, not only the default path.

### Application settings

Settings are stored as `.editor_settings.json` relative to the running
application directory. Each separately extracted version therefore has its own
settings file unless a user manually copies it.

Settings can contain recent/last Project paths, the Project root, Global Module
Library directory, ComfyUI URL/workflow paths, AnimaDex path, image/archive
paths, and other preferences. They are not Project or Library data.

The settings writer is not atomic. If preserving complex path configuration is
important, an optional copy of `.editor_settings.json` is useful, but it is not
a substitute for creative-data backup.

### Runtime and Final Export

Each extracted application version owns its own `.venv/`. It is disposable
runtime state, not user data, and must not be copied to a new version.

Final Images Export defaults below:

```text
<Project directory>\exports\final\<timestamp>\
```

Final Export is derived output, not the authoritative Project backup.

## What to back up

Required for every important Project:

- the complete Project directory;
- its Project JSON;
- Project-local images and Candidate/Variant-referenced assets;
- every required image outside the Project directory referenced as a main,
  source, Candidate, or Variant image;
- every required externally referenced workflow or other asset needed to
  reproduce the Project;
- `refs/`, `candidates/`, `routes/`, `workflows/`, and other Project-owned files;
- `exports/` when those derived copies should also be retained.

A copy of only the Project directory is a partial backup whenever Project JSON
still references an asset outside it. Preserve external assets in an explicit
backup inventory with their original resolved paths and SHA-256 values where
appropriate. Restoring to the same resolved paths avoids changing Project JSON.
Alternatively, before upgrade, use a supported operation that copies the
particular asset into the Project, then confirm the saved Project references
the Project-local copy and that Gallery/Final Export resolve it. Support varies
by asset type; do not assume Project Assets copies a main/source image. Manual
Project JSON path editing is not recommended, and PromptGraph does not
automatically collect or relink arbitrary external assets.

Required when Global Modules are used:

- the resolved `global_modules.json` file.

Optional:

- the old application directory's `.editor_settings.json`, as a preference and
  path-reference backup only.

Not required for creative-data backup:

```text
.venv/
__pycache__/
.pytest_cache/
dist/
logs
temporary files
```

## Verify the backup

Before upgrade, inventory paths referenced by Project JSON. Confirm each
required asset is either inside the copied Project directory or included in the
external-asset backup, and record where it must be restored. Confirm copied
files exist, their sizes are plausible, and the Project/Library files open as
UTF-8 JSON. For important files, compare SHA-256; hashing every image is
optional rather than the only supported method.

```powershell
Get-FileHash .\project.json -Algorithm SHA256
Get-FileHash .\global_modules.json -Algorithm SHA256
Get-FileHash <external-image-path> -Algorithm SHA256
```

Keep the source and backup on separate paths. Never diagnose corruption by
overwriting the only backup.

## Supported separate-directory upgrade

1. Close PromptGraph and keep the old application directory.
2. Back up every important complete Project directory, all required assets it
   references outside that directory, and the resolved `global_modules.json`.
3. Obtain and verify the official public source checkout or release package.
4. Place it in a new, separate application directory. Do not copy it over the
   old version.
5. Do not copy `.venv`. Run the new directory's `setup.bat`.
6. Start it with that directory's `run.bat`.
7. Reconfigure the Project root, Global Module Library path, ComfyUI, AnimaDex,
   and other paths as needed.
8. First open a backup copy or non-critical Project.
9. Verify Gallery, image paths, Candidates, Variants, Modules, Attributes,
   Scenes, Sequence Snapshots, and Sequence Preview.
10. Save only after the data looks correct.
11. Keep the old version and backups until normal production work succeeds.

In-place application updates are unsupported.

## Settings transfer

Prefer reconfiguring paths in the new version. Copying `.editor_settings.json`
is optional convenience, not a migration guarantee: the file can contain stale
absolute paths and Recent Project entries. The old directory retains its own
settings for rollback. Never copy `.venv` with settings.

If settings are missing, PromptGraph loads defaults. If they are malformed or
unreadable, PromptGraph also falls back to defaults. Preserve or rename the old
file, let PromptGraph recreate settings, and reconfigure paths through the UI.
Do not delete the preserved copy until configuration is verified.

## Shared Global Module Library

Two extracted versions can be configured to the same external Global Module
Library. The supported safe process is:

1. back up `global_modules.json`;
2. configure/open the library in the new version;
3. verify normalized Modules and Unicode content;
4. if a write must be validated, make a small disposable change first;
5. retain the backup.

The Global Module Library writer serializes normalized data to a same-directory
temporary file, flushes it, and atomically replaces the authoritative file.
Atomic replacement is not history, synchronization, locking, or protection
from a valid but unwanted logical change.

An unreadable or malformed Global Module Library may appear empty. Do not
immediately save an empty library over the only copy. Stop, preserve the file,
and restore or inspect a backup first.

## Rollback

1. Stop the new version; do not delete its directory yet.
2. Reopen the previous extracted application directory.
3. Use that previous directory's original `.venv` and settings.
4. If the new version saved Project changes, restore the complete pre-upgrade
   Project directory backup to a separate working location.
5. Restore every required external image, workflow, and other asset from the
   pre-upgrade backup to the same resolved paths recorded before upgrade. If a
   supported pre-upgrade operation already copied an asset into the Project,
   use the verified Project-local reference instead; do not manually rewrite
   Project JSON as the normal recovery procedure.
6. If the new version wrote the shared library, restore the pre-upgrade
   `global_modules.json` backup.
7. Start the previous version and open the restored backup copy.
8. Verify Gallery, external and Project-local images, Final Export preview,
   prompts, Modules, and sequence state before resuming
   production.

Rollback compatibility does not mean an older PromptGraph version is
guaranteed to open a Project or Global Module Library after a newer version has
rewritten it. The safe rollback source is the pre-upgrade backup.

## Project JSON compatibility

Current Pro 1.0.0 Projects saved by the current writer reopen in Pro 1.0.0.
The loader supplies exercised defaults for missing Project metadata, Sequence
Snapshots, negative prompts, Candidate/Variant collections, and other current
optional fields. It normalizes legacy flat Module bodies into the current
Module representation.

Normal Project saves write a temporary JSON in the destination directory,
flush/fsync it, and call atomic replacement only after serialization succeeds.
A serialization, flush, or replacement failure does not intentionally replace
the last valid destination. Atomic save is not backup or version history.

Project JSON can reference files outside its directory. Project-relative paths
are more portable than external absolute paths; opening a Project does not make
every external path portable. A first save in a newer version may normalize the
data into the current serialized form.

Unknown extension fields are not guaranteed to survive a load-and-save cycle.
The loader filters unknown Project and PromptLine fields; focused tests prove
selected Module/Candidate/Variant extension metadata only where explicitly
covered.

Pro 1.0.0 supports the older Project shapes exercised by the compatibility
fixtures and current loader tests. Back up untested Projects before first open
and save. The committed synthetic fixture omits modern Project metadata,
Sequence Snapshots, and a negative prompt; it uses a legacy flat Module, Unicode
relative image paths, and one normal Illustration. Tests load it, rebuild the
graph, save to a new Unicode destination, reopen it, keep the source fixture
byte-identical, and reject unexpected temporary-machine paths in saved JSON.

## Failed Project save

- Stop repeated writes and preserve the displayed error.
- Do not assume unsaved in-memory edits are durable after browser/process exit.
- Verify the existing Project JSON before continuing.
- Resolve disk-space, permission, path, or filesystem problems.
- Use Save As to a new destination where appropriate.
- Do not overwrite the only backup during diagnosis.

When the atomic writer fails before replacement, the last valid Project JSON
remains. This does not recover unsaved session edits.

## Malformed Project open

A malformed Project is not automatically migrated or repaired. The normal
Project transition assigns the newly loaded Project only after JSON load and
graph rebuild succeed, so an already loaded valid Project remains active on
the exercised failure paths.

Preserve the malformed file, restore a known-good backup to a new location,
and use normal Open or Advanced direct JSON Open on the restored copy. Do not
save over the malformed original until a backup exists; manually compare any
recovered data when necessary.

## Save As and existing-Project import

An occupied Save As destination displays the normalized target and requires an
acknowledgment plus a separate explicit confirmation. Target/source changes
invalidate confirmation. Save As does not automatically create version history.

Safe Existing Project Import copies a valid existing Project directory into
the configured Project root through a separate staged destination. It is not a
malformed-JSON repair tool and does not replace ordinary backup. Successful
tests keep source data unchanged; use a separate destination and save current
session changes before importing because disk state is authoritative.

## Global Module Library compatibility

The loader accepts either a direct top-level Module mapping or the legacy
`{"module_library": {...}}` wrapper. Flat string entries become current Module
records; current nested Module Graph records are normalized and validated.
Focused tests exercise Unicode, flat/current shapes, save/reopen, malformed
fail-soft behavior, and preservation of explicit extension metadata.

Writes are atomic, but there is no automatic history. Unknown top-level formats
or arbitrary future Module shapes are not guaranteed.

## Final Export manifest v2

Final Images Export writes `export_manifest.json` beside exported image copies:

```text
manifest_version: 2
path_contract: portable-relative-v1
```

`output_dir` is `.` and output paths are manifest-relative. Project identity is
reduced to the Project JSON filename. Project-local source provenance remains
relative; external provenance is intentionally filename-only/unknown according
to the privacy path contract. Moving the complete export directory preserves
manifest-relative output references.

This manifest is an export record, not a Project file, not a Project backup,
not an application upgrade manifest, not an import format, and not complete
Project/Candidate/Variant history. Pro 1.0.0 does not import Final Export
manifests or automatically migrate manifest v1.

Metadata stripping changes exported PNG copies only. It does not delete or
rewrite source images or Project-linked files.

## Missing external assets

A Project can still contain an external path that is missing on the current
machine. Opening the JSON does not repair that dependency. Restore the asset
from backup to its original resolved path. Alternatively, if a supported
pre-upgrade operation copied that asset into the Project and the saved reference
was verified, use that Project-local copy. Do not treat manual Project JSON path
editing as the normal recovery procedure. Preview Gallery/Final Export before
saving or exporting. Missing images are skipped or reported by the operation
that needs them; do not treat a successful JSON load as proof that every linked
file exists.

## Privacy and security

Projects, Global Libraries, backups, and exports may contain prompts and
negative prompts, image paths and filenames, generation metadata, workflow
information, model/LoRA names, external absolute paths, user-authored notes,
and source/generated images. Inspect them before public upload.

The official clean public source tree and any optional archive exclude Projects,
`.editor_settings.json`, Global Modules, user workflows, and images. The public
exposure audit verifies that boundary. Final Export metadata stripping does not
sanitize Project JSON, backups, or release notes. Export manifests may retain
prompt text and selected provenance fields.

SHA-256 detects byte changes but is not an identity/signature system by itself.
For any future archive, compare the digest with the exact value published by the
official OSS release channel. ComfyUI endpoints can be local or remote and
should be configured intentionally. Release QA uses disposable endpoints and
synthetic data, not production services.

PromptGraph does not claim encryption, signing, sandboxing, or secret scanning
for user Projects.

## Mandatory human validation

Release-candidate QA still requires visual UI and normal-browser behavior, DPI/scaling,
Gallery and Graph Edit workflow review, setup/first/repeated launch from the
exact clean public candidate tree, disposable ComfyUI generation, image/prompt
alignment, backup/upgrade/rollback rehearsal, documentation/screenshot
accuracy, public-tree exposure review, and final known-limitations approval.
Checksum, embedded-metadata, extraction, and byte-identity checks apply only if
a convenience archive is selected.

Automated tests and the synthetic pre-release rehearsal do not replace those
checks. See [PromptGraph Pro 1.0.0 release notes](releases/1.0.0.md),
[Release Process](release-process.md), and
[Supported Environment](supported-environment.md).
