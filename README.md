# PromptGraph Pro

PromptGraph Pro 1.0.0 is a Gallery-first Windows workspace for reviewing AI
illustration sequences, editing positive and negative prompts, generating and
selecting image Candidates, organizing Scenes, inspecting prompt structure,
and exporting a reviewed final sequence. Generation is explicit and
Candidate-first: it does not silently replace an Illustration's main image.

## Start here

- Version: `1.0.0`
- Release line: `1.0.0`
- Release tag (if used): `v1.0.0`
- Distribution model: public open-source software from a clean source tree
- Supported platform: Windows 11 x64 with CPython 3.14.x x64
- Browser: current Microsoft Edge or Google Chrome at normal desktop zoom

The primary distribution is a clean public Git source tree. A deterministic
convenience archive, if offered, uses the same reviewed bytes and provenance;
the source tree remains useful independently of that optional channel.

From an official public source checkout or release package:

1. Install a supported CPython 3.14.x x64 interpreter if necessary.
2. Run `setup.bat` once. It creates the application-local `.venv` and verifies
   the exact dependency lock.
3. Run `run.bat` for normal use.
4. Open the local Streamlit address shown by the launcher in Edge or Chrome.

Do not copy an old `.venv` into a new application directory. See the
[Supported Environment](docs/supported-environment.md) for the exact runtime,
browser, setup, and ComfyUI boundaries.

## Gallery-first workflow

The ordinary production loop is:

1. Create or open a Project.
2. Import image metadata or create prompt-only Illustrations.
3. Review the Gallery and edit prompts.
4. Generate Candidates.
5. Explicitly adopt, swap, or insert useful Candidate images; Candidate Prompt
   Adoption is a separate prompt-only action.
6. Keep close alternatives as Candidates or Variants and use Workbench for
   scratch exploration outside the normal sequence.
7. Organize Illustrations into Scenes.
8. Review Sequence Preview.
9. Use Final Images Export to write ordered copies.

Gallery is the primary production surface. Graph Edit supports structural
inspection and graph-assisted editing; Focus Edit handles one Illustration in
context. Project Management, Module / Attribute Authoring, Module / Attribute
Apply, and ComfyUI Settings are dedicated management workspaces. Current
Project status, Project discovery, Quick Save, Advanced Open / Save As,
Project Assets, daily workflow status, and common history controls remain in
the Sidebar. Project Assets remains in the Sidebar for Pro v1 and localizes
Candidate/Variant assets, not arbitrary main/source images.

For operational details, read the
[PromptGraph Pro 1.0.0 User Guide](docs/user-guide.md).

## Data and save safety

Project JSON saves use a same-directory temporary file and atomic replacement.
A failed write does not intentionally replace the previous valid Project JSON,
but atomic save is not backup or version history. Save As uses one click for a
new destination; an occupied destination requires acknowledgment and a
separate explicit overwrite confirmation. Changing the source or target
invalidates that confirmation.

The Global Module Library is also written as a complete atomic replacement.
It does not provide history, synchronization, or conflict merging.
Application-local `.editor_settings.json` stores preferences and path
references; its writer is not atomic and it is not primary Project data.

Before upgrading, back up each complete Project directory plus every
Project-referenced image/workflow/other required asset outside it. A
Project-directory-only copy is a partial backup when external references
remain. Follow the
[Backup, Upgrade, Rollback, and Recovery Guide](docs/backup-upgrade-rollback.md).

## Final Images Export

Final Images Export writes new ordered copies under the Project's export
directory. It does not rewrite source images. Optional PNG metadata stripping
affects exported PNG copies only.

`export_manifest.json` uses `manifest_version: 2` and
`path_contract: portable-relative-v1`. Moving the complete export directory
preserves its manifest-relative output references. External provenance is
reduced according to the current privacy contract, but prompts and Scene labels
remain user-authored content. Final Export is derived output, not a Project
backup, publishing system, or anonymization tool.

## Documentation

- [User Guide](docs/user-guide.md): setup, interface map, production workflow,
  persistence, recovery, and terminology.
- [Release Notes](docs/releases/1.0.0.md): implemented workflows and known
  limitations for 1.0.0.
- [Changelog](CHANGELOG.md): compact release index.
- [Supported Environment](docs/supported-environment.md): supported Windows,
  Python, browser, dependency lock, and ComfyUI boundaries.
- [Backup, Upgrade, Rollback, and Recovery Guide](docs/backup-upgrade-rollback.md):
  data locations and verified recovery procedures.
- Former pixivFANBOX distribution work is historical material; it is not part of
  the source-only OSS tree or release contract.
- [Release Process](docs/release-process.md): public-tree provenance, gated
  clean-repository bootstrap, release-candidate publication boundary, and the
  license/attribution audit.

These user documents are self-contained for a clean public source tree and any
optional release archive. Release engineering keeps the selection manifest and
export checks on its private side; the public tree carries the reviewed source
bytes, runtime contract, and product tests. Roadmap, research, and historical
planning remain excluded.

## Related research

- [LineageEditor](https://github.com/m-otani/LineageEditor) — a research
  prototype that generalizes ideas explored in PromptGraph's Lineage from
  prompt and illustration editing to research processes involving conditions,
  evidence, decisions, artifacts, dependencies, and revisions.

## Source repository note

User-facing Pro v1 terminology is defined by the current product UI and the
packaged User Guide. In source checkouts, `core/version.py` owns release
identity; `python -m core.version --json` prints it without starting the app.
Contributors maintain direct dependency intent in `requirements.in` and the
exact distributable runtime lock in `requirements.txt`. The public source tree
includes the supported runtime inputs described by the release contract.

## Screenshot policy

PromptGraph Pro 1.0.0 public-release documentation is intentionally text-only. Old
development screenshots were removed because they no longer represented the
current Gallery-first interface. A genuine current application capture is part
of exact-candidate human validation; no reconstructed or stale image is used as
release documentation.

## Limits and privacy

- PromptGraph Pro does not include Python, ComfyUI, an installer, cloud backup,
  automatic Project migration, or multi-user synchronization.
- ComfyUI generation is optional and requires an explicitly configured,
  compatible endpoint and workflow.
- Source images, Candidate files, Projects, Global Libraries, and settings are
  not uploaded by the packaged application as a release function.
- Projects, exports, backups, and Global Libraries may contain prompts, image
  paths, workflow data, or images. Inspect them before sharing.
- User review remains required to prevent image/Prompt drift after prompt or
  main-image changes.

See the [1.0.0 release notes](docs/releases/1.0.0.md) for the full limitation
boundary.

## License

PromptGraph-authored source code, documentation, and synthetic examples or
fixtures are released under the [MIT License](LICENSE), Copyright (c) 2026
PromptGraph Lab., unless a file states a different license. Runtime packages
are installed separately from the exact `requirements.txt` lock; they are not
vendored into this source tree. See the
[license and attribution audit](docs/release-process.md#license-and-attribution-audit)
for the dependency, asset, sample-content, and notice-file boundary.
