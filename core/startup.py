import os
from collections.abc import Callable, MutableMapping
from typing import Any


STARTUP_AUTO_OPEN_ATTEMPTED_KEY = "startup_project_auto_open_attempted"


def attempt_startup_project_auto_open(
    session_state: MutableMapping[str, Any],
    *,
    resolve_last_project_path: Callable[[], object],
    open_project: Callable[[str], bool],
    path_is_file: Callable[[str], bool] = os.path.isfile,
) -> dict:
    if session_state.get(STARTUP_AUTO_OPEN_ATTEMPTED_KEY):
        return {
            "attempted": False,
            "opened": False,
            "path": "",
            "reason": "already_attempted",
            "error": "",
        }

    session_state[STARTUP_AUTO_OPEN_ATTEMPTED_KEY] = True
    if session_state.get("project") is not None:
        return {
            "attempted": True,
            "opened": False,
            "path": "",
            "reason": "project_already_loaded",
            "error": "",
        }

    try:
        raw_path = resolve_last_project_path()
        project_path = os.fspath(raw_path).strip() if raw_path else ""
    except (OSError, TypeError, ValueError) as exc:
        return {
            "attempted": True,
            "opened": False,
            "path": "",
            "reason": "invalid_last_project_path",
            "error": f"Invalid last project path: {exc}",
        }

    if not project_path:
        return {
            "attempted": True,
            "opened": False,
            "path": "",
            "reason": "last_project_not_configured",
            "error": "",
        }

    try:
        is_file = bool(path_is_file(project_path))
    except OSError as exc:
        return {
            "attempted": True,
            "opened": False,
            "path": project_path,
            "reason": "last_project_path_check_failed",
            "error": f"Could not validate last project file: {exc}",
        }

    if not is_file:
        return {
            "attempted": True,
            "opened": False,
            "path": project_path,
            "reason": "last_project_file_not_found",
            "error": f"Last project file not found: {project_path}",
        }

    try:
        opened = bool(open_project(project_path))
    except Exception as exc:
        return {
            "attempted": True,
            "opened": False,
            "path": project_path,
            "reason": "last_project_open_failed",
            "error": f"Could not open last project: {exc}",
        }

    return {
        "attempted": True,
        "opened": opened,
        "path": project_path,
        "reason": "opened" if opened else "last_project_open_failed",
        "error": "" if opened else f"Could not open last project: {project_path}",
    }
