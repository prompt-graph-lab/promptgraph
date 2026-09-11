"""Durable ComfyUI analysis drafts and transient widget mirrors."""

import streamlit as st


def _get_comfyui_analysis_workspace_drafts() -> dict:
    drafts = st.session_state.get("comfyui_analysis_workspace_drafts")
    if not isinstance(drafts, dict):
        drafts = {}
        st.session_state.comfyui_analysis_workspace_drafts = drafts
    for section_name in (
        "inspector",
        "prompt_injection",
        "lora_mapping",
        "lora_injection",
    ):
        if not isinstance(drafts.get(section_name), dict):
            drafts[section_name] = {}
    if not isinstance(drafts["lora_injection"].get("strengths"), dict):
        drafts["lora_injection"]["strengths"] = {}
    return drafts


def _normalize_comfyui_draft_scalar(value, default):
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, float):
        if isinstance(value, bool):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return default


def _prepare_comfyui_draft_widget(
    section_name: str,
    draft_key: str,
    widget_key: str,
    default,
):
    section = _get_comfyui_analysis_workspace_drafts()[section_name]
    value = st.session_state.get(widget_key, section.get(draft_key, default))
    value = _normalize_comfyui_draft_scalar(value, default)
    st.session_state[widget_key] = value
    section[draft_key] = value
    return value


def _snapshot_comfyui_draft_widget(
    section_name: str,
    draft_key: str,
    widget_key: str,
    value,
    default,
):
    normalized = _normalize_comfyui_draft_scalar(value, default)
    _get_comfyui_analysis_workspace_drafts()[section_name][draft_key] = normalized
    return normalized


def _comfyui_draft_option_id(option, identity_key: str | None):
    if identity_key is None:
        return str(option or "")
    if isinstance(option, dict):
        return str(option.get(identity_key) or "")
    return str(option or "")


def _prepare_comfyui_draft_option(
    section_name: str,
    draft_key: str,
    widget_key: str,
    options: list,
    *,
    identity_key: str | None = None,
    default_index: int = 0,
):
    section = _get_comfyui_analysis_workspace_drafts()[section_name]
    requested = ""
    has_requested = False
    if widget_key in st.session_state:
        widget_value = st.session_state.get(widget_key)
        has_requested = (
            isinstance(widget_value, str)
            if identity_key is None
            else (
                isinstance(widget_value, dict)
                and isinstance(widget_value.get(identity_key), str)
            )
        )
        if has_requested:
            requested = _comfyui_draft_option_id(
                widget_value,
                identity_key,
            )
    elif draft_key in section:
        draft_value = section.get(draft_key)
        has_requested = isinstance(draft_value, str)
        if has_requested:
            requested = draft_value
    normalized_index = (
        min(max(int(default_index or 0), 0), len(options) - 1)
        if options
        else 0
    )
    if not options:
        selected = None
    elif not has_requested:
        selected = options[normalized_index]
    else:
        selected = next(
            (
                option
                for option in options
                if _comfyui_draft_option_id(option, identity_key) == requested
            ),
            options[normalized_index],
        )
    if selected is None:
        st.session_state.pop(widget_key, None)
        section[draft_key] = ""
        return None
    st.session_state[widget_key] = selected
    section[draft_key] = _comfyui_draft_option_id(selected, identity_key)
    return selected


def _normalize_comfyui_draft_option(
    section_name: str,
    draft_key: str,
    options: list,
    *,
    identity_key: str | None = None,
    default_index: int = 0,
):
    section = _get_comfyui_analysis_workspace_drafts()[section_name]
    has_requested = draft_key in section and isinstance(
        section.get(draft_key),
        str,
    )
    requested = section.get(draft_key, "") if has_requested else ""
    normalized_index = (
        min(max(int(default_index or 0), 0), len(options) - 1)
        if options
        else 0
    )
    if not options:
        selected = None
    elif not has_requested:
        selected = options[normalized_index]
    else:
        selected = next(
            (
                option
                for option in options
                if _comfyui_draft_option_id(option, identity_key) == requested
            ),
            options[normalized_index],
        )
    section[draft_key] = (
        _comfyui_draft_option_id(selected, identity_key)
        if selected is not None
        else ""
    )
    return selected


def _snapshot_comfyui_draft_option(
    section_name: str,
    draft_key: str,
    widget_key: str,
    value,
    *,
    identity_key: str | None = None,
):
    _get_comfyui_analysis_workspace_drafts()[section_name][draft_key] = (
        _comfyui_draft_option_id(value, identity_key)
    )
    return value


def _clear_comfy_workflow_inspector_state() -> None:
    drafts = _get_comfyui_analysis_workspace_drafts()
    drafts["inspector"] = {
        "text": "",
        "show_fields": False,
        "active_input": "",
    }
    st.session_state.comfy_workflow_inspector_raw_text = ""
    st.session_state.comfy_workflow_inspector_source = "workflow JSON"
    st.session_state.pop("comfy_workflow_inspector_text", None)
    st.session_state.pop("comfy_workflow_inspector_show_fields", None)
