"""Apply-workspace Attribute Group Swap draft/widget synchronization."""

import streamlit as st


def prepare_attribute_group_swap_from_widget_state(group_keys) -> str:
    durable_key = "attribute_group_swap_from"
    widget_key = "_attribute_group_swap_from_widget"
    valid_group_keys = list(group_keys)
    durable_value = st.session_state.get(durable_key)
    if durable_value not in valid_group_keys:
        durable_value = valid_group_keys[0] if valid_group_keys else ""
    st.session_state[durable_key] = durable_value
    st.session_state[widget_key] = durable_value
    return durable_value


def sync_attribute_group_swap_from_widget_state() -> None:
    st.session_state.attribute_group_swap_from = st.session_state.get(
        "_attribute_group_swap_from_widget",
        "",
    )


def prepare_attribute_group_swap_to_widget_state(
    group_keys,
    from_group_key,
) -> str:
    durable_key = "attribute_group_swap_to"
    widget_key = "_attribute_group_swap_to_widget"
    valid_group_keys = list(group_keys)
    durable_value = st.session_state.get(durable_key)
    if durable_value not in valid_group_keys:
        durable_value = next(
            (
                group_key
                for group_key in valid_group_keys
                if group_key != from_group_key
            ),
            "",
        )
    st.session_state[durable_key] = durable_value
    st.session_state[widget_key] = durable_value
    return durable_value


def sync_attribute_group_swap_to_widget_state() -> None:
    st.session_state.attribute_group_swap_to = st.session_state.get(
        "_attribute_group_swap_to_widget",
        "",
    )


def prepare_attribute_group_swap_scope_widget_state(scope_options) -> str:
    durable_key = "attribute_group_swap_scope"
    widget_key = "_attribute_group_swap_scope_widget"
    valid_scopes = list(scope_options)
    durable_value = st.session_state.get(durable_key)
    if durable_value not in valid_scopes:
        durable_value = "all_lines"
    st.session_state[durable_key] = durable_value
    st.session_state[widget_key] = durable_value
    return durable_value


def sync_attribute_group_swap_scope_widget_state() -> None:
    st.session_state.attribute_group_swap_scope = st.session_state.get(
        "_attribute_group_swap_scope_widget",
        "all_lines",
    )


def prepare_attribute_group_swap_selected_route_widget_state(
    route_ids,
) -> str:
    durable_key = "attribute_group_swap_selected_route_id"
    widget_key = "_attribute_group_swap_selected_route_id_widget"
    valid_route_ids = list(route_ids)
    durable_value = st.session_state.get(durable_key)
    if durable_value not in valid_route_ids:
        durable_value = valid_route_ids[0] if valid_route_ids else ""
    st.session_state[durable_key] = durable_value
    st.session_state[widget_key] = durable_value
    return durable_value


def sync_attribute_group_swap_selected_route_widget_state() -> None:
    st.session_state.attribute_group_swap_selected_route_id = (
        st.session_state.get(
            "_attribute_group_swap_selected_route_id_widget",
            "",
        )
    )


def prepare_attribute_group_swap_require_full_match_widget_state() -> bool:
    durable_key = "attribute_group_swap_require_full_match"
    widget_key = "_attribute_group_swap_require_full_match_widget"
    durable_value = st.session_state.get(durable_key)
    if not isinstance(durable_value, bool):
        durable_value = False
    st.session_state[durable_key] = durable_value
    st.session_state[widget_key] = durable_value
    return durable_value


def sync_attribute_group_swap_require_full_match_widget_state() -> None:
    widget_value = st.session_state.get(
        "_attribute_group_swap_require_full_match_widget",
        False,
    )
    st.session_state.attribute_group_swap_require_full_match = (
        widget_value if isinstance(widget_value, bool) else False
    )
