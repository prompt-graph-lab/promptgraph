"""Bounded session-host job bookkeeping; no executor or publication capability.

Production instances can prepare/cancel/invalidate jobs only. The explicitly
named characterization methods model a future execution contract with fake
events, and are disabled by default. This module imports no Streamlit, Project,
network or filesystem owner. Lock order: runtime publication gate -> this lock;
never acquire a runtime/mailbox lock or invoke external callbacks from here.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
import re
import threading
import time
import uuid


MAX_REQUESTS = 100
MAX_RUNS = 5
MAX_OUTPUTS_PER_REQUEST = 16
MAX_EVENTS = 1024
MAX_EVENT_HISTORY = 64
MAX_JOBS = 8
PREPARED_TTL = 900
ACTIVE_TTL = 3600
TERMINAL_TTL = 600
_PROCESS_INCARNATION = uuid.uuid4().hex
_TERMINAL = frozenset({
    "completed", "partially_failed", "failed", "submission_outcome_unknown",
    "stale_target_outputs_not_registered", "unavailable", "cancelled", "expired",
})


def _token(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class JobBinding:
    """Host-only origin: opaque tokens, never a Project/path/transport secret."""

    session_id: str
    process_incarnation: str
    target_epoch: str
    activation_id: str
    pairing_generation: int
    plan_identity: str


def _valid_binding(binding):
    return (type(binding) is JobBinding
            and all(_token(value) for value in (
                binding.session_id, binding.process_incarnation,
                binding.target_epoch, binding.activation_id))
            and _digest(binding.plan_identity)
            and type(binding.pairing_generation) is int
            and 1 <= binding.pairing_generation <= 2**63 - 1)


@dataclass(frozen=True)
class JobRequest:
    """Frozen correlation and workflow fingerprint, not runnable workflow JSON."""

    request_id: str
    illustration_id: str
    run_index: int
    workflow_identity: str


@dataclass(frozen=True)
class WorkerEvent:
    """Allowlisted count-only event; sequence is contiguous across a job.

    A worker may report submission_started, submitted, execution_progress, execution_timeout,
    remote_outputs_ready, outputs_ready, failed or submission_unknown. Remote
    metadata is distinct from local output; only host receipts mark registration.
    Raw errors, paths, workflow/Project objects and transport credentials have
    no field in this carrier. No event itself executes work.
    """

    sequence: int
    request_index: int
    kind: str
    output_count: int = 0


@dataclass(frozen=True)
class JobReceipt:
    status: str
    job_id: str | None = None
    claim_id: str | None = field(default=None, repr=False)


@dataclass
class _Job:
    job_id: str
    binding: JobBinding
    requests: tuple
    created: float
    deadline: float
    state: str = "prepared_not_started"
    revision: int = 1
    claim_key: str | None = None
    claim_id: str | None = None
    request_states: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    remote_outputs: list = field(default_factory=list)
    registered: list = field(default_factory=list)
    save_state: str = "not_attempted"
    event_count: int = 0
    events: OrderedDict = field(default_factory=OrderedDict)


class GenerationJobRegistry:
    """One browser-session/process-incarnation owner with bounded retention.

    There is intentionally no Start method. A plan/proposal ID or approval flag
    cannot enable execution. C2 must introduce human Start and a fresh exact
    host plan check before replacing the characterization-only claim contract.
    """

    execution_available = False

    def __init__(self, *, clock=time.monotonic, characterization=False):
        if type(characterization) is not bool:
            raise ValueError("invalid characterization mode")
        self._clock = clock
        self._characterization = characterization
        self._lock = threading.RLock()
        self._jobs = OrderedDict()
        self._closed = False
        self._target = None
        # New runtime = new session/process custody; never load old receipts.
        self._session_incarnation = uuid.uuid4().hex

    def host_binding(self, *, pairing_generation, plan_identity):
        """Capture private origin bookkeeping; this is never Start authority."""
        with self._lock:
            if self._closed or self._target is None:
                return None
            return JobBinding(self._session_incarnation, _PROCESS_INCARNATION,
                              *self._target, pairing_generation, plan_identity)

    def synchronize_target(self, target_epoch, activation_id):
        if not _token(target_epoch) or not _token(activation_id):
            raise ValueError("invalid host target")
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            self._target = (target_epoch, activation_id)
            for job in self._jobs.values():
                if (job.binding.target_epoch, job.binding.activation_id) != self._target:
                    if job.state not in _TERMINAL:
                        self._finish_locked(job, "stale_target_outputs_not_registered", now)

    def prepare(self, binding, requests):
        """Host-only preparation; copies immutable scalars, confers no authority."""
        if not _valid_binding(binding):
            return JobReceipt("invalid_input")
        if type(requests) not in (list, tuple) or not 1 <= len(requests) <= MAX_REQUESTS:
            return JobReceipt("invalid_input")
        detached = []
        ids = set()
        runs = set()
        for request in requests:
            if (type(request) is not JobRequest
                    or any(type(value) is not str or not 1 <= len(value) <= 160
                           for value in (request.request_id, request.illustration_id))
                    or request.request_id in ids
                    or type(request.run_index) is not int
                    or not 1 <= request.run_index <= MAX_RUNS
                    or not _digest(request.workflow_identity)):
                return JobReceipt("invalid_input")
            if (request.illustration_id, request.run_index) in runs:
                return JobReceipt("invalid_input")
            ids.add(request.request_id)
            runs.add((request.illustration_id, request.run_index))
            detached.append(JobRequest(request.request_id, request.illustration_id,
                                       request.run_index, request.workflow_identity))
        frozen_binding = JobBinding(binding.session_id, binding.process_incarnation,
                                    binding.target_epoch, binding.activation_id,
                                    binding.pairing_generation, binding.plan_identity)
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            if self._closed:
                return JobReceipt("unavailable")
            if (binding.session_id != self._session_incarnation
                    or binding.process_incarnation != _PROCESS_INCARNATION):
                return JobReceipt("foreign_origin")
            if (binding.target_epoch, binding.activation_id) != self._target:
                return JobReceipt("stale_target")
            if any(job.state not in _TERMINAL for job in self._jobs.values()):
                return JobReceipt("job_already_active")
            while len(self._jobs) >= MAX_JOBS:
                self._jobs.popitem(last=False)
            job_id = uuid.uuid4().hex
            job = _Job(job_id, frozen_binding, tuple(detached), now, now + PREPARED_TTL,
                       request_states=["unsent"] * len(detached),
                       outputs=[0] * len(detached), registered=[0] * len(detached))
            job.remote_outputs = [0] * len(detached)
            self._jobs[job_id] = job
            return JobReceipt("prepared_not_started", job_id)

    def claim_for_characterization(self, job_id, *, binding, claim_key):
        """Atomic fake Start after exact binding check; production fails closed.

        Same-key/same-binding duplicate returns the original private receipt;
        conflict or a terminal job never creates another claim. This is an
        in-memory claim persisted before any simulated submission event only.
        """
        if not self._characterization:
            return JobReceipt("execution_unavailable")
        if not _valid_binding(binding) or not _token(claim_key):
            return JobReceipt("invalid_input")
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            job = self._jobs.get(job_id) if type(job_id) is str else None
            if self._closed or job is None:
                return JobReceipt("unavailable")
            if binding != job.binding:
                return JobReceipt("claim_conflict")
            if job.state in _TERMINAL:
                return JobReceipt("terminal")
            if job.claim_id is not None:
                if job.claim_key == claim_key:
                    return JobReceipt("duplicate_claim", job_id, job.claim_id)
                return JobReceipt("claim_conflict")
            job.claim_key = claim_key
            job.claim_id = uuid.uuid4().hex
            job.state = "claimed"
            job.deadline = now + ACTIVE_TTL
            job.revision += 1
            return JobReceipt("claimed", job_id, job.claim_id)

    def claim_authorized_for_characterization(self, binding, requests, claim_key):
        """One atomic slot reservation/claim for C2A's fake host acceptance seam.

        Caller holds publication gate -> mailbox -> Generation custodian. No
        callback or expensive preparation runs here. Production remains fenced.
        """
        if not self._characterization:
            return JobReceipt("execution_unavailable")
        with self._lock:
            receipt = self.prepare(binding, requests)
            if receipt.status != "prepared_not_started":
                return receipt
            claim = self.claim_for_characterization(receipt.job_id, binding=binding, claim_key=claim_key)
            if claim.status != "claimed":
                self.cancel_before_submission(receipt.job_id)
            return claim

    def settle_handoff_for_characterization(self, job_id, claim_id, outcome):
        """An unaccepted/ambiguous inbox handoff is terminal, never retryable."""
        if not self._characterization:
            return "execution_unavailable"
        if outcome not in {"rejected", "unknown"}:
            return "invalid_input"
        with self._lock:
            job = self._authorized_locked(job_id, claim_id)
            if job is None or job.state != "claimed":
                return "unavailable"
            self._finish_locked(job, "failed" if outcome == "rejected" else
                                "submission_outcome_unknown", self._clock())
            return "settled"

    def event_for_characterization(self, job_id, claim_id, event):
        """Accept deterministic detached fake events; no real worker is launched."""
        if not self._characterization:
            return "execution_unavailable"
        if (type(event) is not WorkerEvent or type(event.sequence) is not int
                or not 1 <= event.sequence <= MAX_EVENTS
                or type(event.request_index) is not int
                or type(event.output_count) is not int
                or not 0 <= event.output_count <= MAX_OUTPUTS_PER_REQUEST
                or type(event.kind) is not str
                or event.kind not in {"submission_started", "submitted", "execution_progress", "execution_timeout", "remote_outputs_ready", "outputs_ready",
                                      "failed", "submission_unknown"}
                or (event.kind not in {"outputs_ready", "remote_outputs_ready"} and event.output_count != 0)
                or (event.kind in {"outputs_ready", "remote_outputs_ready"} and event.output_count == 0)):
            return "invalid_event"
        detached = WorkerEvent(event.sequence, event.request_index, event.kind, event.output_count)
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            job = self._authorized_locked(job_id, claim_id)
            if job is None:
                return "unavailable"
            previous = job.events.get(event.sequence)
            if previous is not None:
                return "duplicate_event" if previous == detached else "event_conflict"
            if job.state in _TERMINAL:
                return "terminal"
            if event.sequence != job.event_count + 1:
                return "event_out_of_order"
            index = event.request_index
            if not 0 <= index < len(job.requests):
                return "invalid_event"
            before = job.request_states[index]
            transitions = {
                ("unsent", "submission_started"): "submitting",
                ("submitting", "submitted"): "awaiting_result",
                ("awaiting_result", "execution_progress"): "awaiting_result",
                ("awaiting_result", "execution_timeout"): "awaiting_result",
                ("awaiting_result", "remote_outputs_ready"): "awaiting_download",
                ("awaiting_result", "outputs_ready"): "awaiting_host_registration",
                ("awaiting_download", "outputs_ready"): "awaiting_host_registration",
                ("unsent", "failed"): "failed",
                ("submitting", "failed"): "failed",
                ("awaiting_result", "failed"): "failed",
                ("submitting", "submission_unknown"): "submission_outcome_unknown",
            }
            after = transitions.get((before, event.kind))
            # Preserve sequential request submission: registration/failure of
            # earlier work is settled before the next request can be submitted.
            if after is None or (before == "unsent" and any(
                    state not in {"completed", "partially_failed", "failed"}
                    for state in job.request_states[:index])):
                return "invalid_transition"
            job.request_states[index] = after
            if event.kind == "remote_outputs_ready":
                job.remote_outputs[index] = event.output_count
            elif event.kind not in {"execution_progress", "execution_timeout"}:
                job.outputs[index] = event.output_count
            job.event_count += 1
            job.events[event.sequence] = detached
            while len(job.events) > MAX_EVENT_HISTORY:
                job.events.popitem(last=False)
            job.revision += 1
            if after == "submission_outcome_unknown":
                self._finish_locked(job, "submission_outcome_unknown", now)
            else:
                self._aggregate_locked(job, now)
            return "accepted"

    def publication_for_characterization(self, job_id, claim_id, *, binding,
                                         request_index, registered_count):
        """Fake host receipt, separate from worker reports; never appends records."""
        if not self._characterization:
            return "execution_unavailable"
        if (not _valid_binding(binding) or type(request_index) is not int
                or type(registered_count) is not int or registered_count < 0):
            return "invalid_input"
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            job = self._authorized_locked(job_id, claim_id)
            if job is None:
                return "unavailable"
            if (binding != job.binding
                    or (binding.target_epoch, binding.activation_id) != self._target):
                if job.state not in _TERMINAL:
                    self._finish_locked(job, "stale_target_outputs_not_registered", now)
                return "stale_target"
            if not 0 <= request_index < len(job.requests):
                return "invalid_input"
            if (job.outputs[request_index] > 0
                    and job.request_states[request_index] in {"completed", "partially_failed", "failed"}):
                return ("duplicate_publication" if registered_count == job.registered[request_index]
                        else "publication_conflict")
            if job.state in _TERMINAL:
                return "terminal"
            if (job.request_states[request_index] != "awaiting_host_registration"
                    or registered_count > job.outputs[request_index]):
                return "invalid_transition"
            job.registered[request_index] = registered_count
            job.request_states[request_index] = (
                "completed" if registered_count == job.outputs[request_index] else
                "partially_failed" if registered_count else "failed")
            job.revision += 1
            self._aggregate_locked(job, now)
            return "accepted"

    def save_for_characterization(self, job_id, claim_id, *, binding, outcome):
        """Record persistence separately from in-memory Candidate registration."""
        if not self._characterization:
            return "execution_unavailable"
        if (not _valid_binding(binding) or type(outcome) is not str
                or outcome not in {"saved", "save_failed"}):
            return "invalid_input"
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            job = self._authorized_locked(job_id, claim_id)
            if job is None:
                return "unavailable"
            if (binding != job.binding
                    or (binding.target_epoch, binding.activation_id) != self._target):
                return "stale_target"
            if job.state not in {"completed", "partially_failed"}:
                return "invalid_transition"
            if job.save_state != "not_attempted":
                return "duplicate_save" if job.save_state == outcome else "save_conflict"
            job.save_state = outcome
            job.revision += 1
            return "accepted"

    def cancel_before_submission(self, job_id):
        """Host-only cancellation while every request is unsent; no remote cancel."""
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            job = self._jobs.get(job_id) if type(job_id) is str else None
            if self._closed or job is None:
                return "unavailable"
            if job.state in _TERMINAL:
                return "terminal"
            if any(state != "unsent" for state in job.request_states):
                return "already_submitting"
            self._finish_locked(job, "cancelled", now)
            return "cancelled"

    def snapshot(self, job_id):
        """Detached bounded host view; no origin tokens, claim or request IDs.

        Unknown, expired-retention, foreign-session and restarted-process IDs
        all return unavailable. There is no MCP observation/catalog wiring.
        """
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            job = self._jobs.get(job_id) if type(job_id) is str else None
            if self._closed or job is None:
                return {"state": "unavailable", "execution_available": False}
            return {
                "job_id": job.job_id, "state": job.state, "revision": job.revision,
                "execution_available": False, "request_count": len(job.requests),
                "output_count": sum(job.outputs), "registered_count": sum(job.registered),
                "remote_output_count": sum(job.remote_outputs),
                "save_state": job.save_state, "event_count": job.event_count,
                "events_truncated": job.event_count > len(job.events),
                "requests": [{"index": index, "state": state,
                              "output_count": job.outputs[index],
                              "remote_output_count": job.remote_outputs[index],
                              "registered_count": job.registered[index]}
                             for index, state in enumerate(job.request_states)],
                "events": [{"sequence": event.sequence, "request_index": event.request_index,
                            "kind": event.kind, "output_count": event.output_count}
                           for event in job.events.values()],
            }

    def cleanup(self):
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)

    def close(self):
        now = self._clock()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for job in self._jobs.values():
                if job.state not in _TERMINAL:
                    self._finish_locked(job, "unavailable", now)

    def invalidate_execution_custody(self):
        """Explicit host disarm/pairing fencing; never claims remote cancellation."""
        now = self._clock()
        with self._lock:
            for job in self._jobs.values():
                if job.state not in _TERMINAL:
                    self._finish_locked(job, "unavailable", now)

    def _authorized_locked(self, job_id, claim_id):
        if self._closed or type(job_id) is not str or not _token(claim_id):
            return None
        job = self._jobs.get(job_id)
        return job if job is not None and job.claim_id == claim_id else None

    def _aggregate_locked(self, job, now):
        if all(state in {"completed", "partially_failed", "failed"} for state in job.request_states):
            completed = job.request_states.count("completed")
            registered = sum(job.registered)
            state = ("completed" if completed == len(job.requests) else
                     "partially_failed" if registered else "failed")
            self._finish_locked(job, state, now)
        else:
            job.state = ("running" if "submitting" in job.request_states else "awaiting_result")

    @staticmethod
    def _finish_locked(job, state, now):
        job.state = state
        job.deadline = now + TERMINAL_TTL
        job.revision += 1

    def _cleanup_locked(self, now):
        for job_id, job in list(self._jobs.items()):
            if now >= job.deadline:
                if job.state in _TERMINAL:
                    del self._jobs[job_id]
                else:
                    self._finish_locked(job, "expired" if job.claim_id is None else "unavailable", now)
