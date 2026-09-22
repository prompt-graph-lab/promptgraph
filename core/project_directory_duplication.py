"""Read-only Project directory duplication planning, independent of the UI.

Filesystem observations are supplied by the caller. Path operations deliberately
use the host's os.path semantics, including the legacy normalization order.
"""

import os
from dataclasses import dataclass
from typing import Callable


def sanitize_duplicate_project_dir_name(name: str) -> str:
    clean_name = str(name or "").strip()
    clean_name = clean_name.replace("/", "_").replace("\\", "_")
    for char in '<>:"|?*':
        clean_name = clean_name.replace(char, "_")
    clean_name = clean_name.strip(" .")
    if clean_name in ("", ".", ".."):
        return ""
    return clean_name


def source_project_directory(project_path: str) -> tuple[str, str]:
    if not project_path:
        return "", ""
    clean_project_path = os.path.abspath(os.path.expanduser(project_path))
    return clean_project_path, os.path.dirname(clean_project_path)


def default_duplicate_project_dir_name(
    project_path: str, *, exists: Callable[[str], bool]
) -> str:
    source_project_path, source_project_dir = source_project_directory(project_path)
    if not source_project_path or not source_project_dir:
        return "MyProject_copy"

    source_name = os.path.basename(source_project_dir) or "Project"
    parent_dir = os.path.dirname(source_project_dir)
    base_name = f"{source_name}_copy"
    candidate_name = base_name
    suffix = 1
    while exists(os.path.join(parent_dir, candidate_name)):
        candidate_name = f"{base_name}_{suffix}"
        suffix += 1
    return candidate_name


def duplicate_project_destination_dir(project_path: str, destination_name: str) -> str:
    _, source_project_dir = source_project_directory(project_path)
    if not source_project_dir:
        return ""
    clean_name = sanitize_duplicate_project_dir_name(destination_name)
    if not clean_name:
        return ""
    return os.path.abspath(os.path.join(os.path.dirname(source_project_dir), clean_name))


@dataclass(frozen=True)
class ProjectDirectoryDuplicationPlan:
    source_project_path: str = ""
    source_project_dir: str = ""
    destination_dir: str = ""
    error: str = ""


def plan_project_directory_duplication(
    project_path: str,
    destination_name: str,
    *,
    project_available: bool,
    isfile: Callable[[str], bool],
    isdir: Callable[[str], bool],
    exists: Callable[[str], bool],
) -> ProjectDirectoryDuplicationPlan:
    """Stop at the first legacy blocker; propagate path/predicate exceptions.

    Only reached fields are populated. Saving, layout preparation, and copying
    belong to the app and must happen only after a plan with no error.
    """
    if not project_available:
        return ProjectDirectoryDuplicationPlan(error="先にプロジェクトを読み込むか作成してください。")

    source_project_path, source_project_dir = source_project_directory(project_path)

    def blocked(message, destination_dir=""):
        return ProjectDirectoryDuplicationPlan(
            source_project_path, source_project_dir, destination_dir, message
        )

    if not source_project_path:
        return blocked("現在のプロジェクトパスがありません。")
    if not isfile(source_project_path):
        return blocked("元のプロジェクトJSONが見つかりません。")
    if not isdir(source_project_dir):
        return blocked("元のプロジェクトディレクトリが見つかりません。")

    clean_name = sanitize_duplicate_project_dir_name(destination_name)
    if not clean_name:
        return blocked("複製先プロジェクト名が必要です。")
    destination_dir = duplicate_project_destination_dir(project_path, clean_name)
    if not destination_dir:
        return blocked("複製先ディレクトリを解決できません。")
    if exists(destination_dir):
        return blocked("複製先ディレクトリは既に存在します。", destination_dir)
    return ProjectDirectoryDuplicationPlan(
        source_project_path, source_project_dir, destination_dir
    )
