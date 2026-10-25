"""Non-executing host ownership for a supplied Worker and protected roots.

This owner binds exact references, retains bounded diagnostic observations and
may reserve one pre-write staging estimate per request through the existing
Profile A capacity ledger. The original-host runtime's explicit Profile A
pre-send seam can retain one exact accepted ``submission_started`` Executor
event here before registering the Worker operation. This owner itself never
advances the Job Registry/Inbox, performs Worker I/O, invokes a Journal/storage/
promotion writer, or grants write or publication authority.
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
class GenerationWorkerProtectedAcceptanceObservation:
    """Count-only result for one exact Profile A protected Acceptance."""

    status: str
    request_index: int
    accepted_image_count: int
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerProtectedPromotionPreflightObservation:
    """Count-only reservation result; it authorizes no protected write."""

    status: str
    request_index: int
    reserved_image_count: int
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"
    _issuer: object = field(default=None, repr=False, compare=False)
    _attempt_nonce: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class GenerationWorkerProtectedPromotionObservation:
    """Count-only result after one exact original-Host Promotion publication."""

    status: str
    request_index: int
    promoted_image_count: int
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerProtectedOutputsReadyObservation:
    """Count-only result after one genuine protected outputs-ready event."""

    status: str
    request_index: int
    output_count: int
    candidate_eligibility: str = "not_established"
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerProtectedCandidateAdmissionPreflightObservation:
    """Read-only Profile A review; Candidate eligibility is not established."""

    status: str
    request_index: int
    verified_promoted_image_count: int
    candidate_eligibility: str = "not_established"
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerProtectedCandidateAdmissionObservation:
    """Count-only evidence that the protected Candidate admission owner observed eligibility."""

    status: str
    request_index: int
    verified_promoted_image_count: int
    candidate_eligibility: str = "evidence_observed"
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerProtectedCandidatePublicationObservation:
    """Count-only result of one Profile A in-memory Gallery registration."""

    status: str
    request_index: int
    registered_candidate_count: int
    expected_candidate_count: int
    registration_state: str
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass(frozen=True)
class GenerationWorkerExecutorEventChainObservation:
    """Read-only view of accepted and Profile A source-bound Job/Inbox events."""

    status: str
    request_index: int
    accepted_event_kinds: tuple[str, ...]
    profile_a_event_kinds: tuple[str, ...]
    next_required_event: str | None
    candidate_eligibility: str = "not_established"
    execution_available: bool = False
    protected_storage_available: bool = False
    promotion_available: bool = False
    candidate_publication_allowed: bool = False
    project_save_allowed: bool = False
    authorship: str = "unverified"


@dataclass
class _ProfileASubmittedEventAttempt:
    """Private one-shot custody for an issued submission completion and event."""

    lease: object
    completion: object
    prepared: object
    submission_started_event: object
    state: str = "claim_in_progress"
    prompt_id: str | None = None
    event: object = None


@dataclass
class _ProfileARemoteOutputsReadyEventAttempt:
    """Private one-shot custody for a validated successful History event."""

    preadmission_attempt: object = field(repr=False)
    submitted_attempt: object = field(repr=False)
    history_lease: object = field(repr=False)
    history_completion: object = field(repr=False)
    prepared: object = field(repr=False)
    remote_receipt: object = field(repr=False)
    evidence: object = field(repr=False)
    state: str = "event_acceptance_in_progress"
    event: object = field(default=None, repr=False)


@dataclass
class _ProfileAOutputsReadyEventAttempt:
    """Private one-shot custody for the post-Promotion Job/Inbox event."""

    preadmission_attempt: object = field(repr=False)
    promotion_observation: object = field(repr=False)
    promotion_marker: object = field(repr=False)
    remote_attempt: object = field(repr=False)
    promotion_owner: object = field(repr=False)
    promotion_receipt: object = field(repr=False)
    remote_receipt: object = field(repr=False)
    state: str = "claim_in_progress"
    event: object = field(default=None, repr=False)
    observation: object = field(default=None, repr=False)


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
    writer_observation: object = None
    acceptance_observations: tuple = ()
    acceptance_state: str = "not_started"
    acceptance_marker: object = None
    acceptance_host_freshness: object = None
    acceptance_owner: object = None
    accepted_batch: object = None
    acceptance_observation: object = None
    promotion_preflight_state: str = "not_started"
    promotion_preflight_marker: object = None
    promotion_preflight_observation: object = None
    promotion_capacity_operation: object = None
    promotion_capacity_reservation: object = None
    promotion_capacity_estimate: object = None
    promotion_writer_marker: object = None
    promotion_write_admission: object = None
    promotion_owner: object = None
    promotion_host_binding: object = None
    promotion_receipt: object = None
    promotion_create_attempt_count: int = 0
    promotion_create_descriptor_identities: tuple = ()
    promotion_publication_state: str = "not_started"
    promotion_publication_marker: object = None
    promotion_publication_observation: object = None
    promotion_publication_completed_delta: object = None
    candidate_admission_state: str = "not_started"
    candidate_admission_marker: object = None
    candidate_admission_observation: object = None
    protected_candidate_admission_state: str = "not_started"
    protected_candidate_admission_marker: object = None
    protected_candidate_admission_owner: object = None
    protected_candidate_admission_result: object = None
    protected_candidate_admission_observation: object = None
    protected_candidate_publication_state: str = "not_started"
    protected_candidate_publication_marker: object = None
    protected_candidate_publication_locator: object = None
    protected_candidate_publication_owner: object = None
    protected_candidate_publication_receipt: object = None
    protected_candidate_publication_observation: object = None


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
    """One exact lifecycle's Worker/root references and bounded pre-admission.

    The runtime may retain one source-bound pre-send event after Job/Inbox
    acceptance; all subsequent Executor event stages remain unimplemented here.
    """

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
        # Only the prospective Profile A pre-send seam records a source-bound
        # Executor event here. Existing fake/legacy event observations are not
        # upgraded by matching sequence, count, or event values.
        self._profile_a_submission_started_events = {}
        # A submitted event becomes source-bound only after this original Host
        # observes the exact issued Worker completion and both Job/Inbox owners
        # accept the same ExecutorEvent object.
        self._profile_a_submitted_event_attempts = {}
        # The next prospective Profile A source event is issued only alongside
        # exact validated ready-History evidence. Accepted-but-unbound events
        # remain here as uncertainty and cannot be replayed.
        self._profile_a_remote_outputs_ready_event_attempts = {}
        # Published Promotion -> outputs_ready is a distinct one-shot Host
        # event owner. It retains the exact event object; the public result
        # never carries the protected receipt or any Candidate authority.
        self._profile_a_outputs_ready_event_attempts = {}
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

    def begin_operation_for_characterization(
            self, kind, prepared, prompt_id, correlation, *, _defer_worker_registration=False):
        """Pin one host operation before an external caller uses its Worker."""
        from core.comfy_prompt_request import is_owner_prepared_frozen_request
        from ui.agent_generation_http_io_worker import HTTPIOCorrelation

        if (type(_defer_worker_registration) is not bool
                or (_defer_worker_registration
                    and (not self._profile_a or kind != "submission"))
                or kind not in {"submission", "history"}
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
                            defer_worker_registration=_defer_worker_registration,
                        )
        if binding_invalid:
            self.revoke("host_evidence_unavailable")
            return None, "stale_non_authoritative"
        return result

    def _begin_operation_locked(
            self, kind, prepared, prompt_id, correlation, lifecycle, *,
            defer_worker_registration=False):
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
            if kind == "submission" and index in self._profile_a_submission_started_events:
                return None, "profile_a_submission_already_started"
            if (kind == "history"
                    and index in self._profile_a_submission_started_events):
                submitted_attempt = self._profile_a_submitted_event_attempts.get(index)
                if (submitted_attempt is None
                        or submitted_attempt.state != "events_accepted"):
                    return None, "profile_a_submitted_event_required"
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
        if not defer_worker_registration:
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
        return lease, ("pending_executor_event" if defer_worker_registration
                       else "admitted_non_executing")

    def _activate_profile_a_submission_after_event_for_characterization(self, lease, event):
        """Register an exact Worker submission only after its accepted Host event.

        The caller must hold the runtime publication/route gate and the exact
        Job Registry + Inbox locks. This method repeats the private custody
        checks under the established Job -> Inbox -> lifecycle -> capacity ->
        integration -> Worker lock order.
        """
        from ui.agent_generation_executor_inbox import ExecutorEvent
        from ui.agent_generation_job import WorkerEvent

        lifecycle = self._lifecycle_ref()
        if (not self._profile_a or lifecycle is None
                or type(lease) is not GenerationWorkerOperationLease
                or type(event) is not ExecutorEvent
                or type(event.progress) is not WorkerEvent):
            return False
        jobs, inbox = lifecycle._jobs, lifecycle._inbox
        with jobs._lock:
            with inbox._lock:
                job = jobs._authorized_locked(lifecycle._job_id, lifecycle._claim_id)
                sequence = event.progress.sequence
                index = lease.request_index
                if (job is None or inbox._closed or inbox._state != "accepted"
                        or inbox._envelope is not lifecycle._envelope
                        or inbox._events.get(sequence) is not event
                        or not any(item is event for item in inbox._authority_events)
                        or job.event_count != sequence
                        or job.events.get(sequence) != event.progress
                        or not job.authority_events
                        or job.authority_events[-1] != event.progress
                        or job.request_states[index] != "submitting"
                        or (event.job_id, event.claim_id, event.manifest_identity)
                            != (lifecycle._job_id, lifecycle._claim_id,
                                lifecycle._manifest_identity)
                        or (event.progress.kind, event.progress.request_index,
                            event.progress.output_count, event.progress.prompt_id,
                            event.outputs)
                            != ("submission_started", index, 0, None, None)
                        or self._profile_a_submission_started_events.get(index) is not None):
                    return False
                with lifecycle._lock:
                    with self._capacity_owner._lock:
                        with self._lock:
                            if (lifecycle._worker_storage_integration is not self
                                    or lifecycle._state != "bound_non_executing"
                                    or lifecycle._generation != self._lifecycle_generation
                                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                                    or not self._root_binding_matches()
                                    or self._state != "bound_non_executing"
                                    or self._active is not lease
                                    or lease.kind != "submission"
                                    or lease.lifecycle_generation != self._lifecycle_generation
                                    or self._active_prepared is None
                                    or self._active_prepared.request_index != index
                                    or self._issued.get(self._correlation_key(
                                        "submission", lease.correlation)) is not lease.correlation):
                                return False
                            if not self._worker._register_original_host_operation_for_characterization(
                                    self._worker_owner_claim, "submission", lease.correlation):
                                return False
                            self._profile_a_submission_started_events[index] = event
                            return True

    def _claim_profile_a_submitted_event_attempt_for_characterization(
            self, lease, completion):
        """Claim one exact issued completion before Host result observation.

        The original runtime calls this while its publication/route guard and
        Job/Inbox locks are held. This method performs bounded in-memory checks
        only; it does not inspect transport state beyond the Worker-issued
        completion witness.
        """
        from core.comfy_prompt_request import is_owner_prepared_frozen_request
        from ui.agent_generation_executor_inbox import ExecutorEvent
        from ui.agent_generation_http_io_worker import HTTPIOCompletion
        from ui.agent_generation_job import WorkerEvent

        if not self._profile_a:
            return None
        lifecycle = self._lifecycle_ref()
        if lifecycle is None:
            return None
        jobs, inbox = lifecycle._jobs, lifecycle._inbox
        with jobs._lock:
            with inbox._lock:
                job = jobs._authorized_locked(lifecycle._job_id, lifecycle._claim_id)
                envelope = lifecycle._envelope
                if (job is None or envelope is None or inbox._closed
                        or inbox._state != "accepted" or inbox._envelope is not envelope
                        or type(lease) is not GenerationWorkerOperationLease
                        or type(completion) is not HTTPIOCompletion
                        or completion.kind != "submission"
                        or completion.correlation is not lease.correlation
                        or lease.kind != "submission"):
                    return None
                index = lease.request_index
                if (type(index) is not int or not 0 <= index < len(envelope.manifest.requests)
                        or index in self._profile_a_submitted_event_attempts):
                    return None
                started = self._profile_a_submission_started_events.get(index)
                prepared = self._active_prepared if self._active is lease else None
                request = envelope.manifest.requests[index]
                sequence = getattr(getattr(started, "progress", None), "sequence", None)
                if (type(started) is not ExecutorEvent
                        or type(started.progress) is not WorkerEvent
                        or inbox._events.get(sequence) is not started
                        or not any(item is started for item in inbox._authority_events)
                        or job.event_count != sequence
                        or job.events.get(sequence) != started.progress
                        or not job.authority_events
                        or job.authority_events[-1] != started.progress
                        or job.request_states[index] != "submitting"
                        or (started.job_id, started.claim_id, started.manifest_identity)
                            != (lifecycle._job_id, lifecycle._claim_id,
                                lifecycle._manifest_identity)
                        or (started.progress.kind, started.progress.request_index,
                            started.progress.output_count, started.progress.prompt_id,
                            started.outputs) != ("submission_started", index, 0, None, None)
                        or not is_owner_prepared_frozen_request(prepared)
                        or prepared.request_index != index
                        or prepared.request_id != request.request_id
                        or prepared.workflow_identity != request.workflow_identity
                        or lease.lifecycle_generation != self._lifecycle_generation
                        or self._issued.get(self._correlation_key(
                            "submission", lease.correlation,
                        )) is not lease.correlation):
                    return None
                with lifecycle._lock:
                    with self._capacity_owner._lock:
                        with self._lock:
                            attempt = self._storage_preadmission_attempts.get(index)
                            if (lifecycle._worker_storage_integration is not self
                                    or lifecycle._state != "bound_non_executing"
                                    or lifecycle._generation != self._lifecycle_generation
                                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                                    or not self._root_binding_matches()
                                    or self._state != "bound_non_executing"
                                    or self._active is not lease
                                    or self._active_prepared is not prepared
                                    or (attempt is not None and attempt.lease is not lease)):
                                return None

                            marker = _ProfileASubmittedEventAttempt(
                                lease, completion, prepared, started,
                            )

                            def retain_claim():
                                self._profile_a_submitted_event_attempts[index] = marker
                                return marker

                            # Worker lock is last in the established order. It
                            # proves the exact returned completion and fences
                            # a close that wins before the claim.
                            return self._worker._run_if_issued_completion_for_prepared_request_for_characterization(
                                completion, prepared, self._worker_owner_claim,
                                retain_claim,
                            )

    def _retain_profile_a_submitted_event_uncertain_locked(
            self, marker, *, accepted_event=None, reason="submitted_event_uncertain"):
        marker.state = "retained_uncertain"
        if accepted_event is not None:
            marker.event = accepted_event
        self._uncertain_leases[marker.lease.nonce] = marker.lease
        if self._state == "bound_non_executing":
            self._state = "uncertain"
        self._reason = self._reason or reason

    def _complete_profile_a_submitted_event_for_characterization(
            self, lease, completion, observation_status):
        """Publish submitted only from the claimed, Host-observed completion."""
        from core.comfy_http_submission import SubmissionResult
        from ui.agent_generation_executor_inbox import ExecutorEvent
        from ui.agent_generation_http_io_worker import HTTPIOCompletion
        from ui.agent_generation_job import WorkerEvent

        if not self._profile_a:
            return observation_status
        lifecycle = self._lifecycle_ref()
        if lifecycle is None:
            return observation_status
        jobs, inbox = lifecycle._jobs, lifecycle._inbox
        index = getattr(lease, "request_index", None)
        with jobs._lock:
            with inbox._lock:
                with lifecycle._lock:
                    with self._capacity_owner._lock:
                        with self._lock:
                            marker = self._profile_a_submitted_event_attempts.get(index)
                            if (marker is None or marker.lease is not lease
                                    or marker.completion is not completion
                                    or marker.state != "claim_in_progress"):
                                return observation_status

                            if observation_status != "observed_non_authoritative":
                                self._retain_profile_a_submitted_event_uncertain_locked(marker)
                                return (observation_status if observation_status in {
                                    "stale_non_authoritative", "foreign_non_authoritative",
                                    "duplicate_non_authoritative",
                                } else "uncertain_non_authoritative")

                            outcome = (completion.outcome
                                       if type(completion) is HTTPIOCompletion else None)
                            if (type(outcome) is SubmissionResult
                                    and outcome.status == "rejected_before_submission"):
                                marker.state = "submission_rejected"
                                return observation_status
                            accepted_prompt_id = self._accepted_prompt_ids.get(index)
                            attempt = self._storage_preadmission_attempts.get(index)
                            if (type(completion) is not HTTPIOCompletion
                                    or completion.kind != "submission"
                                    or completion.correlation is not lease.correlation
                                    or type(outcome) is not SubmissionResult
                                    or outcome.status != "accepted"
                                    or type(accepted_prompt_id) is not str
                                    or not accepted_prompt_id
                                    or (attempt is not None and (
                                        attempt.lease is not lease
                                        or attempt.prepared is not marker.prepared
                                        or attempt.submission_completion is not completion
                                        or attempt.accepted_prompt_id != accepted_prompt_id
                                    ))):
                                self._retain_profile_a_submitted_event_uncertain_locked(marker)
                                return "uncertain_non_authoritative"

                            marker.prompt_id = accepted_prompt_id
                            marker.state = "event_acceptance_in_progress"
                            started = marker.submission_started_event
                            job = jobs._authorized_locked(lifecycle._job_id, lifecycle._claim_id)
                            if (lifecycle._worker_storage_integration is not self
                                    or lifecycle._state != "bound_non_executing"
                                    or lifecycle._generation != self._lifecycle_generation
                                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                                    or not self._root_binding_matches()
                                    or self._capacity_owner._closed
                                    or self._capacity_owner._invalid
                                    or self._state != "bound_non_executing"
                                    or inbox._closed or inbox._state != "accepted"
                                    or inbox._envelope is not lifecycle._envelope
                                    or job is None
                                    or job.event_count != started.progress.sequence
                                    or job.request_states[index] != "submitting"
                                    or inbox._events.get(started.progress.sequence) is not started
                                    or not any(item is started for item in inbox._authority_events)
                                    or job.events.get(started.progress.sequence) != started.progress):
                                self._retain_profile_a_submitted_event_uncertain_locked(marker)
                                return "uncertain_non_authoritative"

                            event = ExecutorEvent(
                                lifecycle._job_id,
                                lifecycle._claim_id,
                                lifecycle._manifest_identity,
                                WorkerEvent(
                                    job.event_count + 1, index, "submitted", 0,
                                    None, accepted_prompt_id,
                                ),
                                None,
                            )

                            def accept_and_bind():
                                accepted_event = False
                                try:
                                    accepted = inbox.event_for_characterization(
                                        jobs, event, target_current=True,
                                    )
                                    accepted_event = (
                                        inbox._events.get(event.progress.sequence) is event
                                        and any(item is event for item in inbox._authority_events)
                                        and job.events.get(event.progress.sequence) == event.progress
                                        and job.event_count == event.progress.sequence
                                        and job.request_states[index] == "awaiting_result"
                                    )
                                    if accepted == "accepted" and accepted_event:
                                        marker.event = event
                                        # A same-thread reentrant close or
                                        # invalidation may run inside a test
                                        # sink. Preserve the accepted event but
                                        # never claim Profile A binding then.
                                        if (self._state == "bound_non_executing"
                                                and lifecycle._state == "bound_non_executing"
                                                and not self._capacity_owner._closed
                                                and not self._capacity_owner._invalid
                                                and self._worker._state == "running"
                                                and self._worker._active_task is None
                                                and self._worker._characterization_owner_claim
                                                    is self._worker_owner_claim):
                                            marker.state = "events_accepted"
                                            return "submitted_event_accepted_non_authoritative"
                                    elif accepted_event:
                                        marker.event = event
                                except Exception:
                                    accepted_event = (
                                        inbox._events.get(event.progress.sequence) is event
                                        and any(item is event for item in inbox._authority_events)
                                        and job.events.get(event.progress.sequence) == event.progress
                                    )
                                    if accepted_event:
                                        marker.event = event
                                self._retain_profile_a_submitted_event_uncertain_locked(
                                    marker,
                                    accepted_event=event if accepted_event else None,
                                )
                                return "uncertain_non_authoritative"

                            published = self._worker._run_if_issued_completion_for_prepared_request_for_characterization(
                                completion, marker.prepared,
                                self._worker_owner_claim, accept_and_bind,
                            )
                            if published is None:
                                self._retain_profile_a_submitted_event_uncertain_locked(marker)
                                return "uncertain_non_authoritative"
                            return published

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

    def _profile_a_remote_outputs_ready_event_is_current_locked(
            self, lifecycle, attempt, marker, *, outputs_marker=None):
        """Check the exact Profile A event prefix and its current terminal boundary.

        Without ``outputs_marker`` this is the original 19G-D invariant: the
        remote event is the latest accepted event and the Job is awaiting
        download. With an exact private 19G-E marker, the same predecessor
        identities are required while the accepted output event is latest.
        """
        from core.comfy_remote_output_receipts import RemoteOutputReceipt
        from core.generation_windows_protected_promotion import VerifiedProtectedPromotionReceipt
        from ui.agent_generation_executor_inbox import ExecutorEvent, OutputReceipt
        from ui.agent_generation_job import WorkerEvent

        index = attempt.lease.request_index
        source_started = self._profile_a_submission_started_events.get(index)
        submitted = self._profile_a_submitted_event_attempts.get(index)
        inbox = lifecycle._inbox
        job = lifecycle._jobs._authorized_locked(lifecycle._job_id, lifecycle._claim_id)
        event = marker.event
        remote = marker.remote_receipt
        evidence = marker.evidence
        source_sequence = getattr(getattr(source_started, "progress", None), "sequence", None)
        submitted_event = getattr(submitted, "event", None)
        submitted_sequence = getattr(
            getattr(submitted_event, "progress", None), "sequence", None,
        )
        prefix_current = bool(
            self._profile_a_remote_outputs_ready_event_attempts.get(index) is marker
            and marker.preadmission_attempt is attempt
            and submitted is not None and marker.submitted_attempt is submitted
            and submitted.state == "events_accepted"
            and marker.history_lease is attempt.history_lease
            and marker.history_completion is attempt.history_completion
            and marker.prepared is attempt.prepared
            and remote is attempt.remote_receipt
            and type(remote) is RemoteOutputReceipt
            and remote.execution_succeeded is True
            and type(remote.images) is tuple
            and 1 <= len(remote.images) <= 16
            and evidence is attempt.evidence
            and type(evidence) is GenerationWorkerRemoteOutputWriterEvidence
            and evidence._issuer is self
            and evidence._attempt_nonce == attempt.lease.nonce
            and evidence.remote_output_identity == remote.identity
            and evidence.descriptor_count == len(remote.images)
            and type(event) is ExecutorEvent
            and type(event.progress) is WorkerEvent
            and type(event.outputs) is OutputReceipt
            and source_started is not None
            and type(source_started) is ExecutorEvent
            and type(source_started.progress) is WorkerEvent
            and source_started.job_id == lifecycle._job_id
            and source_started.claim_id == lifecycle._claim_id
            and source_started.manifest_identity == lifecycle._manifest_identity
            and source_started.progress.kind == "submission_started"
            and source_started.progress.request_index == index
            and source_started.progress.prompt_id is None
            and submitted_event is not None
            and type(submitted_event) is ExecutorEvent
            and type(submitted_event.progress) is WorkerEvent
            and submitted.submission_started_event is source_started
            and submitted_event.job_id == lifecycle._job_id
            and submitted_event.claim_id == lifecycle._claim_id
            and submitted_event.manifest_identity == lifecycle._manifest_identity
            and submitted_event.progress.kind == "submitted"
            and submitted_event.progress.request_index == index
            and submitted_event.progress.prompt_id == attempt.accepted_prompt_id
            and type(source_sequence) is int
            and type(submitted_sequence) is int
            and source_sequence < submitted_sequence < event.progress.sequence
            # Job progress alone is not enough to authorize a later protected
            # Writer handoff. Retain the exact accepted Inbox objects for both
            # preceding source events throughout the full event prefix.
            and inbox._events.get(source_sequence) is source_started
            and sum(item is source_started for item in inbox._authority_events) == 1
            and inbox._events.get(submitted_sequence) is submitted_event
            and sum(item is submitted_event for item in inbox._authority_events) == 1
            and job is not None
            and job.events.get(source_started.progress.sequence) == source_started.progress
            and sum(item == source_started.progress for item in job.authority_events) == 1
            and job.events.get(submitted_sequence) == submitted_event.progress
            and sum(item == submitted_event.progress for item in job.authority_events) == 1
            and event.job_id == lifecycle._job_id
            and event.claim_id == lifecycle._claim_id
            and event.manifest_identity == lifecycle._manifest_identity
            and event.progress.kind == "remote_outputs_ready"
            and event.progress.request_index == index
            and event.progress.prompt_id is None
            and event.progress.cause is None
            and event.progress.output_count == len(remote.images)
            and event.outputs.receipt_id == remote.identity[:32]
            and event.outputs.output_count == len(remote.images)
            and not inbox._closed
            and inbox._state == "accepted"
            and inbox._envelope is lifecycle._envelope
            and inbox._events.get(event.progress.sequence) is event
            and sum(item is event for item in inbox._authority_events) == 1
            and job.events.get(event.progress.sequence) == event.progress
            and sum(item == event.progress for item in job.authority_events) == 1
            and 0 <= index < len(job.request_states)
            and job.remote_outputs[index] == len(remote.images)
            and job.registered[index] == 0
        )
        if not prefix_current:
            return False
        if outputs_marker is None:
            return bool(
                job.event_count == event.progress.sequence
                and job.request_states[index] == "awaiting_download"
            )

        output_event = outputs_marker.event
        output_observation = outputs_marker.observation
        promotion_receipt = outputs_marker.promotion_receipt
        promotion_observation = outputs_marker.promotion_observation
        return bool(
            type(outputs_marker) is _ProfileAOutputsReadyEventAttempt
            and self._profile_a_outputs_ready_event_attempts.get(index) is outputs_marker
            and outputs_marker.preadmission_attempt is attempt
            and outputs_marker.remote_attempt is marker
            and outputs_marker.remote_receipt is remote
            and outputs_marker.promotion_marker is attempt.promotion_publication_marker
            and outputs_marker.promotion_owner is attempt.promotion_owner
            and promotion_receipt is attempt.promotion_receipt
            and promotion_observation is attempt.promotion_publication_observation
            and (
                (outputs_marker.state == "retained_uncertain"
                 and output_observation is None)
                or (
                    type(output_observation) is GenerationWorkerProtectedOutputsReadyObservation
                    and output_observation.status
                        == "protected_outputs_ready_event_accepted_non_authoritative"
                    and output_observation.request_index == index
                    and output_observation.output_count == len(remote.images)
                    and output_observation.candidate_eligibility == "not_established"
                    and output_observation.execution_available is False
                    and output_observation.protected_storage_available is False
                    and output_observation.promotion_available is False
                    and output_observation.candidate_publication_allowed is False
                    and output_observation.project_save_allowed is False
                    and output_observation.authorship == "unverified"
                )
            )
            and attempt.promotion_publication_state == "published_non_authoritative"
            and attempt.promotion_preflight_state == "promoted_non_authoritative"
            and outputs_marker.state in {
                "event_acceptance_in_progress", "events_accepted", "retained_uncertain",
            }
            and type(promotion_receipt) is VerifiedProtectedPromotionReceipt
            and promotion_receipt._promotion_owner is outputs_marker.promotion_owner
            and promotion_receipt._protected_owner is attempt.writer_owner
            and promotion_receipt._acceptance_owner is attempt.acceptance_owner
            and promotion_receipt._accepted is attempt.accepted_batch
            and promotion_receipt.remote_receipt_identity == remote.identity
            and type(output_event) is ExecutorEvent
            and type(output_event.progress) is WorkerEvent
            and type(output_event.outputs) is OutputReceipt
            and output_event.job_id == lifecycle._job_id
            and output_event.claim_id == lifecycle._claim_id
            and output_event.manifest_identity == lifecycle._manifest_identity
            and output_event.progress.kind == "outputs_ready"
            and output_event.progress.request_index == index
            and output_event.progress.prompt_id is None
            and output_event.progress.cause is None
            and output_event.progress.output_count == len(remote.images)
            and event.progress.sequence + 1 == output_event.progress.sequence
            and output_event.outputs.receipt_id == promotion_receipt.identity[:32]
            and output_event.outputs.receipt_id != event.outputs.receipt_id
            and output_event.outputs.output_count == len(remote.images)
            and inbox._events.get(output_event.progress.sequence) is output_event
            and sum(item is output_event for item in inbox._authority_events) == 1
            and job.event_count == output_event.progress.sequence
            and job.events.get(output_event.progress.sequence) == output_event.progress
            and sum(item == output_event.progress for item in job.authority_events) == 1
            and job.request_states[index] == "awaiting_host_registration"
            and job.remote_outputs[index] == len(remote.images)
            and job.outputs[index] == len(remote.images)
            and job.registered[index] == 0
        )

    def _commit_profile_a_remote_outputs_ready_event_locked(
            self, lifecycle, attempt, remote, evidence):
        """Accept one genuine event after the exact successful History receipt."""
        from ui.agent_generation_executor_inbox import ExecutorEvent, OutputReceipt
        from ui.agent_generation_job import WorkerEvent

        index = attempt.lease.request_index
        source_started = self._profile_a_submission_started_events.get(index)
        # Preserve older direct/fake characterization as non-source-bound.
        if source_started is None:
            return evidence, evidence.status
        if index in self._profile_a_remote_outputs_ready_event_attempts:
            return evidence, "remote_outputs_ready_event_already_claimed"

        submitted = self._profile_a_submitted_event_attempts.get(index)
        marker = _ProfileARemoteOutputsReadyEventAttempt(
            preadmission_attempt=attempt,
            submitted_attempt=submitted,
            history_lease=attempt.history_lease,
            history_completion=attempt.history_completion,
            prepared=attempt.prepared,
            remote_receipt=remote,
            evidence=evidence,
        )
        self._profile_a_remote_outputs_ready_event_attempts[index] = marker
        job = lifecycle._jobs._authorized_locked(lifecycle._job_id, lifecycle._claim_id)
        inbox = lifecycle._inbox
        if (not self._profile_a or submitted is None
                or submitted.state != "events_accepted"
                or submitted.submission_started_event is not source_started
                or submitted.lease is not attempt.lease
                or submitted.completion is not attempt.submission_completion
                or submitted.prompt_id != attempt.accepted_prompt_id
                or submitted.event is None
                or source_started.progress.kind != "submission_started"
                or submitted.event.progress.kind != "submitted"
                or job is None
                or job.events.get(source_started.progress.sequence) != source_started.progress
                or sum(item == source_started.progress for item in job.authority_events) != 1
                or job.events.get(submitted.event.progress.sequence) != submitted.event.progress
                or sum(item == submitted.event.progress for item in job.authority_events) != 1
                or inbox._events.get(source_started.progress.sequence) is not source_started
                or not any(item is source_started for item in inbox._authority_events)
                or inbox._events.get(submitted.event.progress.sequence) is not submitted.event
                or not any(item is submitted.event for item in inbox._authority_events)
                or job is None or inbox._closed or inbox._state != "accepted"
                or inbox._envelope is not lifecycle._envelope
                or not 0 <= index < len(job.request_states)
                or job.request_states[index] != "awaiting_result"
                or job.remote_outputs[index] != 0 or job.registered[index] != 0
                or (submitted.event.job_id, submitted.event.claim_id,
                    submitted.event.manifest_identity)
                    != (lifecycle._job_id, lifecycle._claim_id,
                        lifecycle._manifest_identity)
                or submitted.event.progress.request_index != index
                or submitted.event.progress.prompt_id != attempt.accepted_prompt_id
                or lifecycle._state != "bound_non_executing"
                or self._state != "bound_non_executing"
                or self._capacity_owner._closed or self._capacity_owner._invalid
                or self._worker._state != "running"
                or self._worker._active_task is not None
                or self._worker._characterization_owner_claim is not self._worker_owner_claim):
            marker.state = "refused"
            return evidence, "remote_outputs_ready_event_refused"

        event = ExecutorEvent(
            lifecycle._job_id, lifecycle._claim_id, lifecycle._manifest_identity,
            WorkerEvent(
                job.event_count + 1, index, "remote_outputs_ready",
                output_count=len(remote.images),
            ),
            OutputReceipt(remote.identity[:32], len(remote.images)),
        )
        marker.event = event

        def event_mutation_observed():
            sequence = event.progress.sequence
            current = lifecycle._jobs._authorized_locked(
                lifecycle._job_id, lifecycle._claim_id,
            )
            return bool(
                current is not None
                and (current.events.get(sequence) == event.progress
                     or any(item == event.progress for item in current.authority_events)
                     or inbox._events.get(sequence) is event
                     or any(item is event for item in inbox._authority_events))
            )

        try:
            accepted = inbox.event_for_characterization(
                lifecycle._jobs, event, target_current=True,
            )
        except Exception:
            marker.state = "retained_uncertain"
            return evidence, "remote_outputs_ready_event_uncertain"

        if (accepted == "accepted"
                and self._profile_a_remote_outputs_ready_event_is_current_locked(
                    lifecycle, attempt, marker,
                )
                and lifecycle._state == "bound_non_executing"
                and self._state == "bound_non_executing"
                and not self._capacity_owner._closed
                and not self._capacity_owner._invalid
                and self._worker._state == "running"
                and self._worker._active_task is None
                and self._worker._characterization_owner_claim is self._worker_owner_claim):
            marker.state = "events_accepted"
            return evidence, evidence.status

        marker.state = ("retained_uncertain" if event_mutation_observed()
                        else "refused")
        return evidence, (
            "remote_outputs_ready_event_uncertain"
            if marker.state == "retained_uncertain"
            else "remote_outputs_ready_event_refused"
        )

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
                        return self._commit_profile_a_remote_outputs_ready_event_locked(
                            lifecycle, attempt, remote, evidence,
                        )

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
                    if (attempt is not None
                            and self._profile_a_submission_started_events.get(
                                evidence.request_index,
                            ) is not None):
                        remote_event_attempt = self._profile_a_remote_outputs_ready_event_attempts.get(
                            evidence.request_index,
                        )
                        if (remote_event_attempt is None
                                or remote_event_attempt.state != "events_accepted"
                                or not self._profile_a_remote_outputs_ready_event_is_current_locked(
                                    lifecycle, attempt, remote_event_attempt,
                                )):
                            return None, "remote_outputs_ready_event_required"
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
            attempt.acceptance_observations = (image,)
            observation = GenerationWorkerProtectedWriterObservation(
                status="protected_image_staged_non_authoritative",
                request_index=attempt.lease.request_index,
                verified_image_count=1,
                capacity_accounted=True,
            )
            attempt.writer_observation = observation
            return observation, "protected_image_staged_non_authoritative"

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
            attempt.acceptance_observations = observations
            attempt.writer_handoff_state = "staged_non_authoritative"
            observation = GenerationWorkerProtectedWriterObservation(
                status="protected_image_batch_staged_non_authoritative",
                request_index=attempt.lease.request_index,
                verified_image_count=len(observations),
                capacity_accounted=True,
            )
            attempt.writer_observation = observation
            return observation, "protected_image_batch_staged_non_authoritative"

    def _begin_profile_a_acceptance_locked(self, lifecycle, observation):
        """Claim one exact staged count-only observation for Acceptance."""
        if (not self._profile_a
                or type(observation) is not GenerationWorkerProtectedWriterObservation):
            return None, "protected_acceptance_unavailable"
        with lifecycle._lock:
            with self._capacity_owner._lock:
                with self._lock:
                    attempt = self._storage_preadmission_attempts.get(observation.request_index)
                    if (lifecycle._worker_storage_integration is not self
                            or lifecycle._state != "bound_non_executing"
                            or lifecycle._generation != self._lifecycle_generation
                            or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                            or not self._root_binding_matches()
                            or self._state != "bound_non_executing"
                            or attempt is None or attempt.state != "pre_admitted"
                            or attempt.evidence_state != "evidence_published"
                            or attempt.writer_handoff_state != "staged_non_authoritative"
                            or attempt.writer_observation is not observation
                            or observation.capacity_accounted is not True
                            or observation.write_authorized is not False
                            or attempt.acceptance_state != "not_started"
                            or attempt.acceptance_marker is not None
                            or attempt.acceptance_owner is not None
                            or attempt.accepted_batch is not None
                            or attempt.prepared is None or attempt.remote_receipt is None
                            or attempt.history_completion is None
                            or attempt.history_json != attempt.remote_receipt._validated_history_json
                            or attempt.accepted_prompt_id != attempt.remote_receipt.prompt_id
                            or attempt.writer_owner is not self._profile_a_writer_owner
                            or self._profile_a_writer_owner is None
                            or self._active is not None):
                        return None, "protected_acceptance_evidence_unavailable"
                    count = len(attempt.remote_receipt.images)
                    expected_status = ("protected_image_staged_non_authoritative" if count == 1
                                       else "protected_image_batch_staged_non_authoritative")
                    observations = attempt.acceptance_observations
                    if (count < 1 or count > _MAX_WRITER_IMAGES
                            or observation.status != expected_status
                            or observation.verified_image_count != count
                            or type(observations) is not tuple or len(observations) != count
                            or (count == 1 and observations[0] is not attempt.writer_image_observation)
                            or (count > 1 and observations is not attempt.writer_image_observations)
                            or attempt.writer_create_attempt_count != count):
                        return None, "protected_acceptance_batch_incomplete"
                    if (lifecycle._worker_storage_integration is not self
                            or lifecycle._state != "bound_non_executing"
                            or lifecycle._generation != self._lifecycle_generation
                            or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                            or not self._root_binding_matches()
                            or self._storage_preadmission_attempts.get(
                                attempt.lease.request_index) is not attempt
                            or attempt.evidence._issuer is not self
                            or attempt.evidence._attempt_nonce != attempt.lease.nonce
                            or attempt.writer_handoff_marker is None
                            or attempt.writer_owner is not self._profile_a_writer_owner
                            or attempt.writer_handoff_state != "staged_non_authoritative"
                            or attempt.cancel_requested):
                        return None, "protected_acceptance_host_changed"
                    marker = object()
                    attempt.acceptance_state = "in_progress"
                    attempt.acceptance_marker = marker
                    return (attempt, marker, attempt.evidence, attempt.writer_owner,
                            lifecycle._envelope, attempt.prepared, attempt.remote_receipt,
                            attempt.capacity_operation, attempt.reservation,
                            attempt.writer_admission, observations), "acceptance_claimed"

    def _begin_profile_a_promotion_preflight_locked(self, lifecycle, observation):
        """Claim a private capacity-only preflight for one exact settled Acceptance."""
        from core.comfy_output_containment import AcceptedProtectedOutputBatch
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization

        if (not self._profile_a
                or type(observation) is not GenerationWorkerProtectedAcceptanceObservation
                or observation.status != "protected_image_batch_accepted_non_authoritative"):
            return None, "protected_promotion_preflight_unavailable"
        with lifecycle._lock:
            writer = self._profile_a_writer_owner
            capacity = self._capacity_owner
            if (type(writer) is not WindowsProtectedAssetsCharacterization
                    or type(capacity) is not WindowsProtectedStorageAdmissionCharacterization):
                return None, "protected_promotion_preflight_unavailable"
            with writer._lock:
                with capacity._lock:
                    with self._lock:
                        attempt = self._storage_preadmission_attempts.get(observation.request_index)
                        if (lifecycle._worker_storage_integration is not self
                                or lifecycle._state != "bound_non_executing"
                                or lifecycle._generation != self._lifecycle_generation
                                or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                                or not self._root_binding_matches()
                                or self._state != "bound_non_executing"
                                or attempt is None or attempt.state != "pre_admitted"
                                or attempt.cancel_requested
                                or attempt.evidence_state != "evidence_published"
                                or attempt.writer_handoff_state != "staged_non_authoritative"
                                or attempt.acceptance_state != "accepted_non_authoritative"
                                or attempt.acceptance_observation is not observation
                                or attempt.writer_observation is None
                                or attempt.writer_owner is not writer
                                or attempt.acceptance_owner is None
                                or attempt.accepted_batch is None
                                or attempt.promotion_preflight_state != "not_started"
                                or attempt.promotion_capacity_operation is not None
                                or attempt.promotion_capacity_reservation is not None):
                            return None, "protected_promotion_preflight_evidence_unavailable"
                        from core.comfy_output_containment import ProtectedOutputAcceptanceCharacterization
                        accepted = attempt.accepted_batch
                        acceptance_owner = attempt.acceptance_owner
                        remote, prepared = attempt.remote_receipt, attempt.prepared
                        observations = attempt.acceptance_observations
                        if (type(acceptance_owner) is not ProtectedOutputAcceptanceCharacterization
                                or type(accepted) is not AcceptedProtectedOutputBatch
                                or acceptance_owner._protected_owner is not writer
                                or acceptance_owner._receipt is not accepted
                                or accepted._protected_owner is not writer
                                or accepted._envelope is not lifecycle._envelope
                                or accepted._prepared is not prepared
                                or accepted._remote is not remote
                                or accepted._batch_receipt.observations is not observations
                                or accepted.image_count != observation.accepted_image_count
                                or not 1 <= observation.accepted_image_count <= _MAX_WRITER_IMAGES
                                or type(observations) is not tuple
                                or len(observations) != observation.accepted_image_count
                                or tuple(item.descriptor_identity for item in observations)
                                    != tuple(item.identity for item in remote.images)):
                            return None, "protected_promotion_preflight_evidence_unavailable"
                        key = (prepared.request_id, remote.identity)
                        binding = writer._profile_a_stream_batch_receipt_bindings.get(key)
                        if (writer._closed or writer._revoking or writer._invalid or writer._uncertain
                                or writer._stream_batch_acceptances.get(key) is not accepted
                                or type(binding) is not tuple or len(binding) != 10
                                or binding[0] is not self or binding[1] is not attempt
                                or binding[2] is not attempt.acceptance_marker
                                or binding[3] is not attempt.evidence
                                or binding[4] is not capacity
                                or binding[5] is not attempt.capacity_operation
                                or binding[6] is not attempt.reservation
                                or binding[7] is not attempt.writer_admission
                                or binding[8] is not observations
                                or binding[9] is not attempt.acceptance_host_freshness
                                or capacity._closed or capacity._invalid
                                or capacity._scope_lease is None
                                or capacity._scope_lease._state != "held"):
                            return None, "protected_promotion_preflight_evidence_unavailable"
                        with acceptance_owner._lock:
                            if (acceptance_owner._closed or acceptance_owner._revoking
                                    or acceptance_owner._invalid or acceptance_owner._uncertain
                                    or acceptance_owner._busy or acceptance_owner._receipt is not accepted):
                                return None, "protected_promotion_preflight_acceptance_unavailable"
                        marker = object()
                        attempt.promotion_preflight_state = "in_progress"
                        attempt.promotion_preflight_marker = marker
                        return (attempt, marker, attempt.evidence, attempt.writer_observation,
                                observation, writer, capacity, lifecycle._envelope,
                                prepared, remote, acceptance_owner, accepted, observations), (
                                    "promotion_preflight_claimed"
                                )

    def _begin_profile_a_promotion_writer_locked(self, lifecycle, observation):
        """Consume one exact reserved preflight for the original-Host Writer.

        This is only an in-memory one-shot claim. Native readiness and all file
        operations happen after the Host gate and owner locks are released.
        """
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization

        if (not self._profile_a
                or type(observation) is not GenerationWorkerProtectedPromotionPreflightObservation
                or observation.status != "protected_promotion_preflight_non_authoritative"
                or observation._issuer is not self):
            return None, "protected_promotion_preflight_evidence_unavailable"
        writer, capacity = self._profile_a_writer_owner, self._capacity_owner
        if (type(writer) is not WindowsProtectedAssetsCharacterization
                or type(capacity) is not WindowsProtectedStorageAdmissionCharacterization):
            return None, "protected_promotion_preflight_evidence_unavailable"
        with lifecycle._lock:
            with writer._lock:
                with capacity._lock:
                    with self._lock:
                        attempt = self._storage_preadmission_attempts.get(observation.request_index)
                        if (lifecycle._worker_storage_integration is not self
                                or lifecycle._state != "bound_non_executing"
                                or lifecycle._generation != self._lifecycle_generation
                                or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                                or not self._root_binding_matches()
                                or self._state != "bound_non_executing"
                                or attempt is None or attempt.state != "pre_admitted"
                                or attempt.cancel_requested
                                or attempt.acceptance_state != "accepted_non_authoritative"
                                or attempt.promotion_preflight_state != "reserved_non_authoritative"
                                or attempt.promotion_preflight_observation is not observation
                                or attempt.promotion_writer_marker is not None
                                or attempt.promotion_write_admission is not None
                                or attempt.promotion_owner is not None
                                or attempt.promotion_receipt is not None
                                or attempt.promotion_create_attempt_count != 0
                                or attempt.promotion_create_descriptor_identities != ()
                                or attempt.promotion_capacity_operation is None
                                or attempt.promotion_capacity_reservation is None
                                or attempt.promotion_capacity_estimate is None):
                            return None, "protected_promotion_preflight_evidence_unavailable"
                        accepted_observation = attempt.acceptance_observation
                        marker = attempt.promotion_preflight_marker
                        evidence = attempt.evidence
                        writer_observation = attempt.writer_observation
                        operation = attempt.promotion_capacity_operation
                        reservation = attempt.promotion_capacity_reservation
                        estimate = attempt.promotion_capacity_estimate

        # The shared predicate reacquires lifecycle, capacity and integration
        # locks itself. Run it with none of those non-reentrant locks held.
        if (marker is None or not self._profile_a_promotion_preflight_matches_locked(
                lifecycle, attempt, marker, evidence,
                writer_observation, accepted_observation, writer,
                operation=operation, reservation=reservation,
                estimate=estimate,
                expected_states=("reserved_non_authoritative",),
                promotion_observation=observation)):
            return None, "protected_promotion_preflight_host_changed"

        with lifecycle._lock:
            with writer._lock:
                with capacity._lock:
                    with self._lock:
                        if (self._storage_preadmission_attempts.get(
                                observation.request_index) is not attempt
                                or lifecycle._worker_storage_integration is not self
                                or lifecycle._state != "bound_non_executing"
                                or self._state != "bound_non_executing"
                                or attempt.state != "pre_admitted"
                                or attempt.cancel_requested
                                or attempt.promotion_preflight_state != "reserved_non_authoritative"
                                or attempt.promotion_preflight_observation is not observation
                                or attempt.promotion_preflight_marker is not marker
                                or attempt.promotion_capacity_operation is not operation
                                or attempt.promotion_capacity_reservation is not reservation
                                or attempt.promotion_capacity_estimate is not estimate
                                or attempt.acceptance_observation is not accepted_observation):
                            return None, "protected_promotion_preflight_host_changed"
                        writer_marker = object()
                        attempt.promotion_writer_marker = writer_marker
                        attempt.promotion_preflight_state = "promotion_claiming"
                        return (
                            attempt, writer_marker, marker, evidence,
                            writer_observation, accepted_observation, writer,
                            capacity, operation, reservation, estimate,
                            attempt.acceptance_owner, attempt.accepted_batch,
                            attempt.acceptance_observations, lifecycle._envelope,
                            attempt.prepared, attempt.remote_receipt,
                        ), "promotion_writer_claimed"

    def _profile_a_promotion_writer_matches_locked(
            self, lifecycle, attempt, writer_marker, preflight_marker, evidence,
            writer_observation, acceptance_observation, promotion_observation,
            writer_owner, capacity_owner, operation, reservation, estimate,
            *, write_admission=None, promotion_owner=None,
            expected_states=("promotion_claiming", "promotion_admitting",
                             "promotion_admitted", "promotion_may_have_created")):
        """Check the exact Host/preflight/source chain at a Writer boundary."""
        if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                or attempt.promotion_writer_marker is not writer_marker
                or attempt.promotion_preflight_marker is not preflight_marker
                or attempt.promotion_preflight_observation is not promotion_observation
                or attempt.promotion_capacity_operation is not operation
                or attempt.promotion_capacity_reservation is not reservation
                or attempt.promotion_capacity_estimate is not estimate
                or attempt.promotion_write_admission is not write_admission
                or self._capacity_owner is not capacity_owner
                or self._profile_a_writer_owner is not writer_owner):
            return False
        return self._profile_a_promotion_preflight_matches_locked(
            lifecycle, attempt, preflight_marker, evidence, writer_observation,
            acceptance_observation, writer_owner, operation=operation,
            reservation=reservation, estimate=estimate,
            expected_states=expected_states,
            promotion_observation=promotion_observation,
            write_admission=write_admission, promotion_owner=promotion_owner,
        )

    def _mark_profile_a_promotion_create_for_characterization(
            self, lifecycle, attempt, writer_marker, preflight_marker, evidence,
            writer_observation, acceptance_observation, promotion_observation,
            writer_owner, capacity_owner, operation, reservation, estimate,
            write_admission, promotion_owner, descriptor, request_order):
        """Linearize one possible CREATE_NEW under current original-Host custody."""
        from core.comfy_output_containment import AcceptedProtectedOutputBatch
        from core.comfy_remote_output_receipts import RemoteImageDescriptor
        states = ("promotion_admitted", "promotion_may_have_created")
        if (type(descriptor) is not RemoteImageDescriptor
                or type(request_order) is not int or request_order < 0):
            return False

        # Revalidate every potentially expensive or cross-owner observation
        # while the original Host gate is held but before taking the short
        # native-owner/integration locks below. The Host gate prevents a
        # Project, Claim or route replacement between this check and marker
        # publication.
        if not self._profile_a_promotion_writer_matches_locked(
                lifecycle, attempt, writer_marker, preflight_marker,
                evidence, writer_observation, acceptance_observation,
                promotion_observation, writer_owner, capacity_owner,
                operation, reservation, estimate,
                write_admission=write_admission,
                promotion_owner=promotion_owner,
                expected_states=states):
            return False

        # Lock order remains lifecycle -> protected assets -> capacity ->
        # integration. Do not invoke the freshness predicate while these
        # locks are held: it reopens the earlier owner chain.
        with lifecycle._lock:
            with writer_owner._lock:
                with capacity_owner._lock:
                    ledger = capacity_owner._ledger
                    with ledger._lock:
                        active_reservation = ledger._reservations.get(reservation)
                        active_operation = ledger._operations.get(operation)
                        write_live = bool(
                            not capacity_owner._closed and not capacity_owner._invalid
                            and capacity_owner._scope_lease is not None
                            and capacity_owner._scope_lease._state == "held"
                            and ledger._active_write is write_admission
                            and active_reservation is not None
                            and active_reservation.get("operation") is operation
                            and active_reservation.get("state") == "writing"
                            and active_reservation.get("write") is write_admission
                            and active_operation is not None
                            and active_operation.get("state") == "writing"
                        )
                    if (not write_live
                            or lifecycle._worker_storage_integration is not self
                            or lifecycle._state != "bound_non_executing"
                            or self._state != "bound_non_executing"
                            or writer_owner._closed or writer_owner._revoking
                            or writer_owner._invalid or writer_owner._uncertain
                            or attempt.writer_owner is not writer_owner
                            or type(attempt.accepted_batch) is not AcceptedProtectedOutputBatch
                            or attempt.accepted_batch._protected_owner is not writer_owner
                            or attempt.accepted_batch._envelope is not lifecycle._envelope
                            or request_order != attempt.promotion_create_attempt_count
                            or request_order >= len(attempt.remote_receipt.images)
                            or attempt.remote_receipt.images[request_order] is not descriptor
                            or descriptor.identity in attempt.promotion_create_descriptor_identities):
                        return False
                    with self._lock:
                        if (self._storage_preadmission_attempts.get(
                                attempt.lease.request_index) is not attempt
                                or attempt.promotion_preflight_state not in states
                                or attempt.promotion_writer_marker is not writer_marker
                                or attempt.promotion_preflight_marker is not preflight_marker
                                or attempt.promotion_preflight_observation is not promotion_observation
                                or attempt.promotion_write_admission is not write_admission
                                or attempt.promotion_owner is not promotion_owner
                                or attempt.cancel_requested
                                or attempt.promotion_create_attempt_count != request_order
                                or descriptor.identity in attempt.promotion_create_descriptor_identities):
                            return False
                        attempt.promotion_create_attempt_count += 1
                        attempt.promotion_create_descriptor_identities = (
                            attempt.promotion_create_descriptor_identities + (descriptor.identity,)
                        )
                        attempt.promotion_preflight_state = "promotion_may_have_created"
                        return True

    def _profile_a_promotion_private_commit_matches_locked(
            self, attempt, writer_marker, preflight_marker, promotion_observation,
            writer_owner, capacity_owner, operation, reservation, estimate,
            write_admission, promotion_owner, receipt):
        """Cheap in-memory gate called while this integration lock is held."""
        descriptors = tuple(attempt.remote_receipt.images) if attempt.remote_receipt is not None else ()
        return bool(
            self._storage_preadmission_attempts.get(attempt.lease.request_index) is attempt
            and self._profile_a is True
            and self._state == "bound_non_executing"
            and attempt.state == "pre_admitted"
            and not attempt.cancel_requested
            and attempt.promotion_preflight_state == "promotion_may_have_created"
            and attempt.promotion_writer_marker is writer_marker
            and attempt.promotion_preflight_marker is preflight_marker
            and attempt.promotion_preflight_observation is promotion_observation
            and attempt.promotion_capacity_operation is operation
            and attempt.promotion_capacity_reservation is reservation
            and attempt.promotion_capacity_estimate is estimate
            and attempt.promotion_write_admission is write_admission
            and attempt.promotion_create_attempt_count == len(descriptors)
            and attempt.promotion_create_descriptor_identities == tuple(
                descriptor.identity for descriptor in descriptors)
            and attempt.writer_owner is writer_owner
            and self._profile_a_writer_owner is writer_owner
            and self._capacity_owner is capacity_owner
            and attempt.promotion_owner is promotion_owner
            and attempt.promotion_host_binding is promotion_owner._profile_a_host_binding
            and attempt.promotion_receipt is None
            and promotion_owner._pending_receipt is receipt
            and promotion_owner._receipt is None
            and receipt._promotion_owner is promotion_owner
            and receipt._protected_owner is writer_owner
            and receipt._acceptance_owner is attempt.acceptance_owner
            and receipt._accepted is attempt.accepted_batch
        )

    def _profile_a_promotion_publication_host_matches_locked(
            self, lifecycle, attempt, marker, preflight_observation,
            writer_marker, preflight_marker, evidence, writer_observation,
            acceptance_observation, writer_owner, capacity_owner, operation,
            reservation, estimate, write_admission, promotion_owner, receipt, *,
            settled_publication=False, published_observation=None):
        """Check the current Host/Claim/Worker side of a claimed publication.

        Native roots, files and ledger inventory are deliberately verified by
        the slow publication path outside the Host locks. This helper is the
        short freshness callback used between those observations and again at
        the final Host commit boundary.
        """
        from core.generation_windows_protected_promotion import _ProfileAHostPromotionBinding

        expected_preflight_state = ("promoted_non_authoritative" if settled_publication
                                    else "private_committed_host_publication_pending")
        expected_publication_state = ("published_non_authoritative" if settled_publication
                                      else "in_progress")

        if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                or self._profile_a is not True
                or self._state != "bound_non_executing"
                or lifecycle._worker_storage_integration is not self
                or lifecycle._state != "bound_non_executing"
                or lifecycle._generation != self._lifecycle_generation
                or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                or not self._root_binding_matches()
                or attempt.state != "pre_admitted"
                or attempt.cancel_requested
                or attempt.promotion_preflight_state != expected_preflight_state
                or attempt.promotion_publication_state != expected_publication_state
                or attempt.promotion_publication_marker is not marker
                or (settled_publication
                    and attempt.promotion_publication_observation is not published_observation)
                or attempt.promotion_preflight_observation is not preflight_observation
                or attempt.promotion_preflight_marker is not preflight_marker
                or attempt.promotion_writer_marker is not writer_marker
                or attempt.evidence is not evidence
                or evidence._issuer is not self
                or evidence._attempt_nonce != attempt.lease.nonce
                or attempt.writer_observation is not writer_observation
                or attempt.acceptance_observation is not acceptance_observation
                or attempt.writer_owner is not writer_owner
                or self._profile_a_writer_owner is not writer_owner
                or self._capacity_owner is not capacity_owner
                or attempt.promotion_capacity_operation is not operation
                or attempt.promotion_capacity_reservation is not reservation
                or attempt.promotion_capacity_estimate is not estimate
                or attempt.promotion_write_admission is not write_admission
                or attempt.promotion_owner is not promotion_owner
                or attempt.promotion_receipt is not receipt
                or type(attempt.promotion_host_binding) is not _ProfileAHostPromotionBinding
                or attempt.promotion_host_binding is not promotion_owner._profile_a_host_binding
                or attempt.acceptance_state != "accepted_non_authoritative"
                or attempt.acceptance_observation is not acceptance_observation
                or attempt.writer_handoff_state != "staged_non_authoritative"
                or attempt.promotion_create_attempt_count != len(attempt.remote_receipt.images)
                or attempt.promotion_create_descriptor_identities != tuple(
                    descriptor.identity for descriptor in attempt.remote_receipt.images)):
            return False
        binding = attempt.promotion_host_binding
        if (binding.integration is not self or binding.attempt is not attempt
                or binding.envelope is not lifecycle._envelope
                or binding.writer_owner is not writer_owner
                or binding.capacity_owner is not capacity_owner
                or binding.operation is not operation
                or binding.reservation is not reservation
                or binding.estimate is not estimate
                or binding.write_admission is not write_admission
                or binding.preflight_observation is not preflight_observation):
            return False
        history, remote, prepared = (
            attempt.history_completion, attempt.remote_receipt, attempt.prepared,
        )
        if (history is None or remote is None or prepared is None
                or attempt.accepted_prompt_id != remote.prompt_id
                or remote.execution_succeeded is not True
                or getattr(history, "kind", None) != "history"
                or getattr(getattr(history, "outcome", None), "status", None) != "ready"
                or getattr(getattr(history, "outcome", None), "history_json", None)
                    != attempt.history_json
                or attempt.history_json != remote._validated_history_json):
            return False
        try:
            if self._worker._run_if_issued_completion_for_prepared_request_for_characterization(
                    history, prepared, self._worker_owner_claim, lambda: True) is not True:
                return False
        except Exception:
            return False
        return True

    def _profile_a_candidate_admission_host_matches_locked(
            self, lifecycle, captured):
        """Check settled Profile A Promotion plus the exact claimed preflight."""
        attempt = captured["attempt"]
        runtime = captured["runtime"]
        origin = captured["publication_origin"]
        project = captured["project"]
        if (attempt.candidate_admission_state != "in_progress"
                or attempt.candidate_admission_marker is not captured["marker"]
                or attempt.promotion_publication_observation
                    is not captured["promotion_observation"]
                or lifecycle._runtime_ref() is not runtime
                or runtime._generation_publication_origin is not origin
                or origin.envelope is not captured["envelope"]
                or origin.project is not project
                or origin.path != lifecycle._project_path
                or origin.source_snapshot is not captured["source_snapshot"]
                or lifecycle._project_ref() is not project):
            return False
        try:
            if origin.project != origin.source_snapshot:
                return False
        except Exception:
            return False
        if not self._profile_a_promotion_publication_host_matches_locked(
            lifecycle, attempt, captured["promotion_marker"],
            captured["preflight_observation"], captured["writer_marker"],
            captured["preflight_marker"], captured["evidence"],
            captured["writer_observation"], captured["acceptance_observation"],
            captured["writer"], captured["capacity"], captured["operation"],
            captured["reservation"], captured["estimate"], captured["write"],
            captured["promotion_owner"], captured["receipt"],
            settled_publication=True,
            published_observation=captured["promotion_observation"],
        ):
            return False
        try:
            envelope = captured["envelope"]
            index = attempt.lease.request_index
            request = envelope.manifest.requests[index]
            prepared, remote, receipt = (
                captured["prepared"], captured["remote"], captured["receipt"],
            )
            descriptors = tuple(remote.images)
            rows = tuple(receipt.images)
            sources = tuple(captured["observations"])
            return bool(
                1 <= len(descriptors) <= _MAX_WRITER_IMAGES
                and prepared.request_index == index
                and (prepared.request_id, prepared.workflow_identity)
                    == (request.request_id, request.workflow_identity)
                and (remote.job_id, remote.claim_id, remote.manifest_identity,
                     remote.request_id, remote.request_index, remote.workflow_identity)
                    == (envelope.job_id, envelope.claim_id,
                        envelope.manifest.manifest_identity, request.request_id,
                        index, request.workflow_identity)
                and (receipt.job_id, receipt.claim_id, receipt.manifest_identity,
                     receipt.request_id, receipt.request_index, receipt.workflow_identity,
                     receipt.prompt_id, receipt.remote_receipt_identity)
                    == (envelope.job_id, envelope.claim_id,
                        envelope.manifest.manifest_identity, request.request_id,
                        index, request.workflow_identity, remote.prompt_id, remote.identity)
                and captured["promotion_observation"].request_index == index
                and captured["promotion_observation"].promoted_image_count == len(rows)
                and tuple(item.identity for item in descriptors)
                    == tuple(item.descriptor_identity for item in sources)
                and tuple(item.identity for item in descriptors)
                    == tuple(row.descriptor_identity for row in rows)
            )
        except Exception:
            return False

    def _profile_a_outputs_ready_host_matches_locked(self, lifecycle, captured):
        """Recheck a claimed 19G-E locator against the live Host and Promotion."""
        from ui.agent_generation_executor_handoff import GenerationPublicationOrigin

        attempt = captured["attempt"]
        marker = captured["marker"]
        runtime = captured["runtime"]
        origin = captured["publication_origin"]
        project = captured["project"]
        if (type(origin) is not GenerationPublicationOrigin
                or lifecycle._runtime_ref() is not runtime
                or runtime._generation_publication_origin is not origin
                or origin.envelope is not captured["envelope"]
                or origin.project is not project
                or origin.path != lifecycle._project_path
                or origin.source_snapshot is not captured["source_snapshot"]
                or lifecycle._project_ref() is not project
                or marker.state not in {"claim_in_progress", "event_acceptance_in_progress"}
                or self._profile_a_outputs_ready_event_attempts.get(
                    attempt.lease.request_index,
                ) is not marker):
            return False
        if not self._profile_a_promotion_publication_host_matches_locked(
                lifecycle, captured["attempt"], captured["promotion_marker"],
                captured["preflight_observation"], captured["writer_marker"],
                captured["preflight_marker"], captured["evidence"],
                captured["writer_observation"], captured["acceptance_observation"],
                captured["writer"], captured["capacity"], captured["operation"],
                captured["reservation"], captured["estimate"], captured["write"],
                captured["promotion_owner"], captured["receipt"],
                settled_publication=True,
                published_observation=captured["promotion_observation"],
        ):
            return False
        index = attempt.lease.request_index
        try:
            request = captured["envelope"].manifest.requests[index]
            prepared = captured["prepared"]
            remote = captured["remote"]
            receipt = captured["receipt"]
            descriptors = tuple(remote.images)
            rows = tuple(receipt.images)
            sources = tuple(captured["observations"])
            return bool(
                self._profile_a_remote_outputs_ready_event_is_current_locked(
                    lifecycle, attempt, captured["remote_marker"],
                )
                and 1 <= len(descriptors) <= _MAX_WRITER_IMAGES
                and prepared.request_index == index
                and (prepared.request_id, prepared.workflow_identity)
                    == (request.request_id, request.workflow_identity)
                and (remote.job_id, remote.claim_id, remote.manifest_identity,
                     remote.request_id, remote.request_index, remote.workflow_identity)
                    == (captured["envelope"].job_id, captured["envelope"].claim_id,
                        captured["envelope"].manifest.manifest_identity,
                        request.request_id, index, request.workflow_identity)
                and (receipt.job_id, receipt.claim_id, receipt.manifest_identity,
                     receipt.request_id, receipt.request_index, receipt.workflow_identity,
                     receipt.prompt_id, receipt.remote_receipt_identity)
                    == (captured["envelope"].job_id, captured["envelope"].claim_id,
                        captured["envelope"].manifest.manifest_identity,
                        request.request_id, index, request.workflow_identity,
                        remote.prompt_id, remote.identity)
                and receipt._promotion_owner is captured["promotion_owner"]
                and receipt._protected_owner is captured["writer"]
                and receipt._acceptance_owner is captured["acceptance"]
                and receipt._accepted is captured["accepted"]
                and captured["promotion_observation"].request_index == index
                and captured["promotion_observation"].promoted_image_count == len(rows)
                and tuple(item.identity for item in descriptors)
                    == tuple(item.descriptor_identity for item in sources)
                and tuple(item.identity for item in descriptors)
                    == tuple(row.descriptor_identity for row in rows)
                and tuple(row.source_observation for row in rows) == sources
            )
        except Exception:
            return False

    def _begin_profile_a_protected_candidate_admission_locked(self, lifecycle, locator):
        """Claim the separate G-F admission bridge for one accepted 19G-E event."""
        from core.generation_storage_admission import (
            WindowsProtectedStorageAdmissionCharacterization,
        )
        from core.comfy_output_containment import ProtectedOutputAcceptanceCharacterization
        from core.comfy_remote_output_receipts import RemoteOutputReceipt
        from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization
        from core.generation_windows_protected_promotion import (
            ProtectedDurablePromotionCharacterization,
            VerifiedProtectedPromotionReceipt,
        )
        from ui.agent_generation_executor_handoff import GenerationPublicationOrigin

        if (type(locator) is not GenerationWorkerProtectedOutputsReadyObservation
                or locator.status != "protected_outputs_ready_event_accepted_non_authoritative"
                or locator.candidate_eligibility != "not_established"
                or locator.execution_available is not False
                or locator.protected_storage_available is not False
                or locator.promotion_available is not False
                or locator.candidate_publication_allowed is not False
                or locator.project_save_allowed is not False
                or locator.authorship != "unverified"
                or type(locator.request_index) is not int):
            return None, "protected_candidate_admission_locator_invalid"
        index = locator.request_index
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._worker_storage_integration is not self
                    or not self._profile_a
                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)):
                return None, "protected_candidate_admission_host_changed"
            runtime = lifecycle._runtime_ref()
            origin = getattr(runtime, "_generation_publication_origin", None)
            project = lifecycle._project_ref()
            if (runtime is None or type(origin) is not GenerationPublicationOrigin
                    or origin.envelope is not lifecycle._envelope
                    or origin.project is not project
                    or origin.path != lifecycle._project_path
                    or origin.source_snapshot is None
                    or runtime._generation_host_state is None):
                return None, "protected_candidate_admission_host_changed"
            attempt = self._storage_preadmission_attempts.get(index)
            remote_marker = self._profile_a_remote_outputs_ready_event_attempts.get(index)
            outputs_marker = self._profile_a_outputs_ready_event_attempts.get(index)
            if (attempt is None or remote_marker is None or outputs_marker is None
                    or attempt.promotion_publication_state != "published_non_authoritative"
                    or attempt.promotion_preflight_state != "promoted_non_authoritative"
                    or attempt.cancel_requested
                    or outputs_marker.state != "events_accepted"
                    or outputs_marker.observation is not locator
                    or not self._profile_a_remote_outputs_ready_event_is_current_locked(
                        lifecycle, attempt, remote_marker, outputs_marker=outputs_marker,
                    )):
                return None, "protected_candidate_admission_evidence_unavailable"

            writer, capacity = self._profile_a_writer_owner, self._capacity_owner
            acceptance, promoter = attempt.acceptance_owner, attempt.promotion_owner
            receipt, remote = attempt.promotion_receipt, attempt.remote_receipt
            if (type(writer) is not WindowsProtectedAssetsCharacterization
                    or type(capacity) is not WindowsProtectedStorageAdmissionCharacterization
                    or type(acceptance) is not ProtectedOutputAcceptanceCharacterization
                    or type(promoter) is not ProtectedDurablePromotionCharacterization
                    or type(receipt) is not VerifiedProtectedPromotionReceipt
                    or type(remote) is not RemoteOutputReceipt):
                return None, "protected_candidate_admission_evidence_unavailable"

            # The later Admission owner is the only authority for protected
            # native checks. Claim this independent one-shot marker without
            # taking protected-owner locks while Job/Inbox custody is held.
            with self._lock:
                state = attempt.protected_candidate_admission_state
                if state != "not_started":
                    if state == "in_progress":
                        return None, "protected_candidate_admission_in_progress"
                    if state == "observed":
                        return None, "protected_candidate_admission_already_observed"
                    if state == "retained_uncertain":
                        return None, "protected_candidate_admission_uncertain"
                    return None, "protected_candidate_admission_evidence_unavailable"
                if (self._storage_preadmission_attempts.get(index) is not attempt
                        or self._profile_a_outputs_ready_event_attempts.get(index)
                            is not outputs_marker
                        or attempt.protected_candidate_admission_marker is not None
                        or attempt.protected_candidate_admission_owner is not None
                        or attempt.protected_candidate_admission_result is not None
                        or attempt.protected_candidate_admission_observation is not None
                        or locator.output_count != len(remote.images)
                        or not 1 <= len(remote.images) <= _MAX_WRITER_IMAGES
                        or len(receipt.images) != len(remote.images)
                        or tuple(item.identity for item in remote.images)
                            != tuple(row.descriptor_identity for row in receipt.images)
                        or len(attempt.acceptance_observations) != len(receipt.images)
                        or any(row.source_observation is not source
                               for row, source in zip(
                                   receipt.images, attempt.acceptance_observations,
                               ))
                        or runtime._generation_original_host_lifecycle is not lifecycle
                        or runtime._generation_publication_origin is not origin
                        or lifecycle._job_id != lifecycle._envelope.job_id
                        or lifecycle._claim_id != lifecycle._envelope.claim_id
                        or lifecycle._manifest_identity
                            != lifecycle._envelope.manifest.manifest_identity
                        or lifecycle._pairing_generation
                            != lifecycle._envelope.binding.pairing_generation):
                    return None, "protected_candidate_admission_evidence_unavailable"
                inbox = lifecycle._inbox
                if (inbox._late_output_seen
                        or any(
                            getattr(item, "job_id", None) == lifecycle._job_id
                            and getattr(item, "claim_id", None) == lifecycle._claim_id
                            and getattr(getattr(item, "progress", None), "request_index", None)
                                == index
                            and getattr(getattr(item, "progress", None), "kind", None)
                                in {"remote_outputs_ready", "outputs_ready"}
                            for item in inbox._late
                        )):
                    return None, "protected_candidate_admission_late_event"
                marker = object()
                attempt.protected_candidate_admission_state = "in_progress"
                attempt.protected_candidate_admission_marker = marker
                return {
                    "attempt": attempt,
                    "marker": marker,
                    "locator": locator,
                    "outputs_marker": outputs_marker,
                    "remote_marker": remote_marker,
                    "writer": writer,
                    "capacity": capacity,
                    "acceptance": acceptance,
                    "promotion_owner": promoter,
                    "receipt": receipt,
                    "remote": remote,
                    "prepared": attempt.prepared,
                    "accepted": attempt.accepted_batch,
                    "envelope": lifecycle._envelope,
                    "runtime": runtime,
                    "origin": origin,
                    "project": project,
                    "host_state": runtime._generation_host_state,
                    "project_reference": self._project_reference,
                    "pairing_generation": lifecycle._pairing_generation,
                }, "protected_candidate_admission_claimed"

    def _commit_profile_a_protected_candidate_admission_locked(
            self, lifecycle, captured, admission_owner, result, observation):
        """Publish only a count-only view after exact owner evidence is rechecked."""
        from ui.agent_generation_protected_candidate_admission import (
            ProtectedCandidateAdmissionObservation,
            ProtectedCandidateAdmissionResult,
        )

        attempt = captured["attempt"]
        index = attempt.lease.request_index
        owner_observation = getattr(result, "observation", None)
        if (type(result) is not ProtectedCandidateAdmissionResult
                or result.status != "evidence_observed"
                or result.request_index != index
                or type(owner_observation) is not ProtectedCandidateAdmissionObservation
                or observation.status != "protected_candidate_admission_evidence_observed"
                or observation.request_index != index
                or observation.verified_promoted_image_count != len(captured["receipt"].images)):
            return False
        runtime = captured["runtime"]
        origin = captured["origin"]
        marker = captured["marker"]
        outputs_marker = captured["outputs_marker"]
        remote_marker = captured["remote_marker"]
        if (owner_observation._runtime is not runtime
                or owner_observation._origin is not origin
                or owner_observation._envelope is not captured["envelope"]
                or owner_observation._project is not captured["project"]
                or owner_observation._promotion_owner is not captured["promotion_owner"]
                or owner_observation._promotion_receipt is not captured["receipt"]
                or owner_observation._remote_receipt is not captured["remote"]
                or owner_observation._remote_event is not remote_marker.event
                or owner_observation._outputs_ready_event is not outputs_marker.event):
            return False

        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._worker_storage_integration is not self
                    or lifecycle._runtime_ref() is not runtime
                    or runtime._generation_original_host_lifecycle is not lifecycle
                    or runtime._generation_publication_origin is not origin
                    or runtime._generation_host_state is not captured["host_state"]
                    or lifecycle._project_ref() is not captured["project"]
                    or lifecycle._project_path != origin.path
                    or lifecycle._envelope is not captured["envelope"]
                    or lifecycle._pairing_generation != captured["pairing_generation"]
                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)):
                return False
            with self._lock:
                if (self._storage_preadmission_attempts.get(index) is not attempt
                        or attempt.protected_candidate_admission_state != "in_progress"
                        or attempt.protected_candidate_admission_marker is not marker
                        or attempt.protected_candidate_admission_owner is not admission_owner
                        or attempt.protected_candidate_admission_result is not result
                        or attempt.protected_candidate_admission_observation is not None
                        or runtime._generation_protected_candidate_admission is not admission_owner
                        or admission_owner._runtime is not runtime
                        or admission_owner._state is not captured["host_state"]
                        or admission_owner._origin is not origin
                        or admission_owner._envelope is not captured["envelope"]
                        or admission_owner._closed
                        or lifecycle._inbox._late_output_seen
                        or any(
                            getattr(item, "job_id", None) == lifecycle._job_id
                            and getattr(item, "claim_id", None) == lifecycle._claim_id
                            and getattr(getattr(item, "progress", None), "request_index", None)
                                == index
                            and getattr(getattr(item, "progress", None), "kind", None)
                                in {"remote_outputs_ready", "outputs_ready"}
                            for item in lifecycle._inbox._late
                        )
                        or outputs_marker.observation is not captured["locator"]
                        or outputs_marker.state != "events_accepted"
                        or not self._profile_a_remote_outputs_ready_event_is_current_locked(
                            lifecycle, attempt, remote_marker, outputs_marker=outputs_marker,
                        )):
                    return False
                attempt.protected_candidate_admission_observation = observation
                attempt.protected_candidate_admission_state = "observed"
                return True

    def _retain_profile_a_protected_candidate_admission_uncertain(
            self, captured, *, admission_owner=None, result=None, mark_uncertain=True):
        """Retain exact private evidence when post-native Host publication is uncertain."""
        attempt = captured.get("attempt") if type(captured) is dict else None
        marker = captured.get("marker") if type(captured) is dict else None
        if attempt is None or marker is None:
            return
        index = attempt.lease.request_index
        with self._lock:
            if (self._storage_preadmission_attempts.get(index) is not attempt
                    or attempt.protected_candidate_admission_marker is not marker):
                return
            if admission_owner is not None:
                attempt.protected_candidate_admission_owner = admission_owner
            if result is not None:
                attempt.protected_candidate_admission_result = result
            if (mark_uncertain is True
                    and attempt.protected_candidate_admission_state == "in_progress"):
                attempt.protected_candidate_admission_state = "retained_uncertain"

    def _profile_a_candidate_publication_replay(self, locator):
        """Return only an exact historical count or a bounded one-shot refusal."""
        from ui.agent_generation_protected_candidate_admission import (
            GenerationProtectedCandidateAdmission,
        )

        if type(locator) is not GenerationWorkerProtectedCandidateAdmissionObservation:
            return None, "protected_candidate_publication_locator_invalid"
        index = locator.request_index
        with self._lock:
            attempt = self._storage_preadmission_attempts.get(index)
            if (attempt is None
                    or attempt.protected_candidate_admission_observation is not locator):
                # No already-consumed publication exists. The caller still
                # needs to pass the normal exact Host/event begin boundary.
                return None, None
            state = attempt.protected_candidate_publication_state
            if state == "not_started":
                return None, None
            if attempt.protected_candidate_publication_locator is not locator:
                return None, "protected_candidate_publication_evidence_unavailable"
            if state == "in_progress":
                return None, "protected_candidate_publication_in_progress"
            if state == "retained_uncertain":
                return attempt.protected_candidate_publication_observation, (
                    "protected_candidate_publication_uncertain"
                )
            if state == "observed":
                result = attempt.protected_candidate_publication_observation
                if (type(result) is not GenerationWorkerProtectedCandidatePublicationObservation
                        or attempt.protected_candidate_publication_owner is None
                        or attempt.protected_candidate_publication_receipt is None):
                    return None, "protected_candidate_publication_uncertain"
                return result, "protected_candidate_publication_already_observed"
            return None, "protected_candidate_publication_evidence_unavailable"

    def _begin_profile_a_candidate_publication_locked(self, lifecycle, locator):
        """Claim one exact G-F locator while original Host/Job/Inbox gates are held."""
        from core.comfy_remote_output_receipts import RemoteOutputReceipt
        from core.generation_windows_protected_promotion import VerifiedProtectedPromotionReceipt
        from ui.agent_generation_candidate_publication import GenerationCandidatePublication
        from ui.agent_generation_protected_candidate_admission import (
            GenerationProtectedCandidateAdmission,
            ProtectedCandidateAdmissionObservation,
            ProtectedCandidateAdmissionResult,
        )
        from ui.agent_generation_executor_handoff import GenerationPublicationOrigin

        if (type(locator) is not GenerationWorkerProtectedCandidateAdmissionObservation
                or locator.status != "protected_candidate_admission_evidence_observed"
                or locator.candidate_eligibility != "evidence_observed"
                or locator.execution_available is not False
                or locator.protected_storage_available is not False
                or locator.promotion_available is not False
                or locator.candidate_publication_allowed is not False
                or locator.project_save_allowed is not False
                or locator.authorship != "unverified"
                or type(locator.request_index) is not int):
            return None, "protected_candidate_publication_locator_invalid"
        index = locator.request_index
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._worker_storage_integration is not self
                    or self._profile_a is not True
                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                    or not 0 <= index < lifecycle._request_count):
                return None, "protected_candidate_publication_host_changed"
            runtime = lifecycle._runtime_ref()
            origin = getattr(runtime, "_generation_publication_origin", None)
            project = lifecycle._project_ref()
            if (runtime is None or type(origin) is not GenerationPublicationOrigin
                    or origin.envelope is not lifecycle._envelope
                    or origin.project is not project or origin.path != lifecycle._project_path
                    or origin.source_snapshot is None
                    or runtime._generation_host_state is None
                    or runtime._generation_protected_candidate_admission is None):
                return None, "protected_candidate_publication_host_changed"

            attempt = self._storage_preadmission_attempts.get(index)
            remote_marker = self._profile_a_remote_outputs_ready_event_attempts.get(index)
            outputs_marker = self._profile_a_outputs_ready_event_attempts.get(index)
            if (attempt is None or remote_marker is None or outputs_marker is None
                    or attempt.protected_candidate_admission_state != "observed"
                    or attempt.protected_candidate_admission_observation is not locator
                    or outputs_marker.state != "events_accepted"
                    or outputs_marker.observation is None
                    or attempt.cancel_requested
                    or not self._profile_a_remote_outputs_ready_event_is_current_locked(
                        lifecycle, attempt, remote_marker, outputs_marker=outputs_marker,
                    )):
                return None, "protected_candidate_publication_evidence_unavailable"

            admission_owner = attempt.protected_candidate_admission_owner
            admission_result = attempt.protected_candidate_admission_result
            admission_observation = getattr(admission_result, "observation", None)
            remote = attempt.remote_receipt
            promotion_receipt = attempt.promotion_receipt
            if (type(admission_owner) is not GenerationProtectedCandidateAdmission
                    or runtime._generation_protected_candidate_admission is not admission_owner
                    or type(admission_result) is not ProtectedCandidateAdmissionResult
                    or admission_result.status != "evidence_observed"
                    or admission_result.request_index != index
                    or type(admission_observation) is not ProtectedCandidateAdmissionObservation
                    or admission_observation is None
                    or type(remote) is not RemoteOutputReceipt
                    or type(promotion_receipt) is not VerifiedProtectedPromotionReceipt):
                return None, "protected_candidate_publication_evidence_unavailable"

            descriptors = tuple(remote.images)
            promoted = tuple(promotion_receipt.images)
            if (not descriptors or len(descriptors) != locator.verified_promoted_image_count
                    or len(descriptors) != len(promoted)
                    or tuple(item.identity for item in descriptors)
                        != tuple(item.descriptor_identity for item in promoted)
                    or admission_observation._runtime is not runtime
                    or admission_observation._origin is not origin
                    or admission_observation._envelope is not lifecycle._envelope
                    or admission_observation._project is not project
                    or admission_observation._promotion_owner is not attempt.promotion_owner
                    or admission_observation._promotion_receipt is not promotion_receipt
                    or admission_observation._remote_receipt is not remote
                    or admission_observation._remote_event is not remote_marker.event
                    or admission_observation._outputs_ready_event is not outputs_marker.event):
                return None, "protected_candidate_publication_evidence_unavailable"

            publication_owner = runtime._generation_candidate_publication
            if (publication_owner is not None
                    and (type(publication_owner) is not GenerationCandidatePublication
                         or publication_owner._mode != "profile_a_protected"
                         or publication_owner._runtime is not runtime
                         or publication_owner._origin is not origin
                         or publication_owner._envelope is not lifecycle._envelope
                         or publication_owner._profile_a_capacity_owner is not self._capacity_owner
                         or publication_owner._profile_a_protected_owner is not attempt.writer_owner)):
                return None, "protected_candidate_publication_owner_conflict"

            with self._lock:
                state = attempt.protected_candidate_publication_state
                if state != "not_started":
                    if state == "in_progress":
                        return None, "protected_candidate_publication_in_progress"
                    if state == "observed":
                        if attempt.protected_candidate_publication_locator is locator:
                            return {
                                "historical": attempt.protected_candidate_publication_observation,
                            }, "protected_candidate_publication_already_observed"
                        return None, "protected_candidate_publication_evidence_unavailable"
                    return None, "protected_candidate_publication_uncertain"
                if (self._storage_preadmission_attempts.get(index) is not attempt
                        or attempt.protected_candidate_publication_marker is not None
                        or attempt.protected_candidate_publication_locator is not None
                        or attempt.protected_candidate_publication_owner is not None
                        or attempt.protected_candidate_publication_receipt is not None
                        or attempt.protected_candidate_publication_observation is not None
                        or attempt.protected_candidate_admission_observation is not locator
                        or runtime._generation_original_host_lifecycle is not lifecycle
                        or runtime._generation_publication_origin is not origin
                        or lifecycle._job_id != lifecycle._envelope.job_id
                        or lifecycle._claim_id != lifecycle._envelope.claim_id
                        or lifecycle._manifest_identity
                            != lifecycle._envelope.manifest.manifest_identity
                        or lifecycle._pairing_generation
                            != lifecycle._envelope.binding.pairing_generation
                        or lifecycle._inbox._late_output_seen):
                    return None, "protected_candidate_publication_evidence_unavailable"
                request = lifecycle._envelope.manifest.requests[index]
                if (attempt.prepared is None
                        or attempt.prepared.request_index != index
                        or attempt.prepared.request_id != request.request_id
                        or attempt.prepared.workflow_identity != request.workflow_identity
                        or remote.request_index != index
                        or remote.request_id != request.request_id
                        or remote.workflow_identity != request.workflow_identity
                        or promotion_receipt.request_index != index
                        or attempt.promotion_publication_state != "published_non_authoritative"
                        or attempt.promotion_preflight_state != "promoted_non_authoritative"):
                    return None, "protected_candidate_publication_evidence_unavailable"
                marker = object()
                attempt.protected_candidate_publication_state = "in_progress"
                attempt.protected_candidate_publication_marker = marker
                attempt.protected_candidate_publication_locator = locator
                return {
                    "attempt": attempt,
                    "marker": marker,
                    "locator": locator,
                    "admission_owner": admission_owner,
                    "admission_result": admission_result,
                    "admission_observation": admission_observation,
                    "remote": remote,
                    "promotion_receipt": promotion_receipt,
                    "publication_owner": publication_owner,
                    "lifecycle": lifecycle,
                    "runtime": runtime,
                    "origin": origin,
                    "project": project,
                    "host_state": runtime._generation_host_state,
                    "project_reference": self._project_reference,
                    "pairing_generation": lifecycle._pairing_generation,
                }, "protected_candidate_publication_claimed"

    def _profile_a_candidate_publication_claim_current_locked(self, lifecycle, captured):
        """Recheck the exact in-progress marker under original Host/Job/Inbox gates."""
        attempt = captured["attempt"]
        marker = captured["marker"]
        index = attempt.lease.request_index
        remote_marker = self._profile_a_remote_outputs_ready_event_attempts.get(index)
        outputs_marker = self._profile_a_outputs_ready_event_attempts.get(index)
        with lifecycle._lock:
            with self._lock:
                return bool(
                    lifecycle._state == "bound_non_executing"
                    and lifecycle._worker_storage_integration is self
                    and lifecycle._runtime_ref() is captured["runtime"]
                    and lifecycle._project_ref() is captured["project"]
                    and lifecycle._envelope is captured["origin"].envelope
                    and lifecycle._pairing_generation == captured["pairing_generation"]
                    and self._storage_preadmission_attempts.get(index) is attempt
                    and attempt.protected_candidate_publication_state == "in_progress"
                    and attempt.protected_candidate_publication_marker is marker
                    and attempt.protected_candidate_publication_locator is captured["locator"]
                    and attempt.protected_candidate_admission_owner is captured["admission_owner"]
                    and attempt.protected_candidate_admission_result is captured["admission_result"]
                    and attempt.protected_candidate_admission_observation is captured["locator"]
                    and outputs_marker is not None
                    and outputs_marker.state == "events_accepted"
                    and outputs_marker.observation is not None
                    and remote_marker is not None
                    and remote_marker.state == "events_accepted"
                    and self._profile_a_remote_outputs_ready_event_is_current_locked(
                        lifecycle, attempt, remote_marker, outputs_marker=outputs_marker,
                    ))

    def _complete_profile_a_candidate_publication(
            self, captured, publication_owner, receipt):
        """Retain the exact publisher receipt and publish only count-only evidence."""
        from ui.agent_generation_candidate_publication import (
            GenerationCandidatePublication, PublicationReceipt,
        )

        attempt = captured.get("attempt") if type(captured) is dict else None
        marker = captured.get("marker") if type(captured) is dict else None
        if attempt is None or marker is None:
            return None, "protected_candidate_publication_uncertain"
        index = attempt.lease.request_index
        expected = len(captured["remote"].images)
        if (type(publication_owner) is not GenerationCandidatePublication
                or publication_owner._mode != "profile_a_protected"
                or publication_owner._runtime is not captured["runtime"]
                or publication_owner._origin is not captured["origin"]
                or publication_owner._envelope is not captured["origin"].envelope
                or type(receipt) is not PublicationReceipt
                or receipt.request_index != index
                or type(receipt.registered_count) is not int
                or not 0 <= receipt.registered_count <= expected):
            receipt = None
        if receipt is not None:
            with publication_owner._lock:
                exact_record = (publication_owner._records.get(index) is receipt
                                and publication_owner._protected_evidence.get(index)
                                    == (captured["admission_owner"],
                                        captured["admission_observation"]))
            if not exact_record:
                receipt = None

        with self._lock:
            if (self._storage_preadmission_attempts.get(index) is not attempt
                    or attempt.protected_candidate_publication_marker is not marker
                    or attempt.protected_candidate_publication_locator is not captured["locator"]):
                return None, "protected_candidate_publication_uncertain"
            if publication_owner is not None:
                attempt.protected_candidate_publication_owner = publication_owner
            if receipt is not None:
                attempt.protected_candidate_publication_receipt = receipt

            prior_state = attempt.protected_candidate_publication_state
            if prior_state != "in_progress":
                # Close/revocation crossed a possible mutation. Preserve the
                # private exact result, but never convert uncertainty to success.
                attempt.protected_candidate_publication_state = "retained_uncertain"
                observation = GenerationWorkerProtectedCandidatePublicationObservation(
                    "protected_candidate_publication_uncertain", index,
                    receipt.registered_count if receipt is not None else 0,
                    expected, "registration_uncertain",
                )
                attempt.protected_candidate_publication_observation = observation
                return observation, "protected_candidate_publication_uncertain"

            if (receipt is not None and receipt.registration_state == "registered"
                    and receipt.registered_count == expected):
                status = "protected_candidate_publication_registered_non_authoritative"
                registration_state = "registered"
                attempt.protected_candidate_publication_state = "observed"
                outcome = "protected_candidate_publication_registered"
            elif (receipt is not None and receipt.registration_state == "registration_failed"
                    and receipt.registered_count == 0):
                status = "protected_candidate_publication_not_registered_non_authoritative"
                registration_state = "registration_failed"
                attempt.protected_candidate_publication_state = "observed"
                outcome = "protected_candidate_publication_not_registered"
            else:
                status = "protected_candidate_publication_uncertain"
                registration_state = (
                    receipt.registration_state if receipt is not None else "registration_uncertain"
                )
                attempt.protected_candidate_publication_state = "retained_uncertain"
                outcome = "protected_candidate_publication_uncertain"
            observation = GenerationWorkerProtectedCandidatePublicationObservation(
                status, index, receipt.registered_count if receipt is not None else 0,
                expected, registration_state,
            )
            attempt.protected_candidate_publication_observation = observation
            return observation, outcome

    def _begin_profile_a_outputs_ready_event_locked(self, lifecycle, observation):
        """Claim an exact published Promotion locator once, without exposing it."""
        from core.comfy_output_containment import (
            AcceptedProtectedOutputBatch, ProtectedOutputAcceptanceCharacterization,
        )
        from core.comfy_remote_output_receipts import RemoteOutputReceipt
        from core.generation_storage_admission import (
            WindowsProtectedStorageAdmissionCharacterization,
        )
        from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization
        from core.generation_windows_protected_promotion import (
            ProtectedDurablePromotionCharacterization,
            VerifiedProtectedPromotionReceipt,
        )
        from ui.agent_generation_executor_handoff import GenerationPublicationOrigin

        if (type(observation) is not GenerationWorkerProtectedPromotionObservation
                or observation.status != "protected_promotion_published_non_authoritative"
                or type(observation.request_index) is not int):
            return None, "protected_outputs_ready_observation_invalid"
        index = observation.request_index
        if (lifecycle._state != "bound_non_executing"
                or lifecycle._worker_storage_integration is not self
                or not self._profile_a
                or not self._lifecycle_profile_binding_matches_locked(lifecycle)
                or not 0 <= index < lifecycle._request_count):
            return None, "protected_outputs_ready_host_changed"
        runtime = lifecycle._runtime_ref()
        origin = getattr(runtime, "_generation_publication_origin", None)
        project = lifecycle._project_ref()
        if (runtime is None or type(origin) is not GenerationPublicationOrigin
                or origin.envelope is not lifecycle._envelope
                or origin.project is not project or origin.path != lifecycle._project_path
                or origin.source_snapshot is None):
            return None, "protected_outputs_ready_host_changed"

        attempt = self._storage_preadmission_attempts.get(index)
        if (attempt is None
                or attempt.promotion_publication_observation is not observation
                or attempt.promotion_publication_state != "published_non_authoritative"
                or attempt.promotion_preflight_state != "promoted_non_authoritative"
                or attempt.cancel_requested
                or index in self._profile_a_outputs_ready_event_attempts):
            return None, "protected_outputs_ready_evidence_unavailable"
        writer = self._profile_a_writer_owner
        capacity = self._capacity_owner
        acceptance = attempt.acceptance_owner
        promoter = attempt.promotion_owner
        receipt = attempt.promotion_receipt
        accepted = attempt.accepted_batch
        remote = attempt.remote_receipt
        remote_marker = self._profile_a_remote_outputs_ready_event_attempts.get(index)
        if (type(writer) is not WindowsProtectedAssetsCharacterization
                or type(capacity) is not WindowsProtectedStorageAdmissionCharacterization
                or type(acceptance) is not ProtectedOutputAcceptanceCharacterization
                or type(accepted) is not AcceptedProtectedOutputBatch
                or type(remote) is not RemoteOutputReceipt
                or type(promoter) is not ProtectedDurablePromotionCharacterization
                or type(receipt) is not VerifiedProtectedPromotionReceipt
                or type(observation) is not GenerationWorkerProtectedPromotionObservation):
            return None, "protected_outputs_ready_evidence_unavailable"

        # The locator must be the exact published object and the 19G-D prefix
        # must still be the latest accepted Job/Inbox history before the 19G-E
        # claim can consume it.
        if (remote_marker is None or remote_marker.state != "events_accepted"
                or not self._profile_a_remote_outputs_ready_event_is_current_locked(
                    lifecycle, attempt, remote_marker,
                )):
            return None, "protected_outputs_ready_event_chain_required"

        with lifecycle._lock:
            with writer._lock:
                with acceptance._lock:
                    with promoter._lock:
                        with capacity._lock:
                            with capacity._ledger._lock:
                                with self._lock:
                                    if (self._storage_preadmission_attempts.get(index) is not attempt
                                            or self._profile_a_writer_owner is not writer
                                            or self._capacity_owner is not capacity
                                            or self._profile_a_outputs_ready_event_attempts.get(index)
                                                is not None
                                            or attempt.promotion_publication_observation is not observation
                                            or attempt.promotion_publication_state
                                                != "published_non_authoritative"
                                            or attempt.promotion_preflight_state
                                                != "promoted_non_authoritative"
                                            or attempt.promotion_publication_marker is None
                                            or attempt.promotion_receipt is not receipt
                                            or attempt.promotion_owner is not promoter
                                            or attempt.acceptance_owner is not acceptance
                                            or attempt.accepted_batch is not accepted
                                            or attempt.remote_receipt is not remote
                                            or receipt._promotion_owner is not promoter
                                            or receipt._protected_owner is not writer
                                            or receipt._acceptance_owner is not acceptance
                                            or receipt._accepted is not accepted
                                            or receipt.remote_receipt_identity != remote.identity
                                            or promoter._receipt is not receipt
                                            or promoter._pending_receipt is not None
                                            or promoter._closed or promoter._revoking
                                            or promoter._uncertain or promoter._busy
                                            or writer._closed or writer._revoking
                                            or writer._invalid or writer._uncertain
                                            or acceptance._closed or acceptance._revoking
                                            or acceptance._invalid or acceptance._uncertain
                                            or acceptance._busy or acceptance._receipt is not accepted
                                            or capacity._closed or capacity._invalid
                                            or capacity._scope_lease is None
                                            or capacity._scope_lease._state != "held"
                                            or not capacity._profile_a_root_set
                                            or capacity._ledger._active_write is not None
                                            or remote_marker is not self._profile_a_remote_outputs_ready_event_attempts.get(index)
                                            or remote_marker.state != "events_accepted"
                                            or not self._profile_a_remote_outputs_ready_event_is_current_locked(
                                                lifecycle, attempt, remote_marker,
                                            )):
                                        return None, "protected_outputs_ready_evidence_unavailable"
                                    marker = _ProfileAOutputsReadyEventAttempt(
                                        preadmission_attempt=attempt,
                                        promotion_observation=observation,
                                        promotion_marker=attempt.promotion_publication_marker,
                                        remote_attempt=remote_marker,
                                        promotion_owner=promoter,
                                        promotion_receipt=receipt,
                                        remote_receipt=remote,
                                    )
                                    self._profile_a_outputs_ready_event_attempts[index] = marker
                                    return {
                                        "attempt": attempt,
                                        "marker": marker,
                                        "promotion_observation": observation,
                                        "promotion_marker": attempt.promotion_publication_marker,
                                        "preflight_observation": attempt.promotion_preflight_observation,
                                        "preflight_marker": attempt.promotion_preflight_marker,
                                        "writer_marker": attempt.promotion_writer_marker,
                                        "evidence": attempt.evidence,
                                        "writer_observation": attempt.writer_observation,
                                        "acceptance_observation": attempt.acceptance_observation,
                                        "writer": writer,
                                        "acceptance": acceptance,
                                        "accepted": accepted,
                                        "promotion_owner": promoter,
                                        "receipt": receipt,
                                        "capacity": capacity,
                                        "operation": attempt.promotion_capacity_operation,
                                        "reservation": attempt.promotion_capacity_reservation,
                                        "estimate": attempt.promotion_capacity_estimate,
                                        "write": attempt.promotion_write_admission,
                                        "source_operation": attempt.capacity_operation,
                                        "source_write": attempt.writer_admission,
                                        "source_reservation": attempt.reservation,
                                        "source_estimate": attempt.estimate,
                                        "observations": tuple(attempt.acceptance_observations),
                                        "remote": remote,
                                        "remote_marker": remote_marker,
                                        "prepared": attempt.prepared,
                                        "envelope": lifecycle._envelope,
                                        "runtime": runtime,
                                        "publication_origin": origin,
                                        "source_snapshot": origin.source_snapshot,
                                        "project": project,
                                        "project_reference": self._project_reference,
                                        "pairing_generation": lifecycle._pairing_generation,
                                        "binding": attempt.promotion_host_binding,
                                    }, "protected_outputs_ready_claimed"

    def _commit_profile_a_outputs_ready_event_locked(
            self, lifecycle, captured, inventory, completed_delta,
            destination_records, source_records, result):
        """Accept the exact Promotion output event at the original Host boundary."""
        from core.generation_storage_admission import _WRITABLE
        from core.generation_windows_protected_promotion import VerifiedProtectedPromotionReceipt
        from ui.agent_generation_executor_inbox import ExecutorEvent, OutputReceipt
        from ui.agent_generation_job import WorkerEvent

        attempt = captured["attempt"]
        marker = captured["marker"]
        writer, acceptance = captured["writer"], captured["acceptance"]
        promoter, capacity = captured["promotion_owner"], captured["capacity"]
        receipt, accepted = captured["receipt"], captured["accepted"]
        remote = captured["remote"]
        sources = captured["observations"]
        descriptors = tuple(remote.images)
        rows = tuple(receipt.images)
        total_bytes = sum(item.image.byte_count for item in sources)
        expected_source_delta = {purpose: (0, 0) for purpose in _WRITABLE}
        expected_source_delta["temporary_containment"] = (total_bytes, len(sources))
        expected_destination_delta = {purpose: (0, 0) for purpose in _WRITABLE}
        expected_destination_delta["promoted_assets"] = (total_bytes, len(rows))

        with lifecycle._lock:
            with writer._lock:
                with acceptance._lock:
                    with promoter._lock:
                        with capacity._lock:
                            with capacity._ledger._lock:
                                with self._lock:
                                    destination_record = capacity._ledger._reservations.get(
                                        captured["reservation"],
                                    )
                                    destination_operation = capacity._ledger._operations.get(
                                        captured["operation"],
                                    )
                                    source_record = capacity._ledger._reservations.get(
                                        captured["source_reservation"],
                                    )
                                    source_operation = capacity._ledger._operations.get(
                                        captured["source_operation"],
                                    )
                                    key = (captured["prepared"].request_id, remote.identity)
                                    if (type(receipt) is not VerifiedProtectedPromotionReceipt
                                            or self._storage_preadmission_attempts.get(
                                                attempt.lease.request_index) is not attempt
                                            or self._profile_a_outputs_ready_event_attempts.get(
                                                attempt.lease.request_index) is not marker
                                            or lifecycle._worker_storage_integration is not self
                                            or lifecycle._state != "bound_non_executing"
                                            or self._state != "bound_non_executing"
                                            or attempt.cancel_requested
                                            or marker.state != "claim_in_progress"
                                            or marker.event is not None
                                            or attempt.promotion_publication_observation
                                                is not captured["promotion_observation"]
                                            or attempt.promotion_publication_state
                                                != "published_non_authoritative"
                                            or attempt.promotion_preflight_state
                                                != "promoted_non_authoritative"
                                            or attempt.promotion_publication_completed_delta
                                                != completed_delta
                                            or attempt.promotion_owner is not promoter
                                            or attempt.promotion_receipt is not receipt
                                            or attempt.promotion_host_binding is not captured["binding"]
                                            or attempt.promotion_write_admission is not captured["write"]
                                            or attempt.promotion_capacity_operation
                                                is not captured["operation"]
                                            or attempt.promotion_capacity_reservation
                                                is not captured["reservation"]
                                            or attempt.promotion_capacity_estimate
                                                is not captured["estimate"]
                                            or attempt.acceptance_state != "accepted_non_authoritative"
                                            or attempt.acceptance_observation
                                                is not captured["acceptance_observation"]
                                            or attempt.writer_handoff_state != "staged_non_authoritative"
                                            or attempt.writer_observation is not captured["writer_observation"]
                                            or attempt.writer_owner is not writer
                                            or self._profile_a_writer_owner is not writer
                                            or self._capacity_owner is not capacity
                                            or attempt.acceptance_owner is not acceptance
                                            or attempt.accepted_batch is not accepted
                                            or receipt._promotion_owner is not promoter
                                            or receipt._protected_owner is not writer
                                            or receipt._acceptance_owner is not acceptance
                                            or receipt._accepted is not accepted
                                            or receipt.remote_receipt_identity != remote.identity
                                            or promoter._receipt is not receipt
                                            or promoter._pending_receipt is not None
                                            or promoter._closed or promoter._revoking
                                            or promoter._uncertain or promoter._busy
                                            or writer._closed or writer._revoking
                                            or writer._invalid or writer._uncertain
                                            or acceptance._closed or acceptance._revoking
                                            or acceptance._invalid or acceptance._uncertain
                                            or acceptance._busy or acceptance._receipt is not accepted
                                            or accepted._protected_owner is not writer
                                            or accepted._envelope is not captured["envelope"]
                                            or accepted._prepared is not captured["prepared"]
                                            or accepted._remote is not remote
                                            or promoter._profile_a_host_binding is not captured["binding"]
                                            or writer._stream_promotions.get(key) is not receipt
                                            or writer._stream_batch_acceptances.get(key) is not accepted
                                            or capacity._closed or capacity._invalid
                                            or capacity._scope_lease is None
                                            or capacity._scope_lease._state != "held"
                                            or not capacity._profile_a_root_set
                                            or not capacity._capacity_policy_binding_matches()
                                            or capacity._ledger._active_write is not None
                                            or capacity._ledger._inventory != inventory
                                            or destination_record is None
                                            or destination_record.get("operation") is not captured["operation"]
                                            or destination_record.get("write") is not captured["write"]
                                            or destination_record.get("state") != "completed"
                                            or destination_record.get("estimates") != {
                                                "promoted_assets": (
                                                    captured["estimate"].byte_upper_bound,
                                                    captured["estimate"].entry_upper_bound,
                                                ),
                                            }
                                            or destination_record.get("completed_observed_delta")
                                                != completed_delta
                                            or destination_operation is None
                                            or destination_operation.get("state") != "completed"
                                            or source_record is None
                                            or source_record.get("operation")
                                                is not captured["source_operation"]
                                            or source_record.get("write")
                                                is not captured["source_write"]
                                            or source_record.get("state") != "completed"
                                            or source_record.get("completed_observed_delta")
                                                != expected_source_delta
                                            or source_record.get("estimates") != {
                                                "temporary_containment": (
                                                    captured["source_estimate"].byte_upper_bound,
                                                    captured["source_estimate"].entry_upper_bound,
                                                ),
                                            }
                                            or source_operation is None
                                            or source_operation.get("state") != "completed"
                                            or expected_destination_delta != completed_delta
                                            or not 1 <= len(descriptors) <= _MAX_WRITER_IMAGES
                                            or len(sources) != len(descriptors)
                                            or len(rows) != len(descriptors)
                                            or tuple(item.identity for item in descriptors)
                                                != tuple(item.descriptor_identity for item in sources)
                                            or tuple(item.identity for item in descriptors)
                                                != tuple(row.descriptor_identity for row in rows)
                                            or any(row.source_observation is not source
                                                   for row, source in zip(rows, sources))
                                            or result.status
                                                != "protected_outputs_ready_event_accepted_non_authoritative"
                                            or result.request_index != attempt.lease.request_index
                                            or result.output_count != len(rows)
                                            or result.candidate_eligibility != "not_established"
                                            or result.execution_available is not False
                                            or result.protected_storage_available is not False
                                            or result.promotion_available is not False
                                            or result.candidate_publication_allowed is not False
                                            or result.project_save_allowed is not False
                                            or result.authorship != "unverified"
                                            or not self._profile_a_remote_outputs_ready_event_is_current_locked(
                                                lifecycle, attempt, captured["remote_marker"],
                                            )):
                                        return None, "protected_outputs_ready_event_commit_refused"
                                    for source, row in zip(sources, rows):
                                        source_key = ("temporary_containment",
                                                      source.image.storage_identity)
                                        destination_key = ("promoted_assets",
                                                           row.promoted_image.storage_identity)
                                        source_file = source_records.get(source_key)
                                        destination_file = destination_records.get(destination_key)
                                        if (source_file is None or destination_file is None
                                                or writer._files.get(source_key) is not source_file
                                                or writer._files.get(destination_key) is not destination_file
                                                or writer._images.get(source_key) is not source.image
                                                or writer._images.get(destination_key)
                                                    is not row.promoted_image
                                                or writer._stream_images.get((
                                                    captured["prepared"].request_id,
                                                    source.descriptor_identity)) is not source
                                                or inventory["temporary_containment"].get(
                                                    source.image.storage_identity)
                                                    != (source_file[2], source.image.byte_count,
                                                        source_file[3][0])
                                                or inventory["promoted_assets"].get(
                                                    row.promoted_image.storage_identity)
                                                    != (destination_file[2],
                                                        row.promoted_image.byte_count,
                                                        destination_file[3][0])
                                                or source_file[0].parent
                                                    != writer._roots["temporary_containment"]._path
                                                or destination_file[0].parent
                                                    != writer._roots["promoted_assets"]._path):
                                            return None, "protected_outputs_ready_event_commit_refused"

                                    from ui.agent_generation_job import _TERMINAL
                                    job = lifecycle._jobs._authorized_locked(
                                        lifecycle._job_id, lifecycle._claim_id,
                                    )
                                    inbox = lifecycle._inbox
                                    index = attempt.lease.request_index
                                    if (job is None or job.state in _TERMINAL
                                            or index >= len(job.request_states)
                                            or job.request_states[index] != "awaiting_download"
                                            or job.remote_outputs[index] != len(rows)
                                            or job.outputs[index] != 0
                                            or job.registered[index] != 0
                                            or inbox._closed or inbox._state != "accepted"
                                            or inbox._envelope is not captured["envelope"]):
                                        return None, "protected_outputs_ready_event_commit_refused"

                                    event = ExecutorEvent(
                                        captured["envelope"].job_id,
                                        captured["envelope"].claim_id,
                                        captured["envelope"].manifest.manifest_identity,
                                        WorkerEvent(
                                            job.event_count + 1, index, "outputs_ready",
                                            output_count=len(rows),
                                        ),
                                        OutputReceipt(receipt.identity[:32], len(rows)),
                                    )
                                    if (event.outputs.receipt_id
                                            == captured["remote_marker"].event.outputs.receipt_id):
                                        return None, "protected_outputs_ready_receipt_collision"
                                    marker.event = event
                                    marker.state = "event_acceptance_in_progress"

                                    def event_mutation_observed():
                                        sequence = event.progress.sequence
                                        current = lifecycle._jobs._authorized_locked(
                                            lifecycle._job_id, lifecycle._claim_id,
                                        )
                                        return bool(
                                            current is not None
                                            and (current.events.get(sequence) == event.progress
                                                 or any(item == event.progress
                                                        for item in current.authority_events)
                                                 or inbox._events.get(sequence) is event
                                                 or any(item is event
                                                        for item in inbox._authority_events))
                                        )

                                    try:
                                        accepted_event = inbox.event_for_characterization(
                                            lifecycle._jobs, event, target_current=True,
                                        )
                                    except Exception:
                                        marker.state = "retained_uncertain"
                                        return None, "protected_outputs_ready_event_uncertain"
                                    if accepted_event == "accepted":
                                        marker.observation = result
                                        if self._profile_a_remote_outputs_ready_event_is_current_locked(
                                                lifecycle, attempt, captured["remote_marker"],
                                                outputs_marker=marker,
                                        ):
                                            marker.state = "events_accepted"
                                            return result, result.status
                                        marker.observation = None
                                    marker.state = ("retained_uncertain"
                                                    if event_mutation_observed() else "refused")
                                    return None, (
                                        "protected_outputs_ready_event_uncertain"
                                        if marker.state == "retained_uncertain"
                                        else "protected_outputs_ready_event_refused"
                                    )
    def _begin_profile_a_candidate_admission_preflight_locked(
            self, lifecycle, promotion_observation):
        """Claim one exact post-Promotion read-only Host preflight."""
        from core.comfy_remote_output_receipts import RemoteOutputReceipt
        from ui.agent_generation_executor_handoff import GenerationPublicationOrigin

        if (type(promotion_observation) is not GenerationWorkerProtectedPromotionObservation
                or promotion_observation.status
                    != "protected_promotion_published_non_authoritative"
                or type(promotion_observation.request_index) is not int):
            return None, "protected_candidate_admission_observation_invalid"
        index = promotion_observation.request_index
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._worker_storage_integration is not self
                    or not self._profile_a
                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)):
                return None, "protected_candidate_admission_host_changed"
            runtime = lifecycle._runtime_ref()
            origin = getattr(runtime, "_generation_publication_origin", None)
            project = lifecycle._project_ref()
            if (runtime is None or type(origin) is not GenerationPublicationOrigin
                    or origin.envelope is not lifecycle._envelope
                    or origin.project is not project
                    or origin.path != lifecycle._project_path
                    or origin.source_snapshot is None):
                return None, "protected_candidate_admission_host_changed"
            attempt = self._storage_preadmission_attempts.get(index)
            if (attempt is None
                    or attempt.promotion_publication_observation is not promotion_observation
                    or attempt.promotion_publication_state != "published_non_authoritative"
                    or attempt.promotion_preflight_state != "promoted_non_authoritative"
                    or attempt.candidate_admission_state != "not_started"
                    or attempt.cancel_requested):
                return None, "protected_candidate_admission_evidence_unavailable"
            writer = self._profile_a_writer_owner
            capacity = self._capacity_owner
            acceptance = attempt.acceptance_owner
            promoter = attempt.promotion_owner
            receipt = attempt.promotion_receipt
            accepted = attempt.accepted_batch
            if (writer is None or capacity is None or acceptance is None or promoter is None
                    or receipt is None or accepted is None):
                return None, "protected_candidate_admission_evidence_unavailable"
            with writer._lock:
                with acceptance._lock:
                    with promoter._lock:
                        with capacity._lock:
                            with capacity._ledger._lock:
                                with self._lock:
                                    remote = attempt.remote_receipt
                                    descriptors = tuple(remote.images) if remote is not None else ()
                                    sources = tuple(attempt.acceptance_observations)
                                    rows = tuple(getattr(receipt, "images", ()))
                                    if (self._storage_preadmission_attempts.get(index) is not attempt
                                            or self._state != "bound_non_executing"
                                            or lifecycle._worker_storage_integration is not self
                                            or self._profile_a_writer_owner is not writer
                                            or self._capacity_owner is not capacity
                                            or attempt.candidate_admission_state != "not_started"
                                            or attempt.promotion_publication_observation
                                                is not promotion_observation
                                            or attempt.promotion_publication_state
                                                != "published_non_authoritative"
                                            or attempt.promotion_preflight_state
                                                != "promoted_non_authoritative"
                                            or type(descriptors) is not tuple
                                            or not 1 <= len(descriptors) <= _MAX_WRITER_IMAGES
                                            or len(sources) != len(descriptors)
                                            or len(rows) != len(descriptors)
                                            or tuple(item.identity for item in descriptors)
                                                != tuple(item.descriptor_identity for item in sources)
                                            or tuple(item.identity for item in descriptors)
                                                != tuple(row.descriptor_identity for row in rows)
                                            or any(row.source_observation is not source
                                                   for row, source in zip(rows, sources))
                                            or attempt.prepared is None
                                            or attempt.prepared.request_index != index
                                            or type(remote) is not RemoteOutputReceipt
                                            or attempt.accepted_prompt_id != remote.prompt_id
                                            or remote.execution_succeeded is not True
                                            or attempt.acceptance_state
                                                != "accepted_non_authoritative"
                                            or attempt.writer_handoff_state
                                                != "staged_non_authoritative"
                                            or writer._closed or writer._revoking
                                            or writer._invalid or writer._uncertain
                                            or acceptance._closed or acceptance._revoking
                                            or acceptance._invalid or acceptance._uncertain
                                            or acceptance._busy or acceptance._receipt is not accepted
                                            or promoter._closed or promoter._revoking
                                            or promoter._uncertain or promoter._busy
                                            or promoter._receipt is not receipt
                                            or promoter._pending_receipt is not None
                                            or capacity._closed or capacity._invalid
                                            or capacity._scope_lease is None
                                            or capacity._scope_lease._state != "held"
                                            or not capacity._profile_a_root_set
                                            or capacity._ledger._active_write is not None):
                                        return None, "protected_candidate_admission_evidence_unavailable"
                                    marker = object()
                                    attempt.candidate_admission_state = "in_progress"
                                    attempt.candidate_admission_marker = marker
                                    return {
                                        "attempt": attempt,
                                        "marker": marker,
                                        "promotion_observation": promotion_observation,
                                        "promotion_marker": attempt.promotion_publication_marker,
                                        "preflight_observation": attempt.promotion_preflight_observation,
                                        "preflight_marker": attempt.promotion_preflight_marker,
                                        "writer_marker": attempt.promotion_writer_marker,
                                        "evidence": attempt.evidence,
                                        "writer_observation": attempt.writer_observation,
                                        "acceptance_observation": attempt.acceptance_observation,
                                        "writer": writer,
                                        "capacity": capacity,
                                        "acceptance": acceptance,
                                        "accepted": accepted,
                                        "promotion_owner": promoter,
                                        "receipt": receipt,
                                        "operation": attempt.promotion_capacity_operation,
                                        "reservation": attempt.promotion_capacity_reservation,
                                        "estimate": attempt.promotion_capacity_estimate,
                                        "write": attempt.promotion_write_admission,
                                        "source_operation": attempt.capacity_operation,
                                        "source_write": attempt.writer_admission,
                                        "observations": sources,
                                        "remote": remote,
                                        "prepared": attempt.prepared,
                                        "envelope": lifecycle._envelope,
                                        "runtime": runtime,
                                        "publication_origin": origin,
                                        "source_snapshot": origin.source_snapshot,
                                        "project": project,
                                        "project_reference": self._project_reference,
                                        "pairing_generation": lifecycle._pairing_generation,
                                        "binding": attempt.promotion_host_binding,
                                    }, "candidate_admission_preflight_claimed"

    def _begin_profile_a_promotion_publication_locked(self, lifecycle, observation):
        """Claim one separate Host publication after the private Promotion commit."""
        from core.comfy_output_containment import AcceptedProtectedOutputBatch, ProtectedOutputAcceptanceCharacterization
        from core.generation_storage_admission import (
            CapacityEstimate, WindowsProtectedStorageAdmissionCharacterization, _Opaque,
        )
        from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization
        from core.generation_windows_protected_promotion import (
            ProtectedDurablePromotionCharacterization, VerifiedProtectedPromotionReceipt,
            _ProfileAHostPromotionBinding,
        )

        if (type(observation) is not GenerationWorkerProtectedPromotionPreflightObservation
                or observation.status != "protected_promotion_preflight_non_authoritative"
                or observation._issuer is not self):
            return None, "protected_promotion_publication_observation_invalid"
        writer = self._profile_a_writer_owner
        capacity = self._capacity_owner
        if (type(writer) is not WindowsProtectedAssetsCharacterization
                or type(capacity) is not WindowsProtectedStorageAdmissionCharacterization):
            return None, "protected_promotion_publication_unavailable"
        with lifecycle._lock:
            if (lifecycle._worker_storage_integration is not self
                    or lifecycle._state != "bound_non_executing"
                    or lifecycle._generation != self._lifecycle_generation
                    or not self._lifecycle_profile_binding_matches_locked(lifecycle)):
                return None, "protected_promotion_publication_host_changed"
            with writer._lock:
                attempt = self._storage_preadmission_attempts.get(observation.request_index)
                acceptance = attempt.acceptance_owner if attempt is not None else None
                promoter = attempt.promotion_owner if attempt is not None else None
                receipt = attempt.promotion_receipt if attempt is not None else None
                if (type(acceptance) is not ProtectedOutputAcceptanceCharacterization
                        or type(promoter) is not ProtectedDurablePromotionCharacterization
                        or type(receipt) is not VerifiedProtectedPromotionReceipt):
                    return None, "protected_promotion_publication_evidence_unavailable"
                with acceptance._lock:
                    with promoter._lock:
                        with capacity._lock:
                            with capacity._ledger._lock:
                                with self._lock:
                                    operation = attempt.promotion_capacity_operation
                                    reservation = attempt.promotion_capacity_reservation
                                    estimate = attempt.promotion_capacity_estimate
                                    write = attempt.promotion_write_admission
                                    binding = attempt.promotion_host_binding
                                    record = capacity._ledger._reservations.get(reservation)
                                    operation_record = capacity._ledger._operations.get(operation)
                                    accepted = attempt.accepted_batch
                                    descriptors = tuple(attempt.remote_receipt.images) if attempt.remote_receipt else ()
                                    rows = tuple(receipt.images)
                                    observations = attempt.acceptance_observations
                                    if (self._state != "bound_non_executing"
                                            or self._storage_preadmission_attempts.get(
                                                observation.request_index) is not attempt
                                            or attempt.state != "pre_admitted"
                                            or attempt.cancel_requested
                                            or attempt.promotion_preflight_state
                                                != "private_committed_host_publication_pending"
                                            or attempt.promotion_publication_state != "not_started"
                                            or attempt.promotion_publication_marker is not None
                                            or attempt.promotion_publication_observation is not None
                                            or attempt.promotion_preflight_observation is not observation
                                            or observation._attempt_nonce != attempt.lease.nonce
                                            or attempt.acceptance_state != "accepted_non_authoritative"
                                            or attempt.acceptance_observation is None
                                            or attempt.acceptance_observation.accepted_image_count != len(descriptors)
                                            or attempt.writer_handoff_state != "staged_non_authoritative"
                                            or attempt.writer_owner is not writer
                                            or attempt.acceptance_owner is not acceptance
                                            or attempt.promotion_owner is not promoter
                                            or attempt.promotion_receipt is not receipt
                                            or type(accepted) is not AcceptedProtectedOutputBatch
                                            or accepted._protected_owner is not writer
                                            or receipt._promotion_owner is not promoter
                                            or receipt._protected_owner is not writer
                                            or receipt._acceptance_owner is not acceptance
                                            or receipt._accepted is not accepted
                                            or promoter._receipt is not receipt
                                            or promoter._pending_receipt is not None
                                            or promoter._closed or promoter._revoking or promoter._uncertain
                                            or promoter._busy
                                            or writer._closed or writer._revoking
                                            or writer._invalid or writer._uncertain
                                            or writer._stream_promotions.get((attempt.prepared.request_id,
                                                                              attempt.remote_receipt.identity))
                                                is not receipt
                                            or writer._stream_batch_acceptances.get((attempt.prepared.request_id,
                                                                                    attempt.remote_receipt.identity))
                                                is not accepted
                                            or acceptance._closed or acceptance._revoking
                                            or acceptance._invalid or acceptance._uncertain
                                            or acceptance._busy or acceptance._receipt is not accepted
                                            or capacity._closed or capacity._invalid
                                            or capacity._scope_lease is None
                                            or capacity._scope_lease._state != "held"
                                            or not capacity._profile_a_root_set
                                            or not capacity._capacity_policy_binding_matches()
                                            or type(operation) is not _Opaque
                                            or type(reservation) is not _Opaque
                                            or type(write) is not _Opaque
                                            or type(estimate) is not CapacityEstimate
                                            or capacity._ledger._active_write is not None
                                            or record is None or record.get("operation") is not operation
                                            or record.get("write") is not write
                                            or record.get("state") != "completed"
                                            or operation_record is None
                                            or operation_record.get("state") != "completed"
                                            or type(binding) is not _ProfileAHostPromotionBinding
                                            or binding is not promoter._profile_a_host_binding
                                            or binding.integration is not self
                                            or binding.attempt is not attempt
                                            or binding.preflight_observation is not observation
                                            or binding.write_admission is not write
                                            or len(rows) != len(descriptors)
                                            or len(rows) != len(observations)
                                            or tuple(row.descriptor_identity for row in rows)
                                                != tuple(item.identity for item in descriptors)
                                            or tuple(row.source_observation for row in rows)
                                                != observations
                                            or tuple(item.descriptor_identity for item in observations)
                                                != tuple(item.identity for item in descriptors)):
                                        return None, "protected_promotion_publication_evidence_unavailable"
                                    marker = object()
                                    attempt.promotion_publication_state = "in_progress"
                                    attempt.promotion_publication_marker = marker
                                    return {
                                        "attempt": attempt, "marker": marker,
                                        "preflight_observation": observation,
                                        "writer_marker": attempt.promotion_writer_marker,
                                        "preflight_marker": attempt.promotion_preflight_marker,
                                        "evidence": attempt.evidence,
                                        "writer_observation": attempt.writer_observation,
                                        "acceptance_observation": attempt.acceptance_observation,
                                        "writer": writer, "acceptance": acceptance,
                                        "accepted": accepted, "promotion_owner": promoter,
                                        "receipt": receipt, "capacity": capacity,
                                        "operation": operation, "reservation": reservation,
                                        "estimate": estimate, "write": write,
                                        "binding": binding, "observations": observations,
                                        "envelope": lifecycle._envelope,
                                        "remote": attempt.remote_receipt,
                                        "prepared": attempt.prepared,
                                    }, "promotion_publication_claimed"

    def _commit_profile_a_promotion_publication_locked(
            self, lifecycle, captured, inventory, completed_delta,
            destination_records, source_records, result):
        """Short in-memory publication commit under the original Host gate.

        Required lock order is Host publication/route/registry/Job/Inbox,
        lifecycle, protected assets, Acceptance, Promotion, capacity, ledger,
        then this integration. No filesystem I/O or callbacks are permitted.
        """
        from core.generation_storage_admission import _WRITABLE

        attempt = captured["attempt"]
        writer, acceptance = captured["writer"], captured["acceptance"]
        promoter, capacity = captured["promotion_owner"], captured["capacity"]
        receipt, accepted = captured["receipt"], captured["accepted"]
        descriptors = tuple(captured["remote"].images)
        sources = tuple(captured["observations"])
        rows = tuple(receipt.images)
        total_bytes = sum(item.image.byte_count for item in sources)
        expected_source_delta = {purpose: (0, 0) for purpose in _WRITABLE}
        expected_source_delta["temporary_containment"] = (total_bytes, len(sources))
        expected_destination_delta = {purpose: (0, 0) for purpose in _WRITABLE}
        expected_destination_delta["promoted_assets"] = (total_bytes, len(rows))
        with lifecycle._lock:
            with writer._lock:
                with acceptance._lock:
                    with promoter._lock:
                        with capacity._lock:
                            with capacity._ledger._lock:
                                with self._lock:
                                    record = capacity._ledger._reservations.get(captured["reservation"])
                                    operation_record = capacity._ledger._operations.get(captured["operation"])
                                    source_record = capacity._ledger._reservations.get(attempt.reservation)
                                    source_operation_record = capacity._ledger._operations.get(
                                        attempt.capacity_operation,
                                    )
                                    key = (captured["prepared"].request_id, captured["remote"].identity)
                                    if (self._storage_preadmission_attempts.get(
                                            attempt.lease.request_index) is not attempt
                                            or lifecycle._worker_storage_integration is not self
                                            or lifecycle._state != "bound_non_executing"
                                            or self._state != "bound_non_executing"
                                            or attempt.cancel_requested
                                            or attempt.promotion_preflight_state
                                                != "private_committed_host_publication_pending"
                                            or attempt.promotion_publication_state != "in_progress"
                                            or attempt.promotion_publication_marker is not captured["marker"]
                                            or attempt.promotion_preflight_observation
                                                is not captured["preflight_observation"]
                                            or attempt.promotion_owner is not promoter
                                            or attempt.promotion_receipt is not receipt
                                            or attempt.promotion_host_binding is not captured["binding"]
                                            or attempt.promotion_write_admission is not captured["write"]
                                            or attempt.promotion_capacity_operation is not captured["operation"]
                                            or attempt.promotion_capacity_reservation is not captured["reservation"]
                                            or attempt.promotion_capacity_estimate is not captured["estimate"]
                                            or attempt.promotion_publication_observation is not None
                                            or writer._closed or writer._revoking or writer._invalid or writer._uncertain
                                            or acceptance._closed or acceptance._revoking
                                            or acceptance._invalid or acceptance._uncertain
                                            or acceptance._busy or acceptance._receipt is not accepted
                                            or promoter._closed or promoter._revoking or promoter._uncertain
                                            or promoter._busy or promoter._receipt is not receipt
                                            or writer._stream_promotions.get(key) is not receipt
                                            or writer._stream_batch_acceptances.get(key) is not accepted
                                            or capacity._closed or capacity._invalid
                                            or capacity._scope_lease is None
                                            or capacity._scope_lease._state != "held"
                                            or capacity._ledger._active_write is not None
                                            or capacity._ledger._inventory != inventory
                                            or record is None or record.get("operation") is not captured["operation"]
                                            or record.get("write") is not captured["write"]
                                            or record.get("state") != "completed"
                                            or record.get("estimates") != {
                                                "promoted_assets": (
                                                    captured["estimate"].byte_upper_bound,
                                                    captured["estimate"].entry_upper_bound,
                                                ),
                                            }
                                            or record.get("completed_observed_delta") != completed_delta
                                            or capacity._ledger._operations.get(captured["operation"])
                                                is not operation_record
                                            or operation_record is None
                                            or operation_record.get("state") != "completed"
                                            or source_record is None
                                            or source_record.get("operation") is not attempt.capacity_operation
                                            or source_record.get("write") is not attempt.writer_admission
                                            or source_record.get("state") != "completed"
                                            or source_record.get("completed_observed_delta")
                                                != expected_source_delta
                                            or source_operation_record is None
                                            or source_operation_record.get("state") != "completed"
                                            or source_record.get("estimates") != {
                                                "temporary_containment": (
                                                    attempt.estimate.byte_upper_bound,
                                                    attempt.estimate.entry_upper_bound,
                                                ),
                                            }
                                            or len(descriptors) != len(sources)
                                            or len(rows) != len(sources)
                                            or tuple(item.identity for item in descriptors)
                                                != tuple(row.descriptor_identity for row in rows)
                                            or tuple(item.descriptor_identity for item in sources)
                                                != tuple(row.descriptor_identity for row in rows)
                                            or any(row.source_observation is not source
                                                   for row, source in zip(rows, sources))
                                            or expected_destination_delta != completed_delta
                                            or result.request_index != attempt.lease.request_index
                                            or type(result) is not GenerationWorkerProtectedPromotionObservation
                                            or result.status != "protected_promotion_published_non_authoritative"
                                            or result.promoted_image_count != len(receipt.images)
                                            or result.execution_available is not False
                                            or result.protected_storage_available is not False
                                            or result.promotion_available is not False
                                            or result.candidate_publication_allowed is not False
                                            or result.project_save_allowed is not False
                                            or result.authorship != "unverified"):
                                        return False
                                    for source, row in zip(sources, rows):
                                        source_key = ("temporary_containment",
                                                      source.image.storage_identity)
                                        destination_key = ("promoted_assets",
                                                           row.promoted_image.storage_identity)
                                        source_file = source_records.get(source_key)
                                        destination_file = destination_records.get(destination_key)
                                        if (source_file is None or destination_file is None
                                                or writer._files.get(source_key) is not source_file
                                                or writer._files.get(destination_key) is not destination_file
                                                or writer._images.get(source_key) is not source.image
                                                or writer._images.get(destination_key) is not row.promoted_image
                                                or writer._stream_images.get((captured["prepared"].request_id,
                                                                              source.descriptor_identity)) is not source
                                                or inventory["temporary_containment"].get(
                                                    source.image.storage_identity)
                                                    != (source_file[2], source.image.byte_count,
                                                        source_file[3][0])
                                                or inventory["promoted_assets"].get(
                                                    row.promoted_image.storage_identity)
                                                    != (destination_file[2],
                                                        row.promoted_image.byte_count,
                                                        destination_file[3][0])
                                                or source_file[0].parent
                                                    != writer._roots["temporary_containment"]._path
                                                or destination_file[0].parent
                                                    != writer._roots["promoted_assets"]._path):
                                            return False
                                    attempt.promotion_publication_observation = result
                                    attempt.promotion_publication_completed_delta = completed_delta
                                    attempt.promotion_publication_state = "published_non_authoritative"
                                    attempt.promotion_preflight_state = "promoted_non_authoritative"
                                    return True

    def _commit_profile_a_candidate_admission_preflight_locked(
            self, lifecycle, captured, inventory, completed_delta,
            destination_records, source_records, result):
        """Publish only a read-only, non-authoritative Profile A preflight.

        The caller holds the original runtime/route/Job/Inbox gate. This short
        commit takes lifecycle -> assets -> acceptance -> promotion -> capacity
        -> ledger -> integration locks. It performs no native I/O or callbacks.
        """
        from core.generation_storage_admission import _WRITABLE
        from core.generation_windows_protected_promotion import (
            VerifiedProtectedPromotionReceipt,
        )
        if (type(result) is not GenerationWorkerProtectedCandidateAdmissionPreflightObservation
                or result.status != "protected_candidate_admission_preflight_non_authoritative"):
            return False

        attempt = captured["attempt"]
        writer, acceptance = captured["writer"], captured["acceptance"]
        promoter, capacity = captured["promotion_owner"], captured["capacity"]
        receipt, accepted = captured["receipt"], captured["accepted"]
        sources = captured["observations"]
        descriptors = tuple(captured["remote"].images)
        rows = tuple(receipt.images)
        total_bytes = sum(item.image.byte_count for item in sources)
        expected_source_delta = {purpose: (0, 0) for purpose in _WRITABLE}
        expected_source_delta["temporary_containment"] = (total_bytes, len(sources))
        expected_destination_delta = {purpose: (0, 0) for purpose in _WRITABLE}
        expected_destination_delta["promoted_assets"] = (total_bytes, len(rows))
        with lifecycle._lock:
            with writer._lock:
                with acceptance._lock:
                    with promoter._lock:
                        with capacity._lock:
                            with capacity._ledger._lock:
                                with self._lock:
                                    destination_record = capacity._ledger._reservations.get(
                                        captured["reservation"],
                                    )
                                    destination_operation = capacity._ledger._operations.get(
                                        captured["operation"],
                                    )
                                    source_record = capacity._ledger._reservations.get(
                                        attempt.reservation,
                                    )
                                    source_operation = capacity._ledger._operations.get(
                                        attempt.capacity_operation,
                                    )
                                    key = (captured["prepared"].request_id,
                                           captured["remote"].identity)
                                    if (type(receipt) is not VerifiedProtectedPromotionReceipt
                                            or self._storage_preadmission_attempts.get(
                                                attempt.lease.request_index) is not attempt
                                            or lifecycle._worker_storage_integration is not self
                                            or lifecycle._state != "bound_non_executing"
                                            or self._state != "bound_non_executing"
                                            or attempt.cancel_requested
                                            or attempt.candidate_admission_state != "in_progress"
                                            or attempt.candidate_admission_marker is not captured["marker"]
                                            or attempt.candidate_admission_observation is not None
                                            or attempt.promotion_publication_observation
                                                is not captured["promotion_observation"]
                                            or attempt.promotion_publication_state
                                                != "published_non_authoritative"
                                            or attempt.promotion_preflight_state
                                                != "promoted_non_authoritative"
                                            or attempt.promotion_owner is not promoter
                                            or attempt.promotion_receipt is not receipt
                                            or attempt.promotion_host_binding is not captured["binding"]
                                            or attempt.promotion_write_admission is not captured["write"]
                                            or attempt.promotion_capacity_operation
                                                is not captured["operation"]
                                            or attempt.promotion_capacity_reservation
                                                is not captured["reservation"]
                                            or attempt.promotion_capacity_estimate
                                                is not captured["estimate"]
                                            or writer._closed or writer._revoking
                                            or writer._invalid or writer._uncertain
                                            or acceptance._closed or acceptance._revoking
                                            or acceptance._invalid or acceptance._uncertain
                                            or acceptance._busy or acceptance._receipt is not accepted
                                            or accepted._protected_owner is not writer
                                            or accepted._envelope is not captured["envelope"]
                                            or accepted._prepared is not captured["prepared"]
                                            or accepted._remote is not captured["remote"]
                                            or acceptance._host_freshness
                                                is not attempt.acceptance_host_freshness
                                            or promoter._closed or promoter._revoking
                                            or promoter._uncertain or promoter._busy
                                            or promoter._receipt is not receipt
                                            or promoter._pending_receipt is not None
                                            or receipt._promotion_owner is not promoter
                                            or receipt._protected_owner is not writer
                                            or receipt._acceptance_owner is not acceptance
                                            or receipt._accepted is not accepted
                                            or writer._stream_promotions.get(key) is not receipt
                                            or writer._stream_batch_acceptances.get(key) is not accepted
                                            or capacity._closed or capacity._invalid
                                            or capacity._scope_lease is None
                                            or capacity._scope_lease._state != "held"
                                            or not capacity._profile_a_root_set
                                            or capacity._ledger._active_write is not None
                                            or capacity._ledger._inventory != inventory
                                            or destination_record is None
                                            or destination_record.get("operation") is not captured["operation"]
                                            or destination_record.get("write") is not captured["write"]
                                            or destination_record.get("state") != "completed"
                                            or destination_record.get("estimates") != {
                                                "promoted_assets": (
                                                    captured["estimate"].byte_upper_bound,
                                                    captured["estimate"].entry_upper_bound,
                                                ),
                                            }
                                            or destination_record.get("completed_observed_delta")
                                                != completed_delta
                                            or destination_operation is None
                                            or destination_operation.get("state") != "completed"
                                            or source_record is None
                                            or source_record.get("operation")
                                                is not attempt.capacity_operation
                                            or source_record.get("write") is not attempt.writer_admission
                                            or source_record.get("state") != "completed"
                                            or source_record.get("completed_observed_delta")
                                                != expected_source_delta
                                            or source_record.get("estimates") != {
                                                "temporary_containment": (
                                                    attempt.estimate.byte_upper_bound,
                                                    attempt.estimate.entry_upper_bound,
                                                ),
                                            }
                                            or source_operation is None
                                            or source_operation.get("state") != "completed"
                                            or not 1 <= len(descriptors) <= _MAX_WRITER_IMAGES
                                            or len(sources) != len(descriptors)
                                            or len(rows) != len(descriptors)
                                            or tuple(item.identity for item in descriptors)
                                                != tuple(item.descriptor_identity for item in sources)
                                            or tuple(item.identity for item in descriptors)
                                                != tuple(row.descriptor_identity for row in rows)
                                            or any(row.source_observation is not source
                                                   for row, source in zip(rows, sources))
                                            or expected_destination_delta != completed_delta
                                            or result.request_index != attempt.lease.request_index
                                            or result.verified_promoted_image_count != len(rows)
                                            or result.candidate_eligibility != "not_established"
                                            or result.execution_available is not False
                                            or result.protected_storage_available is not False
                                            or result.promotion_available is not False
                                            or result.candidate_publication_allowed is not False
                                            or result.project_save_allowed is not False
                                            or result.authorship != "unverified"):
                                        return False
                                    for source, row in zip(sources, rows):
                                        source_key = ("temporary_containment",
                                                      source.image.storage_identity)
                                        destination_key = ("promoted_assets",
                                                           row.promoted_image.storage_identity)
                                        source_file = source_records.get(source_key)
                                        destination_file = destination_records.get(destination_key)
                                        if (source_file is None or destination_file is None
                                                or writer._files.get(source_key) is not source_file
                                                or writer._files.get(destination_key) is not destination_file
                                                or writer._images.get(source_key) is not source.image
                                                or writer._images.get(destination_key)
                                                    is not row.promoted_image
                                                or writer._stream_images.get((
                                                    captured["prepared"].request_id,
                                                    source.descriptor_identity)) is not source
                                                or inventory["temporary_containment"].get(
                                                    source.image.storage_identity)
                                                    != (source_file[2], source.image.byte_count,
                                                        source_file[3][0])
                                                or inventory["promoted_assets"].get(
                                                    row.promoted_image.storage_identity)
                                                    != (destination_file[2],
                                                        row.promoted_image.byte_count,
                                                        destination_file[3][0])
                                                or source_file[0].parent
                                                    != writer._roots["temporary_containment"]._path
                                                or destination_file[0].parent
                                                    != writer._roots["promoted_assets"]._path):
                                            return False
                                    attempt.candidate_admission_observation = result
                                    attempt.candidate_admission_state = (
                                        "preflight_observed_non_authoritative")
                                    return True

    def _retain_profile_a_candidate_admission_preflight_uncertain(self, captured):
        """Retain only this downstream preflight uncertainty; never rewrite Promotion."""
        attempt = captured.get("attempt") if type(captured) is dict else None
        if attempt is None:
            return False
        with self._lock:
            if (self._storage_preadmission_attempts.get(
                    attempt.lease.request_index) is not attempt
                    or attempt.candidate_admission_state != "in_progress"
                    or attempt.candidate_admission_marker is not captured.get("marker")):
                return False
            attempt.candidate_admission_state = "retained_uncertain"
            attempt.candidate_admission_observation = None
            return True

    def _retain_profile_a_outputs_ready_event(
            self, attempt, marker, state="retained_uncertain"):
        """Settle only the one-shot downstream event owner; retain Promotion."""
        if state not in {"refused", "retained_uncertain"}:
            return False
        if attempt is None or marker is None:
            return False
        with self._lock:
            index = getattr(getattr(attempt, "lease", None), "request_index", None)
            if (type(index) is not int
                    or self._storage_preadmission_attempts.get(index) is not attempt
                    or self._profile_a_outputs_ready_event_attempts.get(index) is not marker
                    or marker.preadmission_attempt is not attempt
                    or marker.state not in {
                        "claim_in_progress", "event_acceptance_in_progress",
                    }):
                return False
            marker.state = state
            return True

    def _retain_profile_a_promotion_publication_uncertain(self, attempt, marker=None):
        """Compensate only the exact completed destination delta; retain files."""
        from core.generation_windows_protected_promotion import VerifiedProtectedPromotionReceipt

        writer = self._profile_a_writer_owner
        capacity = self._capacity_owner
        promoter = attempt.promotion_owner if attempt is not None else None
        acceptance = attempt.acceptance_owner if attempt is not None else None
        receipt = attempt.promotion_receipt if attempt is not None else None
        if (attempt is None or writer is None or capacity is None or promoter is None
                or acceptance is None or type(receipt) is not VerifiedProtectedPromotionReceipt):
            return False
        try:
            with writer._lock:
                with acceptance._lock:
                    with promoter._lock:
                        with capacity._lock:
                            with capacity._ledger._lock:
                                with self._lock:
                                    if (self._storage_preadmission_attempts.get(
                                            attempt.lease.request_index) is not attempt
                                            or attempt.promotion_preflight_state
                                                == "promoted_non_authoritative"
                                            or (marker is not None
                                                and attempt.promotion_publication_marker is not marker)
                                            or attempt.promotion_owner is not promoter
                                            or promoter._receipt is not receipt
                                            or receipt._promotion_owner is not promoter
                                            or receipt._protected_owner is not writer
                                            or receipt._acceptance_owner is not acceptance
                                            or receipt._accepted is not attempt.accepted_batch
                                            or attempt.promotion_capacity_operation is None
                                            or attempt.promotion_capacity_reservation is None
                                            or attempt.promotion_write_admission is None):
                                        return False
                                    record = capacity._ledger._reservations.get(
                                        attempt.promotion_capacity_reservation,
                                    )
                                    operation_record = capacity._ledger._operations.get(
                                        attempt.promotion_capacity_operation,
                                    )
                                    delta = (record.get("completed_observed_delta")
                                             if record is not None else None)
                                    if (record is not None
                                            and record.get("operation") is attempt.promotion_capacity_operation
                                            and record.get("write") is attempt.promotion_write_admission
                                            and operation_record is not None
                                            and (record.get("state") == "completed"
                                                 or (record.get("state") == "uncertain"
                                                     and record.get("uncertain_completed_delta") == delta))
                                            and (operation_record.get("state") == "completed"
                                                 or operation_record.get("state") == "uncertain")
                                            and type(delta) is dict):
                                        try:
                                            capacity._ledger.retain_completed_write_as_uncertain(
                                                attempt.promotion_capacity_operation,
                                                attempt.promotion_write_admission, delta,
                                            )
                                        except Exception:
                                            pass
                                    # If exact compensation cannot be proven, an
                                    # invalid owner plus the unresolved attempt
                                    # retains the cross-process marker and files.
                                    capacity._invalid = True
                                    promoter._uncertain = True
                                    attempt.cancel_requested = True
                                    attempt.promotion_preflight_state = "retained_uncertain"
                                    attempt.promotion_publication_state = "retained_uncertain"
                                    attempt.promotion_publication_observation = None
                                    return True
        except Exception:
            with self._lock:
                if self._storage_preadmission_attempts.get(
                        attempt.lease.request_index) is attempt:
                    attempt.cancel_requested = True
                    attempt.promotion_preflight_state = "retained_uncertain"
                    attempt.promotion_publication_state = "retained_uncertain"
            try:
                capacity._invalid = True
                promoter._uncertain = True
            except Exception:
                pass
            return False

    def _bind_profile_a_acceptance_freshness(self, attempt, marker, callback):
        if not callable(callback):
            return False
        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or attempt.acceptance_state != "in_progress"
                    or attempt.acceptance_marker is not marker
                    or attempt.acceptance_host_freshness is not None):
                return False
            attempt.acceptance_host_freshness = callback
            return True

    def _profile_a_acceptance_matches_locked(
            self, lifecycle, attempt, marker, evidence, writer_owner, observation):
        """Short host/Worker evidence check; called only inside current-host gate."""
        if (attempt.acceptance_state != "in_progress"
                or attempt.acceptance_marker is not marker
                or attempt.writer_observation is not observation
                or not self._writer_handoff_matches_locked(
                    lifecycle, attempt, attempt.writer_handoff_marker,
                    evidence, writer_owner, states={"staged_non_authoritative"})):
            return False
        history, remote = attempt.history_completion, attempt.remote_receipt
        if (history is None or remote is None
                or getattr(history, "kind", None) != "history"
                or getattr(getattr(history, "outcome", None), "status", None) != "ready"
                or getattr(getattr(history, "outcome", None), "history_json", None)
                    != attempt.history_json
                or attempt.history_json != remote._validated_history_json
                or history.correlation.prompt_id != attempt.accepted_prompt_id):
            return False
        try:
            return self._worker._run_if_issued_completion_for_prepared_request_for_characterization(
                history, attempt.prepared, self._worker_owner_claim, lambda: True,
            ) is True
        except Exception:
            return False

    def _profile_a_promotion_preflight_matches_locked(
            self, lifecycle, attempt, marker, evidence, writer_observation,
            acceptance_observation, writer_owner, *, operation=None, reservation=None,
            estimate=None, expected_states=("in_progress",),
            promotion_observation=None, write_admission=None, promotion_owner=None):
        """Freshness gate for the already-settled Acceptance-to-Promotion preflight.

        This deliberately does not reuse the in-progress Acceptance predicate.
        It accepts only the exact settled count observation and privately
        retained AcceptedProtectedOutputBatch while the same Host, Claim,
        Project, Worker completion, roots, Writer and completed staging record
        remain current.
        """
        from core.comfy_output_containment import AcceptedProtectedOutputBatch
        from core.generation_storage_admission import CapacityEstimate
        from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization

        if (attempt.promotion_preflight_state not in expected_states
                or attempt.promotion_preflight_marker is not marker
                or attempt.acceptance_state != "accepted_non_authoritative"
                or attempt.acceptance_observation is not acceptance_observation
                or attempt.writer_observation is not writer_observation
                or attempt.writer_owner is not writer_owner
                or attempt.cancel_requested
                or (promotion_observation is not None
                    and attempt.promotion_preflight_observation is not promotion_observation)
                or (promotion_owner is not None and attempt.promotion_owner is not promotion_owner)
                or not self._writer_handoff_matches_locked(
                    lifecycle, attempt, attempt.writer_handoff_marker,
                    evidence, writer_owner, states={"staged_non_authoritative"})):
            return False
        history, remote, prepared = (
            attempt.history_completion, attempt.remote_receipt, attempt.prepared,
        )
        if (history is None or remote is None or prepared is None
                or getattr(history, "kind", None) != "history"
                or getattr(getattr(history, "outcome", None), "status", None) != "ready"
                or getattr(getattr(history, "outcome", None), "history_json", None)
                    != attempt.history_json
                or attempt.history_json != remote._validated_history_json
                or attempt.accepted_prompt_id != remote.prompt_id
                or remote.execution_succeeded is not True):
            return False
        accepted, acceptance_owner = attempt.accepted_batch, attempt.acceptance_owner
        if (type(accepted) is not AcceptedProtectedOutputBatch
                or acceptance_owner is None
                or accepted._protected_owner is not writer_owner
                or accepted._prepared is not prepared
                or accepted._remote is not remote
                or accepted._batch_receipt.observations is not attempt.acceptance_observations
                or accepted.image_count != acceptance_observation.accepted_image_count):
            return False
        try:
            with acceptance_owner._lock:
                if (acceptance_owner._closed or acceptance_owner._revoking
                        or acceptance_owner._invalid or acceptance_owner._uncertain
                        or acceptance_owner._busy or acceptance_owner._receipt is not accepted
                        or accepted._host_freshness is not attempt.acceptance_host_freshness):
                    return False
        except Exception:
            return False
        try:
            if self._worker._run_if_issued_completion_for_prepared_request_for_characterization(
                    history, prepared, self._worker_owner_claim, lambda: True) is not True:
                return False
        except Exception:
            return False

        # The original staging reservation stays completed and is checked
        # against the exact same ordered image observations; this preflight
        # reserves destination capacity only and never consumes another 19D write.
        try:
            capacity = self._capacity_owner
            active_promotion = (
                (operation, reservation, write_admission, estimate)
                if write_admission is not None else None
            )
            if (type(writer_owner) is not WindowsProtectedAssetsCharacterization
                    or capacity is None):
                return False
            if len(attempt.acceptance_observations) == 1:
                staging_matches = capacity._asset_stream_write_completed_for_characterization(
                    attempt.capacity_operation, attempt.writer_admission, writer_owner,
                    (prepared.request_id, remote.images[0].identity),
                    attempt.acceptance_observations[0],
                    active_promotion=active_promotion,
                )
            else:
                staging_matches = capacity._asset_stream_image_batch_write_completed_for_characterization(
                    attempt.capacity_operation, attempt.writer_admission, writer_owner,
                    attempt.acceptance_observations,
                    active_promotion=active_promotion,
                )
            if staging_matches is not True:
                return False
            if operation is not None or reservation is not None or estimate is not None:
                if (operation is None or reservation is None or type(estimate) is not CapacityEstimate
                        or (write_admission is None
                            and not capacity._profile_a_promotion_reservation_is_live_for_characterization(
                                operation, reservation, writer_owner, estimate))
                        or (write_admission is not None
                            and not capacity._profile_a_promotion_write_is_live_for_characterization(
                                operation, reservation, write_admission, writer_owner, estimate))):
                    return False
        except Exception:
            return False
        return True

    def _publish_profile_a_promotion_preflight_locked(
            self, lifecycle, attempt, marker, evidence, writer_observation,
            acceptance_observation, writer_owner, capacity_owner, operation,
            reservation, estimate):
        """Publish only a count-only reservation observation under the host gate."""
        if (type(capacity_owner) is not type(self._capacity_owner)
                or self._capacity_owner is not capacity_owner
                or self._profile_a_promotion_preflight_matches_locked(
                    lifecycle, attempt, marker, evidence, writer_observation,
                    acceptance_observation, writer_owner, operation=operation,
                    reservation=reservation, estimate=estimate) is not True):
            return None, "protected_promotion_preflight_host_changed"
        if (attempt.promotion_capacity_operation is not None
                or attempt.promotion_capacity_reservation is not None
                or attempt.promotion_preflight_observation is not None):
            return None, "protected_promotion_preflight_already_settled"
        accepted_count = acceptance_observation.accepted_image_count
        if type(accepted_count) is not int or not 1 <= accepted_count <= _MAX_WRITER_IMAGES:
            return None, "protected_promotion_preflight_incomplete"
        with lifecycle._lock:
            with writer_owner._lock:
                with capacity_owner._lock:
                    with self._lock:
                        if (self._storage_preadmission_attempts.get(
                                attempt.lease.request_index) is not attempt
                                or attempt.promotion_preflight_state != "in_progress"
                                or attempt.promotion_preflight_marker is not marker
                                or attempt.acceptance_observation is not acceptance_observation
                                or attempt.acceptance_state != "accepted_non_authoritative"
                                or attempt.cancel_requested
                                or attempt.promotion_capacity_operation is not None
                                or attempt.promotion_capacity_reservation is not None
                                or self._capacity_owner is not capacity_owner
                                or writer_owner._profile_a_capacity_owner is not capacity_owner
                                or not capacity_owner._profile_a_promotion_reservation_is_live_for_characterization(
                                    operation, reservation, writer_owner, estimate)):
                            return None, "protected_promotion_preflight_host_changed"
                        with attempt.acceptance_owner._lock:
                            accepted = attempt.accepted_batch
                            if (attempt.acceptance_owner._closed
                                    or attempt.acceptance_owner._revoking
                                    or attempt.acceptance_owner._invalid
                                    or attempt.acceptance_owner._uncertain
                                    or attempt.acceptance_owner._busy
                                    or attempt.acceptance_owner._receipt is not accepted):
                                return None, "protected_promotion_preflight_acceptance_changed"
                            observation = GenerationWorkerProtectedPromotionPreflightObservation(
                                status="protected_promotion_preflight_non_authoritative",
                                request_index=attempt.lease.request_index,
                                reserved_image_count=accepted_count,
                                _issuer=self,
                                _attempt_nonce=attempt.lease.nonce,
                            )
                            attempt.promotion_capacity_operation = operation
                            attempt.promotion_capacity_reservation = reservation
                            attempt.promotion_capacity_estimate = estimate
                            attempt.promotion_preflight_observation = observation
                            attempt.promotion_preflight_state = "reserved_non_authoritative"
                            return observation, "protected_promotion_preflight_non_authoritative"

    def _cancel_profile_a_promotion_preflight_reservation(self, attempt, observation=None):
        """Cancel only the exact still-reserved destination estimate; no file exists."""
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization

        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or (observation is not None
                        and attempt.promotion_preflight_observation is not observation)
                    or attempt.promotion_preflight_state not in {
                        "reserved_non_authoritative", "cancellation_requested",
                    }):
                return "promotion_preflight_unavailable"
            operation = attempt.promotion_capacity_operation
            reservation = attempt.promotion_capacity_reservation
            if operation is None or reservation is None:
                attempt.promotion_preflight_state = "refused"
                return "promotion_preflight_unavailable"
            attempt.promotion_preflight_state = "cancellation_in_progress"
            attempt.promotion_preflight_marker = None

        try:
            if type(self._capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization:
                raise ValueError("capacity_owner_unavailable")
            terminal = self._capacity_owner._reservation_terminal_state_for_characterization(
                operation, reservation,
            )
            if terminal == "cancelled":
                pass
            elif terminal == "reserved":
                self._capacity_owner.cancel_before_write_for_characterization(operation, reservation)
            else:
                raise ValueError("promotion_reservation_not_cancellable")
        except Exception:
            with self._lock:
                if self._storage_preadmission_attempts.get(
                        attempt.lease.request_index) is attempt:
                    attempt.promotion_preflight_state = "retained_uncertain"
            return "retained_uncertain"
        with self._lock:
            if self._storage_preadmission_attempts.get(
                    attempt.lease.request_index) is attempt:
                attempt.promotion_preflight_state = "cancelled"
        return "cancelled_before_write"

    def _publish_profile_a_acceptance_locked(
            self, lifecycle, attempt, marker, evidence, writer_owner,
            observation, acceptance_owner, accepted):
        """Publish count-only success at the original-host commit boundary."""
        from core.comfy_output_containment import (
            AcceptedProtectedOutputBatch, ProtectedOutputAcceptanceCharacterization,
        )

        if (type(acceptance_owner) is not ProtectedOutputAcceptanceCharacterization
                or type(accepted) is not AcceptedProtectedOutputBatch
                or acceptance_owner._protected_owner is not writer_owner
                or accepted._protected_owner is not writer_owner
                or accepted._envelope is not lifecycle._envelope
                or accepted._prepared is not attempt.prepared
                or accepted._remote is not attempt.remote_receipt
                or accepted._batch_receipt.observations is not attempt.acceptance_observations
                or accepted._host_freshness is not attempt.acceptance_host_freshness
                or accepted.image_count != observation.verified_image_count
                or not self._profile_a_acceptance_matches_locked(
                    lifecycle, attempt, marker, evidence, writer_owner, observation)):
            return None, "protected_acceptance_host_changed"

        # Serialize the final count-only publication against Writer, Capacity
        # and Acceptance close. Keep the established Writer -> Capacity ->
        # integration -> Acceptance order; no native I/O or callback runs in
        # this commit gate.
        capacity_owner = self._capacity_owner
        with writer_owner._lock:
            with capacity_owner._lock:
                if (self._capacity_owner is not capacity_owner
                        or writer_owner._profile_a_capacity_owner is not capacity_owner
                        or capacity_owner._closed or capacity_owner._invalid):
                    return None, "protected_acceptance_capacity_changed"
                if len(attempt.acceptance_observations) == 1:
                    ledger_matches = capacity_owner._asset_stream_write_completed_for_characterization(
                        attempt.capacity_operation, attempt.writer_admission, writer_owner,
                        (attempt.prepared.request_id,
                         attempt.remote_receipt.images[0].identity),
                        attempt.acceptance_observations[0],
                    )
                else:
                    ledger_matches = capacity_owner._asset_stream_image_batch_write_completed_for_characterization(
                        attempt.capacity_operation, attempt.writer_admission, writer_owner,
                        attempt.acceptance_observations,
                    )
                if ledger_matches is not True:
                    return None, "protected_acceptance_capacity_changed"
                with self._lock:
                    if (attempt.acceptance_state != "in_progress"
                            or attempt.acceptance_marker is not marker
                            or attempt.acceptance_owner is not acceptance_owner
                            or attempt.accepted_batch is not accepted):
                        return None, "protected_acceptance_already_settled"
                    key = (attempt.prepared.request_id, attempt.remote_receipt.identity)
                    profile_binding = writer_owner._profile_a_stream_batch_receipt_bindings.get(key)
                    if (writer_owner._closed or writer_owner._revoking
                            or writer_owner._invalid or writer_owner._uncertain
                            or writer_owner._stream_batches.get(key) is not accepted._batch_receipt
                            or writer_owner._stream_batch_acceptances.get(key) is not accepted
                            or type(profile_binding) is not tuple or len(profile_binding) != 10
                            or profile_binding[0] is not self
                            or profile_binding[1] is not attempt
                            or profile_binding[2] is not marker
                            or profile_binding[3] is not evidence
                            or profile_binding[4] is not capacity_owner
                            or profile_binding[5] is not attempt.capacity_operation
                            or profile_binding[6] is not attempt.reservation
                            or profile_binding[7] is not attempt.writer_admission
                            or profile_binding[8] is not attempt.acceptance_observations
                            or profile_binding[9] is not attempt.acceptance_host_freshness):
                        return None, "protected_acceptance_owner_changed"
                    with acceptance_owner._lock:
                        if (acceptance_owner._closed or acceptance_owner._revoking
                                or acceptance_owner._invalid or acceptance_owner._uncertain
                                or acceptance_owner._busy or acceptance_owner._receipt is not accepted
                                or acceptance_owner._protected_owner is not writer_owner
                                or acceptance_owner._batch_receipt is not accepted._batch_receipt
                                or acceptance_owner._host_freshness is not attempt.acceptance_host_freshness):
                            return None, "protected_acceptance_owner_changed"
                        attempt.acceptance_state = "accepted_non_authoritative"
                        accepted_observation = GenerationWorkerProtectedAcceptanceObservation(
                            status="protected_image_batch_accepted_non_authoritative",
                            request_index=attempt.lease.request_index,
                            accepted_image_count=accepted.image_count,
                        )
                        attempt.acceptance_observation = accepted_observation
                        return accepted_observation, "protected_image_batch_accepted_non_authoritative"

    def _retain_profile_a_acceptance_uncertain(self, attempt, marker):
        """Keep completed staging capacity uncertain after a failed Acceptance boundary."""
        with self._lock:
            if (self._storage_preadmission_attempts.get(attempt.lease.request_index) is not attempt
                    or attempt.acceptance_marker is not marker
                    or attempt.acceptance_state == "accepted_non_authoritative"):
                return False
            attempt.acceptance_state = "retained_uncertain"
            attempt.writer_handoff_state = "retained_uncertain"
            attempt.evidence_state = "uncertain"
            acceptance_owner = attempt.acceptance_owner
        if acceptance_owner is not None:
            try:
                acceptance_owner.invalidate_for_characterization()
            except Exception:
                pass
        try:
            observations = attempt.acceptance_observations
            if len(observations) == 1:
                self._capacity_owner.retain_completed_asset_stream_write_uncertain_for_characterization(
                    attempt.capacity_operation, attempt.writer_admission,
                    attempt.writer_owner, observations[0],
                )
            else:
                self._capacity_owner.retain_completed_asset_stream_batch_uncertain_for_characterization(
                    attempt.capacity_operation, attempt.writer_admission,
                    attempt.writer_owner, observations,
                )
        except Exception:
            try:
                with self._capacity_owner._lock:
                    self._capacity_owner._invalidate()
            except Exception:
                pass
        return True

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
        promotion_reservations_to_cancel = []
        promotion_publications_to_retain = []
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
                admission_in_progress = (
                    attempt.protected_candidate_admission_state == "in_progress"
                )
                candidate_publication_in_progress = (
                    attempt.protected_candidate_publication_state == "in_progress"
                )
                if admission_in_progress:
                    # The genuine Admission owner may be inside native
                    # verification. Keep its exact private owner/result and
                    # retain the settled protected Promotion; never compensate
                    # or route this operation through staging cancellation.
                    attempt.protected_candidate_admission_state = "retained_uncertain"
                if candidate_publication_in_progress:
                    # Candidate append may be inside the existing publisher's
                    # original-Host commit gate. Preserve that one-shot attempt
                    # as uncertain; never issue a second Gallery writer call.
                    attempt.protected_candidate_publication_state = "retained_uncertain"
                if attempt.candidate_admission_state == "in_progress":
                    # This is downstream eligibility uncertainty only. The
                    # already-published Promotion and its completed capacity
                    # evidence remain settled and are never compensated here.
                    attempt.candidate_admission_state = "retained_uncertain"
                    attempt.candidate_admission_observation = None
                    # This attempt has already crossed every staging and
                    # Promotion boundary. Do not route it through the older
                    # pre-admission cancellation branch below.
                    continue
                if admission_in_progress:
                    continue
                if candidate_publication_in_progress:
                    continue
                if attempt.state in {"preparing", "reserved", "pre_admitted"}:
                    attempt.cancel_requested = True
                    if attempt.acceptance_state == "accepted_non_authoritative":
                        # A settled Acceptance owns completed staging evidence.
                        # Host retirement must not reinterpret its completed
                        # 19D write as a cancellable staging pre-admission.
                        if attempt.promotion_preflight_state == "in_progress":
                            attempt.promotion_preflight_marker = None
                            attempt.promotion_preflight_state = "cancellation_requested"
                        elif attempt.promotion_preflight_state == "reserved_non_authoritative":
                            attempt.promotion_preflight_state = "cancellation_requested"
                            promotion_reservations_to_cancel.append(
                                (attempt, attempt.promotion_preflight_observation),
                            )
                        elif attempt.promotion_preflight_state in {
                                "promotion_claiming", "promotion_admitting", "promotion_admitted",
                                "promotion_may_have_created", "private_committed_host_publication_pending"}:
                            # The writer path owns cancellation from this point.
                            # It may still be before CREATE_NEW, have a live
                            # token, or already have retained native evidence;
                            # revoke must not guess and release that capacity.
                            attempt.cancel_requested = True
                            if attempt.promotion_preflight_state == (
                                    "private_committed_host_publication_pending"):
                                attempt.promotion_preflight_state = "retained_uncertain"
                                attempt.promotion_publication_state = "retained_uncertain"
                                promotion_publications_to_retain.append(
                                    (attempt, attempt.promotion_publication_marker),
                                )
                        continue
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
        for attempt, observation in promotion_reservations_to_cancel:
            # This exact destination reservation cannot have crossed CREATE_NEW:
            # the fallback preflight never issues a Writer admission.
            self._cancel_profile_a_promotion_preflight_reservation(attempt, observation)
        for attempt, marker in promotion_publications_to_retain:
            # The private CREATE_NEW/ledger commit already happened. Preserve
            # its exact destination estimate as uncertain before the owner can
            # release the cross-process scope marker.
            self._retain_profile_a_promotion_publication_uncertain(attempt, marker)
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
