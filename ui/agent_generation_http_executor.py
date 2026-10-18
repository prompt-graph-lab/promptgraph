"""Original-host, injected-wire composition for offline HTTP characterization.

This module only assembles the existing bounded transports, Journal owner and
Executor. It does not register a worker, provide a default network wire, or
enable production execution.
"""
from threading import Lock

from core.comfy_http_history import (
    PromptHTTPHistoryTransport,
    stdlib_history_wire_for_characterization,
)
from core.comfy_http_submission import (
    PromptHTTPPolicy,
    PromptHTTPSubmissionTransport,
    stdlib_prompt_wire_for_characterization,
)
from ui.agent_generation_comfy_executor import (
    ComfyExecutorAdapter,
    ExecutionResult,
    history_result_provider_for_characterization,
)
from ui.agent_generation_executor_inbox import HandoffReceipt
from ui.agent_generation_executor_handoff import deliver_executor_event_for_characterization
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_executor_journal import GenerationExecutorJournalIntent
from ui.agent_generation_job import GenerationJobRegistry
from ui.project_agent_session_pump import ProjectAgentSessionRuntime
from ui.agent_generation_http_io_worker import (
    HTTPIOCompletion, HTTPIOCorrelation, HostOwnedHTTPIOWorker,
)
from core.comfy_prompt_request import is_owner_prepared_frozen_request
from core.comfy_http_history import HistoryResult
from core.comfy_http_submission import SubmissionResult
from core.generation_multi_request_journal import SubmissionIntent


class _WorkerSubmissionAdmission:
    """Host-side lease fencing request intent against Worker close."""

    def __init__(self, lock):
        self._lock = lock
        self._released = False

    def release(self):
        if not self._released:
            self._released = True
            self._lock.release()


class OfflineHTTPExecutorComposition:
    """Small host-only handle over the existing offline characterization owners."""

    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    authorship = "unverified"

    def __init__(self, adapter, submission_transport, history_transport, history_reader,
                 history_lock, state, runtime, journal_intent_owner, *, io_worker=None,
                 worker_admission_lock=None):
        self._adapter = adapter
        self._submission_transport = submission_transport
        self._history_transport = history_transport
        self._history_reader = history_reader
        self._history_read_lock = history_lock
        self._state, self._runtime = state, runtime
        self._journal_intent_owner = journal_intent_owner
        self._io_worker = io_worker
        self._worker_admission_lock = (worker_admission_lock if worker_admission_lock is not None
                                       else Lock())
        self._worker_entry_lock = Lock()
        self._worker_admission_reservation = None

    def accept_offer_for_characterization(self, offer):
        if self._io_worker is None:
            return self._adapter.accept_and_run_for_characterization(offer)
        if not self._worker_entry_lock.acquire(blocking=False):
            return HandoffReceipt("executor_busy")
        try:
            if not self._worker_admission_lock.acquire(blocking=False):
                return HandoffReceipt("execution_unavailable")
            try:
                worker_running = (
                    self._io_worker.observation_for_characterization().state == "running")
            except Exception:
                worker_running = False
            if not worker_running:
                self._worker_admission_lock.release()
                return HandoffReceipt("execution_unavailable")
            reservation = _WorkerSubmissionAdmission(self._worker_admission_lock)
            self._worker_admission_reservation = reservation
            try:
                return self._adapter.accept_and_run_for_characterization(offer)
            finally:
                if self._worker_admission_reservation is reservation:
                    self._worker_admission_reservation = None
                    reservation.release()
        finally:
            self._worker_entry_lock.release()

    def advance_for_characterization(self):
        if self._io_worker is None:
            return self._adapter.advance_for_characterization()
        if not self._worker_entry_lock.acquire(blocking=False):
            return self._adapter.observation()
        try:
            return self._adapter.advance_for_characterization()
        finally:
            self._worker_entry_lock.release()

    def start_io_worker_for_characterization(self):
        if self._io_worker is None:
            return None
        # Worker start/close are serialized by the Worker's short lifecycle
        # lock. Do not take the submission-admission lease here: it can span
        # caller-provided Journal callbacks and file I/O.
        return self._io_worker.start_for_characterization()

    def io_worker_observation_for_characterization(self):
        if self._io_worker is None:
            return None
        return self._io_worker.observation_for_characterization()

    def close_io_worker_for_characterization(self):
        if self._io_worker is None:
            return None
        # Close must remain reentrant and bounded even when a host Journal
        # callback requests it during an in-progress submission intent. The
        # Worker's own lifecycle lock serializes close against queue admission;
        # close never waits for the host-side admission lease.
        return self._io_worker.close_for_characterization()

    def observation_for_characterization(self):
        return self._adapter.observation()

    def _read_history_with_custody(self, prepared, prompt_id):
        adapter = self._adapter
        if (adapter._phase != "awaiting_remote_result"
                or adapter._active_prepared is not prepared
                or adapter._active_prompt != prompt_id):
            return None
        envelope = adapter._envelope
        lease = self._journal_intent_owner.begin_history_read_for_characterization(
            envelope, prepared, prompt_id, adapter._jobs, adapter._inbox, adapter._acceptance)
        if lease is None:
            adapter._phase = "stopped"
            adapter._observe("host_invalidated")
            return ExecutionResult(prepared.request_id, prompt_id, "unknown")
        try:
            result = self._history_reader(prepared, prompt_id)
        except Exception:
            result = ExecutionResult(prepared.request_id, prompt_id, "unknown")
        current = self._journal_intent_owner.finish_history_read_for_characterization(
            envelope, prepared, prompt_id, adapter._jobs, adapter._inbox,
            adapter._acceptance, lease)
        if not current:
            adapter._phase = "stopped"
            adapter._observe("host_invalidated")
            return ExecutionResult(prepared.request_id, prompt_id, "unknown")
        return result

    def read_current_history_for_characterization(self):
        """Explicitly GET the current accepted prompt; never resubmit POST /prompt."""
        adapter = self._adapter
        # Preserve the adapter's Journal/send/result serialization order:
        # adapter advance lock -> History read lock -> release read lock ->
        # deliver through the existing result gate while the adapter lock is
        # still held. This fences an explicit GET racing the initial GET or
        # another result transition without holding host/job/inbox locks.
        if not adapter._journal_advance_lock.acquire(blocking=False):
            return self._adapter.observation()
        try:
            if not self._history_read_lock.acquire(blocking=False):
                return adapter.observation()
            try:
                prepared, prompt_id = adapter._active_prepared, adapter._active_prompt
                if (adapter._phase != "awaiting_remote_result" or prepared is None
                        or prompt_id is None):
                    return adapter.observation()
                result = self._read_history_with_custody(prepared, prompt_id)
            finally:
                self._history_read_lock.release()
            if result is None or adapter._phase == "stopped":
                return adapter.observation()
            return adapter.receive_result_for_characterization(result)
        finally:
            adapter._journal_advance_lock.release()

def compose_http_executor_for_characterization(
        state, runtime, journal_intent_owner, *, submission_wire_factory,
        history_wire_factory, policy=PromptHTTPPolicy(), characterization=False):
    """Bind injected HTTP contracts to the exact original host and Journal owner.

    The standard-library HTTP factories are deliberately rejected here: this
    composition is offline-only even though those transport wires exist for
    separately reviewed characterization. Each transport still derives its
    destination only from the per-request frozen ComfyUI origin.
    """
    return _compose_http_executor_for_characterization(
        state, runtime, journal_intent_owner,
        submission_wire_factory=submission_wire_factory,
        history_wire_factory=history_wire_factory, policy=policy,
        characterization=characterization, use_worker=False)


def compose_http_executor_with_worker_for_characterization(
        state, runtime, journal_intent_owner, *, submission_wire_factory,
        history_wire_factory, policy=PromptHTTPPolicy(), worker_wait_timeout_seconds=30.0,
        worker_join_timeout_seconds=0.25, characterization=False):
    """Explicit opt-in to a host-owned thread for injected offline HTTP wires.

    Construction does not start a thread. The original host must call
    ``start_io_worker_for_characterization`` before handing the offer to the
    Executor. No default, stdlib wire or production registration is exposed.
    """
    return _compose_http_executor_for_characterization(
        state, runtime, journal_intent_owner,
        submission_wire_factory=submission_wire_factory,
        history_wire_factory=history_wire_factory, policy=policy,
        characterization=characterization, use_worker=True,
        worker_wait_timeout_seconds=worker_wait_timeout_seconds,
        worker_join_timeout_seconds=worker_join_timeout_seconds)


def _compose_http_executor_for_characterization(
        state, runtime, journal_intent_owner, *, submission_wire_factory,
        history_wire_factory, policy, characterization, use_worker,
        worker_wait_timeout_seconds=30.0, worker_join_timeout_seconds=0.25):
    if (characterization is not True or type(characterization) is not bool
            or type(state) is not dict or type(runtime) is not ProjectAgentSessionRuntime
            or type(journal_intent_owner) is not GenerationExecutorJournalIntent
            or type(runtime.generation_jobs) is not GenerationJobRegistry
            or type(runtime._generation_executor_inbox) is not GenerationExecutorInbox
            or not runtime.generation_jobs._characterization
            or not runtime._generation_executor_inbox._characterization
            or runtime._closed or runtime._registration is None
            or runtime._generation_publication_origin is not None
            or journal_intent_owner._state is not state
            or journal_intent_owner._runtime is not runtime
            or journal_intent_owner._closed
            or journal_intent_owner._state_name != "unbound"
            or not callable(submission_wire_factory) or not callable(history_wire_factory)
            or submission_wire_factory is stdlib_prompt_wire_for_characterization
            or history_wire_factory is stdlib_history_wire_for_characterization
            or type(policy) is not PromptHTTPPolicy):
        raise ValueError("offline_http_executor_unavailable")
    if (type(use_worker) is not bool
            or type(worker_wait_timeout_seconds) not in (int, float)
            or type(worker_join_timeout_seconds) not in (int, float)):
        raise ValueError("offline_http_executor_unavailable")
    root = journal_intent_owner._journal_root(journal_intent_owner._journal_owner)
    if root.identity != journal_intent_owner._journal_root_identity:
        raise ValueError("offline_http_executor_unavailable")
    root.check()

    # One policy object keeps endpoint timeouts consistent for POST and GET.
    submission = PromptHTTPSubmissionTransport(
        wire_factory=submission_wire_factory, policy=policy, characterization=True)
    history = PromptHTTPHistoryTransport(
        wire_factory=history_wire_factory, policy=policy, characterization=True)
    io_worker = (HostOwnedHTTPIOWorker(
        submission, history, wait_timeout_seconds=worker_wait_timeout_seconds,
        join_timeout_seconds=worker_join_timeout_seconds, characterization=True)
        if use_worker else None)
    read_history = (history_result_provider_for_characterization(history)
                    if io_worker is None else None)
    history_lock = Lock()
    worker_admission_lock = Lock()
    composition_holder = {}
    adapter_holder = {}
    attempt_lock = Lock()
    next_attempt_id = [0]

    def next_attempt():
        with attempt_lock:
            next_attempt_id[0] += 1
            return next_attempt_id[0]

    def worker_correlation(kind, prepared, prompt_id=None):
        adapter = adapter_holder.get("adapter")
        owner = journal_intent_owner
        if (adapter is None or not is_owner_prepared_frozen_request(prepared)
                or adapter._envelope is None or owner._operation is None
                or owner._envelope is not adapter._envelope):
            return None
        index = prepared.request_index
        requests = owner._expected_requests if owner._multi_request else (owner._expected_request,)
        if (type(index) is not int or index < 0 or index >= len(requests)
                or index >= len(adapter._envelope.manifest.requests)):
            return None
        request = requests[index]
        manifest_request = adapter._envelope.manifest.requests[index]
        if ((prepared.request_id, prepared.request_index, prepared.workflow_identity)
                != (request.request_id, index, request.workflow_identity)
                or (request.request_id, request.request_index, request.illustration_id,
                    request.run_index, request.workflow_identity)
                != (manifest_request.request_id, index, manifest_request.illustration_id,
                    manifest_request.run_index, manifest_request.workflow_identity)):
            return None
        if kind == "submission":
            if (adapter._phase != "submitting" or adapter._index != index
                    or adapter._last_event is None
                    or adapter._last_event.progress.kind != "submission_started"
                    or not _journal_send_intent_current(
                        owner, adapter, prepared, adapter._last_event)):
                return None
            if owner._multi_request:
                host_current = owner._multi_host_observation(
                    adapter._envelope, runtime.generation_jobs,
                    runtime._generation_executor_inbox, adapter._acceptance,
                    request_index=index, request_state="submitting", event=adapter._last_event)
            else:
                host_current = owner._host_current(
                    adapter._envelope, runtime.generation_jobs,
                    runtime._generation_executor_inbox, adapter._acceptance,
                    request_state="submitting", event=adapter._last_event)
            if host_current is not True:
                return None
        elif (kind != "history" or adapter._phase != "awaiting_remote_result"
              or adapter._active_prepared is not prepared
              or adapter._active_prompt != prompt_id or owner._state_name != "history_reading"):
            return None
        operation = owner._operation
        try:
            return HTTPIOCorrelation(
                operation.operation_id, adapter._envelope.job_id, adapter._envelope.claim_id,
                adapter._envelope.manifest.manifest_identity, operation.session_identity,
                operation.process_identity, request.request_id, index, request.illustration_id,
                request.run_index, request.workflow_identity, next_attempt(), prompt_id)
        except Exception:
            return None

    def worker_submission(prepared):
        correlation = worker_correlation("submission", prepared)
        if correlation is None:
            return SubmissionResult("rejected_before_submission")
        admission = adapter_holder["adapter"]._active_submission_admission
        completion = io_worker.perform_for_characterization(
            "submission", prepared, None, correlation,
            after_admission=(admission.release if admission is not None else None))
        if not _completion_matches(completion, "submission", correlation):
            return SubmissionResult("unknown")
        # Journal intent is already acknowledged. Recheck exact original-host
        # custody after I/O before handing its result to the existing Executor.
        adapter = adapter_holder["adapter"]
        event = adapter._last_event
        if (adapter._phase != "submitting" or event is None
                or event.progress.kind != "submission_started"
                or not _journal_send_intent_current(
                    journal_intent_owner, adapter, prepared, event)):
            io_worker.close_for_characterization()
            return SubmissionResult("unknown")
        if journal_intent_owner._multi_request:
            current = journal_intent_owner._multi_host_observation(
                adapter._envelope, runtime.generation_jobs, runtime._generation_executor_inbox,
                adapter._acceptance, request_index=prepared.request_index,
                request_state="submitting", event=event)
        else:
            current = journal_intent_owner._host_current(
                adapter._envelope, runtime.generation_jobs, runtime._generation_executor_inbox,
                adapter._acceptance, request_state="submitting", event=event)
        return completion.outcome if current is True else SubmissionResult("unknown")

    def worker_history_reader(prepared, prompt_id):
        correlation = worker_correlation("history", prepared, prompt_id)
        if correlation is None:
            return ExecutionResult(prepared.request_id, prompt_id, "unknown")
        completion = io_worker.perform_for_characterization(
            "history", prepared, prompt_id, correlation)
        if not _completion_matches(completion, "history", correlation):
            return ExecutionResult(prepared.request_id, prompt_id, "unknown")
        result = completion.outcome
        return ExecutionResult(prepared.request_id, prompt_id, result.status, result.history_json)

    def serialized_history_provider(prepared, prompt_id):
        if not history_lock.acquire(blocking=False):
            return ExecutionResult(prepared.request_id, prompt_id, "unknown")
        try:
            composition = composition_holder.get("composition")
            if composition is None:
                return ExecutionResult(prepared.request_id, prompt_id, "unknown")
            return composition._read_history_with_custody(prepared, prompt_id)
        finally:
            history_lock.release()

    def worker_submission_admission():
        composition = composition_holder.get("composition")
        if composition is not None and composition._worker_admission_reservation is not None:
            reservation = composition._worker_admission_reservation
            composition._worker_admission_reservation = None
            return reservation
        if io_worker is None or not worker_admission_lock.acquire(blocking=False):
            return None
        try:
            if io_worker.observation_for_characterization().state != "running":
                worker_admission_lock.release()
                return None
            return _WorkerSubmissionAdmission(worker_admission_lock)
        except Exception:
            worker_admission_lock.release()
            return None

    adapter = ComfyExecutorAdapter(
        runtime.generation_jobs,
        runtime._generation_executor_inbox,
        fake_transport=worker_submission if io_worker is not None else submission,
        fake_result_provider=serialized_history_provider,
        host_event_sink=lambda event: deliver_executor_event_for_characterization(
            state, runtime, event),
        characterization=True,
        journal_intent_owner=journal_intent_owner,
        submission_admission_gate=(worker_submission_admission if io_worker is not None else None),
    )
    composed = OfflineHTTPExecutorComposition(
        adapter, submission, history, read_history, history_lock,
        state, runtime, journal_intent_owner, io_worker=io_worker,
        worker_admission_lock=worker_admission_lock)
    composition_holder["composition"] = composed
    adapter_holder["adapter"] = adapter
    if io_worker is not None:
        composed._history_reader = worker_history_reader
    return composed


def _completion_matches(completion, kind, correlation):
    if (type(completion) is not HTTPIOCompletion or type(completion.task_id) is not int
            or completion.task_id < 0 or completion.kind != kind
            or completion.correlation != correlation):
        return False
    if completion.task_id == 0:
        return (kind == "submission" and type(completion.outcome) is SubmissionResult
                and completion.outcome.status == "rejected_before_submission")
    if kind == "submission":
        return type(completion.outcome) is SubmissionResult
    return type(completion.outcome) is HistoryResult


def _journal_send_intent_current(owner, adapter, prepared, event):
    """Check the live in-memory acknowledged Journal tip before/after POST."""
    if (owner._closed or owner._state_name != "send_permitted"
            or owner._envelope is not adapter._envelope or owner._writer is None
            or owner._tip is None or not is_owner_prepared_frozen_request(prepared)
            or owner._writer.operation is not owner._operation
            or event is None or event is not adapter._last_event):
        return False
    writer, tip = owner._writer, owner._tip
    if (writer._revision != tip.revision or writer._digest != tip.digest
            or writer._file_identity != tip.file_identity or writer._uncertain):
        return False
    if owner._multi_request:
        if (not owner._multi_request or owner._multi_expected_index != prepared.request_index
                or writer._tip is not tip or not writer._events
                or writer.operation is not owner._operation
                or type(writer._events[-1]) is not SubmissionIntent
                or event is None or event.progress.kind != "submission_started"
                or event.progress.request_index != prepared.request_index):
            return False
        intent = writer._events[-1]
        request = owner._expected_requests[prepared.request_index]
        return ((intent.kind, intent.request_index, intent.request_id,
                 intent.illustration_id, intent.run_index, intent.workflow_identity)
                == ("submission_intent", request.request_index, request.request_id,
                    request.illustration_id, request.run_index, request.workflow_identity))
    observations = owner._expected_observations
    request = owner._expected_request
    return (writer._revision == 1 and len(observations) == 1
            and observations[-1].checkpoint == "submission_intent"
            and observations[-1].outcome == "intent"
            and len(observations[-1].requests) == 1
            and (observations[-1].requests[0].request_id,
                 observations[-1].requests[0].request_index,
                 observations[-1].requests[0].workflow_identity)
                == (request.request_id, request.request_index, request.workflow_identity)
            and event.progress.request_index == prepared.request_index
            and event.progress.kind == "submission_started")
