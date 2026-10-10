"""Private capacity-one execution custody, isolated from production and MCP.

No thread, transport, filesystem, callback or Project owner lives here. All
registry/inbox operations acquire the existing job lock before the inbox lock.
The future executor takes an envelope once, then sends correlated typed events
to the original host. Tests simulate that boundary synchronously.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import hashlib
import threading
import time
import uuid

from core.generation_executable_manifest import (
    FinalizedManifest, FinalizedRequest, MAX_AGGREGATE_BYTES, MAX_WORKFLOW_BYTES,
)
from ui.agent_generation_job import (
    GenerationJobRegistry, JobBinding, WorkerEvent, MAX_REQUESTS, MAX_RUNS,
    _TERMINAL, _digest, _token, _valid_binding, MAX_EVENTS, MAX_OUTPUTS_PER_REQUEST, MAX_EVENT_HISTORY,
)

CAPACITY = 1
RESERVATION_TTL = 30
MAX_LATE_RECEIPTS = 16
MAX_ID_CHARS = 160


@dataclass(frozen=True)
class InboxReservation:
    status: str
    reservation_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class ExecutionEnvelope:
    binding: JobBinding = field(repr=False)
    origin_identity: str = field(repr=False)
    manifest: FinalizedManifest = field(repr=False)
    job_id: str
    claim_id: str = field(repr=False)


@dataclass(frozen=True)
class HandoffReceipt:
    """No exception text, destination, workflow or output path in receipts."""
    status: str
    job_id: str | None = None
    claim_id: str | None = field(default=None, repr=False)
    manifest_identity: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class OutputReceipt:
    """Opaque future recovery handle; count evidence is never publication."""
    receipt_id: str
    output_count: int


@dataclass(frozen=True)
class ExecutorEvent:
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str = field(repr=False)
    progress: WorkerEvent
    outputs: OutputReceipt | None = None


def _bounded_manifest(manifest):
    if (type(manifest) is not FinalizedManifest or type(manifest.requests) is not tuple
            or not 1 <= len(manifest.requests) <= MAX_REQUESTS
            or type(manifest.host_config_json) is not bytes
            or not 0 < len(manifest.host_config_json) <= MAX_AGGREGATE_BYTES
            or type(manifest.seed_policy) is not str
            or manifest.seed_policy not in {"random_u64", "preserve_u64"}
            or not _digest(manifest.source_identity) or not _digest(manifest.manifest_identity)
            or any(type(s) is not str or not 1 <= len(s) <= MAX_ID_CHARS
                   for s in (manifest.proposal_id, manifest.plan_id, manifest.scene_id))):
        return False
    size = len(manifest.host_config_json)
    ids, runs = set(), set()
    for index, request in enumerate(manifest.requests):
        if (type(request) is not FinalizedRequest or type(request.request_index) is not int
                or request.request_index != index or type(request.run_index) is not int
                or not 1 <= request.run_index <= MAX_RUNS
                or any(type(s) is not str or not 1 <= len(s) <= MAX_ID_CHARS
                       for s in (request.request_id, request.illustration_id))
                or request.request_id in ids or (request.illustration_id, request.run_index) in runs
                or type(request.workflow_json) is not bytes
                or not 0 < len(request.workflow_json) <= MAX_WORKFLOW_BYTES
                or type(request.seed_provenance_json) is not bytes
                or not 0 < len(request.seed_provenance_json) <= MAX_AGGREGATE_BYTES
                or not _digest(request.workflow_identity)
                or hashlib.sha256(request.workflow_json).hexdigest() != request.workflow_identity):
            return False
        ids.add(request.request_id)
        runs.add((request.illustration_id, request.run_index))
        size += len(request.workflow_json) + len(request.seed_provenance_json)
        if size > MAX_AGGREGATE_BYTES:
            return False
    return size <= MAX_AGGREGATE_BYTES


class GenerationExecutorInbox:
    """One session-owned slot, not a second job registry or planning path.

    Reservation has no job/Start authority. Committed ownership is one-shot;
    an unknown handoff pins the slot until session close, never enabling retry.
    Registry lease expiry fences progress but does not prove remote cancellation.
    """
    execution_available = False

    def __init__(self, *, clock=time.monotonic, characterization=False):
        if type(characterization) is not bool:
            raise ValueError("invalid characterization mode")
        self._clock = clock
        self._characterization = characterization
        self._lock = threading.RLock()
        self._closed = False
        self._reservation = None
        self._deadline = 0
        self._manifest = None
        self._envelope = None
        self._state = "empty"
        self._late = deque(maxlen=MAX_LATE_RECEIPTS)
        self._events = OrderedDict()

    def reserve_for_characterization(self, manifest):
        if not self._characterization:
            return InboxReservation("execution_unavailable")
        if not _bounded_manifest(manifest):
            return InboxReservation("invalid_payload")
        now = self._clock()
        with self._lock:
            if self._closed:
                return InboxReservation("unavailable")
            if self._state == "reserved" and now >= self._deadline:
                self._clear_locked()
            if self._state != "empty":
                return InboxReservation("capacity_unavailable")
            self._reservation = uuid.uuid4().hex
            self._deadline = now + RESERVATION_TTL
            self._manifest = manifest
            self._state = "reserved"
            return InboxReservation("reserved", self._reservation)

    def release_reservation(self, reservation):
        with self._lock:
            if (type(reservation) is InboxReservation and self._state == "reserved"
                    and self._reservation == reservation.reservation_id):
                self._clear_locked()

    def _commit_locked(self, reservation, envelope):
        """Caller holds job then inbox lock and consumes host custody together."""
        if (self._closed or self._state != "reserved" or type(reservation) is not InboxReservation
                or reservation.reservation_id != self._reservation
                or type(envelope) is not ExecutionEnvelope or envelope.manifest is not self._manifest
                or not _valid_binding(envelope.binding) or not _digest(envelope.origin_identity)
                or not _token(envelope.job_id) or not _token(envelope.claim_id)):
            return False
        self._envelope = envelope
        self._state = "offered"
        return True

    def accept_for_characterization(self, jobs, receipt):
        """Take exactly once. Production callers cannot obtain an envelope."""
        if not self._characterization or not jobs._characterization:
            return HandoffReceipt("execution_unavailable"), None
        with jobs._lock:
            jobs._cleanup_locked(jobs._clock())
            with self._lock:
                envelope = self._matching_locked(receipt)
                if envelope is None:
                    return HandoffReceipt("stale_receipt"), None
                job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                if self._closed or job is None or job.state in _TERMINAL:
                    return HandoffReceipt("invalidated", envelope.job_id), None
                if self._state != "offered":
                    return HandoffReceipt("duplicate_acceptance", envelope.job_id), None
                self._state = "accepted"
                return self._receipt_locked("accepted"), envelope

    def settle_for_characterization(self, jobs, receipt, outcome):
        """Rejection proves no take/send; ambiguity includes progress-before-return."""
        if not self._characterization or not jobs._characterization:
            return HandoffReceipt("execution_unavailable")
        if outcome not in {"rejected", "unknown"}:
            return HandoffReceipt("invalid_outcome")
        with jobs._lock:
            with self._lock:
                envelope = self._matching_locked(receipt)
                if envelope is None:
                    return HandoffReceipt("stale_receipt")
                if self._state not in {"offered", "accepted"}:
                    return HandoffReceipt("settled", envelope.job_id)
                # A callback cannot retract an observed acceptance/progress by
                # claiming definite rejection after the worker took ownership.
                if outcome == "rejected" and self._state != "offered":
                    outcome = "unknown"
                job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                if job is not None and job.state not in _TERMINAL:
                    jobs._finish_locked(job, "failed" if outcome == "rejected" else
                                        "submission_outcome_unknown", jobs._clock())
                self._state = outcome
                settled = self._receipt_locked("handoff_" + outcome)
                if outcome == "rejected":
                    self._clear_locked()
                return settled

    def accepted_receipt(self, jobs, receipt):
        with jobs._lock:
            jobs._cleanup_locked(jobs._clock())
            with self._lock:
                envelope = self._matching_locked(receipt)
                if envelope is None:
                    return HandoffReceipt("stale_receipt")
                job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                if self._closed or job is None or job.state in _TERMINAL:
                    return HandoffReceipt("handoff_invalidated", envelope.job_id)
                # Acceptance is independent of claimed/running/awaiting_result.
                return self._receipt_locked("characterized_acceptance" if self._state == "accepted"
                                            else "handoff_unknown")

    def event_for_characterization(self, jobs, event, *, target_current):
        if not self._characterization or not jobs._characterization:
            return "execution_unavailable"
        if (type(event) is not ExecutorEvent or type(event.progress) is not WorkerEvent
                or not _token(event.job_id) or not _token(event.claim_id)
                or not _digest(event.manifest_identity) or type(target_current) is not bool):
            return "invalid_event"
        progress = event.progress
        if (type(progress.sequence) is not int or not 1 <= progress.sequence <= MAX_EVENTS
                or type(progress.request_index) is not int or not 0 <= progress.request_index < MAX_REQUESTS
                or type(progress.kind) is not str or progress.kind not in {
                    "submission_started", "submitted", "outputs_ready", "failed", "submission_unknown"}
                or type(progress.output_count) is not int
                or not 0 <= progress.output_count <= MAX_OUTPUTS_PER_REQUEST
                or (progress.kind != "outputs_ready" and progress.output_count != 0)):
            return "invalid_event"
        if event.outputs is not None and (
                type(event.outputs) is not OutputReceipt or not _token(event.outputs.receipt_id)
                or type(event.outputs.output_count) is not int
                or event.progress.kind != "outputs_ready"
                or event.outputs.output_count != event.progress.output_count
                or not 1 <= event.outputs.output_count <= 16):
            return "invalid_event"
        if event.progress.kind == "outputs_ready" and event.outputs is None:
            return "invalid_event"
        with jobs._lock:
            jobs._cleanup_locked(jobs._clock())
            with self._lock:
                envelope = self._matching_locked(event)
                if envelope is None:
                    return "stale_receipt"
                if event.progress.request_index >= len(envelope.manifest.requests):
                    return "invalid_event"
                job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                if (not target_current or self._closed or job is None or job.state in _TERMINAL
                        or self._state in {"unknown", "rejected", "invalidated"}):
                    if job is not None and job.state not in _TERMINAL:
                        jobs._finish_locked(job, "stale_target_outputs_not_registered", jobs._clock())
                    if event.outputs is not None and event not in self._late:
                        self._late.append(event)
                    return "late_event"
                if self._state != "accepted":
                    return "acceptance_required"
                previous = self._events.get(event.progress.sequence)
                if previous is not None:
                    return "duplicate_event" if previous == event else "event_conflict"
                result = jobs.event_for_characterization(event.job_id, event.claim_id, event.progress)
                if result == "accepted":
                    self._events[event.progress.sequence] = event
                    while len(self._events) > MAX_EVENT_HISTORY:
                        self._events.popitem(last=False)
                return result

    def retire_settled_for_characterization(self, jobs, receipt):
        """Explicit original-host retirement only after a known terminal result.

        Unknown, invalidated, expired or lost work pins custody for future human
        recovery. This never retries the consumed proposal or submits anything.
        """
        if not self._characterization or not jobs._characterization:
            return "execution_unavailable"
        with jobs._lock:
            with self._lock:
                envelope = self._matching_locked(receipt)
                if envelope is None:
                    return "stale_receipt"
                job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                if (self._closed or self._state != "accepted" or job is None
                        or job.state not in {"completed", "partially_failed", "failed"}):
                    return "recovery_required"
                self._clear_locked()
                return "retired"

    def late_receipts(self):
        with self._lock:
            return tuple(self._late)

    def close(self):
        with self._lock:
            self._closed = True
            # Retain the bounded original envelope for correlated late receipts;
            # close never transfers or revives execution/publication custody.
            self._manifest = None
            if self._envelope is not None:
                self._state = "invalidated"
            else:
                self._clear_locked()

    def invalidate(self):
        """Host disarm fences the offer without asserting external cancellation."""
        with self._lock:
            if self._envelope is None:
                self._clear_locked()
            else:
                self._state = "invalidated"

    def _matching_locked(self, receipt):
        envelope = self._envelope
        if (type(receipt) not in {HandoffReceipt, ExecutorEvent} or envelope is None
                or (receipt.job_id, receipt.claim_id, receipt.manifest_identity) !=
                   (envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity)):
            return None
        return envelope

    def _receipt_locked(self, status):
        envelope = self._envelope
        return HandoffReceipt(status, envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity)

    def _clear_locked(self):
        self._reservation = self._manifest = self._envelope = None
        self._state = "empty"
        self._events.clear()
