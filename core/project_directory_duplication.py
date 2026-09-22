"""Read-only Project directory duplication planning.

Session access, saving, copying and publishing the copied Project belong to app.
The duplicate flow intentionally sanitizes names differently from New Project;
filesystem and path exceptions propagate to its existing caller.
"""

import os
from collections.abc import Callable


def sanitize_duplicate_project_dir_name(name: str) -> str:
    clean_name = str(name or "").strip()
    clean_name = clean_name.replace("/", "_").replace("\\", "_")
    for char in '<>:"|?*':
        clean_name = clean_name.replace(char, "_")
    clean_name = clean_name.strip(" .")
    if clean_name in ("", ".", ".."):
        return ""
    return clean_name


def source_project_directory(project_path: object) -> tuple[str, str]:
    if not project_path:
        return "", ""
    clean_project_path = os.path.abspath(os.path.expanduser(project_path))
    return clean_project_path, os.path.dirname(clean_project_path)


def default_duplicate_project_dir_name(
    project_path: object,
    *,
    path_exists: Callable[[str], bool] | None = None,
) -> str:
    source_project_path, source_project_dir = source_project_directory(project_path)
    if not source_project_path or not source_project_dir:
        return "MyProject_copy"

    source_name = os.path.basename(source_project_dir) or "Project"
    parent_dir = os.path.dirname(source_project_dir)
    base_name = f"{source_name}_copy"
    candidate_name = base_name
    suffix = 1
    if path_exists is None:
        path_exists = os.path.exists
    while path_exists(os.path.join(parent_dir, candidate_name)):
        candidate_name = f"{base_name}_{suffix}"
        suffix += 1
    return candidate_name


def duplicate_project_destination_dir(project_path: object, destination_name: str) -> str:
    _, source_project_dir = source_project_directory(project_path)
    if not source_project_dir:
        return ""
    clean_name = sanitize_duplicate_project_dir_name(destination_name)
    if not clean_name:
        return ""
    return os.path.abspath(os.path.join(os.path.dirname(source_project_dir), clean_name))


def plan_project_directory_duplication(
    project_path: object,
    destination_name: str,
    *,
    path_is_file: Callable[[str], bool] | None = None,
    path_is_dir: Callable[[str], bool] | None = None,
    path_exists: Callable[[str], bool] | None = None,
) -> dict:
    """Resolve the pre-copy inputs or return the first existing blocker.

    The app checks that a Project is loaded before calling this planner.
    Predicates may be injected for read-only, in-memory characterization.
    """
    source_project_path, source_project_dir = source_project_directory(project_path)
    if not source_project_path:
        return {"valid": False, "error": "現在のプロジェクトパスがありません。"}
    if path_is_file is None:
        path_is_file = os.path.isfile
    if not path_is_file(source_project_path):
        return {"valid": False, "error": "元のプロジェクトJSONが見つかりません。"}
    if path_is_dir is None:
        path_is_dir = os.path.isdir
    if not path_is_dir(source_project_dir):
        return {"valid": False, "error": "元のプロジェクトディレクトリが見つかりません。"}

    clean_name = sanitize_duplicate_project_dir_name(destination_name)
    if not clean_name:
        return {"valid": False, "error": "複製先プロジェクト名が必要です。"}
    destination_dir = duplicate_project_destination_dir(project_path, clean_name)
    if not destination_dir:
        return {"valid": False, "error": "複製先ディレクトリを解決できません。"}
    if path_exists is None:
        path_exists = os.path.exists
    if path_exists(destination_dir):
        return {"valid": False, "error": "複製先ディレクトリは既に存在します。"}

    return {
        "valid": True,
        "error": "",
        "source_project_path": source_project_path,
        "source_project_dir": source_project_dir,
        "clean_name": clean_name,
        "destination_dir": destination_dir,
    }
