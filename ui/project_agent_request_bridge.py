"""Synchronous host-side request/reply boundary for PromptGraph agent tools.

This owner captures a request-scoped Project snapshot only when the existing
MCP adapter asks for one. It does not provide a transport or retain state
between calls.
"""

from math import isfinite

from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from core.project import Project
from core.candidate_observation_handles import project_identity
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


def _dispatch_scene_module_swap_review_request(
        request_id, arguments, provider, review_custodian,
        pairing_generation, target_epoch, session_state, run_token):
    """Recompute and prepare one explicitly requested host review proposal."""

    from agent_adapters import mcp_adapter
    from core import agent_facade
    from ui.agent_scene_module_swap_approval_lifecycle import (
        AgentSceneModuleSwapApprovalCustodian,
        DuplicateReviewReply,
        PreparedReviewReply,
    )

    normalized = mcp_adapter.validate_scene_module_swap_review_request_arguments(
        arguments,
    )
    if normalized is None:
        return _completed_reply(
            request_id,
            mcp_adapter.scene_module_swap_review_failure("invalid_arguments"),
        )

    if (type(review_custodian) is not AgentSceneModuleSwapApprovalCustodian
            or type(pairing_generation) is not int or pairing_generation <= 0
            or type(target_epoch) is not str or not target_epoch):
        return _completed_reply(
            request_id,
            mcp_adapter.scene_module_swap_review_failure("host_review_unavailable"),
        )

    intent = dict(normalized)
    decision = review_custodian.check_request(
        request_id, pairing_generation, target_epoch, intent,
    )
    if decision.status == "retry_pending":
        if decision.retry_token is None or type(decision.result) is not dict:
            return _completed_reply(
                request_id,
                mcp_adapter.scene_module_swap_review_failure("review_unavailable"),
            )
        return DuplicateReviewReply(
            _completed_reply(request_id, decision.result),
            decision.retry_token,
        )
    if decision.status != "new":
        return _completed_reply(
            request_id,
            mcp_adapter.scene_module_swap_review_failure(decision.status),
        )

    def fail(reason):
        review_custodian.remember_failure(
            request_id,
            pairing_generation,
            target_epoch,
            intent,
            decision.revision,
            reason,
        )
        return _completed_reply(
            request_id,
            mcp_adapter.scene_module_swap_review_failure(reason),
        )

    try:
        project = provider()
    except _CaptureProviderUnavailable:
        return fail("review_unavailable")
    except Exception:
        return fail("review_unavailable")

    capture = provider.capture
    if capture is None or provider.failure_reason is not None:
        return fail("review_unavailable")

    try:
        preview = agent_facade.preview_scene_module_swap(
            project,
            {
                "scene_id": normalized["scene_id"],
                "source_module_name": normalized["source_module_name"],
                "target_module_name": normalized["target_module_name"],
                "match_mode": normalized["match_mode"],
            },
        )
    except Exception:
        return fail("invalid_preview")

    if type(preview) is not dict or preview.get("valid") is not True:
        reason = (
            "target_limit_exceeded"
            if type(preview) is dict and preview.get("reason") == "target_limit_exceeded"
            else "invalid_preview"
        )
        return fail(reason)
    target_count = preview.get("target_count")
    changed_count = preview.get("changed_count")
    if (type(target_count) is not int or target_count < 0
            or target_count > agent_facade.MAX_TARGETS):
        return fail("target_limit_exceeded")
    if type(changed_count) is not int:
        return fail("invalid_preview")
    if changed_count <= 0:
        return fail("no_op_preview")
    if preview.get("plan_id") != normalized["expected_plan_id"]:
        return fail("stale_preview")

    try:
        capture_is_current = is_capture_current(session_state, capture, run_token)
    except Exception:
        capture_is_current = False
    if not capture_is_current:
        return fail("stale_target")

    prepared = review_custodian.prepare(
        request_id,
        pairing_generation,
        target_epoch,
        intent,
        decision.revision,
        preview,
    )
    if prepared.status == "retry_pending":
        if prepared.retry_token is None or type(prepared.result) is not dict:
            return _completed_reply(
                request_id,
                mcp_adapter.scene_module_swap_review_failure("review_unavailable"),
            )
        return DuplicateReviewReply(
            _completed_reply(request_id, prepared.result),
            prepared.retry_token,
        )
    if prepared.status != "prepared" or prepared.token is None:
        return _completed_reply(
            request_id,
            mcp_adapter.scene_module_swap_review_failure(prepared.status),
        )
    return PreparedReviewReply(
        _completed_reply(request_id, prepared.result),
        prepared.token,
    )


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


def _dispatch_generation_review(request_id, arguments, provider, custodian, pairing,
                                epoch, state, token, session_identity, host):
    from agent_adapters.mcp_adapter import validate_generation_review_arguments, generation_review_failure
    from core.agent_facade import preview_generation, generation_preview_project_state
    from ui.agent_generation_review_custody import AgentGenerationReviewCustodian
    from ui.agent_scene_module_swap_approval_lifecycle import PreparedReviewReply, DuplicateReviewReply
    args = validate_generation_review_arguments(arguments)
    def reject(reason):
        return _completed_reply(request_id, generation_review_failure(reason))
    if args is None:
        return reject("invalid_arguments")
    if (type(custodian) is not AgentGenerationReviewCustodian or type(pairing) is not int
            or pairing <= 0 or type(epoch) is not str or not epoch or session_identity is None):
        return reject("host_review_unavailable")
    decision = custodian.check_request(request_id, pairing, epoch, args)
    if decision.status not in {"new", "retry_pending"}:
        return reject(decision.status)
    def fail(reason):
        custodian.remember_failure(request_id, pairing, epoch, args, decision.revision, reason)
        return reject(reason)
    try:
        project = provider()
        capture = provider.capture
        source = capture._source_project_ref()
        binding = [project_identity(source), session_identity, state.get("current_project_path", ""), pairing, epoch]
        preview = preview_generation(project, args["scene_id"], run_count=args["run_count"],
                                     host_context_provider=host, observation_binding=binding)
        if preview.get("valid") is not True or preview.get("request_count", 0) <= 0:
            if decision.retry_token is not None:
                custodian.mark_pending_stale(decision.retry_token.proposal_id)
            return fail("invalid_preview")
        if preview.get("plan_id") != args["expected_plan_id"]:
            if decision.retry_token is not None:
                custodian.mark_pending_stale(decision.retry_token.proposal_id)
            return fail("stale_preview")
        if (not is_capture_current(state, capture, token)
                or generation_preview_project_state(project) != generation_preview_project_state(source)):
            return fail("stale_target")
        if decision.status == "retry_pending":
            return DuplicateReviewReply(_completed_reply(request_id, decision.result), decision.retry_token)
        prepared = custodian.prepare(request_id, pairing, epoch, args, decision.revision, preview)
    except Exception:
        return fail("review_unavailable")
    if prepared.status == "retry_pending":
        return DuplicateReviewReply(_completed_reply(request_id, prepared.result), prepared.retry_token)
    if prepared.status != "prepared":
        return reject(prepared.status)
    return PreparedReviewReply(_completed_reply(request_id, prepared.result), prepared.token)


def dispatch_project_agent_request(
        session_state, run_token, request, *, review_custodian=None,
        pairing_generation=None, target_epoch=None, candidate_session_identity=None,
        generation_context_provider=None, generation_review_custodian=None):
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
        if tool == "promptgraph_request_generation_review":
            return _dispatch_generation_review(request_id, arguments, provider, generation_review_custodian,
                pairing_generation, target_epoch, session_state, run_token, candidate_session_identity,
                generation_context_provider)
        if tool == "promptgraph_request_scene_module_swap_review":
            return _dispatch_scene_module_swap_review_request(
                request_id,
                arguments,
                provider,
                review_custodian,
                pairing_generation,
                target_epoch,
                session_state,
                run_token,
            )
        try:
            def candidate_binding():
                # Called only after schema validation and successful capture.
                source = provider.capture._source_project_ref()
                if source is None:
                    raise _CaptureProviderUnavailable()
                return [project_identity(source),
                        candidate_session_identity if candidate_session_identity is not None else id(session_state),
                        session_state.get("current_project_path", ""),
                        pairing_generation, target_epoch]

            if tool == "promptgraph_preview_generation":
                adapter = PromptGraphMCPAdapter(provider, candidate_binding_provider=candidate_binding,
                                               generation_context_provider=generation_context_provider)
            else:
                adapter = (PromptGraphMCPAdapter(provider, candidate_binding_provider=candidate_binding)
                           if tool in ("promptgraph_list_candidates", "promptgraph_get_candidate")
                           else PromptGraphMCPAdapter(provider))
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
            if tool == "promptgraph_preview_generation":
                from core.agent_facade import generation_preview_project_state
                try:
                    content_current = (generation_preview_project_state(capture.project)
                                       == generation_preview_project_state(capture._source_project_ref()))
                except Exception:
                    content_current = False
                if not content_current:
                    return _rejected_reply(request_id, "project_capture_invalidated",
                                           "capture_no_longer_current")

        if not _is_plain_json_result(result):
            return _rejected_reply(request_id, "invalid_adapter_result",
                                   "adapter_result_not_json")

        return _completed_reply(request_id, result)
    finally:
        provider.clear()
