"""PromptGraph Pro supported-runtime diagnostics.

This module uses only the Python standard library and is safe to import from
unsupported environments.  Enforcement is opt-in through the ``--check`` CLI.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import platform
import re
import struct
import sys
from typing import Sequence

from core.version import PRODUCT_NAME, __version__


SUPPORTED_PYTHON = (3, 14)
MINIMUM_WINDOWS_11_BUILD = 22000
SUPPORTED_ARCHITECTURES = frozenset({"amd64", "x86_64"})


@dataclass(frozen=True)
class RuntimeProbe:
    """Raw platform facts, separated for deterministic contract tests."""

    operating_system: str
    windows_build: int | None
    architecture: str
    pointer_bits: int
    python_implementation: str
    python_version: str
    python_version_info: tuple[int, int, int]


@dataclass(frozen=True)
class RuntimeEnvironment:
    """Stable support-diagnostic representation."""

    product: str
    product_version: str
    supported: bool
    operating_system: str
    windows_build: int | None
    architecture: str
    pointer_bits: int
    python_implementation: str
    python_version: str
    python_supported: bool
    implementation_supported: bool
    architecture_supported: bool
    os_supported: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_windows_build(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(?:^|\.)(\d+)$", text)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _current_windows_build(operating_system: str) -> int | None:
    if operating_system.casefold() != "windows":
        return None
    get_windows_version = getattr(sys, "getwindowsversion", None)
    if callable(get_windows_version):
        try:
            return _parse_windows_build(get_windows_version().build)
        except (AttributeError, OSError):
            pass
    return _parse_windows_build(platform.version())


def probe_runtime_environment() -> RuntimeProbe:
    """Read current platform facts without network or filesystem mutation."""

    operating_system = platform.system() or "Unknown"
    version_info = tuple(int(value) for value in sys.version_info[:3])
    return RuntimeProbe(
        operating_system=operating_system,
        windows_build=_current_windows_build(operating_system),
        architecture=platform.machine() or "Unknown",
        pointer_bits=struct.calcsize("P") * 8,
        python_implementation=platform.python_implementation() or "Unknown",
        python_version=platform.python_version() or "Unknown",
        python_version_info=version_info,
    )


def evaluate_runtime_environment(probe: RuntimeProbe) -> RuntimeEnvironment:
    """Evaluate one injected or current probe against the Pro v1 contract."""

    implementation_supported = probe.python_implementation.casefold() == "cpython"
    python_supported = probe.python_version_info[:2] == SUPPORTED_PYTHON
    architecture_supported = (
        probe.architecture.casefold() in SUPPORTED_ARCHITECTURES
        and probe.pointer_bits == 64
    )
    os_supported = (
        probe.operating_system.casefold() == "windows"
        and probe.windows_build is not None
        and probe.windows_build >= MINIMUM_WINDOWS_11_BUILD
    )
    supported = all(
        (
            implementation_supported,
            python_supported,
            architecture_supported,
            os_supported,
        )
    )
    return RuntimeEnvironment(
        product=PRODUCT_NAME,
        product_version=__version__,
        supported=supported,
        operating_system=probe.operating_system,
        windows_build=probe.windows_build,
        architecture=probe.architecture,
        pointer_bits=probe.pointer_bits,
        python_implementation=probe.python_implementation,
        python_version=probe.python_version,
        python_supported=python_supported,
        implementation_supported=implementation_supported,
        architecture_supported=architecture_supported,
        os_supported=os_supported,
    )


def get_runtime_environment() -> RuntimeEnvironment:
    return evaluate_runtime_environment(probe_runtime_environment())


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _render_human(environment: RuntimeEnvironment) -> str:
    build = (
        str(environment.windows_build)
        if environment.windows_build is not None
        else "unavailable"
    )
    return "\n".join(
        (
            f"Product: {environment.product} {environment.product_version}",
            f"Supported: {_yes_no(environment.supported)}",
            f"Operating system: {environment.operating_system}",
            f"Windows build: {build}",
            f"Architecture: {environment.architecture} ({environment.pointer_bits}-bit)",
            f"Python: {environment.python_implementation} {environment.python_version}",
            f"OS supported: {_yes_no(environment.os_supported)}",
            f"Architecture supported: {_yes_no(environment.architecture_supported)}",
            f"Python supported: {_yes_no(environment.python_supported)}",
            f"Implementation supported: {_yes_no(environment.implementation_supported)}",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show the PromptGraph Pro supported-runtime diagnostic."
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
        help="return a nonzero exit code when the runtime is unsupported",
    )
    args = parser.parse_args(argv)
    environment = get_runtime_environment()
    if args.as_json:
        print(json.dumps(environment.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(_render_human(environment))
    return 1 if args.check and not environment.supported else 0


if __name__ == "__main__":
    raise SystemExit(main())
