"""Non-executing host ownership for a supplied Worker and protected roots.

This owner only binds references and retains bounded diagnostic observations.
It never starts or performs Worker I/O, invokes a Journal/storage/promotion
writer, advances the Job Registry/Inbox, or grants publication authority.
"""

from collections import deque
from dataclasses import dataclass, field
import threading
import uuid
import weakref


_FACTORY = object()
_MAX_OBSERVATIONS = 16
_MAX_HISTORY_READS_PER_REQUEST = 16
_PURPOSES = (
    "private_journal", "temporary_containment", "retained_uncertain",
    "promoted_assets", "selected_project_json",
)


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
    """One exact lifecycle's supplied Worker/root references, permanently inert."""

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
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._worker_storage_integration is not None):
                return None, "lifecycle_unavailable"

        worker_view = worker.observation_for_characterization()
        if (worker_view.state not in {"created", "running"}
                or worker_view.in_flight or worker_view.accepted_operations
                or worker_view.completed_operations or worker_view.uncertain_submissions):
            return None, "worker_unavailable"

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
            lifecycle._worker_storage_integration = owner
        return owner, "bound_non_executing"

    def __init__(self, lifecycle, runtime, worker, purpose_roots, capacity_owner, *, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("original_host_binding_required")
        self._lifecycle_ref = weakref.ref(lifecycle)
        self._runtime_ref = weakref.ref(runtime)
        self._lifecycle_generation = lifecycle._generation
        self._worker = worker
        self._purpose_roots = dict(purpose_roots)
        self._capacity_owner = capacity_owner
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
        self._observations = deque(maxlen=_MAX_OBSERVATIONS)
        self._close_call_active = False
        self._last_worker_state = "created"

    def correlation_for_request_for_characterization(self, request_index, *, kind, prompt_id=None):
        """Issue scalars for an exact manifest member; never perform the Worker."""
        from core.comfy_remote_output_receipts import valid_prompt_id
        from ui.agent_generation_http_io_worker import HTTPIOCorrelation

        lifecycle = self._lifecycle_ref()
        if (lifecycle is None or type(request_index) is not int
                or kind not in {"submission", "history"}):
            return None
        if not self._root_binding_matches():
            self.revoke("host_evidence_unavailable")
            return None
        # Match the 19A host order: lifecycle -> integration. Revocation never
        # acquires these locks in the opposite order.
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._generation != self._lifecycle_generation
                    or lifecycle._envelope is None or not self._root_binding_matches()):
                return None
            with self._lock:
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
        from core.comfy_prompt_request import (
            _frozen_fields, is_owner_prepared_frozen_request,
            prepare_frozen_prompt_request,
        )
        from ui.agent_generation_http_io_worker import HTTPIOCorrelation

        if (kind not in {"submission", "history"}
                or type(correlation) is not HTTPIOCorrelation
                or not is_owner_prepared_frozen_request(prepared)):
            return None, "invalid_operation"
        lifecycle = self._lifecycle_ref()
        if lifecycle is None:
            return None, "lifecycle_unavailable"
        if not self._root_binding_matches():
            self.revoke("host_evidence_unavailable")
            return None, "storage_binding_mismatch"
        with lifecycle._lock:
            if (lifecycle._state != "bound_non_executing"
                    or lifecycle._generation != self._lifecycle_generation
                    or lifecycle._envelope is None or not self._root_binding_matches()):
                return None, "stale_non_authoritative"
            with self._lock:
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
                if kind == "submission":
                    self._submitted.add((kind, index, correlation.attempt_id))
                lease = GenerationWorkerOperationLease(
                    lifecycle._generation, uuid.uuid4().hex, kind, index, correlation,
                )
                self._active = lease
                return lease, "admitted_non_executing"

    def _root_binding_matches(self):
        """Check exact owner references only; never touch the filesystem."""
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_storage import WindowsProtectedRootCharacterization

        roots = self._purpose_roots
        capacity = self._capacity_owner
        try:
            owned_roots = capacity._roots
            return (
                type(capacity) is WindowsProtectedStorageAdmissionCharacterization
                and capacity._closed is False and capacity._invalid is False
                and type(roots) is dict and set(roots) == set(_PURPOSES)
                and type(owned_roots) is dict and set(owned_roots) == set(_PURPOSES)
                and all(
                    type(roots[purpose]) is WindowsProtectedRootCharacterization
                    and roots[purpose]._purpose == purpose
                    and roots[purpose]._closed is False
                    and owned_roots[purpose] is roots[purpose]
                    for purpose in _PURPOSES
                )
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
        # This is a nonjoining Worker state transition. The bounded join and
        # terminal observation happen only from an explicit host call after
        # runtime/lifecycle/registry/job/inbox locks have been released.
        if worker is not None:
            worker_view = worker.request_close_for_characterization()
            with self._lock:
                if self._state == "revocation_requested":
                    self._state = "close_pending" if worker_view.thread_alive else "closed"
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
                protected_binding="matched_reference_only",
            )

    def readiness(self):
        if not self._root_binding_matches():
            return self.revoke("host_evidence_unavailable")
        return self._safe_state()
