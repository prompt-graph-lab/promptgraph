"""AnimaDex local-path draft restoration and explicit default persistence.

Owns animadex_browser_path, animadex_browser_path_draft, feedback production,
and settings["animadex_local_path"]. Rendering consumes feedback in app.py;
Project/workspace resets deliberately preserve this session lifecycle.
"""

import os

import streamlit as st

from core.settings import (
    get_animadex_local_path,
    normalize_animadex_local_path,
    save_settings,
)


def initialize_animadex_browser_path() -> str:
    if "animadex_browser_path_draft" not in st.session_state:
        current_widget_path = st.session_state.get("animadex_browser_path")
        if current_widget_path is None:
            current_widget_path = get_animadex_local_path(
                st.session_state.get("settings", {})
            )
        st.session_state.animadex_browser_path_draft = str(
            current_widget_path or ""
        )
    if "animadex_browser_path" not in st.session_state:
        st.session_state.animadex_browser_path = st.session_state.get(
            "animadex_browser_path_draft",
            "",
        )
    return st.session_state.get("animadex_browser_path", "")


def sync_animadex_browser_path_draft() -> None:
    st.session_state.animadex_browser_path_draft = str(
        st.session_state.get("animadex_browser_path", "") or ""
    )


def _animadex_local_path_is_available(path) -> bool:
    try:
        return bool(path) and os.path.exists(path)
    except (OSError, TypeError, ValueError):
        return False


def save_animadex_local_path_default() -> bool:
    current_path = st.session_state.get("animadex_browser_path", "")
    normalized_path = normalize_animadex_local_path(current_path)
    if not normalized_path:
        st.session_state.animadex_local_path_feedback = (
            "warning",
            "Enter a valid AnimaDex file or directory path before saving the default.",
        )
        return False

    settings = st.session_state.get("settings")
    if not isinstance(settings, dict):
        st.session_state.animadex_local_path_feedback = (
            "error",
            "Editor settings are unavailable. The AnimaDex default was not saved.",
        )
        return False

    previous_path = settings.get("animadex_local_path", "")
    settings["animadex_local_path"] = normalized_path
    if not save_settings(settings):
        settings["animadex_local_path"] = previous_path
        st.session_state.animadex_local_path_feedback = (
            "error",
            "Could not save editor settings. The existing AnimaDex default was kept.",
        )
        return False

    st.session_state.animadex_browser_path = normalized_path
    st.session_state.animadex_browser_path_draft = normalized_path
    if _animadex_local_path_is_available(normalized_path):
        feedback = ("success", "AnimaDex local path saved as the default.")
    else:
        feedback = (
            "warning",
            "Saved as default, but the path is not currently available.",
        )
    st.session_state.animadex_local_path_feedback = feedback
    return True


def clear_animadex_local_path_default() -> bool:
    settings = st.session_state.get("settings")
    if not isinstance(settings, dict):
        st.session_state.animadex_local_path_feedback = (
            "error",
            "Editor settings are unavailable. The AnimaDex default was not cleared.",
        )
        return False

    previous_path = settings.get("animadex_local_path", "")
    settings["animadex_local_path"] = ""
    if not save_settings(settings):
        settings["animadex_local_path"] = previous_path
        st.session_state.animadex_local_path_feedback = (
            "error",
            "Could not save editor settings. The existing AnimaDex default was kept.",
        )
        return False

    st.session_state.animadex_local_path_feedback = (
        "success",
        "Saved AnimaDex default cleared. The current session path is unchanged.",
    )
    return True
