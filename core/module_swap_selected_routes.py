"""Preview-first, atomic Module Swap support for session-only Selected Routes."""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable
import copy
import hashlib
import json

from core.operations import apply_module_swap, get_module_body, preview_module_swap
from core.route_operations import sanitize_selected_route_ids


MODULE_SWAP_MATCH_MODES = {"strict", "loose"}
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
            and bool(_clean_id(getattr(line, "id", "")))
            and not getattr(line, "deleted", False)
            and getattr(line, "line_type", None) not in {"separator", "workbench"}
            and _clean_id(getattr(line, "id", "")) not in duplicate_line_ids
        )
    ]
    diagnostics = _selection_diagnostics(selection)
    diagnostics.extend(
        f"ambiguous selected Route line id: {line_id}"
        for line_id in duplicate_line_ids
    )
    if malformed_line_count:
        diagnostics.append(f"ignored selected Route Lines with missing ids: {malformed_line_count}")
    return {
        "selection": selection,
        "target_lines": target_lines,
        "target_line_ids": [_clean_id(getattr(line, "id", "")) for line in target_lines],
        "route_context_by_object": selected_objects,
        "duplicate_line_ids": duplicate_line_ids,
        "malformed_line_count": malformed_line_count,
        "diagnostics": diagnostics,
    }


def _module_library(project: Any) -> tuple[dict[str, Any], list[str]]:
    raw_library = getattr(project, "module_library", None) if project is not None else None
    if not isinstance(raw_library, dict):
        return {}, ["Module Library is not a dictionary"]
    return raw_library, []


def _module_validation(
    library: dict[str, Any],
    source_module_name: str,
    target_module_name: str,
) -> list[str]:
    diagnostics = []
    if not source_module_name or not target_module_name:
        return ["Source and replacement Modules are required"]
    if source_module_name == target_module_name:
        return ["Source and replacement Modules must be different"]
    for role, name in (("source", source_module_name), ("replacement", target_module_name)):
        if name not in library:
            diagnostics.append(f"{role} Module not found: {name}")
            continue
        record = library.get(name)
        if not isinstance(record, dict):
            diagnostics.append(f"{role} Module record is malformed: {name}")
            continue
        if "body" in record and not isinstance(record.get("body"), str):
            diagnostics.append(f"{role} Module body is malformed: {name}")
    return diagnostics


def _signature_payload(
    project: Any,
    selected_route_ids: Any,
    *,
    source_module_name: str,
    target_module_name: str,
    match_mode: str,
    project_path: str = "",
    disabled_modules: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolution = _resolve_targets(project, selected_route_ids)
    selection = resolution.get("selection") or {}
    lines = _safe_lines(project)
    target_ids = set(resolution.get("target_line_ids") or [])
    library, library_diagnostics = _module_library(project)
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
        "source_module_name": source_module_name,
        "target_module_name": target_module_name,
        "match_mode": match_mode,
        "module_library": library,
        "disabled_modules": disabled_modules,
    }
    resolution["diagnostics"] = list(resolution.get("diagnostics") or []) + library_diagnostics
    return payload, resolution


def build_selected_routes_module_swap_signature(
    project: Any,
    selected_route_ids: Any,
    *,
    source_module_name: str,
    target_module_name: str,
    match_mode: str = "strict",
    project_path: str = "",
    disabled_modules: Any = None,
) -> str:
    payload, _resolution = _signature_payload(
        project,
        selected_route_ids,
        source_module_name=_clean_id(source_module_name),
        target_module_name=_clean_id(target_module_name),
        match_mode=str(match_mode or ""),
        project_path=project_path,
        disabled_modules=disabled_modules,
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


def _diff_tokens(example: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    if not example:
        return [], []
    if example.get("swap_kind") == "reference":
        removed = [example.get("removed_reference")] if example.get("removed_reference") else []
        added = [example.get("inserted_reference")] if example.get("inserted_reference") else []
        return removed, added
    return list(example.get("removed_tokens") or []), list(example.get("inserted_tokens") or [])


def _empty_plan(
    signature: str,
    resolution: dict[str, Any],
    source_module_name: str,
    target_module_name: str,
    match_mode: str,
    diagnostics: list[str],
    reason: str,
) -> dict[str, Any]:
    selection = resolution.get("selection") or {}
    return {
        "scope": "selected_routes",
        "signature": signature,
        "source_fingerprint": signature,
        "source_module_name": source_module_name,
        "target_module_name": target_module_name,
        "match_mode": match_mode,
        "selected_route_ids": list(selection.get("selected_route_ids") or []),
        "selected_route_labels": list(selection.get("selected_route_labels") or []),
        "selected_route_count": int(selection.get("selected_route_count", 0) or 0),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "target_line_count": len(resolution.get("target_line_ids") or []),
        "changed_line_count": 0,
        "positive_change_count": 0,
        "negative_change_count": 0,
        "no_op_count": 0,
        "skipped_count": 0,
        "blocked_count": len(diagnostics),
        "image_line_count": 0,
        "drift_count": 0,
        "route_summaries": [],
        "entries": [],
        "diagnostics": diagnostics,
        "valid": False,
        "reason": reason,
        "prompt_only": True,
    }


def build_selected_routes_module_swap_plan(
    project: Any,
    selected_route_ids: Any,
    *,
    source_module_name: str,
    target_module_name: str,
    match_mode: str = "strict",
    project_path: str = "",
    disabled_modules: Any = None,
    preview_func: Callable[..., dict[str, Any]] = preview_module_swap,
) -> dict[str, Any]:
    """Build a non-mutating multi-Route plan using existing Module Swap semantics."""

    source_module_name = _clean_id(source_module_name)
    target_module_name = _clean_id(target_module_name)
    match_mode = str(match_mode or "")
    payload, resolution = _signature_payload(
        project,
        selected_route_ids,
        source_module_name=source_module_name,
        target_module_name=target_module_name,
        match_mode=match_mode,
        project_path=project_path,
        disabled_modules=disabled_modules,
    )
    signature = _digest(payload)
    diagnostics = list(resolution.get("diagnostics") or [])
    selection = resolution.get("selection") or {}
    library, library_diagnostics = _module_library(project)
    diagnostics.extend(item for item in library_diagnostics if item not in diagnostics)
    module_diagnostics = _module_validation(library, source_module_name, target_module_name)
    diagnostics.extend(module_diagnostics)
    if match_mode not in MODULE_SWAP_MATCH_MODES:
        diagnostics.append(f"Unsupported Module Swap match mode: {match_mode or '(empty)'}")

    reason = ""
    if project is None:
        reason = "Project is missing"
    elif not isinstance(getattr(project, "prompt_lines", None), (list, tuple)):
        reason = "prompt_lines is not a list"
    elif not selection.get("selected_route_ids"):
        reason = "no selected Routes"
    elif resolution.get("duplicate_line_ids"):
        reason = "selected Routes contain ambiguous duplicate Line ids"
    elif not resolution.get("target_line_ids"):
        reason = "selected Routes have no Module Swap target Lines"
    elif module_diagnostics:
        reason = module_diagnostics[0]
    elif match_mode not in MODULE_SWAP_MATCH_MODES:
        reason = "unsupported Module Swap match mode"
    if reason:
        return _empty_plan(
            signature,
            resolution,
            source_module_name,
            target_module_name,
            match_mode,
            diagnostics,
            reason,
        )

    try:
        preview_project = copy.deepcopy(project)
        preview = preview_func(
            preview_project,
            source_module_name,
            target_module_name,
            target_line_ids=list(resolution["target_line_ids"]),
            match_mode=match_mode,
            example_limit=1000000,
        )
    except Exception as exc:
        diagnostics.append(f"Module Swap preview failed: {exc}")
        return _empty_plan(
            signature,
            resolution,
            source_module_name,
            target_module_name,
            match_mode,
            diagnostics,
            "Module Swap preview failed",
        )

    if not preview.get("source_tokens") or not preview.get("target_tokens"):
        diagnostics.append("Source or replacement Module has no usable body tokens")
        return _empty_plan(
            signature,
            resolution,
            source_module_name,
            target_module_name,
            match_mode,
            diagnostics,
            "Source or replacement Module is empty",
        )

    example_by_id = {
        _clean_id(example.get("line_id")): example
        for example in preview.get("examples") or []
        if isinstance(example, dict) and _clean_id(example.get("line_id"))
    }
    context_by_object = resolution.get("route_context_by_object") or {}
    project_order_by_object = {id(line): index for index, line in enumerate(_safe_lines(project))}
    entries = []
    for line in resolution.get("target_lines") or []:
        line_id = _clean_id(getattr(line, "id", ""))
        context = context_by_object.get(id(line), {})
        example = example_by_id.get(line_id)
        before_positive = str(getattr(line, "current_text", "") or "")
        after_positive = str(example.get("after") if example else before_positive)
        before_negative = str(getattr(line, "negative_prompt", "") or "")
        after_negative = before_negative
        positive_changed = after_positive != before_positive
        negative_changed = after_negative != before_negative
        removed_tokens, added_tokens = _diff_tokens(example)
        image = _main_image_reference(line)
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
            "after_tokens": (
                copy.deepcopy(example.get("after_tokens") or [])
                if example
                else copy.deepcopy(getattr(line, "tokens", None))
            ),
            "before_negative_prompt": before_negative,
            "after_negative_prompt": after_negative,
            "positive_added_tokens": added_tokens,
            "positive_removed_tokens": removed_tokens,
            "negative_added_tokens": [],
            "negative_removed_tokens": [],
            "positive_changed": positive_changed,
            "negative_changed": negative_changed,
            "no_op": not positive_changed and not negative_changed,
            "operation": "change" if positive_changed or negative_changed else "no_op",
            "skip_reason": "" if positive_changed or negative_changed else "source Module not matched",
            "match_count": int(example.get("matched_count", 0) or 0) if example else 0,
            "swap_kind": example.get("swap_kind", "") if example else "",
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
            "changed_line_count": sum(not entry["no_op"] for entry in route_entries),
            "positive_change_count": sum(entry["positive_changed"] for entry in route_entries),
            "negative_change_count": sum(entry["negative_changed"] for entry in route_entries),
            "no_op_count": sum(entry["no_op"] for entry in route_entries),
            "skipped_count": sum(bool(entry["skip_reason"]) for entry in route_entries),
            "blocked_count": 0,
            "drift_count": sum(
                entry["drift_risk"] not in {"no prompt change", "prompt changed, no representative image"}
                for entry in route_entries
            ),
        })

    changed_line_count = sum(not entry["no_op"] for entry in entries)
    return {
        "scope": "selected_routes",
        "signature": signature,
        "source_fingerprint": signature,
        "source_module_name": source_module_name,
        "target_module_name": target_module_name,
        "source_module_snapshot": copy.deepcopy(library.get(source_module_name)),
        "target_module_snapshot": copy.deepcopy(library.get(target_module_name)),
        "source_module_body": get_module_body(copy.deepcopy(library), source_module_name),
        "target_module_body": get_module_body(copy.deepcopy(library), target_module_name),
        "match_mode": match_mode,
        "selected_route_ids": list(selection.get("selected_route_ids") or []),
        "selected_route_labels": list(selection.get("selected_route_labels") or []),
        "selected_route_count": int(selection.get("selected_route_count", 0) or 0),
        "target_line_ids": list(resolution.get("target_line_ids") or []),
        "target_line_count": len(entries),
        "changed_line_count": changed_line_count,
        "positive_change_count": sum(entry["positive_changed"] for entry in entries),
        "negative_change_count": sum(entry["negative_changed"] for entry in entries),
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
        "reason": "" if changed_line_count else "Module Swap has no changes",
        "prompt_only": True,
        "negative_prompt_semantics": "unchanged by current Module Swap",
    }


def _line_invariant_state(line: Any) -> dict[str, Any]:
    values = copy.deepcopy(getattr(line, "__dict__", {}))
    for field_name in _PROMPT_MUTATION_FIELDS:
        values.pop(field_name, None)
    return values


def _validate_atomic_result(
    source_project: Any,
    updated_project: Any,
    plan: dict[str, Any],
) -> None:
    source_lines = _safe_lines(source_project)
    updated_lines = _safe_lines(updated_project)
    if len(source_lines) != len(updated_lines):
        raise RuntimeError("Module Swap changed the Project Line structure")
    changed_by_id = {
        entry["line_id"]: entry
        for entry in plan.get("entries") or []
        if not entry.get("no_op")
    }
    applied_count = 0
    for source_line, updated_line in zip(source_lines, updated_lines):
        if _clean_id(getattr(source_line, "id", "")) != _clean_id(getattr(updated_line, "id", "")):
            raise RuntimeError("Module Swap changed Line identity or physical order")
        if _line_invariant_state(source_line) != _line_invariant_state(updated_line):
            raise RuntimeError(f"Module Swap changed non-Prompt state for Line {_clean_id(getattr(source_line, 'id', ''))}")
        entry = changed_by_id.get(_clean_id(getattr(source_line, "id", "")))
        if entry:
            if str(getattr(updated_line, "current_text", "") or "") != entry["after_positive_prompt"]:
                raise RuntimeError(f"Module Swap result changed before commit for Line {entry['line_id']}")
            if getattr(updated_line, "tokens", None) != entry["after_tokens"]:
                raise RuntimeError(f"Module Swap tokens changed before commit for Line {entry['line_id']}")
            if not getattr(updated_line, "edited", False):
                raise RuntimeError(f"Module Swap did not mark Line {entry['line_id']} as edited")
            if str(getattr(updated_line, "negative_prompt", "") or "") != entry["after_negative_prompt"]:
                raise RuntimeError(f"Module Swap changed negative Prompt unexpectedly for Line {entry['line_id']}")
            applied_count += 1
        else:
            if str(getattr(updated_line, "current_text", "") or "") != str(getattr(source_line, "current_text", "") or ""):
                raise RuntimeError("Module Swap changed a non-target or no-op Line")
            if getattr(updated_line, "tokens", None) != getattr(source_line, "tokens", None):
                raise RuntimeError("Module Swap changed tokens for a non-target or no-op Line")
            if bool(getattr(updated_line, "edited", False)) != bool(getattr(source_line, "edited", False)):
                raise RuntimeError("Module Swap changed edited state for a non-target or no-op Line")
    if applied_count != int(plan.get("changed_line_count", 0) or 0):
        raise RuntimeError("Module Swap applied count did not match the preview")
    if copy.deepcopy(getattr(source_project, "module_library", None)) != getattr(updated_project, "module_library", None):
        raise RuntimeError("Module Swap changed the Module Library")


def apply_selected_routes_module_swap(
    project: Any,
    selected_route_ids: Any,
    *,
    expected_signature: str,
    source_module_name: str,
    target_module_name: str,
    match_mode: str = "strict",
    project_path: str = "",
    disabled_modules: Any = None,
    apply_func: Callable[..., Any] = apply_module_swap,
    mutation_hook: Callable[[Any, dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Apply one fresh Selected Routes plan to a clone and return it atomically."""

    current_plan = build_selected_routes_module_swap_plan(
        project,
        selected_route_ids,
        source_module_name=source_module_name,
        target_module_name=target_module_name,
        match_mode=match_mode,
        project_path=project_path,
        disabled_modules=disabled_modules,
    )
    if not expected_signature or current_plan.get("signature") != expected_signature:
        return {
            "applied": False,
            "stale_preview": True,
            "applied_count": 0,
            "error": "Selected Routes Module Swap preview is stale",
            "updated_project": None,
        }
    if not current_plan.get("valid") or int(current_plan.get("changed_line_count", 0) or 0) <= 0:
        return {
            "applied": False,
            "stale_preview": False,
            "applied_count": 0,
            "error": current_plan.get("reason") or "Selected Routes Module Swap has no changes",
            "updated_project": None,
        }

    try:
        working_project = copy.deepcopy(project)
        working_plan = build_selected_routes_module_swap_plan(
            working_project,
            selected_route_ids,
            source_module_name=source_module_name,
            target_module_name=target_module_name,
            match_mode=match_mode,
            project_path=project_path,
            disabled_modules=disabled_modules,
        )
        if working_plan.get("signature") != expected_signature:
            raise RuntimeError("Selected Routes Module Swap preview changed before apply")
        original_module_library = copy.deepcopy(getattr(project, "module_library", None))
        updated_project = apply_func(
            working_project,
            source_module_name,
            target_module_name,
            target_line_ids=list(working_plan.get("target_line_ids") or []),
            match_mode=match_mode,
        )
        if updated_project is None:
            raise RuntimeError("Module Swap apply returned no Project")
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
