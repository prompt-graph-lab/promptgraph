"""Explicit, offline-only host-owned HTTP I/O worker lifecycle.

The worker thread sees one bounded task containing an owner-issued frozen
request and exact immutable correlation values. It never receives the live
Project, Streamlit state, Journal owner, host locks, registry, inbox or event
sink. Results return to the original host as bounded typed transport outcomes.
"""
from dataclasses import dataclass, field
import queue
import threading

from core.comfy_http_history import HistoryResult, PromptHTTPHistoryTransport
from core.comfy_http_submission import PromptHTTPSubmissionTransport, SubmissionResult
from core.comfy_prompt_request import FrozenPromptRequest, is_owner_prepared_frozen_request
from core.comfy_remote_output_receipts import MAX_REMOTE_BYTES, valid_prompt_id


MAX_WAIT_SECONDS = 125.0
MAX_JOIN_SECONDS = 2.0
_QUEUE_POLL_SECONDS = 0.025


@dataclass(frozen=True)
class HTTPIOCorrelation:
    operation_id: str
    job_id: str
    claim_id: str
    manifest_identity: str
    session_identity: str
    process_identity: str
    request_id: str
    request_index: int
    illustration_id: str
    run_index: int
    workflow_identity: str
    attempt_id: int
    prompt_id: str | None = None


@dataclass(frozen=True)
class HTTPIOCompletion:
    task_id: int
    kind: str
    correlation: HTTPIOCorrelation
    outcome: object = field(repr=False, compare=False)
    _worker_witness: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class HTTPIOWorkerObservation:
    state: str
    started: bool
    thread_alive: bool
    safe_terminated: bool
    terminal: bool
    in_flight: bool
    in_flight_kind: str | None
    accepted_operations: int
    completed_operations: int
    uncertain_submissions: int


@dataclass
class _Task:
    task_id: int
    kind: str
    correlation: HTTPIOCorrelation
    prepared: FrozenPromptRequest
    prompt_id: str | None
    completed: threading.Event = field(default_factory=threading.Event)
    state: str = "queued"
    possible_send: bool = False
    transport_running: bool = False
    abandoned: bool = False
    cancelled: bool = False
    uncertainty_counted: bool = False
    outcome: object = None


def _identifier(value, maximum=256):
    return type(value) is str and 0 < len(value) <= maximum


def _valid_correlation(kind, correlation, prepared, prompt_id):
    if (type(correlation) is not HTTPIOCorrelation
            or not all(_identifier(value) for value in (
                correlation.operation_id, correlation.job_id, correlation.claim_id,
                correlation.manifest_identity, correlation.session_identity,
                correlation.process_identity, correlation.request_id,
                correlation.illustration_id, correlation.workflow_identity))
            or type(correlation.request_index) is not int or correlation.request_index < 0
            or type(correlation.run_index) is not int or correlation.run_index < 0
            or type(correlation.attempt_id) is not int or correlation.attempt_id < 1
            or (correlation.request_id, correlation.request_index,
                correlation.workflow_identity)
                != (prepared.request_id, prepared.request_index,
                    prepared.workflow_identity)):
        return False
    if kind == "submission":
        return prompt_id is None and correlation.prompt_id is None
    return (kind == "history" and valid_prompt_id(prompt_id)
            and correlation.prompt_id == prompt_id)


def _bounded_outcome(kind, value):
    """Return an exact bounded result value or a safe unknown result."""
    if kind == "submission":
        if (type(value) is SubmissionResult and value.status in {
                "accepted", "rejected_before_submission", "unknown"}
                and type(value.response_json) is bytes
                and len(value.response_json) <= MAX_REMOTE_BYTES
                and (value.status == "accepted" and bool(value.response_json)
                     or value.status != "accepted" and not value.response_json)):
            return value
        return SubmissionResult("unknown")
    if (type(value) is HistoryResult and value.status in {
            "ready", "pending", "timeout", "unknown"}
            and type(value.history_json) is bytes
            and len(value.history_json) <= MAX_REMOTE_BYTES
            and (value.status == "ready" and bool(value.history_json)
                 or value.status != "ready" and not value.history_json)):
        return value
    return HistoryResult("unknown")


class HostOwnedHTTPIOWorker:
    """One explicitly started thread, one bounded queue, one operation at a time.

    A submission is reserved before queue admission and can never be submitted
    again by this owner. Once the transport callback begins, timeout/close is
    conservatively possible-send uncertainty. GET History may be explicitly
    repeated after a completed read; no polling is scheduled here.
    """

    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    authorship = "unverified"

    def __init__(self, submission_transport, history_transport, *,
                 wait_timeout_seconds=30.0, join_timeout_seconds=0.25,
                 characterization=False):
        if (characterization is not True or type(characterization) is not bool
                or type(submission_transport) is not PromptHTTPSubmissionTransport
                or type(history_transport) is not PromptHTTPHistoryTransport
                or type(wait_timeout_seconds) not in (int, float)
                or not 0 < wait_timeout_seconds <= MAX_WAIT_SECONDS
                or type(join_timeout_seconds) not in (int, float)
                or not 0 <= join_timeout_seconds <= MAX_JOIN_SECONDS):
            raise ValueError("http_io_worker_unavailable")
        self._submission_transport = submission_transport
        self._history_transport = history_transport
        self._wait_timeout = float(wait_timeout_seconds)
        self._join_timeout = float(join_timeout_seconds)
        self._queue = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._operation_gate = threading.Lock()
        self._thread = None
        self._state = "created"
        self._active_task = None
        self._next_task_id = 0
        self._post_attempted = set()
        self._accepted_operations = 0
        self._completed_operations = 0
        self._uncertain_submissions = 0
        # Local provenance for completed Worker tasks only. Refusal-shaped
        # synthetic completions remain distinguishable from worker results.
        self._completion_witness = object()
        self._last_completion = None
        # One-shot original-host custody. The claim is never transferred or
        # released, including after close or an uncertain outcome.
        self._characterization_owner_claim = None
        self._characterization_operation = None

    def start_for_characterization(self):
        with self._lock:
            if self._state != "created":
                return self._observation_locked()
            self._state = "starting"
            thread = threading.Thread(target=self._run, name="promptgraph-http-io", daemon=True)
            self._thread = thread
            try:
                thread.start()
            except Exception:
                self._state = "start_failed"
                self._thread = None
                return self._observation_locked()
            self._state = "running"
            return self._observation_locked()

    def _claim_original_host_for_characterization(self, owner_claim):
        """Atomically bind this unused Worker to one original-host lifecycle."""
        if owner_claim is None:
            return False
        with self._lock:
            thread = self._thread
            if (self._characterization_owner_claim is not None
                    or self._state not in {"created", "running"}
                    or (self._state == "running" and (thread is None or not thread.is_alive()))
                    or self._active_task is not None
                    or self._characterization_operation is not None
                    or self._accepted_operations != 0
                    or self._completed_operations != 0
                    or self._uncertain_submissions != 0
                    or self._post_attempted):
                return False
            self._characterization_owner_claim = owner_claim
            return True

    def _register_original_host_operation_for_characterization(
        self, owner_claim, kind, correlation,
    ):
        """Register one exact owner-approved correlation before Worker admission."""
        if kind not in {"submission", "history"} or type(correlation) is not HTTPIOCorrelation:
            return False
        with self._lock:
            if (self._characterization_owner_claim is not owner_claim
                    or owner_claim is None
                    or self._state not in {"created", "running"}
                    or self._active_task is not None
                    or self._characterization_operation is not None):
                return False
            self._characterization_operation = (kind, correlation)
            return True

    def perform_for_characterization(self, kind, prepared, prompt_id, correlation, *,
                                     after_admission=None):
        if (kind not in {"submission", "history"}
                or not is_owner_prepared_frozen_request(prepared)
                or not _valid_correlation(kind, correlation, prepared, prompt_id)
                or (after_admission is not None and not callable(after_admission))):
            return None
        if not self._operation_gate.acquire(blocking=False):
            return self._refusal(kind, correlation, SubmissionResult("unknown")
                                 if kind == "submission" else HistoryResult("unknown"))
        task = None
        try:
            with self._lock:
                if self._characterization_owner_claim is not None:
                    registered = self._characterization_operation
                    if (registered is None or registered[0] != kind
                            or registered[1] is not correlation):
                        return self._refusal(
                            kind, correlation,
                            SubmissionResult("unknown") if kind == "submission"
                            else HistoryResult("unknown"),
                        )
                submission_key = None
                if kind == "submission":
                    submission_key = (correlation.operation_id, correlation.job_id,
                                     correlation.claim_id, correlation.request_id)
                    if submission_key in self._post_attempted:
                        return self._refusal(kind, correlation, SubmissionResult("unknown"))
                if self._state != "running" or self._thread is None:
                    outcome = (SubmissionResult("rejected_before_submission")
                               if kind == "submission" and self._active_task is None
                               and self._state in {
                                   "created", "start_failed", "closing", "close_pending", "closed"}
                               else SubmissionResult("unknown") if kind == "submission"
                               else HistoryResult("unknown"))
                    return self._refusal(kind, correlation, outcome)
                if self._active_task is not None:
                    return self._refusal(
                        kind, correlation,
                        SubmissionResult("unknown") if kind == "submission"
                        else HistoryResult("unknown"))
                if kind == "submission":
                    if len(self._post_attempted) >= 100:
                        return self._refusal(kind, correlation,
                                             SubmissionResult("rejected_before_submission"))
                    self._post_attempted.add(submission_key)
                self._next_task_id += 1
                task = _Task(self._next_task_id, kind, correlation, prepared, prompt_id)
                self._active_task = task
                try:
                    self._queue.put_nowait(task)
                except queue.Full:
                    task.state = "queue_rejected"
                    self._active_task = None
                    return self._refusal(
                        kind, correlation,
                        SubmissionResult("rejected_before_submission") if kind == "submission"
                        else HistoryResult("unknown"))
                if self._characterization_owner_claim is not None:
                    self._characterization_operation = None
                self._accepted_operations += 1

            # This callback stays on the original host caller thread and is
            # never copied into the task visible to the Worker thread. It
            # releases the host's request-admission lease once queue admission
            # has linearized, so close may interrupt the bounded wait.
            if after_admission is not None:
                after_admission()

            if not task.completed.wait(self._wait_timeout):
                with self._lock:
                    if task.completed.is_set():
                        pass
                    elif task.state == "queued":
                        task.cancelled = True
                        task.abandoned = True
                        task.state = "cancelled_before_transport"
                        task.outcome = (SubmissionResult("rejected_before_submission")
                                        if kind == "submission" else HistoryResult("unknown"))
                        task.completed.set()
                    else:
                        task.abandoned = True
                        task.state = "abandoned"
                        if task.possible_send:
                            self._state = "uncertain"
                            self._mark_submission_uncertain_locked(task)
                        task.completed.set()

            with self._lock:
                if task.state == "cancelled_before_transport":
                    outcome = task.outcome
                    self._clear_task_locked(task)
                    self._completed_operations += 1
                    completion = HTTPIOCompletion(
                        task.task_id, kind, correlation, outcome, self._completion_witness,
                    )
                    self._last_completion = completion
                    return completion
                if (task.abandoned or self._state in {"closing", "closed", "uncertain"}
                        or self._active_task is not task or task.state != "completed"):
                    if task.possible_send and kind == "submission" and task.state != "abandoned":
                        self._state = "uncertain"
                        self._mark_submission_uncertain_locked(task)
                    if not task.transport_running:
                        self._clear_task_locked(task)
                    return self._refusal(
                        kind, correlation,
                        SubmissionResult("unknown") if kind == "submission"
                        else HistoryResult("unknown"))
                completion = HTTPIOCompletion(
                    task.task_id, kind, correlation, task.outcome, self._completion_witness,
                )
                self._last_completion = completion
                self._clear_task_locked(task)
                self._completed_operations += 1
                if (kind == "submission" and type(task.outcome) is SubmissionResult
                        and task.outcome.status == "unknown"):
                    self._state = "uncertain"
                    self._mark_submission_uncertain_locked(task)
                return completion
        finally:
            self._operation_gate.release()

    @staticmethod
    def _refusal(kind, correlation, outcome):
        if type(correlation) is not HTTPIOCorrelation:
            return None
        return HTTPIOCompletion(0, kind, correlation, outcome)

    def request_close_for_characterization(self):
        """Fence new operations immediately without waiting for the Worker.

        Host lifecycle revocation can call this while holding its short
        publication boundary. It only changes bounded in-memory state and
        never joins the thread or invokes a transport callback.
        """
        with self._lock:
            if self._state == "closed":
                self._characterization_operation = None
                return self._observation_locked()
            if self._state == "created":
                self._characterization_operation = None
                self._state = "closed"
                return self._observation_locked()
            if self._state not in {"closing", "close_pending"}:
                self._state = "closing"
            # A queued but not yet admitted host operation is invalidated by
            # close. The permanent Worker owner claim itself is retained.
            self._characterization_operation = None
            task = self._active_task
            if task is not None:
                if task.state == "queued":
                    task.cancelled = True
                    task.abandoned = True
                    task.state = "cancelled_before_transport"
                    task.outcome = (SubmissionResult("rejected_before_submission")
                                    if task.kind == "submission" else HistoryResult("unknown"))
                    task.completed.set()
                else:
                    task.abandoned = True
                    task.state = "abandoned"
                    if task.possible_send and task.kind == "submission":
                        self._mark_submission_uncertain_locked(task)
                    task.completed.set()
            thread = self._thread
            if thread is None or not thread.is_alive():
                self._state = "closed"
            else:
                self._state = "close_pending"
            return self._observation_locked()

    def close_for_characterization(self):
        self.request_close_for_characterization()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(self._join_timeout)
        with self._lock:
            if thread is None or not thread.is_alive():
                self._state = "closed"
            else:
                self._state = "close_pending"
            return self._observation_locked()

    def observation_for_characterization(self):
        with self._lock:
            return self._observation_locked()

    def _is_issued_completion_for_characterization(self, completion):
        """Identify only the exact latest completion object returned by this owner."""
        with self._lock:
            return (type(completion) is HTTPIOCompletion
                    and completion is self._last_completion
                    and completion._worker_witness is self._completion_witness)

    def _observation_locked(self):
        thread = self._thread
        alive = thread is not None and thread.is_alive()
        task = self._active_task
        return HTTPIOWorkerObservation(
            self._state, thread is not None, alive,
            (thread is None or not alive) and self._state in {
                "start_failed", "closed", "uncertain_stopped"},
            self._state in {"start_failed", "closed", "uncertain_stopped"},
            task is not None, task.kind if task is not None else None,
            self._accepted_operations, self._completed_operations,
            self._uncertain_submissions)

    def _clear_task_locked(self, task):
        if self._active_task is task:
            self._active_task = None
        task.prepared = None
        task.outcome = None

    def _mark_submission_uncertain_locked(self, task):
        if task.kind == "submission" and not task.uncertainty_counted:
            task.uncertainty_counted = True
            self._uncertain_submissions += 1

    def _run(self):
        while True:
            with self._lock:
                if self._state in {"closing", "close_pending", "uncertain"} and self._active_task is None:
                    self._state = "uncertain_stopped" if self._state == "uncertain" else "closed"
                    return
            try:
                task = self._queue.get(timeout=_QUEUE_POLL_SECONDS)
            except queue.Empty:
                continue
            with self._lock:
                if task.cancelled or self._state in {"closing", "close_pending", "closed"}:
                    task.state = "cancelled_before_transport"
                    task.outcome = (SubmissionResult("rejected_before_submission")
                                    if task.kind == "submission" else HistoryResult("unknown"))
                    task.completed.set()
                    if self._active_task is task:
                        self._active_task = None
                    continue
                if self._active_task is not task or task.state != "queued":
                    task.abandoned = True
                    task.state = "discarded"
                    task.completed.set()
                    continue
                task.state = "running"
                task.transport_running = True
                # Entering an injected POST transport is the conservative
                # possible-send boundary. Its typed pre-send rejection remains
                # authoritative if it proves connect/validation failed first.
                task.possible_send = task.kind == "submission"
            try:
                if task.kind == "submission":
                    raw_outcome = self._submission_transport(task.prepared)
                else:
                    raw_outcome = self._history_transport(task.prepared, task.prompt_id)
                outcome = _bounded_outcome(task.kind, raw_outcome)
            except Exception:
                outcome = (SubmissionResult("unknown") if task.kind == "submission"
                           else HistoryResult("unknown"))
            with self._lock:
                task.transport_running = False
                if task.abandoned or self._state in {"closing", "close_pending", "closed"}:
                    task.state = "discarded"
                    task.outcome = None
                    task.completed.set()
                    if task.kind == "submission" and task.possible_send:
                        self._mark_submission_uncertain_locked(task)
                        self._state = "uncertain" if self._state not in {"closing", "close_pending"} else self._state
                    if self._active_task is task:
                        self._active_task = None
                else:
                    task.outcome = outcome
                    task.state = "completed"
                    task.completed.set()
            task = None
