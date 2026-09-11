"""Existing Project Import input invalidation and deferred confirmation reset.

Preview construction, copy execution, persistence, and reruns remain in app.py.
"""

import os

import streamlit as st

from core.project_root_import import (
    normalize_project_import_path,
    sanitize_project_import_name,
)

PROJECT_ROOT_IMPORT_PREVIEW_KEY = "project_root_import_preview"
PROJECT_ROOT_IMPORT_RESULT_KEY = "project_root_import_result"
PROJECT_ROOT_IMPORT_SOURCE_KEY = "project_root_import_source_path"
PROJECT_ROOT_IMPORT_NAME_KEY = "project_root_import_destination_name"
PROJECT_ROOT_IMPORT_CONFIRM_KEY = "project_root_import_confirm"
PROJECT_ROOT_IMPORT_PHRASE_KEY = "project_root_import_phrase"
PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY = (
    "project_root_import_confirm_reset_pending"
)


def reset_project_root_import_operation_state(*, keep_result: bool = False) -> None:
    """Clear the session-only Existing Project Import operation state."""

    st.session_state.pop(PROJECT_ROOT_IMPORT_PREVIEW_KEY, None)
    if not keep_result:
        st.session_state.pop(PROJECT_ROOT_IMPORT_RESULT_KEY, None)
    st.session_state[PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY] = True


def _reset_project_root_import_confirmation() -> None:
    st.session_state[PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY] = True


def _invalidate_project_root_import_preview() -> None:
    reset_project_root_import_operation_state(keep_result=False)


def _select_project_root_import_source(source_path: str) -> None:
    normalized = normalize_project_import_path(source_path)
    st.session_state[PROJECT_ROOT_IMPORT_SOURCE_KEY] = normalized
    default_name = sanitize_project_import_name(
        os.path.basename(os.path.dirname(normalized))
    )
    if default_name:
        st.session_state[PROJECT_ROOT_IMPORT_NAME_KEY] = default_name
    _invalidate_project_root_import_preview()


def consume_project_root_import_confirmation_reset() -> None:
    if st.session_state.pop(PROJECT_ROOT_IMPORT_CONFIRM_RESET_PENDING_KEY, False):
        st.session_state.pop(PROJECT_ROOT_IMPORT_CONFIRM_KEY, None)
        st.session_state.pop(PROJECT_ROOT_IMPORT_PHRASE_KEY, None)


def initialize_project_root_import_name(source_path: str) -> None:
    if PROJECT_ROOT_IMPORT_NAME_KEY not in st.session_state:
        st.session_state[PROJECT_ROOT_IMPORT_NAME_KEY] = sanitize_project_import_name(
            os.path.basename(os.path.dirname(source_path))
        )
