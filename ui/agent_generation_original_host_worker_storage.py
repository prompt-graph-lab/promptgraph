"""Non-executing host ownership for a supplied Worker and protected roots.

This owner binds exact references, retains bounded diagnostic observations and
may reserve one pre-write staging estimate per request through the existing
Profile A capacity ledger. It never starts or performs Worker I/O, invokes a
Journal/storage/promotion writer, advances the Job Registry/Inbox, or grants
write or publication authority.
"""

from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass, field
import threading
import uuid
import weakref


_FACTORY = object()
_MAX_OBSERVATIONS = 16
_MAX_HISTORY_READS_PER_REQUEST = 16
_MAX_PREADMISSION_REQUESTS = 100
_MAX_WRITER_REQUEST_BYTES = 128 * 1024 * 1024
_MAX_WRITER_IMAGE_BYTES = 32 * 1024 * 1024
_MAX_WRITER_IMAGES = 16
_PURPOSES = (
    "private_journal", "temporary_containment", "retained_uncertain",
    "promoted_assets", "selected_project_json",
)
_PROFILE_A_PURPOSES = _PURPOSES[:-1]


def _profile_a_references_match(lifecycle, purpose_roots, capacity_owner,
                                project_reference, *, lifecycle_locked=False):
    """Check Profile A identities only; never perform native readiness I/O."""
    from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
    from core.generation_windows_protected_storage import (
        WindowsProjectJsonReferenceCharacterization, WindowsProtectedRootCharacterization,
    )
    from ui.project_agent_session_mailbox import _normalize_target_path

    if (type(capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization
            or capacity_owner._profile_a_root_set is not True
            or type(purpose_roots) is not dict
            or set(purpose_roots) != set(_PROFILE_A_PURPOSES)
            or type(capacity_owner._roots) is not dict
            or set(capacity_owner._roots) != set(_PROFILE_A_PURPOSES)
            or capacity_owner._closed is not False or capacity_owner._invalid is not False
            or capacity_owner._scope_lease is None
            or capacity_owner._scope_lease._state != "held"
            or type(project_reference) is not WindowsProjectJsonReferenceCharacterization
            or project_reference._closed is not False):
        return False
    if any(
        type(purpose_roots[purpose]) is not WindowsProtectedRootCharacterization
        or purpose_roots[purpose]._purpose != purpose
        or purpose_roots[purpose]._closed is not False
        or capacity_owner._roots[purpose] is not purpose_roots[purpose]
        for purpose in _PROFILE_A_PURPOSES
    ):
        return False
    if lifecycle is None:
        return False
    if lifecycle_locked:
        binding = lifecycle._profile_a_storage_binding
        project_path = lifecycle._project_path
        if (lifecycle._state != "bound_non_executing"
                or type(binding) is not tuple or len(binding) != 2
                or binding[0] is not capacity_owner
                or binding[1] is not project_reference):
            return False
    else:
        with lifecycle._lock:
            return _profile_a_references_match(
                lifecycle, purpose_roots, capacity_owner, project_reference,
                lifecycle_locked=True,
            )
    project = lifecycle._project_ref()
    if (project is None or type(project_path) is not str or not project_path
            or _normalize_target_path(str(project_reference._path))
            != _normalize_target_path(project_path)):
        return False
    # The 19C-B binding registered this exact lifecycle with the app-owned
    # ledger so its scope lease can observe late Worker uncertainty.
    with capacity_owner._lock:
        return (capacity_owner._closed is False and capacity_owner._invalid is False
                and any(previous is lifecycle
                        for previous in capacity_owner._host_lifecycle_refs))


@dataclass(frozen=True)
class GenerationWorkerOperationLease:
    """Private one-use correlation lease; not execution or storage authority."""

    lifecycle_generation: str = field(repr=False)
    nonce: str = field(repr=False)
    kind: str
    request_index: int
    correlation: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class GenerationWorkerStorageObservation:
    """Safe bounded status with no correlation IDs, paths, or result bodies."""

    status: str
    lifecycle_state: str
    worker_state: str
    worker_thread_alive: bool
    worker_in_flight: bool
    active_operations: int
    retained_uncertain_operations: int
    result_observations: int
    protected_binding: str
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerStoragePreAdmissionObservation:
    """Bounded capacity observation; never a writer or execution capability."""

    status: str
    purpose: str
    request_index: int
    byte_upper_bound: int
    entry_upper_bound: int
    write_authorized: bool = False
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerProtectedWriterObservation:
    """Safe status for a privately retained single-image staging observation."""

    status: str
    request_index: int
    verified_image_count: int
    capacity_accounted: bool
    write_authorized: bool = False
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerRemoteOutputWriterEvidence:
    """Exact remote-history evidence; never an actionable storage capability."""

    identity: str
    request_index: int
    descriptor_count: int
    request_byte_upper_bound: int
    request_entry_upper_bound: int
    history_identity: str = field(repr=False)
    remote_output_identity: str = field(repr=False)
    status: str = "remote_output_writer_evidence_observed_non_authoritative"
    write_authorized: bool = False
    writer_admission_issued: bool = False
    remote_metadata_only: bool = True
    image_bytes_verified: bool = False
    image_content_verified: bool = False
    writer_handoff_pending: bool = True
    max_request_bytes: int = _MAX_WRITER_REQUEST_BYTES
    max_image_bytes: int = _MAX_WRITER_IMAGE_BYTES
    max_images: int = _MAX_WRITER_IMAGES
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"
    _issuer: object = field(default=None, repr=False, compare=False)
    _attempt_nonce: str = field(default="", repr=False, compare=False)


@dataclass
class _StoragePreAdmissionAttempt:
    lease: object
    operation_id: str
    estimate: object
    state: str = "preparing"
    capacity_operation: object = None
    reservation: object = None
    observation: object = None
    cancel_requested: bool = False
    prepared: object = None
    accepted_prompt_id: str | None = None
    submission_completion: object = None
    history_lease: object = None
    history_completion: object = None
    history_json: bytes = b""
    remote_receipt: object = None
    evidence_state: str = "awaiting_submission"
    validation_marker: object = None
    evidence: object = None
    writer_handoff_state: str = "not_started"
    writer_handoff_marker: object = None
    writer_owner: object = None
    writer_admission: object = None
    writer_create_boundary_crossed: bool = False
    writer_create_attempt_count: int = 0
    writer_image_observation: object = None
    writer_image_observations: tuple = ()


def unavailable_observation(status="unavailable"):
    return GenerationWorkerStorageObservation(
        status=status,
        lifecycle_state="unavailable",
        worker_state="unavailable",
        worker_thread_alive=False,
        worker_in_flight=False,
        active_operations=0,
        retained_uncertain_operations=0,
        result_observations=0,
        protected_binding="unavailable",
    )


class OriginalHostWorkerStorageIntegration:
    """One exact lifecycle's Worker/root references and bounded pre-admission."""

    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    project_save_allowed = False
    authorship = "unverified"

    @classmethod
    def _bind_for_runtime(cls, lifecycle, runtime, worker, purpose_roots, capacity_owner):
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from ui.agent_generation_http_io_worker import HostOwnedHTTPIOWorker
        from ui.agent_generation_original_host_lifecycle import OriginalHostGenerationLifecycle
        from ui.project_agent_session_pump import ProjectAgentSessionRuntime

        if (type(lifecycle) is not OriginalHostGenerationLifecycle
                or type(runtime) is not ProjectAgentSessionRuntime
                or lifecycle._runtime_ref() is not runtime
                or lifecycle.readiness().get("lifecycle_state") != "bound_non_executing"
                or type(worker) is not HostOwnedHTTPIOWorker
                or type(capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization
                or type(purpose_roots) is not dict or set(purpose_roots) != set(_PURPOSES)):
            return None, "binding_invalid"
        # Reuse 19A's reference-only validator. It compares exact native owner
        # references and purposes, but intentionally performs no readiness/I/O.
        status = lifecycle.observe_protected_references_for_characterization(
            purpose_roots, capacity_owner,
        )
        if status != "matched_reference_only":
            return None, "storage_binding_mismatch"

        owner = cls(lifecycle, runtime, worker, purpose_roots, capacity_owner,
                    _factory=_FACTORY)
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._worker_storage_integration is not None):
                return None, "lifecycle_unavailable"
            # This claim and the Worker's operation admission share its state
            # lock. If an external fake operation wins first, the claim fails;
            # if the claim wins first, only an exact host-registered operation
            # can be admitted. Concurrent Lifecycles cannot share the Worker.
            if not worker._claim_original_host_for_characterization(
                owner._worker_owner_claim,
            ):
                return None, "worker_unavailable"
            lifecycle._worker_storage_integration = owner
        return owner, "bound_non_executing"

    @classmethod
    def _bind_profile_a_for_runtime(cls, lifecycle, runtime, worker, purpose_roots,
                                    capacity_owner, project_reference):
        """Claim a Worker for an already-bound Profile A lifecycle.

        The caller owns the final runtime/route/Job/Inbox host gate. This
        method performs only short in-memory identity checks; native readiness
        must have been observed before entering that gate.
        """
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_storage import WindowsProjectJsonReferenceCharacterization
        from ui.agent_generation_http_io_worker import HostOwnedHTTPIOWorker
        from ui.agent_generation_original_host_lifecycle import OriginalHostGenerationLifecycle
        from ui.project_agent_session_pump import ProjectAgentSessionRuntime

        if (type(lifecycle) is not OriginalHostGenerationLifecycle
                or type(runtime) is not ProjectAgentSessionRuntime
                or lifecycle._runtime_ref() is not runtime
                or type(worker) is not HostOwnedHTTPIOWorker
                or type(capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization
                or type(project_reference) is not WindowsProjectJsonReferenceCharacterization
                or type(purpose_roots) is not dict
                or set(purpose_roots) != set(_PROFILE_A_PURPOSES)):
            return None, "binding_invalid"

        owner = cls(
            lifecycle, runtime, worker, purpose_roots, capacity_owner,
            project_reference=project_reference, profile_a=True, _factory=_FACTORY,
        )
        # Lock order is Job Registry -> Inbox -> lifecycle -> capacity owner
        # -> Worker. Capacity close and a competing Worker claim are
        # linearized against this short publication.
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._worker_storage_integration is not None
                    or not lifecycle._profile_a_job_claim_current_locked()
                    or not _profile_a_references_match(
                        lifecycle, purpose_roots, capacity_owner, project_reference,
                        lifecycle_locked=True,
                    )):
                return None, "profile_a_binding_unavailable"
            with capacity_owner._lock:
                if (capacity_owner._closed is not False or capacity_owner._invalid is not False
                        or not any(previous is lifecycle
                                   for previous in capacity_owner._host_lifecycle_refs)):
                    return None, "storage_binding_mismatch"
                if not worker._claim_original_host_for_characterization(
                        owner._worker_owner_claim):
                    return None, "worker_unavailable"
                lifecycle._worker_storage_integration = owner
        return owner, "bound_non_executing"

    def __init__(self, lifecycle, runtime, worker, purpose_roots, capacity_owner, *,
                 project_reference=None, profile_a=False, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("original_host_binding_required")
        self._lifecycle_ref = weakref.ref(lifecycle)
        self._runtime_ref = weakref.ref(runtime)
        self._lifecycle_generation = lifecycle._generation
        self._worker = worker
        self._worker_owner_claim = object()
        self._purpose_roots = dict(purpose_roots)
        self._capacity_owner = capacity_owner
        self._profile_a = profile_a is True
        self._project_reference = project_reference if self._profile_a else None
        self._binding_label = (
            "matched_profile_a_reference_only" if self._profile_a
            else "matched_reference_only"
        )
        self._operation_id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._state = "bound_non_executing"
        self._reason = None
        self._active = None
        self._active_prepared = None
        self._uncertain_leases = {}
        self._issued = {}
        self._submitted = set()
        self._history_attempts = {}
        self._accepted_prompt_ids = {}
        # One staging pre-admission attempt per manifest request. The entries
        # privately retain only the exact host lease and the existing
        # capacity owner's opaque reservation; neither is returned as a
        # writer capability.
        self._storage_preadmission_attempts = {}
        self._profile_a_writer_owner = None
        self._observations = deque(maxlen=_MAX_OBSERVATIONS)
        self._close_call_active = False
        self._last_worker_state = "created"

    def correlation_for_request_for_characterization(self, request_index, *, kind, prompt_id=None):
        """Issue scalars for an exact manifest member; never perform the Worker."""
        lifecycle = self._lifecycle_ref()
        if (lifecycle is None or type(request_index) is not int
                or kind not in {"submission", "history"}):
            return None
        if not self._profile_a and not self._root_binding_matches():
            self.revoke("host_evidence_unavailable")
            return None
        # Match the 19A host order: lifecycle -> integration. Revocation never
        # acquires these locks in the opposite order.
        binding_invalid = False
        correlation = None
        with lifecycle._lock:
            capacity_guard = self._capacity_owner._lock if self._profile_a else nullcontext()
            with capacity_guard:
                if self._profile_a and (
                        not self._root_binding_matches()
                        or not self._lifecycle_profile_binding_matches_locked(lifecycle)):
                    binding_invalid = True
                elif (lifecycle._state != "bound_non_executing"
                      or lifecycle._generation != self._lifecycle_generation
                      or lifecycle._envelope is None):
                    return None
                else:
                    with self._lock:
                        correlation = self._issue_correlation_locked(
                            lifecycle, request_index, kind=kind, prompt_id=prompt_id,
                        )
        if binding_invalid:
            self.revoke("host_evidence_unavailable")
            return None
        return correlation

    def _issue_correlation_locked(self, lifecycle, request_index, *, kind, prompt_id):
        """Issue one correlation while lifecycle and integration locks are held."""
        from core.comfy_remote_output_receipts import valid_prompt_id
        from ui.agent_generation_http_io_worker import HTTPIOCorrelation

        if self._state != "bound_non_executing":
            return None
        envelope = lifecycle._envelope
        if not 0 <= request_index < len(envelope.manifest.requests):
            return None
        request = envelope.manifest.requests[request_index]
        if kind == "submission":
            if prompt_id is not None:
                return None
            attempt_id = 1
            key = (kind, request_index, attempt_id)
            if key in self._issued:
                return None
        else:
            if not valid_prompt_id(prompt_id):
                return None
            if self._accepted_prompt_ids.get(request_index) != prompt_id:
                return None
            key_prefix = (kind, request_index, prompt_id)
            attempt_id = self._history_attempts.get(key_prefix, 0) + 1
            if attempt_id > _MAX_HISTORY_READS_PER_REQUEST:
                return None
            key = (kind, request_index, prompt_id, attempt_id)
            if key in self._issued:
                return None
            self._history_attempts[key_prefix] = attempt_id
        correlation = HTTPIOCorrelation(
            operation_id=self._operation_id,
            job_id=envelope.job_id,
            claim_id=envelope.claim_id,
            manifest_identity=envelope.manifest.manifest_identity,
            session_identity=lifecycle._session_incarnation,
            process_identity=lifecycle._process_incarnation,
            request_id=request.request_id,
            request_index=request.request_index,
            illustration_id=request.illustration_id,
            run_index=request.run_index,
            workflow_identity=request.workflow_identity,
            attempt_id=attempt_id,
            prompt_id=prompt_id,
        )
        self._issued[key] = correlation
        return correlation

    def begin_operation_for_characterization(self, kind, prepared, prompt_id, correlation):
        """Pin one host operation before an external caller uses its Worker."""
        from core.comfy_prompt_request import is_owner_prepared_frozen_request
        from ui.agent_generation_http_io_worker import HTTPIOCorrelation

        if (kind not in {"submission", "history"}
                or type(correlation) is not HTTPIOCorrelation
                or not is_owner_prepared_frozen_request(prepared)):
            return None, "invalid_operation"
        lifecycle = self._lifecycle_ref()
        if lifecycle is None:
            return None, "lifecycle_unavailable"
        if not self._profile_a and not self._root_binding_matches():
            self.revoke("host_evidence_unavailable")
            return None, "storage_binding_mismatch"
        binding_invalid = False
        result = None
        with lifecycle._lock:
            capacity_guard = self._capacity_owner._lock if self._profile_a else nullcontext()
            with capacity_guard:
                if self._profile_a and (
                        not self._root_binding_matches()
                        or not self._lifecycle_profile_binding_matches_locked(lifecycle)):
                    binding_invalid = True
                elif (lifecycle._state != "bound_non_executing"
                      or lifecycle._generation != self._lifecycle_generation
                      or lifecycle._envelope is None):
                    return None, "stale_non_authoritative"
                else:
                    with self._lock:
                        result = self._begin_operation_locked(
                            kind, prepared, prompt_id, correlation, lifecycle,
                        )
        if binding_invalid:
            self.revoke("host_evidence_unavailable")
            return None, "stale_non_authoritative"
        return result

    def _begin_operation_locked(self, kind, prepared, prompt_id, correlation, lifecycle):
        """Install exact Worker admission while lifecycle/capacity are pinned."""
        from core.comfy_prompt_request import (
            _frozen_fields, prepare_frozen_prompt_request,
        )

        if self._state != "bound_non_executing" or self._active is not None:
            return None, "operation_unavailable"
        envelope = lifecycle._envelope
        index = correlation.request_index
        if (type(index) is not int or not 0 <= index < len(envelope.manifest.requests)):
            return None, "correlation_mismatch"
        request = envelope.manifest.requests[index]
        expected = (
            envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity,
            lifecycle._session_incarnation, lifecycle._process_incarnation,
            request.request_id, request.request_index, request.illustration_id,
            request.run_index, request.workflow_identity,
        )
        actual = (
            correlation.job_id, correlation.claim_id, correlation.manifest_identity,
            correlation.session_identity, correlation.process_identity,
            correlation.request_id, correlation.request_index, correlation.illustration_id,
            correlation.run_index, correlation.workflow_identity,
        )
        try:
            expected_prepared = prepare_frozen_prompt_request(
                envelope.manifest, request, client_id=prepared.client_id,
            )
        except Exception:
            return None, "request_mismatch"
        if (actual != expected
                or prepared.request_id != request.request_id
                or prepared.request_index != request.request_index
                or prepared.workflow_identity != request.workflow_identity
                or _frozen_fields(prepared) != _frozen_fields(expected_prepared)
                or correlation.operation_id != self._operation_id
                or self._issued.get(self._correlation_key(kind, correlation)) is not correlation
                or ((kind, index, correlation.attempt_id) in self._submitted
                    if kind == "submission" else False)
                or (kind == "submission" and (prompt_id is not None or correlation.prompt_id is not None))
                or (kind == "history" and (prompt_id is None or correlation.prompt_id != prompt_id))):
            return None, "correlation_mismatch"
        if self._profile_a:
            if any(attempt.evidence_state in {"validating", "history_observed"}
                   or (attempt.evidence_state == "evidence_published"
                       and attempt.writer_handoff_state != "staged_non_authoritative")
                   for attempt in self._storage_preadmission_attempts.values()):
                return None, "remote_output_evidence_in_progress"
            attempt = self._storage_preadmission_attempts.get(index)
            if attempt is not None and kind == "history":
                if (attempt.evidence_state != "submission_accepted"
                        or attempt.prepared is not prepared
                        or attempt.accepted_prompt_id != prompt_id):
                    return None, "remote_output_history_unavailable"
        if not self._worker._register_original_host_operation_for_characterization(
                self._worker_owner_claim, kind, correlation):
            return None, "worker_unavailable"
        if kind == "submission":
            self._submitted.add((kind, index, correlation.attempt_id))
        lease = GenerationWorkerOperationLease(
            lifecycle._generation, uuid.uuid4().hex, kind, index, correlation,
        )
        self._active = lease
        self._active_prepared = prepared
        if self._profile_a and kind == "history":
            attempt = self._storage_preadmission_attempts.get(index)
            if attempt is not None:
                # Retain the exact host-issued history lease before the Worker
                # runs; a copied completion or unrelated same-prompt read
                # cannot later be paired with the pre-admission.
                attempt.history_lease = lease
        return lease, "admitted_non_executing"

    def _begin_staging_preadmission_for_characterization(self, lifecycle, lease, estimate):
        """Reserve bounded staging capacity for one exact active Profile A lease."""
        from core.comfy_output_containment import ContainmentLimits
        from core.generation_storage_admission import CapacityEstimate

        if not self._profile_a:
            return None, "profile_a_required"
        if (type(estimate) is not CapacityEstimate
                or type(estimate.byte_upper_bound) is not int
                or type(estimate.entry_upper_bound) is not int
                or not 1 <= estimate.byte_upper_bound <= ContainmentLimits().aggregate_bytes
                or not 1 <= estimate.entry_upper_bound <= ContainmentLimits().images):
            return None, "invalid_capacity_estimate"
        attempt = None
        with lifecycle._lock:
            with self._capacity_owner._lock:
                with self._lock:
                    if (self._state != "bound_non_executing"
                            or lifecycle._worker_storage_integration is not self
                            or lifecycle._generation != self._lifecycle_generation
                            or not self._lifecycle_profile_binding_matches_locked(lifecycle)):
                        return None, "host_or_storage_unavailable"
                    if (type(lease) is not GenerationWorkerOperationLease
                            or self._active is not lease
                            or lease.lifecycle_generation != self._lifecycle_generation
                            or lease.kind != "submission"
                            or type(lease.request_index) is not int
                            or not 0 <= lease.request_index < lifecycle._request_count
                            or lease.correlation.request_index != lease.request_index
                            or self._issued.get(self._correlation_key(
                                lease.kind, lease.correlation)) is not lease.correlation):
                        return None, "operation_lease_mismatch"
                    if lease.request_index in self._storage_preadmission_attempts:
                        return None, "preadmission_already_attempted"
                    if len(self._storage_preadmission_attempts) >= min(
                            _MAX_PREADMISSION_REQUESTS, lifecycle._request_count):
                        return None, "preadmission_limit"
                    attempt = _StoragePreAdmissionAttempt(
                        lease=lease,
                        operation_id=f"worker-stage:{self._operation_id}:{lease.nonce}",
                        estimate=estimate,
                        prepared=self._active_prepared,
                    )
                    if (attempt.prepared is None
                            or attempt.prepared.request_index != lease.request_index):
                        return None, "prepared_request_unavailable"
                    self._storage_preadmission_attempts[lease.request_index] = attempt
        return attempt, "preparing"

    def _attach_staging_capacity_operation(self, attempt, capacity_operation):
        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or attempt.capacity_operation is not None):
                return False
            attempt.capacity_operation = capacity_operation
            return not attempt.cancel_requested and attempt.state == "preparing"

    def _attach_staging_reservation(self, attempt, reservation):
        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or attempt.reservation is not None):
                return False
            attempt.reservation = reservation
            if attempt.cancel_requested or attempt.state != "preparing":
                attempt.state = "cancellation_requested"
                return False
            attempt.state = "reserved"
            return True

    def _finish_staging_preadmission(self, attempt, state):
        with self._lock:
            if self._storage_preadmission_attempts.get(attempt.lease.request_index) is attempt:
                if attempt.state not in {"pre_admitted", "cancelled", "retained_uncertain"}:
                    attempt.state = state

    def _publish_staging_preadmission_locked(
            self, lifecycle, lease, attempt, capacity_view, project_view):
        """Publish one non-authoritative observation at the final host gate."""
        if (capacity_view.get("status") != "characterization_only"
                or capacity_view.get("root_set_contract") != "profile_a_four_writable_roots"
                or capacity_view.get("scope_writer_lease") != "held"
                or project_view.get("status") != "read_only_reference_observed"):
            return None, "storage_observation_unavailable"
        with lifecycle._lock:
            with self._capacity_owner._lock:
                with self._lock:
                    if (self._storage_preadmission_attempts.get(lease.request_index) is not attempt
                            or attempt.state != "reserved" or attempt.cancel_requested
                            or self._state != "bound_non_executing"
                            or self._active is not lease
                            or lifecycle._worker_storage_integration is not self
                            or lifecycle._generation != self._lifecycle_generation
                            or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                            or not self._capacity_owner._staging_reservation_is_live_for_characterization(
                                attempt.capacity_operation, attempt.reservation, attempt.estimate)):
                        attempt.cancel_requested = True
                        return None, "host_or_capacity_changed"
                    observation = GenerationWorkerStoragePreAdmissionObservation(
                        status="pre_admitted_non_authoritative",
                        purpose="temporary_containment",
                        request_index=lease.request_index,
                        byte_upper_bound=attempt.estimate.byte_upper_bound,
                        entry_upper_bound=attempt.estimate.entry_upper_bound,
                    )
                    attempt.observation = observation
                    attempt.state = "pre_admitted"
                    return observation, "pre_admitted_non_authoritative"

    def _cancel_staging_preadmission_attempt(self, attempt):
        """Release only an exact still-reserved token, outside the integration lock."""
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization

        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or attempt.state in {"cancelled", "retained_uncertain", "refused"}):
                return "preadmission_unavailable"
            if attempt.evidence_state == "uncertain":
                attempt.state = "retained_uncertain"
                return "retained_uncertain"
            attempt.cancel_requested = True
            if attempt.reservation is None or attempt.capacity_operation is None:
                if attempt.state == "preparing":
                    attempt.state = "cancellation_requested"
                    return "cancellation_requested"
                return "preadmission_unavailable"
            if attempt.state == "cancellation_in_progress":
                return "cancellation_requested"
            attempt.state = "cancellation_in_progress"
            capacity_operation, reservation = attempt.capacity_operation, attempt.reservation

        try:
            if type(self._capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization:
                raise ValueError("capacity_owner_unavailable")
            terminal_state = self._capacity_owner._reservation_terminal_state_for_characterization(
                capacity_operation, reservation,
            )
            if terminal_state == "cancelled":
                with self._lock:
                    if self._storage_preadmission_attempts.get(
                            attempt.lease.request_index) is attempt:
                        attempt.state = "cancelled"
                return "cancelled_before_write"
            if terminal_state != "reserved":
                raise ValueError("reservation_not_cancellable")
            self._capacity_owner.cancel_before_write_for_characterization(
                capacity_operation, reservation,
            )
        except Exception:
            with self._lock:
                if self._storage_preadmission_attempts.get(attempt.lease.request_index) is attempt:
                    attempt.state = "retained_uncertain"
            return "retained_uncertain"
        with self._lock:
            if self._storage_preadmission_attempts.get(attempt.lease.request_index) is attempt:
                attempt.state = "cancelled"
        return "cancelled_before_write"

    def cancel_staging_preadmission_for_characterization(self, observation):
        """Cancel only the exact returned observation; it never authorizes a write."""
        if type(observation) is not GenerationWorkerStoragePreAdmissionObservation:
            return "invalid_preadmission"
        with self._lock:
            attempt = self._storage_preadmission_attempts.get(observation.request_index)
            if (attempt is None or attempt.observation is not observation
                    or attempt.state != "pre_admitted"
                    or attempt.evidence_state in {"uncertain", "evidence_published"}):
                return "foreign_or_settled_preadmission"
            attempt.evidence_state = "cancelled"
            attempt.validation_marker = None
        return self._cancel_staging_preadmission_attempt(attempt)

    def _begin_remote_output_writer_evidence_validation_locked(self, lifecycle, observation):
        """Reserve one private validation pass for the exact observed request."""
        if not self._profile_a or type(observation) is not GenerationWorkerStoragePreAdmissionObservation:
            return None, "profile_a_required"
        with lifecycle._lock:
            with self._capacity_owner._lock:
                with self._lock:
                    attempt = self._storage_preadmission_attempts.get(observation.request_index)
                    if (lifecycle._worker_storage_integration is not self
                            or lifecycle._state != "bound_non_executing"
                            or lifecycle._generation != self._lifecycle_generation
                            or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                            or not self._root_binding_matches()
                            or attempt is None or attempt.observation is not observation
                            or attempt.state != "pre_admitted" or attempt.cancel_requested
                            or attempt.evidence_state != "history_observed"
                            or attempt.validation_marker is not None or attempt.evidence is not None
                            or self._active is not None
                            or not self._capacity_owner._staging_reservation_is_live_for_characterization(
                                attempt.capacity_operation, attempt.reservation, attempt.estimate)):
                        return None, "remote_output_evidence_unavailable"
                    from core.comfy_http_history import HistoryResult
                    from core.comfy_http_submission import SubmissionResult
                    from ui.agent_generation_http_io_worker import HTTPIOCompletion

                    prepared = attempt.prepared
                    submission = attempt.submission_completion
                    history = attempt.history_completion
                    history_lease = attempt.history_lease
                    if (type(submission) is not HTTPIOCompletion
                            or submission.kind != "submission"
                            or submission.correlation is not attempt.lease.correlation
                            or type(submission.outcome) is not SubmissionResult
                            or submission.outcome.status != "accepted"
                            or type(history) is not HTTPIOCompletion
                            or history.kind != "history"
                            or type(history.outcome) is not HistoryResult
                            or history.outcome.status != "ready"
                            or type(attempt.history_json) is not bytes
                            or not attempt.history_json
                            or history.outcome.history_json != attempt.history_json
                            or type(history_lease) is not GenerationWorkerOperationLease
                            or history_lease.kind != "history"
                            or history_lease.request_index != attempt.lease.request_index
                            or history_lease.lifecycle_generation != self._lifecycle_generation
                            or history.correlation is not history_lease.correlation
                            or history_lease.correlation.prompt_id != attempt.accepted_prompt_id
                            or not attempt.accepted_prompt_id
                            or prepared is None
                            or prepared.request_index != attempt.lease.request_index):
                        return None, "remote_output_evidence_incomplete"
                    marker = object()
                    attempt.validation_marker = marker
                    attempt.evidence_state = "validating"
                    return (attempt, marker, lifecycle._envelope, prepared,
                            attempt.accepted_prompt_id, submission, history_lease,
                            history, attempt.history_json), "validating"

    def _fail_remote_output_writer_evidence_validation(
            self, attempt, marker, evidence_state, *, cancel_reservation):
        """Finish a failed validation without releasing uncertain accounting."""
        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is attempt
                    and attempt.validation_marker is marker
                    and attempt.evidence_state == "validating"):
                attempt.validation_marker = None
                attempt.evidence_state = evidence_state
        if evidence_state == "uncertain":
            return "retained_uncertain"
        if cancel_reservation:
            return self._cancel_staging_preadmission_attempt(attempt)
        return "refused"

    def _publish_remote_output_writer_evidence_locked(
            self, lifecycle, attempt, marker, host_snapshot, remote, evidence,
            capacity_view, project_view):
        """Publish only validated metadata while host and native references are current."""
        from core.comfy_remote_output_receipts import RemoteOutputReceipt

        if (capacity_view.get("status") != "characterization_only"
                or capacity_view.get("root_set_contract") != "profile_a_four_writable_roots"
                or capacity_view.get("scope_writer_lease") != "held"
                or project_view.get("status") != "read_only_reference_observed"):
            return None, "storage_observation_unavailable"
        with lifecycle._lock:
            with self._capacity_owner._lock:
                with self._lock:
                    if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                            or attempt.state != "pre_admitted" or attempt.cancel_requested
                            or attempt.evidence_state != "validating"
                            or attempt.validation_marker is not marker
                            or self._state != "bound_non_executing"
                            or self._active is not None
                            or lifecycle._worker_storage_integration is not self
                            or lifecycle._state != "bound_non_executing"
                            or lifecycle._generation != host_snapshot["generation"]
                            or lifecycle._project_ref() is not host_snapshot["project"]
                            or lifecycle._project_path != host_snapshot["project_path"]
                            or lifecycle._target_epoch != host_snapshot["target_epoch"]
                            or lifecycle._activation_id != host_snapshot["activation_id"]
                            or lifecycle._pairing_generation != host_snapshot["pairing_generation"]
                            or lifecycle._envelope is not host_snapshot["envelope"]
                            or lifecycle._job is not host_snapshot["job"]
                            or lifecycle._job_id != host_snapshot["job_id"]
                            or lifecycle._claim_id != host_snapshot["claim_id"]
                            or lifecycle._manifest_identity != host_snapshot["manifest_identity"]
                            or not lifecycle._profile_a_job_claim_current_locked()
                            or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                            or not self._root_binding_matches()
                            or not self._capacity_owner._staging_reservation_is_live_for_characterization(
                                attempt.capacity_operation, attempt.reservation, attempt.estimate)):
                        return None, "host_or_capacity_changed"
                    if (type(remote) is not RemoteOutputReceipt
                            or remote.execution_succeeded is not True
                            or remote.job_id != host_snapshot["job_id"]
                            or remote.claim_id != host_snapshot["claim_id"]
                            or remote.manifest_identity != host_snapshot["manifest_identity"]
                            or remote.request_index != attempt.lease.request_index
                            or remote.request_id != attempt.prepared.request_id
                            or remote.workflow_identity != attempt.prepared.workflow_identity
                            or remote.prompt_id != attempt.accepted_prompt_id
                            or remote._validated_history_json != attempt.history_json
                            or evidence._issuer is not self
                            or evidence._attempt_nonce != attempt.lease.nonce
                            or evidence.request_index != attempt.lease.request_index
                            or evidence.request_byte_upper_bound != attempt.estimate.byte_upper_bound
                            or evidence.request_entry_upper_bound != attempt.estimate.entry_upper_bound
                            or evidence.descriptor_count != len(remote.images)):
                        return None, "remote_output_evidence_changed"

                    def commit():
                        attempt.remote_receipt = remote
                        attempt.evidence = evidence
                        attempt.evidence_state = "evidence_published"
                        attempt.validation_marker = None
                        return evidence, evidence.status

                    result = self._worker._run_if_issued_completion_for_prepared_request_for_characterization(
                        attempt.history_completion, attempt.prepared,
                        self._worker_owner_claim, commit,
                    )
                    if result is None:
                        attempt.evidence_state = "uncertain"
                        attempt.validation_marker = None
                        return None, "worker_completion_changed"
                    return result

    def _begin_single_image_writer_handoff_locked(
            self, lifecycle, evidence, writer_owner, *, allow_batch=False):
        """Claim one exact 19E-A evidence/reservation handoff before native work."""
        from core import generation_windows_protected_assets as assets

        if (not self._profile_a
                or type(evidence) is not GenerationWorkerRemoteOutputWriterEvidence
                or type(writer_owner) is not assets.WindowsProtectedAssetsCharacterization):
            return None, "writer_handoff_owner_invalid"
        with lifecycle._lock:
            with self._capacity_owner._lock:
                with self._lock:
                    attempt = self._storage_preadmission_attempts.get(evidence.request_index)
                    if (lifecycle._worker_storage_integration is not self
                            or lifecycle._state != "bound_non_executing"
                            or lifecycle._generation != self._lifecycle_generation
                            or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                            or not self._root_binding_matches()
                            or self._state != "bound_non_executing"
                            or attempt is None or attempt.state != "pre_admitted"
                            or attempt.evidence_state != "evidence_published"
                            or attempt.evidence is not evidence
                            or evidence._issuer is not self
                            or evidence._attempt_nonce != attempt.lease.nonce
                            or attempt.remote_receipt is None
                            or attempt.writer_handoff_state != "not_started"
                            or attempt.writer_handoff_marker is not None
                            or attempt.writer_owner is not None
                            or attempt.writer_image_observation is not None
                            or attempt.writer_image_observations
                            or self._active is not None):
                        return None, "writer_handoff_evidence_unavailable"
                    if (self._profile_a_writer_owner is not None
                            and self._profile_a_writer_owner is not writer_owner):
                        return None, "writer_handoff_owner_mismatch"
                    if not writer_owner._is_fresh_profile_a_writer_for_handoff(
                            self._capacity_owner, self._purpose_roots, integration=self):
                        return None, "writer_handoff_root_mismatch"
                    self._profile_a_writer_owner = writer_owner
                    expected_count = evidence.descriptor_count
                    valid_count = ((2 <= expected_count <= _MAX_WRITER_IMAGES) if allow_batch
                                   else expected_count == 1)
                    if (not valid_count
                            or type(attempt.remote_receipt.images) is not tuple
                            or len(attempt.remote_receipt.images) != expected_count
                            or evidence.descriptor_count != len(attempt.remote_receipt.images)):
                        attempt.writer_handoff_state = "refused"
                        return (attempt, None, lifecycle._envelope, attempt.prepared,
                                attempt.remote_receipt, attempt.capacity_operation,
                                attempt.reservation), (
                                    "multi_image_output_required" if allow_batch
                                    else "single_image_output_required"
                                )
                    upper_bound = min(_MAX_WRITER_IMAGE_BYTES * expected_count,
                                      _MAX_WRITER_REQUEST_BYTES)
                    if not self._capacity_owner._staging_reservation_covers_for_characterization(
                            attempt.capacity_operation, attempt.reservation,
                            "temporary_containment", upper_bound, expected_count):
                        return None, "writer_handoff_reservation_unavailable"
                    descriptors = tuple(attempt.remote_receipt.images)
                    if len({item.identity for item in descriptors}) != len(descriptors):
                        attempt.writer_handoff_state = "refused"
                        return (attempt, None, lifecycle._envelope, attempt.prepared,
                                attempt.remote_receipt, attempt.capacity_operation,
                                attempt.reservation), "writer_handoff_descriptor_ambiguous"
                    marker = object()
                    attempt.writer_handoff_state = "in_progress"
                    attempt.writer_handoff_marker = marker
                    attempt.writer_owner = writer_owner
                    return (attempt, marker, lifecycle._envelope, attempt.prepared,
                            attempt.remote_receipt, descriptors,
                            attempt.capacity_operation, attempt.reservation), "handoff_claimed"

    def _writer_handoff_matches_locked(
            self, lifecycle, attempt, marker, evidence, writer_owner, *, states):
        """Short identity/state check; caller holds the host and publication gates."""
        try:
            with lifecycle._lock:
                with self._capacity_owner._lock:
                    with self._lock:
                        return bool(
                            lifecycle._worker_storage_integration is self
                            and lifecycle._state == "bound_non_executing"
                            and lifecycle._generation == self._lifecycle_generation
                            and self._lifecycle_profile_binding_matches_locked(lifecycle)
                            and self._root_binding_matches()
                            and self._state == "bound_non_executing"
                            and self._storage_preadmission_attempts.get(
                                attempt.lease.request_index) is attempt
                            and attempt.state == "pre_admitted"
                            and attempt.evidence_state == "evidence_published"
                            and attempt.evidence is evidence
                            and evidence._issuer is self
                            and evidence._attempt_nonce == attempt.lease.nonce
                            and attempt.remote_receipt is not None
                            and attempt.writer_handoff_marker is marker
                            and attempt.writer_owner is writer_owner
                            and attempt.writer_handoff_state in states
                            and not attempt.cancel_requested
                        )
        except Exception:
            return False

    def _record_writer_admission_locked(
            self, lifecycle, attempt, marker, evidence, writer_owner,
            operation, reservation, write_admission):
        if (not self._writer_handoff_matches_locked(
                lifecycle, attempt, marker, evidence, writer_owner,
                states={"in_progress"})
                or operation is not attempt.capacity_operation
                or reservation is not attempt.reservation
                or write_admission is None):
            return False
        with self._lock:
            if (attempt.writer_handoff_marker is not marker
                    or attempt.writer_handoff_state != "in_progress"
                    or attempt.writer_admission is not None):
                return False
            attempt.writer_admission = write_admission
            attempt.writer_handoff_state = "write_admitted"
            return True

    def _cross_writer_create_boundary_locked(
            self, lifecycle, attempt, marker, evidence, writer_owner):
        if not self._writer_handoff_matches_locked(
                lifecycle, attempt, marker, evidence, writer_owner,
                states={"write_admitted", "create_boundary_crossed"}):
            return False
        if not self._capacity_owner._staging_write_is_live_before_create_for_characterization(
                attempt.capacity_operation, attempt.reservation, attempt.writer_admission):
            return False
        with self._lock:
            expected_count = evidence.descriptor_count
            batch = expected_count > 1
            if (attempt.writer_handoff_marker is not marker
                    or (attempt.writer_handoff_state == "write_admitted"
                        and attempt.writer_create_attempt_count != 0)
                    or (attempt.writer_handoff_state == "create_boundary_crossed"
                        and (not batch or attempt.writer_create_attempt_count >= expected_count))
                    or attempt.writer_handoff_state not in {"write_admitted", "create_boundary_crossed"}):
                return False
            # This short in-memory transition is the one-shot authorization
            # boundary. Native CREATE_NEW follows after all host locks release.
            attempt.writer_create_boundary_crossed = True
            attempt.writer_create_attempt_count += 1
            attempt.writer_handoff_state = "create_boundary_crossed"
            return True

    def _publish_single_image_writer_observation_locked(
            self, lifecycle, attempt, marker, evidence, writer_owner, image,
            capacity_view, project_view, writer_view):
        """Publish a count-only result after exact native/accounting observation."""
        if (capacity_view.get("status") != "characterization_only"
                or capacity_view.get("root_set_contract") != "profile_a_four_writable_roots"
                or capacity_view.get("scope_writer_lease") != "held"
                or project_view.get("status") != "read_only_reference_observed"
                or writer_view.get("asset_observation") != "observed"):
            return None, "writer_handoff_storage_observation_unavailable"
        from core.generation_windows_protected_assets import VerifiedProtectedImageObservation

        if (type(image) is not VerifiedProtectedImageObservation
                or image.job_id != lifecycle._job_id
                or image.claim_id != lifecycle._claim_id
                or image.manifest_identity != lifecycle._manifest_identity
                or image.request_id != attempt.prepared.request_id
                or image.request_index != attempt.lease.request_index
                or image.workflow_identity != attempt.prepared.workflow_identity
                or image.prompt_id != attempt.accepted_prompt_id
                or image.remote_receipt_identity != attempt.remote_receipt.identity
                or image.descriptor_identity != attempt.remote_receipt.images[0].identity):
            return None, "writer_handoff_image_mismatch"
        if not self._capacity_owner._asset_stream_write_completed_for_characterization(
                attempt.capacity_operation, attempt.writer_admission, writer_owner,
                (image.request_id, image.descriptor_identity), image):
            return None, "writer_handoff_accounting_unavailable"
        if not self._writer_handoff_matches_locked(
                lifecycle, attempt, marker, evidence, writer_owner,
                states={"create_boundary_crossed"}):
            return None, "host_or_writer_changed"
        with self._lock:
            if (attempt.writer_image_observation is not None
                    or attempt.writer_handoff_state != "create_boundary_crossed"
                    or not attempt.writer_create_boundary_crossed):
                return None, "writer_handoff_already_settled"
            attempt.writer_image_observation = image
            attempt.writer_handoff_state = "staged_non_authoritative"
            return GenerationWorkerProtectedWriterObservation(
                status="protected_image_staged_non_authoritative",
                request_index=attempt.lease.request_index,
                verified_image_count=1,
                capacity_accounted=True,
            ), "protected_image_staged_non_authoritative"

    def _publish_multi_image_writer_observation_locked(
            self, lifecycle, attempt, marker, evidence, writer_owner, observations,
            capacity_view, project_view, writer_view):
        """Publish one count-only result after exact aggregate batch accounting."""
        if (capacity_view.get("status") != "characterization_only"
                or capacity_view.get("root_set_contract") != "profile_a_four_writable_roots"
                or capacity_view.get("scope_writer_lease") != "held"
                or project_view.get("status") != "read_only_reference_observed"
                or writer_view.get("asset_observation") != "observed"):
            return None, "writer_handoff_storage_observation_unavailable"
        from core.generation_windows_protected_assets import VerifiedProtectedImageObservation

        descriptors = tuple(attempt.remote_receipt.images)
        if (type(observations) is not tuple or not 2 <= len(observations) <= _MAX_WRITER_IMAGES
                or len(observations) != evidence.descriptor_count
                or len(descriptors) != len(observations)
                or len({item.identity for item in descriptors}) != len(descriptors)):
            return None, "writer_handoff_batch_incomplete"
        for descriptor, image in zip(descriptors, observations):
            if (type(image) is not VerifiedProtectedImageObservation
                    or image.job_id != lifecycle._job_id
                    or image.claim_id != lifecycle._claim_id
                    or image.manifest_identity != lifecycle._manifest_identity
                    or image.request_id != attempt.prepared.request_id
                    or image.request_index != attempt.lease.request_index
                    or image.workflow_identity != attempt.prepared.workflow_identity
                    or image.prompt_id != attempt.accepted_prompt_id
                    or image.remote_receipt_identity != attempt.remote_receipt.identity
                    or image.descriptor_identity != descriptor.identity):
                return None, "writer_handoff_image_mismatch"
        if not self._capacity_owner._asset_stream_image_batch_write_completed_for_characterization(
                attempt.capacity_operation, attempt.writer_admission, writer_owner, observations):
            return None, "writer_handoff_accounting_unavailable"
        if not self._writer_handoff_matches_locked(
                lifecycle, attempt, marker, evidence, writer_owner,
                states={"create_boundary_crossed"}):
            return None, "host_or_writer_changed"
        with self._lock:
            if (attempt.writer_image_observation is not None
                    or attempt.writer_image_observations
                    or attempt.writer_handoff_state != "create_boundary_crossed"
                    or not attempt.writer_create_boundary_crossed
                    or attempt.writer_create_attempt_count != len(observations)):
                return None, "writer_handoff_already_settled"
            attempt.writer_image_observations = observations
            attempt.writer_handoff_state = "staged_non_authoritative"
            return GenerationWorkerProtectedWriterObservation(
                status="protected_image_batch_staged_non_authoritative",
                request_index=attempt.lease.request_index,
                verified_image_count=len(observations),
                capacity_accounted=True,
            ), "protected_image_batch_staged_non_authoritative"

    def _fail_single_image_writer_handoff(self, attempt, marker, *, uncertain):
        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or attempt.writer_handoff_marker is not marker):
                return "writer_handoff_stale"
            if attempt.writer_handoff_state == "staged_non_authoritative":
                return ("protected_image_batch_staged_non_authoritative"
                        if attempt.writer_image_observations
                        else "protected_image_staged_non_authoritative")
            attempt.writer_handoff_state = "retained_uncertain" if uncertain else "refused"
            if uncertain:
                attempt.evidence_state = "uncertain"
            return attempt.writer_handoff_state

    def _settle_cancelled_single_image_writer_handoff(self, attempt, marker, writer_owner):
        """Publish only a ledger-confirmed pre-CREATE_NEW cancellation locally."""
        if (self._capacity_owner._reservation_terminal_state_for_characterization(
                attempt.capacity_operation, attempt.reservation) != "cancelled"
                or writer_owner._uncertain):
            return False
        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or attempt.writer_handoff_marker is not marker
                    or attempt.writer_owner is not writer_owner):
                return False
            attempt.state = "cancelled"
            attempt.evidence_state = "cancelled"
            attempt.cancel_requested = True
            attempt.writer_handoff_state = "refused"
            return True

    def _root_binding_matches(self):
        """Check exact owner references only; never touch the filesystem."""
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_storage import WindowsProtectedRootCharacterization

        roots = self._purpose_roots
        capacity = self._capacity_owner
        try:
            if type(capacity) is not WindowsProtectedStorageAdmissionCharacterization:
                return False
            purposes = _PROFILE_A_PURPOSES if self._profile_a else _PURPOSES
            capacity_guard = capacity._lock if self._profile_a else nullcontext()
            with capacity_guard:
                owned_roots = capacity._roots
                if (capacity._closed is not False or capacity._invalid is not False
                        or type(roots) is not dict or set(roots) != set(purposes)
                        or type(owned_roots) is not dict or set(owned_roots) != set(purposes)):
                    return False
                if self._profile_a and (
                        capacity._profile_a_root_set is not True
                        or capacity._scope_lease is None
                        or capacity._scope_lease._state != "held"
                        or self._project_reference is None
                        or self._project_reference._closed is not False):
                    return False
                return all(
                    type(roots[purpose]) is WindowsProtectedRootCharacterization
                    and roots[purpose]._purpose == purpose
                    and roots[purpose]._closed is False
                    and owned_roots[purpose] is roots[purpose]
                    for purpose in purposes
                )
        except Exception:
            return False

    def _lifecycle_profile_binding_matches_locked(self, lifecycle):
        """Check the current lifecycle's Profile A refs while its lock is held."""
        if not self._profile_a:
            return True
        try:
            return _profile_a_references_match(
                lifecycle, self._purpose_roots, self._capacity_owner,
                self._project_reference, lifecycle_locked=True,
            )
        except Exception:
            return False

    @staticmethod
    def _correlation_key(kind, correlation):
        if kind == "submission":
            return kind, correlation.request_index, correlation.attempt_id
        return kind, correlation.request_index, correlation.prompt_id, correlation.attempt_id

    def observe_result_for_characterization(self, lease, completion, worker_observation, *, current):
        """Classify one completion only; never sends a Job/Inbox event."""
        from core.comfy_http_history import HistoryResult
        from core.comfy_http_submission import SubmissionResult
        from ui.agent_generation_http_io_worker import HTTPIOCompletion, HTTPIOWorkerObservation

        if type(worker_observation) is not HTTPIOWorkerObservation:
            return "invalid_observation"
        if self._profile_a:
            lifecycle = self._lifecycle_ref()
            binding_current = lifecycle is not None
            if binding_current:
                with lifecycle._lock:
                    with self._capacity_owner._lock:
                        binding_current = (
                            self._root_binding_matches()
                            and self._lifecycle_profile_binding_matches_locked(lifecycle)
                        )
            if not binding_current:
                # A completion after Profile A evidence was closed, replaced or
                # detached cannot settle the retained Worker lease.
                self.revoke("host_evidence_unavailable")
                return "stale_non_authoritative"
        with self._lock:
            prepared_for_lease = (self._active_prepared
                                  if self._active is lease else None)
        if self._profile_a:
            worker_issued = self._worker._is_issued_completion_for_prepared_request_for_characterization(
                completion, prepared_for_lease,
            )
        else:
            worker_issued = self._worker._is_issued_completion_for_characterization(completion)
        accepted_prompt_id = None
        if (worker_issued and type(completion) is HTTPIOCompletion
                and completion.kind == "submission"
                and type(completion.outcome) is SubmissionResult
                and completion.outcome.status == "accepted"):
            from core.comfy_remote_output_receipts import decode_remote_json, valid_prompt_id
            try:
                response = decode_remote_json(completion.outcome.response_json)
                candidate = response.get("prompt_id") if type(response) is dict else None
                if valid_prompt_id(candidate):
                    accepted_prompt_id = candidate
            except Exception:
                pass
        with self._lock:
            self._last_worker_state = worker_observation.state
            if (type(lease) is not GenerationWorkerOperationLease
                    or self._active is not lease):
                status = "duplicate_non_authoritative" if self._active is None else "foreign_non_authoritative"
                self._observations.append((status, None, None, worker_observation.state))
                return status
            if (type(completion) is not HTTPIOCompletion
                    or completion.kind != lease.kind
                    or completion.correlation is not lease.correlation
                    or not worker_issued):
                self._observations.append(("foreign_non_authoritative", lease.kind,
                                           lease.request_index, worker_observation.state))
                return "foreign_non_authoritative"
            result = completion.outcome
            valid_result = (
                lease.kind == "submission" and type(result) is SubmissionResult
                and result.status in {"accepted", "rejected_before_submission", "unknown"}
            ) or (
                lease.kind == "history" and type(result) is HistoryResult
                and result.status in {"ready", "pending", "timeout", "unknown"}
            )
            if not valid_result:
                self._observations.append(("invalid_non_authoritative", lease.kind,
                                           lease.request_index, worker_observation.state))
                return "invalid_non_authoritative"

            outcome = result.status
            uncertain = (
                current is not True
                or outcome in {"unknown", "timeout"}
                or worker_observation.in_flight
                or worker_observation.state in {"closing", "close_pending", "uncertain"}
            )
            if current is not True or self._state != "bound_non_executing":
                status = "stale_non_authoritative"
            else:
                status = "observed_non_authoritative"
            self._observations.append((status, lease.kind, lease.request_index,
                                       worker_observation.state))
            if uncertain:
                self._uncertain_leases[lease.nonce] = lease
                if self._profile_a:
                    attempt = self._storage_preadmission_attempts.get(lease.request_index)
                    if attempt is not None and attempt.lease is lease:
                        attempt.evidence_state = "uncertain"
                if self._state == "bound_non_executing":
                    self._state = "uncertain"
                    self._reason = ("host_evidence_unavailable" if current is not True
                                    else "worker_outcome_uncertain")
                return "uncertain_non_authoritative" if current is True else status

            if lease.kind == "submission" and outcome == "accepted":
                if accepted_prompt_id is None:
                    self._uncertain_leases[lease.nonce] = lease
                    self._state = "uncertain"
                    self._reason = "worker_result_unverifiable"
                    return "uncertain_non_authoritative"
                if accepted_prompt_id in self._accepted_prompt_ids.values():
                    self._uncertain_leases[lease.nonce] = lease
                    if self._profile_a:
                        attempt = self._storage_preadmission_attempts.get(lease.request_index)
                        if attempt is not None and attempt.lease is lease:
                            attempt.evidence_state = "uncertain"
                    self._state = "uncertain"
                    self._reason = "worker_prompt_conflict"
                    return "uncertain_non_authoritative"
                self._accepted_prompt_ids[lease.request_index] = accepted_prompt_id
                if self._profile_a:
                    attempt = self._storage_preadmission_attempts.get(lease.request_index)
                    if attempt is not None:
                        if (attempt.lease is not lease or attempt.state != "pre_admitted"
                                or attempt.evidence_state != "awaiting_submission"
                                or attempt.prepared is not prepared_for_lease):
                            self._uncertain_leases[lease.nonce] = lease
                            attempt.evidence_state = "uncertain"
                            self._state = "uncertain"
                            self._reason = "worker_result_unverifiable"
                            return "uncertain_non_authoritative"
                        attempt.accepted_prompt_id = accepted_prompt_id
                        attempt.submission_completion = completion
                        attempt.evidence_state = "submission_accepted"

            if self._profile_a:
                attempt = self._storage_preadmission_attempts.get(lease.request_index)
                expected_attempt_lease = (
                    attempt.lease if lease.kind == "submission" else
                    attempt.history_lease if lease.kind == "history" else None
                ) if attempt is not None else None
                if attempt is not None and expected_attempt_lease is lease:
                    if lease.kind == "submission" and outcome == "rejected_before_submission":
                        attempt.evidence_state = "submission_rejected"
                    elif lease.kind == "history":
                        if (attempt.evidence_state != "submission_accepted"
                                or attempt.prepared is not prepared_for_lease
                                or attempt.accepted_prompt_id != lease.correlation.prompt_id
                                or self._issued.get(self._correlation_key(
                                    lease.kind, lease.correlation)) is not lease.correlation):
                            self._uncertain_leases[lease.nonce] = lease
                            attempt.evidence_state = "uncertain"
                            self._state = "uncertain"
                            self._reason = "worker_result_unverifiable"
                            return "uncertain_non_authoritative"
                        if outcome == "ready":
                            attempt.history_completion = completion
                            attempt.history_json = result.history_json
                            attempt.evidence_state = "history_observed"

            self._active = None
            self._active_prepared = None
            return status

    def revoke(self, reason):
        """Fence new work immediately without joining or closing root owners."""
        if reason not in {"target_replaced", "route_replaced", "pairing_replaced",
                          "job_claim_replaced", "host_evidence_unavailable", "session_closed"}:
            reason = "host_evidence_unavailable"
        preadmissions_to_cancel = []
        with self._lock:
            if self._state == "closed":
                worker = None
            else:
                if self._state == "bound_non_executing":
                    self._state = "revocation_requested"
                self._reason = self._reason or reason
                if self._active is not None:
                    # A host revocation cannot prove whether the caller crossed
                    # the Worker's admission boundary. Retain that lease and
                    # its roots as uncertain evidence.
                    self._uncertain_leases[self._active.nonce] = self._active
                    self._active = None
                    self._state = "uncertain"
                worker = self._worker
            # A pre-admission has never produced a write token. It is safe to
            # release only its exact still-reserved capacity token. If native
            # owner close/invalidation wins, that owner retains the estimate
            # as uncertain and the cancellation below remains fail-closed.
            for attempt in self._storage_preadmission_attempts.values():
                if attempt.state in {"preparing", "reserved", "pre_admitted"}:
                    attempt.cancel_requested = True
                    if attempt.evidence_state != "uncertain":
                        attempt.evidence_state = "revoked"
                        attempt.validation_marker = None
                    if attempt.reservation is not None and attempt.capacity_operation is not None:
                        attempt.state = "cancellation_requested"
                        preadmissions_to_cancel.append(attempt)
                    else:
                        attempt.state = "cancellation_requested"
        # This is a nonjoining Worker state transition. The bounded join and
        # terminal observation happen only from an explicit host call after
        # runtime/lifecycle/registry/job/inbox locks have been released.
        if worker is not None:
            worker_view = worker.request_close_for_characterization()
            with self._lock:
                if self._state == "revocation_requested":
                    self._state = "close_pending" if worker_view.thread_alive else "closed"
        for attempt in preadmissions_to_cancel:
            # The reservation cancellation is in-memory only; no readiness,
            # inventory, filesystem or Worker callback runs under this lock.
            self._cancel_staging_preadmission_attempt(attempt)
        return self._safe_state()

    def finish_close_for_characterization(self):
        """Use the Worker's bounded join outside all host owner locks."""
        should_return = False
        with self._lock:
            if self._close_call_active:
                should_return = True
                worker = None
            elif self._state == "bound_non_executing":
                should_return = True
                worker = None
            else:
                self._close_call_active = True
                worker = self._worker
        if should_return:
            return self._safe_state()
        try:
            observation = worker.close_for_characterization()
        except Exception:
            observation = None
        finally:
            with self._lock:
                self._close_call_active = False
                if observation is None:
                    self._state = "uncertain"
                    self._reason = "worker_close_uncertain"
                else:
                    self._last_worker_state = observation.state
                    if observation.state == "close_pending":
                        self._state = "close_pending"
                    elif observation.state in {"closed", "uncertain_stopped", "start_failed"}:
                        if self._uncertain_leases or self._active is not None or observation.uncertain_submissions:
                            self._state = "uncertain"
                            self._reason = self._reason or "worker_close_uncertain"
                        else:
                            self._state = "closed"
                    elif observation.state == "uncertain":
                        self._state = "uncertain"
                        self._reason = self._reason or "worker_close_uncertain"
                    else:
                        self._state = "close_pending"
        return self._safe_state()

    def worker_observation(self):
        return self._worker.observation_for_characterization()

    def _safe_state(self):
        try:
            worker = self._worker.observation_for_characterization()
        except Exception:
            worker = None
        with self._lock:
            state = self._state
            self._last_worker_state = worker.state if worker is not None else "unavailable"
            return GenerationWorkerStorageObservation(
                status=state,
                lifecycle_state=state,
                worker_state=self._last_worker_state,
                worker_thread_alive=worker.thread_alive if worker is not None else False,
                worker_in_flight=worker.in_flight if worker is not None else False,
                active_operations=int(self._active is not None),
                retained_uncertain_operations=len(self._uncertain_leases),
                result_observations=len(self._observations),
                protected_binding=self._binding_label,
            )

    def readiness(self):
        if not self._root_binding_matches():
            return self.revoke("host_evidence_unavailable")
        if self._profile_a:
            lifecycle = self._lifecycle_ref()
            if lifecycle is None:
                return self.revoke("host_evidence_unavailable")
            with lifecycle._lock:
                with self._capacity_owner._lock:
                    binding_matches = self._lifecycle_profile_binding_matches_locked(lifecycle)
            if not binding_matches:
                return self.revoke("host_evidence_unavailable")
        return self._safe_state()
