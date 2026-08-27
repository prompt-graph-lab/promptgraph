"""Route-aware planning and atomic apply for Gallery Variant promotion."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from collections import Counter
from typing import Any, Callable, Iterable

from core.route_operations import resolve_route_block, sanitize_selected_route_ids


VALID_SCOPES = (
    "current_route",
    "selected_route",
    "selected_routes",
    "selected_lines",
    "all_lines",
)
VALID_SOURCES = ("latest", "first")
VALID_PLACEMENTS = ("end", "after_parent")
LEGACY_SCOPE_MAP = {
    "all": "all_lines",
    "selected": "selected_lines",
}

PathResolver = Callable[[str], str]
PathExists = Callable[[str], bool]
PathStat = Callable[[str], os.stat_result]
LinePromoter = Callable[[Any, str, dict[str, Any], str], str | None]


def normalize_batch_variant_promotion_scope(scope: Any) -> str:
    clean_scope = str(scope or "").strip()
    clean_scope = LEGACY_SCOPE_MAP.get(clean_scope, clean_scope)
    return clean_scope if clean_scope in VALID_SCOPES else "current_route"


def _safe_lines(project: Any) -> tuple[list[Any], list[str]]:
    if project is None:
        return [], ["project is missing"]
    value = getattr(project, "prompt_lines", None)
    if not isinstance(value, (list, tuple)):
        return [], ["prompt_lines is not a list"]
    return list(value), []


def _line_id(line: Any) -> str:
    return str(getattr(line, "id", "") or "").strip()


def _line_type(line: Any) -> str:
    return str(getattr(line, "line_type", "") or "")


def _is_separator(line: Any) -> bool:
    return _line_type(line) == "separator"


def _is_workbench(line: Any) -> bool:
    return _line_type(line) == "workbench"


def _is_active_normal_line(line: Any) -> bool:
    return (
        line is not None
        and not bool(getattr(line, "deleted", False))
        and not _is_separator(line)
        and not _is_workbench(line)
    )


def _route_label(separator: Any) -> str:
    return str(
        getattr(separator, "separator_label", "")
        or getattr(separator, "current_text", "")
        or _line_id(separator)
        or "Route"
    )


def _line_label(line: Any) -> str:
    return str(
        getattr(line, "original_file_name", "")
        or _line_id(line)
        or "Line"
    )


def _input_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw = list(value)
    else:
        raw = [value]
    result = []
    seen = set()
    for item in raw:
        clean = str(item or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def _project_route_context(lines: list[Any]) -> dict[int, dict[str, Any]]:
    context = {}
    current_handle = ""
    current_label = "Unrouted"
    current_route_order = -1
    next_route_order = 0
    for project_order, line in enumerate(lines):
        if _is_separator(line):
            current_handle = _line_id(line)
            current_label = _route_label(line)
            current_route_order = next_route_order
            next_route_order += 1
        context[id(line)] = {
            "route_handle": current_handle,
            "route_label": current_label,
            "route_order": current_route_order,
            "project_order": project_order,
        }
    return context


def _route_target(
    project: Any,
    route_handle: str,
    *,
    line_id_counts: Counter,
) -> tuple[list[Any], dict[str, Any], str]:
    clean_handle = str(route_handle or "").strip()
    if not clean_handle:
        return [], {}, "Route could not be resolved"
    if line_id_counts.get(clean_handle, 0) != 1:
        return [], {}, "Route handle is missing or ambiguous"
    block = resolve_route_block(project, clean_handle)
    if not block.resolved or block.separator is None:
        return [], {}, block.failure_reason or "Route could not be resolved"
    if block.deleted:
        return [], {}, "Route separator is deleted"
    target_lines = list(block.active_normal_member_lines)
    summary = {
        "route_handle": block.route_handle,
        "route_label": block.separator_label or clean_handle,
        "route_order": 0,
        "project_order": block.separator_index,
        "target_line_count": len(target_lines),
    }
    if not target_lines:
        return [], summary, "Route has no active normal Gallery Lines"
    return target_lines, summary, ""


def _target_route_summaries(
    target_lines: list[Any],
    route_context: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for line in target_lines:
        context = route_context.get(id(line), {})
        handle = str(context.get("route_handle") or "")
        key = handle or "__unrouted__"
        if key not in summaries:
            route_order = context.get("route_order", -1)
            project_order = context.get("project_order", 0)
            summaries[key] = {
                "route_handle": handle,
                "route_label": str(context.get("route_label") or "Unrouted"),
                "route_order": int(route_order) if isinstance(route_order, int) else -1,
                "project_order": int(project_order) if isinstance(project_order, int) else 0,
                "target_line_count": 0,
            }
        summaries[key]["target_line_count"] += 1
    return sorted(summaries.values(), key=lambda item: item["project_order"])


def resolve_batch_variant_promotion_targets(
    project: Any,
    scope: Any,
    *,
    current_anchor_line_id: str = "",
    selected_route_id: str = "",
    selected_route_ids: Any = None,
    selected_line_ids: Any = None,
) -> dict[str, Any]:
    """Resolve one promotion target set in physical Project order."""

    normalized_scope = normalize_batch_variant_promotion_scope(scope)
    lines, diagnostics = _safe_lines(project)
    route_context = _project_route_context(lines)
    line_id_counts = Counter(_line_id(line) for line in lines if _line_id(line))
    lines_by_id: dict[str, list[Any]] = {}
    for line in lines:
        lines_by_id.setdefault(_line_id(line), []).append(line)

    target_lines: list[Any] = []
    selected_handles: list[str] = []
    resolved_route_summaries: list[dict[str, Any]] = []
    reason = ""

    if normalized_scope == "all_lines":
        target_lines = [line for line in lines if _is_active_normal_line(line)]
    elif normalized_scope == "selected_lines":
        requested_ids = _input_ids(selected_line_ids)
        ambiguous_ids = [line_id for line_id in requested_ids if line_id_counts.get(line_id, 0) > 1]
        if ambiguous_ids:
            reason = "Selected Line id is ambiguous"
            diagnostics.extend(f"ambiguous selected Line id: {line_id}" for line_id in ambiguous_ids)
        else:
            requested_set = set(requested_ids)
            target_lines = [
                line for line in lines
                if _line_id(line) in requested_set and _is_active_normal_line(line)
            ]
            ignored_ids = [
                line_id for line_id in requested_ids
                if not any(
                    _line_id(line) == line_id and _is_active_normal_line(line)
                    for line in lines
                )
            ]
            diagnostics.extend(f"ignored selected Line id: {line_id}" for line_id in ignored_ids)
            if not requested_ids or not target_lines:
                reason = "Selected Lines are empty"
    elif normalized_scope == "current_route":
        anchor_id = str(current_anchor_line_id or "").strip()
        anchor_matches = lines_by_id.get(anchor_id, [])
        if len(anchor_matches) != 1:
            reason = "Current Route anchor is missing or ambiguous"
        else:
            anchor = anchor_matches[0]
            route_handle = _line_id(anchor) if _is_separator(anchor) else str(
                route_context.get(id(anchor), {}).get("route_handle") or ""
            )
            target_lines, summary, reason = _route_target(
                project,
                route_handle,
                line_id_counts=line_id_counts,
            )
            if summary:
                resolved_route_summaries = [summary]
            if target_lines:
                selected_handles = [route_handle]
    elif normalized_scope == "selected_route":
        route_handle = str(selected_route_id or "").strip()
        target_lines, summary, reason = _route_target(
            project,
            route_handle,
            line_id_counts=line_id_counts,
        )
        if summary:
            resolved_route_summaries = [summary]
        if target_lines:
            selected_handles = [route_handle]
    else:
        requested_handles = _input_ids(selected_route_ids)
        ambiguous_handles = [
            route_handle
            for route_handle in requested_handles
            if line_id_counts.get(route_handle, 0) > 1
        ]
        selection = sanitize_selected_route_ids(project, selected_route_ids)
        diagnostics.extend(selection.get("diagnostics") or [])
        for field_name, label in (
            ("removed_missing_ids", "missing Route handle"),
            ("removed_deleted_ids", "deleted Route handle"),
            ("removed_non_separator_ids", "non-separator Route handle"),
        ):
            diagnostics.extend(
                f"ignored {label}: {value or '(empty)'}"
                for value in selection.get(field_name, [])
            )
        if ambiguous_handles:
            reason = "Selected Route handle is ambiguous"
        else:
            selected_handles = list(selection.get("selected_route_ids") or [])
            selected_blocks = list(selection.get("selected_route_blocks") or [])
            resolved_route_summaries = [
                {
                    "route_handle": block.route_handle,
                    "route_label": block.separator_label or block.route_handle,
                    "route_order": int(
                        route_context.get(id(block.separator), {}).get("route_order", -1)
                    ),
                    "project_order": block.separator_index,
                    "target_line_count": len(block.active_normal_member_lines),
                }
                for block in selected_blocks
            ]
            allowed_objects = {
                id(line)
                for block in selected_blocks
                for line in block.active_normal_member_lines
            }
            target_lines = [
                line for line in lines
                if id(line) in allowed_objects and _is_active_normal_line(line)
            ]
            if not selected_handles:
                reason = "Selected Routes are empty"
            elif not target_lines:
                reason = "Selected Routes have no active normal Gallery Lines"

    target_id_counts = Counter(_line_id(line) for line in target_lines if _line_id(line))
    duplicate_target_ids = sorted(
        line_id for line_id, count in target_id_counts.items() if count > 1
    )
    if duplicate_target_ids:
        reason = "Target Line id is ambiguous"
        diagnostics.extend(f"ambiguous target Line id: {line_id}" for line_id in duplicate_target_ids)

    route_summaries = (
        resolved_route_summaries
        if resolved_route_summaries
        else _target_route_summaries(target_lines, route_context)
    )
    if not selected_handles:
        selected_handles = [
            summary["route_handle"]
            for summary in route_summaries
            if summary.get("route_handle")
        ]

    if not reason and not target_lines:
        reason = "No active normal Gallery Lines were resolved"

    return {
        "valid": not reason,
        "scope": normalized_scope,
        "target_lines": target_lines,
        "target_line_ids": [_line_id(line) for line in target_lines],
        "target_line_count": len(target_lines),
        "selected_route_handles": selected_handles,
        "selected_route_labels": [
            summary["route_label"]
            for summary in route_summaries
            if summary.get("route_handle") in set(selected_handles)
        ],
        "selected_route_count": (
            len(selected_handles)
            if normalized_scope == "selected_routes"
            else len(route_summaries)
        ),
        "route_summaries": route_summaries,
        "excluded_workbench_count": sum(1 for line in lines if _is_workbench(line)),
        "excluded_deleted_count": sum(1 for line in lines if getattr(line, "deleted", False)),
        "diagnostics": diagnostics,
        "reason": reason,
    }


def _is_appended_gallery_variant_record(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    return (
        record.get("kind") == "gallery_variant"
        or record.get("source") == "batch_candidate_adoption"
        or str(record.get("id") or "").startswith("variant_")
    )


def _active_appended_variants(line: Any) -> list[tuple[int, dict[str, Any]]]:
    records = getattr(line, "gallery_variants", None)
    if not isinstance(records, list):
        return []
    result = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        if record.get("trashed"):
            continue
        if not _is_appended_gallery_variant_record(record):
            continue
        if not str(record.get("path") or "").strip():
            continue
        result.append((index, record))
    return result


def _variant_for_source(line: Any, source: str) -> tuple[int, dict[str, Any]] | None:
    variants = _active_appended_variants(line)
    if not variants:
        return None
    return variants[0] if source == "first" else variants[-1]


def _signature_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _signature_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_signature_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_signature_value(item) for item in value), key=str)
    return {"unsupported_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _digest(value: Any) -> str:
    payload = json.dumps(
        _signature_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _resolved_path(path: Any, resolve_path: PathResolver | None) -> str:
    clean_path = str(path or "").strip()
    if not clean_path:
        return ""
    try:
        return str(resolve_path(clean_path) or clean_path) if resolve_path else clean_path
    except (OSError, TypeError, ValueError):
        return clean_path


def _file_signature(
    path: Any,
    *,
    resolve_path: PathResolver | None,
    path_exists: PathExists | None,
    path_stat: PathStat | None,
) -> dict[str, Any]:
    raw_path = str(path or "").strip()
    resolved_path = _resolved_path(raw_path, resolve_path)
    try:
        exists = bool(path_exists(resolved_path)) if path_exists else os.path.exists(resolved_path)
    except (OSError, TypeError, ValueError):
        exists = False
    stat_payload = {}
    if exists:
        try:
            stat_result = path_stat(resolved_path) if path_stat else os.stat(resolved_path)
            stat_payload = {
                "size": int(getattr(stat_result, "st_size", 0) or 0),
                "mtime_ns": int(
                    getattr(
                        stat_result,
                        "st_mtime_ns",
                        int(getattr(stat_result, "st_mtime", 0) * 1_000_000_000),
                    )
                    or 0
                ),
            }
        except (OSError, TypeError, ValueError):
            stat_payload = {}
    return {
        "path": raw_path,
        "resolved_path": resolved_path,
        "exists": exists,
        "stat": stat_payload,
    }


def _parent_line_signature(line: Any) -> dict[str, Any]:
    line_fields = vars(line) if hasattr(line, "__dict__") else {}
    excluded_fields = {
        "gallery_variants",
        "generated_candidates",
        "workbench_source_line_id",
        "workbench_title",
        "workbench_note",
        "workbench_status",
    }
    return _signature_value(
        {
            key: value
            for key, value in line_fields.items()
            if key not in excluded_fields
        }
    )


def _variant_sequence_signature(line: Any) -> list[dict[str, Any]]:
    variants = getattr(line, "gallery_variants", None)
    if not isinstance(variants, list):
        return []
    result = []
    for index, record in enumerate(variants):
        if not isinstance(record, dict):
            result.append(
                {
                    "index": index,
                    "record_type": f"{type(record).__module__}.{type(record).__qualname__}",
                }
            )
            continue
        result.append(
            {
                "index": index,
                "id": str(record.get("id") or ""),
                "kind": str(record.get("kind") or ""),
                "source": str(record.get("source") or ""),
                "path": str(record.get("path") or ""),
                "trashed": bool(record.get("trashed")),
            }
        )
    return result


def _signature_target_state(
    line: Any,
    *,
    source: str,
    resolve_path: PathResolver | None,
    path_exists: PathExists | None,
    path_stat: PathStat | None,
    selected_file_signature: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_variant = _variant_for_source(line, source)
    variant_index = selected_variant[0] if selected_variant else None
    variant = selected_variant[1] if selected_variant else None
    variant_path = str(variant.get("path") or "").strip() if variant else ""
    file_signature = selected_file_signature
    if file_signature is None:
        file_signature = _file_signature(
            variant_path,
            resolve_path=resolve_path,
            path_exists=path_exists,
            path_stat=path_stat,
        )
    return {
        "parent_state": _parent_line_signature(line),
        "variant_sequence": _variant_sequence_signature(line),
        "selected_variant_index": variant_index,
        "selected_variant_signature": _digest(variant) if variant is not None else "",
        "selected_variant_file": file_signature,
    }


def _plan_inputs(
    *,
    scope: str,
    source: str,
    placement: str,
    current_anchor_line_id: str,
    selected_route_id: str,
    selected_route_ids: Any,
    selected_line_ids: Any,
) -> dict[str, Any]:
    normalized_scope = normalize_batch_variant_promotion_scope(scope)
    inputs = {
        "scope": normalized_scope,
        "source": str(source or ""),
        "placement": str(placement or ""),
        "current_anchor_line_id": "",
        "selected_route_id": "",
        "selected_route_ids": [],
        "selected_line_ids": [],
    }
    if normalized_scope == "current_route":
        inputs["current_anchor_line_id"] = str(current_anchor_line_id or "")
    elif normalized_scope == "selected_route":
        inputs["selected_route_id"] = str(selected_route_id or "")
    elif normalized_scope == "selected_routes":
        inputs["selected_route_ids"] = _input_ids(selected_route_ids)
    elif normalized_scope == "selected_lines":
        inputs["selected_line_ids"] = _input_ids(selected_line_ids)
    return inputs


def _build_signature_payload(
    project: Any,
    *,
    inputs: dict[str, Any],
    resolution: dict[str, Any],
    project_path: str,
    resolve_path: PathResolver | None,
    path_exists: PathExists | None,
    path_stat: PathStat | None,
    selected_file_signatures: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    lines, _diagnostics = _safe_lines(project)
    route_context = _project_route_context(lines)
    project_order_by_object = {
        id(line): project_order for project_order, line in enumerate(lines)
    }
    selected_file_signatures = selected_file_signatures or {}
    target_state = [
        {
            "project_order": project_order_by_object.get(id(line), 0),
            "line_id": _line_id(line),
            "route_context": route_context.get(id(line), {}),
            "line_state": _signature_target_state(
                line,
                source=inputs["source"],
                resolve_path=resolve_path,
                path_exists=path_exists,
                path_stat=path_stat,
                selected_file_signature=selected_file_signatures.get(id(line)),
            ),
        }
        for line in resolution.get("target_lines") or []
    ]
    structure = [
        {
            "project_order": project_order,
            "line_id": _line_id(line),
            "line_type": _line_type(line),
            "deleted": bool(getattr(line, "deleted", False)),
            "current_index": getattr(line, "current_index", None),
            "separator_label": str(getattr(line, "separator_label", "") or ""),
            "separator_color": str(getattr(line, "separator_color", "") or ""),
        }
        for project_order, line in enumerate(lines)
    ]
    return {
        "project_identity": {
            "project_path": str(project_path or ""),
            "source_directory": str(getattr(project, "source_directory", "") or ""),
        },
        "inputs": inputs,
        "resolved_route_handles": list(resolution.get("selected_route_handles") or []),
        "resolved_route_labels": list(resolution.get("selected_route_labels") or []),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "project_structure": structure,
        "target_state": target_state,
    }


def build_batch_variant_promotion_plan(
    project: Any,
    *,
    scope: Any,
    source: str = "latest",
    placement: str = "end",
    current_anchor_line_id: str = "",
    selected_route_id: str = "",
    selected_route_ids: Any = None,
    selected_line_ids: Any = None,
    project_path: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
) -> dict[str, Any]:
    """Build a non-mutating Route/Line-aware Variant promotion plan."""

    inputs = _plan_inputs(
        scope=scope,
        source=source,
        placement=placement,
        current_anchor_line_id=current_anchor_line_id,
        selected_route_id=selected_route_id,
        selected_route_ids=selected_route_ids,
        selected_line_ids=selected_line_ids,
    )
    resolution = resolve_batch_variant_promotion_targets(
        project,
        inputs["scope"],
        current_anchor_line_id=inputs["current_anchor_line_id"],
        selected_route_id=inputs["selected_route_id"],
        selected_route_ids=inputs["selected_route_ids"],
        selected_line_ids=inputs["selected_line_ids"],
    )
    lines, diagnostics = _safe_lines(project)
    diagnostics.extend(resolution.get("diagnostics") or [])
    route_context = _project_route_context(lines)
    project_order_by_object = {
        id(line): project_order for project_order, line in enumerate(lines)
    }

    reason = str(resolution.get("reason") or "")
    if inputs["source"] not in VALID_SOURCES:
        reason = "Variant source is unsupported"
    if inputs["placement"] not in VALID_PLACEMENTS:
        reason = "Variant placement is unsupported"

    entries = []
    variants_found = 0
    will_promote = 0
    seen_pairs = set()
    selected_file_signatures: dict[int, dict[str, Any]] = {}
    for line in resolution.get("target_lines") or []:
        line_id = _line_id(line)
        context = route_context.get(id(line), {})
        selected_variant = _variant_for_source(line, inputs["source"])
        variant_index = selected_variant[0] if selected_variant else None
        variant = selected_variant[1] if selected_variant else None
        variant_id = str(variant.get("id") or "") if isinstance(variant, dict) else ""
        variant_path = str(variant.get("path") or "").strip() if isinstance(variant, dict) else ""
        resolved_variant_path = _resolved_path(variant_path, resolve_path)
        file_state = _file_signature(
            variant_path,
            resolve_path=resolve_path,
            path_exists=path_exists,
            path_stat=path_stat,
        )
        selected_file_signatures[id(line)] = file_state
        if variant_path:
            variants_found += 1
        promotable = bool(variant_path and file_state["exists"])
        skip_reason = ""
        if not selected_variant:
            skip_reason = "appended gallery variant not found"
        elif not file_state["exists"]:
            skip_reason = "missing variant image"
        pair = (line_id, variant_index, variant_id, variant_path)
        if promotable and pair in seen_pairs:
            promotable = False
            skip_reason = "duplicate promotion entry"
        seen_pairs.add(pair)
        if promotable:
            will_promote += 1
        entries.append(
            {
                "route_handle": str(context.get("route_handle") or ""),
                "route_label": str(context.get("route_label") or "Unrouted"),
                "route_order": (
                    int(context.get("route_order"))
                    if isinstance(context.get("route_order"), int)
                    else -1
                ),
                "parent_line_id": line_id,
                "parent_line_label": _line_label(line),
                "parent_project_order": project_order_by_object.get(id(line), 0),
                "variant_index": variant_index,
                "variant_id": variant_id,
                "variant_path": variant_path,
                "resolved_variant_path": resolved_variant_path,
                "variant_record_signature": _digest(variant) if variant is not None else "",
                "source": inputs["source"],
                "placement": inputs["placement"],
                "promotable": promotable,
                "skip_reason": skip_reason,
                "file_signature": file_state,
            }
        )

    route_summaries = []
    for target_summary in resolution.get("route_summaries") or []:
        handle = str(target_summary.get("route_handle") or "")
        label = str(target_summary.get("route_label") or "Unrouted")
        route_entries = [
            entry
            for entry in entries
            if entry["route_handle"] == handle and entry["route_label"] == label
        ]
        route_summaries.append(
            {
                **target_summary,
                "variants_found": sum(1 for entry in route_entries if entry["variant_path"]),
                "missing_variants": sum(1 for entry in route_entries if not entry["promotable"]),
                "will_promote": sum(1 for entry in route_entries if entry["promotable"]),
            }
        )

    signature_payload = _build_signature_payload(
        project,
        inputs=inputs,
        resolution=resolution,
        project_path=project_path,
        resolve_path=resolve_path,
        path_exists=path_exists,
        path_stat=path_stat,
        selected_file_signatures=selected_file_signatures,
    )
    signature = _digest(signature_payload)
    missing_variants = max(0, len(entries) - will_promote)
    return {
        "valid": bool(resolution.get("valid")) and not reason,
        "signature": signature,
        "signature_payload": signature_payload,
        "scope": inputs["scope"],
        "source": inputs["source"],
        "placement": inputs["placement"],
        "project_path": str(project_path or ""),
        "selected_route_handles": list(resolution.get("selected_route_handles") or []),
        "selected_route_labels": list(resolution.get("selected_route_labels") or []),
        "selected_route_count": int(resolution.get("selected_route_count", 0) or 0),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "target_line_count": int(resolution.get("target_line_count", 0) or 0),
        "variants_found": variants_found,
        "missing_variants": missing_variants,
        "will_promote": will_promote,
        "skipped_count": missing_variants,
        "route_summaries": route_summaries,
        "entries": entries,
        "diagnostics": diagnostics,
        "reason": reason,
    }


def build_batch_variant_promotion_signature(
    project: Any,
    *,
    scope: Any,
    source: str = "latest",
    placement: str = "end",
    current_anchor_line_id: str = "",
    selected_route_id: str = "",
    selected_route_ids: Any = None,
    selected_line_ids: Any = None,
    project_path: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
) -> str:
    """Build the lightweight stale-check signature without a full preview plan."""

    inputs = _plan_inputs(
        scope=scope,
        source=source,
        placement=placement,
        current_anchor_line_id=current_anchor_line_id,
        selected_route_id=selected_route_id,
        selected_route_ids=selected_route_ids,
        selected_line_ids=selected_line_ids,
    )
    resolution = resolve_batch_variant_promotion_targets(
        project,
        inputs["scope"],
        current_anchor_line_id=inputs["current_anchor_line_id"],
        selected_route_id=inputs["selected_route_id"],
        selected_route_ids=inputs["selected_route_ids"],
        selected_line_ids=inputs["selected_line_ids"],
    )
    payload = _build_signature_payload(
        project,
        inputs=inputs,
        resolution=resolution,
        project_path=project_path,
        resolve_path=resolve_path,
        path_exists=path_exists,
        path_stat=path_stat,
    )
    return _digest(payload)


def validate_batch_variant_promotion_submit(
    project: Any,
    stored_plan: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    fresh_plan = build_batch_variant_promotion_plan(project, **kwargs)
    stored_signature = stored_plan.get("signature") if isinstance(stored_plan, dict) else ""
    stale = not stored_signature or stored_signature != fresh_plan.get("signature")
    reason = ""
    if stale:
        reason = "Fresh Preview is required"
    elif not fresh_plan.get("valid"):
        reason = fresh_plan.get("reason") or "promotion plan is invalid"
    return {
        "valid": not stale and bool(fresh_plan.get("valid")),
        "stale_preview": stale,
        "fresh_plan": fresh_plan,
        "reason": reason,
    }


def _clone_variant_for_entry(
    project: Any,
    entry: dict[str, Any],
) -> tuple[Any | None, dict[str, Any] | None]:
    lines, _diagnostics = _safe_lines(project)
    matches = [line for line in lines if _line_id(line) == entry.get("parent_line_id")]
    if len(matches) != 1:
        return None, None
    line = matches[0]
    variants = getattr(line, "gallery_variants", None)
    index = entry.get("variant_index")
    if not isinstance(variants, list) or not isinstance(index, int):
        return line, None
    if index < 0 or index >= len(variants):
        return line, None
    variant = variants[index]
    if not isinstance(variant, dict):
        return line, None
    if _digest(variant) != entry.get("variant_record_signature"):
        return line, None
    return line, variant


def apply_batch_variant_promotion_plan(
    project: Any,
    stored_plan: Any,
    *,
    promote_line: LinePromoter,
    scope: Any,
    source: str = "latest",
    placement: str = "end",
    current_anchor_line_id: str = "",
    selected_route_id: str = "",
    selected_route_ids: Any = None,
    selected_line_ids: Any = None,
    project_path: str = "",
    resolve_path: PathResolver | None = None,
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
) -> dict[str, Any]:
    """Apply one fresh plan to a clone, leaving the source unchanged on failure."""

    validation = validate_batch_variant_promotion_submit(
        project,
        stored_plan,
        scope=scope,
        source=source,
        placement=placement,
        current_anchor_line_id=current_anchor_line_id,
        selected_route_id=selected_route_id,
        selected_route_ids=selected_route_ids,
        selected_line_ids=selected_line_ids,
        project_path=project_path,
        resolve_path=resolve_path,
        path_exists=path_exists,
        path_stat=path_stat,
    )
    fresh_plan = validation["fresh_plan"]
    base_result = {
        "applied": False,
        "stale_preview": bool(validation["stale_preview"]),
        "promoted_count": 0,
        "skipped_count": int(fresh_plan.get("skipped_count", 0) or 0),
        "failed_count": 0,
        "new_line_ids": [],
        "updated_project": None,
        "selected_route_count": int(fresh_plan.get("selected_route_count", 0) or 0),
        "fresh_plan": fresh_plan,
        "error": validation["reason"],
    }
    if not validation["valid"]:
        return base_result
    if int(fresh_plan.get("will_promote", 0) or 0) <= 0:
        base_result["error"] = ""
        return base_result

    working_project = copy.deepcopy(project)
    new_line_ids = []
    try:
        for entry in fresh_plan.get("entries") or []:
            if not entry.get("promotable"):
                continue
            _line, variant = _clone_variant_for_entry(working_project, entry)
            if variant is None:
                raise RuntimeError(
                    f"Variant changed before apply: {entry.get('parent_line_id') or '(unknown)'}"
                )
            new_line_id = promote_line(
                working_project,
                str(entry.get("parent_line_id") or ""),
                variant,
                str(entry.get("placement") or placement),
            )
            if not new_line_id:
                raise RuntimeError(
                    f"Variant promotion failed: {entry.get('parent_line_id') or '(unknown)'}"
                )
            new_line_ids.append(str(new_line_id))
        if len(new_line_ids) != int(fresh_plan.get("will_promote", 0) or 0):
            raise RuntimeError("Variant promotion count changed during apply")
    except Exception as exc:
        return {
            **base_result,
            "failed_count": 1,
            "error": str(exc),
        }

    return {
        **base_result,
        "applied": True,
        "promoted_count": len(new_line_ids),
        "new_line_ids": new_line_ids,
        "updated_project": working_project,
        "error": "",
    }


def resolve_variant_promotion_insert_index(
    project: Any,
    parent_line_id: str,
    placement: str = "end",
) -> int:
    lines = list(getattr(project, "prompt_lines", []) or [])
    if placement == "after_parent":
        matches = [
            index for index, line in enumerate(lines)
            if _line_id(line) == str(parent_line_id or "")
        ]
        if len(matches) != 1:
            raise ValueError("parent Line is missing or ambiguous")
        return matches[0] + 1
    for index in range(len(lines) - 1, -1, -1):
        if not getattr(lines[index], "deleted", False):
            return index + 1
    return len(lines)
