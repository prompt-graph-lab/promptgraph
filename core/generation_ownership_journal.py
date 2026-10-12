"""Offline C2B-8A observations. Reopened evidence never confers runtime authority."""
from dataclasses import asdict, dataclass, field
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import uuid
from types import SimpleNamespace

from core.comfy_output_containment import (
    _ordinary as _storage_ordinary, _file_identity, _ContainmentFailure,
    ContainedOutputStore, ContainmentLimits, SUPPORTED_EXTENSIONS,
)

MAX_BYTES = 1024 * 1024
MAX_IMAGES = 1600
MAX_OPERATION_FILES = 1600  # staging and durable references share this ceiling
MAX_OPERATION_BYTES = 256 * 1024 * 1024
SCHEMA = "promptgraph-generation-ownership"
CHECKPOINTS = ("submission_intent", "submission_observed", "download_attempt",
               "images_verified", "promotion_intent", "registration_observed",
               "save_intent", "save_observed")
OUTCOMES = ("intent", "accepted", "failed", "unknown", "verified", "registered",
            "partial", "saved", "uncertain")


def _fail(code):
    raise ValueError(code)


def _ordinary(path, *, directory):
    try:
        return _storage_ordinary(path, directory=directory)
    except _ContainmentFailure:
        _fail("unsafe_storage")


def _id(value):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_:.-]{1,160}", value):
        _fail("invalid_identifier")
    return value


def _digest(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail("invalid_digest")
    return value


def _relative(value):
    if (type(value) is not str or not value or len(value) > 256
            or "\\" in value or ":" in value or "\x00" in value
            or value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/"))):
        _fail("unsafe_relative_path")
    return value


def _identity(value):
    if (type(value) not in (tuple, list) or len(value) != 2
            or any(type(x) is not int or x < 0 for x in value)):
        _fail("invalid_file_identity")
    return tuple(value)


def _canonical(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        _fail("unsafe_path")
    return path


def _observed_absolute(value):
    # Validate untrusted stored names lexically. Do not probe a journal-supplied
    # absolute path; only independently approved roots may touch the filesystem.
    if (type(value) is not str or len(value) > 1024 or "\x00" in value
            or not Path(value).is_absolute() or os.path.normpath(value) != value):
        _fail("unsafe_path")


@dataclass(frozen=True)
class ApprovedRoot:
    """Host-supplied allowlist entry; never constructed from journal authority."""
    key: str
    path: str
    identity: tuple

    @classmethod
    def capture_for_characterization(cls, key, path, *, characterization=False):
        if characterization is not True:
            _fail("execution_unavailable")
        path = _canonical(path)
        return cls(_id(key), str(path), _file_identity(_ordinary(path, directory=True)))

    def check(self):
        _id(self.key)
        path = _canonical(self.path)
        if _file_identity(_ordinary(path, directory=True)) != _identity(self.identity):
            _fail("root_identity_changed")
        return path


@dataclass(frozen=True)
class FileObservation:
    root_key: str
    root_path: str
    root_identity: tuple
    relative_path: str
    file_identity: tuple
    content_sha256: str
    byte_count: int
    role: str  # contained or promoted
    image_format: str
    width: int
    height: int
    request_id: str
    descriptor_identity: str
    output_index: int
    verification_state: str


@dataclass(frozen=True)
class CandidateObservation:
    illustration_id: str
    job_id: str
    claim_id: str
    manifest_identity: str
    request_id: str
    request_index: int
    run_index: int
    workflow_identity: str
    prompt_id: str
    remote_receipt_identity: str
    local_receipt_identity: str
    descriptor_identity: str
    output_index: int
    content_sha256: str
    asset_root_key: str
    asset_relative_path: str


@dataclass(frozen=True)
class RequestObservation:
    request_id: str
    request_index: int
    workflow_identity: str
    outcome: str
    prompt_id: str | None = None


@dataclass(frozen=True)
class FrozenRequestCorrelation:
    request_id: str
    request_index: int
    illustration_id: str
    run_index: int
    workflow_identity: str


@dataclass(frozen=True)
class RemoteResultObservation:
    request_id: str
    prompt_id: str
    remote_receipt_identity: str
    result_sha256: str
    execution_evidence: str  # validated_success, validated_failure, unproven
    state: str  # ready, pending, unknown, stale, quarantined, unresolved


@dataclass(frozen=True)
class ContainmentObservation:
    request_id: str
    remote_receipt_identity: str
    local_receipt_identity: str
    state: str  # verified, incomplete, quarantined, stale, unresolved
    expected_count: int
    verified_count: int


@dataclass(frozen=True)
class PromotionObservation:
    request_id: str
    local_receipt_identity: str
    root_key: str
    relative_paths: tuple[str, ...]
    state: str  # intent, complete, partial, failed, unknown, stale


@dataclass(frozen=True)
class ProjectSaveObservation:
    root_key: str
    relative_path: str
    state: str  # intent, saved, failed, uncertain
    observed_file_identity: tuple | None = None
    observed_json_sha256: str | None = None


@dataclass(frozen=True)
class UnresolvedObservation:
    request_id: str | None
    state: str  # unknown, stale, quarantined, unresolved
    reason: str  # fixed safe code; never exception/payload text


@dataclass(frozen=True)
class Observation:
    checkpoint: str
    outcome: str
    files: tuple[FileObservation, ...] = ()
    candidates: tuple[CandidateObservation, ...] = ()
    requests: tuple[RequestObservation, ...] = ()
    remote_results: tuple[RemoteResultObservation, ...] = ()
    containment: tuple[ContainmentObservation, ...] = ()
    promotions: tuple[PromotionObservation, ...] = ()
    save: ProjectSaveObservation | None = None
    unresolved: tuple[UnresolvedObservation, ...] = ()


@dataclass(frozen=True)
class OperationObservation:
    operation_id: str
    job_id: str
    manifest_identity: str
    source_sha256: str
    project_root_key: str
    project_root_path: str
    project_root_identity: tuple
    project_relative_path: str
    project_file_identity: tuple
    process_identity: str = field(repr=False)
    session_identity: str = field(repr=False)
    claim_id: str = field(repr=False)
    review_sha256: str = field(repr=False)
    requests: tuple[FrozenRequestCorrelation, ...] = field(repr=False)


def _exact(value, cls):
    if type(value) is not dict or set(value) != set(cls.__dataclass_fields__):
        _fail("invalid_schema")
    value = dict(value)
    for key in ("file_identity", "project_file_identity", "root_identity", "project_root_identity", "observed_file_identity"):
        if key in value:
            value[key] = _identity(value[key]) if value[key] is not None else None
    if cls is OperationObservation:
        if type(value["requests"]) not in (list, tuple) or not 1 <= len(value["requests"]) <= 100:
            _fail("invalid_request")
        value["requests"] = tuple(_exact(x, FrozenRequestCorrelation) for x in value["requests"])
    if cls is PromotionObservation:
        if type(value["relative_paths"]) not in (list, tuple):
            _fail("invalid_schema")
        value["relative_paths"] = tuple(value["relative_paths"])
    return cls(**value)


def _validate_operation(op):
    if type(op) is not OperationObservation:
        _fail("invalid_schema")
    if type(op.operation_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", op.operation_id):
        _fail("invalid_operation_identifier")
    for key in (op.operation_id, op.job_id, op.manifest_identity, op.project_root_key,
                op.process_identity, op.session_identity, op.claim_id):
        _id(key)
    _digest(op.source_sha256)
    _digest(op.review_sha256)
    _relative(op.project_relative_path)
    _observed_absolute(op.project_root_path)
    _identity(op.project_root_identity)
    _identity(op.project_file_identity)
    if type(op.requests) is not tuple or not 1 <= len(op.requests) <= 100:
        _fail("invalid_request")
    seen = set()
    for index, request in enumerate(op.requests):
        if type(request) is not FrozenRequestCorrelation:
            _fail("invalid_schema")
        for value in (request.request_id, request.illustration_id, request.workflow_identity):
            _id(value)
        if (type(request.request_index) is not int or request.request_index != index
                or type(request.run_index) is not int or not 1 <= request.run_index <= 5
                or request.request_id in seen):
            _fail("invalid_request")
        seen.add(request.request_id)


def _validate_observation(obs, index):
    if (type(obs) is not Observation or obs.checkpoint != CHECKPOINTS[index]
            or obs.outcome not in OUTCOMES or type(obs.files) is not tuple
            or type(obs.candidates) is not tuple or len(obs.files) > MAX_IMAGES
            or len(obs.candidates) > MAX_IMAGES or type(obs.requests) is not tuple
            or len(obs.requests) > 100):
        _fail("invalid_checkpoint")
    allowed = ({"intent"}, {"accepted", "failed", "unknown"}, {"intent"},
               {"verified", "partial", "failed", "unknown"}, {"intent"},
               {"registered", "partial", "failed", "uncertain"}, {"intent"},
               {"saved", "failed", "uncertain"})
    if obs.outcome not in allowed[index]:
        _fail("invalid_outcome")
    if ((obs.requests and index not in (0, 1))
            or (obs.remote_results and index not in (1, 2, 3))
            or (obs.containment and index != 3)
            or (obs.files and index not in (3, 5))
            or (obs.promotions and index not in (4, 5))
            or (obs.candidates and index != 5)
            or (index in (6, 7) and obs.save is None)):
        _fail("checkpoint_evidence_misplaced")
    for items, cls in ((obs.remote_results, RemoteResultObservation), (obs.containment, ContainmentObservation),
                       (obs.promotions, PromotionObservation), (obs.unresolved, UnresolvedObservation)):
        if type(items) is not tuple or len(items) > 100 or any(type(item) is not cls for item in items):
            _fail("invalid_schema")
    for item in obs.remote_results:
        for value in (item.request_id, item.prompt_id, item.remote_receipt_identity):
            _id(value)
        _digest(item.result_sha256)
        if (item.execution_evidence not in ("validated_success", "validated_failure", "unproven")
                or item.state not in ("ready", "pending", "unknown", "stale", "quarantined", "unresolved")):
            _fail("invalid_remote_result")
    for item in obs.containment:
        for value in (item.request_id, item.remote_receipt_identity, item.local_receipt_identity):
            _id(value)
        if (item.state not in ("verified", "incomplete", "quarantined", "stale", "unresolved")
                or type(item.expected_count) is not int or not 1 <= item.expected_count <= 16
                or type(item.verified_count) is not int or not 0 <= item.verified_count <= item.expected_count
                or item.state == "verified" and item.verified_count != item.expected_count):
            _fail("invalid_containment")
    for item in obs.promotions:
        for value in (item.request_id, item.local_receipt_identity, item.root_key):
            _id(value)
        if (type(item.relative_paths) is not tuple or not 1 <= len(item.relative_paths) <= 16
                or len(set(item.relative_paths)) != len(item.relative_paths)
                or item.state not in ("intent", "complete", "partial", "failed", "unknown", "stale")):
            _fail("invalid_promotion")
        for path in item.relative_paths:
            _relative(path)
        if (index == 4 and item.state != "intent") or (index == 5 and item.state == "intent"):
            _fail("checkpoint_evidence_misplaced")
    if obs.save is not None:
        if type(obs.save) is not ProjectSaveObservation or index not in (6, 7):
            _fail("invalid_save")
        _id(obs.save.root_key)
        _relative(obs.save.relative_path)
        if obs.save.state != obs.outcome:
            _fail("invalid_save")
        if obs.save.observed_file_identity is not None:
            _identity(obs.save.observed_file_identity)
        if obs.save.observed_json_sha256 is not None:
            _digest(obs.save.observed_json_sha256)
    for item in obs.unresolved:
        if item.request_id is not None:
            _id(item.request_id)
        if (item.state not in ("unknown", "stale", "quarantined", "unresolved")
                or item.reason not in ("host_lost", "crash_interrupted", "remote_unknown", "missing_evidence",
                                       "integrity_conflict", "partial_operation")):
            _fail("invalid_unresolved_state")
    seen = set()
    for item in obs.requests:
        if type(item) is not RequestObservation:
            _fail("invalid_schema")
        _id(item.request_id)
        _id(item.workflow_identity)
        if (type(item.request_index) is not int or not 0 <= item.request_index < 100
                or item.outcome not in ("intent", "accepted", "failed", "unknown")
                or item.request_id in seen):
            _fail("invalid_request")
        seen.add(item.request_id)
        if item.prompt_id is not None:
            _id(item.prompt_id)
        if (index == 0 and (item.outcome != "intent" or item.prompt_id is not None)
                or index == 1 and item.outcome == "intent"
                or item.outcome == "accepted" and item.prompt_id is None):
            _fail("invalid_submission_observation")
    for item in obs.files:
        if type(item) is not FileObservation:
            _fail("invalid_schema")
        _id(item.root_key)
        _id(item.request_id)
        _id(item.descriptor_identity)
        if (type(item.output_index) is not int or not 1 <= item.output_index <= 16
                or item.verification_state not in ("verified", "incomplete", "quarantined", "stale", "unresolved")):
            _fail("invalid_verification_state")
        _observed_absolute(item.root_path)
        _identity(item.root_identity)
        _relative(item.relative_path)
        _identity(item.file_identity)
        _digest(item.content_sha256)
        if type(item.byte_count) is not int or not 0 < item.byte_count <= 32 * 1024 * 1024:
            _fail("invalid_size")
        if item.role not in ("contained", "promoted"):
            _fail("invalid_role")
        if item.role != ("contained" if index == 3 else "promoted"):
            _fail("checkpoint_evidence_misplaced")
        if item.image_format not in SUPPORTED_EXTENSIONS.values():
            _fail("invalid_image_format")
        if (type(item.width) is not int or type(item.height) is not int
                or not 0 < item.width <= 8192 or not 0 < item.height <= 8192
                or item.width * item.height > 16777216):
            _fail("invalid_image_dimensions")
    for item in obs.candidates:
        if type(item) is not CandidateObservation:
            _fail("invalid_schema")
        for key in ("illustration_id", "job_id", "claim_id", "manifest_identity", "request_id",
                    "workflow_identity", "prompt_id", "remote_receipt_identity",
                    "local_receipt_identity", "descriptor_identity", "asset_root_key"):
            _id(getattr(item, key))
        for key in ("request_index", "run_index", "output_index"):
            value = getattr(item, key)
            upper = {"request_index": 99, "run_index": 5, "output_index": 16}[key]
            if type(value) is not int or not (0 if key == "request_index" else 1) <= value <= upper:
                _fail("invalid_index")
        _digest(item.content_sha256)
        _relative(item.asset_relative_path)


def _validate_contract(operation, observations):
    requests = {r.request_id: r for r in operation.requests}
    files, references, role_bytes, prompts, remotes, locals_ = {}, set(), {"contained": 0, "promoted": 0}, {}, {}, {}
    for obs in observations:
        for item in (*obs.requests, *obs.files, *obs.candidates, *obs.remote_results,
                     *obs.containment, *obs.promotions, *obs.unresolved):
            if item.request_id is None:
                continue
            if item.request_id not in requests:
                _fail("request_identity_conflicting")
            frozen = requests[item.request_id]
            for key in ("request_index", "illustration_id", "run_index", "workflow_identity"):
                if hasattr(item, key) and getattr(item, key) != getattr(frozen, key):
                    _fail("request_identity_conflicting")
            if type(item) is CandidateObservation and (item.job_id, item.claim_id, item.manifest_identity) != (
                    operation.job_id, operation.claim_id, operation.manifest_identity):
                _fail("operation_identity_mismatch")
            for key, mapping in (("prompt_id", prompts), ("remote_receipt_identity", remotes), ("local_receipt_identity", locals_)):
                value = getattr(item, key, None)
                if value is not None:
                    if item.request_id in mapping and mapping[item.request_id] != value:
                        _fail("receipt_identity_conflicting")
                    mapping[item.request_id] = value
        if obs.save is not None and (obs.save.root_key, obs.save.relative_path) != (
                operation.project_root_key, operation.project_relative_path):
            _fail("operation_identity_mismatch")
        for image in obs.files:
            key = image.root_key, image.relative_path
            references.add(key)
            if key not in files:
                files[key] = image
                role_bytes[image.role] += image.byte_count
            else:
                previous = files[key]
                if previous.role != image.role:
                    _fail("reference_identity_conflicting")
                if image.byte_count > previous.byte_count:
                    role_bytes[image.role] += image.byte_count - previous.byte_count
                    files[key] = image
        for candidate in obs.candidates:
            references.add((candidate.asset_root_key, candidate.asset_relative_path))
        for promotion in obs.promotions:
            references.update((promotion.root_key, name) for name in promotion.relative_paths)
    if len(references) > MAX_OPERATION_FILES or sum(role_bytes.values()) > MAX_OPERATION_BYTES:
        _fail("operation_budget_exceeded")


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


def _json(data):
    if len(data) > MAX_BYTES:
        _fail("oversize")
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: _fail("invalid_json"),
                          parse_float=_finite_float, parse_int=_bounded_int)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        _fail("invalid_json")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        _fail("invalid_json")
    return number


def _bounded_int(value):
    if len(value) > 64:
        _fail("invalid_json")
    return int(value)


def _read(root, relative, *, expected_identity=None, limit=MAX_BYTES):
    base = root.check()
    path = base / _relative(relative)
    _canonical(path)
    identity = _file_identity(_ordinary(path, directory=False))
    if expected_identity is not None and identity != tuple(expected_identity):
        _fail("file_identity_changed")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as source:
        if _file_identity(os.fstat(source.fileno())) != identity:
            _fail("file_identity_changed")
        data = source.read(limit + 1)
        if len(data) > limit:
            _fail("oversize")
    if _file_identity(_ordinary(path, directory=False)) != identity:
        _fail("file_identity_changed")
    root.check()
    return data, identity


@dataclass(frozen=True)
class ReopenedJournal:
    operation: OperationObservation
    observations: tuple[Observation, ...]
    revision: int
    digest: str
    file_identity: tuple
    authenticity: str = "unverified"
    trust: str = "inspect_only"
    execution_available: bool = False

    @property
    def checkpoint_coverage(self):
        return "complete" if self.revision == 8 else "incomplete"

    @property
    def unresolved_next_stage(self):
        return CHECKPOINTS[self.revision] if self.revision < 8 else "none_recorded"

    @property
    def uncertainties(self):
        last = self.observations[-1]
        values = []
        if last.checkpoint.endswith("intent") or last.checkpoint == "download_attempt":
            values.append(last.checkpoint + "_outcome_unknown")
        if last.outcome in ("unknown", "uncertain", "partial"):
            values.append(last.checkpoint + "_" + last.outcome)
        for observation in self.observations:
            values.extend(item.state + "_" + item.reason for item in observation.unresolved)
        values.append("authenticity_unverified")
        return tuple(values)


def _decode_observation(raw):
    if type(raw) is not dict or set(raw) != set(Observation.__dataclass_fields__):
        _fail("invalid_schema")
    values = dict(raw)
    for key, cls, limit in (("files", FileObservation, MAX_IMAGES),
                             ("candidates", CandidateObservation, MAX_IMAGES),
                             ("requests", RequestObservation, 100),
                             ("remote_results", RemoteResultObservation, 100),
                             ("containment", ContainmentObservation, 100),
                             ("promotions", PromotionObservation, 100),
                             ("unresolved", UnresolvedObservation, 100)):
        if type(values[key]) not in (list, tuple) or len(values[key]) > limit:
            _fail("invalid_schema")
        values[key] = tuple(_exact(item, cls) for item in values[key])
    if values["save"] is not None:
        values["save"] = _exact(values["save"], ProjectSaveObservation)
    return Observation(**values)


def reopen_journal(root, filename, *, expected_revision=None, expected_digest=None):
    """Explicit one-file read. This never recreates claim/envelope/ACK custody."""
    data, identity = _read(root, filename)
    value = _json(data)
    if type(value) is not dict or set(value) != {"schema", "version", "root_path", "root_identity", "operation", "revisions"}:
        _fail("invalid_schema")
    if value["schema"] != SCHEMA or type(value["version"]) is not int or value["version"] != 1:
        _fail("unknown_version")
    if value["root_path"] != root.path or _identity(value["root_identity"]) != root.identity:
        _fail("root_identity_changed")
    operation = _exact(value["operation"], OperationObservation)
    _validate_operation(operation)
    if filename != operation.operation_id + ".json":
        _fail("operation_identity_mismatch")
    entries = value["revisions"]
    if type(entries) is not list or not 1 <= len(entries) <= 8:
        _fail("invalid_revision")
    previous, observations, request_identities = "0" * 64, [], {}
    for index, entry in enumerate(entries):
        if type(entry) is not dict or set(entry) != {"revision", "previous_digest", "observation", "digest"}:
            _fail("invalid_schema")
        if type(entry["revision"]) is not int or entry["revision"] != index + 1 or entry["previous_digest"] != previous:
            _fail("conflicting_revision")
        obs = _decode_observation(entry["observation"])
        _validate_observation(obs, index)
        for request in obs.requests:
            correlation = (request.request_index, request.workflow_identity)
            if request.request_id in request_identities and request_identities[request.request_id] != correlation:
                _fail("request_identity_conflicting")
            request_identities[request.request_id] = correlation
        if any(c.job_id != operation.job_id or c.manifest_identity != operation.manifest_identity
               for c in obs.candidates):
            _fail("operation_identity_mismatch")
        unsigned = {k: v for k, v in entry.items() if k != "digest"}
        expected = _hash({"schema": SCHEMA, "version": 1, "operation": value["operation"], **unsigned})
        if _digest(entry["digest"]) != expected:
            _fail("digest_mismatch")
        previous = expected
        observations.append(obs)
    _validate_contract(operation, observations)
    if expected_revision is not None and (type(expected_revision) is not int or expected_revision != len(entries)):
        _fail("stale_revision")
    if expected_digest is not None and _digest(expected_digest) != previous:
        _fail("conflicting_revision")
    return ReopenedJournal(operation, tuple(observations), len(entries), previous, identity)


class OfflineJournalWriter:
    execution_available = False

    def __init__(self, root, operation, *, characterization=False, fault=lambda boundary: None):
        if characterization is not True:
            _fail("execution_unavailable")
        _validate_operation(operation)
        root.check()
        self.root, self.operation, self.fault = root, operation, fault
        self.filename = operation.operation_id + ".json"
        self._revision, self._digest, self._file_identity = 0, "0" * 64, None
        self._entries = []
        self._uncertain = False

    def append_for_characterization(self, observation):
        if self._uncertain:
            _fail("writer_uncertain")
        if self._revision == 8:
            _fail("journal_complete")
        _validate_observation(observation, self._revision)
        _validate_contract(self.operation, [*(_decode_observation(entry["observation"]) for entry in self._entries), observation])
        prior_requests = {r.request_id: (r.request_index, r.workflow_identity)
                          for entry in self._entries for r in
                          (_exact(raw, RequestObservation) for raw in entry["observation"]["requests"])}
        if any(r.request_id in prior_requests and prior_requests[r.request_id] != (r.request_index, r.workflow_identity)
               for r in observation.requests):
            _fail("request_identity_conflicting")
        if any(c.job_id != self.operation.job_id or c.manifest_identity != self.operation.manifest_identity
               for c in observation.candidates):
            _fail("operation_identity_mismatch")
        base = self.root.check()
        lock = base / (self.operation.operation_id + ".lock")
        # Exclusive same-operation writer fence. A crash leaves this marker for
        # human inspection; no stale-lock takeover or automatic recovery.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        lock_fd = os.open(lock, flags, 0o600)
        lock_identity = _file_identity(os.fstat(lock_fd))
        os.close(lock_fd)
        try:
            target = base / self.filename
            if self._revision:
                prior = reopen_journal(self.root, self.filename)
                if (prior.revision != self._revision or prior.digest != self._digest
                        or prior.file_identity != self._file_identity or prior.operation != self.operation):
                    _fail("conflicting_revision")
            elif target.exists() or target.is_symlink():
                _fail("conflicting_revision")
            unsigned = {"revision": self._revision + 1, "previous_digest": self._digest,
                        "observation": asdict(observation)}
            digest = _hash({"schema": SCHEMA, "version": 1, "operation": asdict(self.operation), **unsigned})
            entries = self._entries + [{**unsigned, "digest": digest}]
            data = _encoded({"schema": SCHEMA, "version": 1, "root_path": self.root.path, "root_identity": self.root.identity,
                             "operation": asdict(self.operation), "revisions": entries})
            if len(data) > MAX_BYTES:
                _fail("oversize")
            temp = base / (self.operation.operation_id + "." + uuid.uuid4().hex + ".tmp")
            fd = os.open(temp, flags | getattr(os, "O_BINARY", 0), 0o600)
            temp_identity = _file_identity(os.fstat(fd))
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            self.fault("before_replace")
            self.root.check()
            if _file_identity(_ordinary(temp, directory=False)) != temp_identity:
                _fail("file_identity_changed")
            # Recheck immediately before replace; supported writers obey lock.
            if self._revision:
                prior = reopen_journal(self.root, self.filename)
                if prior.file_identity != self._file_identity or prior.digest != self._digest:
                    _fail("conflicting_revision")
            elif target.exists() or target.is_symlink():
                _fail("conflicting_revision")
            os.replace(temp, target)
            self.fault("after_replace_before_ack")
            observed = reopen_journal(self.root, self.filename)
            if observed.digest != digest or observed.revision != self._revision + 1:
                _fail("conflicting_revision")
            self._entries, self._revision, self._digest = entries, observed.revision, digest
            self._file_identity = observed.file_identity
            return observed
        except BaseException:
            self._uncertain = True
            raise
        finally:
            # Only this live writer's unchanged lock is released. Temp files and
            # interrupted evidence remain; inventory never removes either.
            self.root.check()
            if _file_identity(_ordinary(lock, directory=False)) == lock_identity:
                lock.unlink()


@dataclass(frozen=True)
class InventoryResult:
    journals: tuple
    errors: tuple
    files: tuple
    orphans: tuple
    truncated: bool
    trust: str = "inspect_only"
    execution_available: bool = False


def inspect_inventory(journal_root, asset_roots=(), *, max_entries=64, max_file_bytes=32 * 1024 * 1024):
    """Direct approved-root listing only; no recursive/temp/Project discovery."""
    if type(max_entries) is not int or not 1 <= max_entries <= 64:
        _fail("invalid_budget")
    if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= 32 * 1024 * 1024:
        _fail("invalid_budget")
    roots = {root.key: root for root in asset_roots}
    if len(roots) != len(asset_roots) or len(roots) > 7:
        _fail("invalid_allowlist")
    journals, errors, files, orphans = [], [], [], []
    truncated = False
    names = []
    with os.scandir(journal_root.check()) as entries:
        for entry in entries:
            if len(names) == max_entries:
                truncated = True
                break
            names.append(entry.name)
    for name in sorted(names):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}\.json", name):
            errors.append((name, "unindexed_entry"))
            continue
        try:
            journal = reopen_journal(journal_root, name)
            if name != journal.operation.operation_id + ".json":
                _fail("operation_identity_mismatch")
            journals.append(journal)
        except (ValueError, OSError) as error:
            errors.append((name, str(error) if isinstance(error, ValueError) else "unreadable"))
    expected = {}
    for journal in journals:
        for obs in journal.observations:
            for item in obs.files:
                key = (item.root_key, item.relative_path)
                if key in expected and expected[key] != item:
                    expected[key] = None
                elif key not in expected:
                    expected[key] = item
    # One aggregate entry and byte budget, including unindexed files.
    total_bytes = 0
    for key, item in list(expected.items())[:max_entries]:
        if item is None:
            files.append((*key, "conflicting"))
            continue
        if key[0] not in roots:
            files.append((*key, "unapproved_root"))
            continue
        if roots[key[0]].path != item.root_path or roots[key[0]].identity != tuple(item.root_identity):
            files.append((*key, "root_identity_changed"))
            continue
        try:
            if total_bytes + item.byte_count > max_file_bytes:
                _fail("budget_exceeded")
            total_bytes += item.byte_count
            data, _ = _read(roots[key[0]], key[1], expected_identity=item.file_identity,
                            limit=min(item.byte_count, max_file_bytes))
            status = "exact" if len(data) == item.byte_count and hashlib.sha256(data).hexdigest() == item.content_sha256 else "tampered"
            if status == "exact":
                extension = next(k for k, v in SUPPORTED_EXTENSIONS.items() if v == item.image_format)
                try:
                    decoded = ContainedOutputStore._verify(SimpleNamespace(_limits=ContainmentLimits()),
                                                          io.BytesIO(data), extension)
                    if decoded != (item.image_format, item.width, item.height):
                        status = "image_metadata_conflicting"
                except _ContainmentFailure:
                    status = "image_invalid"
            files.append((*key, status))
        except FileNotFoundError:
            files.append((*key, "missing"))
        except (ValueError, OSError) as error:
            files.append((*key, str(error) if isinstance(error, ValueError) else "unreadable"))
    if len(expected) > max_entries:
        truncated = True
    count = 0
    for root in asset_roots:
        try:
            with os.scandir(root.check()) as entries:
                for entry in entries:
                    if count == max_entries:
                        truncated = True
                        break
                    count += 1
                    if (root.key, entry.name) not in expected:
                        orphans.append((root.key, entry.name, "unverified"))
        except (ValueError, OSError):
            errors.append((root.key, "root_unreadable_or_changed"))
    return InventoryResult(tuple(journals), tuple(errors), tuple(files), tuple(orphans), truncated)


@dataclass(frozen=True)
class ReconciliationResult:
    state: str
    matched: int = 0
    expected: int = 0
    save_observation: str = "unknown"
    trust: str = "inspect_only"
    attachment_allowed: bool = False
    execution_available: bool = False


def reconcile_selected_project(journal, selected_root, selected_relative_path, asset_roots=()):
    """Read original selected JSON directly, without serializer/model mutation."""
    op = journal.operation
    final = journal.observations[-1]
    save = final.outcome if final.checkpoint == "save_observed" else "unknown"
    candidates = tuple(c for obs in journal.observations for c in obs.candidates)
    def result(state, matched=0):
        return ReconciliationResult(state, matched, len(candidates), save)
    if (selected_root.key != op.project_root_key or selected_relative_path != op.project_relative_path
            or selected_root.path != op.project_root_path
            or selected_root.identity != tuple(op.project_root_identity)):
        return result("conflicting")
    try:
        data, _ = _read(selected_root, selected_relative_path)
        # Atomic saving changes inode. Compare captured identity only before any
        # save intent; after it, JSON content is observed with explicit uncertainty.
        if not any(o.checkpoint == "save_intent" for o in journal.observations):
            _, identity = _read(selected_root, selected_relative_path, expected_identity=op.project_file_identity)
        value = _json(data)
    except FileNotFoundError:
        return result("missing")
    except OSError:
        return result("unreadable")
    except ValueError:
        return result("uncertain")
    if type(value) is not dict or type(value.get("prompt_lines")) is not list:
        return result("uncertain")
    if not candidates:
        return result("uncertain")
    keys = [(c.job_id, c.request_id, c.output_index) for c in candidates]
    if len(set(keys)) != len(keys):
        return result("uncertain")
    roots = {r.key: r for r in asset_roots}
    matched, conflict = 0, False
    for candidate in candidates:
        root = roots.get(candidate.asset_root_key)
        if root is None:
            return result("uncertain", matched)
        try:
            expected_path = root.check() / _relative(candidate.asset_relative_path)
        except (ValueError, OSError):
            return result("uncertain", matched)
        related = []
        for line in value["prompt_lines"]:
            if type(line) is not dict or type(line.get("generated_candidates", [])) is not list:
                return result("uncertain", matched)
            for record in line.get("generated_candidates", []):
                if type(record) is not dict:
                    return result("uncertain", matched)
                provenance = record.get("generation_provenance")
                if type(provenance) is dict and provenance.get("job_id") == candidate.job_id and provenance.get("request_id") == candidate.request_id and provenance.get("output_index") == candidate.output_index:
                    related.append((line, record, provenance))
        if not related:
            continue
        if len(related) != 1:
            conflict = True
            continue
        line, record, provenance = related[0]
        expected_provenance = {k: v for k, v in asdict(candidate).items()
                               if k not in ("claim_id", "asset_root_key", "asset_relative_path")}
        path_value = record.get("path")
        try:
            if type(path_value) is not str or not path_value:
                _fail("invalid_path")
            path = Path(path_value)
            if not path.is_absolute():
                _relative(path_value)
                path = selected_root.check() / Path(selected_relative_path).parent / path
            _observed_absolute(str(path))
            exact = (path == expected_path and str(line.get("id")) == candidate.illustration_id
                     and all(type(provenance.get(k)) is type(v) and provenance.get(k) == v for k, v in expected_provenance.items()))
        except (ValueError, OSError):
            exact = False
        if exact:
            matched += 1
        else:
            conflict = True
    state = "conflicting" if conflict else "exact" if matched == len(candidates) else "partial" if matched else "absent"
    return result(state, matched)
