"""PromptGraph Pro release identity and optional checkout diagnostics."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence


PRODUCT_NAME = "PromptGraph Pro"
__version__ = "1.0.0"
VERSION = __version__
TAG_PREFIX = "v"
BUILD_SHA_ENV = "PROMPTGRAPH_BUILD_SHA"
GIT_TIMEOUT_SECONDS = 2.0
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

_FULL_GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_GitRunner = Callable[..., Any]


@dataclass(frozen=True)
class ReleaseIdentity:
    """Support-facing product and optional checkout identity."""

    product: str
    version: str
    tag: str
    commit_sha: str
    commit_short: str
    commit_source: str
    dirty: bool | None

    def as_dict(self) -> dict[str, object]:
        """Return the stable structured-output representation."""

        return asdict(self)


def release_tag() -> str:
    """Return the proposed tag derived from the authoritative version."""

    return f"{TAG_PREFIX}{__version__}"


def _normalize_full_sha(value: object) -> str:
    text = str(value or "").strip()
    return text.lower() if _FULL_GIT_SHA.fullmatch(text) else ""


def _run_git(
    arguments: Sequence[str],
    *,
    repository_root: Path,
    runner: _GitRunner | None = None,
) -> Any | None:
    """Run one bounded, read-only Git diagnostic when checkout data exists."""

    if not (repository_root / ".git").exists():
        return None
    command_runner = subprocess.run if runner is None else runner
    try:
        return command_runner(
            ["git", *arguments],
            cwd=str(repository_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_git_commit_sha(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    runner: _GitRunner | None = None,
) -> str:
    """Return the checkout HEAD SHA, or an empty string when unavailable."""

    completed = _run_git(
        ["rev-parse", "HEAD"],
        repository_root=repository_root,
        runner=runner,
    )
    if completed is None or completed.returncode != 0:
        return ""
    return _normalize_full_sha(completed.stdout)


def resolve_commit_sha(
    *,
    environ: Mapping[str, str] | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    runner: _GitRunner | None = None,
) -> tuple[str, str]:
    """Resolve commit identity from the build environment, then local Git."""

    environment = os.environ if environ is None else environ
    environment_sha = _normalize_full_sha(environment.get(BUILD_SHA_ENV, ""))
    if environment_sha:
        return environment_sha, "environment"

    git_sha = resolve_git_commit_sha(
        repository_root=repository_root,
        runner=runner,
    )
    if git_sha:
        return git_sha, "git"
    return "", "unavailable"


def resolve_dirty_state(
    *,
    repository_root: Path = REPOSITORY_ROOT,
    runner: _GitRunner | None = None,
) -> bool | None:
    """Report tracked or staged changes without enumerating untracked files."""

    commands = (
        ["diff", "--quiet", "--ignore-submodules", "--"],
        ["diff", "--cached", "--quiet", "--ignore-submodules", "--"],
    )
    for arguments in commands:
        completed = _run_git(
            arguments,
            repository_root=repository_root,
            runner=runner,
        )
        if completed is None or completed.returncode not in (0, 1):
            return None
        if completed.returncode == 1:
            return True
    return False


def get_release_identity(
    *,
    environ: Mapping[str, str] | None = None,
    repository_root: Path = REPOSITORY_ROOT,
    runner: _GitRunner | None = None,
) -> ReleaseIdentity:
    """Build the product identity without network or repository mutation."""

    commit_sha, commit_source = resolve_commit_sha(
        environ=environ,
        repository_root=repository_root,
        runner=runner,
    )
    return ReleaseIdentity(
        product=PRODUCT_NAME,
        version=__version__,
        tag=release_tag(),
        commit_sha=commit_sha,
        commit_short=commit_sha[:12],
        commit_source=commit_source,
        dirty=resolve_dirty_state(
            repository_root=repository_root,
            runner=runner,
        ),
    )


def _working_tree_label(dirty: bool | None) -> str:
    if dirty is True:
        return "modified"
    if dirty is False:
        return "clean"
    return "unavailable"


def _render_human(identity: ReleaseIdentity) -> str:
    commit = identity.commit_sha or "unavailable"
    return "\n".join(
        (
            f"Product: {identity.product}",
            f"Version: {identity.version}",
            f"Tag: {identity.tag}",
            f"Commit: {commit}",
            f"Working tree: {_working_tree_label(identity.dirty)}",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print human-readable or JSON release identity diagnostics."""

    parser = argparse.ArgumentParser(description="Show PromptGraph Pro release identity.")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit structured JSON only",
    )
    args = parser.parse_args(argv)
    identity = get_release_identity()
    if args.as_json:
        print(json.dumps(identity.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_human(identity))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
