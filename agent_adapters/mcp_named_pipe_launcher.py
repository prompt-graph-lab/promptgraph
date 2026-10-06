"""Stable stdio MCP launcher for one explicitly armed PromptGraph session.

The launcher resolves only the protected per-logon rendezvous. It does not
discover a current Project or browser session and never writes diagnostics to
stdout, which remains owned by MCP stdio traffic.
"""

import sys

import anyio

from agent_adapters.mcp_named_pipe_gateway import (
    NamedPipeGatewayStartupError,
    serve_stdio_over_named_pipe,
)
from ui.project_agent_named_pipe import (
    LocalLauncherRendezvous,
    read_local_launcher_rendezvous,
)


_RENDEZVOUS_FAILURES = frozenset({
    "unsupported_platform",
    "security_unavailable",
    "rendezvous_unavailable",
    "rendezvous_owned",
    "rendezvous_not_ready",
    "invalid_rendezvous",
    "rendezvous_cleanup_failed",
    "expired_rendezvous",
    "stale_rendezvous",
    "already_owned",
})
_GATEWAY_FAILURES = frozenset({
    "invalid_descriptor",
    "pairing_unavailable",
    "session_unavailable",
    "transport_error",
    "request_failed",
})


def _bounded_reason(reason, allowed, fallback):
    return reason if type(reason) is str and reason in allowed else fallback


def main(arguments=None):
    """Run the fixed launcher command without a transient descriptor argument."""

    args = list(sys.argv[1:] if arguments is None else arguments)
    if args:
        print("PromptGraph MCP launcher: unexpected_arguments", file=sys.stderr)
        return 2

    try:
        rendezvous = read_local_launcher_rendezvous()
    except Exception:
        rendezvous = None
    if (type(rendezvous) is not LocalLauncherRendezvous
            or rendezvous.status != "ready"):
        reason = _bounded_reason(
            rendezvous.status if type(rendezvous) is LocalLauncherRendezvous else None,
            _RENDEZVOUS_FAILURES,
            "rendezvous_unavailable",
        )
        print(
            f"PromptGraph MCP launcher: {reason}",
            file=sys.stderr,
        )
        return 1

    try:
        anyio.run(
            serve_stdio_over_named_pipe,
            rendezvous.descriptor_file_path,
        )
    except NamedPipeGatewayStartupError as error:
        reason = _bounded_reason(
            error.reason,
            _GATEWAY_FAILURES,
            "gateway_failed",
        )
        print(
            f"PromptGraph MCP launcher: {reason}",
            file=sys.stderr,
        )
        return 1
    except Exception:
        print("PromptGraph MCP launcher: gateway_failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
