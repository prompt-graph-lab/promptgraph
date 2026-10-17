"""C2B-8D-15A bounded multi-request Journal contract.

This is a separately identified offline characterization format. It preserves
the original eight-revision Journal unchanged and never restores runtime
authority from reopened bytes.
"""
from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import re
import threading
import uuid

from core import generation_ownership_journal as legacy


SCHEMA = "promptgraph-generation-multi-request-ownership"
VERSION = 1
MAX_REQUESTS = 100
MAX_REVISIONS = MAX_REQUESTS * 3
MAX_FILE_BYTES = 1024 * 1024
# At atomic replacement, one old journal and one complete temp file can coexist.
MAX_LIVE_OPERATION_BYTES = 2 * MAX_FILE_BYTES
# Includes each complete snapshot written by the append-only revision chain.
MAX_CUMULATIVE_WRITE_BYTES = 128 * 1024 * 1024
MAX_RETAINED_OBSERVATIONS = MAX_REVISIONS
_ZERO_DIGEST = "0" * 64
_FACTORY = object()
_HOST_ISSUER = object()


def _fail(code):
    raise ValueError(code)


def _operation_filename(operation_id):
    if type(operation_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", operation_id):
        _fail("invalid_operation_identifier")
    return operation_id + ".json"


@dataclass(frozen=True)
class SubmissionIntent:
    kind: str
    request_index: int
    request_id: str
    illustration_id: str
    run_index: int
    workflow_identity: str


@dataclass(frozen=True)
class SubmissionOutcome:
    kind: str
    request_index: int
    request_id: str
    outcome: str
    prompt_id: str | None


@dataclass(frozen=True)
class RequestSettlement:
    kind: str
    request_index: int
    request_id: str
    disposition: str
    prompt_id: str | None
    host_observation_id: str
    host_tip_revision: int
    host_tip_digest: str


@dataclass(frozen=True)
class JournalAcknowledgement:
    operation_id: str
    revision: int
    digest: str = field(repr=False)
    file_identity: tuple = field(repr=False)
    _owner_token: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class ValidatedOriginalHostSettlement:
    """Typed observation returned by the separate original-host validator."""

    operation_id: str
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str
    process_identity: str = field(repr=False)
    session_identity: str = field(repr=False)
    request_index: int
    request_id: str
    illustration_id: str
    run_index: int
    workflow_identity: str
    disposition: str
    prompt_id: str | None
    host_observation_id: str
    tip_revision: int
    tip_digest: str = field(repr=False)


@dataclass(frozen=True)
class OriginalHostSettlementObservation:
    """Live host observation; the instance is never serialized as authority."""

    operation_id: str
    job_id: str
    claim_id: str = field(repr=False)
    manifest_identity: str
    process_identity: str = field(repr=False)
    session_identity: str = field(repr=False)
    request_index: int
    request_id: str
    illustration_id: str
    run_index: int
    workflow_identity: str
    disposition: str
    prompt_id: str | None
    host_observation_id: str
    _tip: JournalAcknowledgement = field(repr=False, compare=False)
    _writer_token: object = field(repr=False, compare=False)

    @classmethod
    def _issue_for_characterization(cls, writer, expected_tip, facts, *, _issuer=None):
        # C2B-8D-15B must call this only after its original-host owner has
        # independently validated the terminal request state and freshness.
        # The private issuer and live tip prevent Journal bytes or a prompt ID
        # from reconstructing this in-memory observation.
        if _issuer is not _HOST_ISSUER:
            _fail("original_host_settlement_required")
        writer._validate_settlement_issue(expected_tip, facts)
        request = writer.operation.requests[facts.request_index]
        operation = writer.operation
        observation = cls(operation.operation_id, operation.job_id, operation.claim_id,
                   operation.manifest_identity, operation.process_identity, operation.session_identity,
                   facts.request_index, request.request_id,
                   request.illustration_id, request.run_index, request.workflow_identity,
                   facts.disposition, facts.prompt_id, facts.host_observation_id,
                   expected_tip, writer._owner_token)
        writer._issued_settlement = observation
        return observation


@dataclass(frozen=True)
class ReopenedMultiRequestJournal:
    operation: legacy.OperationObservation
    events: tuple
    revision: int
    digest: str
    file_identity: tuple
    next_request_index: int
    state: str
    trust: str = "inspect_only"
    authorship: str = "unverified"
    execution_available: bool = False


def _decode_event(raw):
    if type(raw) is not dict or type(raw.get("kind")) is not str:
        _fail("invalid_event")
    kinds = {
        "submission_intent": SubmissionIntent,
        "submission_outcome": SubmissionOutcome,
        "request_settlement": RequestSettlement,
    }
    cls = kinds.get(raw["kind"])
    if cls is None or set(raw) != set(cls.__dataclass_fields__):
        _fail("invalid_event")
    return cls(**raw)


def _validate_event(event, operation):
    if type(event) not in (SubmissionIntent, SubmissionOutcome, RequestSettlement):
        _fail("invalid_event")
    if (type(event.request_index) is not int or not 0 <= event.request_index < len(operation.requests)
            or event.request_index >= MAX_REQUESTS):
        _fail("invalid_request_order")
    request = operation.requests[event.request_index]
    if event.request_id != request.request_id:
        _fail("request_identity_conflicting")
    if type(event.kind) is not str:
        _fail("invalid_event")
    if type(event) is SubmissionIntent:
        if (event.kind != "submission_intent" or type(event.illustration_id) is not str
                or type(event.run_index) is not int or event.illustration_id != request.illustration_id
                or event.run_index != request.run_index or event.workflow_identity != request.workflow_identity):
            _fail("request_identity_conflicting")
        for value in (event.request_id, event.illustration_id, event.workflow_identity):
            legacy._id(value)
    elif type(event) is SubmissionOutcome:
        if event.kind != "submission_outcome" or event.outcome not in ("accepted", "pre_send_rejected", "unknown"):
            _fail("invalid_submission_outcome")
        if event.prompt_id is not None:
            legacy._id(event.prompt_id)
        if ((event.outcome == "accepted" and event.prompt_id is None)
                or (event.outcome == "pre_send_rejected" and event.prompt_id is not None)):
            _fail("invalid_submission_outcome")
    else:
        if (event.kind != "request_settlement"
                or event.disposition not in ("execution_completed", "execution_failed", "pre_send_rejected")
                or type(event.host_tip_revision) is not int or event.host_tip_revision < 1):
            _fail("invalid_settlement")
        legacy._id(event.host_observation_id)
        legacy._digest(event.host_tip_digest)
        if event.prompt_id is not None:
            legacy._id(event.prompt_id)


def _sequence_state(operation, events):
    next_index = 0
    phase = "ready"
    outcome = None
    prompt_id = None
    current_index = None
    for event_index, event in enumerate(events):
        _validate_event(event, operation)
        index = event.request_index
        if type(event) is SubmissionIntent:
            if phase != "ready" or index != next_index:
                _fail("invalid_request_order")
            phase, current_index, outcome, prompt_id = "awaiting_outcome", index, None, None
        elif type(event) is SubmissionOutcome:
            if phase != "awaiting_outcome" or index != current_index:
                _fail("conflicting_submission_outcome")
            phase, outcome, prompt_id = "awaiting_settlement", event.outcome, event.prompt_id
            if event.outcome == "unknown":
                phase = "blocked_unknown"
        else:
            if phase != "awaiting_settlement" or index != current_index:
                _fail("settlement_not_expected")
            if event.host_tip_revision != event_index:
                _fail("settlement_tip_mismatch")
            if outcome == "accepted":
                if (event.disposition not in ("execution_completed", "execution_failed")
                        or event.prompt_id != prompt_id or event.prompt_id is None):
                    _fail("settlement_outcome_mismatch")
            elif outcome == "pre_send_rejected":
                if event.disposition != "pre_send_rejected" or event.prompt_id is not None:
                    _fail("settlement_outcome_mismatch")
            else:
                _fail("settlement_outcome_mismatch")
            next_index = index + 1
            current_index, phase, outcome, prompt_id = None, "ready", None, None
    if phase == "ready":
        state = "all_requests_settled" if next_index == len(operation.requests) else "ready_for_request"
    elif phase == "awaiting_outcome":
        state = "intent_outcome_unknown"
    elif phase == "awaiting_settlement":
        state = "awaiting_original_host_settlement"
    else:
        state = "submission_outcome_unknown"
    return next_index, state


def _validate_entries(operation, entries):
    if type(entries) is not list or not 1 <= len(entries) <= MAX_REVISIONS:
        _fail("invalid_revision")
    previous = _ZERO_DIGEST
    events = []
    for index, entry in enumerate(entries):
        if (type(entry) is not dict or set(entry) != {"revision", "previous_digest", "event", "digest"}
                or type(entry["revision"]) is not int or entry["revision"] != index + 1
                or entry["previous_digest"] != previous):
            _fail("conflicting_revision")
        event = _decode_event(entry["event"])
        _validate_event(event, operation)
        if type(event) is RequestSettlement:
            if (event.host_tip_revision != index or event.host_tip_digest != previous):
                _fail("settlement_tip_mismatch")
        unsigned = {"revision": entry["revision"], "previous_digest": previous, "event": entry["event"]}
        expected = legacy._hash({"schema": SCHEMA, "version": VERSION,
                                  "operation": asdict(operation), **unsigned})
        if legacy._digest(entry["digest"]) != expected:
            _fail("digest_mismatch")
        previous = expected
        events.append(event)
    return tuple(events), previous, _sequence_state(operation, events)


def _header(root, operation):
    return {"schema": SCHEMA, "version": VERSION, "root_path": root.path,
            "root_identity": root.identity, "operation": asdict(operation)}


def _maximum_workload(operation, root):
    """Return worst-case final-file and full-snapshot write ceilings."""
    header = _header(root, operation)
    entries = []
    previous = _ZERO_DIGEST
    cumulative = 0
    maximum = 0
    for request in operation.requests:
        intent = SubmissionIntent("submission_intent", request.request_index, request.request_id,
                                  request.illustration_id, request.run_index, request.workflow_identity)
        # Bound both valid outcome forms and their longest legal values.
        outcomes = (
            SubmissionOutcome("submission_outcome", request.request_index, request.request_id,
                              "accepted", "p" * 160),
            SubmissionOutcome("submission_outcome", request.request_index, request.request_id,
                              "pre_send_rejected", None),
        )
        settlement = RequestSettlement("request_settlement", request.request_index, request.request_id,
            "execution_failed", "p" * 160, "h" * 160, len(entries) + 2, _ZERO_DIGEST)
        for event in (intent, max(outcomes, key=lambda item: len(legacy._encoded(asdict(item)))), settlement):
            unsigned = {"revision": len(entries) + 1, "previous_digest": previous, "event": asdict(event)}
            digest = legacy._hash({"schema": SCHEMA, "version": VERSION,
                                   "operation": asdict(operation), **unsigned})
            entry = {**unsigned, "digest": digest}
            entries.append(entry)
            previous = digest
            size = len(legacy._encoded({**header, "revisions": entries}))
            if size > MAX_FILE_BYTES:
                _fail("journal_capacity_exceeded")
            cumulative += size
            maximum = size
            if cumulative > MAX_CUMULATIVE_WRITE_BYTES:
                _fail("journal_write_budget_exceeded")
    return maximum, cumulative


def reopen_multi_request_journal(root, filename, *, expected_revision=None, expected_digest=None):
    """Validate bytes for inspection only; never reconstruct a live writer."""
    legacy._relative(filename)
    data, identity = legacy._read(root, filename, limit=MAX_FILE_BYTES)
    value = legacy._json(data)
    if type(value) is not dict or set(value) != {"schema", "version", "root_path", "root_identity", "operation", "revisions"}:
        _fail("invalid_schema")
    if value["schema"] != SCHEMA or type(value["version"]) is not int or value["version"] != VERSION:
        _fail("unknown_version")
    if value["root_path"] != root.path or legacy._identity(value["root_identity"]) != tuple(root.identity):
        _fail("root_identity_changed")
    operation = legacy._exact(value["operation"], legacy.OperationObservation)
    legacy._validate_operation(operation)
    if filename != _operation_filename(operation.operation_id):
        _fail("operation_identity_mismatch")
    events, digest, (next_index, state) = _validate_entries(operation, value["revisions"])
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision != len(events)):
        _fail("stale_revision")
    if expected_digest is not None and legacy._digest(expected_digest) != digest:
        _fail("conflicting_revision")
    return ReopenedMultiRequestJournal(operation, events, len(events), digest, identity, next_index, state)


class MultiRequestJournalWriter:
    """Exclusive live writer; acknowledgements are exact in-memory tip tokens."""

    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    authorship = "unverified"

    def _create_exclusive_file(self, path, flags):
        return os.open(path, flags, 0o600)

    def _check_file(self, path, identity):
        if legacy._file_identity(legacy._ordinary(path, directory=False)) != tuple(identity):
            _fail("file_identity_changed")

    def _release_lock(self, path, identity):
        self.root.check()
        self._check_file(path, identity)
        path.unlink()
        self.root.check()

    def __init__(self, root, operation, *, characterization=False, fault=lambda boundary: None):
        if characterization is not True:
            _fail("execution_unavailable")
        if not callable(fault):
            _fail("invalid_fault_hook")
        legacy._validate_operation(operation)
        if len(operation.requests) > MAX_REQUESTS:
            _fail("request_limit_exceeded")
        root.check()
        self.root, self.operation, self.fault = root, operation, fault
        self.filename = _operation_filename(operation.operation_id)
        self._revision, self._digest, self._file_identity = 0, _ZERO_DIGEST, None
        self._entries = []
        self._events = []
        self._tip = None
        self._issued_settlement = None
        self._owner_token = object()
        self._uncertain = False
        self._closed = False
        self._busy = threading.Lock()
        self._maximum_file_bytes, self._maximum_cumulative_bytes = _maximum_workload(operation, root)

    def _assert_tip(self, expected_tip):
        if expected_tip is not self._tip:
            _fail("acknowledged_tip_conflict")
        if expected_tip is not None and (type(expected_tip) is not JournalAcknowledgement
                or expected_tip.operation_id != self.operation.operation_id
                or expected_tip.revision != self._revision or expected_tip.digest != self._digest
                or expected_tip.file_identity != self._file_identity
                or expected_tip._owner_token is not self._owner_token):
            _fail("acknowledged_tip_conflict")

    def _state(self):
        return _sequence_state(self.operation, self._events)

    def _enter(self):
        if not self._busy.acquire(blocking=False):
            _fail("writer_busy")

    def _leave(self):
        self._busy.release()

    def append_intent_for_characterization(self, expected_tip, request_index):
        self._enter()
        try:
            self._assert_writable(expected_tip)
            next_index, state = self._state()
            if (state != "ready_for_request" or request_index != next_index
                    or type(request_index) is not int):
                _fail("invalid_request_order")
            request = self.operation.requests[request_index]
            event = SubmissionIntent("submission_intent", request_index, request.request_id,
                                     request.illustration_id, request.run_index, request.workflow_identity)
            return self._append(expected_tip, event)
        finally:
            self._leave()

    def append_submission_outcome_for_characterization(self, expected_tip, outcome, prompt_id=None):
        self._enter()
        try:
            self._assert_writable(expected_tip)
            next_index, state = self._state()
            if state != "intent_outcome_unknown":
                _fail("submission_outcome_not_expected")
            request = self.operation.requests[next_index]
            event = SubmissionOutcome("submission_outcome", next_index, request.request_id, outcome, prompt_id)
            _validate_event(event, self.operation)
            return self._append(expected_tip, event)
        finally:
            self._leave()

    def append_settlement_for_characterization(self, expected_tip, settlement):
        self._enter()
        try:
            self._assert_writable(expected_tip)
            if (type(settlement) is not OriginalHostSettlementObservation
                    or settlement is not self._issued_settlement
                    or settlement._writer_token is not self._owner_token
                    or settlement._tip is not expected_tip):
                _fail("original_host_settlement_required")
            next_index, state = self._state()
            if state != "awaiting_original_host_settlement" or settlement.request_index != next_index:
                _fail("settlement_not_expected")
            request = self.operation.requests[next_index]
            if (settlement.operation_id != self.operation.operation_id
                    or settlement.job_id != self.operation.job_id
                    or settlement.claim_id != self.operation.claim_id
                    or settlement.manifest_identity != self.operation.manifest_identity
                    or settlement.process_identity != self.operation.process_identity
                    or settlement.session_identity != self.operation.session_identity
                    or settlement.request_id != request.request_id
                    or settlement.illustration_id != request.illustration_id
                    or settlement.run_index != request.run_index
                    or settlement.workflow_identity != request.workflow_identity):
                _fail("settlement_identity_conflicting")
            event = RequestSettlement("request_settlement", next_index, request.request_id,
                settlement.disposition, settlement.prompt_id, settlement.host_observation_id,
                expected_tip.revision, expected_tip.digest)
            return self._append(expected_tip, event)
        finally:
            self._leave()

    def _validate_settlement_issue(self, expected_tip, facts):
        self._assert_writable(expected_tip)
        next_index, state = self._state()
        if type(facts) is not ValidatedOriginalHostSettlement:
            _fail("original_host_settlement_required")
        if state != "awaiting_original_host_settlement" or facts.request_index != next_index:
            _fail("settlement_not_expected")
        request = self.operation.requests[next_index]
        operation = self.operation
        if (facts.operation_id != operation.operation_id or facts.job_id != operation.job_id
                or facts.claim_id != operation.claim_id or facts.manifest_identity != operation.manifest_identity
                or facts.process_identity != operation.process_identity or facts.session_identity != operation.session_identity
                or facts.request_id != request.request_id or facts.illustration_id != request.illustration_id
                or facts.run_index != request.run_index or facts.workflow_identity != request.workflow_identity
                or facts.tip_revision != expected_tip.revision or facts.tip_digest != expected_tip.digest):
            _fail("settlement_identity_conflicting")
        _validate_event(RequestSettlement("request_settlement", next_index,
            request.request_id, facts.disposition, facts.prompt_id,
            facts.host_observation_id, expected_tip.revision, expected_tip.digest), operation)
        previous = self._events[-1]
        if type(previous) is not SubmissionOutcome:
            _fail("settlement_not_expected")
        if previous.outcome == "accepted":
            if facts.disposition not in ("execution_completed", "execution_failed") or facts.prompt_id != previous.prompt_id:
                _fail("settlement_outcome_mismatch")
        elif previous.outcome == "pre_send_rejected":
            if facts.disposition != "pre_send_rejected" or facts.prompt_id is not None:
                _fail("settlement_outcome_mismatch")
        else:
            _fail("settlement_outcome_mismatch")

    def _assert_writable(self, expected_tip):
        if self._closed:
            _fail("writer_closed")
        if self._uncertain:
            _fail("writer_uncertain")
        self._assert_tip(expected_tip)

    def _append(self, expected_tip, event):
        if self._revision >= MAX_REVISIONS or len(self._events) >= MAX_RETAINED_OBSERVATIONS:
            _fail("revision_limit_exceeded")
        _validate_event(event, self.operation)
        next_events = [*self._events, event]
        _sequence_state(self.operation, next_events)
        unsigned = {"revision": self._revision + 1, "previous_digest": self._digest,
                    "event": asdict(event)}
        digest = legacy._hash({"schema": SCHEMA, "version": VERSION,
            "operation": asdict(self.operation), **unsigned})
        entries = [*self._entries, {**unsigned, "digest": digest}]
        data = legacy._encoded({**_header(self.root, self.operation), "revisions": entries})
        # Worst-case preflight at construction reserves enough space for every
        # possible result and settlement before any send can be authorized.
        if len(data) > MAX_FILE_BYTES:
            _fail("journal_capacity_exceeded")
        if self._maximum_cumulative_bytes > MAX_CUMULATIVE_WRITE_BYTES:
            _fail("journal_write_budget_exceeded")
        base = self.root.check()
        target = base / self.filename
        lock = base / (self.operation.operation_id + ".lock")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        lock_fd = self._create_exclusive_file(lock, flags | getattr(os, "O_BINARY", 0))
        lock_identity = legacy._file_identity(os.fstat(lock_fd))
        os.close(lock_fd)
        acknowledged = False
        try:
            if self._revision:
                prior = reopen_multi_request_journal(self.root, self.filename)
                if (prior.revision != self._revision or prior.digest != self._digest
                        or prior.file_identity != self._file_identity or prior.operation != self.operation):
                    _fail("conflicting_revision")
            elif target.exists() or target.is_symlink():
                _fail("conflicting_revision")
            # Orphan temps are retained evidence and prohibit another attempt.
            if any(name.startswith(self.operation.operation_id + ".") and name.endswith(".tmp")
                   for name in os.listdir(base)):
                _fail("uncertain_evidence_exists")
            temp = base / (self.operation.operation_id + "." + uuid.uuid4().hex + ".tmp")
            if len(data) + (target.stat().st_size if target.exists() else 0) > MAX_LIVE_OPERATION_BYTES:
                _fail("journal_live_storage_limit")
            fd = self._create_exclusive_file(temp, flags | getattr(os, "O_BINARY", 0))
            temp_identity = legacy._file_identity(os.fstat(fd))
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            self.fault("before_replace")
            self.root.check()
            self._check_file(temp, temp_identity)
            self._check_file(lock, lock_identity)
            if self._revision:
                current = reopen_multi_request_journal(self.root, self.filename)
                if current.file_identity != self._file_identity or current.digest != self._digest:
                    _fail("conflicting_revision")
            elif target.exists() or target.is_symlink():
                _fail("conflicting_revision")
            os.replace(temp, target)
            self.fault("after_replace_before_ack")
            observed = reopen_multi_request_journal(self.root, self.filename)
            if observed.revision != self._revision + 1 or observed.digest != digest:
                _fail("conflicting_revision")
            # Release the live writer's exact lock before publishing the ACK.
            self._release_lock(lock, lock_identity)
            self._entries, self._events = entries, next_events
            self._revision, self._digest, self._file_identity = observed.revision, digest, observed.file_identity
            self._tip = JournalAcknowledgement(self.operation.operation_id, self._revision,
                self._digest, self._file_identity, self._owner_token)
            if type(event) is RequestSettlement:
                self._issued_settlement = None
            acknowledged = True
            return self._tip
        except BaseException:
            self._uncertain = True
            raise
        finally:
            if acknowledged:
                # The exact lock was released above. Never clean up on failure.
                pass

    def close_for_characterization(self):
        if not self._busy.acquire(blocking=False):
            _fail("writer_busy")
        try:
            self._closed = True
        finally:
            self._busy.release()


def _issue_original_host_settlement_for_characterization(writer, expected_tip, request_index,
        host_validator):
    """Test seam standing in for a separately checked original-host owner.

    Production integration must replace this fixture issuer with an opaque
    observation emitted only after current original-host settlement validation.
    Journal parsing never calls this function.
    """
    if not isinstance(writer, MultiRequestJournalWriter) or not callable(host_validator):
        _fail("original_host_settlement_required")
    # The original-host check runs outside the Journal writer lock. Its typed
    # result is then bound to the still-current exact acknowledgment below.
    if (type(request_index) is not int or not 0 <= request_index < len(writer.operation.requests)
            or expected_tip is not writer._tip):
        _fail("settlement_not_expected")
    request = writer.operation.requests[request_index]
    facts = host_validator(writer.operation, request, expected_tip)
    if type(facts) is not ValidatedOriginalHostSettlement:
        _fail("original_host_settlement_required")
    writer._enter()
    try:
        if writer._issued_settlement is not None:
            _fail("settlement_already_issued")
        return OriginalHostSettlementObservation._issue_for_characterization(
            writer, expected_tip, facts, _issuer=_HOST_ISSUER)
    finally:
        writer._leave()
