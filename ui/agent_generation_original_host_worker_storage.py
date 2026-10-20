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
        if not self._worker._register_original_host_operation_for_characterization(
                self._worker_owner_claim, kind, correlation):
            return None, "worker_unavailable"
        if kind == "submission":
            self._submitted.add((kind, index, correlation.attempt_id))
        lease = GenerationWorkerOperationLease(
            lifecycle._generation, uuid.uuid4().hex, kind, index, correlation,
        )
        self._active = lease
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
                    )
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
                    or attempt.state != "pre_admitted"):
                return "foreign_or_settled_preadmission"
        return self._cancel_staging_preadmission_attempt(attempt)

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
                    self._state = "uncertain"
                    self._reason = "worker_prompt_conflict"
                    return "uncertain_non_authoritative"
                self._accepted_prompt_ids[lease.request_index] = accepted_prompt_id

            self._active = None
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
