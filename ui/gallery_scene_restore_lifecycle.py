"""Application publication lifecycle for Gallery Scene Restore."""

from core.route_operations import get_route_move_ui_state, restore_removed_route


def apply_and_publish_gallery_scene_restore(
    project,
    record,
    *,
    session_state,
    reset_gallery_route_action_session_state,
    reset_gallery_route_move_preview_state,
    build_graph,
    synchronize_selected_routes,
    restore_focus_after_graph_update,
    save_current_project_if_possible,
):
    """Restore a Scene in place, then publish its successful application."""
    route_handle = str(record.get("route_handle") or record.get("separator_line_id") or "").strip()
    previous_focus = session_state.get("focused_line_id")
    previous_highlight = session_state.get("highlighted_line_id")
    previous_expanded = session_state.get("gallery_expanded_line_id")
    # Capture the pre-restore Project now, but mutate bounded Undo history only
    # after a successful restore or a core exception following in-place mutation.
    history_snapshot = session_state.project.clone() if session_state.project else None

    def commit_restore_history():
        if history_snapshot is not None:
            history = session_state.history
            history.append(history_snapshot)
            if len(history) > 20:
                history.pop(0)

    try:
        result = restore_removed_route(project, str(record.get("id") or route_handle))
    except Exception:
        commit_restore_history()
        raise
    if not result.get("restored"):
        return result

    commit_restore_history()
    reset_gallery_route_action_session_state()
    reset_gallery_route_move_preview_state()
    session_state.pop(
        f"pro_trash_restore_route_confirm_{record.get('id') or route_handle}",
        None,
    )
    session_state.project = build_graph(project)
    synchronize_selected_routes(session_state.project)
    restored_state = get_route_move_ui_state(
        session_state.project,
        route_handle=route_handle,
        focused_line_id=previous_focus,
        highlighted_line_id=previous_highlight,
        expanded_line_id=previous_expanded,
    )
    session_state.gallery_selected_route_separator_id = restored_state[
        "gallery_selected_route_separator_id"
    ]
    session_state.focused_line_id = restored_state["focused_line_id"]
    session_state.highlighted_line_id = restored_state["highlighted_line_id"]
    session_state.gallery_expanded_line_id = restored_state["gallery_expanded_line_id"]
    affected_line_ids = set(record.get("line_ids") or [])
    session_state.gallery_move_targets = {
        line_id: selected
        for line_id, selected in session_state.get("gallery_move_targets", {}).items()
        if line_id not in affected_line_ids
    }
    restore_focus_after_graph_update(restored_state["focused_line_id"])
    save_current_project_if_possible("route restored")
    session_state.gallery_feedback = f"Restored Scene '{route_handle}'."
    session_state.gallery_feedback_kind = "success"
    return result
