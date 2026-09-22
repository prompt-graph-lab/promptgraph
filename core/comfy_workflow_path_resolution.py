"""Effective shared ComfyUI workflow path selection, independent of UI state."""


def resolve_effective_workflow_path(
    configured_workflow_path,
    preset_path,
    force_shared,
    *,
    resolve_project_path,
    path_exists,
):
    """Resolve precedence using caller-owned path and filesystem operations.

    Resolve the project path lazily so an existing forced preset bypasses it.
    Existence checks deliberately remain ordered and uncached: a missing forced
    preset is checked again after the project path, as in the original resolver.
    Filesystem and path-resolution errors propagate to the caller.
    """
    if force_shared and preset_path and path_exists(preset_path):
        return preset_path, "preset"

    resolved_project_path = resolve_project_path(configured_workflow_path)
    if resolved_project_path and path_exists(resolved_project_path):
        return resolved_project_path, "project"

    if preset_path and path_exists(preset_path):
        return preset_path, "preset"

    return resolved_project_path, "fallback"
