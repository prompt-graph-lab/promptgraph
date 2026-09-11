"""Global Module Library authoritative session reads and explicit writes."""

import copy

import streamlit as st

from core.io import (
    get_global_module_library_path,
    load_global_module_library,
    save_global_module_library,
)


def get_session_global_module_library() -> dict:
    """Load the Global Library once per path and reuse it during the session."""

    library_path = get_global_module_library_path(
        st.session_state.get("settings", {})
    )
    cache = st.session_state.get("global_module_library_session_cache")
    if (
        isinstance(cache, dict)
        and cache.get("path") == library_path
        and isinstance(cache.get("library"), dict)
    ):
        return cache["library"]

    library = load_global_module_library(
        st.session_state.get("settings", {})
    )
    st.session_state.global_module_library_session_cache = {
        "path": library_path,
        "library": library,
    }
    return library


def cache_global_module_library_for_session(library: dict) -> None:
    """Refresh the session cache after an explicit library write."""

    library_path = get_global_module_library_path(
        st.session_state.get("settings", {})
    )
    st.session_state.global_module_library_session_cache = {
        "path": library_path,
        "library": library if isinstance(library, dict) else {},
    }


def save_and_cache_global_module_library(update_library):
    """Rebase one explicit mutation and cache the persisted representation."""

    settings = st.session_state.get("settings", {})
    authoritative_library = load_global_module_library(settings)
    updated_library = update_library(
        copy.deepcopy(authoritative_library)
    )
    if not isinstance(updated_library, dict):
        raise TypeError("Global Module Library update must return a dict.")

    saved_path = save_global_module_library(updated_library, settings)
    persisted_library = load_global_module_library(settings)
    cache_global_module_library_for_session(persisted_library)
    return saved_path, persisted_library
