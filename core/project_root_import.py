import copy
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
from typing import Any, Callable, Iterable

from core.graph_builder import build_graph
from core.io import load_project_from_json
from core.lightweight_fork import (
    WINDOWS_RETRY_DELAYS,
    _commit_directory_with_retry,
    _remove_tree_with_retry,
)
from core.lightweight_fork_append import (
    MANIFEST_OPERATION,
    SUPPORTED_MANIFEST_VERSION,
    load_existing_fork_snapshot,
)


PROJECT_ROOT_IMPORT_CONFIRM_PHRASE = "COPY PROJECT"

IGNORED_IMPORT_DIRECTORIES = frozenset(
    {
        ".git",
        ".promptgraph_cache",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
    }
)
IGNORED_IMPORT_FILES = frozenset({".DS_Store", "Thumbs.db"})
_EXCLUDED_PROJECT_JSON_NAMES = frozenset({"manifest.json", "export_manifest.json"})
_TEMPORARY_JSON_SUFFIXES = (
    ".bak.json",
    ".backup.json",
    ".partial.json",
    ".temp.json",
    ".tmp.json",
)
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
_NATURAL_PARTS = re.compile(r"(\d+)")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


PROJECT_JSON_PATH_REGISTRY = (
    "source_directory",
    "project_metadata.image_imports[].source_directory",
    "project_metadata.image_imports[].images[].path",
    "prompt_lines[].image_path",
    "prompt_lines[].generated_image_path",
    "prompt_lines[].selected_candidate_path",
    "prompt_lines[].generated_candidates[].path",
    "prompt_lines[].generated_candidates[].previous_main_image_path",
    "prompt_lines[].gallery_variants[].path",
    "prompt_lines[].gallery_variants[].lineage_info.candidate_image_path",
    "prompt_lines[].gallery_variants[].lineage_info.parent_image_path",
    "prompt_lines[].gallery_variants[].source_generation_info.source_image_path",
    "prompt_lines[].lineage_info.candidate_image_path",
    "prompt_lines[].lineage_info.parent_image_path",
    "prompt_lines[].lineage_info.candidate_image_adoption.candidate_image_path",
    "prompt_lines[].lineage_info.candidate_image_swap.new_main_image_path",
    "prompt_lines[].lineage_info.candidate_image_swap.previous_main_image_path",
    "prompt_lines[].source_generation_info.source_image_path",
    "route_snapshots[].items[].selected_candidate_path",
    "route_snapshots[].items[].generated_image_path",
    "route_snapshots[].items[].reference_image_path",
)

FORK_MANIFEST_PATH_REGISTRY = (
    "source_project_path",
    "destination_project_path",
    "destination_manifest_path",
    "materialized_entries[].source_image_path",
    "append_history[].source_project_path",
    "append_history[].materialized_entries[].source_image_path",
)


class ProjectRootImportStaleError(RuntimeError):
    """Raised when a confirmed import Preview no longer matches the source."""


def normalize_project_import_path(path: object) -> str:
    try:
        raw_path = os.fspath(path).strip() if path is not None else ""
    except (OSError, TypeError, ValueError):
        return ""
    if not raw_path or "\x00" in raw_path:
        return ""
    try:
        return os.path.realpath(os.path.abspath(os.path.expanduser(raw_path)))
    except (OSError, TypeError, ValueError):
        return ""


def _path_key(path: object) -> str:
    normalized = normalize_project_import_path(path)
    return os.path.normcase(normalized) if normalized else ""


def _same_path(left: object, right: object) -> bool:
    left_key = _path_key(left)
    right_key = _path_key(right)
    return bool(left_key and right_key and left_key == right_key)


def _path_is_within(path: object, root: object) -> bool:
    normalized_path = normalize_project_import_path(path)
    normalized_root = normalize_project_import_path(root)
    if not normalized_path or not normalized_root:
        return False
    try:
        return os.path.commonpath(
            (os.path.normcase(normalized_path), os.path.normcase(normalized_root))
        ) == os.path.normcase(normalized_root)
    except (OSError, TypeError, ValueError):
        return False


def _natural_key(value: object) -> tuple:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in _NATURAL_PARTS.split(str(value or ""))
    )


def _unique_messages(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _stat_is_reparse(stat_result: os.stat_result) -> bool:
    attributes = int(getattr(stat_result, "st_file_attributes", 0) or 0)
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _path_is_link_or_reparse(path: str) -> bool:
    try:
        stat_result = os.lstat(path)
    except (OSError, TypeError, ValueError):
        return False
    return stat.S_ISLNK(stat_result.st_mode) or _stat_is_reparse(stat_result)


def sanitize_project_import_name(name: object) -> str:
    clean_name = str(name or "").strip()
    clean_name = clean_name.replace("/", "_").replace("\\", "_")
    clean_name = "".join(
        character if character not in '<>:"|?*' and character != "\x00" else "_"
        for character in clean_name
    )
    clean_name = clean_name.strip(" .")
    if clean_name in {"", ".", ".."}:
        return "ImportedProject"
    if clean_name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        clean_name = f"{clean_name}_"
    return clean_name or "ImportedProject"


def _validate_destination_name(name: object) -> tuple[str, str]:
    raw_name = str(name or "").strip()
    if not raw_name:
        return "", "Destination Project name is required."
    if "\x00" in raw_name:
        return "", "Destination Project name contains NUL."
    if os.path.isabs(os.path.expanduser(raw_name)):
        return "", "Destination Project name must not be an absolute path."
    if raw_name in {".", ".."} or "/" in raw_name or "\\" in raw_name:
        return "", "Destination Project name must be one direct-child folder name."
    sanitized = sanitize_project_import_name(raw_name)
    if sanitized != raw_name:
        return "", f"Destination Project name is unsafe. Suggested name: {sanitized}"
    return sanitized, ""


def _destination_conflict(destination_root: str, destination_name: str) -> str:
    if not os.path.isdir(destination_root):
        return ""
    target_key = destination_name.casefold()
    try:
        for existing_name in os.listdir(destination_root):
            if str(existing_name).casefold() == target_key:
                return os.path.join(destination_root, str(existing_name))
    except OSError:
        return ""
    return ""


def _destination_paths(
    destination_root: object,
    destination_name: object,
    source_project_path: str,
) -> dict:
    normalized_root = normalize_project_import_path(destination_root)
    clean_name, name_error = _validate_destination_name(destination_name)
    result = {
        "valid": False,
        "destination_root": normalized_root,
        "destination_name": clean_name,
        "destination_directory": "",
        "destination_project_path": "",
        "error": name_error,
    }
    if not normalized_root:
        result["error"] = result["error"] or "Destination Project root is invalid."
        return result
    if name_error:
        return result
    destination_directory = os.path.join(normalized_root, clean_name)
    normalized_destination = normalize_project_import_path(destination_directory)
    if (
        not normalized_destination
        or not _path_is_within(normalized_destination, normalized_root)
        or _path_key(os.path.dirname(normalized_destination)) != _path_key(normalized_root)
    ):
        result["error"] = "Destination escapes the effective Project root."
        return result
    conflict = _destination_conflict(normalized_root, clean_name)
    if conflict or os.path.lexists(destination_directory):
        result["error"] = f"Destination already exists: {conflict or destination_directory}"
        result["destination_directory"] = normalized_destination
        return result
    source_file_name = os.path.basename(str(source_project_path or "")) or "project.json"
    result.update(
        {
            "valid": True,
            "destination_directory": normalized_destination,
            "destination_project_path": os.path.join(
                normalized_destination,
                source_file_name,
            ),
            "error": "",
        }
    )
    return result


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_json_matching_digest(path: str, expected_digest: str) -> Any:
    with open(path, "rb") as handle:
        payload = handle.read()
    if _sha256_bytes(payload) != expected_digest:
        raise ProjectRootImportStaleError(f"JSON changed during import: {path}")
    return json.loads(payload.decode("utf-8"))


def _write_json(path: str, payload: object) -> None:
    parent = os.path.dirname(path)
    file_name = os.path.basename(path) or "project.json"
    temporary_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=f".{file_name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(temporary_path, path)
        temporary_path = ""
    finally:
        if temporary_path and os.path.isfile(temporary_path):
            try:
                os.remove(temporary_path)
            except OSError:
                pass


def _project_json_candidate_reason(file_name: str) -> str:
    lowered = str(file_name or "").casefold()
    if not lowered.endswith(".json"):
        return "not_json"
    if lowered in _EXCLUDED_PROJECT_JSON_NAMES:
        return "reserved"
    if lowered.startswith((".", "~")) or lowered.endswith(_TEMPORARY_JSON_SUFFIXES):
        return "temporary"
    return ""


def _validate_project_json(path: str) -> tuple[dict, str]:
    try:
        raw = _read_json(path)
    except Exception as exc:
        return {}, f"Project JSON is unreadable: {exc}"
    if not isinstance(raw, dict) or not isinstance(raw.get("prompt_lines"), list):
        return {}, "JSON is not a PromptGraph Project"
    try:
        project = load_project_from_json(path)
        build_graph(project)
    except Exception as exc:
        return {}, f"Project load/graph validation failed: {exc}"
    return raw, ""


def _inventory_source_directory(source_directory: str) -> dict:
    entries: list[dict] = []
    ignored: list[dict] = []
    blockers: list[str] = []
    seen_relative_keys: set[str] = set()
    seen_real_paths: set[str] = set()

    if _path_is_link_or_reparse(source_directory):
        blockers.append("Source Project directory is a symlink or reparse point.")
        return {"entries": entries, "ignored": ignored, "blockers": blockers}

    def visit(directory: str, relative_directory: str = "") -> None:
        try:
            children = sorted(os.scandir(directory), key=lambda item: _natural_key(item.name))
        except OSError as exc:
            blockers.append(f"Source directory could not be read: {directory}: {exc}")
            return
        for child in children:
            relative_path = os.path.join(relative_directory, child.name) if relative_directory else child.name
            portable_relative = relative_path.replace(os.sep, "/")
            ignored_directory = child.name in IGNORED_IMPORT_DIRECTORIES
            ignored_file = child.name in IGNORED_IMPORT_FILES
            if ignored_directory or ignored_file:
                ignored.append(
                    {
                        "relative_path": portable_relative,
                        "kind": "directory" if ignored_directory else "file",
                    }
                )
                continue
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                blockers.append(f"Source entry could not be inspected: {portable_relative}: {exc}")
                continue
            if child.is_symlink() or _stat_is_reparse(child_stat):
                blockers.append(f"Symlink or reparse entry is not allowed: {portable_relative}")
                continue
            normalized_path = normalize_project_import_path(child.path)
            if not normalized_path or not _path_is_within(normalized_path, source_directory):
                blockers.append(f"Source entry escapes the Project directory: {portable_relative}")
                continue
            relative_key = portable_relative.casefold()
            real_key = _path_key(normalized_path)
            if relative_key in seen_relative_keys:
                blockers.append(f"Duplicate case-insensitive source path: {portable_relative}")
                continue
            if real_key in seen_real_paths:
                blockers.append(f"Duplicate resolved source entry: {portable_relative}")
                continue
            seen_relative_keys.add(relative_key)
            seen_real_paths.add(real_key)
            if stat.S_ISDIR(child_stat.st_mode):
                entries.append(
                    {
                        "kind": "directory",
                        "relative_path": portable_relative,
                        "source_path": normalized_path,
                        "size": 0,
                        "mtime_ns": int(getattr(child_stat, "st_mtime_ns", 0) or 0),
                    }
                )
                visit(child.path, relative_path)
            elif stat.S_ISREG(child_stat.st_mode):
                entries.append(
                    {
                        "kind": "file",
                        "relative_path": portable_relative,
                        "source_path": normalized_path,
                        "size": int(child_stat.st_size),
                        "mtime_ns": int(getattr(child_stat, "st_mtime_ns", 0) or 0),
                    }
                )
            else:
                blockers.append(f"Non-regular source entry is not allowed: {portable_relative}")

    visit(source_directory)
    return {
        "entries": entries,
        "ignored": ignored,
        "blockers": blockers,
    }


def _classify_path_value(
    value: object,
    *,
    field: str,
    source_root: str,
    destination_root: str,
    owner_source_directory: str,
    owner_destination_directory: str,
    mode: str,
    missing_severity: str,
) -> dict:
    raw_value = str(value or "")
    result = {
        "field": field,
        "original": raw_value,
        "rewritten": raw_value,
        "classification": "empty",
        "source_relative_path": "",
        "exists": False,
        "missing_severity": missing_severity,
    }
    if not raw_value:
        return result

    if not os.path.isabs(os.path.expanduser(raw_value)):
        resolved = normalize_project_import_path(
            os.path.join(owner_source_directory, os.path.expanduser(raw_value))
        )
        result["classification"] = "relative"
        result["exists"] = bool(resolved and os.path.exists(resolved))
        if not resolved or not _path_is_within(resolved, source_root):
            result["classification"] = "unsafe_relative"
            return result
        result["source_relative_path"] = os.path.relpath(resolved, source_root).replace(os.sep, "/")
        return result

    normalized = normalize_project_import_path(raw_value)
    if not normalized:
        result["classification"] = "invalid_absolute"
        return result
    result["exists"] = os.path.exists(normalized)
    if not _path_is_within(normalized, source_root):
        result["classification"] = "external_absolute"
        return result

    source_relative = os.path.relpath(normalized, source_root)
    portable_source_relative = source_relative.replace(os.sep, "/")
    destination_absolute = os.path.normpath(
        os.path.join(destination_root, source_relative)
    )
    result["classification"] = "internal_absolute"
    result["source_relative_path"] = portable_source_relative
    if mode == "destination_absolute":
        result["rewritten"] = destination_absolute
    elif _path_is_within(normalized, owner_source_directory):
        result["rewritten"] = os.path.relpath(
            destination_absolute,
            owner_destination_directory,
        ).replace(os.sep, "/")
    else:
        result["rewritten"] = destination_absolute
    return result


def _record_path(
    container: object,
    key: str,
    *,
    field: str,
    source_root: str,
    destination_root: str,
    owner_source_directory: str,
    owner_destination_directory: str,
    analysis: dict,
    mode: str = "project_relative",
    missing_severity: str = "warning",
) -> None:
    if not isinstance(container, dict) or key not in container:
        return
    detail = _classify_path_value(
        container.get(key),
        field=field,
        source_root=source_root,
        destination_root=destination_root,
        owner_source_directory=owner_source_directory,
        owner_destination_directory=owner_destination_directory,
        mode=mode,
        missing_severity=missing_severity,
    )
    classification = detail["classification"]
    if classification == "empty":
        return
    analysis["references"].append(detail)
    if classification == "internal_absolute" and detail["rewritten"] != detail["original"]:
        container[key] = detail["rewritten"]
        analysis["rewrites"].append(detail)
    elif classification == "external_absolute":
        analysis["external_paths"].append(detail)
    elif classification == "relative":
        analysis["relative_paths"].append(detail)
    elif classification in {"unsafe_relative", "invalid_absolute"}:
        analysis["blockers"].append(f"Unsafe known path field {field}: {detail['original']}")

    if classification in {"internal_absolute", "relative"} and not detail["exists"]:
        message = f"Missing Project-local reference {field}: {detail['original']}"
        if missing_severity == "blocker":
            analysis["blockers"].append(message)
        else:
            analysis["warnings"].append(message)
    elif classification == "external_absolute" and not detail["exists"]:
        analysis["warnings"].append(f"Missing external reference {field}: {detail['original']}")


def _record_nested_lineage_paths(
    lineage: object,
    *,
    prefix: str,
    source_root: str,
    destination_root: str,
    owner_source_directory: str,
    owner_destination_directory: str,
    analysis: dict,
) -> None:
    if not isinstance(lineage, dict):
        return
    for key in ("candidate_image_path", "parent_image_path"):
        _record_path(
            lineage,
            key,
            field=f"{prefix}.{key}",
            source_root=source_root,
            destination_root=destination_root,
            owner_source_directory=owner_source_directory,
            owner_destination_directory=owner_destination_directory,
            analysis=analysis,
        )
    adoption = lineage.get("candidate_image_adoption")
    _record_path(
        adoption,
        "candidate_image_path",
        field=f"{prefix}.candidate_image_adoption.candidate_image_path",
        source_root=source_root,
        destination_root=destination_root,
        owner_source_directory=owner_source_directory,
        owner_destination_directory=owner_destination_directory,
        analysis=analysis,
    )
    swap = lineage.get("candidate_image_swap")
    for key in ("new_main_image_path", "previous_main_image_path"):
        _record_path(
            swap,
            key,
            field=f"{prefix}.candidate_image_swap.{key}",
            source_root=source_root,
            destination_root=destination_root,
            owner_source_directory=owner_source_directory,
            owner_destination_directory=owner_destination_directory,
            analysis=analysis,
        )


def rebase_project_json_paths(
    raw_project: dict,
    *,
    source_root: str,
    destination_root: str,
    source_project_path: str,
    destination_project_path: str,
) -> tuple[dict, dict]:
    data = copy.deepcopy(raw_project)
    analysis = {
        "rewrites": [],
        "external_paths": [],
        "relative_paths": [],
        "references": [],
        "warnings": [],
        "blockers": [],
    }
    owner_source_directory = os.path.dirname(source_project_path)
    owner_destination_directory = os.path.dirname(destination_project_path)

    _record_path(
        data,
        "source_directory",
        field="source_directory",
        source_root=source_root,
        destination_root=destination_root,
        owner_source_directory=owner_source_directory,
        owner_destination_directory=owner_destination_directory,
        analysis=analysis,
        mode="destination_absolute",
    )

    metadata = data.get("project_metadata")
    if isinstance(metadata, dict):
        image_imports = metadata.get("image_imports")
        for import_index, image_import in enumerate(image_imports if isinstance(image_imports, list) else []):
            _record_path(
                image_import,
                "source_directory",
                field=f"project_metadata.image_imports[{import_index}].source_directory",
                source_root=source_root,
                destination_root=destination_root,
                owner_source_directory=owner_source_directory,
                owner_destination_directory=owner_destination_directory,
                analysis=analysis,
                mode="destination_absolute",
            )
            images = image_import.get("images") if isinstance(image_import, dict) else []
            for image_index, image in enumerate(images if isinstance(images, list) else []):
                _record_path(
                    image,
                    "path",
                    field=f"project_metadata.image_imports[{import_index}].images[{image_index}].path",
                    source_root=source_root,
                    destination_root=destination_root,
                    owner_source_directory=owner_source_directory,
                    owner_destination_directory=owner_destination_directory,
                    analysis=analysis,
                    mode="destination_absolute",
                )

    prompt_lines = data.get("prompt_lines")
    for line_index, line in enumerate(prompt_lines if isinstance(prompt_lines, list) else []):
        if not isinstance(line, dict):
            continue
        prefix = f"prompt_lines[{line_index}]"
        for key in ("image_path", "generated_image_path", "selected_candidate_path"):
            _record_path(
                line,
                key,
                field=f"{prefix}.{key}",
                source_root=source_root,
                destination_root=destination_root,
                owner_source_directory=owner_source_directory,
                owner_destination_directory=owner_destination_directory,
                analysis=analysis,
                missing_severity="blocker" if key in {"image_path", "selected_candidate_path", "generated_image_path"} else "warning",
            )
        candidates = line.get("generated_candidates")
        for candidate_index, candidate in enumerate(candidates if isinstance(candidates, list) else []):
            for key in ("path", "previous_main_image_path"):
                _record_path(
                    candidate,
                    key,
                    field=f"{prefix}.generated_candidates[{candidate_index}].{key}",
                    source_root=source_root,
                    destination_root=destination_root,
                    owner_source_directory=owner_source_directory,
                    owner_destination_directory=owner_destination_directory,
                    analysis=analysis,
                )
        variants = line.get("gallery_variants")
        for variant_index, variant in enumerate(variants if isinstance(variants, list) else []):
            variant_prefix = f"{prefix}.gallery_variants[{variant_index}]"
            _record_path(
                variant,
                "path",
                field=f"{variant_prefix}.path",
                source_root=source_root,
                destination_root=destination_root,
                owner_source_directory=owner_source_directory,
                owner_destination_directory=owner_destination_directory,
                analysis=analysis,
            )
            if isinstance(variant, dict):
                _record_nested_lineage_paths(
                    variant.get("lineage_info"),
                    prefix=f"{variant_prefix}.lineage_info",
                    source_root=source_root,
                    destination_root=destination_root,
                    owner_source_directory=owner_source_directory,
                    owner_destination_directory=owner_destination_directory,
                    analysis=analysis,
                )
                _record_path(
                    variant.get("source_generation_info"),
                    "source_image_path",
                    field=f"{variant_prefix}.source_generation_info.source_image_path",
                    source_root=source_root,
                    destination_root=destination_root,
                    owner_source_directory=owner_source_directory,
                    owner_destination_directory=owner_destination_directory,
                    analysis=analysis,
                )
        _record_nested_lineage_paths(
            line.get("lineage_info"),
            prefix=f"{prefix}.lineage_info",
            source_root=source_root,
            destination_root=destination_root,
            owner_source_directory=owner_source_directory,
            owner_destination_directory=owner_destination_directory,
            analysis=analysis,
        )
        _record_path(
            line.get("source_generation_info"),
            "source_image_path",
            field=f"{prefix}.source_generation_info.source_image_path",
            source_root=source_root,
            destination_root=destination_root,
            owner_source_directory=owner_source_directory,
            owner_destination_directory=owner_destination_directory,
            analysis=analysis,
        )

    snapshots = data.get("route_snapshots")
    for snapshot_index, snapshot in enumerate(snapshots if isinstance(snapshots, list) else []):
        items = snapshot.get("items") if isinstance(snapshot, dict) else []
        for item_index, item in enumerate(items if isinstance(items, list) else []):
            for key in ("selected_candidate_path", "generated_image_path", "reference_image_path"):
                _record_path(
                    item,
                    key,
                    field=f"route_snapshots[{snapshot_index}].items[{item_index}].{key}",
                    source_root=source_root,
                    destination_root=destination_root,
                    owner_source_directory=owner_source_directory,
                    owner_destination_directory=owner_destination_directory,
                    analysis=analysis,
                )

    analysis["warnings"] = _unique_messages(analysis["warnings"])
    analysis["blockers"] = _unique_messages(analysis["blockers"])
    return data, analysis


def _record_manifest_entry_paths(
    records: object,
    *,
    prefix: str,
    source_root: str,
    destination_root: str,
    owner_source_directory: str,
    owner_destination_directory: str,
    analysis: dict,
) -> None:
    for index, record in enumerate(records if isinstance(records, list) else []):
        _record_path(
            record,
            "source_image_path",
            field=f"{prefix}[{index}].source_image_path",
            source_root=source_root,
            destination_root=destination_root,
            owner_source_directory=owner_source_directory,
            owner_destination_directory=owner_destination_directory,
            analysis=analysis,
            mode="destination_absolute",
        )


def rebase_fork_manifest_paths(
    raw_manifest: dict,
    *,
    source_root: str,
    destination_root: str,
    source_manifest_path: str,
    destination_manifest_path: str,
) -> tuple[dict, dict]:
    manifest = copy.deepcopy(raw_manifest)
    analysis = {
        "rewrites": [],
        "external_paths": [],
        "relative_paths": [],
        "references": [],
        "warnings": [],
        "blockers": [],
    }
    owner_source_directory = os.path.dirname(source_manifest_path)
    owner_destination_directory = os.path.dirname(destination_manifest_path)
    for key in ("source_project_path", "destination_project_path", "destination_manifest_path"):
        _record_path(
            manifest,
            key,
            field=key,
            source_root=source_root,
            destination_root=destination_root,
            owner_source_directory=owner_source_directory,
            owner_destination_directory=owner_destination_directory,
            analysis=analysis,
            mode="destination_absolute",
            missing_severity="blocker" if key == "source_project_path" else "warning",
        )
    _record_manifest_entry_paths(
        manifest.get("materialized_entries"),
        prefix="materialized_entries",
        source_root=source_root,
        destination_root=destination_root,
        owner_source_directory=owner_source_directory,
        owner_destination_directory=owner_destination_directory,
        analysis=analysis,
    )
    history = manifest.get("append_history")
    for history_index, record in enumerate(history if isinstance(history, list) else []):
        _record_path(
            record,
            "source_project_path",
            field=f"append_history[{history_index}].source_project_path",
            source_root=source_root,
            destination_root=destination_root,
            owner_source_directory=owner_source_directory,
            owner_destination_directory=owner_destination_directory,
            analysis=analysis,
            mode="destination_absolute",
            missing_severity="blocker",
        )
        if isinstance(record, dict):
            _record_manifest_entry_paths(
                record.get("materialized_entries"),
                prefix=f"append_history[{history_index}].materialized_entries",
                source_root=source_root,
                destination_root=destination_root,
                owner_source_directory=owner_source_directory,
                owner_destination_directory=owner_destination_directory,
                analysis=analysis,
            )
    analysis["warnings"] = _unique_messages(analysis["warnings"])
    analysis["blockers"] = _unique_messages(analysis["blockers"])
    return manifest, analysis


def discover_import_source_project(
    source_project_path: object,
    destination_root: object,
) -> dict:
    raw_source_path = ""
    try:
        raw_source_path = os.path.abspath(os.path.expanduser(os.fspath(source_project_path).strip()))
    except (OSError, TypeError, ValueError):
        pass
    normalized_source_path = normalize_project_import_path(source_project_path)
    normalized_root = normalize_project_import_path(destination_root)
    result = {
        "valid": False,
        "source_project_path": normalized_source_path,
        "source_directory": os.path.dirname(normalized_source_path) if normalized_source_path else "",
        "destination_root": normalized_root,
        "raw_project": {},
        "warnings": [],
        "blockers": [],
    }
    if not raw_source_path or not normalized_source_path:
        result["blockers"].append("Source Project JSON path is invalid.")
        return result
    if not os.path.isfile(raw_source_path):
        result["blockers"].append("Source Project JSON is missing or is not a file.")
        return result
    if _path_is_link_or_reparse(raw_source_path):
        result["blockers"].append("Source Project JSON is a symlink or reparse point.")
        return result
    source_directory = os.path.dirname(normalized_source_path)
    if not os.path.isdir(source_directory):
        result["blockers"].append("Source Project directory is missing.")
        return result
    if _path_is_link_or_reparse(os.path.dirname(raw_source_path)):
        result["blockers"].append("Source Project directory is a symlink or reparse point.")
    if not normalized_root:
        result["blockers"].append("Destination Project root is invalid.")
    elif _same_path(source_directory, normalized_root) or _path_is_within(source_directory, normalized_root):
        result["blockers"].append(
            "This Project is already inside the effective Project root. Open it from the Project Directory Browser."
        )
    elif _path_is_within(normalized_root, source_directory):
        result["blockers"].append("Destination Project root must not be inside the source Project directory.")
    if normalized_root and os.path.lexists(normalized_root):
        if not os.path.isdir(normalized_root):
            result["blockers"].append("Destination Project root is not a directory.")
        elif _path_is_link_or_reparse(normalized_root):
            result["blockers"].append("Destination Project root is a symlink or reparse point.")
    raw_project, project_error = _validate_project_json(normalized_source_path)
    if project_error:
        result["blockers"].append(project_error)
    else:
        result["raw_project"] = raw_project
    result["blockers"] = _unique_messages(result["blockers"])
    result["valid"] = not result["blockers"]
    return result


def _project_plan(
    source_path: str,
    relative_path: str,
    raw: dict,
    *,
    source_root: str,
    destination_root: str,
) -> dict:
    destination_path = os.path.join(destination_root, relative_path.replace("/", os.sep))
    _rewritten, analysis = rebase_project_json_paths(
        raw,
        source_root=source_root,
        destination_root=destination_root,
        source_project_path=source_path,
        destination_project_path=destination_path,
    )
    return {
        "source_path": source_path,
        "relative_path": relative_path,
        "destination_path": destination_path,
        "digest": _file_digest(source_path),
        "analysis": analysis,
    }


def _empty_path_analysis() -> dict:
    return {
        "rewrites": [],
        "external_paths": [],
        "relative_paths": [],
        "references": [],
        "warnings": [],
        "blockers": [],
    }


def _resolve_manifest_relation_path(value: object, source_manifest_path: str) -> str:
    try:
        raw_value = os.fspath(value).strip() if value is not None else ""
    except (OSError, TypeError, ValueError):
        return ""
    if not raw_value or "\x00" in raw_value:
        return ""
    expanded = os.path.expanduser(raw_value)
    candidate = (
        expanded
        if os.path.isabs(expanded)
        else os.path.join(os.path.dirname(source_manifest_path), expanded)
    )
    return normalize_project_import_path(candidate)


def _enforce_manifest_relationship_rewrites(
    rewritten: dict,
    raw: dict,
    analysis: dict,
    expected_paths: dict[str, str],
) -> None:
    for field, expected in expected_paths.items():
        original = str(raw.get(field) or "")
        rewritten[field] = expected
        for category in ("external_paths", "relative_paths"):
            analysis[category] = [
                item for item in analysis[category] if item.get("field") != field
            ]
        existing = next(
            (item for item in analysis["rewrites"] if item.get("field") == field),
            None,
        )
        if existing is not None:
            existing["rewritten"] = expected
        elif original != expected:
            analysis["rewrites"].append(
                {
                    "field": field,
                    "original": original,
                    "rewritten": expected,
                    "classification": "manifest_relationship",
                    "source_relative_path": "",
                    "exists": True,
                    "missing_severity": "blocker",
                }
            )


def _manifest_plan(
    source_path: str,
    relative_path: str,
    raw: dict,
    *,
    source_root: str,
    destination_root: str,
    source_project_mapping: dict[str, str],
    source_fork_project_path: str,
    destination_fork_project_path: str,
) -> dict:
    destination_path = os.path.join(destination_root, relative_path.replace("/", os.sep))
    original_source_project_path = _resolve_manifest_relation_path(
        raw.get("source_project_path"), source_path
    )
    original_destination_project_path = _resolve_manifest_relation_path(
        raw.get("destination_project_path"), source_path
    )
    original_destination_manifest_path = _resolve_manifest_relation_path(
        raw.get("destination_manifest_path"), source_path
    )
    expected_source_project_path = source_project_mapping.get(
        _path_key(original_source_project_path), ""
    )
    expected_paths = {
        "source_project_path": expected_source_project_path,
        "destination_project_path": destination_fork_project_path,
        "destination_manifest_path": destination_path,
    }
    relation_reason = ""
    if raw.get("operation") != MANIFEST_OPERATION or raw.get("manifest_version") != SUPPORTED_MANIFEST_VERSION:
        relation_reason = "Fork manifest operation/version is unsupported."
    elif not expected_source_project_path:
        relation_reason = (
            "Fork manifest source Project is not one of the valid Project JSONs included in this import."
        )
    elif not _same_path(original_destination_project_path, source_fork_project_path):
        relation_reason = "Fork manifest destination Project does not match its actual Fork project.json."
    elif not _same_path(original_destination_manifest_path, source_path):
        relation_reason = "Fork manifest destination manifest does not match its actual manifest.json."
    elif (
        not _path_is_within(expected_source_project_path, destination_root)
        or not _path_is_within(destination_fork_project_path, destination_root)
        or not _path_is_within(destination_path, destination_root)
    ):
        relation_reason = "Fork manifest destination relationship escapes the imported Project directory."

    analysis = _empty_path_analysis()
    if not relation_reason:
        rewritten, analysis = rebase_fork_manifest_paths(
            raw,
            source_root=source_root,
            destination_root=destination_root,
            source_manifest_path=source_path,
            destination_manifest_path=destination_path,
        )
        _enforce_manifest_relationship_rewrites(rewritten, raw, analysis, expected_paths)
    plan = {
        "source_path": source_path,
        "relative_path": relative_path,
        "destination_path": destination_path,
        "digest": _file_digest(source_path),
        "analysis": analysis,
        "source_manifest_source_project_path": original_source_project_path,
        "expected_destination_source_project_path": expected_source_project_path,
        "expected_destination_fork_project_path": destination_fork_project_path,
        "expected_destination_manifest_path": destination_path,
        "relation_valid": not relation_reason,
        "relation_reason": relation_reason,
    }
    return plan


def build_project_root_import_signature(preview: dict) -> dict:
    return {
        "source_project_path": preview.get("source_project_path", ""),
        "source_project_digest": preview.get("source_project_digest", ""),
        "source_directory": preview.get("source_directory", ""),
        "destination_root": preview.get("destination_root", ""),
        "destination_name": preview.get("destination_name", ""),
        "destination_directory": preview.get("destination_directory", ""),
        # A directory's mtime can be published lazily on Windows after its
        # children were created. Child paths already expose additions/removals,
        # so only regular-file mtimes are stable signature inputs.
        "inventory": _inventory_signature_rows(preview.get("source_inventory", [])),
        "project_jsons": tuple(
            (plan.get("relative_path", ""), plan.get("digest", ""))
            for plan in preview.get("project_json_plans", [])
        ),
        "fork_manifests": tuple(
            (
                plan.get("relative_path", ""),
                plan.get("digest", ""),
                plan.get("source_manifest_source_project_path", ""),
                plan.get("expected_destination_source_project_path", ""),
                plan.get("expected_destination_fork_project_path", ""),
                plan.get("expected_destination_manifest_path", ""),
                bool(plan.get("relation_valid")),
                plan.get("relation_reason", ""),
            )
            for plan in preview.get("fork_manifest_plans", [])
        ),
        "ignored": _ignored_signature_rows(preview.get("ignored", [])),
        "rewrite_plan": tuple(
            (
                item.get("field", ""),
                item.get("original", ""),
                item.get("rewritten", ""),
            )
            for item in preview.get("rewrites", [])
        ),
        "external_dependencies": tuple(
            (item.get("field", ""), item.get("original", ""))
            for item in preview.get("external_paths", [])
        ),
    }


def _inventory_signature_rows(entries: Iterable[dict]) -> tuple:
    return tuple(
        (
            entry.get("kind", ""),
            entry.get("relative_path", ""),
            entry.get("size", 0),
            entry.get("mtime_ns", 0) if entry.get("kind") == "file" else 0,
        )
        for entry in entries
    )


def _ignored_signature_rows(entries: Iterable[dict]) -> tuple:
    return tuple(
        (entry.get("kind", ""), entry.get("relative_path", ""))
        for entry in entries
    )


def build_project_root_import_preview(
    source_project_path: object,
    destination_root: object,
    destination_name: object,
) -> dict:
    source = discover_import_source_project(source_project_path, destination_root)
    source_path = source.get("source_project_path", "")
    source_directory = source.get("source_directory", "")
    default_name = sanitize_project_import_name(os.path.basename(source_directory))
    requested_name = str(destination_name or "").strip() or default_name
    destination = _destination_paths(destination_root, requested_name, source_path)
    preview = {
        "valid": False,
        "source_project_path": source_path,
        "source_project_digest": "",
        "source_directory": source_directory,
        "destination_root": destination.get("destination_root", ""),
        "destination_name": destination.get("destination_name", ""),
        "destination_directory": destination.get("destination_directory", ""),
        "destination_project_path": destination.get("destination_project_path", ""),
        "source_inventory": [],
        "project_json_plans": [],
        "fork_manifest_plans": [],
        "rewrites": [],
        "external_paths": [],
        "relative_paths": [],
        "ignored": [],
        "warnings": list(source.get("warnings", [])),
        "blockers": list(source.get("blockers", [])),
        "diagnostics": [],
        "counts": {},
        "signature": {},
        "signature_digest": "",
    }
    if destination.get("error"):
        preview["blockers"].append(destination["error"])
    if not source.get("valid") or not destination.get("valid"):
        preview["blockers"] = _unique_messages(preview["blockers"])
        preview["counts"] = {
            "project_json_count": 0,
            "fork_count": 0,
            "file_count": 0,
            "total_bytes": 0,
            "ignored_count": 0,
            "rewrite_count": 0,
            "relative_path_count": 0,
            "external_path_count": 0,
            "fork_manifest_rewrite_count": 0,
            "auxiliary_json_warning_count": 0,
        }
        return preview

    inventory = _inventory_source_directory(source_directory)
    preview["source_inventory"] = inventory["entries"]
    preview["ignored"] = inventory["ignored"]
    preview["blockers"].extend(inventory["blockers"])
    file_entries = [entry for entry in inventory["entries"] if entry.get("kind") == "file"]
    file_by_relative = {
        entry["relative_path"]: entry for entry in file_entries
    }
    primary_relative = os.path.relpath(source_path, source_directory).replace(os.sep, "/")
    auxiliary_warnings = 0
    project_plans = []
    fork_plans = []
    manifest_plans = []

    direct_json_entries = [
        entry
        for entry in file_entries
        if "/" not in entry["relative_path"]
        and not _project_json_candidate_reason(os.path.basename(entry["relative_path"]))
    ]
    for entry in direct_json_entries:
        candidate_path = entry["source_path"]
        raw, error = _validate_project_json(candidate_path)
        if error:
            if entry["relative_path"] == primary_relative:
                preview["blockers"].append(error)
            else:
                try:
                    parsed = _read_json(candidate_path)
                except Exception as exc:
                    parsed = None
                    preview["warnings"].append(
                        f"Auxiliary JSON copied unchanged: {entry['relative_path']}: {exc}"
                    )
                    auxiliary_warnings += 1
                if isinstance(parsed, dict) and isinstance(parsed.get("prompt_lines"), list):
                    preview["warnings"].append(
                        f"Project-like sibling JSON copied unchanged: {entry['relative_path']}: {error}"
                    )
                    auxiliary_warnings += 1
            continue
        project_plans.append(
            _project_plan(
                candidate_path,
                entry["relative_path"],
                raw,
                source_root=source_directory,
                destination_root=preview["destination_directory"],
            )
        )

    source_project_mapping = {
        _path_key(plan["source_path"]): normalize_project_import_path(plan["destination_path"])
        for plan in project_plans
        if _path_key(plan.get("source_path"))
    }

    fork_project_entries = []
    for relative_path, entry in file_by_relative.items():
        parts = relative_path.split("/")
        if len(parts) == 3 and parts[0].casefold() == "forks" and parts[2].casefold() == "project.json":
            fork_project_entries.append(entry)
    for entry in sorted(fork_project_entries, key=lambda item: _natural_key(item["relative_path"])):
        raw, error = _validate_project_json(entry["source_path"])
        if error:
            preview["warnings"].append(
                f"Fork Project JSON copied unchanged and will not be validated: {entry['relative_path']}: {error}"
            )
            auxiliary_warnings += 1
            continue
        plan = _project_plan(
            entry["source_path"],
            entry["relative_path"],
            raw,
            source_root=source_directory,
            destination_root=preview["destination_directory"],
        )
        project_plans.append(plan)
        fork_plans.append(plan)
        manifest_relative = "/".join(entry["relative_path"].split("/")[:2] + ["manifest.json"])
        manifest_entry = file_by_relative.get(manifest_relative)
        if not manifest_entry:
            preview["warnings"].append(
                f"Fork manifest is missing; the Fork Project will remain openable but Append compatibility is not guaranteed: {manifest_relative}"
            )
            auxiliary_warnings += 1
            continue
        try:
            manifest = _read_json(manifest_entry["source_path"])
        except Exception as exc:
            preview["warnings"].append(
                f"Fork manifest copied unchanged because it is unreadable: {manifest_relative}: {exc}"
            )
            auxiliary_warnings += 1
            continue
        if (
            not isinstance(manifest, dict)
            or manifest.get("operation") != MANIFEST_OPERATION
            or manifest.get("manifest_version") != SUPPORTED_MANIFEST_VERSION
        ):
            preview["warnings"].append(
                f"Fork manifest copied unchanged because it is unsupported: {manifest_relative}"
            )
            auxiliary_warnings += 1
            continue
        manifest_plan = _manifest_plan(
            manifest_entry["source_path"],
            manifest_relative,
            manifest,
            source_root=source_directory,
            destination_root=preview["destination_directory"],
            source_project_mapping=source_project_mapping,
            source_fork_project_path=entry["source_path"],
            destination_fork_project_path=plan["destination_path"],
        )
        if not manifest_plan["relation_valid"]:
            preview["blockers"].append(
                f"Fork manifest relationship is invalid: {manifest_relative}: "
                f"{manifest_plan['relation_reason']}"
            )
            continue
        manifest_plans.append(manifest_plan)

    primary_plan = next(
        (plan for plan in project_plans if plan.get("relative_path") == primary_relative),
        None,
    )
    if not primary_plan:
        preview["blockers"].append("Primary Project JSON was not included in the import plan.")
    else:
        preview["source_project_digest"] = primary_plan["digest"]
        preview["destination_project_path"] = primary_plan["destination_path"]

    all_analyses = [plan["analysis"] for plan in project_plans] + [
        plan["analysis"] for plan in manifest_plans
    ]
    for analysis in all_analyses:
        preview["rewrites"].extend(analysis["rewrites"])
        preview["external_paths"].extend(analysis["external_paths"])
        preview["relative_paths"].extend(analysis["relative_paths"])
        preview["warnings"].extend(analysis["warnings"])
        preview["blockers"].extend(analysis["blockers"])

    preview["project_json_plans"] = sorted(
        project_plans,
        key=lambda plan: _natural_key(plan["relative_path"]),
    )
    preview["fork_manifest_plans"] = sorted(
        manifest_plans,
        key=lambda plan: _natural_key(plan["relative_path"]),
    )
    preview["warnings"] = _unique_messages(preview["warnings"])
    preview["blockers"] = _unique_messages(preview["blockers"])
    preview["counts"] = {
        "project_json_count": len(source_project_mapping),
        "fork_count": len(fork_plans),
        "file_count": len(file_entries),
        "total_bytes": sum(int(entry.get("size", 0) or 0) for entry in file_entries),
        "ignored_count": len(preview["ignored"]),
        "rewrite_count": len(preview["rewrites"]),
        "relative_path_count": len(preview["relative_paths"]),
        "external_path_count": len(preview["external_paths"]),
        "fork_manifest_rewrite_count": sum(
            len(plan["analysis"]["rewrites"]) for plan in manifest_plans
        ),
        "auxiliary_json_warning_count": auxiliary_warnings,
    }
    preview["valid"] = not preview["blockers"]
    preview["signature"] = build_project_root_import_signature(preview)
    preview["signature_digest"] = _canonical_digest(preview["signature"])
    return preview


def _expected_signature_digest(expected_signature: object) -> str:
    if isinstance(expected_signature, str):
        return expected_signature
    if isinstance(expected_signature, dict):
        return _canonical_digest(expected_signature)
    return ""


def _inventory_entry_is_unchanged(entry: dict) -> bool:
    path = str(entry.get("source_path") or "")
    if not path or _path_is_link_or_reparse(path):
        return False
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    if entry.get("kind") == "directory":
        return stat.S_ISDIR(current.st_mode)
    return (
        stat.S_ISREG(current.st_mode)
        and int(current.st_size) == int(entry.get("size", -1))
        and int(getattr(current, "st_mtime_ns", 0) or 0) == int(entry.get("mtime_ns", -1))
    )


def validate_staged_project_import(staging_directory: str, preview: dict) -> dict:
    result = {"valid": False, "warnings": [], "blockers": []}
    destination_directory = preview.get("destination_directory", "")
    if not staging_directory or not os.path.isdir(staging_directory):
        result["blockers"].append("Staging directory is missing.")
        return result

    for plan in preview.get("project_json_plans", []):
        staging_path = os.path.join(
            staging_directory,
            plan.get("relative_path", "").replace("/", os.sep),
        )
        _raw, error = _validate_project_json(staging_path)
        if error:
            result["blockers"].append(
                f"Staged Project validation failed: {plan.get('relative_path')}: {error}"
            )
        for reference in plan.get("analysis", {}).get("references", []):
            relative_path = reference.get("source_relative_path", "")
            if not relative_path or not reference.get("exists"):
                continue
            staged_reference = os.path.join(staging_directory, relative_path.replace("/", os.sep))
            if not os.path.exists(staged_reference) or _path_is_link_or_reparse(staged_reference):
                result["blockers"].append(
                    f"Staged internal reference is missing or unsafe: {reference.get('field')}: {relative_path}"
                )

    for plan in preview.get("fork_manifest_plans", []):
        relative_path = plan.get("relative_path", "")
        staging_manifest_path = os.path.join(staging_directory, relative_path.replace("/", os.sep))
        try:
            manifest = _read_json(staging_manifest_path)
        except Exception as exc:
            result["blockers"].append(f"Staged Fork manifest is unreadable: {relative_path}: {exc}")
            continue
        fork_relative_directory = os.path.dirname(relative_path)
        staging_fork_project = os.path.join(
            staging_directory,
            fork_relative_directory.replace("/", os.sep),
            "project.json",
        )
        snapshot = load_existing_fork_snapshot(staging_fork_project)
        if not snapshot.get("valid"):
            result["blockers"].append(
                f"Staged Fork validation failed: {fork_relative_directory}: {snapshot.get('reason') or 'invalid Fork'}"
            )
        expected_source = plan.get("expected_destination_source_project_path", "")
        expected_project = plan.get("expected_destination_fork_project_path", "")
        expected_manifest = plan.get("expected_destination_manifest_path", "")
        if not plan.get("relation_valid"):
            result["blockers"].append(f"Fork manifest relationship is invalid: {relative_path}")
        if not _same_path(manifest.get("source_project_path", ""), expected_source):
            result["blockers"].append(f"Fork source Project mapping is invalid: {relative_path}")
        if not _same_path(manifest.get("destination_project_path", ""), expected_project):
            result["blockers"].append(f"Fork destination Project mapping is invalid: {relative_path}")
        if not _same_path(manifest.get("destination_manifest_path", ""), expected_manifest):
            result["blockers"].append(f"Fork destination manifest mapping is invalid: {relative_path}")
        if manifest.get("operation") != MANIFEST_OPERATION or manifest.get("manifest_version") != SUPPORTED_MANIFEST_VERSION:
            result["blockers"].append(f"Fork manifest operation/version changed: {relative_path}")

    primary_relative = os.path.relpath(
        preview.get("destination_project_path", ""),
        preview.get("destination_directory", ""),
    )
    staging_primary = os.path.join(staging_directory, primary_relative)
    if not os.path.isfile(staging_primary):
        result["blockers"].append("Staged primary Project JSON is missing.")
    result["blockers"] = _unique_messages(result["blockers"])
    result["valid"] = not result["blockers"]
    return result


def _cleanup_staging(
    staging_directory: str,
    *,
    rmtree: Callable[[str], Any],
    sleep: Callable[[float], Any],
    retry_delays: Iterable[float],
) -> dict:
    if not staging_directory:
        return {"success": True, "attempts": 0, "error": ""}
    return _remove_tree_with_retry(
        staging_directory,
        rmtree=rmtree,
        path_exists=os.path.exists,
        sleep=sleep,
        retry_delays=retry_delays,
    )


def apply_project_root_import(
    stored_preview: dict,
    *,
    expected_signature: object,
    copy_file: Callable[[str, str], Any] = shutil.copy2,
    rename: Callable[[str, str], Any] = os.rename,
    rmtree: Callable[[str], Any] = shutil.rmtree,
    sleep: Callable[[float], Any] = time.sleep,
    retry_delays: Iterable[float] = WINDOWS_RETRY_DELAYS,
) -> dict:
    result = {
        "success": False,
        "error": "",
        "stale_preview": False,
        "conflict": False,
        "cleanup_error": "",
        "staging_directory": "",
        "destination_directory": str((stored_preview or {}).get("destination_directory") or ""),
        "destination_project_path": str((stored_preview or {}).get("destination_project_path") or ""),
        "source_directory": str((stored_preview or {}).get("source_directory") or ""),
        "copied_file_count": 0,
        "copied_bytes": 0,
        "rewritten_path_count": 0,
        "retained_external_path_count": 0,
        "commit_attempts": 0,
        "commit_retry_performed": False,
    }
    if not isinstance(stored_preview, dict) or not stored_preview.get("valid"):
        result["error"] = "A valid Project Import Preview is required."
        return result
    try:
        fresh_preview = build_project_root_import_preview(
            stored_preview.get("source_project_path", ""),
            stored_preview.get("destination_root", ""),
            stored_preview.get("destination_name", ""),
        )
    except Exception as exc:
        result["error"] = f"Fresh Project Import Preview failed: {exc}"
        result["stale_preview"] = True
        return result
    expected_digest = _expected_signature_digest(expected_signature)
    if (
        not fresh_preview.get("valid")
        or not expected_digest
        or fresh_preview.get("signature_digest") != expected_digest
    ):
        result["error"] = "Project Import Preview is stale. Generate a new Preview."
        result["stale_preview"] = True
        return result

    destination_root = fresh_preview["destination_root"]
    destination_directory = fresh_preview["destination_directory"]
    result.update(
        {
            "destination_directory": destination_directory,
            "destination_project_path": fresh_preview["destination_project_path"],
            "source_directory": fresh_preview["source_directory"],
            "rewritten_path_count": fresh_preview["counts"]["rewrite_count"],
            "retained_external_path_count": fresh_preview["counts"]["external_path_count"],
        }
    )
    staging_directory = ""
    try:
        if os.path.lexists(destination_root):
            if not os.path.isdir(destination_root) or _path_is_link_or_reparse(destination_root):
                raise OSError("Destination Project root is missing, unsafe, or not a directory.")
        else:
            os.makedirs(destination_root, exist_ok=False)
        if os.path.lexists(destination_directory) or _destination_conflict(
            destination_root,
            fresh_preview["destination_name"],
        ):
            result["error"] = "Destination already exists."
            result["conflict"] = True
            return result

        staging_directory = tempfile.mkdtemp(
            prefix=".promptgraph-import-",
            dir=destination_root,
        )
        result["staging_directory"] = staging_directory
        for entry in fresh_preview["source_inventory"]:
            if not _inventory_entry_is_unchanged(entry):
                raise ProjectRootImportStaleError(
                    f"Source changed before copy: {entry.get('relative_path')}"
                )
            destination_path = os.path.join(
                staging_directory,
                entry["relative_path"].replace("/", os.sep),
            )
            if entry["kind"] == "directory":
                os.makedirs(destination_path, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(destination_path), exist_ok=True)
            source_path = entry["source_path"]
            before = os.stat(source_path, follow_symlinks=False)
            copy_file(source_path, destination_path)
            after = os.stat(source_path, follow_symlinks=False)
            if (
                int(before.st_size) != int(after.st_size)
                or int(getattr(before, "st_mtime_ns", 0) or 0)
                != int(getattr(after, "st_mtime_ns", 0) or 0)
            ):
                raise ProjectRootImportStaleError(
                    f"Source changed during copy: {entry.get('relative_path')}"
                )
            copied_stat = os.stat(destination_path, follow_symlinks=False)
            if not stat.S_ISREG(copied_stat.st_mode) or int(copied_stat.st_size) != int(entry["size"]):
                raise OSError(f"Copied file size mismatch: {entry.get('relative_path')}")
            result["copied_file_count"] += 1
            result["copied_bytes"] += int(entry["size"])

        for plan in fresh_preview["project_json_plans"]:
            raw = _read_json_matching_digest(plan["source_path"], plan["digest"])
            rewritten, analysis = rebase_project_json_paths(
                raw,
                source_root=fresh_preview["source_directory"],
                destination_root=destination_directory,
                source_project_path=plan["source_path"],
                destination_project_path=plan["destination_path"],
            )
            if analysis["blockers"]:
                raise ValueError(analysis["blockers"][0])
            staging_path = os.path.join(staging_directory, plan["relative_path"].replace("/", os.sep))
            _write_json(staging_path, rewritten)

        for plan in fresh_preview["fork_manifest_plans"]:
            raw = _read_json_matching_digest(plan["source_path"], plan["digest"])
            rewritten, analysis = rebase_fork_manifest_paths(
                raw,
                source_root=fresh_preview["source_directory"],
                destination_root=destination_directory,
                source_manifest_path=plan["source_path"],
                destination_manifest_path=plan["destination_path"],
            )
            if analysis["blockers"]:
                raise ValueError(analysis["blockers"][0])
            _enforce_manifest_relationship_rewrites(
                rewritten,
                raw,
                analysis,
                {
                    "source_project_path": plan["expected_destination_source_project_path"],
                    "destination_project_path": plan["expected_destination_fork_project_path"],
                    "destination_manifest_path": plan["expected_destination_manifest_path"],
                },
            )
            staging_path = os.path.join(staging_directory, plan["relative_path"].replace("/", os.sep))
            _write_json(staging_path, rewritten)

        validation = validate_staged_project_import(staging_directory, fresh_preview)
        if not validation.get("valid"):
            raise ValueError(validation.get("blockers", ["Staged Project validation failed."])[0])
        final_inventory = _inventory_source_directory(fresh_preview["source_directory"])
        if (
            final_inventory.get("blockers")
            or _inventory_signature_rows(final_inventory.get("entries", []))
            != _inventory_signature_rows(fresh_preview.get("source_inventory", []))
            or _ignored_signature_rows(final_inventory.get("ignored", []))
            != _ignored_signature_rows(fresh_preview.get("ignored", []))
        ):
            raise ProjectRootImportStaleError(
                "Source inventory changed before commit. Generate a new Preview."
            )
        if os.path.lexists(destination_directory) or _destination_conflict(
            destination_root,
            fresh_preview["destination_name"],
        ):
            result["error"] = "Destination appeared before commit."
            result["conflict"] = True
            cleanup = _cleanup_staging(
                staging_directory,
                rmtree=rmtree,
                sleep=sleep,
                retry_delays=retry_delays,
            )
            if cleanup.get("success"):
                staging_directory = ""
                result["staging_directory"] = ""
            else:
                result["cleanup_error"] = cleanup.get("error", "staging cleanup failed")
            return result

        commit = _commit_directory_with_retry(
            staging_directory,
            destination_directory,
            rename=rename,
            path_exists=os.path.exists,
            sleep=sleep,
            retry_delays=retry_delays,
        )
        result["commit_attempts"] = int(commit.get("attempts", 0) or 0)
        result["commit_retry_performed"] = bool(commit.get("retry_performed"))
        result["conflict"] = bool(commit.get("conflict"))
        if not commit.get("success"):
            result["error"] = commit.get("error", "Project Import commit failed.")
            cleanup = _cleanup_staging(
                staging_directory,
                rmtree=rmtree,
                sleep=sleep,
                retry_delays=retry_delays,
            )
            if cleanup.get("success"):
                staging_directory = ""
                result["staging_directory"] = ""
            else:
                result["cleanup_error"] = cleanup.get("error", "staging cleanup failed")
            return result
        staging_directory = ""
        result["staging_directory"] = ""
        result["success"] = True
        return result
    except ProjectRootImportStaleError as exc:
        result["error"] = str(exc)
        result["stale_preview"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if staging_directory:
            cleanup = _cleanup_staging(
                staging_directory,
                rmtree=rmtree,
                sleep=sleep,
                retry_delays=retry_delays,
            )
            if cleanup.get("success"):
                result["staging_directory"] = ""
            else:
                result["cleanup_error"] = cleanup.get("error", "staging cleanup failed")
    return result
