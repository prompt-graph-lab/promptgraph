# PromptGraph Pro 1.0.0 Supported Environment

This document defines the supported Windows clean-source runtime for PromptGraph
Pro `1.0.0` and applies to any optional convenience archive. A release tag, if
used, identifies the exact reviewed bytes; this contract applies to the clean
source distribution and any optional archive built from those bytes.

## Supported platform

PromptGraph Pro 1.0.0 is supported on:

- Windows 11, 64-bit;
- AMD64 / x86-64 architecture with 64-bit CPython;
- CPython `>=3.14,<3.15` (Python 3.14.x);
- current stable Microsoft Edge or Google Chrome, with JavaScript and local
  storage enabled;
- local access to Streamlit's loopback URL;
- an official clean source checkout or release package, using
  that application directory's project-local `.venv`.

The validation baseline is Windows 11 Pro x64 build `26200`. Build 26200 is
validation evidence, not a minimum or only supported Windows 11 build. Release-
candidate QA includes a second independent Windows 11 environment.

Python 3.14.4 and 3.14.6 were observed during release audits. The supported
contract is the Python 3.14 minor line, not either individual patch. An existing
`.venv` keeps its selected interpreter even if the global Windows Python
launcher later selects a newer 3.14 patch.

The following environments are outside the Pro 1.0.0 support guarantee:

- Windows 10, Windows ARM64, and 32-bit Windows;
- macOS, Linux, and WSL;
- Python 3.13, Python 3.15, PyPy, and 32-bit CPython;
- browsers other than stable Edge and Chrome.

They may work, but they are unsupported and unverified for this release. The
application does not deliberately block them; `run.bat` only fails closed when
the documented runtime contract is not met.

## Validated lock baseline

The committed runtime lock was generated in a clean environment rather than
from the developer environment.

| Evidence | Value |
|---|---|
| Windows | Windows 11 Pro x64, build 26200 |
| Architecture | AMD64, 64-bit |
| Lock-generation Python | CPython 3.14.4 |
| Bootstrap tooling | pip 26.1.1 |
| Runtime package count | 54 |
| `requirements.txt` canonical LF-normalized SHA-256 | `EA7628D4C4059FAB5D9ADE168B2A567E68035721B8692B22F3638A69ED769C66` |
| Clean venv creation | 6.497 seconds |
| pip bootstrap | 5.360 seconds |
| Wheel-only runtime install | 57.238 seconds |
| `pip check` | pass, 1.323 seconds |
| Install artifacts | 54 wheels, 0 source distributions |

`requirements.in` records the six direct dependency decisions.
`requirements.txt` is the complete exact runtime lock, including transitives.
Every runtime requirement uses `==`; pip, setuptools, wheel, pytest, and audit
tools are not runtime-lock entries.

The lock digest is calculated after converting CRLF or CR line endings to LF
and encoding the result as UTF-8. This keeps the dependency identity stable
when a Windows checkout or `git archive` materializes text with CRLF endings.

## Setup and launch

Run explicit setup once and whenever the committed lock changes:

```bat
setup.bat
```

Setup creates or reuses only the project-local `.venv`. It selects CPython 3.14
x64, validates Windows 11 and architecture, installs exactly `pip==26.1.1`,
installs the complete lock using wheels only, runs `pip check`, and then
fail-closed verifies that the installed runtime distribution set exactly
matches `requirements.txt`. `pip` is the sole bootstrap-tooling exclusion from
that comparison. Setup never installs Python, prunes packages, or deletes an
existing environment.

If an existing `.venv` has the wrong Python minor, implementation, operating
system, or architecture, setup stops with instructions to rename or delete it
manually. The same fail-closed guidance applies when a locked package is
missing, has the wrong version, or when any lock-external runtime package is
installed. Deleting `.venv` is the clean reinstall procedure; setup does not
automatically remove unexpected packages. Recreating `.venv` is also required
when intentionally switching to a newer Python 3.14 patch.

Start the application without changing the environment:

```bat
run.bat
```

`run.bat` requires `.venv\Scripts\python.exe`, runs the lightweight runtime
contract check, and starts Streamlit. It never invokes pip and never falls back
to global Python. If `.venv` is missing, it exits nonzero with `Run setup.bat
first` guidance.

Equivalent manual commands are:

```bat
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install pip==26.1.1
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m core.runtime_lock --requirements requirements.txt --check
.venv\Scripts\python.exe -m streamlit run app.py
```

Support diagnostics are available without third-party imports:

```bat
.venv\Scripts\python.exe -m core.version --json
.venv\Scripts\python.exe -m core.runtime_environment
.venv\Scripts\python.exe -m core.runtime_environment --check
.venv\Scripts\python.exe -m core.runtime_environment --json
.venv\Scripts\python.exe -m core.runtime_lock --requirements requirements.txt --check
.venv\Scripts\python.exe -m core.runtime_lock --requirements requirements.txt --json
```

The runtime-environment helper reports product version, OS/build, architecture,
Python implementation/version, and the individual support verdicts. The lock
helper reports only package names, versions, counts, and the exact-match verdict.
Neither helper prints the user name, home path, or unrelated environment
variables.

## Browser boundary

Streamlit serves a loopback URL on the local machine. Use current stable Edge
or Chrome with JavaScript and local storage enabled and permit local access to
that URL. PromptGraph does not install, update, select, or otherwise manage the
browser. Browser user-agent blocking is not used.

## ComfyUI boundary

ComfyUI is optional for Project editing, Gallery review, Module/Attribute work,
image import, save/reopen, and Final Export. Generation requires an explicitly
configured ComfyUI-compatible HTTP endpoint and an executable API workflow.

The current integration expects these behaviors:

- `POST /prompt` accepts `{"prompt": <workflow>, "client_id": <uuid>}` and
  returns a `prompt_id`;
- `ws://<endpoint>/ws?clientId=<uuid>` reports execution start, progress,
  completion, and execution errors;
- `GET /history/<prompt_id>` returns the target prompt history and output image
  records; PromptGraph polls up to eight times at 0.75-second intervals after
  execution;
- `GET /view?filename=...&subfolder=...&type=...` returns each generated image;
- executable workflow JSON uses the ComfyUI API-style node map and compatible
  prompt/output-node semantics.

PromptGraph does not install or launch ComfyUI and does not contact an endpoint
passively. Network requests occur only after an explicit generation action.
No ComfyUI release number is claimed. Final endpoint evidence belongs to the
release-candidate QA gate and must use a disposable test endpoint, never a
remote production queue.

## Contained Streamlit compatibility

The runtime lock pins Streamlit exactly to `1.60.0`. All PromptGraph
`use_container_width=True` calls were migrated to `width="stretch"` while
preserving their layout owners and widget semantics.

Two executable-JavaScript uses require the Streamlit component iframe: global
keyboard shortcuts reach the parent Streamlit document, and the focused prompt
copy action calls the Clipboard API. `st.html` is not behaviorally equivalent
for that iframe contract. Both uses route through one compatibility wrapper,
which is the sole `components.html` owner. Upgrading Streamlit outside the
committed lock is unsupported for Pro 1.0.0.

## Updating dependencies

Do not manually upgrade individual packages inside the release `.venv`.
Dependency changes require all of the following:

1. update the six direct decisions in `requirements.in`;
2. create a fresh temporary CPython 3.14 x64 environment;
3. install `pip==26.1.1`;
4. install `requirements.in` with `--only-binary=:all:` and run `pip check`;
5. normalize the sorted `pip freeze` into `requirements.txt` and update its
   header;
6. verify two independent clean installs have identical normalized freezes;
7. run the focused runtime-contract tests and complete test suite;
8. update this evidence and the release documentation.

If any required dependency lacks a compatible wheel, lock regeneration stops;
a source compilation toolchain is not part of the supported Pro 1.0.0 contract.
