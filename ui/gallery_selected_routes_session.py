"""Gallery Selected Routes session, widget reconciliation and deferred reset.

Owns selection IDs, prefixed widget mirrors and pending selection resets,
including dependent preview invalidation at Project replacement. Rendering,
select-all/invert/clear actions, Project mutation and persistence stay in app.
"""

import streamlit as st

from core.route_operations import (
    initialize_selected_route_widget_state,
    sanitize_selected_route_ids,
    toggle_selected_route,
)

SELECTED_ROUTE_WIDGET_PREFIX = "pro_gallery_route_selected_"


def _gallery_selected_route_widget_key(route_handle: str) -> str:
    return f"{SELECTED_ROUTE_WIDGET_PREFIX}{str(route_handle or '').strip()}"


def _initialize_gallery_selected_route_widget(route_handle: str) -> str:
    return initialize_selected_route_widget_state(
        st.session_state,
        SELECTED_ROUTE_WIDGET_PREFIX,
        route_handle,
        st.session_state.get("gallery_selected_route_ids", []),
    )


def _clear_gallery_selected_route_widget_keys(route_handles=None) -> None:
    allowed_handles = None
    if route_handles is not None:
        if isinstance(route_handles, str):
            route_handles = [route_handles]
        allowed_handles = {
            str(route_handle or "").strip()
            for route_handle in route_handles
            if str(route_handle or "").strip()
        }
    for key in list(st.session_state.keys()):
        key_text = str(key)
        if not key_text.startswith(SELECTED_ROUTE_WIDGET_PREFIX):
            continue
        route_handle = key_text[len(SELECTED_ROUTE_WIDGET_PREFIX):]
        if allowed_handles is None or route_handle in allowed_handles:
            st.session_state.pop(key, None)


def reset_gallery_selected_route_session_state() -> None:
    """Reset session-only Selected Routes state during a Project switch."""

    st.session_state.gallery_selected_route_ids = []
    st.session_state.pop("gallery_selected_route_widget_pending_reset", None)
    st.session_state.pop("module_swap_preview", None)
    st.session_state.pop("module_swap_selected_routes_confirm", None)
    st.session_state.pop("gallery_attribute_group_swap_preview", None)
    st.session_state.pop("gallery_attribute_group_swap_selected_routes_confirm", None)
    st.session_state.pop("attribute_group_swap_preview", None)
    st.session_state.pop("attribute_group_swap_selected_routes_confirm", None)
    _clear_gallery_selected_route_widget_keys()


def _apply_pending_gallery_selected_route_widget_reset() -> None:
    pending = st.session_state.pop("gallery_selected_route_widget_pending_reset", None)
    if not isinstance(pending, dict):
        return
    _clear_gallery_selected_route_widget_keys(pending.get("route_handles"))


def _sanitize_gallery_selected_route_session_state(
    project,
    *,
    sync_widgets: bool = True,
    cleanup_widgets: bool = True,
) -> dict:
    state = sanitize_selected_route_ids(
        project,
        st.session_state.get("gallery_selected_route_ids", []),
    )
    st.session_state.gallery_selected_route_ids = list(state["selected_route_ids"])
    if cleanup_widgets:
        selectable_ids = set(state["selectable_route_ids"])
        selected_ids = set(state["selected_route_ids"])
        for key in list(st.session_state.keys()):
            key_text = str(key)
            if not key_text.startswith(SELECTED_ROUTE_WIDGET_PREFIX):
                continue
            route_handle = key_text[len(SELECTED_ROUTE_WIDGET_PREFIX):]
            if route_handle not in selectable_ids:
                st.session_state.pop(key, None)
            elif sync_widgets:
                st.session_state[key] = route_handle in selected_ids
    return state


def _on_gallery_route_selection_changed(route_handle: str) -> None:
    project = st.session_state.get("project")
    widget_key = _gallery_selected_route_widget_key(route_handle)
    st.session_state.gallery_selected_route_ids = toggle_selected_route(
        project,
        st.session_state.get("gallery_selected_route_ids", []),
        route_handle,
        selected=bool(st.session_state.get(widget_key, False)),
    )


def _set_gallery_selected_route_ids_after_structure_change(project, *, removed_route_handles=()):
    state = _sanitize_gallery_selected_route_session_state(
        project,
        sync_widgets=False,
        cleanup_widgets=False,
    )
    removed_handles = {
        str(route_handle or "").strip()
        for route_handle in removed_route_handles
        if str(route_handle or "").strip()
    }
    if removed_handles:
        state = sanitize_selected_route_ids(
            project,
            [
                route_id
                for route_id in state["selected_route_ids"]
                if route_id not in removed_handles
            ],
        )
        st.session_state.gallery_selected_route_ids = list(state["selected_route_ids"])
        st.session_state.gallery_selected_route_widget_pending_reset = {
            "route_handles": sorted(removed_handles),
        }
    return state
