"""C2B-6 original-host characterization. No production call site or Start.

Existing Gallery ingestion is the sole router. Host supplies its existing app
factory/appender and exact-object/path save callback. Files, factory work and
JSON persistence run outside job/inbox locks; disk I/O also releases host gates.
"""
from contextlib import contextmanager, nullcontext
import copy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import threading
from types import FunctionType

from core.candidate_record_normalization import _normalize_candidate_records
from core.gallery_generation import ingest_gallery_generation_outputs, resolve_gallery_generation_result_target
from core.generation_output_promotion import DurableGenerationAssets
from core.io import (
    _project_to_serializable_data, load_project_from_json, resolve_project_asset_path,
)
from ui.agent_generation_executor_inbox import ExecutionEnvelope, ExecutorEvent, OutputReceipt
from ui.agent_generation_executor_handoff import GenerationPublicationOrigin
from ui.agent_generation_job import JobRequest, WorkerEvent, _PROCESS_INCARNATION
from ui.project_agent_session_pump import ProjectAgentSessionRuntime
from ui.agent_generation_protected_candidate_admission import (
    GenerationProtectedCandidateAdmission,
    ProtectedCandidateAdmissionObservation,
)


@dataclass(frozen=True)
class PublicationReceipt:
    request_index: int
    promotion_state: str
    registration_state: str
    registered_count: int = 0


@dataclass(frozen=True)
class _ProfileAHostGalleryCallbacks:
    """Current app-run references captured from the executing host wrapper."""

    runtime: object
    state: object
    app_namespace: object
    app_entrypoint: object
    app_entrypoint_name: str
    candidate_factory: object
    candidate_appender: object
    save_project: object


def _profile_a_host_gallery_callbacks_for_current_app_run(runtime, state):
    """Capture callbacks only from the actual Gallery wrapper on the call stack.

    The callback values are read from the globals of the executing app.py
    entrypoint, never from caller-supplied arguments or an issuer API that can
    stamp arbitrary callables. Direct characterization callers therefore
    cannot manufacture an app callback binding.
    """
    return _profile_a_host_callbacks_for_current_app_run(
        runtime, state, "publish_profile_a_generation_candidates_for_characterization",
        app_frame=sys._getframe(2),
    )


def _profile_a_host_project_save_callbacks_for_current_app_run(runtime, state):
    """Capture the existing app Project writer from its fixed save wrapper."""
    return _profile_a_host_callbacks_for_current_app_run(
        runtime, state, "save_profile_a_generation_project_for_characterization",
        app_frame=sys._getframe(2),
    )


def _profile_a_host_callbacks_for_current_app_run(
        runtime, state, app_entrypoint_name, *, app_frame=None):
    """Capture app-owned callbacks only from an exact fixed app.py frame."""
    try:
        if (type(runtime) is not ProjectAgentSessionRuntime or state is None
                or app_entrypoint_name not in {
                    "publish_profile_a_generation_candidates_for_characterization",
                    "save_profile_a_generation_project_for_characterization",
                }):
            return None
        # The thin route helper captures its caller before delegating here.
        # This prevents a changed helper stack from mistaking runtime code or
        # a same-named test function for the actual app entrypoint.
        if app_frame is None:
            return None
        expected_app_path = (Path(__file__).resolve().parents[1] / "app.py")
        expected_app_path = os.path.normcase(os.path.realpath(expected_app_path))
        if os.path.normcase(os.path.realpath(app_frame.f_code.co_filename)) != expected_app_path:
            return None
        namespace = app_frame.f_globals
        entrypoint = namespace.get(app_entrypoint_name)
        if (type(entrypoint) is not FunctionType
                or entrypoint.__code__ is not app_frame.f_code
                or entrypoint.__globals__ is not namespace):
            return None
        names = (
            "_make_generated_candidate_record",
            "_append_line_generated_candidates",
            "save_agent_scene_module_swap_project",
        )
        callbacks = tuple(namespace.get(name) for name in names)
        if any(
                type(callback) is not FunctionType
                or callback.__globals__ is not namespace
                or os.path.normcase(os.path.realpath(callback.__code__.co_filename))
                    != expected_app_path
                for callback in callbacks):
            return None
        binding = _ProfileAHostGalleryCallbacks(
            runtime, state, namespace, entrypoint, app_entrypoint_name, *callbacks,
        )
        # Publish this per-run identity under the runtime gate. A later host
        # change/close clears it; reuse accepts only this exact object.
        with runtime._publication_gate:
            if runtime._closed or runtime._generation_host_state is not state:
                return None
            runtime._generation_profile_a_host_callback_binding = binding
        return binding
    except Exception:
        return None
    finally:
        app_frame = None


def _profile_a_host_gallery_callbacks_are_valid(callbacks, runtime, state):
    namespace = getattr(callbacks, "app_namespace", None)
    entrypoint = getattr(callbacks, "app_entrypoint", None)
    return bool(
        type(callbacks) is _ProfileAHostGalleryCallbacks
        and callbacks is getattr(runtime, "_generation_profile_a_host_callback_binding", None)
        and callbacks.runtime is runtime
        and callbacks.state is state
        and runtime._generation_host_state is state
        and type(namespace) is dict
        and type(entrypoint) is FunctionType
        and namespace.get(callbacks.app_entrypoint_name) is entrypoint
        and all(callable(callback) for callback in
                (callbacks.candidate_factory, callbacks.candidate_appender,
                 callbacks.save_project))
        and namespace.get("_make_generated_candidate_record") is callbacks.candidate_factory
        and namespace.get("_append_line_generated_candidates") is callbacks.candidate_appender
        and namespace.get("save_agent_scene_module_swap_project") is callbacks.save_project
    )


@dataclass(frozen=True)
class _ProtectedSettledEventEvidence:
    """Exact accepted output events retained after bounded logs evict them."""

    request_index: int
    remote_event: ExecutorEvent
    outputs_ready_event: ExecutorEvent


class GenerationCandidatePublication:
    execution_available = False

    @classmethod
    def create_for_characterization(cls, state, runtime, envelope, *, approved_directory,
                                    candidate_factory, candidate_appender, save_project,
                                    characterization=False):
        return cls._create_for_characterization(
            state, runtime, envelope, approved_directory=approved_directory,
            candidate_factory=candidate_factory, candidate_appender=candidate_appender,
            save_project=save_project, characterization=characterization, protected_only=False)

    @classmethod
    def create_protected_for_characterization(cls, state, runtime, envelope, *, approved_directory,
                                              candidate_factory, candidate_appender, save_project,
                                              characterization=False):
        """Create the same single writer without allocating legacy asset custody."""
        return cls._create_for_characterization(
            state, runtime, envelope, approved_directory=approved_directory,
            candidate_factory=candidate_factory, candidate_appender=candidate_appender,
            save_project=save_project, characterization=characterization, protected_only=True)

    @classmethod
    def create_profile_a_protected_for_characterization(
            cls, state, runtime, envelope, admission_owner, admission_result, *,
            callback_bundle,
            characterization=False, disposable_opt_in=False):
        """Create the single Gallery writer under exact Profile A root custody.

        Profile A's app-private promoted root is authorized by its original
        four-root owner and held scope lease. It is not authorized by the
        unrelated ComfyUI output_directory and this path never relaxes the
        legacy/protected output-directory constructor.
        """
        from core.generation_storage_admission import (
            WindowsProtectedStorageAdmissionCharacterization,
        )
        from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization
        from ui.agent_generation_original_host_lifecycle import OriginalHostGenerationLifecycle
        from ui.agent_generation_original_host_worker_storage import OriginalHostWorkerStorageIntegration
        from ui.agent_generation_protected_candidate_admission import (
            GenerationProtectedCandidateAdmission,
            ProtectedCandidateAdmissionObservation,
            ProtectedCandidateAdmissionResult,
        )

        if characterization is not True or disposable_opt_in is not True:
            raise ValueError("execution_unavailable")
        if (state is None or not callable(getattr(state, "get", None))
                or type(runtime) is not ProjectAgentSessionRuntime
                or not runtime.generation_jobs._characterization
                or not runtime._generation_executor_inbox._characterization
                or type(envelope) is not ExecutionEnvelope
                or type(admission_owner) is not GenerationProtectedCandidateAdmission
                or type(admission_result) is not ProtectedCandidateAdmissionResult
                or admission_result.status != "evidence_observed"
                or type(admission_result.observation) is not ProtectedCandidateAdmissionObservation
                or admission_result.observation.request_index != admission_result.request_index
                or not _profile_a_host_gallery_callbacks_are_valid(
                    callback_bundle, runtime, state,
                )):
            raise ValueError("profile_a_host_binding_required")

        origin = runtime._generation_publication_origin
        lifecycle = runtime._generation_original_host_lifecycle
        integration = (getattr(lifecycle, "_worker_storage_integration", None)
                       if lifecycle is not None else None)
        observation = admission_result.observation
        promotion_owner = observation._promotion_owner
        protected_owner = getattr(promotion_owner, "_protected_owner", None)
        capacity = getattr(integration, "_capacity_owner", None)
        if (type(origin) is not GenerationPublicationOrigin
                or origin.envelope is not envelope
                or admission_owner._runtime is not runtime
                or admission_owner._state is not state
                or admission_owner._origin is not origin
                or admission_owner._envelope is not envelope
                or runtime._generation_protected_candidate_admission is not admission_owner
                or runtime._generation_host_state is not state
                or type(lifecycle) is not OriginalHostGenerationLifecycle
                or lifecycle._worker_storage_integration is not integration
                or type(integration) is not OriginalHostWorkerStorageIntegration
                or integration._profile_a is not True
                or type(capacity) is not WindowsProtectedStorageAdmissionCharacterization
                or capacity._profile_a_root_set is not True
                or type(protected_owner) is not WindowsProtectedAssetsCharacterization
                or protected_owner._profile_a_capacity_owner is not capacity
                or protected_owner._roots.get("promoted_assets")
                    is not capacity._roots.get("promoted_assets")
                or lifecycle._profile_a_storage_binding is None
                or type(lifecycle._profile_a_storage_binding) is not tuple
                or len(lifecycle._profile_a_storage_binding) != 2
                or lifecycle._profile_a_storage_binding[0] is not capacity
                or lifecycle._profile_a_storage_binding[1] is not integration._project_reference
                or type(integration._purpose_roots) is not dict
                or set(integration._purpose_roots) != set(capacity._roots)
                or any(integration._purpose_roots.get(name) is not root
                       for name, root in capacity._roots.items())
                or state.get("project") is not origin.project
                or state.get("current_project_path", "") != origin.path):
            raise ValueError("profile_a_host_binding_required")

        # The protected admission owner is the only authority for the exact
        # receipt and its original-host/event freshness. This is a read-only
        # check and performs native verification without holding host locks.
        with admission_owner._admission_result_current_for_characterization(
                admission_result) as events:
            if (events is None or events[0] is not observation._remote_event
                    or events[1] is not observation._outputs_ready_event):
                raise ValueError("protected_admission_unavailable")

        if not cls._profile_a_scope_authorizes_observation(
                runtime, state, lifecycle, integration, capacity, observation,
                protected_owner, expected_scope_identity=capacity._scope_identity,
                expected_promoted_identity=protected_owner._roots["promoted_assets"]._identity,
        ):
            raise ValueError("profile_a_promoted_root_unavailable")

        owner = cls(
                    state, runtime, envelope,
                    callback_bundle.candidate_factory,
                    callback_bundle.candidate_appender,
                    callback_bundle.save_project,
                    approved_directory=None, mode="profile_a_protected", _factory=_FACTORY)
        owner._profile_a_callback_bundle = callback_bundle
        owner._profile_a_capacity_owner = capacity
        owner._profile_a_protected_owner = protected_owner
        owner._profile_a_promoted_root = capacity._roots["promoted_assets"]
        owner._profile_a_scope_identity = capacity._scope_identity
        owner._profile_a_promoted_root_identity = owner._profile_a_promoted_root._identity
        if not cls._profile_a_scope_authorizes_observation(
                runtime, state, lifecycle, integration, capacity, observation,
                protected_owner,
                expected_scope_identity=owner._profile_a_scope_identity,
                expected_promoted_identity=owner._profile_a_promoted_root_identity,
        ):
            raise ValueError("profile_a_promoted_root_unavailable")
        with owner._authority() as current:
            if not current:
                raise ValueError("stale_original_host")
            if getattr(runtime, "_generation_candidate_publication", None) is not None:
                raise ValueError("publication_owner_exists")
            runtime._generation_candidate_publication = owner
        return owner

    @staticmethod
    def _profile_a_scope_authorizes_observation(
            runtime, state, lifecycle, integration, capacity, observation,
            protected_owner, *, expected_scope_identity=None,
            expected_promoted_identity=None):
        """Recheck Profile A's exact native root, Project reference and lease."""
        try:
            from pathlib import Path
            import json
            from ui.project_agent_session_mailbox import _normalize_target_path

            roots = capacity._roots
            promoted = roots.get("promoted_assets") if type(roots) is dict else None
            reference = integration._project_reference
            binding = lifecycle._profile_a_storage_binding
            if (capacity._closed is not False or capacity._invalid is not False
                    or capacity._scope_lease is None
                    or capacity._scope_lease._state != "held"
                    or set(roots) != {"private_journal", "temporary_containment",
                                      "retained_uncertain", "promoted_assets"}
                    or promoted is not protected_owner._roots.get("promoted_assets")
                    or protected_owner._profile_a_capacity_owner is not capacity
                    or protected_owner._roots.get("promoted_assets") is not promoted
                    or type(integration._purpose_roots) is not dict
                    or set(integration._purpose_roots) != set(roots)
                    or any(integration._purpose_roots.get(name) is not root
                           for name, root in roots.items())
                    or promoted._closed is not False
                    or promoted._purpose != "promoted_assets"
                    or binding is None or type(binding) is not tuple or len(binding) != 2
                    or binding[0] is not capacity or binding[1] is not reference
                    or reference is None or reference._closed is not False
                    or _normalize_target_path(str(reference._path))
                        != _normalize_target_path(lifecycle._project_path)
                    or runtime._generation_host_state is not state
                    or state.get("project") is not runtime._generation_publication_origin.project
                    or state.get("current_project_path", "")
                        != runtime._generation_publication_origin.path
                    or observation._runtime is not runtime
                    or observation._origin is not runtime._generation_publication_origin):
                return False

            scope = Path(capacity._scope)
            scope_identity = capacity._scope_identity
            promoted_path = Path(promoted._path)
            frozen_config = json.loads(
                runtime._generation_publication_origin.envelope.manifest.host_config_json,
            )
            frozen_output = frozen_config.get("output_directory")
            if type(frozen_output) is not str or not frozen_output:
                return False
            frozen_output_path = Path(frozen_output)
            if not frozen_output_path.is_absolute():
                return False
            frozen_output_resolved = frozen_output_path.resolve(strict=False)

            def contains(parent, child):
                return parent == child or child.is_relative_to(parent)

            if (not scope.is_absolute() or not promoted_path.is_absolute()
                    or (expected_scope_identity is not None
                        and scope_identity != expected_scope_identity)
                    or (expected_promoted_identity is not None
                        and promoted._identity != expected_promoted_identity)
                    or promoted_path == scope or not promoted_path.is_relative_to(scope)
                    or scope.resolve(strict=True) != scope
                    or promoted_path.resolve(strict=True) != promoted_path):
                return False
            # Profile A deliberately uses a separate app-private root owner.
            # Keep its root tree disjoint from the frozen Comfy output tree;
            # the latter never becomes authorization for the private root.
            resolved_scope = scope.resolve(strict=True)
            if (contains(frozen_output_resolved, resolved_scope)
                    or contains(resolved_scope, frozen_output_resolved)
                    or contains(frozen_output_resolved, promoted_path.resolve(strict=True))):
                return False
            view = capacity.readiness()
            root_view = promoted.readiness()
            reference_view = reference.readiness()
            return bool(
                view.get("status") == "characterization_only"
                and view.get("root_set_contract") == "profile_a_four_writable_roots"
                and view.get("scope_writer_lease") == "held"
                and view.get("filesystem") == "local_ntfs_observed"
                and view.get("native_root_identity") == "observed_unchanged"
                and view.get("approved_scope_identity") == "observed_unchanged"
                and capacity._scope_identity == scope_identity
                and capacity._scope_lease._state == "held"
                and root_view.get("acl_verified") is True
                and root_view.get("identity") == "handle_observed"
                and reference_view.get("status") == "read_only_reference_observed"
                and reference_view.get("identity") == "observed_unchanged"
                and promoted._closed is False
            )
        except Exception:
            return False

    @classmethod
    def _create_for_characterization(cls, state, runtime, envelope, *, approved_directory,
                                     candidate_factory, candidate_appender, save_project,
                                     characterization, protected_only):
        if (characterization is not True or type(runtime) is not ProjectAgentSessionRuntime
                or not runtime.generation_jobs._characterization
                or not runtime._generation_executor_inbox._characterization):
            raise ValueError("execution_unavailable")
        origin = runtime._generation_publication_origin
        if (type(envelope) is not ExecutionEnvelope or type(origin) is not GenerationPublicationOrigin
                or origin.envelope is not envelope or origin.project is None
                or origin.source_snapshot is None or not origin.path
                or not all(callable(c) for c in (candidate_factory, candidate_appender, save_project))):
            raise ValueError("original_host_required")
        options = json.loads(envelope.manifest.host_config_json)
        # Explicit host approval must exactly name the original frozen output
        # configuration, never a path recomputed from the currently active UI.
        if (type(approved_directory) is not str or not Path(approved_directory).is_absolute()
                or options.get("output_directory") != approved_directory):
            raise ValueError("destination_not_approved")
        approved = Path(approved_directory)
        if not approved.is_dir() or approved.resolve() != approved:
            raise ValueError("destination_not_approved")
        owner = cls(state, runtime, envelope, candidate_factory, candidate_appender, save_project,
                    approved_directory=approved_directory,
                    mode="protected" if protected_only else "legacy", _factory=_FACTORY)
        with owner._authority() as current:
            if not current:
                raise ValueError("stale_original_host")
            if getattr(runtime, "_generation_candidate_publication", None) is not None:
                raise ValueError("publication_owner_exists")
            runtime._generation_candidate_publication = owner
        # Legacy allocation is pinned even if it fails. Protected publication
        # uses its separate native owner and never fabricates this custody.
        if not protected_only:
            owner._assets = DurableGenerationAssets.create_for_characterization(
                approved_directory, characterization=True)
        with owner._authority() as current:
            if not current:
                raise ValueError("stale_original_host")
        return owner

    def __init__(self, state, runtime, envelope, factory, appender, save, *,
                 approved_directory, mode, _factory=None):
        if _factory is not _FACTORY:
            raise ValueError("host_publication_factory_required")
        self._state, self._runtime, self._envelope = state, runtime, envelope
        self._factory, self._appender, self._save = factory, appender, save
        self._approved_directory = Path(approved_directory) if approved_directory is not None else None
        self._mode = mode
        self._origin = runtime._generation_publication_origin
        self._expected = copy.deepcopy(self._origin.source_snapshot)
        self._assets = None
        self._lock = threading.Lock()
        self._busy = False
        self._records, self._evidence = {}, {}
        self._protected_evidence = {}
        self._protected_settled_event_evidence = {}
        self._profile_a_capacity_owner = None
        self._profile_a_protected_owner = None
        self._profile_a_promoted_root = None
        self._profile_a_scope_identity = None
        self._profile_a_promoted_root_identity = None
        self._profile_a_callback_bundle = None
        self._save_state = "not_attempted"
        self._save_callback_outcome = "not_attempted"

    def _bind_profile_a_host_gallery_callbacks_for_characterization(self, callback_bundle):
        """Refresh app-script identities only from an app-issued callback bundle."""
        if (self._mode != "profile_a_protected"
                or not _profile_a_host_gallery_callbacks_are_valid(
                    callback_bundle, self._runtime, self._state,
                )):
            return False
        with self._lock:
            if self._busy or self._save_state != "not_attempted":
                return False
            self._factory = callback_bundle.candidate_factory
            self._appender = callback_bundle.candidate_appender
            self._save = callback_bundle.save_project
            self._profile_a_callback_bundle = callback_bundle
            return True

    def _begin_profile_a_project_save_for_characterization(
            self, authorization, callback_bundle):
        """Claim the single Profile A save only from an integration-issued proof."""
        from ui.agent_generation_original_host_worker_storage import (
            _ProfileAProjectSaveAuthorization,
        )

        if (self._mode != "profile_a_protected"
                or type(authorization) is not _ProfileAProjectSaveAuthorization
                or authorization.publication_owner is not self
                or authorization.integration._profile_a_project_save_authorization
                    is not authorization
                or not _profile_a_host_gallery_callbacks_are_valid(
                    callback_bundle, self._runtime, self._state,
                )):
            return "save_not_authorized"
        with self._lock:
            previous_bundle = self._profile_a_callback_bundle
            if (self._busy or self._save_state != "not_attempted"
                    or type(previous_bundle) is not _ProfileAHostGalleryCallbacks
                    or callback_bundle.candidate_factory is not previous_bundle.candidate_factory
                    or callback_bundle.candidate_appender is not previous_bundle.candidate_appender
                    or callback_bundle.save_project is not previous_bundle.save_project
                    or self._factory is not previous_bundle.candidate_factory
                    or self._appender is not previous_bundle.candidate_appender
                    or self._save is not previous_bundle.save_project):
                return "save_not_authorized"
            self._profile_a_callback_bundle = callback_bundle
            self._save_state = "saving"
            self._busy = True
            return "saving"

    def _finish_profile_a_project_save_for_characterization(
            self, authorization, outcome, callback_outcome):
        from ui.agent_generation_original_host_worker_storage import (
            _ProfileAProjectSaveAuthorization,
        )

        if (type(authorization) is not _ProfileAProjectSaveAuthorization
                or authorization.publication_owner is not self
                or outcome not in {"saved", "save_failed", "save_uncertain", "save_not_authorized"}):
            return False
        with self._lock:
            if not self._busy or self._save_state != "saving":
                return False
            self._save_callback_outcome = callback_outcome
            self._save_state = outcome
            self._busy = False
            return True

    def _abort_profile_a_project_save_before_write_for_characterization(self, authorization):
        """Release only a proven pre-write refusal; never reset a possible save."""
        from ui.agent_generation_original_host_worker_storage import (
            _ProfileAProjectSaveAuthorization,
        )

        if (type(authorization) is not _ProfileAProjectSaveAuthorization
                or authorization.publication_owner is not self):
            return False
        with self._lock:
            if not self._busy or self._save_state != "saving":
                return False
            self._save_state = "not_attempted"
            self._busy = False
            return True

    def _profile_a_saved_candidate_paths_match(self, evidence, serialized_project):
        """Bind reloaded Project-relative Candidate paths to exact Promotions."""
        try:
            lines = serialized_project.get("prompt_lines")
            if type(lines) is not list:
                return False
            for index, (_admission, observation) in evidence.items():
                request = self._envelope.manifest.requests[index]
                promoted_paths = self._protected_candidate_paths(observation)
                matches = [line for line in lines
                           if type(line) is dict and line.get("id") == request.illustration_id
                           and line.get("line_type") != "separator"]
                if len(matches) != 1:
                    return False
                candidates = matches[0].get("generated_candidates")
                if type(candidates) is not list:
                    return False
                rows = []
                for candidate in candidates:
                    provenance = candidate.get("generation_provenance") if type(candidate) is dict else None
                    if (type(provenance) is dict
                            and provenance.get("job_id") == self._envelope.job_id
                            and provenance.get("request_id") == request.request_id
                            and provenance.get("request_index") == index):
                        rows.append(candidate)
                if len(rows) != len(promoted_paths):
                    return False
                for candidate, promoted_path in zip(rows, promoted_paths):
                    saved_path = candidate.get("path")
                    if type(saved_path) is not str or not saved_path:
                        return False
                    resolved = resolve_project_asset_path(saved_path, self._origin.path)
                    if (os.path.normcase(os.path.abspath(resolved))
                            != os.path.normcase(os.path.abspath(promoted_path))
                            or not os.path.isfile(resolved)):
                        return False
            return True
        except Exception:
            return False

    @contextmanager
    def _authority(self, index=None, remote=None, local=None, *, source=True, _gate_held=False):
        runtime, envelope = self._runtime, self._envelope
        jobs, inbox = runtime.generation_jobs, runtime._generation_executor_inbox
        with nullcontext() if _gate_held else runtime._publication_gate:
            route = (runtime._registry._record_for_registration(runtime._registration)
                     if not runtime._closed and runtime._registration is not None else None)
            if route is None:
                yield False
                return
            with route.operation_lock:
                epoch = runtime._synchronize_target_locked(self._state.get("project"),
                                                          self._state.get("current_project_path", ""))
                available, pairing = runtime._registration.inspect_pairing_generation()
                with jobs._lock:
                    jobs._cleanup_locked(jobs._clock())
                    job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                    with inbox._lock:
                        current = bool(available and jobs._characterization and inbox._characterization
                            and job is not None and job.binding == envelope.binding
                            and job.binding.session_id == jobs._session_incarnation
                            and job.binding.process_incarnation == _PROCESS_INCARNATION
                            and job.binding.target_epoch == epoch
                            and (job.binding.target_epoch, job.binding.activation_id) == jobs._target
                            and type(pairing) is int and job.binding.pairing_generation == pairing
                            and job.state not in {"expired", "cancelled", "unavailable",
                                "stale_target_outputs_not_registered", "submission_outcome_unknown"}
                            and inbox._envelope is envelope and inbox._state == "accepted" and not inbox._closed
                            and runtime._generation_publication_origin is self._origin
                            and self._origin.envelope is envelope
                            and self._state.get("project") is self._origin.project
                            and self._state.get("current_project_path", "") == self._origin.path)
                        if current and index is not None:
                            request = envelope.manifest.requests[index]
                            current = bool(job.request_states[index] == "awaiting_host_registration"
                                and job.requests[index] == JobRequest(request.request_id, request.illustration_id,
                                                                     request.run_index, request.workflow_identity)
                                and remote is not None and local is not None and local.state == "verified"
                                and (remote.job_id, remote.claim_id, remote.manifest_identity, remote.request_id,
                                     remote.request_index, remote.workflow_identity) ==
                                    (envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity,
                                     request.request_id, index, request.workflow_identity)
                                and (local.job_id, local.claim_id, local.manifest_identity, local.request_id,
                                     local.request_index, local.workflow_identity, local.remote_receipt_identity,
                                     local.prompt_id) ==
                                    (remote.job_id, remote.claim_id, remote.manifest_identity, remote.request_id,
                                     index, remote.workflow_identity, remote.identity, remote.prompt_id)
                                and remote.execution_succeeded
                                and local.verified_count == local.downloaded_count == len(remote.images)
                                and job.outputs[index] == local.verified_count
                                and tuple(i.descriptor_identity for i in local.images) == tuple(i.identity for i in remote.images)
                                and any(e.progress.request_index == index and e.progress.kind == "outputs_ready"
                                    and e.outputs.receipt_id == local.identity[:32]
                                    and e.outputs.output_count == local.verified_count for e in inbox._events.values()))
                # In-memory equality follows the serialized full-app host writer
                # contract, including prompts, Modules, routes and source images.
                if current and source:
                    current = self._origin.project == self._expected
                yield current  # no job/inbox/mailbox locks cross host mutation

    def publish_for_characterization(self, store, remote, local):
        if self._mode != "legacy":
            index = getattr(local, "request_index", -1)
            return PublicationReceipt(index if type(index) is int else -1,
                                      "not_attempted", "writer_mode_mismatch")
        index = getattr(local, "request_index", -1)
        if type(index) is not int or not 0 <= index < len(self._envelope.manifest.requests):
            return PublicationReceipt(-1, "not_attempted", "invalid_receipt")
        with self._lock:
            previous = self._records.get(index)
            if previous is not None:
                evidence = self._evidence[index]
                return previous if all(a is b for a, b in zip(evidence, (store, remote, local))) else PublicationReceipt(
                    index, "not_attempted", "receipt_conflict")
            if self._busy or self._save_state != "not_attempted":
                return PublicationReceipt(index, "not_attempted", "publication_busy")
            self._busy = True
            # One-shot attempt linearizes here, before any callbacks/I/O.
            self._records[index] = PublicationReceipt(index, "not_attempted", "publication_in_progress")
            self._evidence[index] = (store, remote, local)
        promotion = "not_attempted"
        mutation_started, observed_count = False, 0
        receipt = PublicationReceipt(index, promotion, "stale_original_host")
        try:
            with self._authority(index, remote, local) as current:
                if not current:
                    return receipt
            images = self._assets.promote_for_characterization(store, self._envelope, remote, local)
            promotion = "promoted"
            request = self._envelope.manifest.requests[index]
            row = json.loads(self._origin.review_json)["requests"][index]
            target = resolve_gallery_generation_result_target(self._expected, request.illustration_id)["target_line"]
            records = []
            for ordinal, promoted in enumerate(images, 1):
                # Existing app factory keeps its schema/timestamp/path behavior.
                record = self._factory(promoted.path, target, "agent_generation", request.run_index)
                if type(record) is not dict:
                    raise ValueError("candidate_factory_failed")
                record = copy.deepcopy(record)
                prompts = row["prompts"]
                def prompt(role):
                    values = [p["text"] for p in prompts if p["role"] == role]
                    return values[0] if values and len(set(values)) == 1 else None
                seed_values = [s["value"] for s in row["seeds"] if s["input_key"] == "seed"]
                record.update(path=promoted.path, prompt_text=prompt("positive"), negative_prompt=prompt("negative"),
                    candidate_prompt_source="frozen_execution", seed=seed_values[0] if len(seed_values) == 1 else None,
                    seed_mode="frozen_execution", run_index=request.run_index,
                    generation_provenance={"job_id": self._envelope.job_id,
                        "manifest_identity": self._envelope.manifest.manifest_identity,
                        "request_id": request.request_id, "request_index": index,
                        "illustration_id": request.illustration_id, "run_index": request.run_index,
                        "workflow_identity": request.workflow_identity, "prompt_id": remote.prompt_id,
                        "remote_receipt_identity": remote.identity, "local_receipt_identity": local.identity,
                        "descriptor_identity": promoted.image.descriptor_identity,
                        "content_sha256": promoted.image.content_sha256, "output_index": ordinal,
                        "prompts": prompts, "seeds": row["seeds"], "parameters": row["parameters"],
                        "prompt_available": prompt("positive") is not None,
                        "seed_available": len(seed_values) == 1})
                records.append(record)
            history_snapshot = copy.deepcopy(self._expected)
            normalized_existing = _normalize_candidate_records(target.generated_candidates)
            # Keep the expected-current snapshot detached even for nested
            # provenance. The existing app normalizer intentionally uses
            # shallow record copies; sharing those aliases would hide later
            # source metadata edits from this owner's freshness comparison.
            normalized_new = _normalize_candidate_records(copy.deepcopy(records))
            self._assets.revalidate_for_characterization(images)
            store.revalidate_for_characterization(local)
            by_path = {r["path"]: r for r in records}
            paths = [i.path for i in images]
            with self._authority(index, remote, local) as current:
                if not current:
                    receipt = PublicationReceipt(index, promotion, "stale_original_host")
                    return receipt
                history = self._state.get("history")
                if type(history) is not list:
                    raise ValueError("history_unavailable")
                history.append(history_snapshot)
                error = False
                actual = resolve_gallery_generation_result_target(self._origin.project,
                    request.illustration_id)["target_line"]
                mutation_started = True
                try:
                    ingest_gallery_generation_outputs(self._origin.project,
                        {"source_line_id": request.illustration_id, "request_id": request.request_id,
                         "run_index": request.run_index}, paths,
                        candidate_factory=lambda path, line, request: by_path[path],
                        candidate_appender=self._appender, resolve_path=lambda p: p,
                        path_exists=lambda p: p in by_path)
                except Exception:
                    error = True  # appender may have mutated before raising
                observed = [r for r in normalized_new if r in actual.generated_candidates]
                # `target` belongs to the detached expected-current snapshot.
                # Advance only this publisher's exact observed Candidate delta;
                # the immutable origin baseline and every other source value
                # remain unchanged for subsequent request/drift checks.
                target.generated_candidates = [*normalized_existing, *observed]
                count = len(observed)
                observed_count = count
                if not count:
                    history.pop()
                elif len(history) > 20:
                    history.pop(0)
                # Compare every other Project value before settling counts.
                intact = self._origin.project == self._expected
                with self._authority(index, remote, local, source=False, _gate_held=True) as still_current:
                    if not still_current or not intact:
                        receipt = PublicationReceipt(index, promotion, "registration_uncertain", count)
                        return receipt
                    result = self._runtime.generation_jobs.publication_for_characterization(
                        self._envelope.job_id, self._envelope.claim_id, binding=self._envelope.binding,
                        request_index=index, registered_count=count)
                status = ("registered" if count == len(records) and not error and result == "accepted"
                          else "registration_uncertain" if error or result != "accepted"
                          else "partially_registered" if count else "registration_failed")
                receipt = PublicationReceipt(index, promotion, status, count)
                return receipt
        except Exception:
            receipt = PublicationReceipt(index, "promotion_failed" if promotion != "promoted" else promotion,
                "registration_uncertain" if mutation_started else "registration_failed", observed_count)
            return receipt
        finally:
            with self._lock:
                self._records[index] = receipt
                self._busy = False

    def publish_protected_for_characterization(self, admission_owner, observation):
        """Append exact protected promotion images through the existing Gallery writer.

        This is a distinct characterization mode: protected receipts are never
        adapted into LocalOutputReceipt, ContainedOutputStore or PromotedImage.
        """
        if self._mode not in {"protected", "profile_a_protected"}:
            index = getattr(observation, "request_index", -1)
            return PublicationReceipt(index if type(index) is int else -1,
                                      "not_attempted", "writer_mode_mismatch")
        index = getattr(observation, "request_index", -1)
        if (type(admission_owner) is not GenerationProtectedCandidateAdmission
                or type(observation) is not ProtectedCandidateAdmissionObservation
                or type(index) is not int
                or not 0 <= index < len(self._envelope.manifest.requests)):
            return PublicationReceipt(-1, "not_attempted", "admission_required")
        with self._lock:
            previous = self._records.get(index)
            if previous is not None:
                evidence = self._protected_evidence.get(index)
                exact = (evidence is not None and evidence[0] is admission_owner
                         and evidence[1] is observation)
                return previous if exact else PublicationReceipt(
                    index, "not_attempted", "receipt_conflict")
            if self._busy or self._save_state != "not_attempted":
                return PublicationReceipt(index, "not_attempted", "publication_busy")
            self._busy = True
            self._records[index] = PublicationReceipt(index, "not_attempted", "publication_in_progress")
            self._protected_evidence[index] = (admission_owner, observation)

        promotion_state = "not_attempted"
        mutation_started, observed_count = False, 0
        receipt = PublicationReceipt(index, promotion_state, "stale_original_host")
        settled_events = None
        try:
            if not self._protected_observation_is_owned(admission_owner, observation):
                receipt = PublicationReceipt(index, promotion_state, "admission_mismatch")
                return receipt
            with self._authority() as current:
                if not current:
                    return receipt

            promotion_owner = observation._promotion_owner
            protected_receipt = observation._promotion_receipt
            remote = observation._remote_receipt
            if (promotion_owner._inspect_for_candidate_admission_for_characterization(
                    protected_receipt, admission_owner._host_freshness_for_admission)
                    is not protected_receipt):
                raise ValueError("protected_promotion_unavailable")
            paths = self._protected_candidate_paths(observation)
            promotion_state = "protected_verified"

            request = self._envelope.manifest.requests[index]
            if (request.request_index != index or remote.request_index != index
                    or protected_receipt.request_index != index):
                raise ValueError("request_mismatch")
            row = json.loads(self._origin.review_json)["requests"][index]
            target_result = resolve_gallery_generation_result_target(self._expected, request.illustration_id)
            target = target_result["target_line"]
            actual = resolve_gallery_generation_result_target(
                self._origin.project, request.illustration_id)["target_line"]
            if target is None or actual is None:
                raise ValueError("target_unavailable")

            records = []
            for ordinal, (promoted, path) in enumerate(zip(protected_receipt.images, paths), 1):
                # Keep the established app record factory and frozen review
                # fields; only the exact owner-verified path supplies the image.
                record = self._factory(path, target, "agent_generation", request.run_index)
                if type(record) is not dict:
                    raise ValueError("candidate_factory_failed")
                record = copy.deepcopy(record)
                prompts = row["prompts"]

                def prompt(role):
                    values = [p["text"] for p in prompts if p["role"] == role]
                    return values[0] if values and len(set(values)) == 1 else None

                seed_values = [s["value"] for s in row["seeds"] if s["input_key"] == "seed"]
                image = promoted.promoted_image
                record.update(path=path, prompt_text=prompt("positive"), negative_prompt=prompt("negative"),
                    candidate_prompt_source="frozen_execution",
                    seed=seed_values[0] if len(seed_values) == 1 else None,
                    seed_mode="frozen_execution", run_index=request.run_index,
                    generation_provenance={"job_id": self._envelope.job_id,
                        "manifest_identity": self._envelope.manifest.manifest_identity,
                        "request_id": request.request_id, "request_index": index,
                        "illustration_id": request.illustration_id, "run_index": request.run_index,
                        "workflow_identity": request.workflow_identity, "prompt_id": remote.prompt_id,
                        "remote_receipt_identity": remote.identity,
                        "protected_promotion_identity": protected_receipt.identity,
                        "protected_candidate_admission_identity": observation.identity,
                        "descriptor_identity": promoted.descriptor_identity,
                        "protected_storage_identity": image.storage_identity,
                        "protected_purpose": image.purpose,
                        "content_sha256": image.content_sha256, "output_index": ordinal,
                        "image_format": image.image_format, "image_byte_count": image.byte_count,
                        "prompts": prompts, "seeds": row["seeds"], "parameters": row["parameters"],
                        "prompt_available": prompt("positive") is not None,
                        "seed_available": len(seed_values) == 1})
                records.append(record)

            if not records or len(records) != len(paths):
                raise ValueError("protected_batch_incomplete")
            history_snapshot = copy.deepcopy(self._expected)
            normalized_existing = _normalize_candidate_records(target.generated_candidates)
            normalized_new = _normalize_candidate_records(copy.deepcopy(records))
            by_path = {record["path"]: record for record in records}
            if len(by_path) != len(records):
                raise ValueError("protected_path_conflict")

            # Reverify all native files after factory work and immediately
            # before entering the host commit gate. The lease acquired by that
            # gate serializes owner close/invalidation against the appender.
            if promotion_owner._inspect_for_candidate_admission_for_characterization(
                    protected_receipt, admission_owner._host_freshness_for_admission) is not protected_receipt:
                raise ValueError("protected_promotion_unavailable")
            if self._protected_candidate_paths(observation) != paths:
                raise ValueError("protected_path_changed")

            with self._protected_candidate_publication_commit_guard(
                    admission_owner, observation) as current_events:
                if current_events is None:
                    receipt = PublicationReceipt(index, promotion_state, "stale_original_host")
                    return receipt
                settled_events = current_events
                history = self._state.get("history")
                if type(history) is not list:
                    raise ValueError("history_unavailable")
                history.append(history_snapshot)
                error = False
                actual = resolve_gallery_generation_result_target(
                    self._origin.project, request.illustration_id)["target_line"]
                if actual is None:
                    history.pop()
                    raise ValueError("target_unavailable")
                mutation_started = True
                try:
                    ingest_gallery_generation_outputs(self._origin.project,
                        {"source_line_id": request.illustration_id, "request_id": request.request_id,
                         "run_index": request.run_index}, paths,
                        candidate_factory=lambda path, line, generation_request: by_path[path],
                        candidate_appender=self._appender, resolve_path=lambda path: path,
                        path_exists=lambda path: path in by_path)
                except Exception:
                    error = True  # the appender may have mutated before raising

                observed = [record for record in normalized_new if record in actual.generated_candidates]
                # Advance only the observed Candidate delta in the detached
                # expected Project. The original source snapshot remains fixed.
                expected_target = resolve_gallery_generation_result_target(
                    self._expected, request.illustration_id)["target_line"]
                if expected_target is None:
                    raise ValueError("target_unavailable")
                expected_target.generated_candidates = [*normalized_existing, *observed]
                count = len(observed)
                observed_count = count
                if not count:
                    history.pop()
                elif len(history) > 20:
                    history.pop(0)

                intact = self._origin.project == self._expected
                runtime = self._runtime
                try:
                    epoch = runtime._synchronize_target_locked(
                        self._state.get("project"), self._state.get("current_project_path", ""))
                    available, pairing = runtime._registration.inspect_pairing_generation()
                    still_current = (not runtime._closed
                        and runtime._generation_publication_origin is self._origin
                        and self._state.get("project") is self._origin.project
                        and self._state.get("current_project_path", "") == self._origin.path
                        and epoch == self._envelope.binding.target_epoch
                        and (epoch, epoch) == (self._envelope.binding.target_epoch,
                                               self._envelope.binding.activation_id)
                        and available and pairing == self._envelope.binding.pairing_generation)
                except Exception:
                    still_current = False
                if not still_current or not intact:
                    receipt = PublicationReceipt(index, promotion_state, "registration_uncertain", count)
                    return receipt
                result = runtime.generation_jobs.publication_for_characterization(
                    self._envelope.job_id, self._envelope.claim_id, binding=self._envelope.binding,
                    request_index=index, registered_count=count)

                status = ("registered" if count == len(records) and not error and result == "accepted"
                          else "registration_uncertain" if error or result != "accepted"
                          else "partially_registered" if count else "registration_failed")
                if status != "registered":
                    settled_events = None
                # A safely observed partial delta is current Project state even
                # when the appender raised or the job records uncertainty.
                # Advance only the admission comparison baseline; the request
                # receipt remains uncertain and is never replayed or treated as
                # successful. This permits a later distinct request only when
                # the complete Project exactly matches the observed delta.
                if count and not admission_owner._advance_candidate_snapshot_for_characterization(
                        observation, history_snapshot, self._expected):
                    status = "registration_uncertain"
                receipt = PublicationReceipt(index, promotion_state, status, count)
                return receipt
        except Exception:
            receipt = PublicationReceipt(index,
                "protected_verification_failed" if promotion_state == "not_attempted" else promotion_state,
                "registration_uncertain" if mutation_started else "registration_failed", observed_count)
            return receipt
        finally:
            with self._lock:
                self._records[index] = receipt
                if (receipt.registration_state == "registered"
                        and type(settled_events) is tuple and len(settled_events) == 2):
                    self._protected_settled_event_evidence[index] = _ProtectedSettledEventEvidence(
                        index, settled_events[0], settled_events[1])
                else:
                    self._protected_settled_event_evidence.pop(index, None)
                self._busy = False

    def _protected_observation_is_owned(self, admission_owner, observation):
        if (admission_owner._runtime is not self._runtime
                or admission_owner._envelope is not self._envelope
                or observation._runtime is not self._runtime
                or observation._origin is not self._origin
                or observation._envelope is not self._envelope
                or observation._project is not self._origin.project
                or observation._source_snapshot != self._origin.source_snapshot):
            return False
        index = observation.request_index
        with admission_owner._lock:
            attempt = admission_owner._attempts.get(index)
            return bool(not admission_owner._closed and attempt is not None
                and attempt.status == "observed"
                and attempt.promotion_owner is observation._promotion_owner
                and attempt.receipt is observation._promotion_receipt
                and attempt.remote is observation._remote_receipt
                and attempt.result is not None
                and attempt.result.status == "evidence_observed"
                and attempt.result.observation is observation
                and admission_owner._receipt_binding(
                    observation._promotion_owner, observation._promotion_receipt,
                    observation._remote_receipt, index))

    def _profile_a_registered_prefix_snapshot_for_characterization(
            self, project, request_index):
        """Return the exact Project state after a fully registered request prefix.

        Profile A appends Candidates to the original Project before the next
        sequential request can be published. The original review snapshot
        remains immutable; this owner separately retains the exact expected
        Project state advanced only by observed Candidate registration.
        """
        if (self._mode != "profile_a_protected"
                or type(request_index) is not int
                or not 0 <= request_index <= len(self._envelope.manifest.requests)
                or project is not self._origin.project
                or self._runtime._generation_publication_origin is not self._origin
                or self._runtime._generation_candidate_publication is not self):
            return None
        with self._lock:
            if self._busy or self._save_state != "not_attempted":
                return None
            expected = copy.deepcopy(self._expected)
            records = dict(self._records)
            evidence = dict(self._protected_evidence)
            settled = dict(self._protected_settled_event_evidence)
        try:
            if project != expected:
                return None
        except Exception:
            return None

        jobs, inbox = self._runtime.generation_jobs, self._runtime._generation_executor_inbox
        owned_observations = []
        try:
            with jobs._lock:
                with inbox._lock:
                    job = jobs._authorized_locked(
                        self._envelope.job_id, self._envelope.claim_id,
                    )
                    if (jobs._closed or inbox._closed or inbox._state != "accepted"
                            or inbox._envelope is not self._envelope
                            or inbox._late_output_seen or job is None
                            or job.binding != self._envelope.binding
                            or len(job.request_states) != len(self._envelope.manifest.requests)):
                        return None
                    for index in range(request_index):
                        request = self._envelope.manifest.requests[index]
                        record = records.get(index)
                        pair = evidence.get(index)
                        if (job.request_states[index] != "completed"
                                or job.outputs[index] <= 0
                                or job.remote_outputs[index] != job.outputs[index]
                                or job.registered[index] != job.outputs[index]
                                or record is None
                                or record.registration_state != "registered"
                                or record.promotion_state != "protected_verified"
                                or record.registered_count != job.registered[index]
                                or type(pair) is not tuple or len(pair) != 2
                                or settled.get(index) is None
                                or job.requests[index].request_id != request.request_id
                                or job.requests[index].illustration_id != request.illustration_id
                                or job.requests[index].run_index != request.run_index
                                or job.requests[index].workflow_identity != request.workflow_identity
                                or not self._protected_save_event_current(
                                    index, job, inbox, pair[1], settled[index],
                                )):
                            return None
                        owned_observations.append(pair)
        except Exception:
            return None

        for admission_owner, observation in owned_observations:
            if (admission_owner is None
                    or not self._protected_observation_is_owned(
                        admission_owner, observation)):
                return None
        return expected

    @contextmanager
    def _profile_a_candidate_publication_guard(self):
        """Serialize the Profile A Gallery commit with capacity-owner close."""
        if self._mode != "profile_a_protected":
            yield
            return
        capacity = self._profile_a_capacity_owner
        token = capacity._begin_profile_a_candidate_publication_for_characterization(
            expected_scope_identity=self._profile_a_scope_identity,
            expected_promoted_root=self._profile_a_promoted_root,
        )
        try:
            yield
        finally:
            capacity._finish_profile_a_candidate_publication_for_characterization(token)

    @contextmanager
    def _protected_candidate_publication_commit_guard(self, admission_owner, observation):
        """Enter the original admission guard, then the Profile A capacity lease."""
        with admission_owner._candidate_publication_commit_for_characterization(
                observation) as events:
            if events is None:
                yield None
                return
            with self._profile_a_candidate_publication_guard():
                yield events

    def _protected_candidate_paths(self, observation):
        promotion_owner = observation._promotion_owner
        receipt = observation._promotion_receipt
        protected = promotion_owner._protected_owner
        root_owner = protected._roots.get("promoted_assets")
        root = Path(root_owner._path) if root_owner is not None else None
        if self._mode == "profile_a_protected":
            if (root is None
                    or protected is not self._profile_a_protected_owner
                    or root_owner is not self._profile_a_promoted_root
                    or root_owner._identity != self._profile_a_promoted_root_identity
                    or self._profile_a_capacity_owner is None
                    or not self._profile_a_scope_authorizes_observation(
                        self._runtime, self._state,
                        self._runtime._generation_original_host_lifecycle,
                        self._runtime._generation_original_host_lifecycle._worker_storage_integration,
                        self._profile_a_capacity_owner, observation, protected,
                        expected_scope_identity=self._profile_a_scope_identity,
                        expected_promoted_identity=self._profile_a_promoted_root_identity,
                    )):
                raise ValueError("profile_a_promoted_root_unavailable")
        elif (root is None or self._approved_directory is None
                or root == self._approved_directory
                or not _path_is_within_approved_destination(
                    root, self._approved_directory, strict=True)):
            raise ValueError("destination_not_approved")
        remote = observation._remote_receipt
        if len(receipt.images) != len(remote.images) or not receipt.images:
            raise ValueError("protected_batch_incomplete")
        paths, seen = [], set()
        for promoted, descriptor in zip(receipt.images, remote.images):
            image = promoted.promoted_image
            key = ("promoted_assets", image.storage_identity)
            file_record = protected._files.get(key)
            path = Path(file_record[0]) if file_record is not None else None
            if (promoted.descriptor_identity != descriptor.identity
                    or image.purpose != "promoted_assets"
                    or path is None or path.parent != root or path.name != image.storage_identity
                    or protected._images.get(key) is not image
                    or (self._mode != "profile_a_protected"
                        and not _path_is_within_approved_destination(path, self._approved_directory))):
                raise ValueError("protected_path_unavailable")
            normalized = os.path.normcase(os.path.abspath(path))
            if normalized in seen:
                raise ValueError("protected_path_conflict")
            seen.add(normalized)
            paths.append(str(path))
        return tuple(paths)

    def _protected_candidate_records_current(self, evidence):
        """Match persisted in-memory Candidate records to exact protected bytes."""
        try:
            review = json.loads(self._origin.review_json)
            requests = review["requests"]
            if len(requests) != len(self._envelope.manifest.requests):
                return False
            for index, (admission_owner, observation) in evidence.items():
                if not self._protected_observation_is_owned(admission_owner, observation):
                    return False
                request = self._envelope.manifest.requests[index]
                remote = observation._remote_receipt
                promotion = observation._promotion_receipt
                row = requests[index]
                paths = self._protected_candidate_paths(observation)
                target = resolve_gallery_generation_result_target(
                    self._origin.project, request.illustration_id)["target_line"]
                if (target is None or request.request_index != index
                        or remote.request_index != index or promotion.request_index != index
                        or len(paths) != len(remote.images) or len(paths) != len(promotion.images)):
                    return False
                candidates = target.generated_candidates
                if type(candidates) is not list:
                    return False
                matching = []
                for candidate in candidates:
                    provenance = candidate.get("generation_provenance") if type(candidate) is dict else None
                    if (type(provenance) is dict
                            and provenance.get("job_id") == self._envelope.job_id
                            and provenance.get("request_id") == request.request_id
                            and provenance.get("request_index") == index):
                        matching.append(candidate)
                if len(matching) != len(paths):
                    return False

                prompt_rows = row["prompts"]
                positive = [item["text"] for item in prompt_rows if item["role"] == "positive"]
                negative = [item["text"] for item in prompt_rows if item["role"] == "negative"]
                prompt_text = positive[0] if positive and len(set(positive)) == 1 else None
                negative_text = negative[0] if negative and len(set(negative)) == 1 else None
                seed_rows = row["seeds"]
                seed_values = [item["value"] for item in seed_rows if item["input_key"] == "seed"]
                seed = seed_values[0] if len(seed_values) == 1 else None

                for ordinal, (candidate, promoted, descriptor, path) in enumerate(
                        zip(matching, promotion.images, remote.images, paths), 1):
                    image = promoted.promoted_image
                    provenance = candidate["generation_provenance"]
                    expected = {
                        "job_id": self._envelope.job_id,
                        "manifest_identity": self._envelope.manifest.manifest_identity,
                        "request_id": request.request_id,
                        "request_index": index,
                        "illustration_id": request.illustration_id,
                        "run_index": request.run_index,
                        "workflow_identity": request.workflow_identity,
                        "prompt_id": remote.prompt_id,
                        "remote_receipt_identity": remote.identity,
                        "protected_promotion_identity": promotion.identity,
                        "protected_candidate_admission_identity": observation.identity,
                        "descriptor_identity": descriptor.identity,
                        "protected_storage_identity": image.storage_identity,
                        "protected_purpose": "promoted_assets",
                        "content_sha256": image.content_sha256,
                        "output_index": ordinal,
                        "image_format": image.image_format,
                        "image_byte_count": image.byte_count,
                        "prompts": prompt_rows,
                        "seeds": seed_rows,
                        "parameters": row["parameters"],
                        "prompt_available": prompt_text is not None,
                        "seed_available": len(seed_values) == 1,
                    }
                    if (any(provenance.get(key) != value for key, value in expected.items())
                            or candidate.get("path") != path
                            or candidate.get("candidate_prompt_source") != "frozen_execution"
                            or candidate.get("prompt_text") != prompt_text
                            or candidate.get("negative_prompt") != negative_text
                            or candidate.get("seed") != seed
                            or candidate.get("seed_mode") != "frozen_execution"
                            or candidate.get("run_index") != request.run_index):
                        return False
            return True
        except Exception:
            return False

    @staticmethod
    def _protected_save_event_current(index, job, inbox, observation, settled):
        """Verify publisher-retained events against any still-live event logs.

        Inbox and job event histories are bounded diagnostic logs. Successful
        publication retains the exact accepted event pair in this owner, so
        absence from either log is legitimate eviction while missing private
        proof, changed retained values, extra events, or late outputs refuse.
        """
        remote = observation._remote_receipt
        promotion = observation._promotion_receipt
        if (type(settled) is not _ProtectedSettledEventEvidence
                or settled.request_index != index or inbox._late_output_seen):
            return False
        if any(type(event) is not ExecutorEvent or type(event.progress) is not WorkerEvent
               for event in inbox._events.values()):
            return False
        index_events = tuple((sequence, event) for sequence, event in inbox._events.items()
            if event.progress.request_index == index
            and event.progress.kind in {"remote_outputs_ready", "outputs_ready"})
        late_events = tuple(event for event in inbox._late
            if getattr(getattr(event, "progress", None), "request_index", None) == index
            and getattr(getattr(event, "progress", None), "kind", None)
                in {"remote_outputs_ready", "outputs_ready"}
            and (getattr(event, "job_id", None), getattr(event, "claim_id", None),
                 getattr(event, "manifest_identity", None))
                == (job.job_id, job.claim_id, job.binding.plan_identity))
        if late_events:
            return False

        remote_event = settled.remote_event
        output_event = settled.outputs_ready_event
        if (type(remote_event) is not ExecutorEvent or type(remote_event.progress) is not WorkerEvent
                or type(output_event) is not ExecutorEvent or type(output_event.progress) is not WorkerEvent
                or remote_event is not observation._remote_event
                or output_event is not observation._outputs_ready_event):
            return False
        remote_sequence = remote_event.progress.sequence
        output_sequence = output_event.progress.sequence
        expected_events = {remote_sequence: remote_event, output_sequence: output_event}
        if len(expected_events) != 2:
            return False
        if any(sequence not in expected_events or event is not expected_events[sequence]
               for sequence, event in index_events):
            return False
        job_events = tuple((sequence, event) for sequence, event in job.events.items()
            if type(event) is WorkerEvent and event.request_index == index
            and event.kind in {"remote_outputs_ready", "outputs_ready"})
        if (any(type(event) is not WorkerEvent for event in job.events.values())
                or any(sequence not in expected_events or event != expected_events[sequence].progress
                       for sequence, event in job_events)
                or any(sequence in job.events and job.events[sequence] != event.progress
                       for sequence, event in expected_events.items())
                or any(sequence in inbox._events and inbox._events[sequence] is not event
                       for sequence, event in expected_events.items())):
            return False

        count = len(remote.images)
        return bool(
            type(remote_event.outputs) is OutputReceipt
            and type(output_event.outputs) is OutputReceipt
            and remote_sequence == remote_event.progress.sequence
            and output_sequence == output_event.progress.sequence
            and remote_event.progress.request_index == index
            and remote_event.progress.kind == "remote_outputs_ready"
            and output_event.progress.request_index == index
            and output_event.progress.kind == "outputs_ready"
            and remote_sequence < output_sequence <= job.event_count
            and (remote_event.job_id, remote_event.claim_id, remote_event.manifest_identity)
                == (job.job_id, job.claim_id, job.binding.plan_identity)
            and (remote_event.outputs.receipt_id, remote_event.outputs.output_count,
                 remote_event.progress.output_count)
                == (remote.identity[:32], count, count)
            and (output_event.job_id, output_event.claim_id, output_event.manifest_identity)
                == (job.job_id, job.claim_id, job.binding.plan_identity)
            and (output_event.outputs.receipt_id, output_event.outputs.output_count,
                 output_event.progress.output_count)
                == (promotion.identity[:32], count, count))

    @contextmanager
    def _protected_save_authority(self, evidence, *, allowed_project_states=None):
        """Check settled registrations and host evidence under original gates.

        Only the runtime/route gates span the yielded section. Job, inbox and
        admission locks are released before Candidate inspection or callers
        publish the registry save result.
        """
        runtime, envelope = self._runtime, self._envelope
        jobs, inbox = runtime.generation_jobs, runtime._generation_executor_inbox
        allowed_project_states = ((self._expected,) if allowed_project_states is None
                                  else tuple(allowed_project_states))
        with runtime._publication_gate:
            if runtime._closed or runtime._registration is None:
                yield False
                return
            route = runtime._registry._record_for_registration(runtime._registration)
            if route is None:
                yield False
                return
            with route.operation_lock:
                try:
                    epoch = runtime._synchronize_target_locked(
                        self._state.get("project"), self._state.get("current_project_path", ""))
                    available, pairing = runtime._registration.inspect_pairing_generation()
                except Exception:
                    epoch, available, pairing = None, False, None
                base_current = bool(
                    available and not runtime._closed
                    and runtime._generation_candidate_publication is self
                    and runtime._generation_publication_origin is self._origin
                    and self._origin.envelope is envelope
                    and self._state.get("project") is self._origin.project
                    and self._state.get("current_project_path", "") == self._origin.path
                    and self._origin.source_snapshot is not None
                    and (epoch, epoch) == (envelope.binding.target_epoch, envelope.binding.activation_id)
                    and pairing == envelope.binding.pairing_generation)
                if not base_current:
                    yield False
                    return

                admission_owners = {pair[0] for pair in evidence.values()}
                if len(admission_owners) != 1:
                    yield False
                    return
                admission = next(iter(admission_owners))
                with jobs._lock:
                    jobs._cleanup_locked(jobs._clock())
                    job = jobs._authorized_locked(envelope.job_id, envelope.claim_id)
                    with inbox._lock:
                        with admission._lock:
                            current = bool(
                                jobs._characterization and inbox._characterization
                                and not jobs._closed and not inbox._closed
                                and not inbox._late_output_seen
                                and job is not None and job.binding == envelope.binding
                                and job.binding.session_id == jobs._session_incarnation
                                and job.binding.process_incarnation == _PROCESS_INCARNATION
                                and job.binding.plan_identity == envelope.manifest.manifest_identity
                                and (job.binding.target_epoch, job.binding.activation_id) == jobs._target
                                and job.binding.pairing_generation == pairing
                                and job.state in {"completed", "partially_failed"}
                                and len(job.requests) == len(envelope.manifest.requests)
                                and len(job.request_states) == len(job.requests)
                                and inbox._state == "accepted" and inbox._envelope is envelope
                                and inbox._manifest is envelope.manifest
                                and runtime._generation_protected_candidate_admission is admission
                                and not admission._closed
                                and admission._runtime is runtime
                                and admission._origin is self._origin
                                and admission._envelope is envelope
                                and admission._source_snapshot == self._origin.source_snapshot
                                and admission._candidate_expected == self._expected
                                and self._origin.project in allowed_project_states)
                            if current:
                                current = all(
                                    type(event) is ExecutorEvent and type(event.progress) is WorkerEvent
                                    for event in inbox._events.values())
                            if current:
                                current = all(state in {"completed", "failed"}
                                              for state in job.request_states)
                            if current:
                                for index, request in enumerate(envelope.manifest.requests):
                                    expected_request = JobRequest(
                                        request.request_id, request.illustration_id,
                                        request.run_index, request.workflow_identity)
                                    state = job.request_states[index]
                                    output_count = job.outputs[index]
                                    remote_count = job.remote_outputs[index]
                                    registered_count = job.registered[index]
                                    if job.requests[index] != expected_request:
                                        current = False
                                        break
                                    pair = evidence.get(index)
                                    receipt = self._records.get(index)
                                    if state == "completed":
                                        if (pair is None or receipt is None
                                                or receipt.registration_state != "registered"
                                                or receipt.promotion_state != "protected_verified"
                                                or output_count <= 0
                                                or remote_count != output_count
                                                or registered_count != output_count
                                                or receipt.registered_count != output_count):
                                            current = False
                                            break
                                        admission_owner, observation = pair
                                        attempt = admission._attempts.get(index)
                                        if (admission_owner is not admission or attempt is None
                                                or attempt.status != "observed"
                                                or attempt.result is None
                                                or attempt.result.status != "evidence_observed"
                                                or attempt.result.observation is not observation
                                                or not self._protected_observation_is_owned(
                                                    admission, observation)
                                                or not self._protected_save_event_current(
                                                    index, job, inbox, observation,
                                                    self._protected_settled_event_evidence.get(index))):
                                            current = False
                                            break
                                        remote = observation._remote_receipt
                                        promotion = observation._promotion_receipt
                                        if (remote.request_index != index
                                                or promotion.request_index != index
                                                or remote.request_id != request.request_id
                                                or promotion.request_id != request.request_id
                                                or remote.workflow_identity != request.workflow_identity
                                                or promotion.workflow_identity != request.workflow_identity
                                                or len(remote.images) != output_count
                                                or len(promotion.images) != output_count
                                                or tuple(row.descriptor_identity for row in promotion.images)
                                                    != tuple(item.identity for item in remote.images)):
                                            current = False
                                            break
                                    elif (output_count != 0 or remote_count != 0 or registered_count != 0
                                            or pair is not None or receipt is not None):
                                        # A failed zero-output request is settled;
                                        # any output without a complete registered
                                        # receipt is an incomplete publication.
                                        current = False
                                        break
                                    elif any(event.progress.request_index == index
                                             and event.progress.kind in {
                                                 "remote_outputs_ready", "outputs_ready"}
                                             for event in inbox._events.values()):
                                        current = False
                                        break
                                    elif any(getattr(getattr(event, "progress", None), "request_index", None) == index
                                             and getattr(getattr(event, "progress", None), "kind", None)
                                                 in {"remote_outputs_ready", "outputs_ready"}
                                             for event in inbox._late):
                                        current = False
                                        break
                if current:
                    try:
                        current = (self._origin.project in allowed_project_states
                                   and self._protected_candidate_records_current(evidence))
                    except Exception:
                        current = False
                yield bool(current)

    def _protected_save_freshness(self, envelope, remote, evidence, *, allowed_project_states=None):
        if envelope is not self._envelope:
            return False
        index = getattr(remote, "request_index", -1)
        pair = evidence.get(index)
        if pair is None or pair[1]._remote_receipt is not remote:
            return False
        with self._protected_save_authority(
                evidence, allowed_project_states=allowed_project_states) as current:
            return current

    def _protected_save_readiness(self):
        snapshot = self._runtime.generation_jobs.snapshot(self._envelope.job_id)
        rows = snapshot.get("requests") if type(snapshot) is dict else None
        if (snapshot.get("state") not in {"completed", "partially_failed"}
                or type(rows) is not list or len(rows) != len(self._envelope.manifest.requests)):
            return "registration_incomplete"
        if any(receipt.registration_state == "registration_uncertain"
               for receipt in self._records.values()):
            return "registration_uncertain"
        for index, row in enumerate(rows):
            receipt = self._records.get(index)
            pair = self._protected_evidence.get(index)
            if row.get("state") == "completed":
                if (pair is None or receipt is None
                        or index not in self._protected_settled_event_evidence):
                    return "registration_evidence_missing"
                if (receipt.registration_state != "registered"
                        or receipt.promotion_state != "protected_verified"
                        or receipt.registered_count != row.get("output_count")
                        or row.get("registered_count") != row.get("output_count")
                        or row.get("remote_output_count") != row.get("output_count")):
                    return "registration_incomplete"
            elif (row.get("state") == "failed" and row.get("output_count") == 0
                    and row.get("remote_output_count") == 0
                    and row.get("registered_count") == 0 and pair is None and receipt is None):
                continue
            elif receipt is not None and receipt.registration_state == "registration_uncertain":
                return "registration_uncertain"
            else:
                return "registration_incomplete"
        if any(index < 0 or index >= len(rows) for index in self._records):
            return "registration_evidence_conflict"
        if any(index < 0 or index >= len(rows) for index in self._protected_evidence):
            return "registration_evidence_conflict"
        return None

    def save_for_characterization(self):
        if self._mode == "profile_a_protected":
            return "save_not_authorized"
        if self._mode == "protected":
            return self._save_protected_for_characterization()
        with self._lock:
            if self._save_state != "not_attempted":
                return self._save_state
            if self._busy:
                return "publication_busy"
            snapshot = self._runtime.generation_jobs.snapshot(self._envelope.job_id)
            if snapshot.get("state") not in {"completed", "partially_failed"}:
                return "registration_incomplete"
            if any(row["registered_count"] != (self._records[index].registered_count
                    if index in self._records else 0)
                    for index, row in enumerate(snapshot.get("requests", []))):
                return "registration_evidence_missing"
            if any(r.registration_state == "registration_uncertain" for r in self._records.values()):
                return "registration_uncertain"
            self._busy = True
            self._save_state = "saving"  # one-shot, no automatic retry
        outcome = "save_not_authorized"
        attempted = False
        try:
            # Rehash all durable references before attempting persistence.
            for attempt in self._assets._attempts.values():
                if type(attempt) is tuple:
                    self._assets.revalidate_for_characterization(attempt)
            # The established save owner normalizes Modules/attributes/Candidates
            # in place. Characterize those exact changes on a detached clone;
            # do not mistake this legacy normalization for source drift.
            saved_source = copy.deepcopy(self._expected)
            _project_to_serializable_data(saved_source, self._origin.path)
            with self._authority() as current:
                if not current:
                    return outcome
            # Exact captured object/path callback, outside every owner lock.
            try:
                attempted = True
                result = self._save(self._origin.project, self._origin.path,
                                    "Agent generation Candidates registered")
                outcome = "saved" if result is True else "save_failed" if result is False else "save_uncertain"
            except Exception:
                outcome = "save_uncertain"
            self._save_callback_outcome = outcome
            with self._authority(source=False) as current:
                current = current and self._origin.project in (self._expected, saved_source)
                if not current:
                    # A switched/closed host cannot attest its final persistence
                    # state. Preserve actual callback evidence privately.
                    outcome = "save_uncertain"
                else:
                    status = self._runtime.generation_jobs.save_for_characterization(
                        self._envelope.job_id, self._envelope.claim_id,
                        binding=self._envelope.binding, outcome=outcome)
                    if status != "accepted":
                        outcome = "save_uncertain"
            return outcome
        except Exception:
            outcome = "save_uncertain" if attempted else "save_not_authorized"
            return outcome
        finally:
            with self._lock:
                self._save_state, self._busy = outcome, False

    def _save_protected_for_characterization(self):
        with self._lock:
            if self._save_state != "not_attempted":
                return self._save_state
            if self._busy:
                return "publication_busy"
            refusal = self._protected_save_readiness()
            if refusal is not None:
                return refusal
            evidence = dict(self._protected_evidence)
            self._busy = True
            self._save_state = "saving"

        outcome = "save_not_authorized"
        attempted = False
        lease_tokens = []
        try:
            # The exact protected owner rechecks accepted staging and promoted
            # files through the save-time host guard. Admission's earlier
            # guard is deliberately not reused because requests are registered.
            for admission_owner, observation in evidence.values():
                if not self._protected_observation_is_owned(admission_owner, observation):
                    raise ValueError("protected_admission_unavailable")
                promotion_owner = observation._promotion_owner
                if (promotion_owner._inspect_for_project_save_for_characterization(
                        observation._promotion_receipt,
                        lambda envelope, remote: self._protected_save_freshness(
                            envelope, remote, evidence))
                        is not observation._promotion_receipt):
                    raise ValueError("protected_promotion_unavailable")

            # A separate one-shot revocation lease fences owner close while the
            # callback runs. It holds no protected/native/job/inbox lock.
            seen_owners = set()
            for _admission, observation in evidence.values():
                owner = observation._promotion_owner
                if owner in seen_owners:
                    continue
                token = owner.begin_project_save_for_characterization(
                    observation._promotion_receipt)
                seen_owners.add(owner)
                lease_tokens.append((owner, token))

            # Recheck every native file after acquiring all close leases.
            for _admission, observation in evidence.values():
                owner = observation._promotion_owner
                if (owner._inspect_for_project_save_for_characterization(
                        observation._promotion_receipt,
                        lambda envelope, remote: self._protected_save_freshness(
                            envelope, remote, evidence))
                        is not observation._promotion_receipt):
                    raise ValueError("protected_promotion_unavailable")

            # The established serializer normalizes Modules, attributes and
            # Candidate records in place. Compute the exact permitted result
            # on a detached clone before the callback.
            saved_source = copy.deepcopy(self._expected)
            _project_to_serializable_data(saved_source, self._origin.path)
            with self._protected_save_authority(evidence) as current:
                if not current:
                    return outcome

            try:
                attempted = True
                result = self._save(self._origin.project, self._origin.path,
                                    "Agent generation Candidates registered")
                outcome = "saved" if result is True else "save_failed" if result is False else "save_uncertain"
            except Exception:
                outcome = "save_uncertain"
            self._save_callback_outcome = outcome

            # Revalidate native bytes, ACLs, identities and every registration
            # after a possible write. A lost owner or host makes the disk result
            # uncertain; retained files and JSON are never rolled back.
            try:
                allowed_states = (self._expected, saved_source)
                for _admission, observation in evidence.values():
                    owner = observation._promotion_owner
                    if (owner._inspect_for_project_save_for_characterization(
                            observation._promotion_receipt,
                            lambda envelope, remote: self._protected_save_freshness(
                                envelope, remote, evidence, allowed_project_states=allowed_states))
                            is not observation._promotion_receipt):
                        raise ValueError("protected_promotion_unavailable")
                with self._protected_save_authority(
                        evidence, allowed_project_states=allowed_states) as current:
                    if not current:
                        outcome = "save_uncertain"
                    else:
                        status = self._runtime.generation_jobs.save_for_characterization(
                            self._envelope.job_id, self._envelope.claim_id,
                            binding=self._envelope.binding, outcome=outcome)
                        if status != "accepted":
                            outcome = "save_uncertain"
            except Exception:
                outcome = "save_uncertain"
            return outcome
        except Exception:
            outcome = "save_uncertain" if attempted else "save_not_authorized"
            return outcome
        finally:
            for owner, token in reversed(lease_tokens):
                owner.finish_project_save_for_characterization(token)
            with self._lock:
                self._save_state, self._busy = outcome, False


_FACTORY = object()


def _path_is_within_approved_destination(path, approved_directory, *, strict=False):
    """Compare canonical absolute Windows paths without accepting prefixes."""
    try:
        candidate = os.path.normcase(os.path.abspath(os.fspath(path)))
        approved = os.path.normcase(os.path.abspath(os.fspath(approved_directory)))
        if not Path(candidate).is_absolute() or not Path(approved).is_absolute():
            return False
        common = os.path.normcase(os.path.commonpath((candidate, approved)))
        return common == approved and (not strict or candidate != approved)
    except (OSError, TypeError, ValueError):
        return False
