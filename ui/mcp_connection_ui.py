"""Human-facing controls for the current Streamlit session's MCP pairing."""

import json
from pathlib import Path
import sys

import streamlit as st

from ui.project_agent_session_pump import get_project_agent_session_runtime


MCP_CONNECTION_POLL_INTERVAL_SECONDS = 2.0
MCP_CONNECTION_NOTICE_KEY = "mcp_connection_ui_notice"
MCP_LAUNCHER_MODULE = "agent_adapters.mcp_named_pipe_launcher"

_ACTIVE_STATUSES = {"preparing", "ready", "claimed"}
_SUCCESSFUL_ARM_STATUSES = {"ready", "already_armed", "already_paired"}
_SUCCESSFUL_DISARM_STATUSES = {"disarmed", "released", "expired", "not_armed"}


def launcher_configuration_values():
    """Return stable launcher fields derived from this running installation."""

    return {
        "command": sys.executable,
        "args": ["-m", MCP_LAUNCHER_MODULE],
        "cwd": str(Path(__file__).resolve().parents[1]),
    }


def _bounded_status(operation):
    status = getattr(operation, "status", None)
    if type(status) is str and status.isascii() and status:
        return status
    return "unavailable"


def _read_status(runtime):
    try:
        return _bounded_status(runtime.launcher_rendezvous_status()), False
    except Exception:
        return "unavailable", True


def _status_presentation(status, notice=None):
    """Map internal bounded statuses to text safe for the human-facing UI."""

    if notice == "another_session":
        return (
            "warning",
            "Another PromptGraph session owns the MCP connection",
            "Disconnect it in that browser tab before trying this session again.",
        )
    if notice == "unavailable":
        return (
            "error",
            "MCP connection unavailable",
            "PromptGraph could not prepare this local connection. Check the supported Windows runtime and try again.",
        )
    if status in {"preparing", "ready"}:
        return (
            "info",
            "Waiting for MCP client",
            "Start your configured MCP client to connect this browser session.",
        )
    if status == "claimed":
        return (
            "success",
            "Connected",
            "The MCP client is paired with this browser session.",
        )
    if status == "expired":
        return (
            "warning",
            "Expired / disconnected",
            "The pairing offer expired. Reconnect this session to create a new offer.",
        )
    if status in {"disarmed", "released"}:
        return (
            "info",
            "Disconnected",
            "This browser session is no longer paired with an MCP client.",
        )
    if status in {"unavailable", "not_armed"}:
        return (
            "info",
            "Not connected / available",
            "Enable this browser session when you are ready to connect an MCP client.",
        )
    return (
        "error",
        "MCP connection unavailable",
        "PromptGraph could not read this session's connection status. Try again or restart PromptGraph.",
    )


def _record_arm_result(session_state, status):
    if status in _SUCCESSFUL_ARM_STATUSES:
        session_state.pop(MCP_CONNECTION_NOTICE_KEY, None)
    elif status == "already_owned":
        session_state[MCP_CONNECTION_NOTICE_KEY] = "another_session"
    else:
        session_state[MCP_CONNECTION_NOTICE_KEY] = "unavailable"


def _record_disarm_result(session_state, status):
    if status in _SUCCESSFUL_DISARM_STATUSES:
        session_state.pop(MCP_CONNECTION_NOTICE_KEY, None)
    else:
        session_state[MCP_CONNECTION_NOTICE_KEY] = "unavailable"


def _render_launcher_configuration():
    st.caption(
        "Use these stable launcher values in your MCP client's server setup. "
        "Field names vary by client; no temporary pairing details are needed."
    )
    configuration = launcher_configuration_values()
    st.caption("Python executable running PromptGraph")
    st.code(configuration["command"] or "Unavailable", language="text")
    st.caption("Arguments")
    st.code(json.dumps(configuration["args"]), language="json")
    st.caption("Working directory")
    st.code(configuration["cwd"], language="text")


def _render_mcp_connection_fragment():
    session_state = st.session_state
    try:
        runtime = get_project_agent_session_runtime()
    except Exception:
        runtime = None

    if runtime is None:
        st.markdown("**Status: MCP connection unavailable**")
        st.error(
            "PromptGraph could not access this browser session's connection. "
            "Try again or restart PromptGraph."
        )
        _render_launcher_configuration()
        return

    status, status_failed = _read_status(runtime)
    notice = session_state.get(MCP_CONNECTION_NOTICE_KEY)
    if status_failed:
        notice = "unavailable"

    if status in _ACTIVE_STATUSES:
        if st.button(
            "Disconnect",
            key="mcp_connection_disconnect",
            width="stretch",
        ):
            try:
                result = runtime.disarm_launcher_rendezvous()
            except Exception:
                result = None
            _record_disarm_result(session_state, _bounded_status(result))
    else:
        if notice == "another_session":
            connect_label = "Try connecting this session again"
        elif status == "expired":
            connect_label = "Reconnect this session"
        else:
            connect_label = "Enable / Connect this session"
        if st.button(
            connect_label,
            key="mcp_connection_connect",
            width="stretch",
            disabled=status == "session_unavailable",
        ):
            try:
                result = runtime.arm_launcher_rendezvous()
            except Exception:
                result = None
            _record_arm_result(session_state, _bounded_status(result))

    # Re-read after an action so the UI reflects the completed transition in
    # this fragment run. This is a session-owned rendezvous status lookup only.
    status, status_failed = _read_status(runtime)
    notice = session_state.get(MCP_CONNECTION_NOTICE_KEY)
    if status_failed:
        notice = "unavailable"
    tone, title, description = _status_presentation(status, notice)
    st.markdown(f"**Status: {title}**")
    if tone == "success":
        st.success(description)
    elif tone == "warning":
        st.warning(description)
    elif tone == "error":
        st.error(description)
    else:
        st.info(description)

    _render_launcher_configuration()


@st.fragment(run_every=MCP_CONNECTION_POLL_INTERVAL_SECONDS, parallel=False)
def _mcp_connection_sidebar_fragment():
    """Refresh only this session's connection controls and bounded status."""

    with st.expander("MCP Connection", expanded=False):
        _render_mcp_connection_fragment()


def render_mcp_connection_sidebar():
    """Render a session-local connection surface without touching Project state."""

    with st.sidebar:
        _mcp_connection_sidebar_fragment()
