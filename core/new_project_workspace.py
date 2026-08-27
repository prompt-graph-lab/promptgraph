import os
from collections.abc import Callable

from core.io import ensure_project_folder_layout, save_project_to_json
from core.project import Project


WINDOWS_INVALID_NAME_CHARS = frozenset('<>:"/\\|?*')
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def _invalid_windows_name(name: str) -> bool:
    if any(character in WINDOWS_INVALID_NAME_CHARS or ord(character) < 32 for character in name):
        return True
    return name.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES


def normalize_new_workspace_project_file_name(project_file_name: object) -> tuple[str, str]:
    raw_name = str(project_file_name or "project.json").strip() or "project.json"
    normalized_name = raw_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not normalized_name:
        normalized_name = "project.json"
    if normalized_name in (".", ".."):
        return "", "Project JSON filename is invalid."
    if normalized_name.endswith((" ", ".")):
        return "", "Project JSON filename cannot end with a space or period."
    if _invalid_windows_name(normalized_name):
        return "", "Project JSON filename contains characters that are not allowed on Windows."
    if not normalized_name.lower().endswith(".json"):
        normalized_name += ".json"
    return normalized_name, ""


def resolve_new_workspace_destination(
    parent_dir: object,
    project_name: object,
    project_file_name: object = "project.json",
    *,
    path_exists: Callable[[str], bool] = os.path.lexists,
    path_is_file: Callable[[str], bool] = os.path.isfile,
) -> dict:
    try:
        raw_parent = os.fspath(parent_dir).strip() if parent_dir else ""
    except (TypeError, ValueError):
        raw_parent = ""
    if not raw_parent:
        return {"valid": False, "error": "Parent destination folder is required."}

    try:
        normalized_parent = os.path.abspath(os.path.expanduser(raw_parent))
        if path_is_file(normalized_parent):
            return {
                "valid": False,
                "parent_dir": normalized_parent,
                "error": "Parent destination must be a folder, not a file.",
            }
    except (OSError, TypeError, ValueError) as exc:
        return {"valid": False, "error": f"Parent destination path is invalid: {exc}"}

    raw_project_name = str(project_name or "")
    clean_project_name = raw_project_name.strip()
    if not clean_project_name:
        return {"valid": False, "parent_dir": normalized_parent, "error": "Project name is required."}
    if raw_project_name.rstrip(" .") != raw_project_name:
        return {
            "valid": False,
            "parent_dir": normalized_parent,
            "error": "Project name cannot end with a space or period.",
        }
    if clean_project_name in (".", ".."):
        return {"valid": False, "parent_dir": normalized_parent, "error": "Project name cannot be '.' or '..'."}
    if os.path.isabs(clean_project_name):
        return {
            "valid": False,
            "parent_dir": normalized_parent,
            "error": "Project name must be one folder name, not an absolute path.",
        }
    if "/" in clean_project_name or "\\" in clean_project_name:
        return {
            "valid": False,
            "parent_dir": normalized_parent,
            "error": "Project name cannot contain folder separators.",
        }
    if _invalid_windows_name(clean_project_name):
        return {
            "valid": False,
            "parent_dir": normalized_parent,
            "error": "Project name contains characters that are not allowed on Windows.",
        }

    normalized_file_name, file_name_error = normalize_new_workspace_project_file_name(project_file_name)
    if file_name_error:
        return {"valid": False, "parent_dir": normalized_parent, "error": file_name_error}

    requested_project_dir = os.path.abspath(os.path.join(normalized_parent, clean_project_name))
    try:
        if os.path.commonpath((normalized_parent, requested_project_dir)) != normalized_parent:
            return {
                "valid": False,
                "parent_dir": normalized_parent,
                "error": "Project destination must stay inside the parent folder.",
            }
    except ValueError:
        return {
            "valid": False,
            "parent_dir": normalized_parent,
            "error": "Project destination must stay inside the parent folder.",
        }

    try:
        project_dir, collision_index = _unique_new_workspace_project_dir_with_index(
            requested_project_dir,
            normalized_file_name,
            path_exists=path_exists,
        )
    except (OSError, TypeError, ValueError) as exc:
        return {
            "valid": False,
            "parent_dir": normalized_parent,
            "error": f"Project destination could not be checked: {exc}",
        }

    project_path = os.path.abspath(os.path.join(project_dir, normalized_file_name))
    return {
        "valid": True,
        "parent_dir": normalized_parent,
        "project_name": clean_project_name,
        "requested_project_dir": requested_project_dir,
        "project_dir": project_dir,
        "project_file_name": normalized_file_name,
        "project_path": project_path,
        "collision_index": collision_index,
        "error": "",
    }


def _unique_new_workspace_project_dir_with_index(
    base_dir: str,
    project_file_name: str,
    *,
    path_exists: Callable[[str], bool],
    start_suffix: int = 0,
) -> tuple[str, int]:
    suffix = max(0, int(start_suffix))
    candidate_dir = base_dir if suffix == 0 else f"{base_dir}-{suffix}"
    while path_exists(candidate_dir) or path_exists(os.path.join(candidate_dir, project_file_name)):
        suffix += 1
        candidate_dir = f"{base_dir}-{suffix}"
    return candidate_dir, suffix


def unique_new_workspace_project_dir(
    base_dir: str,
    project_file_name: str,
    *,
    path_exists: Callable[[str], bool] = os.path.lexists,
) -> str:
    candidate_dir, _suffix = _unique_new_workspace_project_dir_with_index(
        base_dir,
        project_file_name,
        path_exists=path_exists,
    )
    return candidate_dir


def create_new_workspace_files(
    project_dir: object,
    project_file_name: object = "project.json",
    *,
    save_project: Callable[[Project, str], None] = save_project_to_json,
    ensure_folder_layout: Callable[[str], dict] = ensure_project_folder_layout,
    path_exists: Callable[[str], bool] = os.path.lexists,
) -> tuple[str | None, str | None]:
    try:
        raw_project_dir = os.fspath(project_dir).strip() if project_dir else ""
    except (TypeError, ValueError):
        raw_project_dir = ""
    if not raw_project_dir:
        return None, "Project folder is required."

    normalized_file_name, file_name_error = normalize_new_workspace_project_file_name(project_file_name)
    if file_name_error:
        return None, file_name_error

    requested_project_dir = os.path.abspath(os.path.expanduser(raw_project_dir))
    next_suffix = 0
    while True:
        candidate_dir, candidate_suffix = _unique_new_workspace_project_dir_with_index(
            requested_project_dir,
            normalized_file_name,
            path_exists=path_exists,
            start_suffix=next_suffix,
        )
        try:
            os.makedirs(candidate_dir, exist_ok=False)
            break
        except FileExistsError:
            next_suffix = candidate_suffix + 1
            continue

    project_path = os.path.join(candidate_dir, normalized_file_name)
    project = Project(source_directory="")
    save_project(project, project_path)
    ensure_folder_layout(project_path)
    return os.path.abspath(project_path), None
