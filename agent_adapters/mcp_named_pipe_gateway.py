"""Forward one stdio MCP connection through one authenticated local route.

The gateway owns only the paired transport client and delegates every tool
call through the existing app-side mailbox and request bridge. It never loads
a Project or accesses Streamlit/session state.
"""

import math
import threading
import time
import uuid

from agent_adapters.mcp_sdk_binding import MCPToolCaller
from agent_adapters.mcp_stdio_runner import serve_stdio
from ui.project_agent_named_pipe import (
    LocalNamedPipeClient,
    LocalPipeError,
    PipeConnectionResult,
)
from ui.project_agent_session_mailbox import DEFAULT_REQUEST_TIMEOUT_SECONDS


GATEWAY_CONTRACT_VERSION = "promptgraph.mcp-stdio-named-pipe-gateway.v1"
_RESULT_WAIT_MARGIN_SECONDS = 5.0
_DEFAULT_POLL_INTERVAL_SECONDS = 0.05

_BRIDGE_REASONS = frozenset({
    "invalid_request",
    "project_capture_failed",
    "adapter_dispatch_failed",
    "project_capture_invalidated",
    "invalid_adapter_result",
})


def _failure(reason: str) -> dict:
    return {
        "gateway_contract_version": GATEWAY_CONTRACT_VERSION,
        "ok": False,
        "reason": reason,
        "diagnostics": [{"code": reason}],
    }


def _wire_failure(status) -> str:
    if type(status) is not str:
        return "transport_error"
    return {
        "busy": "request_busy",
        "expired": "request_expired",
        "stale_target": "stale_target",
        "expired_pairing": "pairing_unavailable",
        "invalid_pairing": "pairing_unavailable",
        "invalid_descriptor": "pairing_unavailable",
        "descriptor_unavailable": "pairing_unavailable",
        "wrong_endpoint": "pairing_unavailable",
        "already_claimed": "pairing_unavailable",
        "session_unavailable": "session_unavailable",
        "session_closed": "session_unavailable",
        "pipe_disconnected": "transport_error",
        "pipe_unavailable": "transport_error",
        "pipe_timeout": "transport_error",
        "security_unavailable": "transport_error",
        "unsupported_platform": "transport_error",
        "transport_error": "transport_error",
        "invalid_request": "request_rejected",
        "invalid_response": "invalid_reply",
        "internal_error": "request_failed",
        "idle": "invalid_reply",
    }.get(status, "request_failed")


class NamedPipeMCPToolCaller:
    """Synchronous tool caller bound to exactly one paired Named Pipe route."""

    def __init__(
        self,
        pipe_client,
        *,
        result_wait_seconds=None,
        poll_interval_seconds=_DEFAULT_POLL_INTERVAL_SECONDS,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        if not callable(getattr(pipe_client, "current_target_epoch", None)):
            raise TypeError("An authenticated paired-route client is required.")
        if not callable(getattr(pipe_client, "submit", None)):
            raise TypeError("An authenticated paired-route client is required.")
        if not callable(getattr(pipe_client, "consume_reply", None)):
            raise TypeError("An authenticated paired-route client is required.")
        if not callable(getattr(pipe_client, "release", None)):
            raise TypeError("An authenticated paired-route client is required.")
        if result_wait_seconds is None:
            result_wait_seconds = (
                DEFAULT_REQUEST_TIMEOUT_SECONDS + _RESULT_WAIT_MARGIN_SECONDS
            )
        if (type(result_wait_seconds) not in (int, float)
                or not math.isfinite(result_wait_seconds)
                or result_wait_seconds <= 0):
            raise ValueError("Invalid result wait duration.")
        if (type(poll_interval_seconds) not in (int, float)
                or not math.isfinite(poll_interval_seconds)
                or poll_interval_seconds <= 0):
            raise ValueError("Invalid polling interval.")
        if not callable(clock) or not callable(sleep):
            raise ValueError("Invalid gateway clock.")

        self._pipe_client = pipe_client
        self._result_wait_seconds = float(result_wait_seconds)
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._closed = False

    def __repr__(self):
        return "NamedPipeMCPToolCaller(<one paired session>)"

    def call_tool(self, name, arguments):
        """Forward one tool call without retrying or changing its target."""

        with self._lock:
            if self._closed:
                return _failure("gateway_unavailable")

            try:
                target = self._pipe_client.current_target_epoch()
                if type(target) is not dict or target.get("status") != "ok":
                    status = target.get("status") if type(target) is dict else None
                    return _failure(_wire_failure(status))
                target_epoch = target.get("target_epoch")
                if type(target_epoch) is not str or not target_epoch:
                    return _failure("invalid_reply")

                request_id = uuid.uuid4().hex
                request_arguments = {} if arguments is None else arguments
                submitted = self._pipe_client.submit(
                    target_epoch,
                    {
                        "request_id": request_id,
                        "tool": name,
                        "arguments": request_arguments,
                    },
                )
                if type(submitted) is not dict or submitted.get("status") != "accepted":
                    status = submitted.get("status") if type(submitted) is dict else None
                    return _failure(_wire_failure(status))

                deadline = self._clock() + self._result_wait_seconds
                while True:
                    outcome = self._pipe_client.consume_reply(target_epoch)
                    if type(outcome) is not dict:
                        self._disconnect_after_uncertain_request()
                        return _failure("invalid_reply")

                    status = outcome.get("status")
                    if status == "busy":
                        remaining = deadline - self._clock()
                        if remaining <= 0:
                            # A submitted request may still own the capacity-one
                            # mailbox. Closing signals a real disconnect so the
                            # existing endpoint caretaker drains this generation.
                            self._disconnect_after_uncertain_request()
                            return _failure("request_timeout")
                        self._sleep(min(self._poll_interval_seconds, remaining))
                        continue

                    if status == "completed":
                        reply = outcome.get("reply")
                        if (type(reply) is not dict
                                or reply.get("request_id") != request_id):
                            return _failure("invalid_reply")
                        if reply.get("status") == "completed":
                            if "result" not in reply:
                                return _failure("invalid_reply")
                            # Preserve the app-side adapter payload unchanged.
                            return reply["result"]
                        if reply.get("status") == "rejected":
                            reason = reply.get("reason")
                            if type(reason) is str and reason in _BRIDGE_REASONS:
                                return _failure(reason)
                            return _failure("bridge_rejected")
                        return _failure("invalid_reply")

                    return _failure(_wire_failure(status))
            except LocalPipeError as error:
                self._disconnect_after_uncertain_request()
                return _failure(_wire_failure(error.reason))
            except Exception:
                self._disconnect_after_uncertain_request()
                return _failure("transport_error")

    def close(self):
        """Release this pairing when idle; disconnect safely if still busy."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                released = self._pipe_client.release()
            except Exception:
                self._close_pipe_client()
                return
            if type(released) is not dict or released.get("status") != "released":
                # The route's existing release rule rejects in-flight work.
                # A real disconnect leaves only the #123 caretaker path.
                self._close_pipe_client()
                return
            # LocalNamedPipeClient.release() also closes on success; keep this
            # explicit for any future paired-route client implementing the seam.
            self._close_pipe_client()

    def _disconnect_after_uncertain_request(self):
        if self._closed:
            return
        self._closed = True
        self._close_pipe_client()

    def _close_pipe_client(self):
        try:
            self._pipe_client.close()
        except Exception:
            pass


class NamedPipeGatewayStartupError(RuntimeError):
    """Bounded gateway setup error; never contains the descriptor path."""

    def __init__(self, reason):
        safe_reason = reason if type(reason) is str else "pairing_unavailable"
        self.reason = safe_reason
        super().__init__(safe_reason)


async def serve_stdio_over_named_pipe(descriptor_file_path: str) -> None:
    """Connect one protected descriptor, serve stdio, then release that route."""

    if type(descriptor_file_path) is not str or not descriptor_file_path:
        raise NamedPipeGatewayStartupError("invalid_descriptor")
    connection = LocalNamedPipeClient.connect_from_descriptor_file(
        descriptor_file_path,
    )
    if (type(connection) is not PipeConnectionResult
            or connection.status != "paired"
            or type(connection.client) is not LocalNamedPipeClient):
        status = (
            connection.status
            if type(connection) is PipeConnectionResult
            else "pairing_unavailable"
        )
        raise NamedPipeGatewayStartupError(_wire_failure(status))

    caller = NamedPipeMCPToolCaller(connection.client)
    try:
        await serve_stdio(tool_caller=caller)
    finally:
        caller.close()
