"""Deterministic Final Export scope planning over caller-prepared inputs.

The app selects the current-route anchor and obtains Gallery route options.
No image resolution, filesystem access, export execution, or UI is performed.
"""
from core.prompt_line_selection import get_visible_prompt_lines, is_gallery_operation_prompt_line
from core.operations import resolve_gallery_route_for_line
from core.route_operations import resolve_selected_route_export_lines


def prepare_final_export_scope(project, scope):
    """Prepare visible eligible Lines before app-owned anchor/option lookup."""
    scope = scope if scope in {"all_lines", "current_route", "selected_route", "selected_routes"} else "all_lines"
    active_lines = [
        line
        for line in get_visible_prompt_lines(project)
        if not getattr(line, "deleted", False)
    ]
    active_prompt_lines = [line for line in active_lines if is_gallery_operation_prompt_line(line)]
    return scope, active_prompt_lines


def resolve_final_export_targets(
    project,
    scope,
    active_prompt_lines,
    *,
    anchor_line_id="",
    route_id=None,
    route_options=(),
    selected_route_ids=None,
) -> dict:
    """Plan a prepared scope, preserving references to the original Lines.

    Use prepare_final_export_scope first. For selected_route, supply the app's
    counted Gallery options after normalizing route_id; for current_route,
    supply the app-selected anchor. Separate preparation preserves evaluation
    order without moving session lookup into this owner.
    """
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
            (option for option in route_options if option.get("route_id") == selected_route_id),
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
