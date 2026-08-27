"""Verify that installed runtime distributions exactly match the release lock.

The verifier uses only the Python standard library.  It reports package names
and versions, but never the lock path or user-specific filesystem details.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from importlib import metadata
import json
from pathlib import Path
import re
from typing import Mapping, Sequence


BOOTSTRAP_DISTRIBUTIONS = frozenset({"pip"})
_EXACT_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;]+)$"
)


def normalize_distribution_name(name: str) -> str:
    """Return the normalized distribution key used for exact comparisons."""

    return re.sub(r"[-_.]+", "-", name).casefold()


@dataclass(frozen=True)
class VersionMismatch:
    name: str
    expected: str
    installed: str


@dataclass(frozen=True)
class RuntimeLockVerification:
    """Stable exact-lock verification result."""

    exact: bool
    expected_count: int
    installed_runtime_count: int
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    version_mismatches: tuple[VersionMismatch, ...]
    lock_errors: tuple[str, ...]
    bootstrap_exclusions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_exact_lock(text: str) -> tuple[dict[str, str], tuple[str, ...]]:
    """Parse a comments-and-pins lock, failing closed on ambiguous entries."""

    expected: dict[str, str] = {}
    errors: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _EXACT_REQUIREMENT.fullmatch(line)
        if match is None:
            errors.append(f"line {line_number}: not an exact package pin")
            continue
        name = normalize_distribution_name(match.group("name"))
        if name in BOOTSTRAP_DISTRIBUTIONS:
            errors.append(f"line {line_number}: bootstrap package is not runtime")
            continue
        if name in expected:
            errors.append(f"line {line_number}: duplicate package {name}")
            continue
        expected[name] = match.group("version")
    if not expected:
        errors.append("lock has no runtime packages")
    return expected, tuple(errors)


def installed_distributions() -> dict[str, str]:
    """Read installed distribution metadata without importing runtime packages."""

    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            continue
        name = normalize_distribution_name(raw_name)
        installed[name] = distribution.version
    return installed


def evaluate_exact_lock(
    expected: Mapping[str, str],
    installed: Mapping[str, str],
    *,
    lock_errors: Sequence[str] = (),
) -> RuntimeLockVerification:
    """Compare injected expected and installed package maps exactly."""

    expected_normalized = {
        normalize_distribution_name(name): version
        for name, version in expected.items()
    }
    installed_normalized = {
        normalize_distribution_name(name): version
        for name, version in installed.items()
        if normalize_distribution_name(name) not in BOOTSTRAP_DISTRIBUTIONS
    }
    missing = tuple(sorted(set(expected_normalized) - set(installed_normalized)))
    unexpected = tuple(sorted(set(installed_normalized) - set(expected_normalized)))
    version_mismatches = tuple(
        VersionMismatch(
            name=name,
            expected=expected_normalized[name],
            installed=installed_normalized[name],
        )
        for name in sorted(set(expected_normalized) & set(installed_normalized))
        if expected_normalized[name] != installed_normalized[name]
    )
    normalized_errors = tuple(lock_errors)
    exact = not (missing or unexpected or version_mismatches or normalized_errors)
    return RuntimeLockVerification(
        exact=exact,
        expected_count=len(expected_normalized),
        installed_runtime_count=len(installed_normalized),
        missing=missing,
        unexpected=unexpected,
        version_mismatches=version_mismatches,
        lock_errors=normalized_errors,
        bootstrap_exclusions=tuple(sorted(BOOTSTRAP_DISTRIBUTIONS)),
    )


def verify_runtime_lock(lock_path: Path) -> RuntimeLockVerification:
    """Load one lock and compare it with the active interpreter environment."""

    try:
        text = lock_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return evaluate_exact_lock(
            {},
            installed_distributions(),
            lock_errors=("lock file could not be read",),
        )
    expected, errors = parse_exact_lock(text)
    return evaluate_exact_lock(
        expected,
        installed_distributions(),
        lock_errors=errors,
    )


def _names(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "none"


def _render_human(result: RuntimeLockVerification) -> str:
    mismatches = ", ".join(
        f"{item.name} (expected {item.expected}, installed {item.installed})"
        for item in result.version_mismatches
    )
    lines = [
        f"Exact runtime lock: {'PASS' if result.exact else 'FAIL'}",
        f"Expected runtime packages: {result.expected_count}",
        f"Installed runtime packages: {result.installed_runtime_count}",
        f"Missing packages: {_names(result.missing)}",
        f"Unexpected packages: {_names(result.unexpected)}",
        f"Version mismatches: {mismatches or 'none'}",
        f"Lock errors: {_names(result.lock_errors)}",
        f"Bootstrap exclusions: {_names(result.bootstrap_exclusions)}",
    ]
    if not result.exact:
        lines.append(
            "Rename or delete .venv manually, then run setup.bat again."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the PromptGraph Pro exact runtime lock."
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=Path("requirements.txt"),
        help="exact runtime lock to verify",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="emit structured JSON only",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="return a nonzero exit code when the environment is not exact",
    )
    args = parser.parse_args(argv)
    result = verify_runtime_lock(args.requirements)
    if args.as_json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_human(result))
    return 1 if args.check and not result.exact else 0


if __name__ == "__main__":
    raise SystemExit(main())
