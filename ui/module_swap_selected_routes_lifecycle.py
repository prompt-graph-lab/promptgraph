"""Application publication for Selected Routes Module Swap."""

from core.module_swap_selected_routes import apply_selected_routes_module_swap


def apply_and_publish_selected_routes_module_swap(
    *,
    preview,
    source_module_name,
    target_module_name,
    match_mode,
    session_state,
    push_history,
    restore_focus_after_graph_update,
    save_current_project_if_possible,
):
    """Apply once and publish only a successful Selected Routes swap."""

    previous_focus = session_state.get("focused_line_id")
    result = apply_selected_routes_module_swap(
        session_state.project,
        session_state.get("gallery_selected_route_ids", []),
        expected_signature=preview.get("signature", ""),
        source_module_name=source_module_name,
        target_module_name=target_module_name,
        match_mode=match_mode,
        project_path=session_state.get("current_project_path", ""),
        disabled_modules=session_state.get("disabled_modules", set()),
    )
    if result.get("applied"):
        push_history()
        session_state.project = result["updated_project"]
        restore_focus_after_graph_update(previous_focus)
        save_current_project_if_possible("Selected Routes Module Swap applied")
        session_state.pop("module_swap_preview", None)
    return result
