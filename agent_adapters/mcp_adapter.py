"""SDK-independent MCP-facing catalog and call adapter for the Agent Facade.

This module describes logical tool registrations; it does not implement MCP's
wire protocol, own Project state, or expose mutation Apply.
"""

from copy import deepcopy
from typing import Callable

from core import agent_facade


ADAPTER_CONTRACT_VERSION = "promptgraph.mcp-adapter.v1"


_EMPTY_OBJECT = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

_TOOL_CATALOG = (
    {
        "name": "promptgraph_capabilities",
        "description": "List PromptGraph observations, search Illustrations, and create a Batch Replace Preview. Apply is not exposed.",
        "inputSchema": _EMPTY_OBJECT,
        "effect": "read_only",
    },
    {
        "name": "promptgraph_project_summary",
        "description": "Summarize the host-supplied active PromptGraph Project.",
        "inputSchema": _EMPTY_OBJECT,
        "effect": "read_only",
    },
    {
        "name": "promptgraph_list_scenes",
        "description": "List active separator-backed Scenes and their Illustration IDs.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            "additionalProperties": False,
        },
        "effect": "read_only",
    },
    {
        "name": "promptgraph_list_illustrations",
        "description": "List active Illustrations, optionally within one Scene.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
        "effect": "read_only",
    },
    {
        "name": "promptgraph_search_illustrations",
        "description": "Count and return a bounded list of active Illustration prompt matches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_text": {"type": "string", "minLength": 1,
                               "maxLength": agent_facade.MAX_REQUEST_TEXT},
                "match_mode": {"type": "string", "enum": list(agent_facade.SEARCH_MODES),
                               "default": "exact_token"},
                "scene_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": agent_facade.MAX_ITEMS},
            },
            "required": ["query_text"],
            "additionalProperties": False,
        },
        "effect": "read_only",
    },
    {
        "name": "promptgraph_get_illustration",
        "description": "Read one Illustration by its stable ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "illustration_id": {"type": "string", "minLength": 1, "maxLength": 200},
            },
            "required": ["illustration_id"],
            "additionalProperties": False,
        },
        "effect": "read_only",
    },
    {
        "name": "promptgraph_preview_batch_replace",
        "description": "Create a reviewed Batch Replace Preview for explicit Illustration IDs. This tool does not Apply the plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "illustration_ids": {
                    "type": "array", "minItems": 1, "maxItems": 1000,
                    "items": {"type": "string", "minLength": 1, "maxLength": 200},
                },
                "find_text": {"type": "string", "minLength": 1, "maxLength": 10000},
                "replace_text": {"type": "string", "minLength": 1, "maxLength": 10000},
                "match_mode": {"type": "string", "enum": list(agent_facade.REPLACE_MODES)},
                "preserve_weights": {"type": "boolean"},
            },
            "required": ["illustration_ids", "find_text", "replace_text"],
            "additionalProperties": False,
        },
        "effect": "reviewed_preview",
    },
    {
        "name": "promptgraph_preview_scene_module_swap",
        "description": "Create a bounded reviewed Module Swap Preview for one explicit Scene. This tool does not Apply the plan.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "source_module_name": {"type": "string", "minLength": 1, "maxLength": 200},
                "target_module_name": {"type": "string", "minLength": 1, "maxLength": 200},
                "match_mode": {
                    "type": "string",
                    "enum": list(agent_facade.SCENE_MODULE_SWAP_MODES),
                    "default": "strict",
                },
            },
            "required": ["scene_id", "source_module_name", "target_module_name"],
            "additionalProperties": False,
        },
        "effect": "reviewed_preview",
    },
    {
        "name": "promptgraph_request_scene_module_swap_review",
        "description": (
            "Request host review of a freshly recomputed single-Scene Module Swap Preview. "
            "A successful response only queues the exact proposal for human review; it does not approve or Apply it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string", "minLength": 1, "maxLength": 200},
                "source_module_name": {"type": "string", "minLength": 1, "maxLength": 200},
                "target_module_name": {"type": "string", "minLength": 1, "maxLength": 200},
                "expected_plan_id": {
                    "type": "string",
                    "minLength": 64,
                    "maxLength": 64,
                    "pattern": "^[0-9a-f]{64}$",
                },
                "match_mode": {
                    "type": "string",
                    "enum": list(agent_facade.SCENE_MODULE_SWAP_MODES),
                    "default": "strict",
                },
            },
            "required": [
                "scene_id", "source_module_name", "target_module_name", "expected_plan_id",
            ],
            "additionalProperties": False,
        },
        "effect": "host_review_request",
    },
)

_CAPABILITIES_TOOL = "promptgraph_capabilities"
_SUMMARY_TOOL = "promptgraph_project_summary"
_SCENES_TOOL = "promptgraph_list_scenes"
_ILLUSTRATIONS_TOOL = "promptgraph_list_illustrations"
_SEARCH_ILLUSTRATIONS_TOOL = "promptgraph_search_illustrations"
_ILLUSTRATION_TOOL = "promptgraph_get_illustration"
_PREVIEW_TOOL = "promptgraph_preview_batch_replace"
_SCENE_MODULE_SWAP_PREVIEW_TOOL = "promptgraph_preview_scene_module_swap"
_SCENE_MODULE_SWAP_REVIEW_REQUEST_TOOL = "promptgraph_request_scene_module_swap_review"
_PREVIEW_REQUIRED_ARGUMENTS = ("illustration_ids", "find_text", "replace_text")
_PREVIEW_OPTIONAL_ARGUMENTS = ("match_mode", "preserve_weights")
_SEARCH_OPTIONAL_ARGUMENTS = ("match_mode", "scene_id", "limit")
_SCENE_MODULE_SWAP_REQUIRED_ARGUMENTS = (
    "scene_id", "source_module_name", "target_module_name",
)
_SCENE_MODULE_SWAP_OPTIONAL_ARGUMENTS = ("match_mode",)
_SCENE_MODULE_SWAP_REVIEW_REQUIRED_ARGUMENTS = (
    "scene_id", "source_module_name", "target_module_name", "expected_plan_id",
)
_SCENE_MODULE_SWAP_REVIEW_OPTIONAL_ARGUMENTS = ("match_mode",)

SCENE_MODULE_SWAP_REVIEW_FAILURE_REASONS = frozenset({
    "invalid_arguments",
    "host_review_unavailable",
    "stale_preview",
    "invalid_preview",
    "no_op_preview",
    "target_limit_exceeded",
    "review_already_pending",
    "request_id_conflict",
    "replay_not_accepted",
    "proposal_too_large",
    "proposal_expired",
    "stale_target",
    "session_closed",
    "review_unavailable",
    "proposal_cancelled",
})


def _error(reason: str):
    return {
        "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
        "ok": False,
        "reason": reason,
        "diagnostics": [{"code": reason}],
    }


def _object_arguments(arguments, *, required=(), optional=()):
    if type(arguments) is not dict:
        return None
    # Reject non-JSON keys before any set/dict membership operation can invoke
    # a caller-supplied key's hashing or equality hooks.
    keys = list(arguments.keys())
    if any(type(key) is not str for key in keys):
        return None
    if any(key not in keys for key in required):
        return None
    if any(key not in required and key not in optional for key in keys):
        return None
    return arguments


def _arguments_have_types(arguments, expected):
    return all(type(arguments[key]) is expected[key] for key in expected if key in arguments)


def _preview_transport_arguments(arguments):
    """Validate only the Preview tool's immediate JSON shape before host access."""
    args = _object_arguments(arguments, required=_PREVIEW_REQUIRED_ARGUMENTS,
                             optional=_PREVIEW_OPTIONAL_ARGUMENTS)
    if args is None or not _arguments_have_types(args, {
            "illustration_ids": list, "find_text": str, "replace_text": str,
            "match_mode": str, "preserve_weights": bool}):
        return None
    # The outer container is now a built-in list, so this exact-type scan cannot
    # invoke coercion/stringification hooks on non-JSON Illustration IDs.
    if any(type(item) is not str for item in args["illustration_ids"]):
        return None
    return args


def _search_transport_arguments(arguments):
    """Validate the bounded search schema before resolving the host Project."""
    args = _object_arguments(arguments, required=("query_text",),
                             optional=_SEARCH_OPTIONAL_ARGUMENTS)
    if args is None or not _arguments_have_types(args, {
            "query_text": str, "match_mode": str, "scene_id": str, "limit": int}):
        return None
    query = args["query_text"]
    if not 1 <= len(query) <= agent_facade.MAX_REQUEST_TEXT:
        return None
    try:
        query.encode("utf-8")
    except UnicodeError:
        return None
    if "match_mode" in args and args["match_mode"] not in agent_facade.SEARCH_MODES:
        return None
    if "scene_id" in args and not 1 <= len(args["scene_id"]) <= 200:
        return None
    if "limit" in args and not 1 <= args["limit"] <= agent_facade.MAX_ITEMS:
        return None
    return args


def _scene_module_swap_transport_arguments(arguments):
    """Validate the fixed scene-swap wire shape before resolving the host Project."""
    args = _object_arguments(
        arguments,
        required=_SCENE_MODULE_SWAP_REQUIRED_ARGUMENTS,
        optional=_SCENE_MODULE_SWAP_OPTIONAL_ARGUMENTS,
    )
    if args is None or not _arguments_have_types(args, {
            "scene_id": str, "source_module_name": str,
            "target_module_name": str, "match_mode": str}):
        return None
    for field_name in _SCENE_MODULE_SWAP_REQUIRED_ARGUMENTS:
        value = args[field_name]
        if not 1 <= len(value) <= 200:
            return None
        try:
            value.encode("utf-8")
        except UnicodeError:
            return None
    if "match_mode" in args and args["match_mode"] not in agent_facade.SCENE_MODULE_SWAP_MODES:
        return None
    return args


def validate_scene_module_swap_review_request_arguments(arguments):
    """Validate the review-request wire shape without resolving a Project.

    This is intentionally a transport-level check. The facade remains the
    owner of Module Swap domain semantics; the trusted host bridge calls this
    helper before capture and then computes the Preview itself.
    """

    args = _object_arguments(
        arguments,
        required=_SCENE_MODULE_SWAP_REVIEW_REQUIRED_ARGUMENTS,
        optional=_SCENE_MODULE_SWAP_REVIEW_OPTIONAL_ARGUMENTS,
    )
    if args is None or not _arguments_have_types(args, {
            "scene_id": str,
            "source_module_name": str,
            "target_module_name": str,
            "expected_plan_id": str,
            "match_mode": str,
    }):
        return None
    for field_name in ("scene_id", "source_module_name", "target_module_name"):
        value = args[field_name]
        if not 1 <= len(value) <= 200:
            return None
        try:
            value.encode("utf-8")
        except UnicodeError:
            return None
    expected_plan_id = args["expected_plan_id"]
    if (len(expected_plan_id) != 64
            or any(char not in "0123456789abcdef" for char in expected_plan_id)):
        return None
    match_mode = args.get("match_mode", "strict")
    if match_mode not in agent_facade.SCENE_MODULE_SWAP_MODES:
        return None
    normalized = {
        "scene_id": args["scene_id"],
        "source_module_name": args["source_module_name"],
        "target_module_name": args["target_module_name"],
        "expected_plan_id": expected_plan_id,
        "match_mode": match_mode,
    }
    return normalized


def scene_module_swap_review_failure(reason):
    """Return a bounded adapter-shaped failure for the host review route."""

    if reason not in SCENE_MODULE_SWAP_REVIEW_FAILURE_REASONS:
        reason = "review_unavailable"
    return _error(reason)


def get_tool_catalog():
    """Return a fresh deterministic logical catalog for later SDK registration."""
    return deepcopy(list(_TOOL_CATALOG))


def get_adapter_capabilities():
    """Map facade capabilities to the smaller agent-callable MCP surface."""
    facade_result = agent_facade.discover_capabilities()
    mutation_capabilities = {
        item["operation"]: item for item in facade_result["capabilities"]["mutations"]
    }
    batch = mutation_capabilities[agent_facade.OPERATION]
    scene_swap = mutation_capabilities[agent_facade.SCENE_MODULE_SWAP_OPERATION]
    search = facade_result["capabilities"]["illustration_search"]
    return {
        "adapter_contract_version": ADAPTER_CONTRACT_VERSION,
        "facade_contract_version": facade_result["contract_version"],
        "tools": [
            {"name": item["name"], "effect": item["effect"]}
            for item in _TOOL_CATALOG
        ],
        "batch_replace_preview_modes": list(batch["modes"]),
        "batch_replace_requires_explicit_illustration_ids": True,
        "scene_module_swap_preview_modes": list(scene_swap["modes"]),
        "scene_module_swap_requires_explicit_scene_id": scene_swap["requires_explicit_scene_id"],
        "scene_module_swap_requires_explicit_source_module_name": (
            scene_swap["requires_explicit_source_module_name"]
        ),
        "scene_module_swap_requires_explicit_target_module_name": (
            scene_swap["requires_explicit_target_module_name"]
        ),
        "scene_module_swap_requires_explicit_module_names": (
            scene_swap["requires_explicit_source_module_name"]
            and scene_swap["requires_explicit_target_module_name"]
        ),
        "scene_module_swap_requires_reviewed_preview_before_host_apply": (
            scene_swap["requires_reviewed_preview_before_host_apply"]
        ),
        "scene_module_swap_review_request_requires_human_review": True,
        "scene_module_swap_review_request_requires_expected_plan_id": True,
        "illustration_search_modes": list(search["modes"]),
        "illustration_search_max_results": search["max_results"],
        "illustration_search_query_text_chars": search["query_text_chars"],
        "agent_callable_apply": False,
    }


class PromptGraphMCPAdapter:
    """Expose a fixed tool catalog against a host-supplied Project provider.

    The provider is called for each Project-dependent tool call. The adapter
    never caches the Project, Preview, approval state, or result.
    """

    def __init__(self, project_provider: Callable[[], object] | None):
        self._project_provider = project_provider

    def call_tool(self, name, arguments):
        """Invoke one catalog tool and return only ordinary JSON data."""
        if type(name) is not str:
            return _error("unknown_tool")
        if name not in {item["name"] for item in _TOOL_CATALOG}:
            return _error("unknown_tool")
        if name == _CAPABILITIES_TOOL:
            if _object_arguments(arguments, required=()) is None or arguments:
                return _error("invalid_arguments")
            return get_adapter_capabilities()

        # Validate the fixed transport shape before asking the host for its
        # active Project. Domain-level values and semantics remain facade-owned.
        if name == _SUMMARY_TOOL:
            if _object_arguments(arguments, required=()) is None or arguments:
                return _error("invalid_arguments")
        elif name == _SCENES_TOOL:
            arguments = _object_arguments(arguments, optional=("limit",))
            if arguments is None or not _arguments_have_types(arguments, {"limit": int}):
                return _error("invalid_arguments")
        elif name == _ILLUSTRATIONS_TOOL:
            arguments = _object_arguments(arguments, optional=("scene_id", "limit"))
            if arguments is None or not _arguments_have_types(arguments, {"scene_id": str, "limit": int}):
                return _error("invalid_arguments")
        elif name == _ILLUSTRATION_TOOL:
            arguments = _object_arguments(arguments, required=("illustration_id",))
            if arguments is None or not _arguments_have_types(arguments, {"illustration_id": str}):
                return _error("invalid_arguments")
        elif name == _SEARCH_ILLUSTRATIONS_TOOL:
            arguments = _search_transport_arguments(arguments)
            if arguments is None:
                return _error("invalid_arguments")
        elif name == _PREVIEW_TOOL:
            arguments = _preview_transport_arguments(arguments)
            if arguments is None:
                return _error("invalid_arguments")
        elif name == _SCENE_MODULE_SWAP_PREVIEW_TOOL:
            arguments = _scene_module_swap_transport_arguments(arguments)
            if arguments is None:
                return _error("invalid_arguments")
        elif name == _SCENE_MODULE_SWAP_REVIEW_REQUEST_TOOL:
            arguments = validate_scene_module_swap_review_request_arguments(arguments)
            if arguments is None:
                return _error("invalid_arguments")
            # An adapter call has no trusted session/run/custody context. It
            # must never make a review proposal or ask its Project provider.
            return scene_module_swap_review_failure("host_review_unavailable")

        if self._project_provider is None:
            return _error("missing_project_provider")
        if not callable(self._project_provider):
            return _error("invalid_project_provider")
        try:
            project = self._project_provider()
        except Exception:
            return _error("project_provider_failed")

        try:
            if name == _SUMMARY_TOOL:
                return agent_facade.summarize_project(project)

            if name == _SCENES_TOOL:
                return agent_facade.observe_scenes(project, **arguments)

            if name == _ILLUSTRATIONS_TOOL:
                return agent_facade.list_illustrations(project, **arguments)

            if name == _SEARCH_ILLUSTRATIONS_TOOL:
                return agent_facade.search_illustrations(project, **arguments)

            if name == _ILLUSTRATION_TOOL:
                return agent_facade.get_illustration(project, arguments["illustration_id"])

            if name == _PREVIEW_TOOL:
                # The facade owns the complete JSON/request validation and
                # returns the exact Preview envelope; the adapter only routes it.
                return agent_facade.preview_batch_replace(project, arguments)

            if name == _SCENE_MODULE_SWAP_PREVIEW_TOOL:
                # The facade owns all Module Swap request semantics and returns
                # the exact safe Preview envelope; the adapter only routes it.
                return agent_facade.preview_scene_module_swap(project, arguments)
        except Exception:
            return _error("adapter_call_failed")

        return _error("unknown_tool")
