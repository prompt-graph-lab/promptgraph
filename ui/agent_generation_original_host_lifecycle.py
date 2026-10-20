"""Non-executing original-host binding for a future Agent Generation owner.

This private owner tracks one exact ProjectAgentSessionRuntime target. It does
not start a worker, perform transport/protected I/O, or grant Start,
publication, save, Recovery, or cleanup authority.

Lock order for host snapshots is runtime publication gate -> route registry
snapshot -> GenerationJobRegistry -> GenerationExecutorInbox -> this owner's
short lock. Readiness/correlation observations additionally retain the exact
route operation lock while comparing the live registration/pairing snapshot
and taking this owner's short lock. The registry-wide lock is held only across
that bounded local observation. This owner never acquires any external owner
lock. Observation callbacks are outside all locks; revocation only marks the
binding and never closes resources.
"""

from collections import deque
from dataclasses import dataclass, field
import re
import threading
import uuid
import weakref


_FACTORY = object()
_TOKEN = re.compile(r"[0-9a-f]{32}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TEXT = 256
_MAX_REQUESTS = 100
_MAX_EVENTS = 1024
_MAX_OBSERVATIONS = 16
_WORKER_EVENT_KINDS = frozenset({
    "submission_started", "submitted", "execution_progress", "execution_timeout",
    "remote_outputs_ready", "outputs_ready", "failed", "submission_unknown",
})
_PURPOSES = (
    "private_journal", "temporary_containment", "retained_uncertain",
    "promoted_assets", "selected_project_json",
)
_PROFILE_A_WRITABLE_PURPOSES = _PURPOSES[:-1]


@dataclass(frozen=True)
class GenerationWorkerCorrelation:
    """Correlation-only scalars; never a worker capability or owner reference."""

    status: str
    lifecycle_generation: str | None = field(default=None, repr=False)
    job_id: str | None = field(default=None, repr=False)
    claim_id: str | None = field(default=None, repr=False)
    manifest_identity: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class GenerationWorkerResultObservation:
    """Untrusted, bounded worker-reported correlation retained as non-authority."""

    lifecycle_generation: str = field(repr=False)
    job_id: str = field(repr=False)
    claim_id: str = field(repr=False)
    manifest_identity: str | None = field(default=None, repr=False)
    request_index: int = 0
    sequence: int = 0
    kind: str = ""


@dataclass(frozen=True)
class _HostEvidence:
    runtime: object = field(repr=False)
    project: object = field(repr=False)
    project_path: str = field(repr=False)
    target_epoch: str = field(repr=False)
    activation_id: str = field(repr=False)
    registry: object = field(repr=False)
    registration: object = field(repr=False)
    route_id: str = field(repr=False)
    process_incarnation: str = field(repr=False)
    session_incarnation: str = field(repr=False)
    job_process_incarnation: str = field(repr=False)
    jobs: object = field(repr=False)
    inbox: object = field(repr=False)
    pairing_generation: int | None = field(repr=False)
    job: object = field(default=None, repr=False)
    envelope: object = field(default=None, repr=False)
    job_id: str | None = field(default=None, repr=False)
    claim_id: str | None = field(default=None, repr=False)
    manifest_identity: str | None = field(default=None, repr=False)
    request_count: int = 0


def _safe_token(value):
    return type(value) is str and _TOKEN.fullmatch(value) is not None


def _safe_digest(value):
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _valid_evidence(evidence):
    if type(evidence) is not _HostEvidence:
        return False
    if (evidence.project is None or type(evidence.project_path) is not str
            or len(evidence.project_path) > 4096
            or not _safe_token(evidence.target_epoch)
            or not _safe_token(evidence.activation_id)
            or type(evidence.route_id) is not str
            or not evidence.route_id.isascii()
            or not 1 <= len(evidence.route_id) <= _MAX_TEXT
            or type(evidence.process_incarnation) is not str
            or not evidence.process_incarnation.isascii()
            or not 1 <= len(evidence.process_incarnation) <= _MAX_TEXT
            or not _safe_token(evidence.session_incarnation)
            or not _safe_token(evidence.job_process_incarnation)
            or (evidence.pairing_generation is not None
                and (type(evidence.pairing_generation) is not int
                     or not 1 <= evidence.pairing_generation <= 2**63 - 1))
            or (evidence.job_id is not None and not _safe_token(evidence.job_id))
            or (evidence.claim_id is not None and not _safe_token(evidence.claim_id))
            or (evidence.manifest_identity is not None
                and not _safe_digest(evidence.manifest_identity))
            or type(evidence.request_count) is not int
            or not 0 <= evidence.request_count <= _MAX_REQUESTS):
        return False
    try:
        weakref.ref(evidence.project)
        weakref.ref(evidence.runtime)
    except TypeError:
        return False

    if evidence.envelope is None:
        return (
            evidence.job is None and evidence.job_id is None
            and evidence.claim_id is None and evidence.manifest_identity is None
            and evidence.request_count == 0
        )

    from ui.agent_generation_executor_inbox import ExecutionEnvelope
    if type(evidence.envelope) is not ExecutionEnvelope or evidence.job is None:
        return False
    envelope = evidence.envelope
    binding = envelope.binding
    manifest = envelope.manifest
    return (
        evidence.job_id == envelope.job_id
        and evidence.claim_id == envelope.claim_id
        and evidence.manifest_identity == manifest.manifest_identity
        and evidence.request_count == len(manifest.requests)
        and binding.session_id == evidence.session_incarnation
        and binding.process_incarnation == evidence.job_process_incarnation
        and binding.target_epoch == evidence.target_epoch
        and binding.activation_id == evidence.activation_id
        and binding.pairing_generation == evidence.pairing_generation
        and evidence.job.job_id == evidence.job_id
        and evidence.job.claim_id == evidence.claim_id
        and evidence.job.binding == binding
    )


def _empty_dependencies():
    return {
        "purpose_roots": {purpose: "absent" for purpose in _PURPOSES},
        "capacity_owner": "absent",
        "root_capacity_identity": "not_checked",
        "asset_writer": "absent",
        "journal_writer": "absent",
        "promotion_writer": "absent",
        "native_acl_or_identity_revalidated": False,
    }


def unavailable_readiness(reason="host_evidence_unavailable"):
    safe_reason = reason if reason in {
        "no_active_project", "route_unavailable", "runtime_closed",
        "lifecycle_not_opted_in", "host_evidence_unavailable",
    } else "host_evidence_unavailable"
    state = {
        "no_active_project": "unbound",
        "lifecycle_not_opted_in": "unbound",
        "runtime_closed": "closed",
    }.get(safe_reason, "uncertain")
    return {
        "lifecycle_state": state,
        "binding": "unavailable",
        "selected_project": "unavailable",
        "project_path": "unavailable",
        "target_epoch": "unavailable",
        "activation": "unavailable",
        "process_session": "unavailable",
        "route": "unavailable",
        "pairing": "unavailable",
        "job_claim": "unavailable",
        "profile_a_storage": "unbound",
        "worker_results": "correlation_only_non_authoritative",
        "reason": safe_reason,
        "protected_dependencies": _empty_dependencies(),
        "execution_available": False,
        "protected_storage_available": False,
        "promotion_available": False,
        "candidate_publication_allowed": False,
        "project_save_allowed": False,
        "recovery_execution_allowed": False,
        "human_start_allowed": False,
        "cleanup_allowed": False,
        "authorship": "unverified",
    }


class OriginalHostGenerationLifecycle:
    """One exact host binding whose lifecycle is permanently non-executing."""

    execution_available = False
    protected_storage_available = False
    promotion_available = False
    candidate_publication_allowed = False
    project_save_allowed = False
    recovery_execution_allowed = False
    human_start_allowed = False
    cleanup_allowed = False
    authorship = "unverified"

    def __init__(self, evidence, *, _factory=None):
        if _factory is not _FACTORY or not _valid_evidence(evidence):
            raise ValueError("original_host_evidence_required")
        self._runtime_ref = weakref.ref(evidence.runtime)
        self._project_ref = weakref.ref(evidence.project)
        self._project_path = evidence.project_path
        self._target_epoch = evidence.target_epoch
        self._activation_id = evidence.activation_id
        self._registry = evidence.registry
        self._registration = evidence.registration
        self._route_id = evidence.route_id
        self._process_incarnation = evidence.process_incarnation
        self._session_incarnation = evidence.session_incarnation
        self._job_process_incarnation = evidence.job_process_incarnation
        self._jobs = evidence.jobs
        self._inbox = evidence.inbox
        self._pairing_generation = evidence.pairing_generation
        self._job = evidence.job
        self._envelope = evidence.envelope
        self._job_id = evidence.job_id
        self._claim_id = evidence.claim_id
        self._manifest_identity = evidence.manifest_identity
        self._request_count = evidence.request_count
        self._generation = uuid.uuid4().hex
        self._state = "bound_non_executing"
        self._reason = None
        self._lock = threading.Lock()
        self._active_observations = 0
        self._close_requested = False
        self._worker_observations = deque(maxlen=_MAX_OBSERVATIONS)
        self._dependencies = _empty_dependencies()
        self._protected_refs = None
        self._profile_a_storage_binding = None
        self._worker_storage_integration = None

    @classmethod
    def _create_for_runtime(cls, runtime, evidence):
        """Construct only for the exact existing runtime and its current owners."""
        from ui.project_agent_session_pump import ProjectAgentSessionRuntime
        from ui.agent_generation_job import _PROCESS_INCARNATION

        if (type(runtime) is not ProjectAgentSessionRuntime
                or type(evidence) is not _HostEvidence
                or evidence.runtime is not runtime
                or runtime._closed
                or runtime._generation_original_host_lifecycle is not None
                or runtime._registry is not evidence.registry
                or runtime._registration is not evidence.registration
                or runtime.generation_jobs is not evidence.jobs
                or runtime._generation_executor_inbox is not evidence.inbox
                or evidence.registration._registry is not evidence.registry
                or evidence.registration.route_id != evidence.route_id
                or evidence.registry.process_incarnation != evidence.process_incarnation
                or evidence.jobs._session_incarnation != evidence.session_incarnation
                or evidence.job_process_incarnation != _PROCESS_INCARNATION):
            raise ValueError("original_runtime_binding_required")
        try:
            available, pairing_generation = evidence.registration.inspect_pairing_generation()
        except Exception as exc:
            raise ValueError("original_runtime_binding_required") from exc
        if available is not True or pairing_generation != evidence.pairing_generation:
            raise ValueError("original_runtime_binding_required")
        with evidence.jobs._lock:
            if (evidence.jobs._closed
                    or evidence.jobs._target != (evidence.target_epoch, evidence.activation_id)
                    or evidence.jobs._session_incarnation != evidence.session_incarnation):
                raise ValueError("original_runtime_binding_required")
            with evidence.inbox._lock:
                if (evidence.inbox._closed
                        or evidence.inbox._state == "invalidated"
                        or evidence.inbox._envelope is not evidence.envelope
                        or (evidence.envelope is not None
                            and evidence.inbox._state not in {"offered", "accepted", "unknown"})):
                    raise ValueError("original_runtime_binding_required")
                if evidence.envelope is not None:
                    job = evidence.jobs._authorized_locked(
                        evidence.envelope.job_id, evidence.envelope.claim_id,
                    )
                    if job is not evidence.job:
                        raise ValueError("original_runtime_binding_required")
        return cls(evidence, _factory=_FACTORY)

    def _same_host_locked(self, evidence):
        project = self._project_ref()
        return (
            self._state == "bound_non_executing"
            and self._runtime_ref() is evidence.runtime
            and project is not None and project is evidence.project
            and self._project_path == evidence.project_path
            and self._target_epoch == evidence.target_epoch
            and self._activation_id == evidence.activation_id
            and self._registry is evidence.registry
            and self._registration is evidence.registration
            and self._route_id == evidence.route_id
            and self._process_incarnation == evidence.process_incarnation
            and self._session_incarnation == evidence.session_incarnation
            and self._job_process_incarnation == evidence.job_process_incarnation
            and self._jobs is evidence.jobs
            and self._inbox is evidence.inbox
            and self._pairing_generation == evidence.pairing_generation
        )

    def _replacement_reason(self, evidence):
        with self._lock:
            project = self._project_ref()
            if (project is not evidence.project
                    or self._project_path != evidence.project_path
                    or self._target_epoch != evidence.target_epoch
                    or self._activation_id != evidence.activation_id):
                return "target_replaced"
            if (self._registry is not evidence.registry
                    or self._registration is not evidence.registration
                    or self._route_id != evidence.route_id
                    or self._process_incarnation != evidence.process_incarnation
                    or self._session_incarnation != evidence.session_incarnation
                    or self._job_process_incarnation != evidence.job_process_incarnation
                    or self._jobs is not evidence.jobs
                    or self._inbox is not evidence.inbox):
                return "route_replaced"
            if self._pairing_generation != evidence.pairing_generation:
                return "pairing_replaced"
            same_claim_scalars = (
                self._job_id == evidence.job_id
                and self._claim_id == evidence.claim_id
                and self._manifest_identity == evidence.manifest_identity
                and self._request_count == evidence.request_count
            )
            same_claim_objects = self._job is evidence.job and self._envelope is evidence.envelope
            if (self._state != "bound_non_executing" and same_claim_scalars) or (
                    self._state == "bound_non_executing"
                    and same_claim_scalars and same_claim_objects):
                return "terminal_same_binding"
            return "job_claim_replaced"

    def _route_snapshot_mismatch(
        self, *, registry, registration, process_incarnation, pairing_generation,
    ):
        """Compare the exact live route snapshot while its operation lock is held."""
        with self._lock:
            if self._state != "bound_non_executing":
                return None
            if (self._runtime_ref() is None
                    or self._registry is not registry
                    or self._registration is not registration
                    or self._route_id != getattr(registration, "route_id", None)
                    or self._process_incarnation != process_incarnation):
                return "route_replaced"
            if self._pairing_generation != pairing_generation:
                return "pairing_replaced"
            return None

    def _reconcile_evidence(self, evidence):
        """Refresh only first-issued job/claim facts for an unchanged host."""
        if not _valid_evidence(evidence):
            return False
        with self._lock:
            if not self._same_host_locked(evidence):
                return False

            if self._job_id is None:
                next_values = (
                    evidence.job, evidence.envelope, evidence.job_id, evidence.claim_id,
                    evidence.manifest_identity, evidence.request_count,
                )
            else:
                if (evidence.job is not self._job
                        or evidence.envelope is not self._envelope
                        or evidence.job_id != self._job_id
                        or evidence.claim_id != self._claim_id
                        or evidence.manifest_identity != self._manifest_identity
                        or evidence.request_count != self._request_count):
                    return False
                next_values = (
                    self._job, self._envelope, self._job_id, self._claim_id,
                    self._manifest_identity, self._request_count,
                )
            (self._job, self._envelope, self._job_id, self._claim_id,
             self._manifest_identity, self._request_count) = next_values
            return True

    def _release_live_references_locked(self):
        if self._active_observations:
            return
        # Keep only weak Project/runtime identity and opaque host-owner
        # references needed to prevent terminal same-binding resurrection.
        # Drop the 19A manifest and readiness-only root references; a 19B
        # integration independently retains roots pinned by an active or
        # uncertain Worker operation. Nothing is closed here.
        self._job = self._envelope = None
        self._protected_refs = None
        self._profile_a_storage_binding = None

    def _retire_for_replacement(self, reason):
        """End this generation without waiting for an observation callback."""
        with self._lock:
            if self._state in {"closed", "uncertain"}:
                state = self._state
            else:
                self._reason = reason if reason in {
                    "target_replaced", "route_replaced", "pairing_replaced",
                    "job_claim_replaced", "host_evidence_unavailable",
                } else "host_evidence_unavailable"
                self._close_requested = True
                self._state = "revocation_requested"
                if self._active_observations == 0:
                    self._state = "closed"
                    self._release_live_references_locked()
                state = self._state
            integration = self._worker_storage_integration
            integration_reason = self._reason or reason
        if integration is not None:
            integration.revoke(integration_reason)
        return state

    def close(self):
        """Publish revocation immediately; never wait under the owner lock."""
        with self._lock:
            if self._state not in {"closed", "uncertain"}:
                self._close_requested = True
                self._reason = "session_closed"
                if self._state == "bound_non_executing":
                    self._state = "revocation_requested"
                if self._active_observations == 0:
                    self._state = "closed"
                    self._release_live_references_locked()
            state = "close_pending" if self._active_observations else self._state
            integration = self._worker_storage_integration
        if integration is not None:
            integration.revoke("session_closed")
        return state

    def _observe_non_io_callback_for_characterization(self, callback):
        """Private deterministic seam proving callback lock/revocation behavior.

        Callback values are discarded. This method cannot execute or authorize
        transport, filesystem work, publication or Project mutation.
        """
        if not callable(callback):
            return "invalid_observation"
        with self._lock:
            if self._state != "bound_non_executing":
                return "unavailable"
            self._active_observations += 1
        failed = False
        try:
            callback()
        except Exception:
            failed = True
        finally:
            with self._lock:
                self._active_observations -= 1
                if failed and self._state == "bound_non_executing":
                    self._state = "uncertain"
                    self._reason = "host_evidence_unavailable"
                    self._close_requested = True
                if self._active_observations == 0 and self._close_requested:
                    if self._state == "revocation_requested":
                        self._state = "closed"
                    self._release_live_references_locked()
                outcome = (
                    "observed_non_authoritative"
                    if self._state == "bound_non_executing"
                    else "revoked_non_authoritative"
                )
                integration = self._worker_storage_integration if failed else None
            if integration is not None:
                integration.revoke("host_evidence_unavailable")
        return outcome

    def worker_correlation_for_characterization(self):
        """Return bounded correlation only; not a worker task or capability."""
        with self._lock:
            if self._state != "bound_non_executing":
                return GenerationWorkerCorrelation("lifecycle_unavailable")
            if self._job_id is None or self._claim_id is None:
                return GenerationWorkerCorrelation("claim_not_issued")
            return GenerationWorkerCorrelation(
                "correlation_only", self._generation, self._job_id, self._claim_id,
                self._manifest_identity,
            )

    def observe_worker_result_for_characterization(self, observation):
        """Retain one bounded worker observation without changing host state."""
        if (type(observation) is not GenerationWorkerResultObservation
                or not _safe_token(observation.lifecycle_generation)
                or not _safe_token(observation.job_id)
                or not _safe_token(observation.claim_id)
                or (observation.manifest_identity is not None
                    and not _safe_digest(observation.manifest_identity))
                or type(observation.request_index) is not int
                or not 0 <= observation.request_index < _MAX_REQUESTS
                or type(observation.sequence) is not int
                or not 1 <= observation.sequence <= _MAX_EVENTS
                or type(observation.kind) is not str
                or observation.kind not in _WORKER_EVENT_KINDS):
            return "invalid_observation"
        with self._lock:
            current = (
                self._state == "bound_non_executing"
                and observation.lifecycle_generation == self._generation
                and observation.job_id == self._job_id
                and observation.claim_id == self._claim_id
                and observation.manifest_identity == self._manifest_identity
                and self._request_count > observation.request_index
            )
            self._worker_observations.append(observation)
            return "observed_non_authoritative" if current else "stale_non_authoritative"

    def observe_protected_references_for_characterization(self, purpose_roots, capacity_owner):
        """Compare exact supplied owner references only; perform no filesystem I/O."""
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_storage import WindowsProtectedRootCharacterization

        statuses = _empty_dependencies()
        supplied_roots = purpose_roots is not None
        supplied_capacity = capacity_owner is not None
        roots_valid_shape = type(purpose_roots) is dict and set(purpose_roots) == set(_PURPOSES)
        capacity_valid_type = type(capacity_owner) is WindowsProtectedStorageAdmissionCharacterization
        if supplied_roots and not roots_valid_shape:
            statuses["purpose_roots"] = {purpose: "mismatched" for purpose in _PURPOSES}
        elif roots_valid_shape:
            for purpose in _PURPOSES:
                root = purpose_roots[purpose]
                statuses["purpose_roots"][purpose] = (
                    "supplied_reference_only"
                    if (type(root) is WindowsProtectedRootCharacterization
                        and root._purpose == purpose and root._closed is False)
                    else "mismatched"
                )
        if supplied_capacity:
            statuses["capacity_owner"] = (
                "supplied_reference_only"
                if (capacity_valid_type and capacity_owner._closed is False
                    and capacity_owner._invalid is False)
                else "mismatched"
            )
        all_root_refs_valid = roots_valid_shape and all(
            statuses["purpose_roots"][purpose] == "supplied_reference_only"
            for purpose in _PURPOSES
        )
        if not supplied_roots and not supplied_capacity:
            identity_status = "not_checked"
        elif not all_root_refs_valid or not capacity_valid_type:
            identity_status = "mismatched"
        else:
            owner_roots = getattr(capacity_owner, "_roots", None)
            identity_status = (
                "matched_reference_only"
                if type(owner_roots) is dict
                and set(owner_roots) == set(_PURPOSES)
                and all(owner_roots[purpose] is purpose_roots[purpose] for purpose in _PURPOSES)
                else "mismatched"
            )
        statuses["root_capacity_identity"] = identity_status
        if identity_status == "mismatched":
            for purpose in _PURPOSES:
                if statuses["purpose_roots"][purpose] == "supplied_reference_only":
                    statuses["purpose_roots"][purpose] = "mismatched"
            if statuses["capacity_owner"] == "supplied_reference_only":
                statuses["capacity_owner"] = "mismatched"
        with self._lock:
            if self._state != "bound_non_executing":
                return "lifecycle_unavailable"
            self._dependencies = statuses
            self._protected_refs = (
                (dict(purpose_roots), capacity_owner)
                if identity_status == "matched_reference_only" else None
            )
        return identity_status

    def observe_profile_a_storage_binding_for_characterization(
            self, capacity_owner, project_reference):
        """Bind exact four-root storage and a separate read-only Project identity.

        The caller must already have performed native readiness observations
        outside runtime/lifecycle locks and must recheck the exact current host
        target before calling this publication method.
        """
        from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
        from core.generation_windows_protected_storage import WindowsProjectJsonReferenceCharacterization
        from ui.project_agent_session_mailbox import _normalize_target_path

        if (type(capacity_owner) is not WindowsProtectedStorageAdmissionCharacterization
                or capacity_owner._profile_a_root_set is not True
                or type(capacity_owner._roots) is not dict
                or set(capacity_owner._roots) != set(_PROFILE_A_WRITABLE_PURPOSES)
                or capacity_owner._closed is not False or capacity_owner._invalid is not False
                or capacity_owner._scope_lease is None
                or capacity_owner._scope_lease._state != "held"
                or type(project_reference) is not WindowsProjectJsonReferenceCharacterization
                or project_reference._closed is not False):
            return "binding_invalid"
        project = self._project_ref()
        if (project is None or not self._project_path
                or _normalize_target_path(str(project_reference._path))
                != _normalize_target_path(self._project_path)):
            return "project_reference_mismatch"
        with self._lock:
            if self._state != "bound_non_executing":
                return "lifecycle_unavailable"
            existing = self._profile_a_storage_binding
            requested = (capacity_owner, project_reference)
            if existing is not None:
                return "matched_reference_only" if (
                    existing[0] is capacity_owner and existing[1] is project_reference
                ) else "binding_conflict"
            self._profile_a_storage_binding = requested
        return "matched_reference_only"

    def readiness(self):
        with self._lock:
            became_uncertain = False
            state = self._state
            if (state == "bound_non_executing"
                    and (self._runtime_ref() is None or self._project_ref() is None)):
                self._state = state = "uncertain"
                self._reason = "host_evidence_unavailable"
                self._close_requested = True
                self._release_live_references_locked()
                became_uncertain = True
            integration = self._worker_storage_integration if became_uncertain else None
            reason = self._reason
            dependencies = {
                **self._dependencies,
                "purpose_roots": dict(self._dependencies["purpose_roots"]),
            }
            job_state = ("not_issued" if self._job_id is None else
                         "claim_not_issued" if self._claim_id is None else "bound")
            pairing_state = ("unpaired" if self._pairing_generation is None else "paired")
            profile_a_storage = (
                "bound_reference_only" if self._profile_a_storage_binding is not None
                and state == "bound_non_executing" else "unbound"
            )
        if integration is not None:
            integration.revoke("host_evidence_unavailable")
        available = state == "bound_non_executing"
        return {
            "lifecycle_state": state,
            "binding": "exact_host_observation" if available else "unavailable",
            "selected_project": "bound" if available else "unavailable",
            "project_path": "bound" if available and self._project_path else "missing_or_unavailable",
            "target_epoch": "bound" if available else "unavailable",
            "activation": "bound" if available else "unavailable",
            "process_session": "bound" if available else "unavailable",
            "route": "bound" if available else "unavailable",
            "pairing": pairing_state if available else "unavailable",
            "job_claim": job_state if available else "unavailable",
            "worker_results": "correlation_only_non_authoritative",
            "profile_a_storage": profile_a_storage,
            "reason": reason,
            "protected_dependencies": dependencies,
            "execution_available": False,
            "protected_storage_available": False,
            "promotion_available": False,
            "candidate_publication_allowed": False,
            "project_save_allowed": False,
            "recovery_execution_allowed": False,
            "human_start_allowed": False,
            "cleanup_allowed": False,
            "authorship": "unverified",
        }
