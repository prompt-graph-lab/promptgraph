"""Deterministic Final Export target planning, without session or export lifecycle.

The app prepares eligible lines before reading its current-route anchor. Passing
that prepared list preserves the legacy evaluation and exception order; callers
without UI state can let the planner prepare it itself.
"""

from core.operations import get_gallery_route_options, resolve_gallery_route_for_line
from core.prompt_line_selection import (
    get_visible_prompt_lines, is_gallery_operation_prompt_line, is_route_separator,
)
from core.route_operations import resolve_selected_route_export_lines


_UNPREPARED = object()


def get_final_export_prompt_lines(project) -> list:
    active_lines = [
        line
        for line in get_visible_prompt_lines(project)
        if not getattr(line, "deleted", False)
    ]
    active_prompt_lines = [line for line in active_lines if is_gallery_operation_prompt_line(line)]
    return active_prompt_lines


def _route_line_count(active_lines: list, separator_line_id: str) -> int:
    separator_index = next(
        (index for index, line in enumerate(active_lines) if getattr(line, "id", "") == separator_line_id),
        None,
    )
    if separator_index is None:
        return 0
    next_separator_index = next(
        (
            index
            for index, line in enumerate(active_lines[separator_index + 1:], start=separator_index + 1)
            if is_route_separator(line)
        ),
        len(active_lines),
    )
    return sum(
        1
        for line in active_lines[separator_index + 1:next_separator_index]
        if is_gallery_operation_prompt_line(line)
    )


def get_final_export_route_options(project) -> list[dict]:
    route_options = []
    active_lines = get_visible_prompt_lines(project)
    for route in get_gallery_route_options(project):
        route_id = route.get("route_id", "")
        route_options.append({
            **route,
            "line_count": _route_line_count(active_lines, route_id),
        })
    return route_options


def resolve_final_export_targets(
    project,
    scope: str,
    route_id: str | None = None,
    selected_route_ids: list[str] | None = None,
    *,
    anchor_line_id: str = "",
    active_prompt_lines=_UNPREPARED,
) -> dict:
    """Plan targets using an app-selected anchor and optional prepared line list.

    Returned lines are the original objects. Inputs are only read; Route details
    and diagnostics for multiple selections belong to the existing resolver.
    """
    scope = scope if scope in {"all_lines", "current_route", "selected_route", "selected_routes"} else "all_lines"
    if active_prompt_lines is _UNPREPARED:
        active_prompt_lines = get_final_export_prompt_lines(project)
    warnings = []
    route_resolution = {}

    selected_route_resolution = {}
    if scope == "all_lines":
        target_lines = active_prompt_lines
    elif scope == "current_route":
        route_resolution = resolve_gallery_route_for_line(project, anchor_line_id)
        warnings.extend(route_resolution.get("warnings", []))
        route_line_ids = set(route_resolution.get("line_ids", []))
        target_lines = [line for line in active_prompt_lines if getattr(line, "id", "") in route_line_ids]
    elif scope == "selected_route":
        selected_route_id = str(route_id or "").strip()
        route = next(
            (option for option in get_final_export_route_options(project) if option.get("route_id") == selected_route_id),
            None,
        )
        if route:
            route_line_ids = set(route.get("line_ids", []))
            target_lines = [line for line in active_prompt_lines if getattr(line, "id", "") in route_line_ids]
            route_resolution = {
                "route_id": route.get("route_id", ""),
                "route_label": route.get("route_label", ""),
                "line_ids": list(route_line_ids),
                "line_count": int(route.get("line_count", 0) or 0),
                "warnings": [],
            }
        else:
            target_lines = []
            warnings.append("シーンが選択されていません。")
    else:
        selected_route_resolution = resolve_selected_route_export_lines(
            project,
            selected_route_ids,
        )
        target_lines = list(selected_route_resolution["target_lines"])
        route_resolution = {"line_count": len(target_lines)}
        warnings.extend(selected_route_resolution.get("diagnostics", []))

    if scope != "all_lines" and not target_lines and not warnings:
        warnings.append("選択されたシーンには書き出し対象イラストがありません。")

    return {
        "lines": target_lines,
        "line_ids": [getattr(line, "id", "") for line in target_lines if getattr(line, "id", "")],
        "scope": scope,
        "route_id": route_resolution.get("route_id", ""),
        "route_label": route_resolution.get("route_label", ""),
        "route_line_count": route_resolution.get("line_count"),
        "resolved_route_handles": selected_route_resolution.get("resolved_route_handles", []),
        "resolved_route_labels": selected_route_resolution.get("resolved_route_labels", []),
        "selected_route_count": selected_route_resolution.get("selected_route_count", 0),
        "selected_main_line_count": selected_route_resolution.get("selected_main_line_count", 0),
        "selected_workbench_count": selected_route_resolution.get("selected_workbench_count", 0),
        "selected_deleted_member_count": selected_route_resolution.get("selected_deleted_member_count", 0),
        "selected_candidate_count": selected_route_resolution.get("selected_candidate_count", 0),
        "selected_gallery_variant_count": selected_route_resolution.get("selected_gallery_variant_count", 0),
        "route_summaries": selected_route_resolution.get("route_summaries", []),
        "diagnostics": selected_route_resolution.get("diagnostics", []),
        "warnings": warnings,
    }
