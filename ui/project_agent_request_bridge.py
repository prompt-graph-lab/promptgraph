"""Synchronous host-side request/reply boundary for PromptGraph agent tools.

This owner captures a request-scoped Project snapshot only when the existing
MCP adapter asks for one. It does not provide a transport or retain state
between calls.
"""

from math import isfinite

from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from core.project import Project
from ui.project_capture_safety import (
    CapturedProject,
    ProjectCaptureResult,
    capture_active_project,
    is_capture_current,
)


BRIDGE_CONTRACT_VERSION = "promptgraph.app-agent-request-bridge.v1"

_MAX_REQUEST_ID_LENGTH = 128
_MAX_TOOL_NAME_LENGTH = 128
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 20_000
_MAX_JSON_STRING_CHARS = 500_000

_CAPTURE_FAILURE_REASONS = frozenset({
    "missing_project",
    "invalid_project",
    "run_not_current",
    "overlapping_reruns_enabled",
    "capture_mode_unavailable",
    "capture_mode_changed",
    "project_changed",
    "capture_failed",
    "capture_unavailable",
})


class _CaptureProviderUnavailable(Exception):
    """Internal signal; the adapter deliberately receives no host detail."""


def _is_bounded_plain_json_value(value):
    """Check untrusted request JSON within the bridge's input budget."""

    remaining_nodes = _MAX_JSON_NODES
    total_string_chars = 0
    ancestors = set()

    def visit(item, depth):
        nonlocal remaining_nodes, total_string_chars
        if depth > _MAX_JSON_DEPTH:
            return False
        remaining_nodes -= 1
        if remaining_nodes < 0:
            return False

        item_type = type(item)
        if item_type is type(None) or item_type is bool:
            return True
        if item_type is int:
            return item.bit_length() <= 4096
        if item_type is float:
            return isfinite(item)
        if item_type is str:
            total_string_chars += len(item)
            return total_string_chars <= _MAX_JSON_STRING_CHARS

        if item_type is dict:
            identity = id(item)
            if identity in ancestors:
                return False
            ancestors.add(identity)
            try:
                for key, child in item.items():
                    if type(key) is not str:
                        return False
                    total_string_chars += len(key)
                    if total_string_chars > _MAX_JSON_STRING_CHARS:
                        return False
                    if not visit(child, depth + 1):
                        return False
                return True
            finally:
                ancestors.remove(identity)

        if item_type is list:
            identity = id(item)
            if identity in ancestors:
                return False
            ancestors.add(identity)
            try:
                return all(visit(child, depth + 1) for child in item)
            finally:
                ancestors.remove(identity)

        return False

    try:
        return visit(value, 0)
    except Exception:
        # Exact built-in containers and scalar types should not raise here, but
        # this boundary must still fail closed without surfacing host details.
        return False


def _is_plain_json_result(value):
    """Check adapter output shape without adding a bridge payload budget.

    The existing adapter/facade own output bounds. This boundary only ensures
    their returned value can cross the JSON bridge as finite built-in data.
    An iterative walk avoids imposing a separate recursion-depth contract.
    """

    active_containers = set()
    pending = [(value, False)]
    try:
        while pending:
            item, leaving = pending.pop()
            item_type = type(item)

            if leaving:
                active_containers.remove(id(item))
                continue

            if (item_type is type(None) or item_type is bool
                    or item_type is int or item_type is str):
                continue
            if item_type is float:
                if not isfinite(item):
                    return False
                continue

            if item_type is dict:
                identity = id(item)
                if identity in active_containers:
                    return False
                active_containers.add(identity)
                pending.append((item, True))
                for key, child in item.items():
                    if type(key) is not str:
                        return False
                    pending.append((child, False))
                continue

            if item_type is list:
                identity = id(item)
                if identity in active_containers:
                    return False
                active_containers.add(identity)
                pending.append((item, True))
                pending.extend((child, False) for child in item)
                continue

            return False
    except Exception:
        # Adapter output is expected to use exact built-in containers, but the
        # host boundary still fails closed if that contract is ever violated.
        return False
    return True


def _parse_request(request):
    if type(request) is not dict:
        return None, None, "invalid_envelope"
    if len(request) != 3:
        return None, None, "invalid_envelope"

    try:
        keys = list(request.keys())
    except Exception:
        return None, None, "invalid_envelope"
    if any(type(key) is not str for key in keys):
        return None, None, "invalid_envelope"
    if len(keys) != 3 or set(keys) != {"request_id", "tool", "arguments"}:
        return None, None, "invalid_envelope"

    request_id_value = request.get("request_id")
    if (type(request_id_value) is not str
            or not request_id_value
            or len(request_id_value) > _MAX_REQUEST_ID_LENGTH):
        return None, None, "invalid_request_id"

    tool = request.get("tool")
    if type(tool) is not str or len(tool) > _MAX_TOOL_NAME_LENGTH:
        return None, request_id_value, "invalid_tool"

    arguments = request.get("arguments")
    if type(arguments) is not dict:
        return None, request_id_value, "invalid_arguments"
    if not _is_bounded_plain_json_value(arguments):
        return None, request_id_value, "invalid_json_arguments"

    return (tool, arguments), request_id_value, ""


def _completed_reply(request_id, result):
    return {
        "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
        "request_id": request_id,
        "status": "completed",
        "result": result,
    }


def _rejected_reply(request_id, reason, diagnostic_code):
    return {
        "bridge_contract_version": BRIDGE_CONTRACT_VERSION,
        "request_id": request_id,
        "status": "rejected",
        "reason": reason,
        "diagnostics": [{"code": diagnostic_code}],
    }


class _RequestCaptureProvider:
    """Lazy one-capture cache whose lifetime is one dispatch call."""

    def __init__(self, session_state, run_token):
        self._session_state = session_state
        self._run_token = run_token
        self._attempted = False
        self._capture = None
        self._failure_reason = None

    def __call__(self):
        if not self._attempted:
            self._attempted = True
            try:
                result = capture_active_project(self._session_state, self._run_token)
            except Exception:
                self._failure_reason = "capture_unavailable"
            else:
                if type(result) is not ProjectCaptureResult:
                    self._failure_reason = "capture_unavailable"
                elif not result.ok:
                    reason = result.reason
                    self._failure_reason = (
                        reason if type(reason) is str and reason in _CAPTURE_FAILURE_REASONS
                        else "capture_unavailable"
                    )
                elif (type(result.capture) is CapturedProject
                      and type(result.capture.project) is Project):
                    self._capture = result.capture
                else:
                    self._failure_reason = "capture_unavailable"

        if self._capture is None:
            raise _CaptureProviderUnavailable()
        return self._capture.project

    @property
    def capture(self):
        return self._capture

    @property
    def failure_reason(self):
        return self._failure_reason

    def clear(self):
        """Drop all request-local references after the reply is decided."""
        self._session_state = None
        self._run_token = None
        self._capture = None
        self._failure_reason = None
        self._attempted = False


def dispatch_project_agent_request(session_state, run_token, request):
    """Dispatch one bounded request against a fresh optional Project snapshot.

    Adapter and facade results are returned unchanged when JSON-safe. Host
    capture/dispatch failures use a separate bounded bridge reply envelope.
    """

    parsed, request_id, invalid_reason = _parse_request(request)
    if invalid_reason:
        return _rejected_reply(request_id, "invalid_request", invalid_reason)

    tool, arguments = parsed
    provider = _RequestCaptureProvider(session_state, run_token)
    try:
        try:
            adapter = PromptGraphMCPAdapter(provider)
            result = adapter.call_tool(tool, arguments)
        except Exception:
            return _rejected_reply(request_id, "adapter_dispatch_failed",
                                   "adapter_dispatch_failed")

        if provider.failure_reason is not None:
            return _rejected_reply(request_id, "project_capture_failed",
                                   provider.failure_reason)

        capture = provider.capture
        if capture is not None:
            try:
                current = is_capture_current(session_state, capture, run_token)
            except Exception:
                current = False
            if not current:
                return _rejected_reply(request_id, "project_capture_invalidated",
                                       "capture_no_longer_current")

        if not _is_plain_json_result(result):
            return _rejected_reply(request_id, "invalid_adapter_result",
                                   "adapter_result_not_json")

        return _completed_reply(request_id, result)
    finally:
        provider.clear()
