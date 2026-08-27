import json
import os
import re
import shutil
import tempfile
import copy
import hashlib
import errno
import time
from collections import Counter
from typing import Any, Callable, Iterable

from core.io import save_project_to_json
from core.parser import parse_prompt
from core.project import Project, PromptLine
from core.route_operations import (
    ROUTE_REMOVALS_METADATA_KEY,
    safe_record_list,
    sanitize_selected_route_ids,
)


PathExists = Callable[[str], bool]
PathResolver = Callable[[str], str]
PathStat = Callable[[str], os.stat_result]
CopyFile = Callable[[str, str], Any]
Makedirs = Callable[[str], Any]
Rename = Callable[[str, str], Any]
RemoveTree = Callable[[str], Any]
Sleep = Callable[[float], Any]
IdGenerator = Callable[[str], str]
CreatedAtProvider = Callable[[], str]

DRIFT_WARNING = (
    "Lightweight Fork materializes image references only. Prompt text is copied unchanged. "
    "Review whether displayed images still match prompt meaning before creating a fork. "
    "Run Candidate Prompt Adoption separately when needed."
)
ALL_SCOPE_CONFIRM_PHRASE = "FORK FINAL"
WINDOWS_RETRY_WINERRORS = frozenset({5, 32, 33})
WINDOWS_RETRY_DELAYS = (0.0, 0.05, 0.1, 0.2, 0.4, 0.8)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _text_hash(value: Any) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_fork_name(fork_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", _clean_text(fork_name))
    clean = clean.strip("._-")
    return clean or "lightweight_fork"


def sanitize_filename(filename: str) -> str:
    stem, extension = os.path.splitext(os.path.basename(_clean_text(filename)))
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "image"
    safe_extension = re.sub(r"[^A-Za-z0-9.]+", "", extension).lower() or ".png"
    if not safe_extension.startswith("."):
        safe_extension = f".{safe_extension}"
    return f"{safe_stem}{safe_extension}"


def _resolve_path(path: str, *, project_path: str = "", resolve_path: PathResolver | None = None) -> str:
    clean_path = _clean_text(path)
    if not clean_path:
        return ""
    if resolve_path:
        return resolve_path(clean_path) or clean_path
    if os.path.isabs(clean_path):
        return clean_path
    if project_path:
        project_dir = project_path if os.path.isdir(project_path) else os.path.dirname(project_path)
        if project_dir:
            return os.path.abspath(os.path.join(project_dir, clean_path))
    return clean_path


def _file_stat(path: str, *, path_stat: PathStat | None = None) -> dict:
    try:
        stat_result = path_stat(path) if path_stat else os.stat(path)
    except OSError:
        return {}
    return {
        "size": int(getattr(stat_result, "st_size", 0) or 0),
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", int(getattr(stat_result, "st_mtime", 0) * 1_000_000_000)) or 0),
    }


def _signature_digest(signature: dict) -> str:
    payload = json.dumps(signature or {}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_join(base_dir: str, *parts: str) -> str:
    base_real = os.path.realpath(os.path.abspath(base_dir))
    candidate = os.path.realpath(os.path.abspath(os.path.join(base_real, *parts)))
    common = os.path.commonpath([base_real, candidate])
    if common != base_real:
        raise ValueError(f"destination escapes parent: {candidate}")
    return candidate


def _planned_image_filename(planned_destination_path: str, fork_name: str) -> str:
    normalized = planned_destination_path.replace("\\", "/").strip()
    if os.path.isabs(normalized) or normalized.startswith("../") or "/../" in normalized:
        raise ValueError("planned destination path is unsafe")
    expected_prefix = f"forks/{sanitize_fork_name(fork_name)}/images/"
    if not normalized.startswith(expected_prefix):
        raise ValueError("planned destination path does not match fork layout")
    filename = normalized[len(expected_prefix):]
    if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
        raise ValueError("planned destination filename is unsafe")
    return sanitize_filename(filename)


def _relative_image_path(filename: str) -> str:
    return os.path.join("images", sanitize_filename(filename))


def _next_fork_line_id(prefix: str, used_ids: set[str], id_generator: IdGenerator | None) -> str:
    safe_prefix = re.sub(r"[^A-Za-z0-9_]+", "_", _clean_text(prefix)).strip("_") or "line"
    while True:
        candidate = id_generator(safe_prefix) if id_generator else f"{safe_prefix}_{len(used_ids) + 1:04d}"
        candidate = re.sub(r"[^A-Za-z0-9_:-]+", "_", _clean_text(candidate)).strip("_") or f"{safe_prefix}_{len(used_ids) + 1:04d}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate


def _source_line_lookup(lines: Iterable[Any]) -> dict[str, Any]:
    return {getattr(line, "id", "") or "": line for line in lines or []}


def _main_image_reference(line: Any, *, project_path: str = "", resolve_path: PathResolver | None = None) -> dict:
    for field in ("selected_candidate_path", "generated_image_path", "image_path"):
        path = _clean_text(getattr(line, field, ""))
        if path:
            return {
                "field": field,
                "path": path,
                "resolved_path": _resolve_path(path, project_path=project_path, resolve_path=resolve_path),
            }
    return {}


def _ordered_lines(lines: Iterable[Any]) -> list[Any]:
    indexed = []
    for fallback_index, line in enumerate(list(lines or [])):
        line_index = getattr(line, "current_index", None)
        sort_index = line_index if isinstance(line_index, int) else fallback_index
        indexed.append((sort_index, fallback_index, line))
    return [line for _sort_index, _fallback_index, line in sorted(indexed, key=lambda item: (item[0], item[1]))]


def _route_context_by_line_id(
    lines: Iterable[Any],
    *,
    physical_order: bool = False,
) -> dict[str, dict]:
    route_context = {}
    current_route = {}
    route_order = -1
    route_line_order = 0
    source_lines = list(lines or []) if physical_order else _ordered_lines(lines)
    for project_order, line in enumerate(source_lines):
        if getattr(line, "deleted", False):
            continue
        if getattr(line, "line_type", None) == "separator":
            route_order += 1
            route_line_order = 0
            current_route = {
                "route_id": getattr(line, "id", "") or "",
                "route_label": (
                    getattr(line, "separator_label", None)
                    or getattr(line, "current_text", "")
                    or getattr(line, "original_file_name", "")
                    or ""
                ),
                "route_color": getattr(line, "separator_color", None),
                "route_order": route_order,
            }
            continue
        if physical_order and getattr(line, "line_type", None) == "workbench":
            continue
        route_context[getattr(line, "id", "") or ""] = {
            **current_route,
            "project_order": project_order,
            "route_line_order": route_line_order,
        }
        route_line_order += 1
    return route_context


def _fork_line_list(project_or_lines: Any) -> list[Any]:
    raw_lines = getattr(project_or_lines, "prompt_lines", project_or_lines)
    if isinstance(raw_lines, (list, tuple)):
        return list(raw_lines)
    return []


def _count_fork_records(lines: Iterable[Any], field_name: str) -> tuple[int, int, int]:
    total = 0
    trashed = 0
    for line in lines:
        for record in safe_record_list(getattr(line, field_name, None)):
            if not isinstance(record, dict) or not str(record.get("path") or "").strip():
                continue
            if field_name == "gallery_variants":
                if not (
                    record.get("kind") == "gallery_variant"
                    or record.get("source") == "batch_candidate_adoption"
                    or str(record.get("id") or "").startswith("variant_")
                ):
                    continue
            total += 1
            if record.get("trashed"):
                trashed += 1
    return total, total - trashed, trashed


def resolve_selected_routes_fork_plan(
    project_or_lines: Any,
    selected_route_ids: Any,
) -> dict:
    """Build a pure, Project-order plan for the session-only Selected Routes Fork scope."""

    state = sanitize_selected_route_ids(project_or_lines, selected_route_ids)
    lines = _fork_line_list(project_or_lines)
    line_id_counts: dict[str, int] = {}
    for line in lines:
        line_id = str(getattr(line, "id", "") or "").strip()
        if line_id:
            line_id_counts[line_id] = line_id_counts.get(line_id, 0) + 1

    selected_member_ids = {
        str(getattr(line, "id", "") or "").strip()
        for block in state["selected_route_blocks"]
        for line in block.active_normal_member_lines
        if str(getattr(line, "id", "") or "").strip()
    }
    duplicate_member_ids = {
        line_id
        for line_id in selected_member_ids
        if line_id_counts.get(line_id, 0) > 1
    }
    diagnostics = list(state.get("diagnostics", []))
    diagnostics.extend(
        f"ambiguous selected Route line id: {line_id}"
        for line_id in sorted(duplicate_member_ids)
    )
    target_line_ids = [
        str(getattr(line, "id", "") or "").strip()
        for line in lines
        if (
            str(getattr(line, "id", "") or "").strip() in selected_member_ids
            and str(getattr(line, "id", "") or "").strip() not in duplicate_member_ids
            and not getattr(line, "deleted", False)
            and getattr(line, "line_type", None) not in {"separator", "workbench"}
        )
    ]

    route_summaries = [
        {key: value for key, value in summary.items() if key != "block"}
        for summary in state.get("selected_route_summaries", [])
    ]
    source_route_blocks = []
    selected_block_line_ids = set()
    route_id_by_member_id = {}
    route_order_by_id = {
        summary.get("route_handle"): index
        for index, summary in enumerate(state.get("selected_route_summaries", []))
    }
    candidate_total = 0
    candidate_active = 0
    candidate_trashed = 0
    variant_total = 0
    variant_active = 0
    variant_trashed = 0
    for block in state.get("selected_route_blocks", []):
        block_line_ids = [
            str(getattr(line, "id", "") or "").strip()
            for line in block.block_lines
            if str(getattr(line, "id", "") or "").strip()
        ]
        selected_block_line_ids.update(block_line_ids)
        for block_line_id in block_line_ids:
            route_id_by_member_id.setdefault(block_line_id, block.route_handle)
        source_route_blocks.append({
            "route_handle": block.route_handle,
            "route_label": block.separator_label,
            "route_color": getattr(block.separator, "separator_color", None),
            "route_order": route_order_by_id.get(block.route_handle),
            "line_ids": block_line_ids,
            "separator_line_id": block.route_handle,
        })
        candidate_counts = _count_fork_records(block.active_normal_member_lines, "generated_candidates")
        variant_counts = _count_fork_records(block.active_normal_member_lines, "gallery_variants")
        candidate_total += candidate_counts[0]
        candidate_active += candidate_counts[1]
        candidate_trashed += candidate_counts[2]
        variant_total += variant_counts[0]
        variant_active += variant_counts[1]
        variant_trashed += variant_counts[2]

    target_id_set = set(target_line_ids)
    output_line_plan = []
    asset_materialization_plan = []
    unresolved_main_image_count = 0
    for source_order, line in enumerate(lines):
        line_id = str(getattr(line, "id", "") or "").strip()
        if line_id not in target_id_set:
            continue
        image_reference = _main_image_reference(line)
        if not image_reference.get("path"):
            unresolved_main_image_count += 1
        output_line_plan.append({
            "source_line_id": line_id,
            "route_id": route_id_by_member_id.get(line_id, ""),
            "source_order": source_order,
            "materializable": bool(image_reference.get("path")),
            "source_field": image_reference.get("field", ""),
        })
        asset_materialization_plan.append({
            "source_line_id": line_id,
            "source_field": image_reference.get("field", ""),
            "source_image_path": image_reference.get("path", ""),
        })

    reason = ""
    if not state.get("selected_route_ids"):
        reason = "no selected Routes"
    elif not target_line_ids:
        reason = "selected Routes have no active normal Lines"

    return {
        "scope": "selected_routes",
        "selected_route_ids": list(state.get("selected_route_ids", [])),
        "resolved_route_handles": list(state.get("selected_route_ids", [])),
        "resolved_route_labels": list(state.get("selected_route_labels", [])),
        "selected_route_count": int(state.get("selected_route_count", 0) or 0),
        "selected_route_summaries": route_summaries,
        "route_summaries": route_summaries,
        "source_route_blocks": source_route_blocks,
        "retained_separator_ids": list(state.get("selected_route_ids", [])),
        "retained_source_line_ids": target_line_ids,
        "target_line_ids": target_line_ids,
        "excluded_line_ids": [
            line_id
            for line_id in selected_block_line_ids
            if line_id not in set(target_line_ids) and line_id not in set(state.get("selected_route_ids", []))
        ],
        "selected_line_count": int(state.get("selected_line_count", 0) or 0),
        "selected_main_line_count": len(target_line_ids),
        "selected_workbench_count": int(state.get("selected_workbench_count", 0) or 0),
        "selected_deleted_member_count": int(state.get("selected_deleted_member_count", 0) or 0),
        "selected_separator_count": int(state.get("selected_route_count", 0) or 0),
        "selected_normal_line_count": len(target_line_ids),
        "output_line_plan": output_line_plan,
        "asset_materialization_plan": asset_materialization_plan,
        "id_mapping_plan": {
            "strategy": "fresh_ids",
            "source_line_ids": [
                str(getattr(line, "id", "") or "")
                for line in lines
                if str(getattr(line, "id", "") or "") in selected_block_line_ids
            ],
            "scope": "selected_routes",
        },
        "retained_reference_plan": {
            "main_image_fields": ["image_path"],
            "cleared_fields": [
                "selected_candidate_path",
                "generated_image_path",
                "generated_candidates",
                "gallery_variants",
                "source_generation_info",
                "lineage_info",
            ],
        },
        "cleared_reference_diagnostics": [
            "Candidates, Gallery Variants, and transient generation references are cleared in the fork copy."
        ],
        "copied_main_image_count": len(asset_materialization_plan) - unresolved_main_image_count,
        "unresolved_main_image_count": unresolved_main_image_count,
        "output_project_path": "",
        "output_folder": "",
        "candidate_removal_count": candidate_total,
        "candidate_active_count": candidate_active,
        "candidate_trash_removal_count": candidate_trashed,
        "gallery_variant_removal_count": variant_total,
        "gallery_variant_active_count": variant_active,
        "gallery_variant_trash_removal_count": variant_trashed,
        "trash_removal_count": candidate_trashed + variant_trashed,
        "diagnostics": diagnostics,
        "valid": bool(state.get("selected_route_ids")) and bool(target_line_ids),
        "reason": reason,
    }


LIGHTWEIGHT_FORK_APPEND_TARGET_SCOPES = ("selected_route", "selected_routes")
LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY = "lightweight_fork_selected_route_id"
LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY = "_lightweight_fork_selected_route_id_widget"
LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_RESET_PENDING_KEY = (
    "_lightweight_fork_selected_route_id_widget_reset_pending"
)


def initialize_lightweight_fork_single_route_widget_state(state: Any) -> str:
    """Initialize the temporary selector widget from its durable Route state."""

    selected_route_id = str(state.get(LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY, "") or "").strip()
    state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY] = selected_route_id
    return selected_route_id


def sync_lightweight_fork_single_route_widget_state(state: Any) -> str:
    """Commit a selector change to the durable Route state."""

    selected_route_id = str(state.get(LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY, "") or "").strip()
    state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY] = selected_route_id
    return selected_route_id


def request_lightweight_fork_single_route_state_reset(state: Any) -> None:
    """Clear durable state and defer widget cleanup until the next safe render phase."""

    state.pop(LIGHTWEIGHT_FORK_SELECTED_ROUTE_STATE_KEY, None)
    state[LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_RESET_PENDING_KEY] = True


def apply_pending_lightweight_fork_single_route_widget_reset(state: Any) -> bool:
    """Clear the temporary widget before Gallery operation widgets are instantiated."""

    if not state.pop(LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_RESET_PENDING_KEY, False):
        return False
    state.pop(LIGHTWEIGHT_FORK_SELECTED_ROUTE_WIDGET_KEY, None)
    return True


def resolve_lightweight_fork_append_targets(
    project_or_lines: Any,
    *,
    scope: str,
    selected_route_id: Any = "",
    selected_route_ids: Any = None,
) -> dict:
    """Resolve Append UI targets through the existing Selected Routes plan."""

    clean_single_route_id = str(selected_route_id or "").strip()
    if isinstance(selected_route_ids, str):
        raw_selected_route_ids = [selected_route_ids]
    elif isinstance(selected_route_ids, (list, tuple)):
        raw_selected_route_ids = list(selected_route_ids)
    else:
        raw_selected_route_ids = []

    single_plan = resolve_selected_routes_fork_plan(
        project_or_lines,
        [clean_single_route_id] if clean_single_route_id else [],
    )
    selected_routes_plan = resolve_selected_routes_fork_plan(
        project_or_lines,
        raw_selected_route_ids,
    )
    clean_scope = str(scope or "").strip()
    if clean_scope not in LIGHTWEIGHT_FORK_APPEND_TARGET_SCOPES:
        if single_plan.get("valid") and single_plan.get("selected_route_ids") == [clean_single_route_id]:
            clean_scope = "selected_route"
        elif selected_routes_plan.get("valid"):
            clean_scope = "selected_routes"
        else:
            clean_scope = "selected_route"

    raw_route_ids = (
        [clean_single_route_id] if clean_scope == "selected_route" and clean_single_route_id
        else raw_selected_route_ids if clean_scope == "selected_routes"
        else []
    )
    plan = single_plan if clean_scope == "selected_route" else selected_routes_plan
    effective_route_ids = list(plan.get("selected_route_ids", []))
    valid = bool(plan.get("valid"))
    if clean_scope == "selected_route":
        valid = valid and effective_route_ids == [clean_single_route_id]
        reason = "" if valid else "Select a valid Route."
    else:
        reason = "" if valid else "Select at least one Route using the Gallery Route checkboxes."

    diagnostics = list(plan.get("diagnostics", []))
    if clean_scope == "selected_route" and clean_single_route_id and not valid:
        diagnostics.append(
            f"Selected Route is missing, deleted, ambiguous, or not an active separator: {clean_single_route_id}"
        )
    lines = _fork_line_list(project_or_lines)
    project_structure = [
        (
            str(getattr(line, "id", "") or ""),
            str(getattr(line, "line_type", "") or ""),
            bool(getattr(line, "deleted", False)),
        )
        for line in lines
    ]
    return {
        "scope": clean_scope,
        "raw_route_ids": raw_route_ids,
        "effective_route_ids": effective_route_ids,
        "selected_route_id": clean_single_route_id,
        "selected_route_plan": plan,
        "selected_route_count": int(plan.get("selected_route_count", 0) or 0),
        "target_line_ids": list(plan.get("target_line_ids", [])),
        "resolved_route_labels": list(plan.get("resolved_route_labels", [])),
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "project_structure": project_structure,
        "valid": valid,
        "reason": reason,
    }


def build_lightweight_fork_append_input_signature(
    *,
    source_project_path: str,
    destination_project_path: str,
    target_resolution: dict,
) -> tuple:
    def normalized_path(path: Any) -> str:
        clean = str(path or "").strip()
        if not clean:
            return ""
        return os.path.normcase(os.path.realpath(os.path.abspath(clean)))

    scope = str(target_resolution.get("scope") or "")
    selected_route_id = (
        str(target_resolution.get("selected_route_id") or "")
        if scope == "selected_route"
        else ""
    )
    return (
        normalized_path(source_project_path),
        normalized_path(destination_project_path),
        scope,
        selected_route_id,
        tuple(target_resolution.get("raw_route_ids", [])),
        tuple(target_resolution.get("effective_route_ids", [])),
        tuple(target_resolution.get("target_line_ids", [])),
        tuple(tuple(item) for item in target_resolution.get("project_structure", [])),
    )


def _line_label(line: Any) -> str:
    label = getattr(line, "original_file_name", None) or getattr(line, "id", None) or "Line"
    line_number = getattr(line, "original_index", None)
    if line_number is not None:
        return f"{label}:{line_number + 1}"
    return str(label)


def _destination_path(
    *,
    fork_name: str,
    source_path: str,
    index: int,
    used_filenames: set[str],
) -> str:
    source_filename = sanitize_filename(source_path)
    stem, extension = os.path.splitext(source_filename)
    base_filename = f"{int(index):04d}_{stem}{extension}"
    candidate = base_filename
    suffix = 2
    while candidate.lower() in used_filenames:
        candidate = f"{int(index):04d}_{stem}_{suffix}{extension}"
        suffix += 1
    used_filenames.add(candidate.lower())
    return os.path.join("forks", sanitize_fork_name(fork_name), "images", candidate)


def _skip_entry(line: Any, reason: str, route: dict) -> dict:
    return {
        "line_id": getattr(line, "id", "") or "",
        "line_index": getattr(line, "current_index", getattr(line, "original_index", None)),
        "display_id": _line_label(line),
        "route_id": route.get("route_id", ""),
        "route_label": route.get("route_label", ""),
        "route_color": route.get("route_color"),
        "route_order": route.get("route_order"),
        "route_line_order": route.get("route_line_order"),
        "project_order": route.get("project_order"),
        "line_type": getattr(line, "line_type", None) or "",
        "prompt_preview": _clean_text(getattr(line, "current_text", ""))[:240],
        "negative_prompt_preview": _clean_text(getattr(line, "negative_prompt", ""))[:240],
        "prompt_hash": _text_hash(getattr(line, "current_text", "")),
        "negative_prompt_hash": _text_hash(getattr(line, "negative_prompt", "")),
        "source_field": "",
        "resolved_image_path": "",
        "planned_destination_path": "",
        "materializable": False,
        "skipped_reason": reason,
    }


def build_lightweight_fork_preview_signature(
    preview: dict | None = None,
    *,
    scope: str = "",
    fork_name: str = "",
    selected_route_id: str = "",
    selected_route_ids: Iterable[str] | None = None,
    current_route_anchor_id: str = "",
    selected_line_ids: Iterable[str] | None = None,
    target_line_ids: Iterable[str] | None = None,
    entries: Iterable[dict] | None = None,
) -> dict:
    if preview:
        scope = preview.get("scope", scope)
        fork_name = preview.get("fork_name", fork_name)
        selected_route_id = preview.get("selected_route_id", selected_route_id)
        selected_route_ids = preview.get("selected_route_ids", selected_route_ids)
        current_route_anchor_id = preview.get("current_route_anchor_id", current_route_anchor_id)
        selected_line_ids = preview.get("selected_line_ids", selected_line_ids)
        target_line_ids = preview.get("target_line_ids", target_line_ids)
        entries = preview.get("entries", entries)
    selected_route_summaries = preview.get("selected_route_summaries", ()) if preview else ()
    source_route_blocks = preview.get("source_route_blocks", ()) if preview else ()
    return {
        "scope": scope or "",
        "fork_name": sanitize_fork_name(fork_name),
        "selected_route_id": selected_route_id or "",
        "selected_route_ids": tuple(route_id for route_id in (selected_route_ids or []) if route_id),
        "current_route_anchor_id": current_route_anchor_id or "",
        "selected_line_ids": tuple(line_id for line_id in (selected_line_ids or []) if line_id),
        "target_line_ids": tuple(line_id for line_id in (target_line_ids or []) if line_id),
        "selected_route_summaries": tuple(
            json.dumps(summary, sort_keys=True, default=str, ensure_ascii=False)
            for summary in (selected_route_summaries or [])
        ),
        "source_route_blocks": tuple(
            json.dumps(block, sort_keys=True, default=str, ensure_ascii=False)
            for block in (source_route_blocks or [])
        ),
        "resolved_sources": tuple(
            (
                entry.get("line_id", ""),
                entry.get("line_index", None),
                entry.get("route_id", ""),
                entry.get("route_label", ""),
                entry.get("route_color"),
                entry.get("route_order"),
                entry.get("route_line_order"),
                entry.get("project_order"),
                entry.get("source_field", ""),
                entry.get("resolved_image_path", ""),
                entry.get("planned_destination_path", ""),
                bool(entry.get("materializable")),
                entry.get("skipped_reason", ""),
                entry.get("prompt_preview", ""),
                entry.get("negative_prompt_preview", ""),
                entry.get("prompt_hash", ""),
                entry.get("negative_prompt_hash", ""),
                entry.get("source_file_size", None),
                entry.get("source_file_mtime_ns", None),
            )
            for entry in (entries or [])
        ),
    }


def build_lightweight_fork_preview(
    lines: Iterable[Any],
    *,
    fork_name: str = "lightweight_fork",
    scope: str = "all_lines",
    project_path: str = "",
    target_line_ids: Iterable[str] | None = None,
    selected_line_ids: Iterable[str] | None = None,
    selected_route_id: str = "",
    selected_route_ids: Iterable[str] | None = None,
    current_route_anchor_id: str = "",
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
    resolve_path: PathResolver | None = None,
    example_limit: int = 50,
) -> dict:
    source_lines = list(lines or [])
    selected_route_plan = None
    if scope == "selected_routes":
        selected_route_plan = resolve_selected_routes_fork_plan(source_lines, selected_route_ids)
        selected_route_ids = selected_route_plan.get("selected_route_ids", [])
        target_line_ids = selected_route_plan.get("target_line_ids", [])
    ordered_lines = source_lines if scope == "selected_routes" else _ordered_lines(source_lines)
    target_line_ids_provided = target_line_ids is not None
    target_id_set = {line_id for line_id in (target_line_ids or []) if line_id}
    route_context = _route_context_by_line_id(ordered_lines, physical_order=scope == "selected_routes")
    entries = []
    skipped_reasons = Counter()
    target_line_count = 0
    materializable_count = 0
    used_filenames = set()
    materialized_index = 1
    affected_routes = {}

    for project_order, line in enumerate(ordered_lines):
        line_id = getattr(line, "id", "") or ""
        if target_line_ids_provided and line_id not in target_id_set:
            continue
        route = route_context.get(line_id, {})
        line_type = getattr(line, "line_type", None)
        if getattr(line, "deleted", False):
            entry = _skip_entry(line, "deleted line", route)
        elif line_type == "separator":
            entry = _skip_entry(line, "Route separator", route)
        elif line_type == "workbench":
            entry = _skip_entry(line, "Workbench line", route)
        else:
            target_line_count += 1
            source_reference = _main_image_reference(line, project_path=project_path, resolve_path=resolve_path)
            source_path = source_reference.get("path", "")
            resolved_path = source_reference.get("resolved_path", "")
            if not source_path:
                entry = _skip_entry(line, "no resolved final image", route)
            elif path_exists and not path_exists(resolved_path):
                entry = _skip_entry(line, "missing resolved image file", route)
                entry["source_field"] = source_reference.get("field", "")
                entry["resolved_image_path"] = resolved_path
            else:
                destination_path = _destination_path(
                    fork_name=fork_name,
                    source_path=source_path,
                    index=materialized_index,
                    used_filenames=used_filenames,
                )
                materialized_index += 1
                materializable_count += 1
                if route.get("route_id"):
                    affected_routes[route.get("route_id", "")] = route.get("route_label", "")
                stat_info = _file_stat(resolved_path, path_stat=path_stat)
                entry = {
                    "line_id": line_id,
                    "line_index": getattr(line, "current_index", getattr(line, "original_index", None)),
                    "display_id": _line_label(line),
                    "route_id": route.get("route_id", ""),
                    "route_label": route.get("route_label", ""),
                    "route_color": route.get("route_color"),
                    "route_order": route.get("route_order"),
                    "route_line_order": route.get("route_line_order"),
                    "project_order": route.get("project_order"),
                    "line_type": line_type or "",
                    "prompt_preview": _clean_text(getattr(line, "current_text", ""))[:240],
                    "negative_prompt_preview": _clean_text(getattr(line, "negative_prompt", ""))[:240],
                    "prompt_hash": _text_hash(getattr(line, "current_text", "")),
                    "negative_prompt_hash": _text_hash(getattr(line, "negative_prompt", "")),
                    "source_field": source_reference.get("field", ""),
                    "resolved_image_path": resolved_path,
                    "planned_destination_path": destination_path,
                    "source_file_size": stat_info.get("size"),
                    "source_file_mtime_ns": stat_info.get("mtime_ns"),
                    "materializable": True,
                    "skipped_reason": "",
                }
        if not entry.get("materializable"):
            skipped_reasons[entry.get("skipped_reason") or "skipped"] += 1
        if scope == "selected_routes":
            entry["line_index"] = project_order
        entries.append(entry)

    preview = {
        "scope": scope or "all_lines",
        "fork_name": sanitize_fork_name(fork_name),
        "target_line_count": target_line_count,
        "materializable_count": materializable_count,
        "skipped_count": sum(skipped_reasons.values()),
        "skipped_reasons": dict(skipped_reasons),
        "affected_route_count": len(affected_routes),
        "affected_routes": [
            {"route_id": route_id, "route_label": route_label}
            for route_id, route_label in affected_routes.items()
        ],
        "all_scope_phrase_required": scope == "all_lines",
        "drift_warning": DRIFT_WARNING,
        "selected_route_id": selected_route_id or "",
        "selected_route_ids": tuple(route_id for route_id in (selected_route_ids or []) if route_id),
        "current_route_anchor_id": current_route_anchor_id or "",
        "selected_line_ids": tuple(line_id for line_id in (selected_line_ids or []) if line_id),
        "target_line_ids": tuple(line_id for line_id in (target_line_ids or []) if line_id),
        "entries": entries,
        "entry_count": len(entries),
        "example_limit": example_limit,
    }
    if selected_route_plan is not None:
        preview.update({
            "selected_route_count": selected_route_plan.get("selected_route_count", 0),
            "selected_route_labels": list(selected_route_plan.get("resolved_route_labels", [])),
            "selected_route_summaries": selected_route_plan.get("selected_route_summaries", []),
            "source_route_blocks": selected_route_plan.get("source_route_blocks", []),
            "selected_route_diagnostics": list(selected_route_plan.get("diagnostics", [])),
            "selected_workbench_count": selected_route_plan.get("selected_workbench_count", 0),
            "selected_deleted_member_count": selected_route_plan.get("selected_deleted_member_count", 0),
            "selected_separator_count": selected_route_plan.get("selected_separator_count", 0),
            "selected_normal_line_count": selected_route_plan.get("selected_normal_line_count", 0),
            "output_line_plan": selected_route_plan.get("output_line_plan", []),
            "asset_materialization_plan": selected_route_plan.get("asset_materialization_plan", []),
            "id_mapping_plan": selected_route_plan.get("id_mapping_plan", {}),
            "retained_reference_plan": selected_route_plan.get("retained_reference_plan", {}),
            "cleared_reference_diagnostics": selected_route_plan.get("cleared_reference_diagnostics", []),
            "copied_main_image_count": selected_route_plan.get("copied_main_image_count", 0),
            "unresolved_main_image_count": selected_route_plan.get("unresolved_main_image_count", 0),
            "output_project_path": selected_route_plan.get("output_project_path", ""),
            "output_folder": selected_route_plan.get("output_folder", ""),
            "candidate_removal_count": selected_route_plan.get("candidate_removal_count", 0),
            "candidate_trash_removal_count": selected_route_plan.get("candidate_trash_removal_count", 0),
            "gallery_variant_removal_count": selected_route_plan.get("gallery_variant_removal_count", 0),
            "gallery_variant_trash_removal_count": selected_route_plan.get("gallery_variant_trash_removal_count", 0),
            "trash_removal_count": selected_route_plan.get("trash_removal_count", 0),
        })
    preview["signature"] = build_lightweight_fork_preview_signature(preview)
    return preview


def _materializable_entries(preview: dict) -> list[dict]:
    return [entry for entry in preview.get("entries", []) if entry.get("materializable")]


def _skipped_entries(preview: dict) -> list[dict]:
    return [entry for entry in preview.get("entries", []) if not entry.get("materializable")]


def _entry_by_line_id(preview: dict) -> dict[str, dict]:
    return {entry.get("line_id", ""): entry for entry in _materializable_entries(preview)}


def _default_destination_parent(source_project_path: str, destination_parent_dir: str = "") -> str:
    if destination_parent_dir:
        return os.path.abspath(destination_parent_dir)
    if source_project_path:
        project_dir = source_project_path if os.path.isdir(source_project_path) else os.path.dirname(source_project_path)
        if project_dir:
            return os.path.abspath(project_dir)
    return os.getcwd()


def _fork_paths(destination_parent_dir: str, fork_name: str) -> dict:
    destination_parent = os.path.realpath(os.path.abspath(destination_parent_dir))
    forks_parent = _safe_join(destination_parent, "forks")
    fork_dir = _safe_join(forks_parent, sanitize_fork_name(fork_name))
    return {
        "destination_parent": destination_parent,
        "forks_parent": forks_parent,
        "fork_dir": fork_dir,
        "images_dir": _safe_join(fork_dir, "images"),
        "project_path": _safe_join(fork_dir, "project.json"),
        "manifest_path": _safe_join(fork_dir, "manifest.json"),
    }


def validate_lightweight_fork_apply(
    source_project: Project,
    *,
    source_project_path: str = "",
    stored_preview: dict,
    current_preview: dict | None = None,
    destination_parent_dir: str = "",
    fork_name: str = "",
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
) -> dict:
    path_exists = path_exists or os.path.exists
    safe_fork_name = sanitize_fork_name(fork_name or stored_preview.get("fork_name", ""))
    destination_parent = _default_destination_parent(source_project_path, destination_parent_dir)
    try:
        paths = _fork_paths(destination_parent, safe_fork_name)
    except ValueError as exc:
        return {"valid": False, "error": str(exc), "path_safety": True, "stale_preview": False}

    stored_target_line_ids = stored_preview.get("target_line_ids", ())
    current_target_line_ids = stored_target_line_ids if stored_target_line_ids else None
    selected_route_ids = stored_preview.get("selected_route_ids", ())
    if stored_preview.get("scope") == "selected_routes":
        selected_route_plan = resolve_selected_routes_fork_plan(
            getattr(source_project, "prompt_lines", []),
            selected_route_ids,
        )
        current_target_line_ids = selected_route_plan.get("target_line_ids", [])
    rebuilt_preview = build_lightweight_fork_preview(
        getattr(source_project, "prompt_lines", []),
        fork_name=safe_fork_name,
        scope=stored_preview.get("scope", "all_lines"),
        project_path=source_project_path,
        target_line_ids=current_target_line_ids,
        selected_line_ids=stored_preview.get("selected_line_ids", ()),
        selected_route_id=stored_preview.get("selected_route_id", ""),
        selected_route_ids=selected_route_ids,
        current_route_anchor_id=stored_preview.get("current_route_anchor_id", ""),
        path_exists=path_exists,
        path_stat=path_stat,
    )
    if current_preview is not None:
        provided_signature = current_preview.get("signature") or build_lightweight_fork_preview_signature(current_preview)
        rebuilt_signature = rebuilt_preview.get("signature") or build_lightweight_fork_preview_signature(rebuilt_preview)
        if provided_signature != rebuilt_signature:
            return {
                "valid": False,
                "error": "stale preview",
                "stale_preview": True,
                "current_preview": rebuilt_preview,
                "provided_signature": provided_signature,
                "current_signature": rebuilt_signature,
                **paths,
            }
    current_preview = rebuilt_preview

    stored_signature = stored_preview.get("signature") or build_lightweight_fork_preview_signature(stored_preview)
    stored_content_signature = build_lightweight_fork_preview_signature(stored_preview)
    if stored_signature != stored_content_signature:
        return {
            "valid": False,
            "error": "stale preview",
            "stale_preview": True,
            "stored_signature": stored_signature,
            "stored_content_signature": stored_content_signature,
            **paths,
        }
    current_signature = current_preview.get("signature") or build_lightweight_fork_preview_signature(current_preview)
    if stored_signature != current_signature:
        return {
            "valid": False,
            "error": "stale preview",
            "stale_preview": True,
            "current_preview": current_preview,
            "stored_signature": stored_signature,
            "current_signature": current_signature,
            **paths,
        }

    entries = _materializable_entries(stored_preview)
    if not entries:
        return {"valid": False, "error": "no materializable lines", "stale_preview": False, **paths}

    if path_exists(paths["fork_dir"]):
        return {
            "valid": False,
            "error": "destination already exists",
            "conflict": True,
            "stale_preview": False,
            **paths,
        }

    seen_destinations = set()
    for entry in entries:
        try:
            filename = _planned_image_filename(entry.get("planned_destination_path", ""), safe_fork_name)
            destination = _safe_join(paths["images_dir"], filename)
        except ValueError as exc:
            return {"valid": False, "error": str(exc), "path_safety": True, "stale_preview": False, **paths}
        destination_key = os.path.normcase(destination)
        if destination_key in seen_destinations:
            return {"valid": False, "error": "duplicate destination filename", "path_safety": True, "stale_preview": False, **paths}
        seen_destinations.add(destination_key)
        source_path = entry.get("resolved_image_path", "")
        if not source_path or not path_exists(source_path):
            return {"valid": False, "error": "source image missing", "stale_preview": True, **paths}

    return {
        "valid": True,
        "error": "",
        "stale_preview": False,
        "current_preview": current_preview,
        "preview_signature": stored_signature,
        **paths,
    }


def is_valid_lightweight_fork_name(fork_name: str) -> bool:
    clean_name = _clean_text(fork_name)
    return bool(clean_name) and clean_name not in {".", ".."} and not os.path.isabs(clean_name) and not any(
        separator in clean_name for separator in ("/", "\\")
    )


def get_lightweight_fork_create_blockers(
    *,
    fork_name: str,
    source_project_saved: bool,
    stored_preview: dict | None,
    current_preview: dict | None,
    preview_project_path: str = "",
    current_project_path: str = "",
    confirmation_checked: bool = False,
    all_scope_phrase: str = "",
    destination_conflict: bool = False,
    validation: dict | None = None,
    materialization_running: bool = False,
) -> list[str]:
    blockers = []

    def add_once(reason: str) -> None:
        if reason not in blockers:
            blockers.append(reason)

    if not is_valid_lightweight_fork_name(fork_name):
        add_once("fork name is required")
    if not source_project_saved:
        add_once("source project is not saved")
    if not stored_preview:
        add_once("no preview")
    else:
        stored_signature = stored_preview.get("signature") or build_lightweight_fork_preview_signature(stored_preview)
        current_signature = (
            current_preview.get("signature") or build_lightweight_fork_preview_signature(current_preview)
            if current_preview
            else None
        )
        if (
            not current_preview
            or stored_signature != current_signature
            or os.path.abspath(preview_project_path or "") != os.path.abspath(current_project_path or "")
        ):
            add_once("preview is stale")
        if int(stored_preview.get("materializable_count", 0) or 0) < 1:
            add_once("no materializable lines")

    if not confirmation_checked:
        add_once("confirmation required")
    if stored_preview and stored_preview.get("scope") == "all_lines" and all_scope_phrase != ALL_SCOPE_CONFIRM_PHRASE:
        add_once("FORK FINAL phrase mismatch")
    if destination_conflict:
        add_once("destination already exists")
    if validation and not validation.get("valid"):
        if validation.get("stale_preview"):
            add_once("preview is stale")
        elif validation.get("conflict"):
            add_once("destination already exists")
        else:
            add_once("core validation failed")
    if materialization_running:
        add_once("materialization running")
    return blockers


def build_lightweight_fork_project(
    source_project: Project,
    preview: dict,
    *,
    id_generator: IdGenerator | None = None,
    used_ids: Iterable[str] | None = None,
) -> tuple[Project, list[dict]]:
    materializable_by_line = _entry_by_line_id(preview)
    raw_source_lines = list(getattr(source_project, "prompt_lines", []) or [])
    source_lines = raw_source_lines if preview.get("scope") == "selected_routes" else _ordered_lines(raw_source_lines)
    fork_project = Project(source_directory="")
    fork_project.merge_by_word_only = bool(getattr(source_project, "merge_by_word_only", True))
    fork_project.module_library = copy.deepcopy(getattr(source_project, "module_library", {}) or {})
    fork_project.node_attribute_labels = copy.deepcopy(getattr(source_project, "node_attribute_labels", {}) or {})
    fork_project.custom_attribute_labels = copy.deepcopy(getattr(source_project, "custom_attribute_labels", []) or [])
    fork_project.attribute_label_usage_counts = copy.deepcopy(getattr(source_project, "attribute_label_usage_counts", {}) or {})
    fork_project.attribute_groups = copy.deepcopy(getattr(source_project, "attribute_groups", {}) or {})
    source_metadata = getattr(source_project, "project_metadata", {})
    fork_project.project_metadata = copy.deepcopy(source_metadata) if isinstance(source_metadata, dict) else {}
    fork_project.project_metadata.pop(ROUTE_REMOVALS_METADATA_KEY, None)
    fork_project.route_snapshots = []
    fork_project.line_groups = {}

    used_ids = {
        str(line_id).strip()
        for line_id in (used_ids or [])
        if str(line_id).strip()
    }
    manifest_entries = []
    pending_separator = None
    pending_separator_project_order = None
    included_separator_source_ids = set()
    line_index = 0

    for source_project_order, source_line in enumerate(source_lines):
        source_line_id = getattr(source_line, "id", "") or ""
        if getattr(source_line, "line_type", None) == "separator":
            pending_separator = source_line
            pending_separator_project_order = source_project_order
            continue
        entry = materializable_by_line.get(source_line_id)
        if not entry:
            continue

        if pending_separator is not None:
            separator_source_id = getattr(pending_separator, "id", "") or ""
            if separator_source_id and separator_source_id not in included_separator_source_ids:
                separator_id = _next_fork_line_id("separator", used_ids, id_generator)
                label = (
                    getattr(pending_separator, "separator_label", None)
                    or getattr(pending_separator, "current_text", "")
                    or getattr(pending_separator, "original_file_name", "")
                    or "Route"
                )
                fork_project.prompt_lines.append(PromptLine(
                    id=separator_id,
                    original_file_name=str(getattr(pending_separator, "original_file_name", "") or label),
                    original_index=line_index,
                    current_index=line_index,
                    original_text=str(label),
                    current_text=str(label),
                    tokens=[],
                    negative_prompt="",
                    edited=True,
                    line_type="separator",
                    separator_label=str(label),
                    separator_color=getattr(pending_separator, "separator_color", None),
                ))
                manifest_entries.append({
                    "kind": "route_separator",
                    "source_line_id": separator_source_id,
                    "source_line_index": (
                        pending_separator_project_order
                        if preview.get("scope") == "selected_routes"
                        else getattr(pending_separator, "current_index", getattr(pending_separator, "original_index", None))
                    ),
                    "fork_line_id": separator_id,
                    "route_label": str(label),
                    "route_color": getattr(pending_separator, "separator_color", None),
                    "route_order": entry.get("route_order"),
                })
                included_separator_source_ids.add(separator_source_id)
                line_index += 1

        filename = _planned_image_filename(entry.get("planned_destination_path", ""), preview.get("fork_name", ""))
        copied_relative_path = _relative_image_path(filename)
        current_text = str(getattr(source_line, "current_text", "") or "")
        negative_prompt = str(getattr(source_line, "negative_prompt", "") or "")
        fork_line_id = _next_fork_line_id("line", used_ids, id_generator)
        fork_project.prompt_lines.append(PromptLine(
            id=fork_line_id,
            original_file_name=os.path.basename(copied_relative_path),
            original_index=line_index,
            current_index=line_index,
            original_text=current_text,
            current_text=current_text,
            tokens=parse_prompt(current_text),
            negative_prompt=negative_prompt,
            image_path=copied_relative_path,
            selected_candidate_path="",
            generated_image_path="",
            generated_candidates=[],
            gallery_variants=[],
            source_generation_info={},
            lineage_info={},
            edited=False,
            deleted=False,
        ))
        manifest_entries.append({
            "kind": "materialized_line",
            "source_line_id": source_line_id,
            "source_line_index": (
                entry.get("project_order")
                if preview.get("scope") == "selected_routes"
                else getattr(source_line, "current_index", getattr(source_line, "original_index", None))
            ),
            "fork_line_id": fork_line_id,
            "fork_line_index": line_index,
            "route_id": entry.get("route_id", ""),
            "route_label": entry.get("route_label", ""),
            "route_color": entry.get("route_color"),
            "route_order": entry.get("route_order"),
            "route_line_order": entry.get("route_line_order"),
            "project_order": entry.get("project_order", entry.get("line_index")),
            "source_field": entry.get("source_field", ""),
            "source_image_path": entry.get("resolved_image_path", ""),
            "copied_image_path": copied_relative_path,
            "prompt_copied_unchanged": True,
            "negative_prompt_copied_unchanged": True,
        })
        line_index += 1

    fork_project.line_map = {line.id: line for line in fork_project.prompt_lines}
    return fork_project, manifest_entries


def build_lightweight_fork_manifest(
    *,
    source_project_path: str = "",
    destination_project_path: str = "",
    destination_manifest_path: str = "",
    preview: dict,
    fork_name: str,
    created_at: str,
    manifest_entries: list[dict],
) -> dict:
    materialized_entries = [entry for entry in manifest_entries if entry.get("kind") == "materialized_line"]
    return {
        "manifest_version": 1,
        "operation": "lightweight_fork_final_sequence",
        "created_at": created_at,
        "fork_name": sanitize_fork_name(fork_name),
        "source_project_name": os.path.basename(source_project_path) if source_project_path else "",
        "source_project_path": source_project_path or "",
        "destination_project_path": destination_project_path,
        "destination_manifest_path": destination_manifest_path,
        "scope": preview.get("scope", ""),
        "preview_signature_digest": _signature_digest(preview.get("signature", {})),
        "selected_route_ids": list(preview.get("selected_route_ids", [])),
        "selected_route_labels": list(preview.get("selected_route_labels", [])),
        "selected_route_count": preview.get("selected_route_count", 0),
        "selected_route_summaries": preview.get("selected_route_summaries", []),
        "source_route_blocks": preview.get("source_route_blocks", []),
        "target_line_count": preview.get("target_line_count", 0),
        "materialized_line_count": len(materialized_entries),
        "skipped_line_count": preview.get("skipped_count", 0),
        "skipped_reasons": preview.get("skipped_reasons", {}),
        "affected_routes": preview.get("affected_routes", []),
        "materialized_entries": materialized_entries,
        "skipped_entries": [
            {
                "source_line_id": entry.get("line_id", ""),
                "source_line_index": entry.get("line_index"),
                "route_id": entry.get("route_id", ""),
                "route_label": entry.get("route_label", ""),
                "skipped_reason": entry.get("skipped_reason", ""),
            }
            for entry in _skipped_entries(preview)
        ],
        "structure_entries": [entry for entry in manifest_entries if entry.get("kind") != "materialized_line"],
    }


def _exception_winerror(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_retryable_windows_filesystem_error(exc: BaseException) -> bool:
    if _exception_winerror(exc) in WINDOWS_RETRY_WINERRORS:
        return True
    if os.name != "nt" or not isinstance(exc, PermissionError):
        return False
    return getattr(exc, "errno", None) in {errno.EACCES, errno.EPERM, 5}


def _normalized_retry_delays(retry_delays: Iterable[float] | None) -> tuple[float, ...]:
    values = tuple(
        max(0.0, float(delay))
        for delay in (WINDOWS_RETRY_DELAYS if retry_delays is None else retry_delays)
    )
    return values or (0.0,)


def _commit_directory_with_retry(
    staging_dir: str,
    final_dir: str,
    *,
    rename: Rename,
    path_exists: PathExists,
    sleep: Sleep | None = None,
    retry_delays: Iterable[float] | None = None,
) -> dict:
    sleep = sleep or time.sleep
    delays = _normalized_retry_delays(retry_delays)
    attempts = 0
    retry_performed = False
    retryable_windows_error = False
    last_winerror = None

    for attempt_index, delay in enumerate(delays):
        if attempt_index > 0:
            sleep(delay)
        if path_exists(final_dir):
            return {
                "success": False,
                "error": "destination already exists",
                "error_kind": "destination conflict",
                "conflict": True,
                "attempts": attempts,
                "retry_performed": retry_performed,
                "retryable_windows_error": retryable_windows_error,
                "last_winerror": last_winerror,
            }
        attempts += 1
        try:
            rename(staging_dir, final_dir)
            return {
                "success": True,
                "error": "",
                "error_kind": "",
                "conflict": False,
                "attempts": attempts,
                "retry_performed": retry_performed,
                "retryable_windows_error": retryable_windows_error,
                "last_winerror": last_winerror,
            }
        except FileExistsError as exc:
            return {
                "success": False,
                "error": "destination already exists",
                "error_kind": "destination conflict",
                "conflict": True,
                "attempts": attempts,
                "retry_performed": retry_performed,
                "retryable_windows_error": retryable_windows_error,
                "last_winerror": _exception_winerror(exc),
            }
        except OSError as exc:
            last_winerror = _exception_winerror(exc)
            if not _is_retryable_windows_filesystem_error(exc):
                return {
                    "success": False,
                    "error": f"non-retryable commit error: {exc}",
                    "error_kind": "non-retryable commit error",
                    "conflict": False,
                    "attempts": attempts,
                    "retry_performed": retry_performed,
                    "retryable_windows_error": retryable_windows_error,
                    "last_winerror": last_winerror,
                }
            retryable_windows_error = True
            if attempt_index >= len(delays) - 1:
                return {
                    "success": False,
                    "error": (
                        "temporary Windows filesystem lock exhausted after "
                        f"{attempts} commit attempts: {exc}"
                    ),
                    "error_kind": "temporary Windows filesystem lock exhausted",
                    "conflict": False,
                    "attempts": attempts,
                    "retry_performed": retry_performed,
                    "retryable_windows_error": retryable_windows_error,
                    "last_winerror": last_winerror,
                }
            retry_performed = True
            continue

    raise RuntimeError("commit retry loop did not execute")


def _remove_tree_with_retry(
    directory: str,
    *,
    rmtree: RemoveTree,
    path_exists: PathExists,
    sleep: Sleep | None = None,
    retry_delays: Iterable[float] | None = None,
) -> dict:
    sleep = sleep or time.sleep
    delays = _normalized_retry_delays(retry_delays)
    attempts = 0
    retry_performed = False
    retryable_windows_error = False
    last_winerror = None

    for attempt_index, delay in enumerate(delays):
        if attempt_index > 0:
            sleep(delay)
        if not path_exists(directory):
            return {
                "success": True,
                "error": "",
                "attempts": attempts,
                "retry_performed": retry_performed,
                "retryable_windows_error": retryable_windows_error,
                "last_winerror": last_winerror,
            }
        attempts += 1
        try:
            rmtree(directory)
            return {
                "success": True,
                "error": "",
                "attempts": attempts,
                "retry_performed": retry_performed,
                "retryable_windows_error": retryable_windows_error,
                "last_winerror": last_winerror,
            }
        except OSError as exc:
            last_winerror = _exception_winerror(exc)
            if not path_exists(directory):
                return {
                    "success": True,
                    "error": "",
                    "attempts": attempts,
                    "retry_performed": retry_performed,
                    "retryable_windows_error": retryable_windows_error,
                    "last_winerror": last_winerror,
                }
            if not _is_retryable_windows_filesystem_error(exc):
                return {
                    "success": False,
                    "error": f"non-retryable cleanup error: {exc}",
                    "attempts": attempts,
                    "retry_performed": retry_performed,
                    "retryable_windows_error": retryable_windows_error,
                    "last_winerror": last_winerror,
                }
            retryable_windows_error = True
            if attempt_index >= len(delays) - 1:
                return {
                    "success": False,
                    "error": (
                        "temporary Windows filesystem lock exhausted while cleaning staging after "
                        f"{attempts} cleanup attempts: {exc}"
                    ),
                    "attempts": attempts,
                    "retry_performed": retry_performed,
                    "retryable_windows_error": retryable_windows_error,
                    "last_winerror": last_winerror,
                }
            retry_performed = True
            continue

    raise RuntimeError("cleanup retry loop did not execute")


def materialize_lightweight_fork(
    source_project: Project,
    *,
    source_project_path: str = "",
    stored_preview: dict,
    current_preview: dict | None = None,
    destination_parent_dir: str = "",
    fork_name: str = "",
    created_at_provider: CreatedAtProvider | None = None,
    id_generator: IdGenerator | None = None,
    path_exists: PathExists | None = None,
    path_stat: PathStat | None = None,
    copy_file: CopyFile | None = None,
    makedirs: Makedirs | None = None,
    rename: Rename | None = None,
    rmtree: RemoveTree | None = None,
    sleep: Sleep | None = None,
    retry_delays: Iterable[float] | None = None,
) -> dict:
    path_exists = path_exists or os.path.exists
    copy_file = copy_file or shutil.copy2
    makedirs = makedirs or os.makedirs
    rename = rename or os.rename
    rmtree = rmtree or shutil.rmtree
    sleep = sleep or time.sleep
    retry_delays = WINDOWS_RETRY_DELAYS if retry_delays is None else retry_delays
    safe_fork_name = sanitize_fork_name(fork_name or stored_preview.get("fork_name", ""))
    validation = validate_lightweight_fork_apply(
        source_project,
        source_project_path=source_project_path,
        stored_preview=stored_preview,
        current_preview=current_preview,
        destination_parent_dir=destination_parent_dir,
        fork_name=safe_fork_name,
        path_exists=path_exists,
        path_stat=path_stat,
    )
    result = {
        "success": False,
        "error": validation.get("error", ""),
        "fork_name": safe_fork_name,
        "destination_directory": validation.get("fork_dir", ""),
        "project_path": validation.get("project_path", ""),
        "manifest_path": validation.get("manifest_path", ""),
        "materialized_count": 0,
        "skipped_count": stored_preview.get("skipped_count", 0) if isinstance(stored_preview, dict) else 0,
        "skipped_reasons": stored_preview.get("skipped_reasons", {}) if isinstance(stored_preview, dict) else {},
        "affected_routes": stored_preview.get("affected_routes", []) if isinstance(stored_preview, dict) else [],
        "copied_files": [],
        "cleanup_performed": False,
        "cleanup_attempts": 0,
        "commit_attempts": 0,
        "commit_retry_performed": False,
        "retryable_windows_error": False,
        "last_winerror": None,
        "staging_directory": "",
        "preview_signature": validation.get("preview_signature") or stored_preview.get("signature", {}),
        "stale_preview": bool(validation.get("stale_preview")),
        "conflict": bool(validation.get("conflict")),
    }
    if not validation.get("valid"):
        return result

    staging_dir = ""
    try:
        makedirs(validation["forks_parent"], exist_ok=True)
        staging_dir = tempfile.mkdtemp(prefix=f".{safe_fork_name}.staging.", dir=validation["forks_parent"])
        result["staging_directory"] = staging_dir
        staging_images_dir = _safe_join(staging_dir, "images")
        makedirs(staging_images_dir, exist_ok=True)

        for entry in _materializable_entries(stored_preview):
            filename = _planned_image_filename(entry.get("planned_destination_path", ""), safe_fork_name)
            destination_path = _safe_join(staging_images_dir, filename)
            copy_file(entry.get("resolved_image_path", ""), destination_path)
            result["copied_files"].append({
                "source": entry.get("resolved_image_path", ""),
                "destination": _relative_image_path(filename),
            })

        fork_project, manifest_entries = build_lightweight_fork_project(
            source_project,
            stored_preview,
            id_generator=id_generator,
        )
        staging_project_path = _safe_join(staging_dir, "project.json")
        staging_manifest_path = _safe_join(staging_dir, "manifest.json")
        save_project_to_json(fork_project, staging_project_path)
        created_at = created_at_provider() if created_at_provider else ""
        manifest = build_lightweight_fork_manifest(
            source_project_path=source_project_path,
            destination_project_path=validation["project_path"],
            destination_manifest_path=validation["manifest_path"],
            preview=stored_preview,
            fork_name=safe_fork_name,
            created_at=created_at,
            manifest_entries=manifest_entries,
        )
        with open(staging_manifest_path, "w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, indent=2, ensure_ascii=False)

        commit_result = _commit_directory_with_retry(
            staging_dir,
            validation["fork_dir"],
            rename=rename,
            path_exists=path_exists,
            sleep=sleep,
            retry_delays=retry_delays,
        )
        result.update({
            "commit_attempts": commit_result.get("attempts", 0),
            "commit_retry_performed": bool(commit_result.get("retry_performed")),
            "retryable_windows_error": bool(commit_result.get("retryable_windows_error")),
            "last_winerror": commit_result.get("last_winerror"),
            "conflict": bool(commit_result.get("conflict")),
        })
        if not commit_result.get("success"):
            result["error"] = commit_result.get("error", "Lightweight Fork commit failed.")
            result["error_kind"] = commit_result.get("error_kind", "")
            cleanup_result = _remove_tree_with_retry(
                staging_dir,
                rmtree=rmtree,
                path_exists=path_exists,
                sleep=sleep,
                retry_delays=retry_delays,
            )
            result["cleanup_attempts"] = cleanup_result.get("attempts", 0)
            result["cleanup_performed"] = bool(cleanup_result.get("success"))
            result["retryable_windows_error"] = result["retryable_windows_error"] or bool(
                cleanup_result.get("retryable_windows_error")
            )
            result["last_winerror"] = cleanup_result.get("last_winerror") or result["last_winerror"]
            if not cleanup_result.get("success"):
                result["cleanup_error"] = cleanup_result.get("error", "staging cleanup failed")
            staging_dir = ""
            return result
        staging_dir = ""
        result.update({
            "success": True,
            "error": "",
            "materialized_count": len(_materializable_entries(stored_preview)),
        })
        return result
    except Exception as exc:
        result["error"] = str(exc)
        if staging_dir:
            try:
                cleanup_result = _remove_tree_with_retry(
                    staging_dir,
                    rmtree=rmtree,
                    path_exists=path_exists,
                    sleep=sleep,
                    retry_delays=retry_delays,
                )
                result["cleanup_attempts"] = cleanup_result.get("attempts", 0)
                result["cleanup_performed"] = bool(cleanup_result.get("success"))
                result["retryable_windows_error"] = result["retryable_windows_error"] or bool(
                    cleanup_result.get("retryable_windows_error")
                )
                result["last_winerror"] = cleanup_result.get("last_winerror") or result["last_winerror"]
                if not cleanup_result.get("success"):
                    result["cleanup_error"] = cleanup_result.get("error", "staging cleanup failed")
            except Exception as cleanup_exc:
                result["cleanup_error"] = str(cleanup_exc)
            staging_dir = ""
        return result
