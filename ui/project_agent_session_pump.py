"""Session-scoped wake-up and full-app service for agent requests.

The periodic fragment only wakes the normal Streamlit app run. The run-local
capture token and the existing request bridge are used by the synchronous
service point; neither the mailbox nor the fragment can capture a Project.
"""

from dataclasses import dataclass, field
import threading

import streamlit as st
from ui.agent_generation_review_custody import AgentGenerationReviewCustodian
from ui.agent_generation_job import GenerationJobRegistry
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_original_host_lifecycle import (
    GenerationWorkerCorrelation,
    GenerationWorkerResultObservation,
    OriginalHostGenerationLifecycle,
    _HostEvidence,
    unavailable_readiness,
)

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
    generation_jobs: GenerationJobRegistry = field(default_factory=GenerationJobRegistry)
    _generation_executor_inbox: GenerationExecutorInbox = field(default_factory=GenerationExecutorInbox, repr=False)
    # Private original-host publication evidence; never sent to the executor.
    _generation_publication_origin: object = field(default=None, init=False, repr=False)
    _generation_candidate_publication: object = field(default=None, init=False, repr=False)
    _generation_protected_candidate_admission: object = field(default=None, init=False, repr=False)
    # Non-executing, exact original-host binding; never sent to a worker.
    _generation_original_host_lifecycle: object = field(default=None, init=False, repr=False)
    _generation_original_host_lifecycle_opt_in: bool = field(default=False, init=False, repr=False)
    _generation_original_host_lifecycle_reason: str = field(default="lifecycle_not_opted_in", init=False, repr=False)
    # Host-only, one bounded detached executable carrier and acknowledgment.
    # These are never session widget values, mailbox replies or Start authority.
    _executable_review: object = field(default=None, init=False, repr=False)
    _executable_confirmation: object = field(default=None, init=False, repr=False)
    _executable_revision: int = field(default=0, init=False, repr=False)
    _executable_target_epoch: object = field(default=None, init=False, repr=False)
    _executable_proposal_id: object = field(default=None, init=False, repr=False)
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
        # The tracker epoch binds exact Project object/path activation, including
        # switch-away/back and Save As. No Project/path enters the job owner.
        self.generation_jobs.synchronize_target(epoch, epoch)
        self._prune_executable_review_locked(epoch)
        self._synchronize_generation_original_host_lifecycle_locked(project, project_path, epoch)
        return epoch

    def _retire_generation_original_host_lifecycle_locked(self, reason):
        lifecycle = self._generation_original_host_lifecycle
        self._generation_original_host_lifecycle = None
        if lifecycle is not None:
            lifecycle._retire_for_replacement(reason)

    def _synchronize_generation_original_host_lifecycle_locked(self, project, project_path, epoch):
        if not self._generation_original_host_lifecycle_opt_in:
            return
        lifecycle = self._generation_original_host_lifecycle
        evidence, unavailable_reason = self._capture_generation_host_evidence_locked(
            project, project_path, epoch,
        )
        if evidence is None:
            reason = {
                "no_active_project": "target_replaced",
                "route_unavailable": "route_replaced",
                "runtime_closed": "session_closed",
            }.get(unavailable_reason, "host_evidence_unavailable")
            self._retire_generation_original_host_lifecycle_locked(reason)
            self._generation_original_host_lifecycle_reason = unavailable_reason
            return
        if lifecycle is not None and lifecycle._reconcile_evidence(evidence):
            self._generation_original_host_lifecycle_reason = None
            return
        if lifecycle is not None:
            reason = lifecycle._replacement_reason(evidence)
            if reason == "terminal_same_binding":
                self._generation_original_host_lifecycle_reason = "host_evidence_unavailable"
                return
            self._retire_generation_original_host_lifecycle_locked(reason)
        try:
            self._generation_original_host_lifecycle = (
                OriginalHostGenerationLifecycle._create_for_runtime(self, evidence)
            )
        except Exception:
            self._generation_original_host_lifecycle = None
            self._generation_original_host_lifecycle_reason = "host_evidence_unavailable"
        else:
            self._generation_original_host_lifecycle_reason = None

    def _capture_generation_host_evidence_locked(self, project, project_path, epoch):
        if project is None:
            return None, "no_active_project"
        if type(project_path) is not str or len(project_path) > 4096:
            return None, "host_evidence_unavailable"
        registration = self._registration
        if (self._closed or type(registration) is not ProjectAgentSessionRegistration
                or registration._closed or registration._registry is not self._registry
                or type(registration.route_id) is not str):
            return None, "route_unavailable"
        try:
            route_available, pairing_generation = registration.inspect_pairing_generation()
            process_incarnation = self._registry.process_incarnation
        except Exception:
            return None, "route_unavailable"
        if route_available is not True:
            return None, "route_unavailable"

        from ui.agent_generation_job import _PROCESS_INCARNATION
        from ui.agent_generation_executor_inbox import ExecutionEnvelope

        jobs = self.generation_jobs
        inbox = self._generation_executor_inbox
        with jobs._lock:
            if (jobs._closed or jobs._target != (epoch, epoch)
                    or type(jobs._session_incarnation) is not str):
                return None, "host_evidence_unavailable"
            session_incarnation = jobs._session_incarnation
            with inbox._lock:
                if inbox._closed or inbox._state == "invalidated":
                    return None, "host_evidence_unavailable"
                envelope = inbox._envelope
                job = None
                job_id = claim_id = manifest_identity = None
                request_count = 0
                if envelope is not None:
                    if (type(envelope) is not ExecutionEnvelope
                            or inbox._state not in {"offered", "accepted", "unknown"}):
                        return None, "host_evidence_unavailable"
                    job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                    if job is None:
                        return None, "host_evidence_unavailable"
                    binding = envelope.binding
                    if (binding.session_id != session_incarnation
                            or binding.process_incarnation != _PROCESS_INCARNATION
                            or (binding.target_epoch, binding.activation_id) != (epoch, epoch)
                            or binding.pairing_generation != pairing_generation
                            or job.binding != binding or job.claim_id != envelope.claim_id):
                        return None, "host_evidence_unavailable"
                    job_id = envelope.job_id
                    claim_id = envelope.claim_id
                    manifest_identity = envelope.manifest.manifest_identity
                    request_count = len(envelope.manifest.requests)
                evidence = _HostEvidence(
                    runtime=self,
                    project=project,
                    project_path=project_path,
                    target_epoch=epoch,
                    activation_id=epoch,
                    registry=self._registry,
                    registration=registration,
                    route_id=registration.route_id,
                    process_incarnation=process_incarnation,
                    session_incarnation=session_incarnation,
                    job_process_incarnation=_PROCESS_INCARNATION,
                    jobs=jobs,
                    inbox=inbox,
                    pairing_generation=pairing_generation,
                    job=job,
                    envelope=envelope,
                    job_id=job_id,
                    claim_id=claim_id,
                    manifest_identity=manifest_identity,
                    request_count=request_count,
                )
        return evidence, None

    def opt_in_generation_original_host_lifecycle_for_characterization(self, project, project_path):
        """Explicitly bind this runtime for offline lifecycle characterization only."""
        with self._publication_gate:
            if self._closed:
                return "runtime_closed"
            self._generation_original_host_lifecycle_opt_in = True
            self._synchronize_target_locked(project, project_path)
            if self._generation_original_host_lifecycle is not None:
                return "bound_non_executing"
            return self._generation_original_host_lifecycle_reason

    def inspect_generation_original_host_readiness(self, *, purpose_roots=None, capacity_owner=None):
        """Return a safe readiness projection; never refresh native storage here."""
        with self._publication_gate:
            if self._closed:
                return unavailable_readiness("runtime_closed")
            lifecycle = self._generation_original_host_lifecycle
            if lifecycle is None:
                return unavailable_readiness(self._generation_original_host_lifecycle_reason)
            if purpose_roots is not None or capacity_owner is not None:
                lifecycle.observe_protected_references_for_characterization(
                    purpose_roots, capacity_owner,
                )
            return lifecycle.readiness()

    def generation_worker_correlation_for_characterization(self):
        """Return opaque correlation only; this does not start or authorize a Worker."""
        with self._publication_gate:
            lifecycle = self._generation_original_host_lifecycle
            if self._closed or lifecycle is None:
                return GenerationWorkerCorrelation("lifecycle_unavailable")
            return lifecycle.worker_correlation_for_characterization()

    def observe_generation_worker_result_for_characterization(self, observation):
        """Record only bounded correlation; never advances the Job Registry."""
        if type(observation) is not GenerationWorkerResultObservation:
            return "invalid_observation"
        with self._publication_gate:
            lifecycle = self._generation_original_host_lifecycle
            if self._closed or lifecycle is None:
                return "stale_non_authoritative"
            return lifecycle.observe_worker_result_for_characterization(observation)

    def _clear_executable_review_locked(self):
        self._executable_review = None
        self._executable_confirmation = None
        self._executable_target_epoch = None
        self._executable_proposal_id = None
        self._executable_revision += 1

    def _prune_executable_review_locked(self, epoch):
        if self._executable_target_epoch is None:
            return
        record = self.mailbox.inspect_review_custody(self.generation_review_custodian)
        if (epoch != self._executable_target_epoch or record.get("state") != "pending"
                or record.get("proposal_id") != self._executable_proposal_id):
            self._clear_executable_review_locked()

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
            self._clear_executable_review_locked()
            self._retire_generation_original_host_lifecycle_locked("pairing_replaced")
            self._generation_original_host_lifecycle_reason = "route_unavailable"
            broker = self._named_pipe_broker
            self.generation_jobs.invalidate_execution_custody()
            self._generation_executor_inbox.invalidate()
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
            self._clear_executable_review_locked()
            lifecycle = self._generation_original_host_lifecycle
            self._generation_original_host_lifecycle = None
            self._generation_original_host_lifecycle_reason = "runtime_closed"
            if lifecycle is not None:
                lifecycle.close()
            admission = self._generation_protected_candidate_admission
            if admission is not None:
                admission._close_under_runtime_gate()
            # This shares the publication gate with final Apply commit, then
            # closes the mailbox/custodian under their fixed lock order.
            self.mailbox.close(review_custodian=self.review_custodian)
            self.generation_review_custodian.close()
            self.generation_jobs.close()
            self._generation_executor_inbox.close()
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
            runtime.mailbox.fail_generation_review_publication(
                claim, bridge_reply, runtime.generation_review_custodian)
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
