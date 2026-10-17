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

from core import generation_ownership_journal as journal
from core import generation_protected_journal as protected_journal
from core.comfy_prompt_request import is_owner_prepared_frozen_request
from core.comfy_remote_output_receipts import valid_prompt_id
from ui.agent_generation_executor_handoff import GenerationPublicationOrigin
from ui.agent_generation_executor_inbox import ExecutionEnvelope, ExecutorEvent, GenerationExecutorInbox, HandoffReceipt
from ui.agent_generation_job import GenerationJobRegistry, JobRequest, WorkerEvent, _PROCESS_INCARNATION, _TERMINAL
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
        if type(manifest.requests) is not tuple or len(manifest.requests) != 1:
            raise ValueError("single_request_required")
        request = manifest.requests[0]
        if (request.request_index != 0 or type(request.request_id) is not str
                or type(request.workflow_identity) is not str):
            raise ValueError("request_identity_conflicting")
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
            (journal.FrozenRequestCorrelation(request.request_id, request.request_index,
                request.illustration_id, request.run_index, request.workflow_identity),))
        journal._validate_operation(operation)
        return origin, operation, request

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

    def bind_for_characterization(self, envelope, jobs, inbox, acceptance):
        with self._lock:
            if self._closed or self._state_name != "unbound":
                return "journal_binding_unavailable"
            self._state_name = "binding"
        try:
            if (type(acceptance) is not HandoffReceipt or acceptance.status != "accepted"
                    or inbox.accepted_receipt(jobs, acceptance).status != "characterized_acceptance"):
                raise ValueError("accepted_host_claim_required")
            origin, operation, request = self._capture_operation(envelope)
            self._origin, self._operation, self._envelope = origin, operation, envelope
            self._expected_request = request
            if not self._host_current(envelope, jobs, inbox, acceptance, request_state="unsent"):
                raise ValueError("stale_original_host")
            owner = self._journal_owner
            root = self._journal_root(owner)
            if root.identity != self._journal_root_identity:
                raise ValueError("journal_root_changed")
            root.check()
            if type(owner) is protected_journal.WindowsProtectedJournalCharacterization:
                if owner._writer is not None or owner.readiness().get("journal_lifecycle") != "protected_observation":
                    raise ValueError("journal_owner_unavailable")
                owner.initialize_for_characterization(operation)
                writer = owner._writer
            else:
                writer = journal.OfflineJournalWriter(root, operation,
                    characterization=True, fault=self._journal_fault)
            if (root.identity != self._journal_root_identity
                    or root.check() != Path(root.path)):
                raise ValueError("journal_root_changed")
            if (type(owner) is protected_journal.WindowsProtectedJournalCharacterization
                    and owner.readiness().get("journal_lifecycle") != "protected_observation"):
                raise ValueError("journal_owner_unavailable")
            if (writer is None or writer.operation != operation or writer.root.identity != self._journal_root_identity
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

    def acknowledge_intent_before_send_for_characterization(self, envelope, prepared, event,
                                                            jobs, inbox, acceptance):
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

    def record_submission_result_for_characterization(self, outcome, prompt_id=None):
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

    def inspection_for_characterization(self):
        """Bounded private diagnostic; never exposes a writer or send capability."""
        with self._lock:
            tip = self._tip
            return {"state": self._state_name, "revision": tip.revision if tip else 0,
                    "digest": tip.digest if tip else None, "file_identity": tip.file_identity if tip else None,
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


def create_executor_journal_intent_for_characterization(
        state, runtime, *, project_root, project_relative_path, journal_root,
        operation_id, characterization=False, disposable_opt_in=False,
        journal_fault=lambda boundary: None):
    return GenerationExecutorJournalIntent.create_for_characterization(
        state, runtime, project_root=project_root, project_relative_path=project_relative_path,
        journal_root=journal_root, operation_id=operation_id, characterization=characterization,
        disposable_opt_in=disposable_opt_in, journal_fault=journal_fault)
