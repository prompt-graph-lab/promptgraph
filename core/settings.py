import json
import os
from datetime import datetime, timezone

SETTINGS_FILE = ".editor_settings.json"
EDITION = "PRO"  # Change to "PRO" to unlock all features
MAX_RECENT_PROJECTS = 10
DEFAULT_GLOBAL_MODULE_LIBRARY_DIR = os.path.join(os.path.expanduser("~"), "PromptGraph", "modules")


def _default_settings():
    return {
        "last_source_directory": "./dummy_data",
        "last_export_path": "prompts.txt",
        "image_root_directory": "",
        "image_set": "",
        "comfyui_url": "127.0.0.1:8188",
        "comfyui_workflow_path": "workflow_api.json",
        "comfyui_workflow_preset": "",
        "force_shared_comfy_workflow": False,
        "global_module_library_dir": DEFAULT_GLOBAL_MODULE_LIBRARY_DIR,
        "projects_root_directory": "",
        "animadex_local_path": "",
        "last_project": "",
        "recent_projects": [],
    }


def normalize_projects_root_directory(path) -> str:
    try:
        path_value = os.fspath(path)
    except (TypeError, ValueError):
        return ""
    if not isinstance(path_value, str) or not path_value.strip():
        return ""
    clean_path = path_value.strip()
    if "\x00" in clean_path or any(ord(character) < 32 for character in clean_path):
        return ""
    if os.name == "nt":
        _drive, path_tail = os.path.splitdrive(clean_path)
        if any(character in '<>:"|?*' for character in path_tail):
            return ""
    try:
        return os.path.abspath(os.path.expanduser(clean_path))
    except (OSError, TypeError, ValueError):
        return ""


def get_projects_root_directory(settings, fallback_root) -> str:
    normalized_fallback = normalize_projects_root_directory(fallback_root)
    if not isinstance(settings, dict):
        return normalized_fallback
    configured_root = normalize_projects_root_directory(
        settings.get("projects_root_directory", "")
    )
    return configured_root or normalized_fallback


def normalize_animadex_local_path(path) -> str:
    try:
        path_value = os.fspath(path)
    except (TypeError, ValueError):
        return ""
    if not isinstance(path_value, str) or not path_value.strip():
        return ""
    clean_path = path_value.strip()
    if "\x00" in clean_path or any(ord(character) < 32 for character in clean_path):
        return ""
    if os.name == "nt":
        _drive, path_tail = os.path.splitdrive(clean_path)
        if any(character in '<>:"|?*' for character in path_tail):
            return ""
    try:
        return os.path.abspath(os.path.expanduser(clean_path))
    except (OSError, TypeError, ValueError):
        return ""


def get_animadex_local_path(settings) -> str:
    if not isinstance(settings, dict):
        return ""
    return normalize_animadex_local_path(settings.get("animadex_local_path", ""))


def _normalize_project_path(path):
    if not path:
        return ""
    try:
        path_value = os.fspath(path)
    except TypeError:
        return ""
    if not isinstance(path_value, str) or not path_value.strip():
        return ""
    return os.path.abspath(os.path.expanduser(path_value.strip()))


def _project_display_name(path):
    project_dir = os.path.basename(os.path.dirname(path))
    return project_dir or os.path.basename(path) or "project.json"

def load_settings():
    defaults = _default_settings()
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    defaults.update(loaded)
                    defaults["recent_projects"] = [
                        item for item in defaults.get("recent_projects", [])
                        if isinstance(item, dict) and item.get("path")
                    ][:MAX_RECENT_PROJECTS]
                    return defaults
        except Exception:
            pass
    return defaults

def save_settings(settings) -> bool:
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception:
        return False


def get_last_project_path(settings):
    return _normalize_project_path(settings.get("last_project", ""))


def get_recent_projects(settings):
    recent_projects = settings.get("recent_projects", [])
    if not isinstance(recent_projects, list):
        return []
    return [
        {
            "name": str(item.get("name") or _project_display_name(item.get("path", ""))),
            "path": _normalize_project_path(item.get("path", "")),
            "last_opened": str(item.get("last_opened", "")),
        }
        for item in recent_projects
        if isinstance(item, dict) and item.get("path")
    ][:MAX_RECENT_PROJECTS]


def remember_project(settings, project_path, project_name=None, *, update_last_project=True):
    normalized_path = _normalize_project_path(project_path)
    if not normalized_path:
        return settings

    opened_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    recent = [
        item for item in get_recent_projects(settings)
        if os.path.normcase(item["path"]) != os.path.normcase(normalized_path)
    ]
    recent.insert(0, {
        "name": project_name or _project_display_name(normalized_path),
        "path": normalized_path,
        "last_opened": opened_at,
    })
    if update_last_project:
        settings["last_project"] = normalized_path
    settings["recent_projects"] = recent[:MAX_RECENT_PROJECTS]
    return settings
