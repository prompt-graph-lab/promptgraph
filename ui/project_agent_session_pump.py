"""Session-scoped wake-up and full-app service for agent requests.

The periodic fragment only wakes the normal Streamlit app run. The run-local
capture token and the existing request bridge are used by the synchronous
service point; neither the mailbox nor the fragment can capture a Project.
"""

from contextlib import contextmanager
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
    _normalize_target_path,
)
from ui.project_agent_session_registry import (
    PairingOperation,
    ProjectAgentSessionRegistration,
    ProjectAgentSessionRegistry,
    get_process_project_agent_session_registry,
)


_MAX_RETIRED_GENERATION_WORKER_STORAGE = 16


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
    # Revoked owners remain strongly held while a Worker may still be active
    # or uncertain. Binding stops at this bounded retention ceiling until a
    # terminal, non-uncertain close has been explicitly observed.
    _retired_generation_worker_storage_integrations: list = field(
        default_factory=list, init=False, repr=False,
    )
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
            integration = lifecycle._worker_storage_integration
            if (integration is not None
                    and integration not in self._retired_generation_worker_storage_integrations
                    and len(self._retired_generation_worker_storage_integrations)
                    < _MAX_RETIRED_GENERATION_WORKER_STORAGE):
                self._retired_generation_worker_storage_integrations.append(integration)
            lifecycle._retire_for_replacement(reason)

    @contextmanager
    def _current_generation_original_host_lifecycle_locked(self):
        """Hold the exact live pairing boundary during one local observation.

        The runtime publication gate is already held by callers. Lock order is
        route operation lock, registry snapshot lock, then the lifecycle's
        short lock. The route and registry locks remain held through the
        bounded local observation. No Project, job, or inbox lock is acquired.
        """
        lifecycle = self._generation_original_host_lifecycle
        if self._closed or lifecycle is None:
            yield None
            return

        registration = self._registration
        if registration is not lifecycle._registration:
            self._retire_generation_original_host_lifecycle_locked("route_replaced")
            self._generation_original_host_lifecycle_reason = "route_unavailable"
            yield None
            return

        with self._registry._pairing_generation_guard(registration) as (
            route_available, pairing_generation,
        ):
            mismatch = (
                None
                if route_available is True
                else "route_replaced"
            )
            if mismatch is None:
                mismatch = lifecycle._route_snapshot_mismatch(
                    registry=self._registry,
                    registration=registration,
                    process_incarnation=self._registry.process_incarnation,
                    pairing_generation=pairing_generation,
                )
            if mismatch is not None:
                self._retire_generation_original_host_lifecycle_locked(mismatch)
                self._generation_original_host_lifecycle_reason = "route_unavailable"
                yield None
                return
            yield lifecycle

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

    def _generation_original_host_evidence_current_locked(self, lifecycle, pairing_generation):
        """Check the exact target, claim, and pairing while the route guard is held.

        Lock order is publication gate -> route/registry guard -> target
        tracker -> Job Registry -> Inbox -> lifecycle -> worker-storage owner.
        This is a bounded in-memory check; it performs no Worker, network,
        Journal, filesystem, Project, or host callback work.
        """
        from ui.agent_generation_job import _TERMINAL

        if (lifecycle is not self._generation_original_host_lifecycle
                or self._closed or self._registration is not lifecycle._registration
                or self._registry is not lifecycle._registry
                or self._registry.process_incarnation != lifecycle._process_incarnation
                or self.generation_jobs is not lifecycle._jobs
                or self._generation_executor_inbox is not lifecycle._inbox):
            return False
        project = lifecycle._project_ref()
        if project is None:
            return False
        tracker = self.target_tracker
        with tracker._lock:
            if (not tracker._initialized or not tracker._had_project
                    or tracker._project_ref is None or tracker._project_ref() is not project
                    or tracker._project_path != _normalize_target_path(lifecycle._project_path)
                    or tracker._epoch != lifecycle._target_epoch):
                return False

        jobs, inbox = self.generation_jobs, self._generation_executor_inbox
        with jobs._lock:
            if (jobs._closed or jobs._target != (lifecycle._target_epoch, lifecycle._activation_id)
                    or jobs._session_incarnation != lifecycle._session_incarnation):
                return False
            with inbox._lock:
                if inbox._closed or inbox._state == "invalidated":
                    return False
                envelope = inbox._envelope
                if envelope is not lifecycle._envelope:
                    return False
                job = job_id = claim_id = manifest_identity = None
                request_count = 0
                if envelope is not None:
                    if inbox._state not in {"offered", "accepted", "unknown"}:
                        return False
                    job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                    binding = envelope.binding
                    if (job is None or job.state in _TERMINAL
                            or job is not lifecycle._job
                            or binding.session_id != lifecycle._session_incarnation
                            or binding.process_incarnation != lifecycle._job_process_incarnation
                            or binding.target_epoch != lifecycle._target_epoch
                            or binding.activation_id != lifecycle._activation_id
                            or binding.pairing_generation != pairing_generation
                            or job.binding != binding or job.claim_id != envelope.claim_id):
                        return False
                    job_id, claim_id = envelope.job_id, envelope.claim_id
                    manifest_identity = envelope.manifest.manifest_identity
                    request_count = len(envelope.manifest.requests)
                evidence = _HostEvidence(
                    runtime=self,
                    project=project,
                    project_path=lifecycle._project_path,
                    target_epoch=lifecycle._target_epoch,
                    activation_id=lifecycle._activation_id,
                    registry=self._registry,
                    registration=self._registration,
                    route_id=self._registration.route_id,
                    process_incarnation=self._registry.process_incarnation,
                    session_incarnation=jobs._session_incarnation,
                    job_process_incarnation=lifecycle._job_process_incarnation,
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
                with lifecycle._lock:
                    return (
                        lifecycle._same_host_locked(evidence)
                        and lifecycle._job is job
                        and lifecycle._envelope is envelope
                        and lifecycle._job_id == job_id
                        and lifecycle._claim_id == claim_id
                        and lifecycle._manifest_identity == manifest_identity
                        and lifecycle._request_count == request_count
                    )

    def bind_generation_worker_storage_for_characterization(
        self, worker, purpose_roots, capacity_owner,
    ):
        """Associate supplied owners only; never starts a worker or opens roots."""
        from ui.agent_generation_original_host_worker_storage import (
            OriginalHostWorkerStorageIntegration,
        )

        with self._publication_gate:
            if self._closed:
                return "runtime_closed"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return self._generation_original_host_lifecycle_reason or "lifecycle_unavailable"
                if not self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation,
                ):
                    self._retire_generation_original_host_lifecycle_locked("host_evidence_unavailable")
                    return "host_evidence_unavailable"
                if len(self._retired_generation_worker_storage_integrations) >= \
                        _MAX_RETIRED_GENERATION_WORKER_STORAGE:
                    return "retained_worker_storage_limit"
                _, status = OriginalHostWorkerStorageIntegration._bind_for_runtime(
                    lifecycle, self, worker, purpose_roots, capacity_owner,
                )
                return status

    def generation_worker_http_correlation_for_characterization(
        self, request_index, *, kind, prompt_id=None,
    ):
        """Issue bounded request correlation after live host/claim verification."""
        with self._publication_gate:
            if self._closed:
                return None
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return None
                if not self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation,
                ):
                    self._retire_generation_original_host_lifecycle_locked("host_evidence_unavailable")
                    return None
                integration = lifecycle._worker_storage_integration
                if integration is None:
                    return None
                return integration.correlation_for_request_for_characterization(
                    request_index, kind=kind, prompt_id=prompt_id,
                )

    def begin_generation_worker_http_operation_for_characterization(
        self, kind, prepared, prompt_id, correlation,
    ):
        """Pin one operation lease after exact current-host revalidation."""
        with self._publication_gate:
            if self._closed:
                return None, "runtime_closed"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return None, "lifecycle_unavailable"
                if not self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation,
                ):
                    self._retire_generation_original_host_lifecycle_locked("host_evidence_unavailable")
                    return None, "host_evidence_unavailable"
                integration = lifecycle._worker_storage_integration
                if integration is None:
                    return None, "integration_unavailable"
                return integration.begin_operation_for_characterization(
                    kind, prepared, prompt_id, correlation,
                )

    def observe_generation_worker_http_result_for_characterization(
        self, lease, completion,
    ):
        """Return a typed result to its exact live host as non-authority only."""
        lifecycle_snapshot = self._generation_original_host_lifecycle
        integration_snapshot = (getattr(lifecycle_snapshot, "_worker_storage_integration", None)
                                if lifecycle_snapshot is not None else None)
        if integration_snapshot is None:
            return "stale_non_authoritative"
        # Snapshot the actual supplied Worker before taking host/route/job locks.
        try:
            worker_observation = integration_snapshot.worker_observation()
        except Exception:
            integration_snapshot.revoke("host_evidence_unavailable")
            return "uncertain_non_authoritative"

        with self._publication_gate:
            if self._closed or self._generation_original_host_lifecycle is not lifecycle_snapshot:
                current = False
            else:
                with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                    current = lifecycle is lifecycle_snapshot
                    if current:
                        current = self._generation_original_host_evidence_current_locked(
                            lifecycle, lifecycle._pairing_generation,
                        )
                        if not current:
                            self._retire_generation_original_host_lifecycle_locked(
                                "host_evidence_unavailable",
                            )
                    if current:
                        return integration_snapshot.observe_result_for_characterization(
                            lease, completion, worker_observation, current=True,
                        )
        # A late result remains attached to the old owner and can only be
        # retained as stale diagnostic evidence. It cannot advance any host
        # state or release a lease made uncertain by revocation.
        integration_snapshot.observe_result_for_characterization(
            lease, completion, worker_observation, current=False,
        )
        return "stale_non_authoritative"

    def inspect_generation_worker_storage_for_characterization(self):
        """Return safe status without exposing owner, root, or correlation refs."""
        from ui.agent_generation_original_host_worker_storage import unavailable_observation

        with self._publication_gate:
            if self._closed:
                return unavailable_observation("runtime_closed")
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None or not self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation,
                ):
                    if lifecycle is not None:
                        self._retire_generation_original_host_lifecycle_locked(
                            "host_evidence_unavailable",
                        )
                    return unavailable_observation("host_evidence_unavailable")
                integration = lifecycle._worker_storage_integration
        return (integration.readiness() if integration is not None
                else unavailable_observation("integration_unavailable"))

    def finish_generation_worker_storage_close_for_characterization(self):
        """Perform one bounded Worker join outside every host/registry lock."""
        with self._publication_gate:
            candidates = list(self._retired_generation_worker_storage_integrations)
            lifecycle = self._generation_original_host_lifecycle
            current = getattr(lifecycle, "_worker_storage_integration", None) if lifecycle else None
            if current is not None and current not in candidates:
                candidates.append(current)
        integration = fallback = None
        for owner in candidates:
            with owner._lock:
                owner_state = owner._state
            if owner_state == "bound_non_executing":
                continue
            if fallback is None:
                fallback = owner
            try:
                worker_view = owner.worker_observation()
            except Exception:
                integration = owner
                break
            if worker_view.thread_alive or worker_view.state not in {
                    "closed", "uncertain_stopped", "start_failed"}:
                integration = owner
                break
        if integration is None:
            integration = fallback
        if integration is None:
            return None
        observation = integration.finish_close_for_characterization()
        if (observation.lifecycle_state == "closed"
                and observation.active_operations == 0
                and observation.retained_uncertain_operations == 0):
            with self._publication_gate:
                if integration in self._retired_generation_worker_storage_integrations:
                    self._retired_generation_worker_storage_integrations.remove(integration)
        return observation

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
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return unavailable_readiness(self._generation_original_host_lifecycle_reason)
                if purpose_roots is not None or capacity_owner is not None:
                    lifecycle.observe_protected_references_for_characterization(
                        purpose_roots, capacity_owner,
                    )
                return lifecycle.readiness()

    def bind_generation_profile_a_storage_for_characterization(
            self, capacity_owner, project_reference):
        """Bind a Profile A root set to the exact current Project lifecycle.

        Native storage and Project-file observations run between two host
        snapshots, outside the publication, route, and lifecycle locks. The
        second snapshot must still identify the same lifecycle, target epoch,
        Project object/path, session, route and pairing before references are
        published. This is characterization only and grants no write gate.
        """
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_storage import WindowsProjectJsonReferenceCharacterization
        from ui.project_agent_session_mailbox import _normalize_target_path

        if (type(capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization
                or type(project_reference) is not WindowsProjectJsonReferenceCharacterization):
            return "binding_invalid"

        with self._publication_gate:
            if self._closed:
                return "runtime_closed"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return "lifecycle_unavailable"
                with lifecycle._lock:
                    if lifecycle._state != "bound_non_executing":
                        return "lifecycle_unavailable"
                    generation = lifecycle._generation
                    project = lifecycle._project_ref()
                    project_path = lifecycle._project_path
                    target_epoch = lifecycle._target_epoch
                    pairing_generation = lifecycle._pairing_generation
                with self.target_tracker._lock:
                    target_matches = (
                        self.target_tracker._initialized
                        and self.target_tracker._project_ref is not None
                        and self.target_tracker._project_ref() is project
                        and self.target_tracker._project_path == _normalize_target_path(project_path)
                        and self.target_tracker._epoch == target_epoch
                    )
                if not target_matches or project is None or not project_path:
                    return "host_target_unavailable"
                if not self._generation_original_host_evidence_current_locked(
                        lifecycle, pairing_generation):
                    self._retire_generation_original_host_lifecycle_locked(
                        "host_evidence_unavailable",
                    )
                    return "host_evidence_unavailable"

        # These calls can enumerate native storage, inspect ACLs and reopen the
        # selected file path. They must stay outside every host publication lock.
        capacity_view = capacity_owner.readiness()
        project_view = project_reference.readiness()
        if (capacity_view.get("status") != "characterization_only"
                or capacity_view.get("root_set_contract") != "profile_a_four_writable_roots"
                or capacity_view.get("scope_writer_lease") != "held"
                or project_view.get("status") != "read_only_reference_observed"):
            return "storage_observation_unavailable"
        if (_normalize_target_path(str(project_reference._path))
                != _normalize_target_path(project_path)):
            return "project_reference_mismatch"

        with self._publication_gate:
            if self._closed:
                return "runtime_closed"
            with self._current_generation_original_host_lifecycle_locked() as current:
                if current is not lifecycle:
                    return "stale_host_binding"
                with lifecycle._lock:
                    if (lifecycle._state != "bound_non_executing"
                            or lifecycle._generation != generation
                            or lifecycle._project_ref() is not project
                            or lifecycle._project_path != project_path
                            or lifecycle._target_epoch != target_epoch):
                        return "stale_host_binding"
                with self.target_tracker._lock:
                    target_matches = (
                        self.target_tracker._initialized
                        and self.target_tracker._project_ref is not None
                        and self.target_tracker._project_ref() is project
                        and self.target_tracker._project_path == _normalize_target_path(project_path)
                        and self.target_tracker._epoch == target_epoch
                    )
                if not target_matches:
                    return "stale_host_binding"
                if not self._generation_original_host_evidence_current_locked(
                        lifecycle, pairing_generation):
                    self._retire_generation_original_host_lifecycle_locked(
                        "host_evidence_unavailable",
                    )
                    return "host_evidence_unavailable"
                try:
                    return capacity_owner._bind_profile_a_lifecycle_for_characterization(
                        lifecycle, project_reference,
                    )
                except ValueError:
                    return "storage_binding_unavailable"

    def generation_worker_correlation_for_characterization(self):
        """Return opaque correlation only; this does not start or authorize a Worker."""
        with self._publication_gate:
            if self._closed:
                return GenerationWorkerCorrelation("lifecycle_unavailable")
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return GenerationWorkerCorrelation("lifecycle_unavailable")
                return lifecycle.worker_correlation_for_characterization()

    def observe_generation_worker_result_for_characterization(self, observation):
        """Record only bounded correlation; never advances the Job Registry."""
        if type(observation) is not GenerationWorkerResultObservation:
            return "invalid_observation"
        with self._publication_gate:
            if self._closed:
                return "stale_non_authoritative"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
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
                integration = lifecycle._worker_storage_integration
                if (integration is not None
                        and integration not in self._retired_generation_worker_storage_integrations
                        and len(self._retired_generation_worker_storage_integrations)
                        < _MAX_RETIRED_GENERATION_WORKER_STORAGE):
                    self._retired_generation_worker_storage_integrations.append(integration)
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
