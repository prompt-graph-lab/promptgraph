"""C2B-8D-10 exact protected-promotion admission observation.

This owner records whether one exact protected promotion currently matches the
original host and its accepted ``outputs_ready`` event. The immutable result is
evidence only: it is not a Candidate writer, publication approval, save
authority, or legacy receipt.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import copy
import hashlib
import json
import threading

from core.comfy_output_containment import AcceptedProtectedOutputBatch
from core.comfy_remote_output_receipts import RemoteImageDescriptor, RemoteOutputReceipt
from core.generation_windows_protected_promotion import (
    ProtectedDurablePromotionCharacterization,
    ProtectedPromotedImage,
    VerifiedProtectedPromotionReceipt,
)
from core.generation_windows_protected_assets import (
    VerifiedProtectedImageBatchReceipt,
    VerifiedProtectedImageObservation,
)
from ui.agent_generation_executor_handoff import GenerationPublicationOrigin
from ui.agent_generation_executor_inbox import ExecutionEnvelope, ExecutorEvent, OutputReceipt
from ui.agent_generation_job import JobRequest, WorkerEvent, _PROCESS_INCARNATION, _TERMINAL
from ui.project_agent_session_pump import ProjectAgentSessionRuntime


@dataclass(frozen=True)
class ProtectedCandidateAdmissionObservation:
    """Private immutable evidence; identity is a content label, not authority."""

    identity: str
    request_index: int
    _runtime: object = field(repr=False, compare=False)
    _origin: GenerationPublicationOrigin = field(repr=False, compare=False)
    _envelope: ExecutionEnvelope = field(repr=False, compare=False)
    _project: object = field(repr=False, compare=False)
    _source_snapshot: object = field(repr=False, compare=False)
    _promotion_owner: ProtectedDurablePromotionCharacterization = field(repr=False, compare=False)
    _promotion_receipt: VerifiedProtectedPromotionReceipt = field(repr=False, compare=False)
    _remote_receipt: RemoteOutputReceipt = field(repr=False, compare=False)
    _remote_event: ExecutorEvent = field(repr=False, compare=False)
    _outputs_ready_event: ExecutorEvent = field(repr=False, compare=False)


@dataclass(frozen=True)
class ProtectedCandidateAdmissionResult:
    status: str
    request_index: int | None = None
    observation: ProtectedCandidateAdmissionObservation | None = field(default=None, repr=False)


@dataclass
class _Attempt:
    promotion_owner: object
    receipt: object
    remote: object
    status: str
    result: ProtectedCandidateAdmissionResult | None = None


class GenerationProtectedCandidateAdmission:
    """One runtime-pinned, one-shot observation owner for protected promotion."""

    execution_available = False
    candidate_publication_allowed = False
    project_save_allowed = False
    protected_storage_available = False
    promotion_available = False
    authorship = "unverified"

    @classmethod
    def create_for_characterization(
            cls, state, runtime, envelope, *, characterization=False, disposable_opt_in=False):
        if characterization is not True or disposable_opt_in is not True:
            raise ValueError("execution_unavailable")
        if (type(runtime) is not ProjectAgentSessionRuntime
                or type(envelope) is not ExecutionEnvelope
                or not runtime.generation_jobs._characterization
                or not runtime._generation_executor_inbox._characterization):
            raise ValueError("admission_unavailable")
        origin = runtime._generation_publication_origin
        if (type(origin) is not GenerationPublicationOrigin or origin.envelope is not envelope
                or origin.project is None or origin.source_snapshot is None
                or type(origin.path) is not str or not origin.path):
            raise ValueError("original_host_required")
        try:
            expected = copy.deepcopy(origin.source_snapshot)
        except Exception as error:
            raise ValueError("source_snapshot_unavailable") from error
        owner = cls(state, runtime, envelope, origin, expected)
        with runtime._publication_gate:
            if runtime._closed or runtime._registration is None:
                raise ValueError("original_host_unavailable")
            route = runtime._registry._record_for_registration(runtime._registration)
            if route is None:
                raise ValueError("original_host_unavailable")
            with route.operation_lock:
                try:
                    epoch = runtime._synchronize_target_locked(
                        state.get("project"), state.get("current_project_path", ""))
                    available, pairing = runtime._registration.inspect_pairing_generation()
                    source_current = (runtime._generation_publication_origin is origin
                        and state.get("project") is origin.project
                        and state.get("current_project_path", "") == origin.path
                        and origin.source_snapshot == expected
                        and origin.project == expected)
                except Exception:
                    source_current, available, pairing, epoch = False, False, None, None
                if (not source_current or not available
                        or (epoch, epoch) != (envelope.binding.target_epoch, envelope.binding.activation_id)
                        or pairing != envelope.binding.pairing_generation
                        or getattr(runtime, "_generation_protected_candidate_admission", None) is not None):
                    raise ValueError("original_host_unavailable")
                runtime._generation_protected_candidate_admission = owner
        return owner

    def __init__(self, state, runtime, envelope, origin, source_snapshot):
        self._state = state
        self._runtime = runtime
        self._envelope = envelope
        self._origin = origin
        self._source_snapshot = source_snapshot
        # Candidate publication advances only the exact in-memory Candidate
        # delta. The original source snapshot above remains immutable evidence.
        self._candidate_expected = copy.deepcopy(source_snapshot)
        self._lock = threading.RLock()
        self._closed = False
        self._attempts = {}

    def _receipt_binding(self, promotion_owner, receipt, remote, index):
        if (type(promotion_owner) is not ProtectedDurablePromotionCharacterization
                or type(receipt) is not VerifiedProtectedPromotionReceipt
                or type(remote) is not RemoteOutputReceipt
                or type(index) is not int or not 0 <= index < len(self._envelope.manifest.requests)):
            return False
        try:
            accepted = receipt._accepted
            if (type(accepted) is not AcceptedProtectedOutputBatch
                    or type(accepted._batch_receipt) is not VerifiedProtectedImageBatchReceipt
                    or type(remote.images) is not tuple
                    or not remote.images
                    or any(type(item) is not RemoteImageDescriptor for item in remote.images)
                    or type(receipt.images) is not tuple
                    or any(type(row) is not ProtectedPromotedImage for row in receipt.images)):
                return False
            prepared = accepted._prepared
            request = self._envelope.manifest.requests[index]
            descriptors = tuple(item.identity for item in remote.images)
            rows = receipt.images
            observations = accepted._batch_receipt.observations
            return bool(
                type(observations) is tuple
                and all(type(observation) is VerifiedProtectedImageObservation for observation in observations)
                and promotion_owner._receipt is receipt
                and receipt._promotion_owner is promotion_owner
                and receipt._protected_owner is promotion_owner._protected_owner
                and receipt._acceptance_owner is promotion_owner._acceptance_owner
                and receipt._accepted is promotion_owner._accepted is accepted
                and accepted._envelope is self._envelope
                and accepted._prepared is prepared
                and accepted._remote is remote
                and prepared.request_index == index
                and prepared.request_id == request.request_id
                and prepared.workflow_identity == request.workflow_identity
                and remote.request_index == index
                and remote.request_id == request.request_id
                and remote.workflow_identity == request.workflow_identity
                and remote.execution_succeeded is True
                and (receipt.job_id, receipt.claim_id, receipt.manifest_identity,
                     receipt.request_id, receipt.request_index, receipt.workflow_identity,
                     receipt.prompt_id, receipt.remote_receipt_identity)
                    == (self._envelope.job_id, self._envelope.claim_id,
                        self._envelope.manifest.manifest_identity, request.request_id,
                        index, request.workflow_identity, remote.prompt_id, remote.identity)
                and len(descriptors) == len(set(descriptors))
                and len(rows) == len(descriptors)
                and len(observations) == len(descriptors)
                and tuple(observation.descriptor_identity for observation in observations) == descriptors
                and tuple(row.descriptor_identity for row in rows) == descriptors
                and all(row.source_observation is observation
                        for row, observation in zip(rows, observations))
                and all(row.promoted_image.purpose == "promoted_assets" for row in rows))
        except Exception:
            return False

    @contextmanager
    def _locked_request_events_for_characterization(self, remote, receipt, index, pairing):
        """Hold exact current job/inbox event evidence for a bounded decision."""
        runtime, envelope = self._runtime, self._envelope
        jobs, inbox = runtime.generation_jobs, runtime._generation_executor_inbox
        with jobs._lock:
            jobs._cleanup_locked(jobs._clock())
            job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
            with inbox._lock:
                if (not jobs._characterization or jobs._closed or not inbox._characterization
                        or inbox._closed or inbox._state != "accepted"
                        or inbox._envelope is not envelope
                        or inbox._manifest is not envelope.manifest
                        or job is None or job.binding != envelope.binding
                        or job.binding.session_id != jobs._session_incarnation
                        or job.binding.process_incarnation != _PROCESS_INCARNATION
                        or job.binding.plan_identity != envelope.manifest.manifest_identity
                        or (job.binding.target_epoch, job.binding.activation_id) != jobs._target
                        or job.binding.pairing_generation != pairing
                        or job.state in _TERMINAL
                        or index >= len(job.request_states)
                        or job.request_states[index] != "awaiting_host_registration"
                        or job.outputs[index] != len(remote.images)
                        or job.remote_outputs[index] != len(remote.images)
                        or job.registered[index] != 0
                        or job.requests[index] != JobRequest(
                            envelope.manifest.requests[index].request_id,
                            envelope.manifest.requests[index].illustration_id,
                            envelope.manifest.requests[index].run_index,
                            envelope.manifest.requests[index].workflow_identity)):
                    yield None
                    return
                if any(type(event) is not ExecutorEvent
                       or type(event.progress) is not WorkerEvent
                       for event in inbox._events.values()):
                    yield None
                    return
                index_events = tuple((sequence, event) for sequence, event in inbox._events.items()
                    if event.progress.request_index == index
                    and event.progress.kind in {"remote_outputs_ready", "outputs_ready"})
                late_outputs = tuple(event for event in inbox._late
                    if getattr(getattr(event, "progress", None), "request_index", None) == index
                    and getattr(getattr(event, "progress", None), "kind", None) == "outputs_ready")
                remote_events = tuple((sequence, event) for sequence, event in index_events
                    if event.progress.kind == "remote_outputs_ready")
                output_events = tuple((sequence, event) for sequence, event in index_events
                    if event.progress.kind == "outputs_ready")
                if late_outputs or len(remote_events) != 1 or len(output_events) != 1:
                    yield None
                    return
                remote_sequence, remote_event = remote_events[0]
                output_sequence, output_event = output_events[0]
                count = len(remote.images)
                if (type(remote_event.outputs) is not OutputReceipt
                        or type(output_event.outputs) is not OutputReceipt
                        or remote_sequence != remote_event.progress.sequence
                        or output_sequence != output_event.progress.sequence
                        or remote_sequence >= output_sequence or output_sequence != job.event_count
                        or output_sequence not in job.events or remote_sequence not in job.events
                        or job.events[remote_sequence] != remote_event.progress
                        or job.events[output_sequence] != output_event.progress
                        or (remote_event.job_id, remote_event.claim_id, remote_event.manifest_identity)
                            != (envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity)
                        or (remote_event.outputs.receipt_id, remote_event.outputs.output_count,
                            remote_event.progress.output_count)
                            != (remote.identity[:32], count, count)
                        or (output_event.job_id, output_event.claim_id, output_event.manifest_identity)
                            != (envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity)
                        or (output_event.outputs.receipt_id, output_event.outputs.output_count,
                            output_event.progress.output_count)
                            != (receipt.identity[:32], count, count)):
                    yield None
                    return
                yield remote_event, output_event

    @contextmanager
    def _host_evidence(self, promotion_owner, receipt, remote, index):
        """Hold the final host/owner/job/inbox evidence through result issue."""
        runtime, envelope = self._runtime, self._envelope
        jobs, inbox = runtime.generation_jobs, runtime._generation_executor_inbox
        with runtime._publication_gate:
            if runtime._closed or runtime._registration is None:
                yield None
                return
            route = runtime._registry._record_for_registration(runtime._registration)
            if route is None:
                yield None
                return
            with route.operation_lock:
                try:
                    epoch = runtime._synchronize_target_locked(
                        self._state.get("project"), self._state.get("current_project_path", ""))
                    available, pairing = runtime._registration.inspect_pairing_generation()
                    source_current = (not self._closed
                        and runtime._generation_publication_origin is self._origin
                        and runtime._generation_protected_candidate_admission is self
                        and self._origin.envelope is envelope
                        and self._state.get("project") is self._origin.project
                        and self._state.get("current_project_path", "") == self._origin.path
                        and self._origin.source_snapshot == self._source_snapshot
                        and self._origin.project == self._candidate_expected)
                except Exception:
                    source_current, available, pairing, epoch = False, False, None, None
                if (not source_current or not available
                        or (epoch, epoch) != (envelope.binding.target_epoch, envelope.binding.activation_id)
                        or pairing != envelope.binding.pairing_generation):
                    yield None
                    return
                # This guard performs no callbacks or native I/O. It serializes
                # close/invalidation against the final observation commit.
                with promotion_owner._admission_custody_guard_for_characterization(receipt) as custody_current:
                    if not custody_current:
                        yield None
                        return
                    with self._locked_request_events_for_characterization(
                            remote, receipt, index, pairing) as evidence:
                        yield evidence

    def admit_for_characterization(self, promotion_owner, receipt, remote, request_index):
        """Observe exact current eligibility; never appends Candidates or saves."""
        if not self._receipt_binding(promotion_owner, receipt, remote, request_index):
            return ProtectedCandidateAdmissionResult("receipt_mismatch", request_index)
        with self._lock:
            if self._closed:
                return ProtectedCandidateAdmissionResult("unavailable", request_index)
            previous = self._attempts.get(request_index)
            if previous is not None:
                exact = (previous.promotion_owner is promotion_owner and previous.receipt is receipt
                         and previous.remote is remote)
                if not exact:
                    return ProtectedCandidateAdmissionResult("receipt_conflict", request_index)
                return ProtectedCandidateAdmissionResult(
                    ("duplicate_observed" if previous.status == "observed" else "duplicate_uncertain")
                    if previous.result is not None else "admission_in_progress",
                    request_index, previous.result.observation if previous.result else None)
        with self._lock:
            if self._closed:
                return ProtectedCandidateAdmissionResult("unavailable", request_index)
            previous = self._attempts.get(request_index)
            if previous is not None:
                return ProtectedCandidateAdmissionResult("admission_in_progress", request_index)
            attempt = _Attempt(promotion_owner, receipt, remote, "checking")
            self._attempts[request_index] = attempt

        # Preflight avoids native work for stale host/event evidence. It still
        # consumes this exact one-shot attempt and retains the refusal.
        with self._host_evidence(promotion_owner, receipt, remote, request_index) as evidence:
            if evidence is None:
                with self._lock:
                    attempt.status = "uncertain"
                    attempt.result = ProtectedCandidateAdmissionResult(
                        "host_or_event_unavailable", request_index)
                    return attempt.result

        try:
            # Native file/ACL/content checks and host-freshness callbacks run
            # outside runtime, job, inbox and protected-owner locks.
            if promotion_owner._inspect_for_candidate_admission_for_characterization(
                    receipt, self._host_freshness_for_admission) is not receipt:
                raise ValueError("promotion_unavailable")
        except Exception:
            with self._lock:
                attempt.status = "uncertain"
                attempt.result = ProtectedCandidateAdmissionResult("promotion_uncertain", request_index)
                return attempt.result

        with self._host_evidence(promotion_owner, receipt, remote, request_index) as evidence:
            if evidence is None:
                with self._lock:
                    attempt.status = "uncertain"
                    attempt.result = ProtectedCandidateAdmissionResult("stale_original_host", request_index)
                    return attempt.result
            remote_event, output_event = evidence
            payload = ["promptgraph.protected-candidate-admission.v1",
                self._envelope.job_id, self._envelope.claim_id,
                self._envelope.manifest.manifest_identity, request_index,
                receipt.identity, remote.identity, remote_event.progress.sequence,
                output_event.progress.sequence]
            observation = ProtectedCandidateAdmissionObservation(
                hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest(),
                request_index, self._runtime, self._origin, self._envelope,
                self._origin.project, self._source_snapshot, promotion_owner, receipt,
                remote, remote_event, output_event)
            result = ProtectedCandidateAdmissionResult("evidence_observed", request_index, observation)
            with self._lock:
                if self._closed:
                    attempt.status = "uncertain"
                    attempt.result = ProtectedCandidateAdmissionResult("unavailable", request_index)
                    return attempt.result
                attempt.status = "observed"
                attempt.result = result
                return result

    @contextmanager
    def _candidate_publication_commit_for_characterization(self, observation):
        """Serialize one app Candidate commit with exact host and protected custody.

        Native checks must run immediately before entering this context. The
        context keeps only the original-host publication/route gates across
        the app callback. Protected and job/inbox locks are released before
        yielding; the promotion owner's revocation lease keeps custody live.
        """
        if (type(observation) is not ProtectedCandidateAdmissionObservation
                or observation._runtime is not self._runtime
                or observation._origin is not self._origin
                or observation._envelope is not self._envelope):
            yield None
            return
        index = observation.request_index
        promotion_owner = observation._promotion_owner
        receipt = observation._promotion_receipt
        remote = observation._remote_receipt
        with self._lock:
            attempt = self._attempts.get(index)
            owned = bool(not self._closed and attempt is not None
                and attempt.status == "observed"
                and attempt.promotion_owner is promotion_owner
                and attempt.receipt is receipt and attempt.remote is remote
                and attempt.result is not None
                and attempt.result.status == "evidence_observed"
                and attempt.result.observation is observation)
        if not owned or not self._receipt_binding(promotion_owner, receipt, remote, index):
            yield None
            return

        runtime, envelope = self._runtime, self._envelope
        with runtime._publication_gate:
            if runtime._closed or runtime._registration is None:
                yield None
                return
            route = runtime._registry._record_for_registration(runtime._registration)
            if route is None:
                yield None
                return
            with route.operation_lock:
                try:
                    epoch = runtime._synchronize_target_locked(
                        self._state.get("project"), self._state.get("current_project_path", ""))
                    available, pairing = runtime._registration.inspect_pairing_generation()
                    with self._lock:
                        attempt = self._attempts.get(index)
                        source_current = (not self._closed
                            and runtime._generation_publication_origin is self._origin
                            and runtime._generation_protected_candidate_admission is self
                            and attempt is not None and attempt.result is not None
                            and attempt.result.observation is observation
                            and self._origin.envelope is envelope
                            and self._state.get("project") is self._origin.project
                            and self._state.get("current_project_path", "") == self._origin.path
                            and self._origin.source_snapshot == self._source_snapshot
                            and self._origin.project == self._candidate_expected)
                except Exception:
                    source_current, available, pairing, epoch = False, False, None, None
                if (not source_current or not available
                        or (epoch, epoch) != (envelope.binding.target_epoch, envelope.binding.activation_id)
                        or pairing != envelope.binding.pairing_generation):
                    yield None
                    return

                token, events = None, None
                with promotion_owner._admission_custody_guard_for_characterization(receipt) as current:
                    if current:
                        with self._locked_request_events_for_characterization(
                                remote, receipt, index, pairing) as current_events:
                            if (current_events is not None
                                    and current_events[0] is observation._remote_event
                                    and current_events[1] is observation._outputs_ready_event):
                                token = promotion_owner.begin_candidate_publication_for_characterization(receipt)
                                events = current_events
                if token is None:
                    yield None
                    return
                try:
                    yield events
                finally:
                    promotion_owner.finish_candidate_publication_for_characterization(token)

    def _advance_candidate_snapshot_for_characterization(self, observation, before, after):
        """Track only the exact successful Candidate delta for the next request."""
        if (type(observation) is not ProtectedCandidateAdmissionObservation
                or observation._runtime is not self._runtime
                or observation._origin is not self._origin):
            return False
        index = observation.request_index
        try:
            with self._lock:
                attempt = self._attempts.get(index)
                if (self._closed or attempt is None or attempt.result is None
                        or attempt.result.observation is not observation
                        or self._candidate_expected != before
                        or self._origin.source_snapshot != self._source_snapshot
                        or self._origin.project != after):
                    return False
                self._candidate_expected = copy.deepcopy(after)
                return self._candidate_expected == self._origin.project
        except Exception:
            return False

    def _host_freshness_for_admission(self, envelope, remote):
        """Recheck the exact original host after its accepted outputs_ready event."""
        if envelope is not self._envelope:
            return False
        index = getattr(remote, "request_index", -1)
        with self._lock:
            attempt = self._attempts.get(index)
            if attempt is None or attempt.remote is not remote or self._closed:
                return False
            promotion_owner, receipt = attempt.promotion_owner, attempt.receipt
        with self._host_evidence(promotion_owner, receipt, remote, index) as evidence:
            return evidence is not None

    def _close_under_runtime_gate(self):
        with self._lock:
            self._closed = True

    def close(self):
        with self._runtime._publication_gate:
            self._close_under_runtime_gate()

    def readiness(self):
        with self._lock:
            return {
                "admission": "closed" if self._closed else "observed" if self._attempts else "available",
                "attempt_count": len(self._attempts),
                "execution_available": False,
                "protected_storage_available": False,
                "promotion_available": False,
                "candidate_publication_allowed": False,
                "project_save_allowed": False,
                "authorship": "unverified",
            }
