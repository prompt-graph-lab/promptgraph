# PromptGraph Pro 1.0.0 Public OSS Release Contract

This document is the canonical release, provenance, and publication contract
for the PromptGraph Pro 1.0.0 public open-source release. It describes the
required gates and evidence; publication-channel metadata is recorded when a
release channel is selected.

## Release model

Public Git source in a clean canonical repository is the primary distribution.
The reviewed source candidate and the clean bootstrap are distinct provenance
artifacts; Git history is not transplanted automatically, and this document
does not prescribe a hosting name.

The release path is:

```text
reviewed source candidate
    -> release-engineering inventory and exposure review

vetted clean public source tree
    -> deterministic inventory and hash comparison

clean public repository bootstrap commit
    -> public release-candidate human QA

canonical public v1.0.0 commit and annotated tag
    -> OSS publication

optional: QA-passed deterministic convenience archive
```

The candidate commit SHA and public bootstrap commit SHA differ when history is
reset. Provenance records both identifiers and verifies file content; it never
requires identical Git commit IDs between the two repositories.

## Authoritative version and tag

[`core/version.py`](../core/version.py) is the sole machine-readable application
version source. PromptGraph Pro v1 is version `1.0.0`; a release tag, if used,
is `v1.0.0`.

Support diagnostics are:

```bash
python -m core.version
python -m core.version --json
```

`PROMPTGRAPH_BUILD_SHA` may provide a validated full commit SHA to an optional
archive build. Otherwise the diagnostic reads the current Git checkout when
available. The release tag uses `v<MAJOR>.<MINOR>.<PATCH>`, is annotated,
points to the exact canonical public commit that passed release-candidate QA,
and is never moved or reused after publication.

## Mandatory publication gates

Public publication is blocked until all of these named gates complete:

1. The license and attribution gate finalizes the public license, copyright,
   attribution, dependency notices, and sample-content rule.
2. The public-tree exposure gate audits the exact selected tree for secrets,
   private/local data, inappropriate assets and fixtures, path disclosure, and
   documentation scope.
3. The clean-repository bootstrap gate creates a new public Git history only
   after the first two gates pass, records candidate/bootstrap provenance, and
   verifies the bootstrap tree against the approved inventory and hashes.
4. The release-candidate QA gate runs human validation against the exact public
   candidate.

An optional archive gate decides whether to generalize deterministic archive
tooling for a convenience archive. It does not block a source-only OSS release
unless the release model explicitly makes an archive mandatory.

## License and attribution audit

The license and attribution gate records the release-engineering conclusion for
the source-only OSS distribution. It is not formal legal advice.

### Final source license and holder wording

PromptGraph Pro v1 public source code uses the standard [MIT License](../LICENSE).
The existing `LICENSE` text is the canonical MIT text and remains unchanged;
its holder line is exactly `Copyright (c) 2026 PromptGraph Lab.`. Repository
history uses `PromptGraph Lab.` as the project attribution, so this audit does
not invent a legal entity or replace that wording with a personal name.

The MIT-covered repository surface is PromptGraph-authored source code,
documentation, and synthetic examples or fixtures, unless a file explicitly
states a different license. A license notice in this repository does not grant
rights to user Projects, external images, model files, workflow assets, or other
third-party material.

### Runtime dependency audit

`requirements.in` declares six direct runtime dependencies: `matplotlib`,
`requests`, `streamlit`, `streamlit-agraph`, `websocket-client`, and `wordcloud`.
The exact versions are shown once each in the table below. The exact
`requirements.txt` lock resolves 54 packages;
the entries below account for every non-comment lock line. License families
come from the matching distribution metadata and `LICENSE`/`COPYING`/`NOTICE`
files in the validated CPython 3.14 environment. The direct projects expose
their upstream sources as [Matplotlib](https://github.com/matplotlib/matplotlib),
[Requests](https://github.com/psf/requests),
[Streamlit](https://github.com/streamlit/streamlit),
[streamlit-agraph](https://github.com/ChrisChross/streamlit-agraph),
[websocket-client](https://github.com/websocket-client/websocket-client), and
[wordcloud](https://github.com/amueller/word_cloud).

One metadata caveat is recorded explicitly: `streamlit-agraph==0.0.45` reports
`License: UNKNOWN` in its package metadata, but the installed distribution's
`LICENSE` file and the upstream repository `LICENSE` are the standard MIT text.
That package-level file evidence is the basis for the MIT row below; it does not
turn the package into repository-vendored material.

| License evidence | Exact lock entries (`name==version`) |
| --- | --- |
| MIT | `anyio==4.14.2`, `attrs==26.1.0`, `blinker==1.9.0`, `charset-normalizer==3.4.9`, `fonttools==4.63.0`, `h11==0.16.0`, `httptools==0.8.0`, `jsonschema==4.26.0`, `jsonschema-specifications==2025.9.1`, `narwhals==2.24.0`, `pyparsing==3.3.2`, `referencing==0.37.0`, `rpds-py==2026.6.3`, `six==1.17.0`, `streamlit-agraph==0.0.45`, `toml==0.10.2`, `urllib3==2.7.0`, `wordcloud==1.9.6` |
| BSD-3-Clause | `altair==6.2.2`, `click==8.4.2`, `colorama==0.4.6`, `contourpy==1.3.3`, `cycler==0.12.1`, `gitdb==4.0.12`, `gitpython==3.1.57`, `idna==3.18`, `itsdangerous==2.2.0`, `jinja2==3.1.6`, `kiwisolver==1.5.0`, `markupsafe==3.0.3`, `networkx==3.6.1`, `pandas==3.0.5`, `protobuf==7.35.1`, `rdflib==7.6.0`, `smmap==5.0.3`, `starlette==1.3.1`, `uvicorn==0.52.1`, `websockets==16.1.1` |
| Apache-2.0 | `pyarrow==24.0.0`, `pydeck==0.9.3`, `python-multipart==0.0.32`, `requests==2.34.2`, `streamlit==1.60.0`, `tenacity==9.1.4`, `tzdata==2026.3`, `watchdog==6.0.0`, `websocket-client==1.9.0` |
| MPL-2.0 (Mozilla CA bundle) | `certifi==2026.7.22` |
| Matplotlib license; package carries separately licensed font/test material | `matplotlib==3.11.1` |
| BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | `numpy==2.5.1` |
| Apache-2.0 OR BSD-2-Clause | `packaging==26.2` |
| MIT-CMU | `pillow==12.3.0` |
| Apache-2.0 OR BSD-3-Clause | `python-dateutil==2.9.0.post0` |
| PSF-2.0 | `typing_extensions==4.16.0` |

This repository only declares and resolves those packages. `setup.bat` installs
them into a local `.venv`; no third-party source, wheel, binary, font, or
license text is copied into the Git source tree. Some installed distributions
carry their own component notices (notably Matplotlib, NumPy, PyArrow, Requests,
and the `streamlit-agraph` frontend); those obligations travel with the
distribution if it is redistributed. An optional archive that bundles
dependencies must preserve each package's license and notice files and is
separately owned by the archive gate. They do not require a repository-level
notice for the source-only model.

### Tracked assets, examples, and fixtures

The reviewed tracked tree contains Python, Markdown, batch files, JSON, and text;
it contains no tracked image, font, binary, or vendored dependency files. The
content classifications are:

- `dummy_data/dummy_*.txt` and `tests/fixtures/release/*.json` are synthetic
  examples/compatibility fixtures and follow the repository MIT policy.
- No `workflows/*.json` files are tracked in the current tree; the tracked
  `workflows/README.md` is only a directory description. Any local or untracked
  workflow JSON is outside this audit. Future workflow sample inclusion belongs
  to the public-tree provenance review, and this audit makes no assertion about who
  owns the rights to such files.
- Documentation is intentionally text-only; no documentation image or external
  artwork is shipped by this source tree.
- User Projects, external images, Global Libraries, local settings, generated
  output, and the untracked working-tree data are not release content and remain
  under the public-tree exposure audit. Historical FANBOX tooling and manifests remain
  historical strategy material, not a new distribution grant.

### Sample/demo-content rule

For public-tree and bootstrap enforcement: PromptGraph-authored source code, docs, synthetic
examples, and synthetic fixtures are MIT unless a file says otherwise. Third-party
content keeps its own license and required attribution; it may enter the public
tree only when compatible provenance is recorded. User-provided or externally
derived content with no such provenance must not enter the public release tree.
This rule applies to prompt samples, metadata, workflow examples, fixtures,
snippets, templates, and any future bundled assets.

### Notice-file conclusion and downstream boundaries

No `NOTICE` or `THIRD_PARTY_NOTICES.md` is required for the approved source-only
distribution model because the repository does not redistribute the locked
packages or other third-party material. The package-level license/notice files
remain authoritative when dependencies are installed separately. If the release
model changes to bundle dependencies, fonts, images, or other third-party files,
the bundle must be re-audited and carry the required notices before publication.

The license and attribution gate owns the license, dependency, and sample-content
rule. The public-tree exposure gate owns the exact file tree and exclusion
decisions. The clean-repository bootstrap gate owns provenance mapping. The
release-candidate QA gate owns human validation, and the archive gate owns any
optional bundled archive.

## Public-tree provenance

The exposure audit produces a reviewed file inventory and deterministic content
hashes, plus explicit exclusions and intentional transformations. The bootstrap
record must contain:

```text
Product: PromptGraph Pro
Version: 1.0.0
Reviewed source candidate: <full 40-character SHA>
Public bootstrap commit: <full 40-character SHA>
Public release candidate: <full 40-character SHA>
Release tag (if used): v1.0.0
Inventory/hash evidence: <reviewed record>
Intentional differences: <reviewed record>
Runtime lock: requirements.txt
Runtime lock SHA-256: <canonical LF-normalized checksum>
Supported environment: docs/supported-environment.md
Release notes: docs/releases/1.0.0.md
Human QA evidence: <release-candidate QA record>
```

The current runtime-lock baseline digest is
`EA7628D4C4059FAB5D9ADE168B2A567E68035721B8692B22F3638A69ED769C66`.
The bootstrap and QA records recalculate it from the exact selected trees.

### Public source-tree selection audit

The reviewed candidate contains 209 Git-tracked files. Release engineering
selects 169 files for the public source tree and records the other 40 in
excluded categories. The selected categories are runtime/source (36),
setup/runtime contract (6), user/release documentation (8), contributor
architecture (15), and tests and synthetic fixtures (104). The private
release-engineering manifest classifies every tracked path individually;
adding a tracked file without adding a classification makes the export fail
closed before bootstrap.

Export and inventory are reproducible from one exact reviewed candidate commit.
Release engineering runs the private-side exporter and records a UTF-8
inventory with stable path order, file sizes, SHA-256 values, and the candidate
commit. The exporter accepts only regular Git blobs with supported modes,
rejects symlinks, submodules, `.git` paths, unsafe paths, and unsupported modes,
and refuses non-empty destinations. The resulting bytes and inventory are then
used by the clean-repository bootstrap gate; the exporter implementation and
manifest remain release-engineering tooling rather than public source files.

The selected tree excludes internal issue/backlog notes, development policy and
devlogs, research/future/roadmap planning, the future app-refactor plan,
superseded pixivFANBOX documentation/manifest/builder, and tests coupled to
those private or obsolete contracts. It includes current runtime architecture,
user guidance, contributor architecture notes, product regression tests, and
synthetic fixtures. No `.git` directory, untracked working-tree file, user
Project, Global Module Library, generated/source image, external workflow JSON,
or release artifact is an export input. The current workflow boundary remains
exactly `workflows/README.md`; future workflow samples require a separate
provenance decision before inclusion, with no user-ownership assumption.

The exposure review found no high-confidence private key, GitHub token, cloud
credential, bearer token, or private repository URL in selected content.
Documented `%USERPROFILE%` examples, `localhost` examples, and deliberately
synthetic path strings in regression fixtures are intentional false positives,
not machine-specific data. Historical Git objects, commits, branches, tags,
reflogs, remotes, review history, and unreachable objects are never export
inputs; the bootstrap gate creates a new clean history from the approved bytes.

## Release notes and operational guidance

[`CHANGELOG.md`](../CHANGELOG.md) is the compact chronological release index.
[`docs/releases/1.0.0.md`](releases/1.0.0.md) is the detailed release-note
source. [`docs/user-guide.md`](user-guide.md) is the operational product guide.
[`docs/backup-upgrade-rollback.md`](backup-upgrade-rollback.md) defines backup,
separate-directory upgrade, rollback, and recovery. These documents freeze as
part of the exact public candidate before final QA.

Any tracked public-candidate change after release-candidate QA invalidates
affected QA evidence. Select a new public candidate and repeat every affected
check. A
publication date is added only after publication and must not be backfilled into
the frozen candidate before tagging.

## Mandatory source/public-tree QA

The release-candidate QA gate obtains the exact clean public candidate and
follows only its public README and User Guide. On supported Windows it creates
the local environment
from scratch with `setup.bat`, launches with `run.bat`, and reviews first-run
comprehension, supported browsers/DPI/scrolling, primary workflows, backup and
recovery, disposable ComfyUI generation, prompt/image alignment, and absence of
accidental private files or local paths.

Source/public-tree QA is mandatory. It remains sufficient when no convenience
archive is selected.

## Optional archive path

The former pixivFANBOX-specific deterministic builder and verifier remain valid
historical infrastructure. They are not the current publication authority. The
archive gate decides whether a neutral successor is required.

If an archive is selected, it must be built from the exact public candidate,
carry verified provenance and runtime-lock identity, pass checksum and
standalone verification, and be tested through extraction, setup, and launch.
The published bytes must be byte-identical to the archive that passed the
release-candidate QA gate. A GitHub Release may be a natural channel, but neither it nor an archive
is promised by this contract.

## Required release sequence

1. Complete the current-user documentation cleanup and OSS strategy reset.
2. Complete the license and attribution gate, including the audit recorded above.
3. Complete the public-tree exposure gate.
4. Complete the archive gate if the release model selects a convenience archive.
5. Bootstrap the clean public repository and record both sides of the provenance
   mapping.
6. Run the release-candidate QA gate against the exact public candidate; also
   run the exact-archive path only if an archive is selected.
7. Record the go/no-go decision with the release owner.
8. Publish the approved public repository state.
9. Create annotated `v1.0.0` on the canonical public release commit.
10. Optionally publish the byte-identical QA-passed deterministic archive
    through the separately approved channel.

The sequence ends with publication of the approved public state, followed by
the optional annotated tag and archive channel. This contract does not by
itself authorize a hosting, tag, archive, or other publication action.
