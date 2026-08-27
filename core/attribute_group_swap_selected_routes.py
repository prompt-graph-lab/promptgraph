"""Preview-first Attribute Group Swap support for session-only Selected Routes."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable
import copy
import hashlib
import json

from core.operations import (
    apply_attribute_group_swap,
    build_attribute_group_negative_preview,
    get_project_attribute_groups,
    normalize_attribute_group_name,
    normalize_attribute_slot,
    preview_attribute_group_swap,
)
from core.route_operations import sanitize_selected_route_ids


_IMAGE_FIELDS = ("selected_candidate_path", "generated_image_path", "image_path")
_PROMPT_MUTATION_FIELDS = {"current_text", "tokens", "edited", "node_path"}


def _safe_lines(project: Any) -> list[Any]:
    lines = getattr(project, "prompt_lines", None) if project is not None else None
    return list(lines) if isinstance(lines, (list, tuple)) else []


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _stable_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_stable_value(item) for item in value), key=lambda item: repr(item))
    return {"unsupported_type": f"{type(value).__module__}.{type(value).__qualname__}"}


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        _stable_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _selection_diagnostics(selection: dict[str, Any]) -> list[str]:
    diagnostics = list(selection.get("diagnostics") or [])
    for field_name, label in (
        ("removed_missing_ids", "missing Route id"),
        ("removed_deleted_ids", "deleted Route id"),
        ("removed_non_separator_ids", "non-separator selected id"),
        ("removed_duplicate_ids", "duplicate or ambiguous Route id"),
    ):
        diagnostics.extend(
            f"ignored {label}: {value or '(empty)'}"
            for value in selection.get(field_name, [])
        )
    return diagnostics


def _resolve_targets(project: Any, selected_route_ids: Any) -> dict[str, Any]:
    try:
        selection = sanitize_selected_route_ids(project, selected_route_ids)
    except Exception as exc:
        return {
            "selection": {},
            "target_lines": [],
            "target_line_ids": [],
            "route_context_by_object": {},
            "duplicate_line_ids": [],
            "malformed_line_count": 0,
            "diagnostics": [f"Selected Routes resolution failed: {exc}"],
        }

    lines = _safe_lines(project)
    selected_objects: dict[int, dict[str, Any]] = {}
    for route_order, (summary, block) in enumerate(zip(
        selection.get("selected_route_summaries") or [],
        selection.get("selected_route_blocks") or [],
    )):
        route_line_order = 0
        for line in getattr(block, "active_normal_member_lines", ()) or ():
            selected_objects[id(line)] = {
                "route_id": _clean_id(summary.get("route_handle")),
                "route_label": str(summary.get("label") or summary.get("route_handle") or "Route"),
                "route_color": summary.get("color"),
                "route_order": route_order,
                "route_line_order": route_line_order,
            }
            route_line_order += 1

    line_id_counts = Counter(
        _clean_id(getattr(line, "id", ""))
        for line in lines
        if _clean_id(getattr(line, "id", ""))
    )
    duplicate_line_ids = sorted(
        line_id
        for line_id, count in line_id_counts.items()
        if count > 1 and any(
            id(line) in selected_objects and _clean_id(getattr(line, "id", "")) == line_id
            for line in lines
        )
    )
    malformed_line_count = sum(
        1
        for line in lines
        if id(line) in selected_objects and not _clean_id(getattr(line, "id", ""))
    )
    target_lines = [
        line
        for line in lines
        if (
            id(line) in selected_objects
            and _clean_id(getattr(line, "id", ""))
            and not getattr(line, "deleted", False)
            and getattr(line, "line_type", None) not in {"separator", "workbench"}
            and _clean_id(getattr(line, "id", "")) not in duplicate_line_ids
        )
    ]
    malformed_token_line_ids = [
        _clean_id(getattr(line, "id", ""))
        for line in target_lines
        if not isinstance(getattr(line, "tokens", None), (list, tuple))
    ]
    diagnostics = _selection_diagnostics(selection)
    diagnostics.extend(
        f"ambiguous selected Route line id: {line_id}"
        for line_id in duplicate_line_ids
    )
    if malformed_line_count:
        diagnostics.append(f"ignored selected Route Lines with missing ids: {malformed_line_count}")
    diagnostics.extend(
        f"selected Route Line has malformed tokens: {line_id}"
        for line_id in malformed_token_line_ids
    )
    return {
        "selection": selection,
        "target_lines": target_lines,
        "target_line_ids": [_clean_id(getattr(line, "id", "")) for line in target_lines],
        "route_context_by_object": selected_objects,
        "duplicate_line_ids": duplicate_line_ids,
        "malformed_token_line_ids": malformed_token_line_ids,
        "malformed_line_count": malformed_line_count,
        "diagnostics": diagnostics,
    }


def _raw_attribute_library(project: Any) -> tuple[dict[str, Any], list[str]]:
    raw_library = getattr(project, "attribute_groups", None) if project is not None else None
    if not isinstance(raw_library, dict):
        return {}, ["Attribute Group Library is not a dictionary"]
    return raw_library, []


def _find_raw_group(library: dict[str, Any], group_key: str) -> Any:
    normalized_key = normalize_attribute_group_name(group_key)
    for raw_key, record in library.items():
        if normalize_attribute_group_name(raw_key) == normalized_key:
            return record
        if isinstance(record, dict) and normalize_attribute_group_name(record.get("name")) == normalized_key:
            return record
    return None


def _validate_group_record(
    library: dict[str, Any],
    group_key: str,
    role: str,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not group_key:
        return [f"{role} Attribute Group is required"], warnings
    record = _find_raw_group(library, group_key)
    if record is None:
        return [f"{role} Attribute Group not found: {group_key}"], warnings
    if not isinstance(record, dict):
        return [f"{role} Attribute Group record is malformed: {group_key}"], warnings
    raw_slot = record.get("slot")
    if not isinstance(raw_slot, str) or not normalize_attribute_slot(raw_slot):
        errors.append(f"{role} Attribute Slot is missing or malformed: {group_key}")
    raw_tokens = record.get("tokens")
    if not isinstance(raw_tokens, (list, tuple)):
        errors.append(f"{role} Attribute Group tokens are malformed: {group_key}")
    elif any(not isinstance(token, str) for token in raw_tokens):
        errors.append(f"{role} Attribute Group tokens contain malformed values: {group_key}")
    elif not any(isinstance(token, str) and token.strip() for token in raw_tokens):
        errors.append(f"{role} Attribute Group has no usable tokens: {group_key}")
    for field_name in ("negative_tags", "negative_when_disabled"):
        value = record.get(field_name, [])
        if not isinstance(value, (str, list)):
            warnings.append(f"{role} {field_name} metadata is malformed and will preview as empty")
        elif isinstance(value, list) and any(not isinstance(item, str) for item in value):
            warnings.append(f"{role} {field_name} contains non-string values that will be ignored")
    notes = record.get("negative_notes", "")
    if notes is not None and not isinstance(notes, str):
        warnings.append(f"{role} negative_notes metadata is malformed and will preview as empty")
    return errors, warnings


def _sanitize_negative_metadata_copy(raw_library: Any) -> Any:
    if not isinstance(raw_library, dict):
        return copy.deepcopy(raw_library)
    sanitized = copy.deepcopy(raw_library)
    for record in sanitized.values():
        if not isinstance(record, dict):
            continue
        for field_name in ("negative_tags", "negative_when_disabled"):
            value = record.get(field_name, [])
            if isinstance(value, str):
                continue
            if isinstance(value, list):
                record[field_name] = [item for item in value if isinstance(item, str)]
            else:
                record[field_name] = []
        if not isinstance(record.get("negative_notes", ""), str):
            record["negative_notes"] = ""
    return sanitized


def _normalized_library(project: Any) -> tuple[dict[str, Any], list[str]]:
    try:
        clone = copy.deepcopy(project)
        clone.attribute_groups = _sanitize_negative_metadata_copy(
            getattr(clone, "attribute_groups", None)
        )
        groups = get_project_attribute_groups(clone)
    except Exception as exc:
        return {}, [f"Attribute Group normalization failed: {exc}"]
    if not isinstance(groups, dict):
        return {}, ["Normalized Attribute Group Library is not a dictionary"]
    return groups, []


def get_attribute_groups_snapshot(project: Any) -> dict[str, Any]:
    """Return normalized display data without mutating the live Project."""

    groups, _diagnostics = _normalized_library(project)
    return groups


def _signature_payload(
    project: Any,
    selected_route_ids: Any,
    *,
    from_group_key: str,
    to_group_key: str,
    require_full_match: bool,
    project_path: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = _resolve_targets(project, selected_route_ids)
    selection = resolution.get("selection") or {}
    lines = _safe_lines(project)
    target_ids = set(resolution.get("target_line_ids") or [])
    library, library_diagnostics = _raw_attribute_library(project)
    structure = []
    target_state = []
    for project_order, line in enumerate(lines):
        line_id = _clean_id(getattr(line, "id", ""))
        structure.append({
            "project_order": project_order,
            "line_id": line_id,
            "line_type": getattr(line, "line_type", None),
            "deleted": bool(getattr(line, "deleted", False)),
            "separator_label": getattr(line, "separator_label", None),
            "separator_color": getattr(line, "separator_color", None),
        })
        if line_id in target_ids:
            target_state.append({
                "project_order": project_order,
                "line_id": line_id,
                "current_text": getattr(line, "current_text", None),
                "negative_prompt": getattr(line, "negative_prompt", None),
                "tokens": getattr(line, "tokens", None),
                "selected_candidate_path": getattr(line, "selected_candidate_path", None),
                "generated_image_path": getattr(line, "generated_image_path", None),
                "image_path": getattr(line, "image_path", None),
            })
    payload = {
        "scope": "selected_routes",
        "project_path": str(project_path or ""),
        "project_source_directory": getattr(project, "source_directory", None),
        "selected_route_ids": list(selection.get("selected_route_ids") or []),
        "selected_route_labels": list(selection.get("selected_route_labels") or []),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "project_structure": structure,
        "target_line_state": target_state,
        "from_group_key": from_group_key,
        "to_group_key": to_group_key,
        "require_full_match": bool(require_full_match),
        "attribute_groups": library,
    }
    resolution["diagnostics"] = list(resolution.get("diagnostics") or []) + library_diagnostics
    return payload, resolution


def build_selected_routes_attribute_group_swap_signature(
    project: Any,
    selected_route_ids: Any,
    *,
    from_group_key: str,
    to_group_key: str,
    require_full_match: bool = False,
    project_path: str = "",
) -> str:
    payload, _resolution = _signature_payload(
        project,
        selected_route_ids,
        from_group_key=normalize_attribute_group_name(from_group_key),
        to_group_key=normalize_attribute_group_name(to_group_key),
        require_full_match=bool(require_full_match),
        project_path=project_path,
    )
    return _digest(payload)


def _main_image_reference(line: Any) -> dict[str, Any]:
    for field_name in _IMAGE_FIELDS:
        value = getattr(line, field_name, None)
        if value:
            if isinstance(value, str):
                return {"field": field_name, "path": value, "available": True}
            return {"field": field_name, "path": "", "available": False}
    return {"field": "", "path": "", "available": True}


def _drift_risk(positive_changed: bool, negative_changed: bool, image: dict[str, Any]) -> str:
    if not positive_changed and not negative_changed:
        return "no prompt change"
    if not image.get("available"):
        return "image reference unavailable"
    if not image.get("path"):
        return "prompt changed, no representative image"
    if positive_changed and negative_changed:
        return "positive and negative changed while main image remains unchanged"
    return "prompt changed while main image remains unchanged"


def _safe_negative_metadata_preview(
    project: Any,
    group_key: str,
    line: Any,
) -> tuple[dict[str, Any], str]:
    try:
        return build_attribute_group_negative_preview(project, group_key, line), ""
    except Exception as exc:
        return {}, f"Attribute Group negative metadata preview failed for {_clean_id(getattr(line, 'id', ''))}: {exc}"


def _empty_plan(
    signature: str,
    resolution: dict[str, Any],
    from_group_key: str,
    to_group_key: str,
    require_full_match: bool,
    diagnostics: list[str],
    reason: str,
    *,
    from_group: dict[str, Any] | None = None,
    to_group: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = resolution.get("selection") or {}
    from_group = from_group or {}
    to_group = to_group or {}
    return {
        "scope": "selected_routes",
        "signature": signature,
        "source_fingerprint": signature,
        "from_group_key": from_group_key,
        "to_group_key": to_group_key,
        "from_group_name": from_group.get("name", from_group_key),
        "to_group_name": to_group.get("name", to_group_key),
        "from_group_snapshot": copy.deepcopy(from_group) or None,
        "to_group_snapshot": copy.deepcopy(to_group) or None,
        "from_slot": from_group.get("slot", ""),
        "to_slot": to_group.get("slot", ""),
        "slot_compatible": False,
        "from_tokens": list(from_group.get("tokens") or []),
        "to_tokens": list(to_group.get("tokens") or []),
        "shared_tokens": [],
        "tokens_to_remove": [],
        "tokens_to_add": [],
        "require_full_match": bool(require_full_match),
        "selected_route_ids": list(selection.get("selected_route_ids") or []),
        "selected_route_labels": list(selection.get("selected_route_labels") or []),
        "selected_route_count": int(selection.get("selected_route_count", 0) or 0),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "target_line_count": len(resolution.get("target_line_ids") or []),
        "changed_line_count": 0,
        "positive_change_count": 0,
        "negative_change_count": 0,
        "full_match_count": 0,
        "partial_match_count": 0,
        "no_match_count": 0,
        "no_op_count": 0,
        "skipped_count": 0,
        "blocked_count": max(1, len(diagnostics)),
        "image_line_count": 0,
        "drift_count": 0,
        "route_summaries": [],
        "entries": [],
        "diagnostics": diagnostics,
        "valid": False,
        "reason": reason,
        "prompt_only": True,
        "negative_prompt_semantics": "unchanged; Attribute Group negative metadata is preview-only",
    }


def build_selected_routes_attribute_group_swap_plan(
    project: Any,
    selected_route_ids: Any,
    *,
    from_group_key: str,
    to_group_key: str,
    require_full_match: bool = False,
    project_path: str = "",
    preview_func: Callable[..., dict[str, Any]] = preview_attribute_group_swap,
) -> dict[str, Any]:
    """Build a non-mutating multi-Route plan using existing Attribute Group semantics."""

    from_group_key = normalize_attribute_group_name(from_group_key)
    to_group_key = normalize_attribute_group_name(to_group_key)
    require_full_match = bool(require_full_match)
    payload, resolution = _signature_payload(
        project,
        selected_route_ids,
        from_group_key=from_group_key,
        to_group_key=to_group_key,
        require_full_match=require_full_match,
        project_path=project_path,
    )
    signature = _digest(payload)
    diagnostics = list(resolution.get("diagnostics") or [])
    selection = resolution.get("selection") or {}
    raw_library, library_diagnostics = _raw_attribute_library(project)
    diagnostics.extend(item for item in library_diagnostics if item not in diagnostics)
    validation_errors: list[str] = []
    if from_group_key == to_group_key and from_group_key:
        validation_errors.append("Source and replacement Attribute Groups must be different")
    for role, key in (("source", from_group_key), ("replacement", to_group_key)):
        errors, warnings = _validate_group_record(raw_library, key, role)
        validation_errors.extend(errors)
        diagnostics.extend(warnings)
    normalized_groups, normalization_errors = _normalized_library(project)
    validation_errors.extend(normalization_errors)
    from_group = normalized_groups.get(from_group_key, {})
    to_group = normalized_groups.get(to_group_key, {})
    from_slot = normalize_attribute_slot(from_group.get("slot")) if from_group else ""
    to_slot = normalize_attribute_slot(to_group.get("slot")) if to_group else ""
    if from_group and to_group and from_slot != to_slot:
        validation_errors.append(
            f"Attribute Slot mismatch: source={from_slot or '(missing)'} replacement={to_slot or '(missing)'}"
        )
    diagnostics.extend(error for error in validation_errors if error not in diagnostics)

    reason = ""
    if project is None:
        reason = "Project is missing"
    elif not isinstance(getattr(project, "prompt_lines", None), (list, tuple)):
        reason = "prompt_lines is not a list"
    elif not selection.get("selected_route_ids"):
        reason = "no selected Routes"
    elif resolution.get("duplicate_line_ids"):
        reason = "selected Routes contain ambiguous duplicate Line ids"
    elif resolution.get("malformed_token_line_ids"):
        reason = "selected Routes contain Lines with malformed tokens"
    elif not resolution.get("target_line_ids"):
        reason = "selected Routes have no Attribute Group Swap target Lines"
    elif validation_errors:
        reason = validation_errors[0]
    if reason:
        return _empty_plan(
            signature,
            resolution,
            from_group_key,
            to_group_key,
            require_full_match,
            diagnostics,
            reason,
            from_group=from_group,
            to_group=to_group,
        )

    try:
        preview_project = copy.deepcopy(project)
        preview_project.attribute_groups = _sanitize_negative_metadata_copy(
            getattr(preview_project, "attribute_groups", None)
        )
        preview = preview_func(
            preview_project,
            from_group_key,
            to_group_key,
            target_line_ids=list(resolution["target_line_ids"]),
            require_full_match=require_full_match,
            example_limit=1000000,
            include_unchanged_examples=True,
        )
    except Exception as exc:
        diagnostics.append(f"Attribute Group Swap preview failed: {exc}")
        return _empty_plan(
            signature,
            resolution,
            from_group_key,
            to_group_key,
            require_full_match,
            diagnostics,
            "Attribute Group Swap preview failed",
            from_group=from_group,
            to_group=to_group,
        )

    for warning in preview.get("warnings") or []:
        diagnostics.append(str(warning))
    examples_by_id = {
        _clean_id(example.get("line_id")): example
        for example in preview.get("examples") or []
        if isinstance(example, dict) and _clean_id(example.get("line_id"))
    }
    preview_lines_by_id = {
        _clean_id(getattr(line, "id", "")): line
        for line in _safe_lines(preview_project)
        if _clean_id(getattr(line, "id", ""))
    }
    context_by_object = resolution.get("route_context_by_object") or {}
    project_order_by_object = {id(line): index for index, line in enumerate(_safe_lines(project))}
    entries = []
    for line in resolution.get("target_lines") or []:
        line_id = _clean_id(getattr(line, "id", ""))
        context = context_by_object.get(id(line), {})
        example = examples_by_id.get(line_id, {})
        raw_before_positive = str(getattr(line, "current_text", "") or "")
        before_positive = str(example.get("before", raw_before_positive) or "")
        after_positive = str(example.get("after", before_positive) or "")
        before_negative = str(getattr(line, "negative_prompt", "") or "")
        after_negative = before_negative
        positive_changed = bool(example.get("changed")) and after_positive != before_positive
        negative_changed = False
        if example.get("full_match"):
            match_classification = "full_match"
        elif example.get("partial_match"):
            match_classification = "partial_match"
        else:
            match_classification = "no_match"
        no_op = not positive_changed
        if positive_changed:
            skip_reason = ""
        elif match_classification == "partial_match" and require_full_match:
            skip_reason = "partial match blocked by require full match"
        elif match_classification == "no_match":
            skip_reason = "source Attribute Group not matched"
        else:
            skip_reason = "replacement produces no Prompt change"
        image = _main_image_reference(line)
        preview_line = preview_lines_by_id.get(line_id)
        source_negative_preview, source_negative_error = _safe_negative_metadata_preview(
            preview_project, from_group_key, preview_line
        )
        replacement_negative_preview, replacement_negative_error = _safe_negative_metadata_preview(
            preview_project, to_group_key, preview_line
        )
        for negative_error in (source_negative_error, replacement_negative_error):
            if negative_error and negative_error not in diagnostics:
                diagnostics.append(negative_error)
        entries.append({
            "line_id": line_id,
            "line_label": str(
                getattr(line, "original_file_name", None)
                or getattr(line, "current_text", None)
                or line_id
                or "Line"
            ),
            "project_order": project_order_by_object.get(id(line)),
            **context,
            "before_positive_prompt": before_positive,
            "after_positive_prompt": after_positive,
            "after_tokens": copy.deepcopy(example.get("after_tokens", getattr(line, "tokens", None))),
            "before_negative_prompt": before_negative,
            "after_negative_prompt": after_negative,
            "positive_added_tokens": list(example.get("added_tokens") or []),
            "positive_removed_tokens": list(example.get("removed_tokens") or []),
            "shared_tokens": list(preview.get("shared_tokens") or []),
            "matched_source_tokens": list(example.get("matched_from_tokens") or []),
            "missing_source_tokens": list(example.get("missing_from_tokens") or []),
            "negative_added_tokens": [],
            "negative_removed_tokens": [],
            "source_negative_metadata_preview": source_negative_preview,
            "replacement_negative_metadata_preview": replacement_negative_preview,
            "positive_changed": positive_changed,
            "negative_changed": negative_changed,
            "match_classification": match_classification,
            "full_match": match_classification == "full_match",
            "partial_match": match_classification == "partial_match",
            "no_match": match_classification == "no_match",
            "no_op": no_op,
            "operation": "change" if positive_changed else "skipped",
            "skip_reason": skip_reason,
            "main_image_field": image.get("field", ""),
            "main_image_path": image.get("path", ""),
            "drift_risk": _drift_risk(positive_changed, negative_changed, image),
        })

    route_summaries = []
    for route_order, summary in enumerate(selection.get("selected_route_summaries") or []):
        route_id = _clean_id(summary.get("route_handle"))
        route_entries = [entry for entry in entries if entry.get("route_id") == route_id]
        route_summaries.append({
            "route_id": route_id,
            "route_label": str(summary.get("label") or route_id or "Route"),
            "route_color": summary.get("color"),
            "route_order": route_order,
            "target_line_count": len(route_entries),
            "changed_line_count": sum(entry["positive_changed"] or entry["negative_changed"] for entry in route_entries),
            "positive_change_count": sum(entry["positive_changed"] for entry in route_entries),
            "negative_change_count": 0,
            "full_match_count": sum(entry["full_match"] for entry in route_entries),
            "partial_match_count": sum(entry["partial_match"] for entry in route_entries),
            "no_match_count": sum(entry["no_match"] for entry in route_entries),
            "no_op_count": sum(entry["no_op"] for entry in route_entries),
            "skipped_count": sum(bool(entry["skip_reason"]) for entry in route_entries),
            "blocked_count": 0,
            "drift_count": sum(
                entry["drift_risk"] not in {"no prompt change", "prompt changed, no representative image"}
                for entry in route_entries
            ),
        })

    changed_line_count = sum(entry["positive_changed"] or entry["negative_changed"] for entry in entries)
    return {
        "scope": "selected_routes",
        "signature": signature,
        "source_fingerprint": signature,
        "from_group_key": from_group_key,
        "to_group_key": to_group_key,
        "from_group_name": preview.get("from_group_name", from_group.get("name", from_group_key)),
        "to_group_name": preview.get("to_group_name", to_group.get("name", to_group_key)),
        "from_group_snapshot": copy.deepcopy(from_group),
        "to_group_snapshot": copy.deepcopy(to_group),
        "from_slot": from_slot,
        "to_slot": to_slot,
        "slot_compatible": from_slot == to_slot,
        "from_tokens": list(preview.get("from_tokens") or []),
        "to_tokens": list(preview.get("to_tokens") or []),
        "shared_tokens": list(preview.get("shared_tokens") or []),
        "tokens_to_remove": list(preview.get("tokens_to_remove") or []),
        "tokens_to_add": list(preview.get("tokens_to_add") or []),
        "already_present_to_tokens": list(preview.get("already_present_to_tokens") or []),
        "require_full_match": require_full_match,
        "selected_route_ids": list(selection.get("selected_route_ids") or []),
        "selected_route_labels": list(selection.get("selected_route_labels") or []),
        "selected_route_count": int(selection.get("selected_route_count", 0) or 0),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "target_line_count": len(entries),
        "changed_line_count": changed_line_count,
        "positive_change_count": sum(entry["positive_changed"] for entry in entries),
        "negative_change_count": 0,
        "full_match_count": sum(entry["full_match"] for entry in entries),
        "partial_match_count": sum(entry["partial_match"] for entry in entries),
        "no_match_count": sum(entry["no_match"] for entry in entries),
        "no_op_count": sum(entry["no_op"] for entry in entries),
        "skipped_count": sum(bool(entry["skip_reason"]) for entry in entries),
        "blocked_count": int(resolution.get("malformed_line_count", 0) or 0),
        "image_line_count": sum(bool(entry["main_image_path"]) for entry in entries),
        "drift_count": sum(
            entry["drift_risk"] not in {"no prompt change", "prompt changed, no representative image"}
            for entry in entries
        ),
        "route_summaries": route_summaries,
        "entries": entries,
        "diagnostics": diagnostics,
        "valid": True,
        "reason": "" if changed_line_count else "Attribute Group Swap has no changes",
        "prompt_only": True,
        "negative_prompt_semantics": "unchanged; Attribute Group negative metadata is preview-only",
    }


def _line_invariant_state(line: Any) -> dict[str, Any]:
    values = copy.deepcopy(getattr(line, "__dict__", {}))
    for field_name in _PROMPT_MUTATION_FIELDS:
        values.pop(field_name, None)
    return values


def _validate_atomic_result(source_project: Any, updated_project: Any, plan: dict[str, Any]) -> None:
    source_lines = _safe_lines(source_project)
    updated_lines = _safe_lines(updated_project)
    if len(source_lines) != len(updated_lines):
        raise RuntimeError("Attribute Group Swap changed the Project Line structure")
    changed_by_id = {
        entry["line_id"]: entry
        for entry in plan.get("entries") or []
        if not entry.get("no_op")
    }
    applied_count = 0
    for source_line, updated_line in zip(source_lines, updated_lines):
        line_id = _clean_id(getattr(source_line, "id", ""))
        if line_id != _clean_id(getattr(updated_line, "id", "")):
            raise RuntimeError("Attribute Group Swap changed Line identity or physical order")
        if _line_invariant_state(source_line) != _line_invariant_state(updated_line):
            raise RuntimeError(f"Attribute Group Swap changed non-Prompt state for Line {line_id}")
        entry = changed_by_id.get(line_id)
        if entry:
            if str(getattr(updated_line, "current_text", "") or "") != entry["after_positive_prompt"]:
                raise RuntimeError(f"Attribute Group Swap result changed before commit for Line {line_id}")
            if getattr(updated_line, "tokens", None) != entry["after_tokens"]:
                raise RuntimeError(f"Attribute Group Swap tokens changed before commit for Line {line_id}")
            if not getattr(updated_line, "edited", False):
                raise RuntimeError(f"Attribute Group Swap did not mark Line {line_id} as edited")
            applied_count += 1
        else:
            if str(getattr(updated_line, "current_text", "") or "") != str(getattr(source_line, "current_text", "") or ""):
                raise RuntimeError("Attribute Group Swap changed a non-target or no-op Line")
            if getattr(updated_line, "tokens", None) != getattr(source_line, "tokens", None):
                raise RuntimeError("Attribute Group Swap changed tokens for a non-target or no-op Line")
            if bool(getattr(updated_line, "edited", False)) != bool(getattr(source_line, "edited", False)):
                raise RuntimeError("Attribute Group Swap changed edited state for a non-target or no-op Line")
    if applied_count != int(plan.get("changed_line_count", 0) or 0):
        raise RuntimeError("Attribute Group Swap applied count did not match the preview")
    if copy.deepcopy(getattr(source_project, "attribute_groups", None)) != getattr(updated_project, "attribute_groups", None):
        raise RuntimeError("Attribute Group Swap changed the Attribute Group Library")
    if copy.deepcopy(getattr(source_project, "module_library", None)) != getattr(updated_project, "module_library", None):
        raise RuntimeError("Attribute Group Swap changed the Module Library")


def apply_selected_routes_attribute_group_swap(
    project: Any,
    selected_route_ids: Any,
    *,
    expected_signature: str,
    from_group_key: str,
    to_group_key: str,
    require_full_match: bool = False,
    project_path: str = "",
    apply_func: Callable[..., Any] = apply_attribute_group_swap,
    mutation_hook: Callable[[Any, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Apply one fresh Selected Routes plan to a clone and return it atomically."""

    current_plan = build_selected_routes_attribute_group_swap_plan(
        project,
        selected_route_ids,
        from_group_key=from_group_key,
        to_group_key=to_group_key,
        require_full_match=require_full_match,
        project_path=project_path,
    )
    if not expected_signature or current_plan.get("signature") != expected_signature:
        return {
            "applied": False,
            "stale_preview": True,
            "applied_count": 0,
            "error": "Selected Routes Attribute Group Swap preview is stale",
            "updated_project": None,
        }
    if not current_plan.get("valid") or int(current_plan.get("changed_line_count", 0) or 0) <= 0:
        return {
            "applied": False,
            "stale_preview": False,
            "applied_count": 0,
            "error": current_plan.get("reason") or "Selected Routes Attribute Group Swap has no changes",
            "updated_project": None,
        }

    try:
        working_project = copy.deepcopy(project)
        working_plan = build_selected_routes_attribute_group_swap_plan(
            working_project,
            selected_route_ids,
            from_group_key=from_group_key,
            to_group_key=to_group_key,
            require_full_match=require_full_match,
            project_path=project_path,
        )
        if working_plan.get("signature") != expected_signature:
            raise RuntimeError("Selected Routes Attribute Group Swap preview changed before apply")
        original_attribute_groups = copy.deepcopy(getattr(project, "attribute_groups", None))
        original_module_library = copy.deepcopy(getattr(project, "module_library", None))
        updated_project = apply_func(
            working_project,
            from_group_key,
            to_group_key,
            target_line_ids=list(working_plan.get("target_line_ids") or []),
            require_full_match=bool(require_full_match),
        )
        if updated_project is None:
            raise RuntimeError("Attribute Group Swap apply returned no Project")
        updated_project.attribute_groups = original_attribute_groups
        updated_project.module_library = original_module_library
        if mutation_hook:
            mutation_hook(updated_project, working_plan)
        _validate_atomic_result(project, updated_project, working_plan)
    except Exception as exc:
        return {
            "applied": False,
            "stale_preview": False,
            "applied_count": 0,
            "error": str(exc),
            "updated_project": None,
        }

    return {
        "applied": True,
        "stale_preview": False,
        "applied_count": int(working_plan.get("changed_line_count", 0) or 0),
        "error": "",
        "updated_project": updated_project,
        "selected_route_ids": list(working_plan.get("selected_route_ids") or []),
        "selected_route_labels": list(working_plan.get("selected_route_labels") or []),
        "plan": working_plan,
    }
