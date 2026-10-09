"""Session-scoped wake-up and full-app service for agent requests.

The periodic fragment only wakes the normal Streamlit app run. The run-local
capture token and the existing request bridge are used by the synchronous
service point; neither the mailbox nor the fragment can capture a Project.
"""

from dataclasses import dataclass, field
import threading

import streamlit as st
from ui.agent_generation_review_custody import AgentGenerationReviewCustodian

from ui.project_agent_request_bridge import dispatch_project_agent_request
from ui.agent_scene_module_swap_approval_lifecycle import (
    AgentSceneModuleSwapApprovalCustodian,
    ApplyProposalClaim,
    DuplicateReviewReply,
    PreparedReviewReply,
)
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
    review_custodian: AgentSceneModuleSwapApprovalCustodian = field(
        default_factory=AgentSceneModuleSwapApprovalCustodian,
    )
    target_tracker: ProjectTargetTracker = field(default_factory=ProjectTargetTracker)
    generation_review_custodian: AgentGenerationReviewCustodian = field(default_factory=AgentGenerationReviewCustodian)
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
    _publication_gate: object = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )

    def __post_init__(self):
        self.mailbox._generation_review_custodian = self.generation_review_custodian
        self._registration = self._registry.register_session(self.mailbox)

    def synchronize_target(self, project, project_path):
        with self._publication_gate:
            if self._closed:
                return None
            return self._synchronize_target_locked(project, project_path)

    def _synchronize_target_locked(self, project, project_path):
        epoch = self.target_tracker.observe(project, project_path)
        self.mailbox.synchronize_target_epoch(
            epoch,
            review_custodian=self.review_custodian,
        )
        self.mailbox.synchronize_target_epoch(epoch, review_custodian=self.generation_review_custodian)
        return epoch

    def publish_review_apply(
        self,
        claim,
        *,
        session_state,
        source_project,
        project_path,
        target_epoch,
        history_snapshot,
        updated_project,
    ):
        """Serialize final claim validation with one host Project replacement.

        The gate excludes runtime target synchronization, explicit Disarm, and
        session cleanup through the commit boundary. Mailbox/custodian locks
        are held only for bounded claim/publication markers, never while the
        history or Project objects are changed.
        """

        with self._publication_gate:
            if self._closed:
                return "session_unavailable"
            active_project = session_state.get("project")
            active_path = session_state.get("current_project_path", "")
            try:
                current_epoch = self._synchronize_target_locked(
                    active_project,
                    active_path,
                )
            except Exception:
                return "session_unavailable"
            if (active_project is not source_project
                    or type(active_path) is not str
                    or type(project_path) is not str
                    or active_path != project_path
                    or current_epoch != target_epoch):
                return "stale"
            if not self.mailbox.review_apply_claim_is_current(
                self.review_custodian,
                claim,
            ):
                return "stale"

            # The full-app Streamlit run is serialized for this supported host
            # path, so ordinary Project mutators cannot run between this exact
            # source-content check and the session replacement. The pipe broker
            # and periodic fragment do not mutate Projects. The publication
            # gate additionally excludes runtime-owned target/disarm/close
            # transitions. Direct out-of-band mutation of a Project from an
            # unrelated thread is not a supported writer.
            try:
                source_unchanged = source_project == history_snapshot
            except Exception:
                source_unchanged = False
            if source_unchanged is not True:
                return "stale"

            # The equality check above covers the complete cloned Project,
            # including unrelated Scene prompts, Module Library, and derived
            # Project state. Re-read host identity immediately before staging
            # history so an intervening host navigation fails closed.
            active_project = session_state.get("project")
            active_path = session_state.get("current_project_path", "")
            try:
                current_epoch = self._synchronize_target_locked(
                    active_project,
                    active_path,
                )
            except Exception:
                return "session_unavailable"
            if (active_project is not source_project
                    or type(active_path) is not str
                    or type(project_path) is not str
                    or active_path != project_path
                    or current_epoch != target_epoch
                    or not self.mailbox.review_apply_claim_is_current(
                        self.review_custodian,
                        claim,
                    )):
                return "stale"

            history = session_state.get("history")
            if type(history) is not list:
                return "apply_failed"
            previous_first = history[0] if len(history) >= 20 else None
            appended = False
            evicted = False
            try:
                history.append(history_snapshot)
                appended = True
                if len(history) > 20:
                    history.pop(0)
                    evicted = True
            except Exception:
                if appended and history and history[-1] is history_snapshot:
                    history.pop()
                if evicted:
                    history.insert(0, previous_first)
                return "apply_failed"

            # Stage the private publication marker before the session-state
            # assignment, with all revokers excluded by this gate. If the
            # assignment fails, both the marker and history are rolled back.
            try:
                marked = self.mailbox.mark_review_proposal_apply_published(
                    self.review_custodian,
                    claim,
                )
            except Exception:
                marked = False
            if not marked:
                if history and history[-1] is history_snapshot:
                    history.pop()
                if evicted:
                    history.insert(0, previous_first)
                return "stale"

            try:
                session_state["project"] = updated_project
            except Exception:
                if session_state.get("project") is not updated_project:
                    try:
                        self.mailbox.rollback_review_proposal_apply_publication(
                            self.review_custodian,
                            claim,
                        )
                    except Exception:
                        pass
                    if history and history[-1] is history_snapshot:
                        history.pop()
                    if evicted:
                        history.insert(0, previous_first)
                    return "apply_failed"

            # The session replacement has now committed. Retire its queued
            # positive review ACK before target synchronization can classify
            # that old mailbox reply as stale.
            try:
                self.mailbox.complete_review_proposal_apply_publication(
                    self.review_custodian,
                    claim,
                )
            except Exception:
                pass

            try:
                self._synchronize_target_locked(updated_project, active_path)
            except Exception:
                # The replacement itself is already committed. Runtime target
                # observation can be retried by the next normal app run.
                pass
            return "published"

    def save_published_review_apply(
        self,
        claim,
        *,
        session_state,
        applied_project,
        project_path,
        save_project,
        reason,
    ):
        """Persist only the exact still-active Project committed by this Apply.

        The caller supplies the applied replacement and destination captured
        for the approved source target. The runtime gate fences target
        synchronization, Disarm, and close while it verifies that the current
        session still selects that same replacement/path and invokes the
        explicit persistence callback. Mailbox/custodian locks are released
        before the callback performs filesystem work.
        """

        with self._publication_gate:
            if self._closed:
                return "session_unavailable"
            active_project = session_state.get("project")
            active_path = session_state.get("current_project_path", "")
            try:
                self._synchronize_target_locked(active_project, active_path)
            except Exception:
                return "session_unavailable"
            if (active_project is not applied_project
                    or type(active_path) is not str
                    or type(project_path) is not str
                    or active_path != project_path):
                return "target_changed"
            if (not callable(save_project)
                    or not self.mailbox.review_apply_claim_is_current(
                        self.review_custodian,
                        claim,
                    )):
                return "session_unavailable"
            try:
                saved = save_project(applied_project, project_path, reason)
            except Exception:
                saved = False
            return "saved" if saved is True else "save_failed"

    def reconcile_published_review_apply(
        self,
        *,
        session_state,
        applied_project,
        project_path,
        previous_focus,
        synchronize_gallery_selection,
        restore_focus,
        sync_text_areas,
    ):
        """Reconcile host UI state only while the exact applied target is active."""

        with self._publication_gate:
            if self._closed:
                return "session_unavailable", False
            active_project = session_state.get("project")
            active_path = session_state.get("current_project_path", "")
            try:
                self._synchronize_target_locked(active_project, active_path)
            except Exception:
                return "session_unavailable", False
            if (active_project is not applied_project
                    or type(active_path) is not str
                    or type(project_path) is not str
                    or active_path != project_path):
                return "target_changed", False

            warning = False
            try:
                session_state["selected_node_ids"] = []
            except Exception:
                warning = True
            for callback, arguments in (
                (synchronize_gallery_selection, (applied_project,)),
                (restore_focus, (previous_focus,)),
                (sync_text_areas, ()),
            ):
                current_project = session_state.get("project")
                current_path = session_state.get("current_project_path", "")
                if (current_project is not applied_project
                        or type(current_path) is not str
                        or current_path != project_path):
                    return "target_changed", warning
                try:
                    if callable(callback):
                        callback(*arguments)
                except Exception:
                    warning = True

            current_project = session_state.get("project")
            current_path = session_state.get("current_project_path", "")
            if (current_project is not applied_project
                    or type(current_path) is not str
                    or current_path != project_path):
                return "target_changed", warning
            session_state.pop("module_swap_preview", None)
            session_state.pop("module_swap_selected_routes_confirm", None)
            return "reconciled", warning

    def inspect_review_custody(self):
        """Return review state through the mailbox/custodian coordination owner."""

        return self.mailbox.inspect_review_custody(self.review_custodian)

    def resolve_review_proposal(self, proposal_id, action):
        """Apply one exact human terminal action to custody and queued ACK state."""

        return self.mailbox.resolve_review_proposal(
            self.review_custodian,
            proposal_id,
            action,
        )

    def mark_review_proposal_stale(self, proposal_id):
        """Invalidate one proposal through the shared terminal transition owner."""

        return self.mailbox.mark_review_proposal_stale(
            self.review_custodian,
            proposal_id,
        )

    def claim_review_proposal_for_apply(
        self,
        proposal_id,
        target_epoch,
        intent,
        preview,
    ):
        """Consume one pending approval and return its one-shot private claim."""

        if self._closed:
            return "session_unavailable", None
        return self.mailbox.claim_review_proposal_for_apply(
            self.review_custodian,
            proposal_id,
            target_epoch,
            intent,
            preview,
        )

    def review_apply_claim_is_current(self, claim):
        if self._closed or type(claim) is not ApplyProposalClaim:
            return False
        return self.mailbox.review_apply_claim_is_current(
            self.review_custodian,
            claim,
        )

    def finish_review_proposal_apply(self, claim, status, result):
        if self._closed or type(claim) is not ApplyProposalClaim:
            return "session_unavailable"
        return self.mailbox.finish_review_proposal_apply(
            self.review_custodian,
            claim,
            status,
            result,
        )

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

    def arm_launcher_rendezvous(self, broker=None):
        """Arm this exact browser session for the fixed local launcher."""

        from ui.project_agent_named_pipe import (
            LauncherRendezvousOperation,
            WindowsNamedPipeBroker,
            get_process_project_agent_named_pipe_broker,
        )

        if self._closed or self._registration is None:
            return LauncherRendezvousOperation("session_unavailable")
        if broker is None:
            current = self._named_pipe_broker
            if (type(current) is WindowsNamedPipeBroker
                    and current._registry is self._registry):
                broker = current
            else:
                try:
                    broker = get_process_project_agent_named_pipe_broker()
                except Exception:
                    return LauncherRendezvousOperation("broker_unavailable")
        if (type(broker) is not WindowsNamedPipeBroker
                or broker._registry is not self._registry):
            return LauncherRendezvousOperation("invalid_broker")
        try:
            result = broker.arm_launcher_rendezvous(self._registration)
        except Exception:
            return LauncherRendezvousOperation("rendezvous_unavailable")
        if result.status in ("ready", "already_armed", "already_paired"):
            self._named_pipe_broker = broker
        return result

    def launcher_rendezvous_status(self):
        """Return bounded status for this session's exact launcher route."""

        from ui.project_agent_named_pipe import LauncherRendezvousOperation

        if self._closed or self._registration is None:
            return LauncherRendezvousOperation("session_unavailable")
        broker = self._named_pipe_broker
        if broker is None:
            return LauncherRendezvousOperation("unavailable")
        try:
            status = broker.launcher_rendezvous_status(self._registration)
        except Exception:
            status = "unavailable"
        return LauncherRendezvousOperation(status)

    def disarm_launcher_rendezvous(self):
        """Disarm this session's pending/claimed fixed-launcher route."""

        from ui.project_agent_named_pipe import LauncherRendezvousOperation

        with self._publication_gate:
            if self._closed or self._registration is None:
                return LauncherRendezvousOperation("session_unavailable")
            # Explicit host disarm cancels review custody. Ordinary pipe
            # release and client disconnect do not call this session method.
            self.mailbox.cancel_review_custody(self.review_custodian)
            self.mailbox.cancel_review_custody(self.generation_review_custodian)
            broker = self._named_pipe_broker
            registration = self._registration
        if broker is None:
            return LauncherRendezvousOperation("unavailable")
        try:
            return broker.disarm_launcher_rendezvous(registration)
        except Exception:
            return LauncherRendezvousOperation("unavailable")

    def close(self):
        with self._publication_gate:
            if self._closed:
                return
            self._closed = True
            # This shares the publication gate with final Apply commit, then
            # closes the mailbox/custodian under their fixed lock order.
            self.mailbox.close(review_custodian=self.review_custodian)
            self.generation_review_custodian.close()
            self.target_tracker.close()
            registration = self._registration
            route_id = registration.route_id if registration is not None else None
            broker = self._named_pipe_broker
        if registration is not None:
            # The mailbox and custodian are already closed. Remove external
            # addressability without holding either owner or publication lock.
            registration.unregister()
        if broker is not None and route_id is not None:
            broker.close_session_route(route_id)
            if registration is not None:
                broker.forget_launcher_rendezvous(registration)


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
    *, generation_context_provider=None,
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
            review_custodian=runtime.review_custodian,
            pairing_generation=claim.pairing_generation,
            target_epoch=claim.target_epoch,
            candidate_session_identity=(runtime._registration.route_id
                                        if runtime._registration is not None else None),
            generation_context_provider=generation_context_provider,
            generation_review_custodian=runtime.generation_review_custodian,
        )
    except Exception:
        bridge_reply = None

    current_epoch = runtime.synchronize_target(
        session_state.get("project"),
        session_state.get("current_project_path", ""),
    )
    if (claim.request.get("tool") == "promptgraph_request_generation_review"
            and type(bridge_reply) in (PreparedReviewReply, DuplicateReviewReply)):
        # Revalidate fresh content/config at the mailbox publication boundary.
        # A plan ID remains a precondition, never an execution capability.
        try:
            fresh = dispatch_project_agent_request(session_state, run_token,
                {"request_id": claim.request["request_id"], "tool": "promptgraph_preview_generation",
                 "arguments": {"scene_id": claim.request["arguments"]["scene_id"],
                               "run_count": claim.request["arguments"]["run_count"]}},
                pairing_generation=claim.pairing_generation, target_epoch=claim.target_epoch,
                candidate_session_identity=runtime._registration.route_id,
                generation_context_provider=generation_context_provider)
        except Exception:
            fresh = None
        result = fresh.get("result", {}) if type(fresh) is dict else {}
        if (result.get("valid") is not True
                or result.get("plan_id") != claim.request["arguments"]["expected_plan_id"]):
            runtime.mailbox.cancel_review_custody(runtime.generation_review_custodian)
            from agent_adapters.mcp_adapter import generation_review_failure
            bridge_reply = {"bridge_contract_version": "promptgraph.app-agent-request-bridge.v1",
                            "request_id": claim.request["request_id"], "status": "completed",
                            "result": generation_review_failure("stale_preview")}
        current_epoch = runtime.synchronize_target(session_state.get("project"),
            session_state.get("current_project_path", ""))
    if type(bridge_reply) is PreparedReviewReply:
        outcome = runtime.mailbox.complete_with_review(
            claim,
            bridge_reply,
            current_epoch,
            (runtime.generation_review_custodian if claim.request.get("tool") == "promptgraph_request_generation_review"
             else runtime.review_custodian),
        )
    elif type(bridge_reply) is DuplicateReviewReply:
        outcome = runtime.mailbox.complete_with_duplicate_review(
            claim,
            bridge_reply,
            current_epoch,
            (runtime.generation_review_custodian if claim.request.get("tool") == "promptgraph_request_generation_review"
             else runtime.review_custodian),
        )
    else:
        outcome = runtime.mailbox.complete(claim, bridge_reply, current_epoch)
    return outcome.status
