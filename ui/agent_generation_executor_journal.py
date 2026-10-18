"""C2B-8D-14 one-request offline Journal intent custody for the executor.

This owner is constructed by the original host and can be attached only to the
existing characterization executor. Journal bytes are inspect-only after
restart; neither this owner nor its acknowledgments enable production work.
"""
from dataclasses import dataclass, field
import copy
import hashlib
import os
from pathlib import Path
import re
import threading

from core import generation_multi_request_journal as multi_journal
from core import generation_ownership_journal as journal
from core import generation_protected_journal as protected_journal
from core.comfy_prompt_request import is_owner_prepared_frozen_request
from core.comfy_remote_output_receipts import valid_prompt_id
from ui.agent_generation_executor_handoff import GenerationPublicationOrigin
from ui.agent_generation_executor_inbox import ExecutionEnvelope, ExecutorEvent, GenerationExecutorInbox, HandoffReceipt
from ui.agent_generation_job import (GenerationJobRegistry, JobRequest, WorkerEvent,
                                    MAX_EVENTS, _PROCESS_INCARNATION, _TERMINAL)
from ui.project_agent_session_pump import ProjectAgentSessionRuntime


_FACTORY = object()


@dataclass(frozen=True)
class _AcknowledgedJournalTip:
    revision: int
    digest: str = field(repr=False)
    file_identity: tuple = field(repr=False)


def _identifier(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None


def _same_path(left, right):
    try:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
    except (TypeError, ValueError, OSError):
        return False


class GenerationExecutorJournalIntent:
    """Host-created, one-request writer binding for `ComfyExecutorAdapter`.

    `project_root` and `journal_root` are explicitly approved host objects.
    The selected project path and review are captured only from the live
    `GenerationPublicationOrigin`; worker input and reopened Journal contents
    never create this owner or its authority.
    """

    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    authorship = "unverified"

    @classmethod
    def create_for_characterization(
            cls, state, runtime, *, project_root, project_relative_path, journal_root,
            operation_id, characterization=False, disposable_opt_in=False,
            journal_fault=lambda boundary: None):
        if characterization is not True or disposable_opt_in is not True:
            raise ValueError("execution_unavailable")
        if (type(runtime) is not ProjectAgentSessionRuntime or type(state) is not dict
                or not runtime.generation_jobs._characterization
                or not runtime._generation_executor_inbox._characterization
                or type(project_root) is not journal.ApprovedRoot
                or type(project_relative_path) is not str
                or type(operation_id) is not str or not _identifier(operation_id)
                or not callable(journal_fault)):
            raise ValueError("journal_host_required")
        if type(journal_root) not in (journal.ApprovedRoot, protected_journal.WindowsProtectedJournalCharacterization):
            raise ValueError("approved_journal_root_required")
        project_root.check()
        root = cls._journal_root(journal_root)
        root.check()
        if _same_path(project_root.path, root.path):
            raise ValueError("journal_root_conflict")
        journal._relative(project_relative_path)
        return cls(state, runtime, project_root, project_relative_path, journal_root,
                   root.identity, operation_id, journal_fault, _factory=_FACTORY)

    def __init__(self, state, runtime, project_root, relative_path, journal_root,
                 journal_root_identity, operation_id, journal_fault, *, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("original_host_required")
        self._state, self._runtime = state, runtime
        self._project_root, self._relative_path = project_root, relative_path
        self._journal_owner = journal_root
        self._journal_root_identity = tuple(journal_root_identity)
        self._operation_id, self._journal_fault = operation_id, journal_fault
        self._lock = threading.RLock()
        self._state_name = "unbound"
        self._closed = False
        self._envelope = self._origin = self._operation = None
        self._writer = None
        self._tip = None
        self._expected_request = None
        self._expected_requests = ()
        self._multi_request = False
        self._multi_expected_index = 0
        self._multi_outcomes = {}

    @staticmethod
    def _journal_root(owner):
        return owner if type(owner) is journal.ApprovedRoot else owner._approved

    def _capture_operation(self, envelope):
        runtime, state = self._runtime, self._state
        origin = runtime._generation_publication_origin
        if (type(origin) is not GenerationPublicationOrigin or origin.envelope is not envelope
                or origin.project is None or origin.source_snapshot is None
                or type(origin.path) is not str or not origin.path
                or type(origin.review_json) is not bytes or not origin.review_json
                or len(origin.review_json) > journal.MAX_BYTES):
            raise ValueError("original_host_required")
        manifest = envelope.manifest
        requests = manifest.requests
        if type(requests) is not tuple or not 1 <= len(requests) <= 100:
            raise ValueError("request_identity_conflicting")
        correlations = []
        for index, request in enumerate(requests):
            if (request.request_index != index or type(request.request_id) is not str
                    or type(request.workflow_identity) is not str):
                raise ValueError("request_identity_conflicting")
            correlations.append(journal.FrozenRequestCorrelation(
                request.request_id, request.request_index, request.illustration_id,
                request.run_index, request.workflow_identity))
        if state.get("project") is not origin.project or not _same_path(state.get("current_project_path"), origin.path):
            raise ValueError("stale_original_host")
        try:
            snapshot = copy.deepcopy(origin.source_snapshot)
            live = copy.deepcopy(origin.project)
        except Exception:
            raise ValueError("source_snapshot_unavailable") from None
        if live != snapshot or origin.project != snapshot or state.get("project") != snapshot:
            raise ValueError("stale_original_host")
        expected_path = str(Path(self._project_root.path) / self._relative_path)
        if not _same_path(origin.path, expected_path):
            raise ValueError("project_path_mismatch")
        data, file_identity = journal._read(self._project_root, self._relative_path)
        project_root_path = self._project_root.check()
        operation = journal.OperationObservation(
            self._operation_id, envelope.job_id, manifest.manifest_identity,
            hashlib.sha256(data).hexdigest(), self._project_root.key,
            str(project_root_path), self._project_root.identity, self._relative_path,
            file_identity, envelope.binding.process_incarnation, envelope.binding.session_id,
            envelope.claim_id, hashlib.sha256(origin.review_json).hexdigest(),
            tuple(correlations))
        journal._validate_operation(operation)
        return origin, operation, requests

    def _disk_current(self, operation):
        try:
            if (self._project_root.identity != operation.project_root_identity
                    or str(self._project_root.check()) != operation.project_root_path):
                return False
            data, identity = journal._read(self._project_root, self._relative_path,
                                           expected_identity=operation.project_file_identity)
            return hashlib.sha256(data).hexdigest() == operation.source_sha256
        except Exception:
            return False

    def _host_current(self, envelope, jobs, inbox, acceptance, *, request_state, event=None,
                      claim_send=False):
        operation, origin = self._operation, self._origin
        if (operation is None or origin is None or not self._disk_current(operation)
                or type(envelope) is not ExecutionEnvelope or envelope is not self._envelope
                or type(jobs) is not GenerationJobRegistry or type(inbox) is not GenerationExecutorInbox):
            return False
        runtime, state = self._runtime, self._state
        try:
            current_project = copy.deepcopy(origin.project)
        except Exception:
            return False
        if current_project != origin.source_snapshot:
            return False
        send_claimed = False
        with runtime._publication_gate:
            if (runtime._closed or runtime._registration is None
                    or runtime._generation_publication_origin is not origin
                    or state.get("project") is not origin.project
                    or not _same_path(state.get("current_project_path"), origin.path)):
                return False
            route = runtime._registry._record_for_registration(runtime._registration)
            if route is None:
                return False
            with route.operation_lock:
                # The detached copy above is an early rejection check only.
                # Recompare the complete live source while both host mutation
                # gates are held, so a cooperating in-place Project edit
                # cannot slip between that copy and the final send claim.
                try:
                    if origin.project != origin.source_snapshot:
                        return False
                except Exception:
                    return False
                try:
                    epoch = runtime._synchronize_target_locked(state.get("project"), state.get("current_project_path", ""))
                    available, pairing = runtime._registration.inspect_pairing_generation()
                except Exception:
                    return False
                with jobs._lock:
                    jobs._cleanup_locked(jobs._clock())
                    job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                    if (job is None or job.binding != envelope.binding or job.state in _TERMINAL
                            or job.binding.session_id != jobs._session_incarnation
                            or job.binding.process_incarnation != _PROCESS_INCARNATION
                            or job.binding.target_epoch != epoch
                            or (job.binding.target_epoch, job.binding.activation_id) != jobs._target
                            or type(pairing) is not int or pairing != job.binding.pairing_generation
                            or (job.binding.session_id, job.binding.process_incarnation, job.claim_id,
                                job.job_id, job.binding.plan_identity) != (
                                operation.session_identity, operation.process_identity, operation.claim_id,
                                operation.job_id, operation.manifest_identity)
                            or job.requests != (JobRequest(
                                self._expected_request.request_id, self._expected_request.illustration_id,
                                self._expected_request.run_index, self._expected_request.workflow_identity),)
                            or len(job.request_states) != 1 or job.request_states[0] != request_state):
                        return False
                    with inbox._lock:
                        if (inbox._closed or inbox._state != "accepted" or inbox._envelope is not envelope
                                or inbox._matching_locked(acceptance) is not envelope):
                            return False
                        if event is not None:
                            expected = WorkerEvent(event.progress.sequence, 0, "submission_started", 0)
                            if (type(event) is not ExecutorEvent or event.progress.kind != "submission_started"
                                    or event.progress.request_index != 0 or event.outputs is not None
                                    or event.job_id != envelope.job_id or event.claim_id != envelope.claim_id
                                    or event.manifest_identity != operation.manifest_identity
                                    or inbox._events.get(event.progress.sequence) != event
                                    or job.events.get(event.progress.sequence) != expected
                                    or job.event_count != event.progress.sequence):
                                return False
                        if claim_send:
                            with self._lock:
                                if self._closed or self._state_name != "intent_acknowledged":
                                    return False
                                # Linearization point: later close/invalidation is
                                # after a possible-send claim, never a retry grant.
                                self._state_name = "send_permitted"
                                send_claimed = True
        return send_claimed if claim_send else True

    def _multi_host_observation(self, envelope, jobs, inbox, acceptance, *,
                                request_index, request_state, event=None,
                                disposition=None, claim_send=False):
        """Validate current host custody for one exact multi-request transition.

        For a successful settlement this requires the existing Candidate
        Publication owner to have completed its exact request registration.
        No diagnostic 64-event projection is used: both live owners retain the
        accepted sequence up to the Registry's hard 1024-event bound.
        """
        if (not self._multi_request or self._operation is None or self._origin is None
                or type(request_index) is not int
                or not 0 <= request_index < len(self._expected_requests)
                or not self._disk_current(self._operation)
                or type(envelope) is not ExecutionEnvelope or envelope is not self._envelope
                or type(jobs) is not GenerationJobRegistry or type(inbox) is not GenerationExecutorInbox):
            return None
        operation, origin = self._operation, self._origin
        expected_request = self._expected_requests[request_index]
        try:
            detached_project = copy.deepcopy(origin.project)
        except Exception:
            return None
        runtime, state = self._runtime, self._state
        with runtime._publication_gate:
            if (runtime._closed or runtime._registration is None
                    or runtime._generation_publication_origin is not origin
                    or state.get("project") is not origin.project
                    or not _same_path(state.get("current_project_path"), origin.path)):
                return None
            route = runtime._registry._record_for_registration(runtime._registration)
            if route is None:
                return None
            with route.operation_lock:
                try:
                    if origin.project != detached_project:
                        return None
                    epoch = runtime._synchronize_target_locked(
                        state.get("project"), state.get("current_project_path", ""))
                    available, pairing = runtime._registration.inspect_pairing_generation()
                except Exception:
                    return None
                with jobs._lock:
                    jobs._cleanup_locked(jobs._clock())
                    job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                    expected_binding = envelope.binding
                    frozen_requests = tuple(JobRequest(
                        request.request_id, request.illustration_id, request.run_index,
                        request.workflow_identity) for request in self._expected_requests)
                    terminal_allowed = disposition is not None
                    if (job is None or job.binding != expected_binding
                            or job.binding.session_id != jobs._session_incarnation
                            or job.binding.process_incarnation != _PROCESS_INCARNATION
                            or job.binding.target_epoch != epoch
                            or (job.binding.target_epoch, job.binding.activation_id) != jobs._target
                            or type(pairing) is not int or job.binding.pairing_generation != pairing
                            or (job.binding.session_id, job.binding.process_incarnation, job.claim_id,
                                job.job_id, job.binding.plan_identity) != (
                                operation.session_identity, operation.process_identity,
                                operation.claim_id, operation.job_id, operation.manifest_identity)
                            or job.requests != frozen_requests
                            or len(job.request_states) != len(self._expected_requests)
                            or len(job.request_failure_causes) != len(self._expected_requests)
                            or job.request_states[request_index] != request_state
                            or (job.state in _TERMINAL and not terminal_allowed)
                            or job.state in {"expired", "cancelled", "unavailable",
                                             "stale_target_outputs_not_registered", "submission_outcome_unknown"}):
                        return None
                    with inbox._lock:
                        if (inbox._closed or inbox._state != "accepted"
                                or inbox._envelope is not envelope
                                or inbox._matching_locked(acceptance) is not envelope):
                            return None
                        # Prove that the exact host event stream and the
                        # Registry's accepted detached stream are complete and
                        # sequence-identical. The 64-entry diagnostic maps may
                        # have evicted early events; they are intentionally not
                        # consulted here.
                        job_events = tuple(job.authority_events)
                        host_events = tuple(inbox._authority_events)
                        if (job.event_count > MAX_EVENTS or len(job_events) != job.event_count
                                or len(host_events) != job.event_count):
                            return None
                        for sequence, (host_event, job_event) in enumerate(zip(host_events, job_events), 1):
                            if (type(host_event) is not ExecutorEvent
                                    or host_event.job_id != envelope.job_id
                                    or host_event.claim_id != envelope.claim_id
                                    or host_event.manifest_identity != operation.manifest_identity
                                    or host_event.progress != job_event
                                    or job_event.sequence != sequence):
                                return None
                        if event is not None:
                            if (type(event) is not ExecutorEvent
                                    or event.progress.request_index != request_index
                                    or event.progress.kind != "submission_started"
                                    or event.outputs is not None
                                    or not any(observed is event for observed in host_events)
                                    or not any(observed == event.progress for observed in job_events)
                                    or job.event_count != event.progress.sequence):
                                return None

                        publisher = getattr(runtime, "_generation_candidate_publication", None)
                        if publisher is None:
                            expected_project = origin.source_snapshot
                        else:
                            from ui.agent_generation_candidate_publication import GenerationCandidatePublication
                            if (type(publisher) is not GenerationCandidatePublication
                                    or publisher._runtime is not runtime
                                    or publisher._envelope is not envelope
                                    or publisher._origin is not origin):
                                return None
                            expected_project = publisher._expected
                        if origin.project != expected_project:
                            return None

                        request_events = [item for item in host_events
                                          if item.progress.request_index == request_index]
                        started = [item for item in request_events
                                   if item.progress.kind == "submission_started"]
                        submitted = [item for item in request_events
                                     if item.progress.kind == "submitted"]
                        failed = [item for item in request_events
                                  if item.progress.kind == "failed"]
                        remote_ready = [item for item in request_events
                                        if item.progress.kind == "remote_outputs_ready"]
                        outputs_ready = [item for item in request_events
                                         if item.progress.kind == "outputs_ready"]

                        if disposition is None:
                            if event is None:
                                if request_state != "unsent" or request_events:
                                    return None
                                return True
                            if (len(started) != 1 or started[0] is not event
                                    or submitted or failed or remote_ready or outputs_ready):
                                return None
                            if claim_send:
                                with self._lock:
                                    if (self._closed or self._state_name != "intent_acknowledged"
                                            or self._multi_expected_index != request_index):
                                        return None
                                    self._state_name = "send_permitted"
                            return True

                        outcome_record = self._multi_outcomes.get(request_index)
                        if (outcome_record is None or outcome_record[0] not in {
                                "accepted", "pre_send_rejected"}):
                            return None
                        outcome, prompt_id = outcome_record
                        if len(started) != 1:
                            return None
                        is_last_request = request_index == len(job.requests) - 1
                        if is_last_request:
                            allowed_job_states = ({"completed", "partially_failed"}
                                if disposition == "execution_completed" else {"failed", "partially_failed"})
                            if job.state not in allowed_job_states:
                                return None
                        elif job.state in _TERMINAL:
                            return None
                        if any(item.progress.kind not in {
                                "submission_started", "submitted", "execution_progress",
                                "execution_timeout", "remote_outputs_ready", "outputs_ready", "failed"}
                                for item in request_events):
                            return None
                        if disposition == "pre_send_rejected":
                            if (outcome != "pre_send_rejected" or prompt_id is not None
                                    or request_state != "failed"
                                    or job.request_failure_causes[request_index] != "pre_send_rejected"
                                    or submitted or len(failed) != 1
                                    or failed[0].progress.cause != "pre_send_rejected"
                                    or remote_ready or outputs_ready):
                                return None
                            if not started[0].progress.sequence < failed[0].progress.sequence:
                                return None
                        elif disposition == "execution_failed":
                            if (outcome != "accepted" or not valid_prompt_id(prompt_id)
                                    or request_state != "failed"
                                    or job.request_failure_causes[request_index] != "execution_failed"
                                    or len(submitted) != 1
                                    or submitted[0].progress.prompt_id != prompt_id
                                    or len(failed) != 1
                                    or failed[0].progress.cause != "execution_failed"
                                    or remote_ready or outputs_ready):
                                return None
                            if not (started[0].progress.sequence < submitted[0].progress.sequence
                                    < failed[0].progress.sequence):
                                return None
                        elif disposition == "execution_completed":
                            if (outcome != "accepted" or not valid_prompt_id(prompt_id)
                                    or request_state != "completed"
                                    or job.request_failure_causes[request_index] is not None
                                    or len(submitted) != 1
                                    or submitted[0].progress.prompt_id != prompt_id
                                    or failed or len(remote_ready) != 1 or len(outputs_ready) != 1):
                                return None
                            if not (started[0].progress.sequence < submitted[0].progress.sequence
                                    < remote_ready[0].progress.sequence
                                    < outputs_ready[0].progress.sequence):
                                return None
                            from ui.agent_generation_candidate_publication import GenerationCandidatePublication
                            if type(publisher) is not GenerationCandidatePublication:
                                return None
                            with publisher._lock:
                                publication = publisher._records.get(request_index)
                                if (publisher._busy or publication is None
                                        or publication.registration_state != "registered"
                                        or publication.registered_count <= 0
                                        or publication.registered_count != job.outputs[request_index]
                                        or publication.registered_count != job.registered[request_index]):
                                    return None
                                if publisher._mode == "legacy":
                                    evidence = publisher._evidence.get(request_index)
                                    if type(evidence) is not tuple or len(evidence) != 3:
                                        return None
                                    _, remote_receipt, local_receipt = evidence
                                    if ((remote_receipt.request_id, remote_receipt.request_index,
                                         remote_receipt.prompt_id, remote_receipt.execution_succeeded)
                                            != (expected_request.request_id, request_index, prompt_id, True)
                                            or local_receipt.remote_receipt_identity != remote_receipt.identity
                                            or local_receipt.request_id != expected_request.request_id
                                            or local_receipt.request_index != request_index
                                            or local_receipt.verified_count != publication.registered_count
                                            or job.remote_outputs[request_index] != len(remote_receipt.images)
                                            or remote_ready[0].outputs is None
                                            or remote_ready[0].outputs.output_count != len(remote_receipt.images)
                                            or outputs_ready[0].outputs is None
                                            or outputs_ready[0].outputs.output_count != local_receipt.verified_count
                                            or remote_ready[0].outputs is None
                                            or remote_ready[0].outputs.receipt_id != remote_receipt.identity[:32]
                                            or outputs_ready[0].outputs is None
                                            or outputs_ready[0].outputs.receipt_id != local_receipt.identity[:32]):
                                        return None
                                elif publisher._mode == "protected":
                                    evidence = publisher._protected_evidence.get(request_index)
                                    settled = publisher._protected_settled_event_evidence.get(request_index)
                                    observation = evidence[1] if type(evidence) is tuple and len(evidence) == 2 else None
                                    protected_remote = getattr(observation, "_remote_receipt", None)
                                    promotion_receipt = getattr(observation, "_promotion_receipt", None)
                                    if (type(evidence) is not tuple or len(evidence) != 2
                                            or settled is None or settled.request_index != request_index
                                            or protected_remote is None or promotion_receipt is None
                                            or protected_remote.request_id != expected_request.request_id
                                            or protected_remote.prompt_id != prompt_id
                                            or promotion_receipt.request_id != expected_request.request_id
                                            or promotion_receipt.prompt_id != prompt_id
                                            or job.remote_outputs[request_index] != len(protected_remote.images)
                                            or not any(item is settled.remote_event for item in host_events)
                                            or not any(item is settled.outputs_ready_event for item in host_events)
                                            or remote_ready[0] is not settled.remote_event
                                            or outputs_ready[0] is not settled.outputs_ready_event
                                            or remote_ready[0].outputs is None
                                            or remote_ready[0].outputs.receipt_id != protected_remote.identity[:32]
                                            or remote_ready[0].outputs.output_count != len(protected_remote.images)
                                            or settled.outputs_ready_event.outputs is None
                                            or settled.outputs_ready_event.outputs.receipt_id != promotion_receipt.identity[:32]
                                            or settled.outputs_ready_event.outputs.output_count != publication.registered_count):
                                        return None
                                else:
                                    return None
                        else:
                            return None

                        if claim_send:
                            return None
                        host_observation_id = hashlib.sha256(repr((
                            operation.operation_id, operation.job_id, operation.claim_id,
                            operation.manifest_identity, request_index, expected_request.request_id,
                            disposition, prompt_id, tuple(item.progress.sequence for item in request_events),
                            job.request_states[request_index], job.request_failure_causes[request_index],
                            job.outputs[request_index], job.registered[request_index],
                        )).encode("utf-8")).hexdigest()
                        tip = self._tip
                        if type(tip) is not multi_journal.JournalAcknowledgement:
                            return None
                        return multi_journal.ValidatedOriginalHostSettlement(
                            operation.operation_id, operation.job_id, operation.claim_id,
                            operation.manifest_identity, operation.process_identity,
                            operation.session_identity, request_index, expected_request.request_id,
                            expected_request.illustration_id, expected_request.run_index,
                            expected_request.workflow_identity, disposition, prompt_id,
                            host_observation_id, tip.revision, tip.digest)

    def bind_for_characterization(self, envelope, jobs, inbox, acceptance):
        with self._lock:
            if self._closed or self._state_name != "unbound":
                return "journal_binding_unavailable"
            self._state_name = "binding"
        try:
            if (type(acceptance) is not HandoffReceipt or acceptance.status != "accepted"
                    or inbox.accepted_receipt(jobs, acceptance).status != "characterized_acceptance"):
                raise ValueError("accepted_host_claim_required")
            origin, operation, requests = self._capture_operation(envelope)
            self._origin, self._operation, self._envelope = origin, operation, envelope
            self._expected_requests = tuple(requests)
            self._expected_request = requests[0]
            self._multi_request = len(requests) > 1
            current = (self._multi_host_observation(envelope, jobs, inbox, acceptance,
                         request_index=0, request_state="unsent") if self._multi_request else
                       self._host_current(envelope, jobs, inbox, acceptance, request_state="unsent"))
            if not current:
                raise ValueError("stale_original_host")
            owner = self._journal_owner
            root = self._journal_root(owner)
            if root.identity != self._journal_root_identity:
                raise ValueError("journal_root_changed")
            root.check()
            if type(owner) is protected_journal.WindowsProtectedJournalCharacterization:
                if (owner._writer is not None or owner._multi_request_writer is not None
                        or owner.readiness().get("journal_lifecycle") != "protected_observation"):
                    raise ValueError("journal_owner_unavailable")
                if self._multi_request:
                    owner.initialize_multi_request_for_characterization(operation)
                    writer = owner._multi_request_writer
                else:
                    owner.initialize_for_characterization(operation)
                    writer = owner._writer
            else:
                writer_type = (multi_journal.MultiRequestJournalWriter if self._multi_request
                               else journal.OfflineJournalWriter)
                writer = writer_type(root, operation, characterization=True, fault=self._journal_fault)
            if (root.identity != self._journal_root_identity
                    or root.check() != Path(root.path)):
                raise ValueError("journal_root_changed")
            if (type(owner) is protected_journal.WindowsProtectedJournalCharacterization
                    and owner.readiness().get("journal_lifecycle") != "protected_observation"):
                raise ValueError("journal_owner_unavailable")
            expected_writer = (multi_journal.MultiRequestJournalWriter if self._multi_request
                               else journal.OfflineJournalWriter)
            if (not isinstance(writer, expected_writer)
                    or (type(owner) is journal.ApprovedRoot and type(writer) is not expected_writer)
                    or writer.operation != operation
                    or writer.root.identity != self._journal_root_identity
                    or writer._revision != 0 or writer._file_identity is not None or writer._uncertain):
                raise ValueError("journal_writer_unavailable")
            with self._lock:
                if self._closed or self._state_name != "binding":
                    raise ValueError("journal_binding_unavailable")
                self._writer = writer
                self._state_name = "bound"
            return "bound"
        except Exception:
            with self._lock:
                self._state_name = "refused"
            return "journal_binding_unavailable"

    def _append_and_verify(self, observation, expected_revision):
        owner = self._journal_owner
        root = self._journal_root(owner)
        if (root.identity != self._journal_root_identity or self._writer is None
                or self._writer.operation != self._operation or self._writer._uncertain
                or self._writer._revision != expected_revision - 1):
            raise ValueError("journal_writer_unavailable")
        root.check()
        if type(owner) is protected_journal.WindowsProtectedJournalCharacterization:
            if owner._writer is not self._writer or owner._uncertain:
                raise ValueError("journal_owner_unavailable")
            result = owner.append_for_characterization(observation)
        else:
            result = self._writer.append_for_characterization(observation)
        expected_observations = tuple(self._expected_observations) + (observation,)
        if (type(result) is not journal.ReopenedJournal or result.operation != self._operation
                or result.revision != expected_revision or len(result.digest) != 64
                or result.digest != self._writer._digest
                or result.file_identity != self._writer._file_identity
                or result.observations != expected_observations
                or result.trust != "inspect_only" or result.authenticity != "unverified"
                or result.execution_available is not False):
            raise ValueError("journal_acknowledgment_uncertain")
        if root.check() != Path(root.path) or root.identity != self._journal_root_identity:
            raise ValueError("journal_root_changed")
        if type(owner) is protected_journal.WindowsProtectedJournalCharacterization:
            readiness = owner.readiness()
            if readiness.get("journal_lifecycle") != "protected_observation":
                raise ValueError("journal_acknowledgment_uncertain")
        self._expected_observations.append(observation)
        return _AcknowledgedJournalTip(result.revision, result.digest, result.file_identity)

    def _append_multi_and_verify(self, action, *arguments):
        owner = self._journal_owner
        root = self._journal_root(owner)
        writer = self._writer
        if (not self._multi_request or writer is None
                or writer.operation != self._operation
                or writer.root.identity != self._journal_root_identity
                or writer._uncertain or writer._closed):
            raise ValueError("journal_writer_unavailable")
        if root.identity != self._journal_root_identity:
            raise ValueError("journal_root_changed")
        root.check()
        expected_revision = writer._revision + 1
        if type(owner) is protected_journal.WindowsProtectedJournalCharacterization:
            if owner._multi_request_writer is not writer or owner._uncertain:
                raise ValueError("journal_owner_unavailable")
            methods = {
                "intent": owner.append_multi_request_intent_for_characterization,
                "outcome": owner.append_multi_request_outcome_for_characterization,
                "settlement": owner.append_multi_request_settlement_for_characterization,
            }
            result = methods[action](*arguments)
        else:
            methods = {
                "intent": writer.append_intent_for_characterization,
                "outcome": writer.append_submission_outcome_for_characterization,
                "settlement": writer.append_settlement_for_characterization,
            }
            result = methods[action](*arguments)
        if (type(result) is not multi_journal.JournalAcknowledgement
                or result is not writer._tip or result.operation_id != self._operation.operation_id
                or result.revision != expected_revision or result.digest != writer._digest
                or result.file_identity != writer._file_identity
                or result._owner_token is not writer._owner_token):
            raise ValueError("journal_acknowledgment_uncertain")
        if type(owner) is protected_journal.WindowsProtectedJournalCharacterization:
            reopened = owner.reopen_multi_request_journal_for_characterization(
                writer.filename, expected_revision=expected_revision, expected_digest=result.digest)
        else:
            reopened = multi_journal.reopen_multi_request_journal(
                root, writer.filename, expected_revision=expected_revision, expected_digest=result.digest)
        if (type(reopened) is not multi_journal.ReopenedMultiRequestJournal
                or reopened.operation != self._operation or reopened.events != tuple(writer._events)
                or reopened.revision != expected_revision or reopened.digest != result.digest
                or reopened.file_identity != result.file_identity
                or reopened.trust != "inspect_only" or reopened.authorship != "unverified"
                or reopened.execution_available is not False):
            raise ValueError("journal_acknowledgment_uncertain")
        if root.check() != Path(root.path) or root.identity != self._journal_root_identity:
            raise ValueError("journal_root_changed")
        if type(owner) is protected_journal.WindowsProtectedJournalCharacterization:
            readiness = owner.readiness()
            if readiness.get("journal_lifecycle") != "protected_observation":
                raise ValueError("journal_acknowledgment_uncertain")
        self._tip = result
        return result

    def acknowledge_intent_before_send_for_characterization(self, envelope, prepared, event,
                                                            jobs, inbox, acceptance):
        if self._multi_request:
            return self._acknowledge_multi_intent(envelope, prepared, event, jobs, inbox, acceptance)
        with self._lock:
            if self._closed or self._state_name != "bound":
                return "intent_unavailable"
            self._state_name = "intent_writing"
        try:
            request = self._expected_request
            if (not is_owner_prepared_frozen_request(prepared)
                    or prepared.request_id != request.request_id
                    or prepared.request_index != request.request_index
                    or prepared.workflow_identity != request.workflow_identity):
                raise ValueError("frozen_request_mismatch")
            if not self._host_current(envelope, jobs, inbox, acceptance,
                                      request_state="submitting", event=event):
                raise ValueError("submission_started_not_current")
            self._expected_observations = []
            intent = journal.Observation("submission_intent", "intent", requests=(
                journal.RequestObservation(request.request_id, request.request_index,
                                           request.workflow_identity, "intent"),))
            tip = self._append_and_verify(intent, 1)
            with self._lock:
                self._tip = tip
                if self._closed or self._state_name != "intent_writing":
                    self._state_name = "uncertain"
                    return "intent_unacknowledged"
                self._state_name = "intent_acknowledged"
            if not self._host_current(envelope, jobs, inbox, acceptance,
                                      request_state="submitting", event=event, claim_send=True):
                with self._lock:
                    if self._state_name == "intent_acknowledged":
                        self._state_name = "no_send"
                return "host_invalidated_before_send"
            return "acknowledged"
        except Exception:
            with self._lock:
                if self._state_name != "send_permitted":
                    self._state_name = "uncertain"
            return "intent_unacknowledged"

    def _acknowledge_multi_intent(self, envelope, prepared, event, jobs, inbox, acceptance):
        index = getattr(prepared, "request_index", -1)
        with self._lock:
            allowed_state = self._state_name in {"bound", "settled"}
            if (self._closed or not allowed_state or index != self._multi_expected_index
                    or index >= len(self._expected_requests)):
                return "intent_unavailable"
            self._state_name = "intent_writing"
        try:
            request = self._expected_requests[index]
            if (not is_owner_prepared_frozen_request(prepared)
                    or (prepared.request_id, prepared.request_index, prepared.workflow_identity)
                    != (request.request_id, index, request.workflow_identity)):
                raise ValueError("frozen_request_mismatch")
            if self._multi_host_observation(envelope, jobs, inbox, acceptance,
                    request_index=index, request_state="submitting", event=event) is not True:
                raise ValueError("submission_started_not_current")
            with self._lock:
                expected_tip = self._tip
                if self._closed or self._state_name != "intent_writing":
                    raise ValueError("journal_binding_unavailable")
            tip = self._append_multi_and_verify(
                "intent", expected_tip, index)
            with self._lock:
                if self._closed or self._state_name != "intent_writing":
                    self._state_name = "uncertain"
                    return "intent_unacknowledged"
                self._state_name = "intent_acknowledged"
            if self._multi_host_observation(envelope, jobs, inbox, acceptance,
                    request_index=index, request_state="submitting", event=event,
                    claim_send=True) is not True:
                with self._lock:
                    if self._state_name == "intent_acknowledged":
                        self._state_name = "no_send"
                return "host_invalidated_before_send"
            return "acknowledged"
        except Exception:
            with self._lock:
                if self._state_name != "send_permitted":
                    self._state_name = "uncertain"
            return "intent_unacknowledged"

    def record_submission_result_for_characterization(self, outcome, prompt_id=None, *, request_index=None):
        if self._multi_request:
            return self._record_multi_submission_result(outcome, prompt_id, request_index)
        with self._lock:
            if self._closed or self._state_name != "send_permitted" or self._tip is None:
                return "result_unavailable"
            self._state_name = "result_writing"
        try:
            if outcome not in {"accepted", "failed", "unknown"}:
                raise ValueError("invalid_submission_outcome")
            request = self._expected_request
            if ((outcome == "accepted" and not valid_prompt_id(prompt_id))
                    or (outcome != "accepted" and prompt_id is not None)):
                raise ValueError("invalid_prompt_observation")
            request_record = journal.RequestObservation(request.request_id, request.request_index,
                request.workflow_identity, outcome, prompt_id)
            unresolved = ((journal.UnresolvedObservation(request.request_id, "unknown", "remote_unknown"),)
                          if outcome == "unknown" else ())
            observation = journal.Observation("submission_observed", outcome,
                requests=(request_record,), unresolved=unresolved)
            tip = self._append_and_verify(observation, 2)
            with self._lock:
                if self._closed or self._state_name != "result_writing":
                    self._state_name = "uncertain"
                    return "result_uncertain"
                self._tip = tip
                self._state_name = "result_observed"
            return "acknowledged"
        except Exception:
            with self._lock:
                self._state_name = "uncertain"
            return "result_uncertain"

    def _record_multi_submission_result(self, outcome, prompt_id, request_index):
        with self._lock:
            index = self._multi_expected_index if request_index is None else request_index
            if (self._closed or self._state_name != "send_permitted"
                    or type(index) is not int or index != self._multi_expected_index
                    or self._tip is None):
                return "result_unavailable"
            self._state_name = "result_writing"
            expected_tip = self._tip
        try:
            if outcome not in {"accepted", "pre_send_rejected", "unknown"}:
                raise ValueError("invalid_submission_outcome")
            if ((outcome == "accepted" and not valid_prompt_id(prompt_id))
                    or (outcome != "accepted" and prompt_id is not None)):
                raise ValueError("invalid_prompt_observation")
            if outcome == "accepted" and any(
                    observed_prompt == prompt_id for observed_outcome, observed_prompt in self._multi_outcomes.values()
                    if observed_outcome == "accepted"):
                raise ValueError("duplicate_prompt_identity")
            tip = self._append_multi_and_verify("outcome", expected_tip, outcome, prompt_id)
            with self._lock:
                if self._closed or self._state_name != "result_writing":
                    self._state_name = "uncertain"
                    return "result_uncertain"
                self._tip = tip
                self._multi_outcomes[index] = (outcome, prompt_id)
                self._state_name = "outcome_unknown" if outcome == "unknown" else "result_observed"
            return "acknowledged"
        except Exception:
            with self._lock:
                self._state_name = "uncertain"
            return "result_uncertain"

    def settle_request_for_characterization(self, envelope, request_index, disposition,
                                            jobs, inbox, acceptance):
        """Append one exact settlement only from current original-host evidence."""
        if not self._multi_request:
            return "settlement_unavailable"
        expected_states = {
            "pre_send_rejected": "failed",
            "execution_failed": "failed",
            "execution_completed": "completed",
        }
        request_state = expected_states.get(disposition)
        with self._lock:
            if (self._closed or self._state_name != "result_observed"
                    or type(request_index) is not int
                    or request_index != self._multi_expected_index
                    or disposition not in expected_states or self._tip is None):
                return "settlement_unavailable"
            self._state_name = "settlement_writing"
            expected_tip = self._tip
            writer = self._writer

        def validate_live_host(operation, request, tip):
            if (operation != self._operation or tip is not expected_tip
                    or request != self._operation.requests[request_index]):
                raise ValueError("settlement_identity_conflicting")
            facts = self._multi_host_observation(envelope, jobs, inbox, acceptance,
                request_index=request_index, request_state=request_state,
                disposition=disposition)
            if type(facts) is not multi_journal.ValidatedOriginalHostSettlement:
                raise ValueError("original_host_settlement_unavailable")
            return facts

        try:
            observation = multi_journal._issue_original_host_settlement_for_characterization(
                writer, expected_tip, request_index, validate_live_host)
            tip = self._append_multi_and_verify("settlement", expected_tip, observation)
            with self._lock:
                if self._closed or self._state_name != "settlement_writing":
                    self._state_name = "uncertain"
                    return "settlement_uncertain"
                self._tip = tip
                self._multi_expected_index += 1
                self._state_name = "settled"
            return "settled"
        except Exception:
            with self._lock:
                self._state_name = "uncertain"
            return "settlement_unavailable"

    def inspection_for_characterization(self):
        """Bounded private diagnostic; never exposes a writer or send capability."""
        with self._lock:
            tip = self._tip
            return {"state": self._state_name, "revision": tip.revision if tip else 0,
                    "digest": tip.digest if tip else None, "file_identity": tip.file_identity if tip else None,
                    "request_index": self._multi_expected_index if self._multi_request else 0,
                    "request_count": len(self._expected_requests) if self._multi_request else 1,
                    "closed": self._closed,
                    "execution_available": False, "protected_storage_available": False,
                    "promotion_available": False, "candidate_publication_allowed": False,
                    "authorship": "unverified"}

    def close(self):
        with self._lock:
            self._closed = True
            if self._state_name in {"send_permitted", "result_writing"}:
                self._state_name = "uncertain"
            elif self._state_name in {"unbound", "binding", "bound", "intent_writing", "intent_acknowledged"}:
                self._state_name = "closed"
            writer = self._writer if self._multi_request else None
        if writer is not None:
            try:
                writer.close_for_characterization()
            except Exception:
                # A writer already in an append remains uncertain and cannot
                # authorize a later request. Preserve its evidence in place.
                writer._uncertain = True


def create_executor_journal_intent_for_characterization(
        state, runtime, *, project_root, project_relative_path, journal_root,
        operation_id, characterization=False, disposable_opt_in=False,
        journal_fault=lambda boundary: None):
    return GenerationExecutorJournalIntent.create_for_characterization(
        state, runtime, project_root=project_root, project_relative_path=project_relative_path,
        journal_root=journal_root, operation_id=operation_id, characterization=characterization,
        disposable_opt_in=disposable_opt_in, journal_fault=journal_fault)
