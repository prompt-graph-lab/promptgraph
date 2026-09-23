"""Application publication lifecycle for Batch Promote Variants."""

from core.gallery_variant_promotion import apply_batch_variant_promotion_plan


def apply_and_publish_batch_gallery_variant_promotion(
    project,
    *,
    stored_plan,
    plan_kwargs,
    promote_gallery_variant_to_route,
    session_state,
    push_history,
    build_graph,
    restore_focus_after_graph_update,
    synchronize_selected_routes,
    save_current_project_if_possible,
):
    """Revalidate and apply a preview, publishing only a successful clone."""

    result = apply_batch_variant_promotion_plan(
        project,
        stored_plan,
        promote_line=lambda working_project, parent_line_id, variant, placement: (
            promote_gallery_variant_to_route(
                working_project,
                parent_line_id,
                variant,
                manage_state=False,
                placement=placement,
            )
        ),
        **plan_kwargs,
    )
    if result["applied"]:
        previous_focused_line_id = session_state.get("focused_line_id")
        push_history()
        session_state.project = build_graph(result["updated_project"])
        restore_focus_after_graph_update(previous_focused_line_id)
        synchronize_selected_routes(session_state.project)
        if result["new_line_ids"]:
            session_state.highlighted_line_id = result["new_line_ids"][-1]
            session_state.gallery_expanded_line_id = result["new_line_ids"][-1]
        save_current_project_if_possible("gallery variants batch promoted to main lines")
        session_state.pop("gallery_variant_promotion_preview", None)
    return result
