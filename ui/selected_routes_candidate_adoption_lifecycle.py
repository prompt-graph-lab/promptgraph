"""Application publication for Selected Routes Candidate Adoption."""

from core.route_batch_candidate_adoption import apply_selected_routes_candidate_adoption


def apply_and_publish_selected_routes_candidate_adoption(
    project,
    selected_route_ids,
    *,
    expected_signature,
    source,
    session_state,
    resolve_path,
    path_exists,
    push_history,
    build_graph,
    get_persistent_line_candidates,
    sync_line_generated_candidates_to_session,
    restore_focus_after_graph_update,
    sync_text_areas,
    save_current_project_if_possible,
):
    """Apply the atomic domain result, then publish a successful clone in app order."""

    previous_focus = session_state.get("focused_line_id")
    result = apply_selected_routes_candidate_adoption(
        project,
        selected_route_ids or [],
        expected_signature=expected_signature,
        source=source,
        project_path=session_state.get("current_project_path", ""),
        resolve_path=resolve_path,
        path_exists=path_exists,
    )
    updated_project = result.pop("updated_project", None)
    if bool(result.get("applied_count", 0)) and result.get("applied"):
        push_history()
        if updated_project is not None:
            session_state.project = updated_project
        session_state.project = build_graph(session_state.project)
        applied_line_ids = set(result.get("applied_line_ids") or [])
        for line in getattr(session_state.project, "prompt_lines", []):
            if getattr(line, "id", "") in applied_line_ids:
                sync_line_generated_candidates_to_session(
                    line, get_persistent_line_candidates(line)
                )
        restore_focus_after_graph_update(previous_focus)
        sync_text_areas()
        save_current_project_if_possible("route-scope candidates batch adopted")
    session_state.pop("route_batch_candidate_adoption_preview", None)
    session_state.route_batch_candidate_adoption_apply_result = result
    return result
