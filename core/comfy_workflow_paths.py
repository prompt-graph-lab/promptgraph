"""Read-only ComfyUI workflow paths and effective filesystem source selection.

The app supplies settings and lazy project context. No session initialization,
persistence, workflow parsing, or generation lifecycle belongs here.
"""

import os


def resolve_comfy_workflow_path(workflow_path, *, get_current_project_path):
    if not workflow_path:
        return ""
    expanded_path = os.path.expanduser(workflow_path)
    if os.path.isabs(expanded_path):
        return os.path.abspath(expanded_path)

    current_project_path = get_current_project_path()
    if current_project_path:
        return os.path.abspath(os.path.join(os.path.dirname(current_project_path), expanded_path))
    return os.path.abspath(expanded_path)


def list_comfy_workflow_presets(preset_dir):
    if not os.path.isdir(preset_dir):
        return []
    presets = []
    for file_name in sorted(os.listdir(preset_dir), key=str.casefold):
        if os.path.splitext(file_name)[1].lower() != ".json":
            continue
        preset_path = os.path.join(preset_dir, file_name)
        if os.path.isfile(preset_path):
            presets.append(file_name)
    return presets


def resolve_comfy_workflow_preset_path(preset_name, preset_dir):
    clean_name = os.path.basename(str(preset_name or "").strip())
    if not clean_name:
        return ""
    preset_path = os.path.abspath(os.path.join(preset_dir, clean_name))
    preset_root = os.path.abspath(preset_dir)
    if os.path.dirname(preset_path) != preset_root:
        return ""
    if os.path.splitext(preset_path)[1].lower() != ".json":
        return ""
    return preset_path


def resolve_effective_comfy_workflow_path(
    configured_workflow_path, preset_path, force_shared, *, resolve_project_path,
):
    """Preserve short-circuiting and existence checks (including directories)."""
    if force_shared and preset_path and os.path.exists(preset_path):
        return preset_path, "preset"

    resolved_project_path = resolve_project_path(configured_workflow_path)
    if resolved_project_path and os.path.exists(resolved_project_path):
        return resolved_project_path, "project"

    if preset_path and os.path.exists(preset_path):
        return preset_path, "preset"

    return resolved_project_path, "fallback"
