"""Module Rename selection, durable name drafts, and preview invalidation.

Project transition resets and rename mutation sequencing remain in app.py.
"""

import streamlit as st


def clear_module_rename_preview():
    st.session_state.pop("module_rename_preview", None)


def initialize_module_rename_selection(module_names) -> str:
    valid_module_names = list(module_names or [])
    if not valid_module_names:
        st.session_state.pop("module_rename_selected", None)
        st.session_state.pop("_module_rename_selected_widget", None)
        return ""

    selected_module = st.session_state.get("module_rename_selected")
    if selected_module not in valid_module_names:
        selected_module = valid_module_names[0]
        st.session_state.module_rename_selected = selected_module
    if st.session_state.get("_module_rename_selected_widget") != selected_module:
        st.session_state["_module_rename_selected_widget"] = selected_module
    return selected_module


def sync_module_rename_selected_widget() -> None:
    selected_module = st.session_state.get("_module_rename_selected_widget")
    if selected_module:
        st.session_state.module_rename_selected = selected_module


def initialize_module_rename_new_name_draft() -> str:
    durable_name = str(
        st.session_state.get("module_rename_new_name", "") or ""
    ).strip()
    st.session_state.module_rename_new_name = durable_name
    if "_module_rename_new_name_widget" not in st.session_state:
        st.session_state["_module_rename_new_name_widget"] = durable_name
    return durable_name


def sync_module_rename_new_name_widget() -> None:
    st.session_state.module_rename_new_name = str(
        st.session_state.get("_module_rename_new_name_widget", "") or ""
    ).strip()
