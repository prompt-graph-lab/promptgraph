"""Project Module Inspector selection and durable draft/widget synchronization.

Rendering, Project resets, mutation, history and persistence remain in app.py.
"""

import streamlit as st

from core.operations import (
    MODULE_TYPES,
    get_module_body,
    get_module_core_tokens,
    get_module_type,
    get_module_min_match_tokens,
)
from core.module_token_rules import _format_module_rule_text


def prepare_project_module_inspector_selection_widget_state(
    module_names,
) -> str:
    durable_key = "project_module_inspector_name"
    widget_key = "_project_module_inspector_name_widget"
    durable_name = st.session_state.get(durable_key)
    if durable_name not in module_names:
        durable_name = module_names[0]
        st.session_state[durable_key] = durable_name
    st.session_state[widget_key] = durable_name
    return durable_name


def sync_project_module_inspector_selection_widget_state() -> None:
    widget_name = st.session_state.get(
        "_project_module_inspector_name_widget"
    )
    if widget_name:
        st.session_state.project_module_inspector_name = widget_name


def prepare_project_module_inspector_body_widget_state(
    module_library,
    module_name,
) -> str:
    durable_key = f"project_module_inspector_body_{module_name}"
    widget_key = (
        f"_project_module_inspector_body_widget_{module_name}"
    )
    if durable_key not in st.session_state:
        st.session_state[durable_key] = get_module_body(
            module_library,
            module_name,
        )
    durable_body = str(st.session_state.get(durable_key, "") or "")
    st.session_state[durable_key] = durable_body
    st.session_state[widget_key] = durable_body
    return durable_body


def sync_project_module_inspector_body_widget_state(module_name) -> None:
    widget_key = (
        f"_project_module_inspector_body_widget_{module_name}"
    )
    durable_key = f"project_module_inspector_body_{module_name}"
    st.session_state[durable_key] = str(
        st.session_state.get(widget_key, "") or ""
    )


def prepare_project_module_inspector_core_widget_state(
    module_library,
    module_name,
) -> str:
    durable_key = f"project_module_inspector_core_{module_name}"
    widget_key = (
        f"_project_module_inspector_core_widget_{module_name}"
    )
    if durable_key not in st.session_state:
        st.session_state[durable_key] = _format_module_rule_text(
            get_module_core_tokens(module_library, module_name)
        )
    durable_core = str(st.session_state.get(durable_key, "") or "")
    st.session_state[durable_key] = durable_core
    st.session_state[widget_key] = durable_core
    return durable_core


def sync_project_module_inspector_core_widget_state(module_name) -> None:
    widget_key = (
        f"_project_module_inspector_core_widget_{module_name}"
    )
    durable_key = f"project_module_inspector_core_{module_name}"
    st.session_state[durable_key] = str(
        st.session_state.get(widget_key, "") or ""
    )


def prepare_project_module_inspector_type_widget_state(
    module_library,
    module_name,
) -> str:
    durable_key = f"project_module_inspector_type_{module_name}"
    widget_key = (
        f"_project_module_inspector_type_widget_{module_name}"
    )
    saved_type = get_module_type(module_library, module_name)
    default_type = saved_type if saved_type in MODULE_TYPES else MODULE_TYPES[0]
    durable_type = st.session_state.get(durable_key, default_type)
    if durable_type not in MODULE_TYPES:
        durable_type = default_type
    st.session_state[durable_key] = durable_type
    st.session_state[widget_key] = durable_type
    return durable_type


def sync_project_module_inspector_type_widget_state(module_name) -> None:
    widget_key = (
        f"_project_module_inspector_type_widget_{module_name}"
    )
    durable_key = f"project_module_inspector_type_{module_name}"
    widget_type = st.session_state.get(widget_key)
    if widget_type in MODULE_TYPES:
        st.session_state[durable_key] = widget_type


def prepare_project_module_inspector_min_match_widget_state(
    module_library,
    module_name,
    body_tokens,
) -> int:
    durable_key = f"project_module_inspector_min_match_{module_name}"
    widget_key = (
        f"_project_module_inspector_min_match_widget_{module_name}"
    )
    maximum = max(1, len(body_tokens))
    saved_min_match = get_module_min_match_tokens(module_library, module_name)
    try:
        default_min_match = int(saved_min_match)
    except (TypeError, ValueError):
        default_min_match = maximum
    if not default_min_match:
        default_min_match = maximum
    default_min_match = max(1, min(default_min_match, maximum))

    durable_value = st.session_state.get(durable_key, default_min_match)
    try:
        durable_min_match = int(durable_value)
    except (TypeError, ValueError):
        durable_min_match = default_min_match
    durable_min_match = max(1, min(durable_min_match, maximum))
    st.session_state[durable_key] = durable_min_match
    st.session_state[widget_key] = durable_min_match
    return durable_min_match


def sync_project_module_inspector_min_match_widget_state(
    module_name,
) -> None:
    widget_key = (
        f"_project_module_inspector_min_match_widget_{module_name}"
    )
    durable_key = f"project_module_inspector_min_match_{module_name}"
    try:
        st.session_state[durable_key] = int(
            st.session_state.get(widget_key, 1)
        )
    except (TypeError, ValueError):
        st.session_state[durable_key] = 1
