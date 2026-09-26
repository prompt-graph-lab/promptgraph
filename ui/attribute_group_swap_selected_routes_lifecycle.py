"""Application publication for Selected Routes Attribute Group Swap."""

from core.attribute_group_swap_selected_routes import apply_selected_routes_attribute_group_swap


def apply_and_publish_selected_routes_attribute_group_swap(
    *,
    preview,
    from_group_key,
    to_group_key,
    require_full_match,
    preview_state_key,
    confirm_key,
    feedback_mode,
    session_state,
    push_history,
    restore_focus_after_graph_update,
    sync_text_areas,
    save_current_project_if_possible,
):
    """Publish a successful atomic swap in the existing application order."""

    previous_focus = session_state.get("focused_line_id")
    result = apply_selected_routes_attribute_group_swap(
        session_state.project,
        session_state.get("gallery_selected_route_ids", []),
        expected_signature=preview.get("signature", ""),
        from_group_key=from_group_key,
        to_group_key=to_group_key,
        require_full_match=require_full_match,
        project_path=session_state.get("current_project_path", ""),
    )
    if result.get("applied"):
        push_history()
        session_state.project = result["updated_project"]
        restore_focus_after_graph_update(previous_focus)
        sync_text_areas()
        session_state.pop(preview_state_key, None)
        session_state.pop(confirm_key, None)
        if feedback_mode == "gallery":
            session_state.gallery_feedback = (
                f"Attribute Group Swap applied to {result['applied_count']} line(s)."
            )
            session_state.gallery_feedback_kind = "success"
        else:
            session_state.attribute_group_swap_notice = (
                f"Attribute Group Swap applied to {result['applied_count']} line(s)."
            )
        save_current_project_if_possible("selected Routes attribute group swap applied")
    return result
