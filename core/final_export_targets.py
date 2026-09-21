"""Deterministic Final Export target planning, without UI or export lifecycle.

The app supplies its already filtered, ordered prompt lines and (only for the
single selected scope) counted route options. It also chooses the current-route
anchor from session state. This keeps preparation/exception ordering at the app
boundary while this owner handles scope membership and the complete result.
"""

from core.operations import resolve_gallery_route_for_line
from core.route_operations import resolve_selected_route_export_lines


def resolve_final_export_targets(
    project,
    scope: str,
    active_prompt_lines: list,
    *,
    anchor_line_id="",
    route_id=None,
    route_options=(),
    selected_route_ids=None,
) -> dict:
    """Plan targets using normalized app inputs without mutating any input.

    ``active_prompt_lines`` retains visible Gallery order and original objects.
    ``route_options`` retains the Gallery's counted single-route semantics;
    selected_routes deliberately uses the existing Project-order resolver.
    No session callback, image inspection, or filesystem access is required.
    """
    scope = scope if scope in {"all_lines", "current_route", "selected_route", "selected_routes"} else "all_lines"
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
