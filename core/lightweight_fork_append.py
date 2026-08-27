import copy
import dataclasses
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from core.graph_builder import build_graph
from core.io import load_project_from_json
from core.lightweight_fork import (
    WINDOWS_RETRY_DELAYS,
    _destination_path,
    _is_retryable_windows_filesystem_error,
    _planned_image_filename,
    _remove_tree_with_retry,
    _safe_join,
    _signature_digest,
    build_lightweight_fork_preview,
    build_lightweight_fork_project,
)
from core.route_operations import sanitize_selected_route_ids


MANIFEST_OPERATION = "lightweight_fork_final_sequence"
SUPPORTED_MANIFEST_VERSION = 1


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_lightweight_fork_path(path: str) -> str:
    clean = _clean(path)
    if not clean:
        return ""
    return os.path.normcase(os.path.realpath(os.path.abspath(clean)))


_normalized_path = normalize_lightweight_fork_path


def _same_path(left: str, right: str) -> bool:
    return bool(_normalized_path(left)) and _normalized_path(left) == _normalized_path(right)


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_stat(path: str) -> dict:
    stat_result = os.stat(path)
    return {
        "size": int(stat_result.st_size),
        "mtime_ns": int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
    }


def _safe_json_load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _safe_record_list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _line_ids_from_raw_project(raw_project: dict) -> tuple[list[str], list[str]]:
    line_ids = []
    malformed = []
    for index, record in enumerate(_safe_record_list(raw_project.get("prompt_lines"))):
        if not isinstance(record, dict):
            malformed.append(f"malformed PromptLine record at index {index}")
            continue
        line_id = _clean(record.get("id"))
        if not line_id:
            malformed.append(f"missing PromptLine id at index {index}")
            continue
        line_ids.append(line_id)
    duplicates = sorted({line_id for line_id in line_ids if line_ids.count(line_id) > 1})
    malformed.extend(f"duplicate existing Fork Line id: {line_id}" for line_id in duplicates)
    return line_ids, malformed


def get_materialized_route_ids_from_manifest(manifest: dict) -> tuple[set[str], list[str]]:
    route_ids = set()
    diagnostics = []
    has_materialization_evidence = False

    def add_entries(values: Any) -> None:
        nonlocal has_materialization_evidence
        if isinstance(values, (list, tuple)):
            has_materialization_evidence = True
        for record in _safe_record_list(values):
            if isinstance(record, dict):
                route_id = _clean(record.get("route_id") or record.get("route_handle"))
                if route_id:
                    route_ids.add(route_id)

    def add_structure(values: Any) -> None:
        nonlocal has_materialization_evidence
        if isinstance(values, (list, tuple)):
            has_materialization_evidence = True
        for record in _safe_record_list(values):
            if not isinstance(record, dict) or record.get("kind") != "route_separator":
                continue
            route_id = _clean(
                record.get("source_line_id")
                or record.get("route_id")
                or record.get("route_handle")
            )
            if route_id:
                route_ids.add(route_id)

    add_entries(manifest.get("materialized_entries"))
    add_structure(manifest.get("structure_entries"))
    top_materialized = _safe_record_list(manifest.get("materialized_entries"))
    top_structure_route_ids = {
        _clean(record.get("source_line_id") or record.get("route_id") or record.get("route_handle"))
        for record in _safe_record_list(manifest.get("structure_entries"))
        if isinstance(record, dict) and record.get("kind") == "route_separator"
    }
    top_materialized_route_ids = {
        _clean(record.get("route_id") or record.get("route_handle"))
        for record in top_materialized
        if isinstance(record, dict)
    }
    if (
        _safe_record_list(manifest.get("selected_route_ids"))
        and top_materialized
        and not (top_structure_route_ids | top_materialized_route_ids) - {""}
    ):
        diagnostics.append(
            "existing Fork manifest materialized Routes are ambiguous"
        )

    for append_index, append_record in enumerate(_safe_record_list(manifest.get("append_history"))):
        if not isinstance(append_record, dict):
            continue
        add_entries(append_record.get("materialized_entries"))
        add_structure(append_record.get("structure_entries"))
        append_materialized = _safe_record_list(append_record.get("materialized_entries"))
        append_route_ids = {
            _clean(record.get("route_id") or record.get("route_handle"))
            for record in append_materialized
            if isinstance(record, dict)
        }
        append_route_ids.update(
            _clean(record.get("source_line_id") or record.get("route_id") or record.get("route_handle"))
            for record in _safe_record_list(append_record.get("structure_entries"))
            if isinstance(record, dict) and record.get("kind") == "route_separator"
        )
        if (
            _safe_record_list(append_record.get("selected_route_ids"))
            and append_materialized
            and not append_route_ids - {""}
        ):
            diagnostics.append(
                f"append_history[{append_index}] materialized Routes are ambiguous"
            )

    selection_metadata_present = bool(
        _safe_record_list(manifest.get("selected_route_ids"))
        or _safe_record_list(manifest.get("source_route_blocks"))
    )
    if selection_metadata_present and not has_materialization_evidence:
        diagnostics.append(
            "existing Fork manifest does not identify materialized Routes"
        )
    return route_ids, _unique_diagnostics(diagnostics)


_route_ids_from_manifest = get_materialized_route_ids_from_manifest


def _image_inventory(images_dir: str) -> tuple[list[dict], list[str]]:
    inventory = []
    diagnostics = []
    if not os.path.isdir(images_dir):
        diagnostics.append("existing Fork images directory is missing")
        return inventory, diagnostics
    images_root = _normalized_path(images_dir)
    for filename in sorted(os.listdir(images_dir), key=str.lower):
        path = os.path.join(images_dir, filename)
        if not os.path.isfile(path):
            continue
        if os.path.commonpath([images_root, _normalized_path(path)]) != images_root:
            diagnostics.append(f"existing image escapes Fork images directory: {filename}")
            continue
        stat_info = _file_stat(path)
        inventory.append({"filename": filename, **stat_info})
    return inventory, diagnostics


def load_existing_fork_snapshot(existing_fork_project_path: str) -> dict:
    """Load and validate an existing Lightweight Fork without mutating it."""

    project_path = _normalized_path(existing_fork_project_path)
    result = {
        "valid": False,
        "reason": "",
        "diagnostics": [],
        "project_path": project_path,
        "fork_dir": "",
        "images_dir": "",
        "manifest_path": "",
        "project": None,
        "project_raw": {},
        "manifest": {},
        "existing_route_ids": [],
        "existing_line_ids": [],
        "image_inventory": [],
    }
    if not project_path or not os.path.isfile(project_path):
        result["reason"] = "existing Fork project.json is missing"
        return result
    if os.path.basename(project_path).lower() != "project.json":
        result["reason"] = "select the existing Fork project.json"
        return result

    fork_dir = _normalized_path(os.path.dirname(project_path))
    try:
        expected_project_path = _safe_join(fork_dir, "project.json")
        images_dir = _safe_join(fork_dir, "images")
        manifest_path = _safe_join(fork_dir, "manifest.json")
    except (OSError, ValueError) as exc:
        result["reason"] = f"unsafe existing Fork path: {exc}"
        return result
    result.update({"fork_dir": fork_dir, "images_dir": images_dir, "manifest_path": manifest_path})
    if not _same_path(project_path, expected_project_path):
        result["reason"] = "existing Fork project path escapes its directory"
        return result
    if not os.path.isfile(manifest_path):
        result["reason"] = "existing Fork manifest.json is missing"
        return result

    try:
        raw_project = _safe_json_load(project_path)
        manifest = _safe_json_load(manifest_path)
        project = load_project_from_json(project_path)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, json.JSONDecodeError) as exc:
        result["reason"] = f"existing Fork could not be loaded: {exc}"
        return result
    if not isinstance(raw_project, dict):
        result["reason"] = "existing Fork project.json is malformed"
        return result
    if not isinstance(manifest, dict):
        result["reason"] = "existing Fork manifest.json is malformed"
        return result
    if manifest.get("operation") != MANIFEST_OPERATION:
        result["reason"] = "selected Project is not a Lightweight Fork"
        return result
    if manifest.get("manifest_version") != SUPPORTED_MANIFEST_VERSION:
        result["reason"] = "unsupported Lightweight Fork manifest version"
        return result
    if "append_history" in manifest and not isinstance(manifest.get("append_history"), list):
        result["reason"] = "existing Fork append_history is malformed"
        return result
    for field_name in (
        "selected_route_ids",
        "selected_route_labels",
        "source_route_blocks",
        "materialized_entries",
        "structure_entries",
        "skipped_entries",
    ):
        if field_name in manifest and not isinstance(manifest.get(field_name), list):
            result["reason"] = f"existing Fork {field_name} is malformed"
            return result
    if not _clean(manifest.get("source_project_path")):
        result["reason"] = "existing Fork source_project_path is missing"
        return result

    line_ids, line_diagnostics = _line_ids_from_raw_project(raw_project)
    materialized_route_ids, materialization_diagnostics = get_materialized_route_ids_from_manifest(manifest)
    inventory, image_diagnostics = _image_inventory(images_dir)
    diagnostics = line_diagnostics + materialization_diagnostics + image_diagnostics
    result.update({
        "project": project,
        "project_raw": raw_project,
        "manifest": manifest,
        "existing_route_ids": sorted(materialized_route_ids),
        "existing_line_ids": line_ids,
        "image_inventory": inventory,
        "project_digest": _file_digest(project_path),
        "manifest_digest": _file_digest(manifest_path),
        "diagnostics": diagnostics,
        "existing_route_count": sum(
            1 for record in _safe_record_list(raw_project.get("prompt_lines"))
            if isinstance(record, dict) and record.get("line_type") == "separator"
        ),
        "existing_line_count": len(line_ids),
        "existing_image_count": len(inventory),
        "append_history_count": len(_safe_record_list(manifest.get("append_history"))),
    })
    if diagnostics:
        result["reason"] = diagnostics[0]
        return result
    result["valid"] = True
    return result


def _next_image_sequence(inventory: Iterable[dict]) -> int:
    maximum = 0
    for record in inventory or []:
        match = re.match(r"^(\d+)_", _clean(record.get("filename")))
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum + 1


def _unique_diagnostics(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(_clean(value) for value in values if _clean(value)))


def _selected_route_diagnostics(
    source_project: Any,
    selected_route_ids: Iterable[str],
    base_preview: dict,
) -> tuple[list[str], list[str]]:
    state = sanitize_selected_route_ids(source_project, selected_route_ids)
    warnings = []
    fatal = []
    for route_id in state.get("removed_missing_ids", []):
        warnings.append(f"missing selected Route excluded: {route_id or '<empty>'}")
    for route_id in state.get("removed_deleted_ids", []):
        warnings.append(f"deleted selected Route excluded: {route_id}")
    for route_id in state.get("removed_non_separator_ids", []):
        warnings.append(f"non-separator selected id excluded: {route_id}")

    lines = getattr(source_project, "prompt_lines", [])
    line_ids = [
        _clean(getattr(line, "id", ""))
        for line in lines
    ] if isinstance(lines, (list, tuple)) else []
    ambiguous_ids = {
        line_id for line_id in line_ids if line_id and line_ids.count(line_id) > 1
    }
    for route_id in state.get("removed_duplicate_ids", []):
        if route_id in ambiguous_ids:
            warnings.append(f"ambiguous selected Route excluded: {route_id}")
        else:
            warnings.append(f"duplicate selected Route ignored: {route_id}")

    for diagnostic in base_preview.get("selected_route_diagnostics", []):
        clean_diagnostic = _clean(diagnostic)
        if clean_diagnostic.startswith("ambiguous selected Route line id:"):
            fatal.append(clean_diagnostic)
        elif clean_diagnostic in {"prompt_lines are missing", "prompt_lines is not a list"}:
            fatal.append(clean_diagnostic)
        else:
            warnings.append(clean_diagnostic)

    selected_handles = set(base_preview.get("selected_route_ids", []))
    for block in state.get("selected_route_blocks", []):
        if _clean(getattr(block, "route_handle", "")) not in selected_handles:
            continue
        for line in getattr(block, "block_lines", ()):
            if not _clean(getattr(line, "id", "")):
                fatal.append(
                    f"malformed source Line in selected Route: {block.route_handle}"
                )
                break
    return _unique_diagnostics(warnings), _unique_diagnostics(fatal)


def _append_signature(preview: dict) -> dict:
    return {
        "source_project_path": preview.get("source_project_path", ""),
        "source_project_digest": preview.get("source_project_digest", ""),
        "source_preview_signature": preview.get("source_preview_signature", {}),
        "existing_fork_project_path": preview.get("existing_fork_project_path", ""),
        "existing_project_digest": preview.get("existing_project_digest", ""),
        "existing_manifest_digest": preview.get("existing_manifest_digest", ""),
        "existing_image_inventory": tuple(
            (item.get("filename"), item.get("size"), item.get("mtime_ns"))
            for item in preview.get("existing_image_inventory", [])
        ),
        "existing_line_ids": tuple(preview.get("existing_line_ids", [])),
        "selected_route_ids": tuple(preview.get("selected_route_ids", [])),
        "appendable_route_ids": tuple(preview.get("appendable_route_ids", [])),
        "already_materialized_route_ids": tuple(preview.get("already_materialized_route_ids", [])),
        "blocked_route_ids": tuple(preview.get("blocked_route_ids", [])),
        "warning_diagnostics": tuple(preview.get("warning_diagnostics", [])),
        "fatal_diagnostics": tuple(preview.get("fatal_diagnostics", [])),
        "planned_entries": tuple(
            (
                entry.get("line_id", ""),
                entry.get("route_id", ""),
                entry.get("prompt_hash", ""),
                entry.get("negative_prompt_hash", ""),
                entry.get("source_field", ""),
                entry.get("resolved_image_path", ""),
                entry.get("source_file_size"),
                entry.get("source_file_mtime_ns"),
                entry.get("planned_destination_path", ""),
                bool(entry.get("materializable")),
                entry.get("skipped_reason", ""),
            )
            for entry in preview.get("entries", [])
        ),
    }


def build_lightweight_fork_append_preview(
    source_project: Any,
    *,
    source_project_path: str,
    selected_route_ids: Iterable[str],
    existing_fork_project_path: str,
    existing_snapshot: dict | None = None,
    current_open_project_path: str = "",
) -> dict:
    """Build a read-only append plan for Selected Routes and an existing Fork."""

    snapshot = existing_snapshot or load_existing_fork_snapshot(existing_fork_project_path)
    source_path = _normalized_path(source_project_path)
    manifest = snapshot.get("manifest") if isinstance(snapshot, dict) else {}
    manifest = manifest if isinstance(manifest, dict) else {}
    fork_name = _clean(manifest.get("fork_name")) or os.path.basename(snapshot.get("fork_dir", ""))
    base_preview = build_lightweight_fork_preview(
        getattr(source_project, "prompt_lines", []),
        fork_name=fork_name,
        scope="selected_routes",
        project_path=source_path,
        selected_route_ids=selected_route_ids,
        path_exists=os.path.exists,
        path_stat=os.stat,
    )
    warning_diagnostics, source_fatal_diagnostics = _selected_route_diagnostics(
        source_project,
        selected_route_ids,
        base_preview,
    )
    existing_route_ids = set(snapshot.get("existing_route_ids", []))
    materializable_route_ids = {
        _clean(entry.get("route_id"))
        for entry in base_preview.get("entries", [])
        if entry.get("materializable") and _clean(entry.get("route_id"))
    }
    selected_ids = list(base_preview.get("selected_route_ids", []))
    already_ids = [route_id for route_id in selected_ids if route_id in existing_route_ids]
    appendable_ids = [
        route_id for route_id in selected_ids
        if route_id not in existing_route_ids and route_id in materializable_route_ids
    ]
    blocked_ids = [
        route_id for route_id in selected_ids
        if route_id not in existing_route_ids and route_id not in materializable_route_ids
    ]
    appendable_set = set(appendable_ids)
    entries = [
        copy.deepcopy(entry)
        for entry in base_preview.get("entries", [])
        if _clean(entry.get("route_id")) in appendable_set
    ]
    used_filenames = {
        _clean(item.get("filename")).lower()
        for item in snapshot.get("image_inventory", [])
        if _clean(item.get("filename"))
    }
    next_sequence = _next_image_sequence(snapshot.get("image_inventory", []))
    sequence = next_sequence
    for entry in entries:
        if not entry.get("materializable"):
            continue
        planned = _destination_path(
            fork_name=fork_name,
            source_path=entry.get("resolved_image_path", ""),
            index=sequence,
            used_filenames=used_filenames,
        )
        entry["planned_destination_path"] = planned
        entry["planned_destination_filename"] = _planned_image_filename(planned, fork_name)
        sequence += 1

    route_summary_lookup = {
        _clean(summary.get("route_handle")): copy.deepcopy(summary)
        for summary in base_preview.get("selected_route_summaries", [])
        if isinstance(summary, dict)
    }
    route_summaries = []
    for route_id in selected_ids:
        summary = route_summary_lookup.get(route_id, {"route_handle": route_id})
        source_route_entries = [
            entry for entry in base_preview.get("entries", []) if entry.get("route_id") == route_id
        ]
        planned_route_entries = [entry for entry in entries if entry.get("route_id") == route_id]
        status = (
            "already_materialized" if route_id in already_ids
            else "appendable" if route_id in appendable_ids
            else "blocked"
        )
        summary.update({
            "status": status,
            "materializable_line_count": sum(1 for entry in source_route_entries if entry.get("materializable")),
            "skipped_line_count": sum(1 for entry in source_route_entries if not entry.get("materializable")),
            "planned_image_filenames": [
                entry.get("planned_destination_filename", "")
                for entry in planned_route_entries if entry.get("materializable")
            ],
        })
        route_summaries.append(summary)

    manifest_source_path = _clean(manifest.get("source_project_path"))
    source_match = bool(source_path and manifest_source_path and _same_path(source_path, manifest_source_path))
    currently_open = bool(current_open_project_path and _same_path(existing_fork_project_path, current_open_project_path))
    fatal_diagnostics = list(snapshot.get("diagnostics", []))
    if not snapshot.get("valid") and snapshot.get("reason"):
        fatal_diagnostics.append(snapshot.get("reason"))
    if not source_path or not os.path.isfile(source_path):
        fatal_diagnostics.append("source Project must be saved before append")
    if snapshot.get("valid") and not source_match:
        fatal_diagnostics.append("This Fork was created from a different source Project.")
    if currently_open:
        fatal_diagnostics.append("The selected Fork is currently open.")
    fatal_diagnostics.extend(source_fatal_diagnostics)
    if not selected_ids:
        fatal_diagnostics.append("no valid selected Routes")
    warning_diagnostics = _unique_diagnostics(warning_diagnostics)
    fatal_diagnostics = _unique_diagnostics(fatal_diagnostics)
    diagnostics = warning_diagnostics + fatal_diagnostics

    source_route_blocks = [
        copy.deepcopy(block)
        for block in base_preview.get("source_route_blocks", [])
        if _clean(block.get("route_handle")) in appendable_set
    ]
    materializable_count = sum(1 for entry in entries if entry.get("materializable"))
    skipped_count = sum(1 for entry in entries if not entry.get("materializable"))
    preview = {
        "operation": "append_selected_routes_to_existing_fork",
        "scope": "selected_routes",
        "valid": not fatal_diagnostics,
        "reason": fatal_diagnostics[0] if fatal_diagnostics else "",
        "diagnostics": diagnostics,
        "warning_diagnostics": warning_diagnostics,
        "fatal_diagnostics": fatal_diagnostics,
        "source_project_path": source_path,
        "source_project_digest": _file_digest(source_path) if source_path and os.path.isfile(source_path) else "",
        "source_preview_signature": base_preview.get("signature", {}),
        "existing_fork_project_path": snapshot.get("project_path", ""),
        "existing_fork_directory": snapshot.get("fork_dir", ""),
        "existing_fork_manifest_path": snapshot.get("manifest_path", ""),
        "existing_project_digest": snapshot.get("project_digest", ""),
        "existing_manifest_digest": snapshot.get("manifest_digest", ""),
        "existing_image_inventory": copy.deepcopy(snapshot.get("image_inventory", [])),
        "existing_line_ids": list(snapshot.get("existing_line_ids", [])),
        "manifest_version": manifest.get("manifest_version"),
        "fork_name": fork_name,
        "source_match": source_match,
        "currently_open": currently_open,
        "existing_route_count": snapshot.get("existing_route_count", 0),
        "existing_line_count": snapshot.get("existing_line_count", 0),
        "existing_image_count": snapshot.get("existing_image_count", 0),
        "append_history_count": snapshot.get("append_history_count", 0),
        "selected_route_ids": selected_ids,
        "selected_route_labels": list(base_preview.get("selected_route_labels", [])),
        "selected_route_count": len(selected_ids),
        "appendable_route_ids": appendable_ids,
        "already_materialized_route_ids": already_ids,
        "blocked_route_ids": blocked_ids,
        "appendable_route_count": len(appendable_ids),
        "already_materialized_route_count": len(already_ids),
        "blocked_route_count": len(blocked_ids),
        "route_summaries": route_summaries,
        "source_route_blocks": source_route_blocks,
        "target_line_ids": [entry.get("line_id", "") for entry in entries],
        "entries": entries,
        "materializable_count": materializable_count,
        "skipped_count": skipped_count,
        "missing_image_count": sum(
            1 for entry in entries if entry.get("skipped_reason") == "missing resolved image file"
        ),
        "destination_conflict_count": 0,
        "next_image_sequence_number": next_sequence,
        "planned_fresh_id_strategy": "fresh ids excluding every existing Fork PromptLine id",
        "append_count": len(appendable_ids),
    }
    preview["signature"] = _append_signature(preview)
    preview["signature_digest"] = _signature_digest(preview["signature"])
    return preview


def _json_safe(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _json_safe(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted((_json_safe(item) for item in value), key=str)
    return value


def _build_updated_project_raw(snapshot: dict, appended_project: Any) -> dict:
    raw = copy.deepcopy(snapshot["project_raw"])
    raw_lines = raw.get("prompt_lines")
    if not isinstance(raw_lines, list):
        raise ValueError("existing Fork prompt_lines is malformed")
    existing_count = len(raw_lines)
    existing_indices = [
        record.get("current_index")
        for record in raw_lines
        if isinstance(record, dict) and isinstance(record.get("current_index"), int)
    ]
    next_index = max(existing_indices, default=existing_count - 1) + 1
    appended_line_dicts = []
    for offset, line in enumerate(getattr(appended_project, "prompt_lines", []) or []):
        line.current_index = next_index + offset
        line.original_index = next_index + offset
        appended_line_dicts.append(_json_safe(line))
    raw_lines.extend(appended_line_dicts)
    raw["line_map"] = {
        _clean(record.get("id")): copy.deepcopy(record)
        for record in raw_lines
        if isinstance(record, dict) and _clean(record.get("id"))
    }

    graph_project = copy.deepcopy(snapshot["project"])
    graph_project.prompt_lines.extend(copy.deepcopy(getattr(appended_project, "prompt_lines", []) or []))
    build_graph(graph_project)
    for field in ("nodes", "edges", "node_freq", "phrase_freq", "global_group_freq"):
        raw[field] = _json_safe(getattr(graph_project, field, {}))
    return raw


def _append_manifest(existing_manifest: dict, preview: dict, manifest_entries: list[dict], appended_at: str) -> dict:
    manifest = copy.deepcopy(existing_manifest)
    materialized = [entry for entry in manifest_entries if entry.get("kind") == "materialized_line"]
    structure = [entry for entry in manifest_entries if entry.get("kind") != "materialized_line"]
    appended_route_ids = list(preview.get("appendable_route_ids", []))
    appended_labels = [
        summary.get("route_label") or summary.get("separator_label") or summary.get("route_handle")
        for summary in preview.get("route_summaries", [])
        if summary.get("status") == "appendable"
    ]
    source_blocks = copy.deepcopy(preview.get("source_route_blocks", []))
    skipped_entries = [
        {
            "source_line_id": entry.get("line_id", ""),
            "source_line_index": entry.get("line_index"),
            "route_id": entry.get("route_id", ""),
            "route_label": entry.get("route_label", ""),
            "skipped_reason": entry.get("skipped_reason", ""),
        }
        for entry in preview.get("entries", []) if not entry.get("materializable")
    ]
    history = list(manifest.get("append_history") or [])
    append_record = {
        "appended_at": appended_at,
        "source_project_path": preview.get("source_project_path", ""),
        "selected_route_ids": appended_route_ids,
        "selected_route_labels": appended_labels,
        "source_route_blocks": source_blocks,
        "materialized_line_count": len(materialized),
        "skipped_line_count": len(skipped_entries),
        "materialized_entries": materialized,
        "structure_entries": structure,
        "preview_signature_digest": preview.get("signature_digest", ""),
        "previous_manifest_digest": preview.get("existing_manifest_digest", ""),
    }
    history.append(append_record)
    manifest["append_history"] = history
    manifest["updated_at"] = appended_at
    manifest["selected_route_ids"] = list(dict.fromkeys(
        list(manifest.get("selected_route_ids") or []) + appended_route_ids
    ))
    manifest["selected_route_labels"] = list(manifest.get("selected_route_labels") or []) + appended_labels
    manifest["selected_route_count"] = len(manifest["selected_route_ids"])
    manifest["source_route_blocks"] = list(manifest.get("source_route_blocks") or []) + source_blocks
    manifest["materialized_entries"] = list(manifest.get("materialized_entries") or []) + materialized
    manifest["structure_entries"] = list(manifest.get("structure_entries") or []) + structure
    manifest["skipped_entries"] = list(manifest.get("skipped_entries") or []) + skipped_entries
    manifest["materialized_line_count"] = len(manifest["materialized_entries"])
    manifest["skipped_line_count"] = len(manifest["skipped_entries"])
    manifest["target_line_count"] = int(manifest.get("target_line_count", 0) or 0) + len(preview.get("entries", []))
    append_record["resulting_project_line_count"] = int(preview.get("existing_line_count", 0) or 0) + len(manifest_entries)
    append_record["resulting_image_count"] = int(preview.get("existing_image_count", 0) or 0) + len(materialized)
    return manifest


def _rename_with_retry(
    source: str,
    destination: str,
    *,
    rename: Callable[[str, str], Any],
    path_exists: Callable[[str], bool],
    sleep: Callable[[float], Any],
    retry_delays: Iterable[float],
) -> dict:
    delays = tuple(max(0.0, float(delay)) for delay in retry_delays) or (0.0,)
    attempts = 0
    for attempt_index, delay in enumerate(delays):
        if attempt_index > 0:
            sleep(delay)
        if path_exists(destination):
            return {"success": False, "error": "rename destination already exists", "conflict": True, "attempts": attempts}
        attempts += 1
        try:
            rename(source, destination)
            return {"success": True, "attempts": attempts, "retry_performed": attempt_index > 0}
        except OSError as exc:
            if not _is_retryable_windows_filesystem_error(exc) or attempt_index == len(delays) - 1:
                return {"success": False, "error": str(exc), "conflict": False, "attempts": attempts}
    return {"success": False, "error": "rename retry exhausted", "attempts": attempts}


def append_selected_routes_to_existing_fork(
    source_project: Any,
    *,
    source_project_path: str,
    selected_route_ids: Iterable[str],
    existing_fork_project_path: str,
    stored_preview: dict,
    current_open_project_path: str = "",
    created_at_provider: Callable[[], str] | None = None,
    id_generator: Callable[[str], str] | None = None,
    copy_tree: Callable[[str, str], Any] | None = None,
    copy_file: Callable[[str, str], Any] | None = None,
    rename: Callable[[str, str], Any] | None = None,
    rmtree: Callable[[str], Any] | None = None,
    sleep: Callable[[float], Any] | None = None,
    retry_delays: Iterable[float] | None = None,
    phase_hook: Callable[[str], Any] | None = None,
) -> dict:
    """Atomically append fresh Route blocks while preserving the source and existing Fork."""

    del source_project  # Apply re-reads the saved source Project by contract.
    copy_tree = copy_tree or shutil.copytree
    copy_file = copy_file or shutil.copy2
    rename = rename or os.rename
    rmtree = rmtree or shutil.rmtree
    sleep = sleep or time.sleep
    retry_delays = WINDOWS_RETRY_DELAYS if retry_delays is None else retry_delays
    phase_hook = phase_hook or (lambda _phase: None)
    created_at_provider = created_at_provider or (lambda: datetime.now(timezone.utc).isoformat())
    result = {
        "applied": False,
        "success": False,
        "error": "",
        "stale_preview": False,
        "appended_route_count": 0,
        "appended_line_count": 0,
        "appended_image_count": 0,
        "skipped_route_count": 0,
        "skipped_line_count": 0,
        "existing_fork_project_path": _normalized_path(existing_fork_project_path),
        "existing_fork_manifest_path": "",
        "appended_route_ids": [],
        "appended_route_labels": [],
        "diagnostics": [],
        "rollback_performed": False,
    }
    staging_dir = ""
    backup_dir = ""
    final_dir = ""
    swap_committed = False
    try:
        stored_content_signature = _append_signature(stored_preview)
        if stored_preview.get("signature") != stored_content_signature:
            result.update({"error": "stale preview", "stale_preview": True})
            return result
        saved_source = load_project_from_json(_normalized_path(source_project_path))
        snapshot = load_existing_fork_snapshot(existing_fork_project_path)
        current_preview = build_lightweight_fork_append_preview(
            saved_source,
            source_project_path=source_project_path,
            selected_route_ids=selected_route_ids,
            existing_fork_project_path=existing_fork_project_path,
            existing_snapshot=snapshot,
            current_open_project_path=current_open_project_path,
        )
        if stored_preview.get("signature") != current_preview.get("signature"):
            result.update({"error": "stale preview", "stale_preview": True, "diagnostics": current_preview.get("diagnostics", [])})
            return result
        if not current_preview.get("valid"):
            result.update({"error": current_preview.get("reason") or "append preview is invalid", "diagnostics": current_preview.get("diagnostics", [])})
            return result
        if not current_preview.get("appendable_route_ids"):
            result["error"] = "Selected Routes are already present in this Fork."
            return result

        final_dir = snapshot["fork_dir"]
        parent_dir = os.path.dirname(final_dir)
        staging_dir = tempfile.mkdtemp(prefix=f".{os.path.basename(final_dir)}.append-staging.", dir=parent_dir)
        os.rmdir(staging_dir)
        copy_tree(final_dir, staging_dir, copy_function=copy_file)
        phase_hook("after_staging_copy")

        appended_project, manifest_entries = build_lightweight_fork_project(
            saved_source,
            current_preview,
            id_generator=id_generator,
            used_ids=snapshot.get("existing_line_ids", []),
        )
        staging_images_dir = _safe_join(staging_dir, "images")
        for entry in current_preview.get("entries", []):
            if not entry.get("materializable"):
                continue
            source_stat = _file_stat(entry.get("resolved_image_path", ""))
            if (
                source_stat.get("size") != entry.get("source_file_size")
                or source_stat.get("mtime_ns") != entry.get("source_file_mtime_ns")
            ):
                raise ValueError(f"source image changed after preview: {entry.get('line_id', '')}")
            filename = entry.get("planned_destination_filename") or _planned_image_filename(
                entry.get("planned_destination_path", ""), current_preview.get("fork_name", "")
            )
            destination = _safe_join(staging_images_dir, filename)
            if os.path.exists(destination):
                raise FileExistsError(f"destination image already exists: {filename}")
            copy_file(entry.get("resolved_image_path", ""), destination)
        phase_hook("after_image_copy")

        updated_raw = _build_updated_project_raw(snapshot, appended_project)
        staging_project_path = _safe_join(staging_dir, "project.json")
        with open(staging_project_path, "w", encoding="utf-8") as handle:
            json.dump(updated_raw, handle, indent=2, ensure_ascii=False)
        phase_hook("after_project_write")

        appended_at = created_at_provider()
        updated_manifest = _append_manifest(snapshot["manifest"], current_preview, manifest_entries, appended_at)
        staging_manifest_path = _safe_join(staging_dir, "manifest.json")
        with open(staging_manifest_path, "w", encoding="utf-8") as handle:
            json.dump(updated_manifest, handle, indent=2, ensure_ascii=False)
        phase_hook("after_manifest_write")

        loaded_staging = load_project_from_json(staging_project_path)
        if len(loaded_staging.prompt_lines) != snapshot["existing_line_count"] + len(manifest_entries):
            raise ValueError("staged Fork Line count validation failed")
        if _safe_json_load(staging_manifest_path).get("operation") != MANIFEST_OPERATION:
            raise ValueError("staged manifest validation failed")
        phase_hook("after_validation")

        final_snapshot = load_existing_fork_snapshot(existing_fork_project_path)
        if (
            not final_snapshot.get("valid")
            or final_snapshot.get("project_digest") != current_preview.get("existing_project_digest")
            or final_snapshot.get("manifest_digest") != current_preview.get("existing_manifest_digest")
            or final_snapshot.get("image_inventory") != current_preview.get("existing_image_inventory")
            or _file_digest(_normalized_path(source_project_path)) != current_preview.get("source_project_digest")
        ):
            raise ValueError("source or existing Fork changed during append staging")
        for entry in current_preview.get("entries", []):
            if not entry.get("materializable"):
                continue
            source_stat = _file_stat(entry.get("resolved_image_path", ""))
            if (
                source_stat.get("size") != entry.get("source_file_size")
                or source_stat.get("mtime_ns") != entry.get("source_file_mtime_ns")
            ):
                raise ValueError(f"source image changed during append staging: {entry.get('line_id', '')}")

        backup_dir = f"{final_dir}.append-backup.{uuid.uuid4().hex}"
        first_rename = _rename_with_retry(
            final_dir, backup_dir, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
        )
        if not first_rename.get("success"):
            raise OSError(f"backup rename failed: {first_rename.get('error')}")
        phase_hook("after_backup_rename")
        second_rename = _rename_with_retry(
            staging_dir, final_dir, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
        )
        if not second_rename.get("success"):
            restore = _rename_with_retry(
                backup_dir, final_dir, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
            )
            result["rollback_performed"] = bool(restore.get("success"))
            backup_dir = "" if restore.get("success") else backup_dir
            raise OSError(f"final rename failed: {second_rename.get('error')}")
        staging_dir = ""
        swap_committed = True
        phase_hook("after_final_rename")

        cleanup = _remove_tree_with_retry(
            backup_dir, rmtree=rmtree, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
        )
        if not cleanup.get("success"):
            rollback_new = f"{final_dir}.append-rollback.{uuid.uuid4().hex}"
            move_new = _rename_with_retry(
                final_dir, rollback_new, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
            )
            restore = _rename_with_retry(
                backup_dir, final_dir, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
            ) if move_new.get("success") else {"success": False}
            result["rollback_performed"] = bool(restore.get("success"))
            if restore.get("success"):
                backup_dir = ""
                swap_committed = False
                _remove_tree_with_retry(
                    rollback_new, rmtree=rmtree, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
                )
            raise OSError(f"backup cleanup failed: {cleanup.get('error')}")
        backup_dir = ""

        appended_labels = [
            summary.get("route_label") or summary.get("separator_label") or summary.get("route_handle")
            for summary in current_preview.get("route_summaries", [])
            if summary.get("status") == "appendable"
        ]
        result.update({
            "applied": True,
            "success": True,
            "appended_route_count": len(current_preview.get("appendable_route_ids", [])),
            "appended_line_count": len([entry for entry in manifest_entries if entry.get("kind") == "materialized_line"]),
            "appended_image_count": current_preview.get("materializable_count", 0),
            "skipped_route_count": current_preview.get("blocked_route_count", 0) + current_preview.get("already_materialized_route_count", 0),
            "skipped_line_count": current_preview.get("skipped_count", 0),
            "existing_fork_manifest_path": os.path.join(final_dir, "manifest.json"),
            "appended_route_ids": list(current_preview.get("appendable_route_ids", [])),
            "appended_route_labels": appended_labels,
            "appended_manifest_record": updated_manifest.get("append_history", [])[-1],
        })
        return result
    except Exception as exc:
        result["error"] = result.get("error") or str(exc)
        if swap_committed and backup_dir and os.path.exists(backup_dir) and final_dir and os.path.exists(final_dir):
            rollback_new = f"{final_dir}.append-rollback.{uuid.uuid4().hex}"
            move_new = _rename_with_retry(
                final_dir, rollback_new, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
            )
            restore = _rename_with_retry(
                backup_dir, final_dir, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
            ) if move_new.get("success") else {"success": False}
            result["rollback_performed"] = bool(restore.get("success"))
            if restore.get("success"):
                backup_dir = ""
                swap_committed = False
                _remove_tree_with_retry(
                    rollback_new, rmtree=rmtree, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
                )
        if backup_dir and os.path.exists(backup_dir) and final_dir and not os.path.exists(final_dir):
            restore = _rename_with_retry(
                backup_dir, final_dir, rename=rename, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
            )
            result["rollback_performed"] = bool(restore.get("success"))
            if restore.get("success"):
                backup_dir = ""
        return result
    finally:
        if staging_dir and os.path.exists(staging_dir):
            _remove_tree_with_retry(
                staging_dir, rmtree=rmtree, path_exists=os.path.exists, sleep=sleep, retry_delays=retry_delays
            )
