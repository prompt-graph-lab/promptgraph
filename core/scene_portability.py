"""Read-only source projection for portable, image-less Scene structure."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any

from core.module_container_policy import REFERENCE_ASSETS_FIELD
from core.modules import MODULE_GRAPH_TYPE, MODULE_GRAPH_VERSION
from core.operations import (
    _has_matching_module_close,
    get_module_body,
    normalize_module_library,
    validate_library_module_body,
)
from core.parser import extract_mod_info, parse_prompt
from core.project import Project, PromptLine
from core.route_operations import resolve_route_block


SCENE_PORTABILITY_CONTRACT_VERSION = "promptgraph.scene-portability.v1"
_MAX_DIAGNOSTICS = 16
_MAX_ID_CHARS = 1024
_MAX_NESTING = 128
_MAX_PORTABLE_MODULE_CLOSURE_DEPTH = 20
_MAX_PORTABLE_MODULE_SNAPSHOT_COUNT = 256
_KNOWN_PATH_KEYS = {"path"}
_STRICT_TEXT_KEYS = {"body", "text", "token", "tokens", "core_tokens", "module_name", "name"}
_LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/])|"
    r"(?<![A-Za-z0-9])\\\\[^\\/\s]+[\\/][^\\/\s]+|"
    r"(?<![A-Za-z0-9])/(?!/)(?:[^/\s]+(?:/|$))",
    re.IGNORECASE,
)
_NETWORK_URL_RE = re.compile(r"\b(?:https?|ftp)://[^\s<>\"']+", re.IGNORECASE)
_DROP = object()


@dataclass(frozen=True)
class _ResolverLine:
    """Only the fields read by ``resolve_route_block`` and its counters."""

    id: str
    line_type: str | None
    deleted: bool
    source_index: int
    separator_label: str | None = None
    current_text: str | None = None
    original_file_name: str | None = None
    generated_candidates: tuple[Any, ...] = ()
    gallery_variants: tuple[Any, ...] = ()


class _ProjectionIssue(Exception):
    def __init__(self, code: str):
        self.code = code


def _failure(code: str, separator_id: str | None = None) -> dict[str, Any]:
    diagnostics = [{"code": code}]
    return {
        "contract_version": SCENE_PORTABILITY_CONTRACT_VERSION,
        "valid": False,
        "source_separator_id": separator_id,
        "scene": None,
        "illustrations": [],
        "module_snapshots": [],
        "source_scene_fingerprint": None,
        "blockers": [code][: _MAX_DIAGNOSTICS],
        "diagnostics": diagnostics[:_MAX_DIAGNOSTICS],
    }


def _is_path_key(key: str) -> bool:
    normalized = key.casefold()
    return normalized in _KNOWN_PATH_KEYS or normalized.endswith("_path")


def _contains_local_absolute_path(value: Any, active: set[int] | None = None, depth: int = 0) -> bool:
    if depth > _MAX_NESTING:
        raise _ProjectionIssue("unsupported_module_content")
    if type(value) is str:
        # Network URLs are portable metadata; file:// URLs are intentionally
        # not exempted because they identify local files.
        inspectable = _NETWORK_URL_RE.sub("", value)
        return _LOCAL_PATH_RE.search(inspectable) is not None
    if value is None or type(value) in (bool, int):
        return False
    if type(value) is float:
        if not math.isfinite(value):
            raise _ProjectionIssue("unsupported_module_content")
        return False
    if type(value) not in (dict, list):
        raise _ProjectionIssue("unsupported_module_content")

    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise _ProjectionIssue("unsupported_module_content")
    active.add(identity)
    try:
        if type(value) is dict:
            for key, child in value.items():
                if type(key) is not str:
                    raise _ProjectionIssue("unsupported_module_content")
                if _LOCAL_PATH_RE.search(_NETWORK_URL_RE.sub("", key)):
                    return True
                if key.casefold() == REFERENCE_ASSETS_FIELD:
                    continue
                if _contains_local_absolute_path(child, active, depth + 1):
                    return True
        else:
            for child in value:
                if _contains_local_absolute_path(child, active, depth + 1):
                    return True
    finally:
        active.remove(identity)
    return False


def _portable_copy(
    value: Any,
    *,
    strict_text: bool = False,
    active: set[int] | None = None,
    depth: int = 0,
) -> Any:
    """Copy JSON data while omitting local path metadata and reference assets."""
    if depth > _MAX_NESTING:
        raise _ProjectionIssue("unsupported_module_content")
    if type(value) is str:
        if _contains_local_absolute_path(value):
            if strict_text:
                raise _ProjectionIssue("unsafe_module_metadata")
            return _DROP
        return value
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise _ProjectionIssue("unsupported_module_content")
        return value
    if type(value) not in (dict, list):
        raise _ProjectionIssue("unsupported_module_content")

    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise _ProjectionIssue("unsupported_module_content")
    active.add(identity)
    try:
        if type(value) is dict:
            copied: dict[str, Any] = {}
            for key, child in value.items():
                if type(key) is not str:
                    raise _ProjectionIssue("unsupported_module_content")
                normalized_key = key.casefold()
                if normalized_key == REFERENCE_ASSETS_FIELD or _is_path_key(key):
                    continue
                if _LOCAL_PATH_RE.search(_NETWORK_URL_RE.sub("", key)):
                    continue
                child_is_strict = normalized_key in _STRICT_TEXT_KEYS
                child_is_container = type(child) in (dict, list)
                child_has_path = _contains_local_absolute_path(child)
                if child_has_path and not child_is_container:
                    if child_is_strict:
                        raise _ProjectionIssue("unsafe_module_metadata")
                    # Unknown extension metadata with a local path is omitted;
                    # no path value crosses the boundary.
                    continue
                projected = _portable_copy(
                    child,
                    strict_text=child_is_strict,
                    active=active,
                    depth=depth + 1,
                )
                if child_has_path and projected in ({}, []):
                    continue
                if projected is not _DROP:
                    copied[key] = projected
            return copied

        copied_items = []
        for child in value:
            child_is_container = type(child) in (dict, list)
            if _contains_local_absolute_path(child) and not child_is_container:
                if strict_text:
                    raise _ProjectionIssue("unsafe_module_metadata")
                continue
            projected = _portable_copy(
                child,
                strict_text=strict_text,
                active=active,
                depth=depth + 1,
            )
            if projected is not _DROP:
                copied_items.append(projected)
        return copied_items
    finally:
        active.remove(identity)


def _module_references(text: str, depth: int = 0) -> list[str]:
    """Find library-style references using the current parser/close semantics."""
    if depth > _MAX_NESTING:
        raise _ProjectionIssue("malformed_referenced_module")
    tokens = parse_prompt(text)
    references: list[str] = []
    for index, token in enumerate(tokens):
        info = extract_mod_info(token)
        if info["type"] == "inline":
            references.extend(_module_references(info["content"], depth + 1))
        elif info["type"] == "open" and not _has_matching_module_close(
            tokens, index, info["name"]
        ):
            references.append(info["name"])
    return references


def _validate_raw_module_graph(graph: Any) -> None:
    """Reject graph values that the normalizer would otherwise silently drop."""
    if type(graph) is not dict:
        raise _ProjectionIssue("malformed_referenced_module")
    expected_fields = {
        "id": None,
        "name": None,
        "type": MODULE_GRAPH_TYPE,
        "version": MODULE_GRAPH_VERSION,
    }
    for key, expected in expected_fields.items():
        if key not in graph:
            continue  # normalize_module_graph supplies these defaults.
        value = graph[key]
        if key == "version":
            if type(value) is not int or value != expected:
                raise _ProjectionIssue("malformed_referenced_module")
        elif type(value) is not str or not value.strip() or (expected is not None and value != expected):
            raise _ProjectionIssue("malformed_referenced_module")

    raw_nodes = graph.get("nodes", [])
    if raw_nodes is None:
        raw_nodes = []
    if type(raw_nodes) is not list:
        raise _ProjectionIssue("malformed_referenced_module")
    node_ids: set[str] = set()
    for node in raw_nodes:
        if type(node) is not dict:
            raise _ProjectionIssue("malformed_referenced_module")
        node_id = node.get("id")
        kind = node.get("kind")
        if type(node_id) is not str or not node_id.strip() or node_id in node_ids:
            raise _ProjectionIssue("malformed_referenced_module")
        node_ids.add(node_id)
        if kind == "token":
            if type(node.get("text")) is not str or not node["text"].strip():
                raise _ProjectionIssue("malformed_referenced_module")
        elif kind == "module_ref":
            if any(type(node.get(key)) is not str or not node[key].strip() for key in ("ref", "module_name")):
                raise _ProjectionIssue("malformed_referenced_module")
        else:
            raise _ProjectionIssue("malformed_referenced_module")

    if "edges" in graph and graph["edges"] is not None:
        edges = graph["edges"]
        if type(edges) is not list:
            raise _ProjectionIssue("malformed_referenced_module")
        for edge in edges:
            if type(edge) is not dict:
                raise _ProjectionIssue("malformed_referenced_module")
            if any(type(edge.get(key)) is not str or edge[key] not in node_ids for key in ("source", "target")):
                raise _ProjectionIssue("malformed_referenced_module")
            if "kind" in edge and type(edge["kind"]) is not str:
                raise _ProjectionIssue("malformed_referenced_module")

    for key in ("child_module_refs", "related_module_refs"):
        if key in graph and type(graph[key]) is list and any(
            type(name) is not str for name in graph[key]
        ):
            raise _ProjectionIssue("malformed_referenced_module")


def _portable_module_snapshots(
    root_prompts: list[str], raw_library: Any
) -> list[dict[str, Any]]:
    roots: list[str] = []
    for prompt in root_prompts:
        roots.extend(_module_references(prompt))
    if not roots:
        return []
    if type(raw_library) is not dict or any(type(name) is not str for name in raw_library):
        raise _ProjectionIssue("malformed_module_library")

    snapshots: dict[str, dict[str, Any]] = {}
    discovered: set[str] = set()
    pending: deque[tuple[str, int]] = deque()

    def enqueue(module_name: str, depth: int) -> None:
        if module_name in discovered:
            return
        if depth > _MAX_PORTABLE_MODULE_CLOSURE_DEPTH:
            raise _ProjectionIssue("module_closure_limit_exceeded")
        if len(discovered) >= _MAX_PORTABLE_MODULE_SNAPSHOT_COUNT:
            raise _ProjectionIssue("module_closure_limit_exceeded")
        discovered.add(module_name)
        pending.append((module_name, depth))

    for root in roots:
        enqueue(root, 1)

    # Breadth-first traversal bounds depth while ensuring shared references are
    # first discovered along their shortest path. Recording before children
    # keeps ordinary cycles deterministic and complete.
    while pending:
        module_name, depth = pending.popleft()
        if _LOCAL_PATH_RE.search(_NETWORK_URL_RE.sub("", module_name)):
            raise _ProjectionIssue("unsafe_module_metadata")
        if module_name not in raw_library:
            raise _ProjectionIssue("unresolved_module_reference")

        raw_entry = raw_library[module_name]
        if type(raw_entry) not in (dict, str):
            raise _ProjectionIssue("malformed_referenced_module")
        if type(raw_entry) is dict:
            raw_body = raw_entry.get("body")
            if raw_body is not None and type(raw_body) is not str:
                raise _ProjectionIssue("malformed_referenced_module")
            raw_type = raw_entry.get("type")
            if raw_type is not None and type(raw_type) is not str:
                raise _ProjectionIssue("malformed_referenced_module")
            raw_category = raw_entry.get("category")
            if raw_category is not None and type(raw_category) is not str:
                raise _ProjectionIssue("malformed_referenced_module")

        try:
            entry_copy = _portable_copy(raw_entry, strict_text=type(raw_entry) is str)
        except _ProjectionIssue:
            raise
        if entry_copy is _DROP:
            raise _ProjectionIssue("malformed_referenced_module")
        if type(entry_copy) is dict:
            body = entry_copy.get("body")
            if body is not None and type(body) is not str:
                raise _ProjectionIssue("malformed_referenced_module")
            module_type = entry_copy.get("type")
            if module_type is not None and type(module_type) is not str:
                raise _ProjectionIssue("malformed_referenced_module")
            category = entry_copy.get("category")
            if category is not None and type(category) is not str:
                raise _ProjectionIssue("malformed_referenced_module")
            core_tokens = entry_copy.get("core_tokens")
            if core_tokens is not None and (
                type(core_tokens) is not list or any(type(token) is not str for token in core_tokens)
            ):
                raise _ProjectionIssue("malformed_referenced_module")
            graph = entry_copy.get("graph")
            if graph is not None:
                _validate_raw_module_graph(graph)

        try:
            normalized_library = normalize_module_library({module_name: entry_copy})
            normalized_entry = normalized_library.get(module_name)
            if type(normalized_entry) is not dict:
                raise _ProjectionIssue("malformed_referenced_module")
            effective_body = get_module_body(normalized_library, module_name)
            if type(effective_body) is not str:
                raise _ProjectionIssue("malformed_referenced_module")
            if validate_library_module_body(module_name, effective_body):
                raise _ProjectionIssue("malformed_referenced_module")
            normalized_entry = dict(normalized_entry)
            normalized_entry["body"] = effective_body
            definition = _portable_copy(normalized_entry)
        except _ProjectionIssue:
            raise
        except Exception:
            # Normalization details are internal; keep failures bounded and
            # avoid exposing malformed metadata or exception text.
            raise _ProjectionIssue("malformed_referenced_module") from None

        if type(definition) is not dict:
            raise _ProjectionIssue("malformed_referenced_module")

        # Record before following child references so recursive graphs terminate.
        snapshots[module_name] = {
            "name": module_name,
            "definition": definition,
        }
        for child_name in _module_references(effective_body):
            enqueue(child_name, depth + 1)
    return [snapshots[name] for name in sorted(snapshots)]


def _fingerprint(source_separator_id: str, scene: dict[str, Any], illustrations: list[dict[str, Any]], modules: list[dict[str, Any]]) -> str:
    fingerprint_input = {
        "contract_version": SCENE_PORTABILITY_CONTRACT_VERSION,
        "source_separator_id": source_separator_id,
        "scene": scene,
        "illustrations": illustrations,
        "module_snapshots": modules,
    }
    canonical = json.dumps(
        fingerprint_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def project_scene_portability_payload(project: Project, separator_id: str) -> dict[str, Any]:
    """Project an active separator-owned Scene into portable JSON-only data.

    The operation reads current prompt text and portable Module definitions.
    It does not allocate target IDs, access files, or mutate the Project.
    """
    bounded_id = separator_id if type(separator_id) is str and len(separator_id) <= _MAX_ID_CHARS else None
    if type(project) is not Project:
        return _failure("invalid_project", bounded_id)
    if type(separator_id) is not str or not separator_id or separator_id != separator_id.strip():
        return _failure("invalid_separator_id", bounded_id)
    if len(separator_id) > _MAX_ID_CHARS:
        return _failure("invalid_separator_id")
    if _LOCAL_PATH_RE.search(_NETWORK_URL_RE.sub("", separator_id)):
        return _failure("unsafe_source_identity")
    if type(project.prompt_lines) is not list:
        return _failure("invalid_project_lines", separator_id)

    resolver_lines: list[_ResolverLine] = []
    source_lines: list[PromptLine] = []
    source_id_counts: dict[str, int] = {}
    for index, line in enumerate(project.prompt_lines):
        if type(line) is not PromptLine:
            return _failure("invalid_project_lines", separator_id)
        values = vars(line)
        line_id = values.get("id")
        line_type = values.get("line_type")
        deleted = values.get("deleted", False)
        if type(line_id) is not str or len(line_id) > _MAX_ID_CHARS:
            return _failure("invalid_source_line_id", separator_id)
        if line_type is not None and type(line_type) is not str:
            return _failure("unsupported_source_line", separator_id)
        if type(deleted) is not bool:
            return _failure("unsupported_source_line", separator_id)
        source_id_counts[line_id] = source_id_counts.get(line_id, 0) + 1
        source_lines.append(line)
        resolver_lines.append(
            _ResolverLine(
                id=line_id,
                line_type=line_type,
                deleted=deleted,
                source_index=index,
                generated_candidates=(),
                gallery_variants=(),
            )
        )

    matches = [line for line in resolver_lines if line.id == separator_id]
    if not matches:
        return _failure("separator_not_found", separator_id)
    if len(matches) != 1:
        return _failure("ambiguous_separator_id", separator_id)

    source_separator = source_lines[matches[0].source_index]
    separator_values = vars(source_separator)
    for key in ("separator_label", "current_text", "original_file_name"):
        value = separator_values.get(key)
        if value is not None and type(value) is not str:
            return _failure("unsupported_scene_metadata", separator_id)
    color = separator_values.get("separator_color")
    if color is not None and type(color) is not str:
        return _failure("unsupported_scene_metadata", separator_id)

    resolver_lines[matches[0].source_index] = _ResolverLine(
        id=matches[0].id,
        line_type=matches[0].line_type,
        deleted=matches[0].deleted,
        source_index=matches[0].source_index,
        separator_label=separator_values.get("separator_label"),
        current_text=separator_values.get("current_text"),
        original_file_name=separator_values.get("original_file_name"),
    )

    block = resolve_route_block(resolver_lines, separator_id)
    if not block.resolved or block.separator_index is None or block.separator is None:
        code = "not_a_separator" if block.failure_reason == "specified line is not a separator" else "separator_not_found"
        return _failure(code, separator_id)
    if block.deleted:
        return _failure("separator_not_active", separator_id)
    if _contains_local_absolute_path(block.separator_label) or _contains_local_absolute_path(color):
        return _failure("unsafe_scene_metadata")

    illustrations: list[dict[str, Any]] = []
    selected_ids = {separator_id}
    root_prompts: list[str] = []
    for scene_order, resolved_line in enumerate(block.active_normal_member_lines):
        source_index = resolved_line.source_index
        line = source_lines[source_index]
        values = vars(line)
        line_id = values.get("id")
        if (
            type(line_id) is not str
            or not line_id
            or line_id in selected_ids
            or source_id_counts.get(line_id) != 1
        ):
            return _failure("ambiguous_illustration_id", separator_id)
        if _LOCAL_PATH_RE.search(_NETWORK_URL_RE.sub("", line_id)):
            return _failure("unsafe_source_identity", separator_id)
        selected_ids.add(line_id)
        positive = values.get("current_text")
        negative = values.get("negative_prompt", "")
        if type(positive) is not str or type(negative) is not str:
            return _failure("unsupported_prompt_text", separator_id)
        illustrations.append(
            {
                "source_line_id": line_id,
                "source_index": source_index,
                "scene_order": scene_order,
                "positive_prompt": positive,
                "negative_prompt": negative,
            }
        )
        root_prompts.append(positive)

    scene = {
        "label": block.separator_label,
        "color": color,
        "source_index": block.separator_index,
    }
    try:
        modules = _portable_module_snapshots(root_prompts, project.module_library)
        fingerprint = _fingerprint(separator_id, scene, illustrations, modules)
    except _ProjectionIssue as issue:
        return _failure(issue.code, separator_id)
    except (TypeError, ValueError, OverflowError):
        return _failure("unsupported_module_content", separator_id)

    result = {
        "contract_version": SCENE_PORTABILITY_CONTRACT_VERSION,
        "valid": True,
        "source_separator_id": separator_id,
        "scene": scene,
        "illustrations": illustrations,
        "module_snapshots": modules,
        "source_scene_fingerprint": fingerprint,
        "blockers": [],
        "diagnostics": [],
    }
    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return _failure("unsupported_module_content", separator_id)
    return result
