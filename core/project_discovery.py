import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from core.lightweight_fork_append import (
    MANIFEST_OPERATION,
    SUPPORTED_MANIFEST_VERSION,
    get_materialized_route_ids_from_manifest,
)


JsonLoader = Callable[[str], Any]
ListDirectory = Callable[[str], Iterable[Any]]
PathPredicate = Callable[[str], bool]
PathMtime = Callable[[str], float]

_EXCLUDED_PROJECT_JSON_NAMES = frozenset({"manifest.json", "export_manifest.json"})
_TEMPORARY_JSON_SUFFIXES = (
    ".bak.json",
    ".backup.json",
    ".partial.json",
    ".temp.json",
    ".tmp.json",
)
_NATURAL_PARTS = re.compile(r"(\d+)")


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_project_discovery_path(path: object) -> str:
    """Return a real absolute path, or an empty string for unsafe input."""

    try:
        raw_path = os.fspath(path).strip() if path is not None else ""
    except (OSError, TypeError, ValueError):
        return ""
    if not raw_path or "\x00" in raw_path:
        return ""
    try:
        return os.path.realpath(
            os.path.abspath(
                os.path.expanduser(raw_path)
            )
        )
    except (OSError, TypeError, ValueError):
        return ""


def _path_key(path: object) -> str:
    normalized = normalize_project_discovery_path(path)
    return os.path.normcase(normalized) if normalized else ""


def path_is_within(path: object, root: object) -> bool:
    normalized_path = normalize_project_discovery_path(path)
    normalized_root = normalize_project_discovery_path(root)
    if not normalized_path or not normalized_root:
        return False
    path_key = os.path.normcase(normalized_path)
    root_key = os.path.normcase(normalized_root)
    try:
        return os.path.commonpath((root_key, path_key)) == root_key
    except (OSError, TypeError, ValueError):
        return False


def is_promptgraph_project_json_payload(payload: object) -> bool:
    """Match the minimum shape accepted by the existing Project loader."""

    return isinstance(payload, dict) and isinstance(payload.get("prompt_lines"), list)


def inspect_promptgraph_project_json(
    path: str,
    *,
    json_loader: JsonLoader = _load_json,
) -> dict:
    normalized_path = normalize_project_discovery_path(path)
    result = {
        "valid": False,
        "path": normalized_path or str(path or ""),
        "reason": "",
    }
    if not normalized_path:
        result["reason"] = "Project JSON path is invalid"
        return result
    try:
        payload = json_loader(normalized_path)
    except Exception as exc:
        result["reason"] = f"Project JSON is unreadable: {exc}"
        return result
    if not isinstance(payload, dict):
        result["reason"] = "Project JSON top level is not an object"
        return result
    if not isinstance(payload.get("prompt_lines"), list):
        result["reason"] = "Project JSON has no prompt_lines list"
        return result
    result["valid"] = True
    return result


def _natural_key(value: object) -> tuple:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in _NATURAL_PARTS.split(str(value or ""))
    )


def _safe_predicate(predicate: PathPredicate, path: str) -> bool:
    try:
        return bool(predicate(path))
    except (OSError, TypeError, ValueError):
        return False


def _safe_mtime(path: str, path_mtime: PathMtime) -> tuple[float, str]:
    try:
        return float(path_mtime(path)), ""
    except (OSError, TypeError, ValueError) as exc:
        return 0.0, f"modified time is unavailable: {exc}"


def _valid_direct_child_name(raw_name: object) -> tuple[str, str]:
    try:
        name = os.fspath(raw_name)
    except (OSError, TypeError, ValueError):
        return "", "candidate name is invalid"
    if (
        not name
        or "\x00" in name
        or name in {".", ".."}
        or os.path.basename(name) != name
        or "/" in name
        or "\\" in name
    ):
        return "", "candidate is not a direct child"
    return name, ""


def _project_json_candidate_reason(file_name: str) -> str:
    lowered = file_name.casefold()
    if not lowered.endswith(".json"):
        return "not a JSON file"
    if lowered in _EXCLUDED_PROJECT_JSON_NAMES:
        return "reserved non-Project JSON filename"
    if lowered.startswith((".", "~")):
        return "hidden or temporary JSON"
    if lowered.endswith(_TEMPORARY_JSON_SUFFIXES):
        return "backup, partial, or temporary JSON"
    return ""


def _date_label(value: object, fallback_timestamp: float) -> str:
    clean_value = str(value or "").strip()
    if clean_value:
        try:
            parsed = datetime.fromisoformat(clean_value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.date().isoformat()
        except (TypeError, ValueError, OverflowError):
            pass
    if fallback_timestamp > 0:
        try:
            return datetime.fromtimestamp(fallback_timestamp, timezone.utc).date().isoformat()
        except (OSError, ValueError, OverflowError):
            pass
    return "unknown"


def _safe_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _inspect_fork_manifest(
    manifest_path: str,
    *,
    project_directory: str,
    fork_directory: str,
    json_loader: JsonLoader,
    path_is_file: PathPredicate,
    path_is_link: PathPredicate,
    path_mtime: PathMtime,
) -> dict:
    result = {
        "available": False,
        "reason": "",
        "metadata": {},
    }
    if not path_is_within(manifest_path, fork_directory):
        result["reason"] = "Fork manifest escapes its directory"
        return result
    if _safe_predicate(path_is_link, manifest_path):
        result["reason"] = "Fork manifest symlinks are not inspected"
        return result
    if not _safe_predicate(path_is_file, manifest_path):
        result["reason"] = "Fork manifest is missing"
        return result
    try:
        manifest = json_loader(manifest_path)
    except Exception as exc:
        result["reason"] = f"Fork manifest is unreadable: {exc}"
        return result
    if not isinstance(manifest, dict):
        result["reason"] = "Fork manifest is not an object"
        return result
    if manifest.get("operation") != MANIFEST_OPERATION:
        result["reason"] = "Fork manifest operation is unsupported"
        return result
    if manifest.get("manifest_version") != SUPPORTED_MANIFEST_VERSION:
        result["reason"] = "Fork manifest version is unsupported"
        return result

    source_project_path = normalize_project_discovery_path(
        manifest.get("source_project_path", "")
    )
    if (
        not source_project_path
        or _path_key(os.path.dirname(source_project_path)) != _path_key(project_directory)
    ):
        result["reason"] = "Fork manifest source Project does not match its parent Project"
        return result

    manifest_mtime, _mtime_error = _safe_mtime(manifest_path, path_mtime)
    materialized_route_ids, _diagnostics = get_materialized_route_ids_from_manifest(
        manifest
    )
    result["available"] = True
    result["metadata"] = {
        "fork_name": str(manifest.get("fork_name") or "").strip(),
        "source_project_name": str(manifest.get("source_project_name") or "").strip(),
        "selected_route_count": _safe_nonnegative_int(
            manifest.get("selected_route_count")
        ),
        "materialized_route_count": len(materialized_route_ids),
        "materialized_line_count": _safe_nonnegative_int(
            manifest.get("materialized_line_count")
        ),
        "updated_date": _date_label(
            manifest.get("updated_at") or manifest.get("created_at"),
            manifest_mtime,
        ),
    }
    return result


def _project_entry(
    *,
    project_name: str,
    project_directory: str,
    project_path: str,
    project_file_name: str,
    root: str,
    modified_at: float,
) -> dict:
    return {
        "kind": "project",
        "project_name": project_name,
        "project_directory": project_directory,
        "project_path": project_path,
        "project_file_name": project_file_name,
        "relative_path": os.path.relpath(project_path, root),
        "display_label": f"Project · {project_name} · {project_file_name}",
        "modified_at": modified_at,
        "currently_open": False,
    }


def _fork_entry(
    *,
    project_name: str,
    project_directory: str,
    fork_directory: str,
    project_path: str,
    manifest_path: str,
    root: str,
    modified_at: float,
    manifest_result: dict,
) -> dict:
    fork_name = (
        manifest_result.get("metadata", {}).get("fork_name")
        or os.path.basename(fork_directory)
        or "Fork"
    )
    display_label = f"Derived Project · {project_name} / {fork_name} · project.json"
    metadata = dict(manifest_result.get("metadata") or {})
    if manifest_result.get("available"):
        route_count = (
            metadata.get("materialized_route_count", 0)
            or metadata.get("selected_route_count", 0)
        )
        updated_date = metadata.get("updated_date", "unknown")
        display_label += f" · {route_count} Scenes · updated {updated_date}"
    else:
        display_label += " · manifest unavailable"
    return {
        "kind": "fork",
        "project_name": project_name,
        "project_directory": fork_directory,
        "parent_project_directory": project_directory,
        "fork_name": fork_name,
        "project_path": project_path,
        "project_file_name": "project.json",
        "manifest_path": manifest_path,
        "manifest_available": bool(manifest_result.get("available")),
        "manifest_error": str(manifest_result.get("reason") or ""),
        "fork_metadata": metadata,
        "relative_path": os.path.relpath(project_path, root),
        "display_label": display_label,
        "modified_at": modified_at,
        "currently_open": False,
    }


def _entry_sort_key(entry: dict) -> tuple:
    kind_rank = 0 if entry.get("kind") == "project" else 1
    return (
        _natural_key(entry.get("project_name")),
        kind_rank,
        _natural_key(
            entry.get("project_file_name")
            if kind_rank == 0
            else entry.get("fork_name")
        ),
        _natural_key(entry.get("project_file_name")),
        _path_key(entry.get("project_path")),
    )


def _empty_result(root: str) -> dict:
    return {
        "valid": False,
        "status": "invalid",
        "reason": "",
        "root": root,
        "projects": [],
        "rejected": [],
        "diagnostics": [],
        "counts": {
            "normal_projects": 0,
            "fork_projects": 0,
            "rejected": 0,
        },
    }


def discover_project_root_projects(
    root: object,
    *,
    path_exists: PathPredicate = os.path.exists,
    path_is_file: PathPredicate = os.path.isfile,
    path_is_dir: PathPredicate = os.path.isdir,
    path_is_link: PathPredicate = os.path.islink,
    list_directory: ListDirectory = os.listdir,
    json_loader: JsonLoader = _load_json,
    path_mtime: PathMtime = os.path.getmtime,
) -> dict:
    """Discover only PromptGraph's direct Project and known Fork layouts."""

    normalized_root = normalize_project_discovery_path(root)
    result = _empty_result(normalized_root or str(root or ""))
    if not normalized_root:
        result["reason"] = "Project root path is invalid"
        return result
    if not _safe_predicate(path_exists, normalized_root):
        result["status"] = "missing"
        result["reason"] = "Project root does not exist"
        return result
    if not _safe_predicate(path_is_dir, normalized_root):
        result["status"] = "not_directory"
        result["reason"] = "Project root is not a directory"
        return result

    result["valid"] = True
    result["status"] = "ready"
    try:
        project_child_names = list(list_directory(normalized_root))
    except Exception as exc:
        result["valid"] = False
        result["status"] = "unreadable"
        result["reason"] = f"Project root could not be read: {exc}"
        return result

    entries = []
    rejected = []
    diagnostics = []
    seen_directories = set()
    seen_project_paths = set()

    for raw_project_name in project_child_names:
        project_name, name_error = _valid_direct_child_name(raw_project_name)
        display_path = os.path.join(normalized_root, str(raw_project_name or ""))
        if name_error:
            rejected.append({"path": display_path, "reason": name_error})
            continue
        raw_project_directory = os.path.join(normalized_root, project_name)
        project_directory = normalize_project_discovery_path(raw_project_directory)
        project_directory_key = _path_key(project_directory)
        if (
            not project_directory
            or not path_is_within(project_directory, normalized_root)
            or project_directory_key == _path_key(normalized_root)
        ):
            rejected.append(
                {"path": raw_project_directory, "reason": "Project directory escapes Project root"}
            )
            continue
        if project_directory_key in seen_directories:
            rejected.append(
                {"path": raw_project_directory, "reason": "duplicate resolved Project directory"}
            )
            continue
        seen_directories.add(project_directory_key)
        if not _safe_predicate(path_is_dir, raw_project_directory):
            rejected.append(
                {"path": raw_project_directory, "reason": "Project root child is not a directory"}
            )
            continue

        try:
            project_member_names = list(list_directory(project_directory))
        except Exception as exc:
            rejected.append(
                {"path": project_directory, "reason": f"Project directory could not be read: {exc}"}
            )
            continue

        for raw_file_name in project_member_names:
            file_name, file_name_error = _valid_direct_child_name(raw_file_name)
            raw_project_path = os.path.join(project_directory, str(raw_file_name or ""))
            if file_name_error:
                rejected.append({"path": raw_project_path, "reason": file_name_error})
                continue
            candidate_reason = _project_json_candidate_reason(file_name)
            if candidate_reason == "not a JSON file":
                continue
            if candidate_reason:
                rejected.append({"path": raw_project_path, "reason": candidate_reason})
                continue
            if _safe_predicate(path_is_link, raw_project_path):
                rejected.append({"path": raw_project_path, "reason": "Project JSON symlinks are not allowed"})
                continue
            project_path = normalize_project_discovery_path(raw_project_path)
            if not project_path or not path_is_within(project_path, project_directory):
                rejected.append({"path": raw_project_path, "reason": "Project JSON escapes its directory"})
                continue
            if not _safe_predicate(path_is_file, raw_project_path):
                rejected.append({"path": raw_project_path, "reason": "Project JSON candidate is not a file"})
                continue
            project_path_key = _path_key(project_path)
            if project_path_key in seen_project_paths:
                rejected.append({"path": raw_project_path, "reason": "duplicate resolved Project JSON"})
                continue
            inspection = inspect_promptgraph_project_json(
                project_path,
                json_loader=json_loader,
            )
            if not inspection["valid"]:
                rejected.append({"path": project_path, "reason": inspection["reason"]})
                continue
            modified_at, mtime_error = _safe_mtime(project_path, path_mtime)
            if mtime_error:
                diagnostics.append(f"{project_path}: {mtime_error}")
            seen_project_paths.add(project_path_key)
            entries.append(
                _project_entry(
                    project_name=project_name,
                    project_directory=project_directory,
                    project_path=project_path,
                    project_file_name=file_name,
                    root=normalized_root,
                    modified_at=modified_at,
                )
            )

        forks_root_raw = os.path.join(project_directory, "forks")
        if not _safe_predicate(path_exists, forks_root_raw):
            continue
        forks_root = normalize_project_discovery_path(forks_root_raw)
        if not forks_root or not path_is_within(forks_root, project_directory):
            rejected.append({"path": forks_root_raw, "reason": "Fork root escapes Project directory"})
            continue
        if not _safe_predicate(path_is_dir, forks_root_raw):
            rejected.append({"path": forks_root_raw, "reason": "Fork root is not a directory"})
            continue
        try:
            fork_child_names = list(list_directory(forks_root))
        except Exception as exc:
            rejected.append({"path": forks_root, "reason": f"Fork root could not be read: {exc}"})
            continue

        seen_fork_directories = set()
        for raw_fork_name in fork_child_names:
            fork_directory_name, fork_name_error = _valid_direct_child_name(raw_fork_name)
            raw_fork_directory = os.path.join(forks_root, str(raw_fork_name or ""))
            if fork_name_error:
                rejected.append({"path": raw_fork_directory, "reason": fork_name_error})
                continue
            fork_directory = normalize_project_discovery_path(raw_fork_directory)
            fork_directory_key = _path_key(fork_directory)
            if (
                not fork_directory
                or not path_is_within(fork_directory, forks_root)
                or fork_directory_key == _path_key(forks_root)
            ):
                rejected.append({"path": raw_fork_directory, "reason": "Fork directory escapes Fork root"})
                continue
            if fork_directory_key in seen_fork_directories:
                rejected.append({"path": raw_fork_directory, "reason": "duplicate resolved Fork directory"})
                continue
            seen_fork_directories.add(fork_directory_key)
            if not _safe_predicate(path_is_dir, raw_fork_directory):
                rejected.append({"path": raw_fork_directory, "reason": "Fork candidate is not a directory"})
                continue

            raw_fork_project_path = os.path.join(fork_directory, "project.json")
            if _safe_predicate(path_is_link, raw_fork_project_path):
                rejected.append({"path": raw_fork_project_path, "reason": "Fork Project JSON symlinks are not allowed"})
                continue
            fork_project_path = normalize_project_discovery_path(raw_fork_project_path)
            if (
                not fork_project_path
                or not path_is_within(fork_project_path, fork_directory)
                or not _safe_predicate(path_is_file, raw_fork_project_path)
            ):
                rejected.append({"path": raw_fork_project_path, "reason": "Fork project.json is missing or unsafe"})
                continue
            fork_project_path_key = _path_key(fork_project_path)
            if fork_project_path_key in seen_project_paths:
                rejected.append({"path": fork_project_path, "reason": "duplicate resolved Project JSON"})
                continue
            inspection = inspect_promptgraph_project_json(
                fork_project_path,
                json_loader=json_loader,
            )
            if not inspection["valid"]:
                rejected.append({"path": fork_project_path, "reason": inspection["reason"]})
                continue

            raw_manifest_path = os.path.join(fork_directory, "manifest.json")
            manifest_path = normalize_project_discovery_path(raw_manifest_path)
            manifest_result = _inspect_fork_manifest(
                raw_manifest_path,
                project_directory=project_directory,
                fork_directory=fork_directory,
                json_loader=json_loader,
                path_is_file=path_is_file,
                path_is_link=path_is_link,
                path_mtime=path_mtime,
            )
            if manifest_result.get("reason"):
                diagnostics.append(
                    f"{fork_project_path}: {manifest_result['reason']}"
                )
            images_directory = os.path.join(fork_directory, "images")
            if not _safe_predicate(path_is_dir, images_directory):
                diagnostics.append(
                    f"{fork_project_path}: Fork images directory is missing"
                )
            modified_at, mtime_error = _safe_mtime(fork_project_path, path_mtime)
            if mtime_error:
                diagnostics.append(f"{fork_project_path}: {mtime_error}")
            seen_project_paths.add(fork_project_path_key)
            entries.append(
                _fork_entry(
                    project_name=project_name,
                    project_directory=project_directory,
                    fork_directory=fork_directory,
                    project_path=fork_project_path,
                    manifest_path=manifest_path,
                    root=normalized_root,
                    modified_at=modified_at,
                    manifest_result=manifest_result,
                )
            )

    entries.sort(key=_entry_sort_key)
    result["projects"] = entries
    result["rejected"] = rejected
    result["diagnostics"] = diagnostics
    result["counts"] = {
        "normal_projects": sum(entry.get("kind") == "project" for entry in entries),
        "fork_projects": sum(entry.get("kind") == "fork" for entry in entries),
        "rejected": len(rejected),
    }
    return result


def build_project_discovery_cache_key(
    root: object,
    refresh_generation: int,
) -> tuple[str, int]:
    return (
        normalize_project_discovery_path(root),
        int(refresh_generation or 0),
    )


def _with_current_project(snapshot: dict, current_open_project_path: object) -> dict:
    current_key = _path_key(current_open_project_path)
    decorated = dict(snapshot)
    decorated["projects"] = [
        {
            **entry,
            "currently_open": bool(
                current_key and _path_key(entry.get("project_path")) == current_key
            ),
        }
        for entry in snapshot.get("projects", [])
    ]
    return decorated


def resolve_cached_project_discovery(
    cache_entry: dict | None,
    *,
    root: object,
    refresh_generation: int,
    current_open_project_path: object = "",
    discoverer: Callable[..., dict] = discover_project_root_projects,
) -> tuple[dict, dict, bool]:
    cache_key = build_project_discovery_cache_key(root, refresh_generation)
    if isinstance(cache_entry, dict) and cache_entry.get("key") == cache_key:
        snapshot = cache_entry.get("snapshot")
        if isinstance(snapshot, dict):
            return _with_current_project(snapshot, current_open_project_path), cache_entry, True
    snapshot = discoverer(root)
    next_entry = {"key": cache_key, "snapshot": snapshot}
    return _with_current_project(snapshot, current_open_project_path), next_entry, False


def validate_project_discovery_open_path(
    project_path: object,
    root: object,
    *,
    path_is_file: PathPredicate = os.path.isfile,
    path_is_link: PathPredicate = os.path.islink,
) -> tuple[str, str]:
    try:
        raw_path = os.fspath(project_path).strip() if project_path is not None else ""
    except (OSError, TypeError, ValueError):
        raw_path = ""
    normalized_root = normalize_project_discovery_path(root)
    normalized_path = normalize_project_discovery_path(raw_path)
    if not normalized_root or not normalized_path:
        return "", "Project path is invalid. Refresh the Project list."
    if _safe_predicate(path_is_link, raw_path):
        return "", "Project JSON is now a symlink. Refresh the Project list."
    if not path_is_within(normalized_path, normalized_root):
        return "", "Project JSON is outside the configured Project root."
    if not _safe_predicate(path_is_file, raw_path):
        return "", "Project JSON is missing. Refresh the Project list."
    return normalized_path, ""
