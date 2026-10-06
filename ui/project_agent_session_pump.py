"""Session-scoped wake-up and full-app service for agent requests.

The periodic fragment only wakes the normal Streamlit app run. The run-local
capture token and the existing request bridge are used by the synchronous
service point; neither the mailbox nor the fragment can capture a Project.
"""

from dataclasses import dataclass, field

import streamlit as st

from ui.project_agent_request_bridge import dispatch_project_agent_request
from ui.project_capture_safety import PROJECT_CAPTURE_RUN_TOKEN_KEY
from ui.project_agent_session_mailbox import (
    FRAGMENT_POLL_INTERVAL_SECONDS,
    ProjectAgentSessionMailbox,
    ProjectTargetTracker,
)
from ui.project_agent_session_registry import (
    PairingOperation,
    ProjectAgentSessionRegistration,
    ProjectAgentSessionRegistry,
    get_process_project_agent_session_registry,
)


@dataclass
class ProjectAgentSessionRuntime:
    """Session resource holding its mailbox, target tracker, and route authority."""

    mailbox: ProjectAgentSessionMailbox = field(default_factory=ProjectAgentSessionMailbox)
    target_tracker: ProjectTargetTracker = field(default_factory=ProjectTargetTracker)
    _registry: ProjectAgentSessionRegistry = field(
        default_factory=get_process_project_agent_session_registry,
        repr=False,
    )
    _registration: ProjectAgentSessionRegistration | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _named_pipe_broker: object = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self):
        self._registration = self._registry.register_session(self.mailbox)

    def synchronize_target(self, project, project_path):
        epoch = self.target_tracker.observe(project, project_path)
        self.mailbox.synchronize_target_epoch(epoch)
        return epoch

    def begin_full_app_run(self, project, project_path):
        epoch = self.synchronize_target(project, project_path)
        self.mailbox.begin_full_app_run(epoch)

    def arm_local_pairing(self):
        """Arm one short-lived offer for this session's own registered route."""

        if self._closed or self._registration is None:
            return PairingOperation("session_unavailable")
        return self._registration.arm_pairing()

    def publish_local_pairing_descriptor(self, broker=None):
        """Create a protected local descriptor for this session's exact route."""

        from ui.project_agent_named_pipe import (
            PairingDescriptorDelivery,
            WindowsNamedPipeBroker,
            get_process_project_agent_named_pipe_broker,
        )

        if self._closed or self._registration is None:
            return PairingDescriptorDelivery("session_unavailable")
        if broker is None:
            try:
                broker = get_process_project_agent_named_pipe_broker()
            except Exception:
                return PairingDescriptorDelivery("broker_unavailable")
        if type(broker) is not WindowsNamedPipeBroker:
            return PairingDescriptorDelivery("invalid_broker")
        result = broker.prepare_pairing_descriptor(self._registration)
        if result.status == "armed":
            self._named_pipe_broker = broker
        return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        route_id = None
        if self._registration is not None:
            route_id = self._registration.route_id
            # Remove external addressability before closing the mailbox. Any
            # in-flight paired operation is serialized with unregister.
            self._registration.unregister()
        if self._named_pipe_broker is not None and route_id is not None:
            self._named_pipe_broker.close_session_route(route_id)
        self.mailbox.close()
        self.target_tracker.close()


def _release_project_agent_session_runtime(runtime):
    """Public Streamlit session cleanup; safe to call without session context."""

    if type(runtime) is ProjectAgentSessionRuntime:
        runtime.close()


@st.cache_resource(
    scope="session",
    on_release=_release_project_agent_session_runtime,
)
def get_project_agent_session_runtime():
    """Return this browser session's isolated route/mailbox resource."""

    return ProjectAgentSessionRuntime()


@st.fragment(run_every=FRAGMENT_POLL_INTERVAL_SECONDS, parallel=False)
def _project_agent_request_pump_fragment():
    """Wake the full app once for pending work; never inspect Project state."""

    runtime = get_project_agent_session_runtime()
    if runtime.mailbox.fragment_tick():
        st.rerun(scope="app")


def render_project_agent_request_pump():
    """Register the session's periodic mailbox wake-up fragment."""

    _project_agent_request_pump_fragment()


def _is_current_run(session_state, run_token):
    if type(run_token) is not str or not run_token:
        return False
    try:
        return session_state.get(PROJECT_CAPTURE_RUN_TOKEN_KEY) == run_token
    except Exception:
        return False


def begin_project_agent_session_run(session_state, run_token):
    """Synchronize active target after session initialization and mark this run."""

    runtime = get_project_agent_session_runtime()
    if not _is_current_run(session_state, run_token):
        return runtime
    runtime.begin_full_app_run(
        session_state.get("project"),
        session_state.get("current_project_path", ""),
    )
    return runtime


def service_project_agent_session_request(
    runtime,
    session_state,
    run_token,
):
    """Run at one explicit full-app point and publish one bounded mailbox outcome."""

    if type(runtime) is not ProjectAgentSessionRuntime:
        return "unavailable"
    if not _is_current_run(session_state, run_token):
        return "stale_run"

    current_epoch = runtime.synchronize_target(
        session_state.get("project"),
        session_state.get("current_project_path", ""),
    )
    claim = runtime.mailbox._claim_for_service(current_epoch)
    if claim is None:
        return "idle"

    try:
        # No mailbox or target-tracker lock is held through Project capture,
        # clone, bridge validation, or adapter response processing.
        bridge_reply = dispatch_project_agent_request(
            session_state,
            run_token,
            claim.request,
        )
    except Exception:
        bridge_reply = None

    current_epoch = runtime.synchronize_target(
        session_state.get("project"),
        session_state.get("current_project_path", ""),
    )
    outcome = runtime.mailbox.complete(claim, bridge_reply, current_epoch)
    return outcome.status
