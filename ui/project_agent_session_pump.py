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

    def _generation_original_host_evidence_current_locked(
            self, lifecycle, pairing_generation, *, on_current=None):
        """Check the exact target, claim, and pairing while the route guard is held.

        Lock order is publication gate -> route/registry guard -> target
        tracker -> Job Registry -> Inbox -> lifecycle -> storage owner. An
        optional internal in-memory publication callback runs while Job
        Registry and Inbox custody remain locked, so claim invalidation cannot
        slip between the final check and binding publication. The callback
        performs no Worker I/O, network, Journal, filesystem, Project, or host
        callback work.
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
                    current = (
                        lifecycle._same_host_locked(evidence)
                        and lifecycle._job is job
                        and lifecycle._envelope is envelope
                        and lifecycle._job_id == job_id
                        and lifecycle._claim_id == claim_id
                        and lifecycle._manifest_identity == manifest_identity
                        and lifecycle._request_count == request_count
                    )
                if not current:
                    return False
                return on_current() if on_current is not None else True

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
                if integration._profile_a:
                    correlation = self._generation_original_host_evidence_current_locked(
                        lifecycle, lifecycle._pairing_generation,
                        on_current=lambda: integration.correlation_for_request_for_characterization(
                            request_index, kind=kind, prompt_id=prompt_id,
                        ),
                    )
                    if correlation is False:
                        self._retire_generation_original_host_lifecycle_locked(
                            "host_evidence_unavailable",
                        )
                        return None
                    return correlation
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
                if integration._profile_a:
                    result = self._generation_original_host_evidence_current_locked(
                        lifecycle, lifecycle._pairing_generation,
                        on_current=lambda: integration.begin_operation_for_characterization(
                            kind, prepared, prompt_id, correlation,
                        ),
                    )
                    if result is False:
                        self._retire_generation_original_host_lifecycle_locked(
                            "host_evidence_unavailable",
                        )
                        return None, "host_evidence_unavailable"
                    return result
                return integration.begin_operation_for_characterization(
                    kind, prepared, prompt_id, correlation,
                )

    def pre_admit_generation_worker_staging_for_characterization(self, lease, estimate):
        """Reserve staging capacity for one exact Profile A Worker lease only.

        This two-phase observation deliberately stops before the existing
        `admit_write` boundary. Capacity and Project-reference readiness run
        outside host/Job/Inbox/lifecycle locks; exact host and reservation
        custody are then revalidated at the in-memory publication point.
        """
        from core.generation_storage_admission import CapacityEstimate

        if type(estimate) is not CapacityEstimate:
            return None, "invalid_capacity_estimate"
        captured = {}
        with self._publication_gate:
            if self._closed:
                return None, "runtime_closed"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return None, self._generation_original_host_lifecycle_reason or "lifecycle_unavailable"
                integration = lifecycle._worker_storage_integration
                if integration is None:
                    return None, "integration_unavailable"

                def begin_attempt():
                    attempt, status = integration._begin_staging_preadmission_for_characterization(
                        lifecycle, lease, estimate,
                    )
                    if attempt is not None:
                        captured.update({
                            "lifecycle": lifecycle,
                            "integration": integration,
                            "capacity_owner": integration._capacity_owner,
                            "project_reference": integration._project_reference,
                            "pairing_generation": lifecycle._pairing_generation,
                            "attempt": attempt,
                        })
                    return attempt, status

                result = self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation, on_current=begin_attempt,
                )
                if result is False:
                    self._retire_generation_original_host_lifecycle_locked("host_evidence_unavailable")
                    return None, "host_evidence_unavailable"
                attempt, status = result
                if attempt is None:
                    return None, status

        integration = captured["integration"]
        capacity_owner = captured["capacity_owner"]
        try:
            capacity_operation = capacity_owner.begin_operation_for_characterization(
                captured["attempt"].operation_id,
            )
        except ValueError:
            integration._finish_staging_preadmission(captured["attempt"], "refused")
            return None, "capacity_refused"
        except Exception:
            self._invalidate_uncertain_profile_a_capacity(capacity_owner)
            integration._finish_staging_preadmission(
                captured["attempt"], "retained_uncertain",
            )
            return None, "capacity_uncertain"

        if not integration._attach_staging_capacity_operation(
                captured["attempt"], capacity_operation):
            integration._finish_staging_preadmission(captured["attempt"], "cancelled")
            return None, "cancelled_before_reserve"

        try:
            reservation = capacity_owner.reserve_for_characterization(
                capacity_operation, {"temporary_containment": estimate},
            )
        except ValueError:
            integration._finish_staging_preadmission(captured["attempt"], "refused")
            return None, "capacity_refused"
        except Exception:
            # An unexpected failure at the reserve boundary cannot prove that
            # no ledger token was committed. Closing the existing owner moves
            # any unsettled reservation to its retained-uncertain accounting.
            self._invalidate_uncertain_profile_a_capacity(capacity_owner)
            integration._finish_staging_preadmission(
                captured["attempt"], "retained_uncertain",
            )
            return None, "capacity_uncertain"

        if not integration._attach_staging_reservation(captured["attempt"], reservation):
            integration._cancel_staging_preadmission_attempt(captured["attempt"])
            return None, "cancelled_before_publication"

        try:
            # These owners perform their filesystem/native observations here,
            # with no host, Job, Inbox, lifecycle or integration lock held.
            capacity_view = capacity_owner.readiness()
            project_view = captured["project_reference"].readiness()
        except Exception:
            integration._cancel_staging_preadmission_attempt(captured["attempt"])
            return None, "storage_observation_unavailable"

        with self._publication_gate:
            if (self._closed
                    or self._generation_original_host_lifecycle is not captured["lifecycle"]):
                result = None
                status = "stale_host_binding"
            else:
                with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                    if lifecycle is not captured["lifecycle"]:
                        result = None
                        status = "stale_host_binding"
                    else:
                        def publish_attempt():
                            return integration._publish_staging_preadmission_locked(
                                lifecycle, lease, captured["attempt"],
                                capacity_view, project_view,
                            )

                        result = self._generation_original_host_evidence_current_locked(
                            lifecycle, captured["pairing_generation"],
                            on_current=publish_attempt,
                        )
                        if result is False:
                            self._retire_generation_original_host_lifecycle_locked(
                                "host_evidence_unavailable",
                            )
                            status = "host_evidence_unavailable"
                        elif type(result) is tuple:
                            observation, status = result
                            if observation is not None:
                                return observation, status
                        else:
                            status = "host_evidence_unavailable"
        # If final host publication lost a race, release only the exact
        # pre-write reservation. A closed/invalid owner retains it uncertain.
        integration._cancel_staging_preadmission_attempt(captured["attempt"])
        return None, status

    def cancel_generation_worker_staging_preadmission_for_characterization(self, observation):
        """Release an exact pre-admission observation; never yields writer authority."""
        lifecycle = self._generation_original_host_lifecycle
        integration = (lifecycle._worker_storage_integration if lifecycle is not None else None)
        if integration is None:
            return "preadmission_unavailable"
        return integration.cancel_staging_preadmission_for_characterization(observation)

    def observe_generation_worker_remote_output_writer_evidence_for_characterization(
            self, observation):
        """Validate one exact remote-history result without authorizing a write.

        This binds the existing 19D reservation to host-owned Worker evidence
        and the existing remote-output validator. It intentionally stops
        before `admit_write`, download, or any protected file operation.
        """
        import hashlib
        import json

        from core.comfy_http_submission import SubmissionResult
        from core.comfy_output_containment import ContainmentLimits, SUPPORTED_EXTENSIONS
        from core.comfy_remote_output_receipts import (
            MAX_REMOTE_IMAGES, RemoteOutputReceipt, decode_remote_json,
            valid_prompt_id, validate_remote_outputs,
        )
        from core.generation_storage_admission import CapacityEstimate
        from core.comfy_prompt_request import is_owner_prepared_frozen_request
        from ui.agent_generation_original_host_worker_storage import (
            GenerationWorkerRemoteOutputWriterEvidence,
            GenerationWorkerStoragePreAdmissionObservation,
            _MAX_WRITER_IMAGES, _MAX_WRITER_IMAGE_BYTES, _MAX_WRITER_REQUEST_BYTES,
        )
        from ui.agent_generation_http_io_worker import HTTPIOCompletion
        from core.comfy_http_history import HistoryResult

        if type(observation) is not GenerationWorkerStoragePreAdmissionObservation:
            return None, "invalid_preadmission"
        lifecycle_snapshot = self._generation_original_host_lifecycle
        integration_snapshot = (getattr(lifecycle_snapshot, "_worker_storage_integration", None)
                                if lifecycle_snapshot is not None else None)
        if integration_snapshot is None or integration_snapshot._profile_a is not True:
            return None, "profile_a_integration_unavailable"
        captured = {}

        with self._publication_gate:
            if (self._closed
                    or self._generation_original_host_lifecycle is not lifecycle_snapshot):
                return None, "stale_host_binding"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is not lifecycle_snapshot:
                    return None, "stale_host_binding"

                def begin_validation():
                    started, status = integration_snapshot._begin_remote_output_writer_evidence_validation_locked(
                        lifecycle, observation,
                    )
                    if started is not None:
                        (attempt, marker, envelope, prepared, prompt_id, submission,
                         history_lease, history, history_json) = started
                        captured.update({
                            "lifecycle": lifecycle,
                            "integration": integration_snapshot,
                            "capacity_owner": integration_snapshot._capacity_owner,
                            "project_reference": integration_snapshot._project_reference,
                            "attempt": attempt,
                            "marker": marker,
                            "envelope": envelope,
                            "prepared": prepared,
                            "prompt_id": prompt_id,
                            "submission": submission,
                            "history_lease": history_lease,
                            "history": history,
                            "history_json": history_json,
                            "generation": lifecycle._generation,
                            "project": lifecycle._project_ref(),
                            "project_path": lifecycle._project_path,
                            "target_epoch": lifecycle._target_epoch,
                            "activation_id": lifecycle._activation_id,
                            "pairing_generation": lifecycle._pairing_generation,
                            "job": lifecycle._job,
                            "job_id": lifecycle._job_id,
                            "claim_id": lifecycle._claim_id,
                            "manifest_identity": lifecycle._manifest_identity,
                        })
                    return started, status

                start_result = self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation, on_current=begin_validation,
                )
                if start_result is False:
                    self._retire_generation_original_host_lifecycle_locked(
                        "host_evidence_unavailable",
                    )
                    return None, "host_evidence_unavailable"
                if type(start_result) is tuple:
                    started, status = start_result
                    if started is None:
                        return None, status
                else:
                    return None, "host_evidence_unavailable"

        integration = captured["integration"]
        attempt, marker = captured["attempt"], captured["marker"]

        def fail(reason, *, uncertain=False):
            integration._fail_remote_output_writer_evidence_validation(
                attempt, marker, "uncertain" if uncertain else "refused",
                cancel_reservation=not uncertain,
            )
            return None, reason

        try:
            prepared = captured["prepared"]
            prompt_id = captured["prompt_id"]
            history = captured["history"]
            history_json = captured["history_json"]
            estimate = attempt.estimate
            limits = ContainmentLimits()
            if (not is_owner_prepared_frozen_request(prepared)
                    or prepared is not attempt.prepared
                    or not valid_prompt_id(prompt_id)
                    or type(estimate) is not CapacityEstimate
                    or type(estimate.byte_upper_bound) is not int
                    or type(estimate.entry_upper_bound) is not int
                    or not 1 <= estimate.byte_upper_bound <= min(
                        _MAX_WRITER_REQUEST_BYTES, limits.aggregate_bytes,
                    )
                    or not 1 <= estimate.entry_upper_bound <= _MAX_WRITER_IMAGES):
                return fail("writer_capacity_policy_incompatible")

            submission = captured["submission"]
            history_lease = captured["history_lease"]
            history_completion = captured["history"]
            if (type(submission) is not HTTPIOCompletion
                    or submission.kind != "submission"
                    or type(submission.outcome) is not SubmissionResult
                    or submission.outcome.status != "accepted"
                    or type(history_completion) is not HTTPIOCompletion
                    or history_completion.kind != "history"
                    or type(history_completion.outcome) is not HistoryResult
                    or history_completion.outcome.status != "ready"):
                return fail("worker_completion_evidence_invalid", uncertain=True)
            submission_correlation = attempt.lease.correlation
            history_correlation = history_lease.correlation
            try:
                submission_payload = decode_remote_json(submission.outcome.response_json)
            except Exception:
                return fail("submission_prompt_evidence_invalid", uncertain=True)
            if (type(submission_payload) is not dict
                    or submission_payload.get("prompt_id") != prompt_id
                    or history_correlation.prompt_id != prompt_id
                    or history_correlation.operation_id != submission_correlation.operation_id
                    or history_correlation.job_id != submission_correlation.job_id
                    or history_correlation.claim_id != submission_correlation.claim_id
                    or history_correlation.manifest_identity != submission_correlation.manifest_identity
                    or history_correlation.session_identity != submission_correlation.session_identity
                    or history_correlation.process_identity != submission_correlation.process_identity
                    or history_correlation.request_id != submission_correlation.request_id
                    or history_correlation.request_index != submission_correlation.request_index
                    or history_correlation.illustration_id != submission_correlation.illustration_id
                    or history_correlation.run_index != submission_correlation.run_index
                    or history_correlation.workflow_identity != submission_correlation.workflow_identity
                    or type(history_completion.outcome.history_json) is not bytes
                    or history_completion.outcome.history_json != history_json):
                return fail("remote_output_correlation_mismatch", uncertain=True)

            # The completion remains the exact Worker-issued object captured at
            # original-host result observation. No caller-provided receipt is
            # accepted or used as the source of truth.
            worker_view = integration.worker_observation()
            if (worker_view.state != "running" or not worker_view.started
                    or worker_view.in_flight or worker_view.terminal
                    or not integration._worker._is_issued_completion_for_prepared_request_for_characterization(
                        history_completion, prepared,
                    )):
                return fail("worker_history_evidence_unavailable", uncertain=True)

            try:
                remote = validate_remote_outputs(
                    captured["envelope"], prepared, prompt_id, history_json,
                )
            except Exception:
                return fail("remote_history_validation_failed")
            if (type(remote) is not RemoteOutputReceipt
                    or remote.execution_succeeded is not True
                    or remote.job_id != captured["job_id"]
                    or remote.claim_id != captured["claim_id"]
                    or remote.manifest_identity != captured["manifest_identity"]
                    or remote.request_id != prepared.request_id
                    or remote.request_index != prepared.request_index
                    or remote.workflow_identity != prepared.workflow_identity
                    or remote.prompt_id != prompt_id
                    or remote._validated_history_json != history_json
                    or type(remote.images) is not tuple
                    or not 1 <= len(remote.images) <= min(MAX_REMOTE_IMAGES, _MAX_WRITER_IMAGES)
                    or len({image.identity for image in remote.images}) != len(remote.images)
                    or any(image.image_format not in SUPPORTED_EXTENSIONS for image in remote.images)):
                return fail("remote_output_descriptor_policy_failed")

            image_count = len(remote.images)
            required_estimate = min(
                _MAX_WRITER_REQUEST_BYTES, _MAX_WRITER_IMAGE_BYTES * image_count,
            )
            if (estimate.byte_upper_bound < required_estimate
                    or estimate.byte_upper_bound > _MAX_WRITER_REQUEST_BYTES
                    or estimate.entry_upper_bound < image_count):
                return fail("writer_capacity_policy_incompatible")

            history_identity = hashlib.sha256(history_json).hexdigest()
            evidence_payload = [
                "promptgraph.remote-output-writer-evidence.v1",
                integration._operation_id, attempt.lease.nonce,
                captured["job_id"], captured["claim_id"],
                captured["manifest_identity"], prepared.request_id,
                prepared.request_index, prepared.workflow_identity, prompt_id,
                remote.identity, history_identity,
                [image.identity for image in remote.images],
                estimate.byte_upper_bound, estimate.entry_upper_bound,
                _MAX_WRITER_REQUEST_BYTES, _MAX_WRITER_IMAGE_BYTES, _MAX_WRITER_IMAGES,
            ]
            evidence_identity = hashlib.sha256(json.dumps(
                evidence_payload, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            evidence = GenerationWorkerRemoteOutputWriterEvidence(
                identity=evidence_identity,
                request_index=prepared.request_index,
                descriptor_count=image_count,
                request_byte_upper_bound=estimate.byte_upper_bound,
                request_entry_upper_bound=estimate.entry_upper_bound,
                history_identity=history_identity,
                remote_output_identity=remote.identity,
                _issuer=integration,
                _attempt_nonce=attempt.lease.nonce,
            )
        except Exception:
            return fail("remote_output_evidence_unavailable")

        try:
            # Fresh native roots/ACL/inventory and Project-reference evidence
            # is deliberately collected outside every host/job/inbox lock.
            capacity_view = captured["capacity_owner"].readiness()
            project_view = captured["project_reference"].readiness()
        except Exception:
            return fail("storage_observation_unavailable")

        host_snapshot = {
            key: captured[key] for key in (
                "generation", "project", "project_path", "target_epoch",
                "activation_id", "pairing_generation", "envelope", "job",
                "job_id", "claim_id", "manifest_identity",
            )
        }
        status = "stale_host_binding"
        result = None
        with self._publication_gate:
            if (self._closed
                    or self._generation_original_host_lifecycle is not captured["lifecycle"]):
                pass
            else:
                with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                    if lifecycle is captured["lifecycle"]:
                        result = self._generation_original_host_evidence_current_locked(
                            lifecycle, captured["pairing_generation"],
                            on_current=lambda: integration._publish_remote_output_writer_evidence_locked(
                                lifecycle, attempt, marker, host_snapshot, remote, evidence,
                                capacity_view, project_view,
                            ),
                        )
                        if result is False:
                            self._retire_generation_original_host_lifecycle_locked(
                                "host_evidence_unavailable",
                            )
                            status = "host_evidence_unavailable"
                        elif type(result) is tuple:
                            evidence_result, status = result
                            if evidence_result is not None:
                                return evidence_result, status
        integration._fail_remote_output_writer_evidence_validation(
            attempt, marker,
            "uncertain" if status == "worker_completion_changed" else "revoked",
            cancel_reservation=status != "worker_completion_changed",
        )
        return None, status

    def stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            self, evidence, writer_owner, *, stream_provider,
            characterization=False, disposable_opt_in=False):
        """Stage exactly one 19E-A image through the original 19D reservation.

        The result is a count-only non-authoritative observation. The image,
        descriptor, write token, native identity and bytes remain retained by
        their issuing owners and are never returned as publication authority.
        """
        from core.generation_storage_admission import (
            WindowsProtectedStorageAdmissionCharacterization,
        )
        from core.generation_windows_protected_assets import (
            WindowsProtectedAssetsCharacterization,
        )
        from ui.agent_generation_original_host_worker_storage import (
            GenerationWorkerRemoteOutputWriterEvidence,
        )

        if characterization is not True or disposable_opt_in is not True:
            return None, "execution_unavailable"
        if (type(evidence) is not GenerationWorkerRemoteOutputWriterEvidence
                or type(writer_owner) is not WindowsProtectedAssetsCharacterization
                or not callable(stream_provider)):
            return None, "writer_handoff_arguments_invalid"

        lifecycle_snapshot = self._generation_original_host_lifecycle
        integration_snapshot = (getattr(lifecycle_snapshot, "_worker_storage_integration", None)
                                if lifecycle_snapshot is not None else None)
        if (integration_snapshot is None or integration_snapshot._profile_a is not True
                or type(integration_snapshot._capacity_owner)
                    is not WindowsProtectedStorageAdmissionCharacterization):
            return None, "profile_a_writer_handoff_unavailable"

        captured = {}
        with self._publication_gate:
            if (self._closed
                    or self._generation_original_host_lifecycle is not lifecycle_snapshot):
                return None, "stale_host_binding"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is not lifecycle_snapshot:
                    return None, "stale_host_binding"

                def begin_handoff():
                    started, status = integration_snapshot._begin_single_image_writer_handoff_locked(
                        lifecycle, evidence, writer_owner,
                    )
                    if started is not None:
                        attempt = started[0]
                        captured.update({
                            "lifecycle": lifecycle,
                            "integration": integration_snapshot,
                            "capacity_owner": integration_snapshot._capacity_owner,
                            "project_reference": integration_snapshot._project_reference,
                            "purpose_roots": integration_snapshot._purpose_roots,
                            "attempt": attempt,
                            "marker": started[1],
                            "envelope": started[2],
                            "prepared": started[3],
                            "remote": started[4],
                            "descriptor": started[5] if len(started) > 5 else None,
                            "operation": started[-2],
                            "reservation": started[-1],
                            "evidence": evidence,
                            "writer_owner": writer_owner,
                            "generation": lifecycle._generation,
                            "pairing_generation": lifecycle._pairing_generation,
                        })
                    return started, status

                start_result = self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation, on_current=begin_handoff,
                )
                if start_result is False:
                    self._retire_generation_original_host_lifecycle_locked(
                        "host_evidence_unavailable",
                    )
                    return None, "host_evidence_unavailable"
                if not type(start_result) is tuple:
                    return None, "host_evidence_unavailable"
                started, status = start_result
                if started is None:
                    return None, status

        integration = captured["integration"]
        attempt, marker = captured["attempt"], captured["marker"]
        if status == "single_image_output_required":
            integration._cancel_staging_preadmission_attempt(attempt)
            return None, status
        if status != "handoff_claimed" or marker is None:
            return None, status

        def retain_completed_write_if_needed(image):
            try:
                if captured["capacity_owner"]._reservation_terminal_state_for_characterization(
                        captured["operation"], captured["reservation"],
                ) != "completed":
                    return
                if image is None:
                    attempt_key = (captured["prepared"].request_id,
                                   captured["remote"].images[0].identity)
                    with writer_owner._lock:
                        image = writer_owner._stream_images.get(attempt_key)
                if image is None:
                    self._invalidate_uncertain_profile_a_capacity(captured["capacity_owner"])
                    return
                captured["capacity_owner"].retain_completed_asset_stream_write_uncertain_for_characterization(
                    captured["operation"], captured["attempt"].writer_admission,
                    writer_owner, image,
                )
            except Exception:
                # The handoff itself remains unresolved and fences scope-lease
                # release even if an exact compensation observation fails.
                self._invalidate_uncertain_profile_a_capacity(captured["capacity_owner"])

        def fail_before_or_after_write(reason, *, uncertain=False, image=None):
            if uncertain:
                retain_completed_write_if_needed(image)
            if not uncertain:
                integration._settle_cancelled_single_image_writer_handoff(
                    attempt, marker, writer_owner,
                )
            state = integration._fail_single_image_writer_handoff(
                attempt, marker, uncertain=uncertain,
            )
            if state == "writer_handoff_stale":
                return None, reason
            return None, reason

        try:
            # Root/ACL/inventory and selected-Project reference observations
            # run outside every host, Job, Inbox, lifecycle and Worker lock.
            capacity_view = captured["capacity_owner"].readiness()
            project_view = captured["project_reference"].readiness()
            writer_view = writer_owner.readiness()
        except Exception:
            integration._cancel_staging_preadmission_attempt(attempt)
            return fail_before_or_after_write("writer_handoff_storage_observation_unavailable")

        if (capacity_view.get("status") != "characterization_only"
                or capacity_view.get("root_set_contract") != "profile_a_four_writable_roots"
                or capacity_view.get("scope_writer_lease") != "held"
                or project_view.get("status") != "read_only_reference_observed"
                or writer_view.get("asset_observation") != "observed"
                or not writer_owner._is_fresh_profile_a_writer_for_handoff(
                    captured["capacity_owner"], captured["purpose_roots"],
                    integration=integration,
                )):
            integration._cancel_staging_preadmission_attempt(attempt)
            return fail_before_or_after_write("writer_handoff_storage_observation_unavailable")

        def with_current_host(on_current):
            with self._publication_gate:
                if (self._closed
                        or self._generation_original_host_lifecycle is not captured["lifecycle"]):
                    return False
                with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                    if lifecycle is not captured["lifecycle"]:
                        return False
                    result = self._generation_original_host_evidence_current_locked(
                        lifecycle, captured["pairing_generation"],
                        on_current=on_current,
                    )
                    return result is True

        def current_handoff(*args):
            if args and (args[0] is not captured["envelope"]
                         or (len(args) > 1 and args[1] is not captured["remote"])):
                return False
            return with_current_host(lambda: integration._writer_handoff_matches_locked(
                captured["lifecycle"], attempt, marker, evidence, writer_owner,
                states={"in_progress", "write_admitted", "create_boundary_crossed"},
            ))

        def on_write_admitted(operation, reservation, write_admission):
            if (operation is not captured["operation"]
                    or reservation is not captured["reservation"]):
                return False
            return with_current_host(lambda: integration._record_writer_admission_locked(
                captured["lifecycle"], attempt, marker, evidence, writer_owner,
                operation, reservation, write_admission,
            ))

        def before_create():
            try:
                current_capacity = captured["capacity_owner"].readiness()
                current_project = captured["project_reference"].readiness()
            except Exception:
                return False
            if (current_capacity.get("status") != "characterization_only"
                    or current_capacity.get("root_set_contract") != "profile_a_four_writable_roots"
                    or current_capacity.get("scope_writer_lease") != "held"
                    or current_project.get("status") != "read_only_reference_observed"):
                return False
            return with_current_host(lambda: integration._cross_writer_create_boundary_locked(
                captured["lifecycle"], attempt, marker, evidence, writer_owner,
            ))

        if not current_handoff(captured["envelope"], captured["remote"]):
            integration._cancel_staging_preadmission_attempt(attempt)
            return fail_before_or_after_write("stale_host_binding")

        try:
            image = writer_owner._stage_remote_image_with_existing_reservation_for_characterization(
                captured["envelope"], captured["prepared"], captured["remote"],
                captured["descriptor"], admission_owner=captured["capacity_owner"],
                operation=captured["operation"], reservation=captured["reservation"],
                stream_provider=stream_provider, host_freshness=current_handoff,
                on_write_admitted=on_write_admitted, before_create=before_create,
                characterization=True, disposable_opt_in=True,
            )
        except Exception:
            state = captured["capacity_owner"]._reservation_terminal_state_for_characterization(
                captured["operation"], captured["reservation"],
            )
            uncertain = bool(writer_owner._uncertain or state in {"retained_uncertain", "completed"})
            if state == "cancelled":
                integration._cancel_staging_preadmission_attempt(attempt)
            elif not uncertain and state in {"reserved", "writing"}:
                cancelled = integration._cancel_staging_preadmission_attempt(attempt)
                terminal = captured["capacity_owner"]._reservation_terminal_state_for_characterization(
                    captured["operation"], captured["reservation"],
                )
                uncertain = terminal != "cancelled" or cancelled == "retained_uncertain"
            elif state is None:
                uncertain = bool(attempt.writer_create_boundary_crossed)
            # The writer's exact ledger terminal state is stronger evidence
            # than the earlier in-memory pre-CREATE_NEW boundary marker.
            return fail_before_or_after_write("protected_writer_stage_failed", uncertain=uncertain)

        try:
            # Reobserve after the native write; final publication remains a
            # count-only host observation under the exact current Claim gate.
            capacity_view = captured["capacity_owner"].readiness()
            project_view = captured["project_reference"].readiness()
            writer_view = writer_owner.readiness()
        except Exception:
            return fail_before_or_after_write(
                "writer_handoff_post_write_observation_unavailable",
                uncertain=True, image=image,
            )

        with self._publication_gate:
            if (self._closed
                    or self._generation_original_host_lifecycle is not captured["lifecycle"]):
                result = None
            else:
                with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                    if lifecycle is captured["lifecycle"]:
                        result = self._generation_original_host_evidence_current_locked(
                            lifecycle, captured["pairing_generation"],
                            on_current=lambda: integration._publish_single_image_writer_observation_locked(
                                lifecycle, attempt, marker, evidence, writer_owner,
                                image, capacity_view, project_view, writer_view,
                            ),
                        )
                    else:
                        result = None
        if type(result) is tuple and result[0] is not None:
            return result
        failure_reason = "host_or_writer_changed"
        if (type(result) is tuple and len(result) > 1
                and type(result[1]) is str and result[1]
                and len(result[1]) <= 96
                and result[1].replace("_", "").isalnum()):
            failure_reason = result[1]
        return fail_before_or_after_write(
            failure_reason, uncertain=True, image=image,
        )

    @staticmethod
    def _invalidate_uncertain_profile_a_capacity(capacity_owner):
        """Fence the existing ledger if reserve acknowledgment itself is uncertain."""
        try:
            with capacity_owner._lock:
                capacity_owner._invalidate()
        except Exception:
            pass

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
                        if integration_snapshot._profile_a:
                            result = self._generation_original_host_evidence_current_locked(
                                lifecycle, lifecycle._pairing_generation,
                                on_current=lambda: integration_snapshot.observe_result_for_characterization(
                                    lease, completion, worker_observation, current=True,
                                ),
                            )
                            if result is not False:
                                return result
                            self._retire_generation_original_host_lifecycle_locked(
                                "host_evidence_unavailable",
                            )
                        else:
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

                def publish_binding():
                    try:
                        return capacity_owner._bind_profile_a_lifecycle_for_characterization(
                            lifecycle, project_reference,
                        )
                    except ValueError:
                        return "storage_binding_unavailable"

                # The previous check is the final host snapshot after native
                # observations. Recheck while holding Job/Inbox locks through
                # the actual in-memory publication to close the claim race.
                publication = self._generation_original_host_evidence_current_locked(
                    lifecycle, pairing_generation, on_current=publish_binding,
                )
                if publication is False or publication == "host_evidence_unavailable":
                    self._retire_generation_original_host_lifecycle_locked(
                        "host_evidence_unavailable",
                    )
                    return "host_evidence_unavailable"
                return publication

    def bind_generation_profile_a_worker_storage_for_characterization(
            self, worker, purpose_roots, capacity_owner, project_reference):
        """Associate one supplied Worker with an already-bound Profile A owner.

        Native root and selected-Project readiness run outside the host
        publication/route/target/Job/Inbox/lifecycle locks. The final snapshot
        revalidates the exact live Job Claim and publishes only an in-memory
        Worker association. This never starts the Worker or invokes a writer.
        """
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_storage import WindowsProjectJsonReferenceCharacterization
        from ui.agent_generation_http_io_worker import HostOwnedHTTPIOWorker
        from ui.agent_generation_original_host_worker_storage import (
            OriginalHostWorkerStorageIntegration, _PROFILE_A_PURPOSES,
            _profile_a_references_match,
        )

        if (type(worker) is not HostOwnedHTTPIOWorker
                or type(capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization
                or type(project_reference) is not WindowsProjectJsonReferenceCharacterization
                or type(purpose_roots) is not dict
                or set(purpose_roots) != set(_PROFILE_A_PURPOSES)):
            return "binding_invalid"

        captured = {}
        with self._publication_gate:
            if self._closed:
                return "runtime_closed"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None:
                    return self._generation_original_host_lifecycle_reason or "lifecycle_unavailable"

                def capture_profile_a_binding():
                    with lifecycle._lock:
                        if not lifecycle._profile_a_job_claim_current_locked():
                            return "host_evidence_unavailable"
                        if not _profile_a_references_match(
                                lifecycle, purpose_roots, capacity_owner,
                                project_reference, lifecycle_locked=True):
                            return "storage_binding_mismatch"
                        captured.update({
                            "lifecycle": lifecycle,
                            "generation": lifecycle._generation,
                            "project": lifecycle._project_ref(),
                            "project_path": lifecycle._project_path,
                            "target_epoch": lifecycle._target_epoch,
                            "pairing_generation": lifecycle._pairing_generation,
                        })
                        return "captured"

                snapshot = self._generation_original_host_evidence_current_locked(
                    lifecycle, lifecycle._pairing_generation,
                    on_current=capture_profile_a_binding,
                )
                if snapshot is False or snapshot == "host_evidence_unavailable":
                    self._retire_generation_original_host_lifecycle_locked(
                        "host_evidence_unavailable",
                    )
                    return "host_evidence_unavailable"
                if snapshot != "captured":
                    return snapshot

        # These observations can inspect native ACLs, file identities and the
        # bounded root inventory. They must stay outside every host lock.
        try:
            capacity_view = capacity_owner.readiness()
            project_view = project_reference.readiness()
        except Exception:
            return "storage_observation_unavailable"
        if (capacity_view.get("status") != "characterization_only"
                or capacity_view.get("root_set_contract") != "profile_a_four_writable_roots"
                or capacity_view.get("scope_writer_lease") != "held"
                or project_view.get("status") != "read_only_reference_observed"):
            return "storage_observation_unavailable"

        with self._publication_gate:
            if self._closed:
                return "runtime_closed"
            with self._current_generation_original_host_lifecycle_locked() as lifecycle:
                if lifecycle is None or lifecycle is not captured["lifecycle"]:
                    return "stale_host_binding"

                def publish_worker_binding():
                    with lifecycle._lock:
                        if (lifecycle._generation != captured["generation"]
                                or lifecycle._project_ref() is not captured["project"]
                                or lifecycle._project_path != captured["project_path"]
                                or lifecycle._target_epoch != captured["target_epoch"]
                                or lifecycle._pairing_generation != captured["pairing_generation"]):
                            return "stale_host_binding"
                    if (len(self._retired_generation_worker_storage_integrations)
                            >= _MAX_RETIRED_GENERATION_WORKER_STORAGE):
                        return "retained_worker_storage_limit"
                    _, status = OriginalHostWorkerStorageIntegration._bind_profile_a_for_runtime(
                        lifecycle, self, worker, purpose_roots, capacity_owner,
                        project_reference,
                    )
                    return status

                result = self._generation_original_host_evidence_current_locked(
                    lifecycle, captured["pairing_generation"],
                    on_current=publish_worker_binding,
                )
                if result is False:
                    self._retire_generation_original_host_lifecycle_locked(
                        "host_evidence_unavailable",
                    )
                    self._generation_original_host_lifecycle_reason = "host_evidence_unavailable"
                    return "host_evidence_unavailable"
                return result

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
