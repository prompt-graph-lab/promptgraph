"""Application lifecycle for whole-folder Duplicate Project."""

from datetime import datetime
import os
import shutil

from core import project_directory_duplication


def _find_copied_project_json(destination_dir: str, source_project_path: str) -> str:
    preferred_path = os.path.join(destination_dir, os.path.basename(source_project_path))
    if os.path.exists(preferred_path):
        return preferred_path
    json_files = [
        os.path.join(destination_dir, file_name)
        for file_name in os.listdir(destination_dir)
        if file_name.lower().endswith(".json") and os.path.isfile(os.path.join(destination_dir, file_name))
    ]
    return json_files[0] if len(json_files) == 1 else ""


def duplicate_project_directory(
    destination_name: str,
    *,
    session_state,
    save_project_to_json,
    ensure_current_project_folder_layout,
    load_project_json_into_session,
    request_project_directory_discovery_refresh,
) -> tuple[bool, str]:
    """Copy the current saved Project folder and open its copied Project JSON."""
    project_available = bool(session_state.project)
    plan = project_directory_duplication.plan_project_directory_duplication(
        session_state.get("current_project_path", "") if project_available else "",
        destination_name,
        project_available=project_available,
        isfile=os.path.isfile,
        isdir=os.path.isdir,
        exists=os.path.exists,
    )
    if plan.error:
        return False, plan.error
    source_project_path = plan.source_project_path
    source_project_dir = plan.source_project_dir
    destination_dir = plan.destination_dir

    try:
        save_project_to_json(session_state.project, source_project_path)
        ensure_current_project_folder_layout(source_project_path)
    except Exception as exc:
        return False, f"複製前のプロジェクト保存に失敗しました: {exc}"

    shutil.copytree(
        source_project_dir,
        destination_dir,
        ignore=shutil.ignore_patterns(
            ".promptgraph_cache",
            ".*.tmp",
            ".git",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".DS_Store",
            "Thumbs.db",
        ),
    )
    destination_project_path = _find_copied_project_json(destination_dir, source_project_path)
    if not destination_project_path:
        return False, "複製先で開くproject JSONが見つかりません。"

    try:
        if not load_project_json_into_session(destination_project_path):
            return False, "複製先project JSONを開けませんでした。"
    except Exception as exc:
        return False, f"複製先project JSONを開けませんでした: {exc}"

    session_state.last_saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    session_state.autosave_feedback = "project duplicated"
    request_project_directory_discovery_refresh()
    return True, f"プロジェクトディレクトリを複製して開きました: {destination_project_path}"
