import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from core.lightweight_fork_append import (
    MANIFEST_OPERATION,
    SUPPORTED_MANIFEST_VERSION,
    get_materialized_route_ids_from_manifest,
    normalize_lightweight_fork_path,
)


JsonLoader = Callable[[str], Any]


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _parsed_timestamp(value: Any) -> float | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    try:
        parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _display_date(updated_at: Any, created_at: Any, fallback_timestamp: float) -> str:
    for value in (updated_at, created_at):
        timestamp = _parsed_timestamp(value)
        if timestamp is not None:
            return datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
    if fallback_timestamp > 0:
        return datetime.fromtimestamp(fallback_timestamp, timezone.utc).date().isoformat()
    return "unknown"


def _path_is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([root, path]) == root
    except (OSError, ValueError):
        return False


def _rejected(path: str, reason: str) -> dict:
    return {"path": path, "reason": reason}


def _candidate_summary(
    manifest: dict,
    *,
    fork_directory: str,
    project_path: str,
    manifest_path: str,
    images_directory: str,
    source_project_path: str,
    current_open_project_path: str,
    manifest_mtime: float,
) -> dict:
    fork_name = str(manifest.get("fork_name") or "").strip() or os.path.basename(fork_directory)
    updated_at = str(manifest.get("updated_at") or "").strip()
    created_at = str(manifest.get("created_at") or "").strip()
    sort_timestamp = _parsed_timestamp(updated_at)
    if sort_timestamp is None:
        sort_timestamp = _parsed_timestamp(created_at)
    if sort_timestamp is None:
        sort_timestamp = manifest_mtime

    selected_route_count = _safe_int(manifest.get("selected_route_count"))
    materialized_route_ids, materialization_diagnostics = get_materialized_route_ids_from_manifest(manifest)
    materialized_route_count = len(materialized_route_ids)
    materialized_line_count = _safe_int(manifest.get("materialized_line_count"))
    skipped_line_count = _safe_int(manifest.get("skipped_line_count"))
    append_history_count = len(_safe_list(manifest.get("append_history")))
    updated_label = _display_date(updated_at, created_at, manifest_mtime)
    display_label = (
        f"{fork_name} - {materialized_route_count} Scenes / "
        f"{materialized_line_count} Illustrations / updated {updated_label}"
    )
    normalized_current = normalize_lightweight_fork_path(current_open_project_path)
    return {
        "fork_name": fork_name,
        "fork_directory": fork_directory,
        "project_path": project_path,
        "manifest_path": manifest_path,
        "images_directory": images_directory,
        "source_project_path": source_project_path,
        "source_match": True,
        "manifest_version": manifest.get("manifest_version"),
        "operation": manifest.get("operation"),
        "created_at": created_at,
        "updated_at": updated_at,
        "selected_route_count": selected_route_count,
        "materialized_route_count": materialized_route_count,
        "materialization_diagnostics": materialization_diagnostics,
        "materialized_line_count": materialized_line_count,
        "skipped_line_count": skipped_line_count,
        "append_history_count": append_history_count,
        "currently_open": bool(normalized_current and normalized_current == project_path),
        "display_label": display_label,
        "sort_key": (-float(sort_timestamp or 0.0), fork_name.casefold(), fork_directory.casefold()),
    }


def discover_lightweight_forks_for_source(
    source_project_path: str,
    *,
    search_root: str = "",
    current_open_project_path: str = "",
    path_exists: Callable[[str], bool] = os.path.exists,
    path_is_file: Callable[[str], bool] = os.path.isfile,
    path_is_dir: Callable[[str], bool] = os.path.isdir,
    list_directory: Callable[[str], list[str]] = os.listdir,
    json_loader: JsonLoader = _load_json,
    path_mtime: Callable[[str], float] = os.path.getmtime,
) -> dict:
    """Discover same-source Lightweight Forks by reading direct-child manifests only."""

    normalized_source = normalize_lightweight_fork_path(source_project_path)
    default_root = os.path.join(os.path.dirname(normalized_source), "forks") if normalized_source else ""
    normalized_root = normalize_lightweight_fork_path(search_root or default_root)
    result = {
        "valid": False,
        "reason": "",
        "source_project_path": normalized_source,
        "search_root": normalized_root,
        "candidates": [],
        "rejected": [],
        "diagnostics": [],
    }
    if not normalized_source or not path_is_file(normalized_source):
        result["reason"] = "saved source Project is required for Fork discovery"
        return result
    if not normalized_root:
        result["reason"] = "Fork discovery root is unavailable"
        return result
    normalized_source_directory = normalize_lightweight_fork_path(os.path.dirname(normalized_source))
    if (
        not normalized_source_directory
        or normalized_root == normalized_source_directory
        or not _path_is_within(normalized_root, normalized_source_directory)
    ):
        result["reason"] = "Fork discovery root escapes the source Project directory"
        return result
    result["valid"] = True
    if not path_exists(normalized_root):
        return result
    if not path_is_dir(normalized_root):
        result["valid"] = False
        result["reason"] = "Fork discovery root is not a directory"
        return result

    seen_directories = set()
    seen_project_paths = set()
    try:
        child_names = list(list_directory(normalized_root))
    except OSError as exc:
        result["valid"] = False
        result["reason"] = f"Fork discovery failed: {exc}"
        return result

    for raw_name in child_names:
        child_name = str(raw_name or "")
        display_path = os.path.join(normalized_root, child_name)
        if not child_name or child_name in (".", "..") or os.path.basename(child_name) != child_name:
            result["rejected"].append(_rejected(display_path, "candidate is not a direct child"))
            continue
        candidate_dir = normalize_lightweight_fork_path(display_path)
        if not candidate_dir or not _path_is_within(candidate_dir, normalized_root) or candidate_dir == normalized_root:
            result["rejected"].append(_rejected(display_path, "candidate escapes Fork discovery root"))
            continue
        if candidate_dir in seen_directories:
            result["rejected"].append(_rejected(display_path, "duplicate Fork directory"))
            continue
        seen_directories.add(candidate_dir)
        if not path_is_dir(candidate_dir):
            result["rejected"].append(_rejected(display_path, "candidate is not a directory"))
            continue

        manifest_path = normalize_lightweight_fork_path(os.path.join(candidate_dir, "manifest.json"))
        project_path = normalize_lightweight_fork_path(os.path.join(candidate_dir, "project.json"))
        images_directory = normalize_lightweight_fork_path(os.path.join(candidate_dir, "images"))
        if not all(
            path and _path_is_within(path, candidate_dir)
            for path in (manifest_path, project_path, images_directory)
        ):
            result["rejected"].append(_rejected(candidate_dir, "Fork member path escapes candidate directory"))
            continue
        if not path_is_file(manifest_path):
            result["rejected"].append(_rejected(candidate_dir, "manifest.json is missing"))
            continue
        if not path_is_file(project_path):
            result["rejected"].append(_rejected(candidate_dir, "project.json is missing"))
            continue
        if not path_is_dir(images_directory):
            result["rejected"].append(_rejected(candidate_dir, "images directory is missing"))
            continue
        if project_path == normalized_source:
            result["rejected"].append(_rejected(candidate_dir, "candidate is the source Project"))
            continue
        if project_path in seen_project_paths:
            result["rejected"].append(_rejected(candidate_dir, "duplicate resolved Fork project path"))
            continue

        try:
            manifest = json_loader(manifest_path)
        except Exception as exc:
            result["rejected"].append(_rejected(candidate_dir, f"manifest.json is unreadable: {exc}"))
            continue
        if not isinstance(manifest, dict):
            result["rejected"].append(_rejected(candidate_dir, "manifest.json is not an object"))
            continue
        if manifest.get("operation") != MANIFEST_OPERATION:
            result["rejected"].append(_rejected(candidate_dir, "unsupported manifest operation"))
            continue
        if manifest.get("manifest_version") != SUPPORTED_MANIFEST_VERSION:
            result["rejected"].append(_rejected(candidate_dir, "unsupported manifest version"))
            continue
        manifest_source = normalize_lightweight_fork_path(manifest.get("source_project_path", ""))
        if not manifest_source:
            result["rejected"].append(_rejected(candidate_dir, "manifest source_project_path is missing"))
            continue
        if manifest_source != normalized_source:
            result["rejected"].append(_rejected(candidate_dir, "Fork source Project does not match"))
            continue

        try:
            manifest_mtime = float(path_mtime(manifest_path))
        except (OSError, TypeError, ValueError):
            manifest_mtime = 0.0
        seen_project_paths.add(project_path)
        result["candidates"].append(
            _candidate_summary(
                manifest,
                fork_directory=candidate_dir,
                project_path=project_path,
                manifest_path=manifest_path,
                images_directory=images_directory,
                source_project_path=manifest_source,
                current_open_project_path=current_open_project_path,
                manifest_mtime=manifest_mtime,
            )
        )

    result["candidates"].sort(key=lambda candidate: candidate["sort_key"])
    result["diagnostics"] = [
        f"{os.path.basename(entry['path']) or entry['path']}: {entry['reason']}"
        for entry in result["rejected"]
    ]
    return result


def build_lightweight_fork_discovery_cache_key(
    source_project_path: str,
    search_root: str,
    refresh_generation: int,
) -> tuple[str, str, int]:
    return (
        normalize_lightweight_fork_path(source_project_path),
        normalize_lightweight_fork_path(search_root),
        int(refresh_generation or 0),
    )


def resolve_cached_lightweight_fork_discovery(
    cache_entry: dict | None,
    *,
    source_project_path: str,
    search_root: str,
    refresh_generation: int,
    discoverer: Callable[..., dict] = discover_lightweight_forks_for_source,
    current_open_project_path: str = "",
) -> tuple[dict, dict, bool]:
    cache_key = build_lightweight_fork_discovery_cache_key(
        source_project_path,
        search_root,
        refresh_generation,
    )
    if isinstance(cache_entry, dict) and cache_entry.get("key") == cache_key:
        snapshot = cache_entry.get("snapshot")
        if isinstance(snapshot, dict):
            return snapshot, cache_entry, True
    snapshot = discoverer(
        source_project_path,
        search_root=search_root,
        current_open_project_path=current_open_project_path,
    )
    next_entry = {"key": cache_key, "snapshot": snapshot}
    return snapshot, next_entry, False
