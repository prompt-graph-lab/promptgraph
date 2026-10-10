"""Offline C2B-4 adapter. No production transport, thread or download owner.

Injected fakes run synchronously outside all custody locks. The original host
delivers count-only events; this owner never sees Project/Streamlit objects.
"""
from collections import OrderedDict, deque
from dataclasses import dataclass, field
import uuid

from core.comfy_prompt_request import prepare_frozen_prompt_request
from core.comfy_remote_output_receipts import (
    validate_remote_outputs, valid_prompt_id, decode_remote_json,
)
from ui.agent_generation_executor_inbox import (
    GenerationExecutorInbox, ExecutorEvent, OutputReceipt, HandoffReceipt, _bounded_manifest,
)
from ui.agent_generation_job import GenerationJobRegistry, JobRequest, WorkerEvent

MAX_PROGRESS_PER_REQUEST = 4
MAX_RECEIPT_BYTES = 512 * 1024
MAX_LATE_BATCHES = 16


@dataclass(frozen=True)
class SubmissionResult:
    """Trusted transport classification, not an exception-to-rejection guess.

    Only rejected_before_submission proves that no send happened. Every thrown
    error or malformed/missing accepted response is uncertain and not retried.
    """
    status: str
    response_json: bytes = field(default=b"", repr=False)


@dataclass(frozen=True)
class ComfyProgress:
    completed_steps: int
    total_steps: int


@dataclass(frozen=True)
class ExecutionResult:
    request_id: str
    prompt_id: str
    status: str
    history_json: bytes = field(default=b"", repr=False)
    progress: tuple[ComfyProgress, ...] = ()


@dataclass(frozen=True)
class ExecutorObservation:
    status: str
    request_index: int
    remote_output_count: int = 0


class ComfyExecutorAdapter:
    """One accepted envelope, one attempt/request, private bounded receipts.

    Metadata ready pauses at awaiting_download. Later requests are submitted
    only after separate original-host settlement of the prior request. Neither
    advancing nor result timeout can resubmit a sent request or reopen custody.
    """
    execution_available = False

    def __init__(self, jobs, inbox, *, fake_transport, fake_result_provider, host_event_sink,
                 characterization=False):
        if (type(jobs) is not GenerationJobRegistry or type(inbox) is not GenerationExecutorInbox
                or type(characterization) is not bool):
            raise ValueError("invalid_executor_owner")
        self._enabled = characterization and jobs._characterization and inbox._characterization
        self._jobs, self._inbox = jobs, inbox
        self._transport, self._result_provider, self._event_sink = fake_transport, fake_result_provider, host_event_sink
        self._envelope = self._acceptance = None
        self._index = 0
        self._phase = "not_taken"
        self._prompts = set()
        self._active_prepared = self._active_prompt = None
        self._progress_count = 0
        self._timeout_reported = False
        self._receipts = OrderedDict()
        self._late = deque()
        self._receipt_bytes = 0
        self._observation = ExecutorObservation("execution_unavailable", 0)

    def accept_and_run_for_characterization(self, offer):
        if not self._enabled:
            return HandoffReceipt("execution_unavailable")
        if self._envelope is not None:
            return HandoffReceipt("duplicate_acceptance", self._envelope.job_id)
        if not all(callable(callback) for callback in (self._transport, self._result_provider, self._event_sink)):
            return HandoffReceipt("executor_unavailable")
        receipt, envelope = self._inbox.accept_for_characterization(self._jobs, offer)
        if envelope is None:
            return receipt
        self._envelope, self._acceptance = envelope, receipt
        bounded = _bounded_manifest(envelope.manifest)
        with self._jobs._lock:
            job = self._jobs._authorized_locked(envelope.job_id, envelope.claim_id)
            expected = tuple(JobRequest(r.request_id, r.illustration_id, r.run_index, r.workflow_identity)
                             for r in envelope.manifest.requests)
            valid = (job is not None and job.binding == envelope.binding
                     and envelope.binding.plan_identity == envelope.manifest.manifest_identity
                     and job.requests == expected and bounded)
        if not valid:
            self._inbox.settle_for_characterization(self._jobs, receipt, "unknown")
            self._phase = "stopped"
            self._observe("invalid_envelope")
            return receipt
        self._phase = "ready"
        self.advance_for_characterization()
        return receipt

    def advance_for_characterization(self):
        if not self._enabled or self._envelope is None:
            return self._observe("execution_unavailable")
        if self._phase not in {"ready", "awaiting_download"}:
            return self._observation
        if self._phase == "awaiting_download":
            snapshot = self._jobs.snapshot(self._envelope.job_id)
            rows = snapshot.get("requests", [])
            if len(rows) <= self._index or rows[self._index]["state"] not in {"completed", "partially_failed", "failed"}:
                return self._observation
            self._index += 1
            self._phase = "ready"
        while self._index < len(self._envelope.manifest.requests):
            if self._inbox.accepted_receipt(self._jobs, self._acceptance).status != "characterized_acceptance":
                self._phase = "stopped"
                return self._observe("host_invalidated")
            request = self._envelope.manifest.requests[self._index]
            self._phase = "preparing"
            self._active_prepared = self._active_prompt = None
            self._progress_count = 0
            self._timeout_reported = False
            client = str(uuid.uuid5(uuid.NAMESPACE_OID, "|".join((self._envelope.job_id,
                self._envelope.claim_id, self._envelope.manifest.manifest_identity, request.request_id))))
            try:
                prepared = prepare_frozen_prompt_request(self._envelope.manifest, request, client_id=client)
            except Exception:
                if self._emit("failed") != "accepted":
                    self._phase = "stopped"
                    return self._observe("host_invalidated")
                self._index += 1
                continue
            self._phase = "submitting"
            if self._emit("submission_started") != "accepted":
                self._phase = "stopped"
                return self._observe("host_invalidated")
            try:
                submission = self._transport(prepared)
            except Exception:
                submission = None
            if type(submission) is SubmissionResult and submission.status == "rejected_before_submission":
                if self._emit("failed") != "accepted":
                    self._phase = "stopped"
                    return self._observe("host_invalidated")
                self._index += 1
                continue
            try:
                if (type(submission) is not SubmissionResult or submission.status != "accepted"
                        or type(submission.response_json) is not bytes):
                    raise ValueError("unknown_submission")
                response = decode_remote_json(submission.response_json)
                prompt = response.get("prompt_id") if type(response) is dict else None
                if not valid_prompt_id(prompt) or prompt in self._prompts:
                    raise ValueError("unknown_submission")
            except Exception:
                self._emit("submission_unknown")
                self._phase = "stopped"
                return self._observe("submission_outcome_unknown")
            self._prompts.add(prompt)
            self._active_prepared, self._active_prompt = prepared, prompt
            if self._emit("submitted") != "accepted":
                self._phase = "stopped"
                return self._observe("host_invalidated")
            try:
                self._phase = "awaiting_remote_result"
                result = self._result_provider(prepared, prompt)
            except Exception:
                result = None
            outcome = self.receive_result_for_characterization(result)
            if self._phase != "ready":
                return outcome
        self._phase = "done"
        return self._observe("requests_settled")

    def receive_result_for_characterization(self, result):
        """One correlated result stream, including private late output evidence.

        An explicit later result may resolve accepted-but-pending execution; it
        never calls transport again. A metadata receipt never settles local
        containment or host publication.
        """
        if not self._enabled or self._active_prepared is None:
            return self._observe("execution_unavailable")
        if self._phase not in {"awaiting_remote_result", "awaiting_download"}:
            return self._observe("result_fenced")
        if type(result) is ExecutionResult and (
                result.request_id != self._active_prepared.request_id or result.prompt_id != self._active_prompt):
            return self._observe("result_correlation_mismatch")
        if self._phase == "awaiting_download":
            # A terminal remote receipt is immutable; no failure/progress may
            # replace it or resolve a different request after host settlement.
            try:
                receipt = validate_remote_outputs(self._envelope, self._active_prepared,
                                                   self._active_prompt, result.history_json)
                if result.status == "ready" and receipt.identity in self._receipts:
                    return self._observe("duplicate_remote_receipt", len(receipt.images))
            except Exception:
                pass
            return self._observe("result_fenced")
        if (type(result) is not ExecutionResult or type(result.status) is not str or result.status not in {
                "ready", "execution_failed", "pending", "timeout", "unknown"}
                or type(result.progress) is not tuple
                or self._progress_count + len(result.progress) > MAX_PROGRESS_PER_REQUEST):
            self._phase = "awaiting_remote_result"
            return self._observe("execution_outcome_unknown")
        for progress in result.progress:
            if (type(progress) is not ComfyProgress or type(progress.completed_steps) is not int
                    or type(progress.total_steps) is not int
                    or not 0 <= progress.completed_steps <= progress.total_steps <= 1_000_000):
                self._phase = "awaiting_remote_result"
                return self._observe("execution_outcome_unknown")
        self._phase = "handling_result"
        for progress in result.progress:
            if self._emit("execution_progress") != "accepted":
                self._phase = "stopped"
                return self._observe("host_invalidated")
            self._progress_count += 1
        if result.status in {"pending", "timeout", "unknown"}:
            if result.status == "timeout" and not self._timeout_reported:
                if self._emit("execution_timeout") != "accepted":
                    self._phase = "stopped"
                    return self._observe("host_invalidated")
                self._timeout_reported = True
            self._phase = "awaiting_remote_result"
            return self._observe({"pending": "awaiting_remote_result", "timeout": "execution_timeout",
                                  "unknown": "execution_outcome_unknown"}[result.status])
        if result.status == "execution_failed":
            if self._emit("failed") == "accepted":
                self._active_prepared = self._active_prompt = None
                self._index += 1
                self._phase = "ready"
                return self._observe("request_failed")
            self._phase = "stopped"
            return self._observe("host_invalidated")
        try:
            receipt = validate_remote_outputs(self._envelope, self._active_prepared,
                                               self._active_prompt, result.history_json)
        except Exception:
            self._phase = "awaiting_remote_result"
            return self._observe("remote_metadata_quarantined")
        if receipt.identity in self._receipts or any(r.identity == receipt.identity for r in self._late):
            return self._observe("duplicate_remote_receipt", len(receipt.images))
        if self._receipt_bytes + receipt.encoded_size > MAX_RECEIPT_BYTES:
            self._phase = "awaiting_remote_result"
            return self._observe("receipt_capacity_unavailable")
        delivered = self._emit("remote_outputs_ready", count=len(receipt.images), receipt_id=receipt.identity[:32])
        self._receipt_bytes += receipt.encoded_size
        if delivered == "accepted":
            self._receipts[receipt.identity] = receipt
            self._phase = "awaiting_download"
            return self._observe("awaiting_download", len(receipt.images))
        self._late.append(receipt)
        while len(self._late) > MAX_LATE_BATCHES:
            self._receipt_bytes -= self._late.popleft().encoded_size
        self._phase = "stopped"
        return self._observe("late_remote_receipt", len(receipt.images))

    def remote_receipts(self):
        return tuple(self._receipts.values())

    def late_receipts(self):
        return tuple(self._late)

    def observation(self):
        return self._observation

    def _emit(self, kind, *, count=0, receipt_id=None):
        snapshot = self._jobs.snapshot(self._envelope.job_id)
        sequence = snapshot.get("event_count", 0) + 1
        outputs = OutputReceipt(receipt_id, count) if count else None
        event = ExecutorEvent(self._envelope.job_id, self._envelope.claim_id,
            self._envelope.manifest.manifest_identity, WorkerEvent(sequence, self._index, kind, count), outputs)
        try:
            return self._event_sink(event)
        except Exception:
            return "unavailable"

    def _observe(self, status, count=0):
        self._observation = ExecutorObservation(status, self._index, count)
        return self._observation
