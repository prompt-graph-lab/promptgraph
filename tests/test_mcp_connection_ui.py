import json
from dataclasses import dataclass
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import mcp_connection_ui


@dataclass(frozen=True)
class _Operation:
    status: str


class _SessionRuntime:
    """Small session-owned API double; it exposes no Project or mailbox."""

    def __init__(
        self,
        status="unavailable",
        arm_status="ready",
        disarm_status="disarmed",
    ):
        self.status = status
        self.arm_status = arm_status
        self.disarm_status = disarm_status
        self.arm_calls = 0
        self.disarm_calls = 0

    def launcher_rendezvous_status(self):
        return _Operation(self.status)

    def arm_launcher_rendezvous(self):
        self.arm_calls += 1
        if self.arm_status in {"ready", "already_armed", "already_paired"}:
            self.status = "ready" if self.arm_status != "already_paired" else "claimed"
        return _Operation(self.arm_status)

    def disarm_launcher_rendezvous(self):
        self.disarm_calls += 1
        if self.disarm_status in {"disarmed", "released", "expired", "not_armed"}:
            self.status = self.disarm_status
        return _Operation(self.disarm_status)


def _start_ui(monkeypatch, runtime):
    monkeypatch.setattr(
        mcp_connection_ui,
        "get_project_agent_session_runtime",
        lambda: runtime,
    )
    app = AppTest.from_string(
        "from ui.mcp_connection_ui import render_mcp_connection_sidebar\n"
        "render_mcp_connection_sidebar()",
        default_timeout=30,
    ).run(timeout=30)
    assert not app.exception
    return app


def _visible_text(app):
    collections = (
        app.markdown,
        app.caption,
        app.info,
        app.success,
        app.warning,
        app.error,
        app.code,
    )
    return "\n".join(
        str(element.value)
        for collection in collections
        for element in collection
    )


def test_connection_ui_arms_only_the_current_session_and_tracks_waiting_connected_disconnect(
    monkeypatch,
):
    selected_session = _SessionRuntime()
    app = _start_ui(monkeypatch, selected_session)

    assert "Not connected / available" in _visible_text(app)
    app.button(key="mcp_connection_connect").click().run(timeout=30)
    assert not app.exception
    assert selected_session.arm_calls == 1
    assert selected_session.disarm_calls == 0
    assert "Waiting for MCP client" in _visible_text(app)

    selected_session.status = "claimed"
    app.run(timeout=30)
    assert "Connected" in _visible_text(app)

    app.button(key="mcp_connection_disconnect").click().run(timeout=30)
    assert not app.exception
    assert selected_session.disarm_calls == 1
    assert "Disconnected" in _visible_text(app)


def test_another_session_ownership_is_clear_and_cannot_be_disconnected_or_overridden(
    monkeypatch,
):
    current_session = _SessionRuntime(arm_status="already_owned")
    app = _start_ui(monkeypatch, current_session)

    app.button(key="mcp_connection_connect").click().run(timeout=30)
    assert not app.exception
    assert current_session.arm_calls == 1
    assert current_session.disarm_calls == 0
    text = _visible_text(app)
    assert "Another PromptGraph session owns the MCP connection" in text
    assert "Disconnect" not in [button.label for button in app.button]
    assert "mcp_connection_disconnect" not in {button.key for button in app.button}

    app.button(key="mcp_connection_connect").click().run(timeout=30)
    assert not app.exception
    assert current_session.arm_calls == 2
    assert current_session.disarm_calls == 0
    assert "Another PromptGraph session owns the MCP connection" in _visible_text(app)


def test_expired_offer_can_be_rearmed_for_the_same_session(monkeypatch):
    runtime = _SessionRuntime(status="expired")
    app = _start_ui(monkeypatch, runtime)

    assert "Expired / disconnected" in _visible_text(app)
    assert any(button.label == "Reconnect this session" for button in app.button)
    app.button(key="mcp_connection_connect").click().run(timeout=30)

    assert not app.exception
    assert runtime.arm_calls == 1
    assert "Waiting for MCP client" in _visible_text(app)


def test_launcher_guidance_uses_running_installation_values_without_pairing_secrets(
    monkeypatch,
):
    runtime = _SessionRuntime()
    app = _start_ui(monkeypatch, runtime)
    configuration = mcp_connection_ui.launcher_configuration_values()
    code_values = {element.value for element in app.code}

    assert configuration["command"] in code_values
    assert configuration["args"] == ["-m", "agent_adapters.mcp_named_pipe_launcher"]
    assert json.dumps(configuration["args"]) in code_values
    assert configuration["cwd"] in code_values
    assert "Python executable running PromptGraph" in _visible_text(app)
    assert "Working directory" in _visible_text(app)
    visible = _visible_text(app).casefold()
    for forbidden in ("descriptor_path", "capability", "route_id", "process_incarnation"):
        assert forbidden not in visible


def test_unavailable_broker_failure_is_bounded_and_human_readable(monkeypatch):
    runtime = _SessionRuntime(arm_status="rendezvous_unavailable")
    app = _start_ui(monkeypatch, runtime)

    app.button(key="mcp_connection_connect").click().run(timeout=30)

    assert not app.exception
    text = _visible_text(app)
    assert "MCP connection unavailable" in text
    assert "could not prepare this local connection" in text
    assert "rendezvous_unavailable" not in text


def test_session_provider_failure_is_bounded_and_does_not_expose_exception_text(
    monkeypatch,
):
    def fail_provider():
        raise RuntimeError("private session detail")

    monkeypatch.setattr(
        mcp_connection_ui,
        "get_project_agent_session_runtime",
        fail_provider,
    )
    app = AppTest.from_string(
        "from ui.mcp_connection_ui import render_mcp_connection_sidebar\n"
        "render_mcp_connection_sidebar()",
        default_timeout=30,
    ).run(timeout=30)

    assert not app.exception
    text = _visible_text(app)
    assert "MCP connection unavailable" in text
    assert "could not access this browser session" in text
    assert "private session detail" not in text


def test_project_switch_is_not_part_of_the_connection_ui_surface():
    repo_root = Path(__file__).resolve().parents[1]
    source = (repo_root / "ui" / "mcp_connection_ui.py").read_text(encoding="utf-8")
    app_source = (repo_root / "app.py").read_text(encoding="utf-8")

    assert "st.session_state.get(\"project\")" not in source
    assert "synchronize_target(" not in source
    assert "mailbox" not in source.casefold()
    assert "dispatch_project_agent_request" not in source
    pump = app_source.index("render_project_agent_request_pump()")
    connection = app_source.index("render_mcp_connection_sidebar()")
    # The tutorial guard also excludes Agent Review and spans multiple lines.
    tutorial = app_source.index("if (is_free() and st.session_state.show_tutorial")
    assert pump < connection < tutorial
