"""Module Candidate Selection durable drafts and widget synchronization."""

import streamlit as st


def prepare_module_candidate_selection_widget_state(
    module_names,
) -> str:
    durable_key = "module_candidate_selection_name"
    widget_key = "_module_candidate_selection_name_widget"
    durable_name = st.session_state.get(durable_key)
    durable_repaired = durable_name not in module_names
    if durable_repaired:
        durable_name = module_names[0]
        st.session_state[durable_key] = durable_name

    st.session_state[widget_key] = durable_name
    return durable_name


def sync_module_candidate_selection_widget_state() -> None:
    widget_name = st.session_state.get("_module_candidate_selection_name_widget")
    if widget_name:
        st.session_state.module_candidate_selection_name = widget_name


def prepare_module_candidate_core_tokens_widget_state(
    module_name,
    module_tokens,
    current_core_tokens,
) -> list:
    durable_key = f"module_candidate_core_tokens_{module_name}"
    widget_key = f"_module_candidate_core_tokens_widget_{module_name}"
    durable_exists = durable_key in st.session_state
    durable_value = st.session_state.get(durable_key)
    if not durable_exists or not isinstance(durable_value, (list, tuple)):
        durable_tokens = list(current_core_tokens)
    else:
        durable_tokens = [
            token for token in durable_value if token in module_tokens
        ]
        if durable_value and not durable_tokens:
            durable_tokens = list(current_core_tokens)
    st.session_state[durable_key] = durable_tokens

    st.session_state[widget_key] = list(durable_tokens)
    return durable_tokens


def sync_module_candidate_core_tokens_widget_state(module_name) -> None:
    widget_key = f"_module_candidate_core_tokens_widget_{module_name}"
    durable_key = f"module_candidate_core_tokens_{module_name}"
    st.session_state[durable_key] = list(
        st.session_state.get(widget_key, [])
    )


def prepare_module_candidate_min_match_widget_state(
    module_name,
    module_tokens,
    current_min_match,
) -> int:
    durable_key = f"module_candidate_min_match_tokens_{module_name}"
    widget_key = f"_module_candidate_min_match_tokens_widget_{module_name}"
    durable_value = st.session_state.get(durable_key, current_min_match)
    try:
        durable_min_match = int(durable_value)
    except (TypeError, ValueError):
        durable_min_match = int(current_min_match)
    normalized_min_match = max(
        1,
        min(durable_min_match, len(module_tokens)),
    )
    durable_min_match = normalized_min_match
    st.session_state[durable_key] = durable_min_match

    st.session_state[widget_key] = durable_min_match
    return durable_min_match


def sync_module_candidate_min_match_widget_state(module_name) -> None:
    widget_key = f"_module_candidate_min_match_tokens_widget_{module_name}"
    durable_key = f"module_candidate_min_match_tokens_{module_name}"
    st.session_state[durable_key] = int(st.session_state[widget_key])
