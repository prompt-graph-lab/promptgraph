"""Project Directory Browser discovery cache and root-scoped selection.

Filesystem discovery stays in core; refresh trigger ordering and opening a
Project stay in app.py. Cache entries are published only after resolution.
"""

import streamlit as st

from core.project_discovery import (
    normalize_project_discovery_path,
    resolve_cached_project_discovery,
)


def request_project_directory_discovery_refresh() -> None:
    generation = st.session_state.get(
        "project_directory_discovery_refresh_generation",
        0,
    )
    st.session_state.project_directory_discovery_refresh_generation = (
        int(generation or 0) + 1
    )


def _get_project_directory_discovery_snapshot(project_root: str) -> dict:
    snapshot, cache_entry, _cache_hit = resolve_cached_project_discovery(
        st.session_state.get("project_directory_discovery_cache"),
        root=project_root,
        refresh_generation=st.session_state.get(
            "project_directory_discovery_refresh_generation",
            0,
        ),
        current_open_project_path=st.session_state.get("current_project_path", ""),
    )
    st.session_state.project_directory_discovery_cache = cache_entry
    return snapshot


def _normalize_project_directory_browser_selection(
    project_root: str,
    project_entries: list[dict],
) -> str:
    normalized_root = normalize_project_discovery_path(project_root)
    if st.session_state.get("project_directory_selection_root") != normalized_root:
        st.session_state.project_directory_selection_root = normalized_root
        st.session_state.pop("project_directory_selected_path", None)

    available_paths = [
        str(entry.get("project_path") or "")
        for entry in project_entries
        if str(entry.get("project_path") or "")
    ]
    selected_path = str(
        st.session_state.get("project_directory_selected_path", "") or ""
    )
    if selected_path not in available_paths:
        selected_path = available_paths[0] if available_paths else ""
        if selected_path:
            st.session_state.project_directory_selected_path = selected_path
        else:
            st.session_state.pop("project_directory_selected_path", None)
    return selected_path
