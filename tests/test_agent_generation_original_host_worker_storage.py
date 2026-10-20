"""C2B-8D-19B worker/storage association; offline characterization only."""

import threading
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.comfy_http_history import PromptHTTPHistoryTransport
from core.comfy_http_submission import PromptHTTPSubmissionTransport
from core.comfy_prompt_request import prepare_frozen_prompt_request
from core.generation_storage_admission import WindowsProtectedStorageAdmissionCharacterization
from core.generation_windows_protected_storage import (
    WindowsProjectJsonReferenceCharacterization, WindowsProtectedRootCharacterization,
)
from ui.agent_generation_http_io_worker import HTTPIOCorrelation, HostOwnedHTTPIOWorker
from ui.agent_generation_original_host_worker_storage import (
    OriginalHostWorkerStorageIntegration,
)
from test_agent_generation_executor_handoff import ready, start


_PURPOSES = (
    "private_journal", "temporary_containment", "retained_uncertain",
    "promoted_assets", "selected_project_json",
)
_PROFILE_A_PURPOSES = _PURPOSES[:-1]


class _Response:
    def __init__(self, body, status=200):
        self.status = status
        self._body = body
        self._read = False
        self.closed = False
        self.finished = False

    def read(self, _size, _timeout):
        if self._read:
            return b""
        self._read = True
        return self._body

    def finish(self):
        self.finished = True

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self, *, prompt_id=None, entered=None, release=None, on_post=None):
        self.prompt_id = prompt_id
        self.entered = entered
        self.release = release
        self.on_post = on_post
        self.closed = False

    def connect(self):
        return None

    def post_prompt(self, _body, _timeout):
        if self.on_post is not None:
            self.on_post()
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(3)
        return _Response((f'{{"prompt_id":"{self.prompt_id}"}}').encode("ascii"))

    def get_history(self, _prompt_id, _timeout):
        return _Response(b"{}")

    def close(self):
        self.closed = True


def _worker(*, prompt_id=None, entered=None, release=None, on_post=None):
    def factory(_origin, _timeout):
        return _Connection(
            prompt_id=prompt_id, entered=entered, release=release, on_post=on_post,
        )

    submission = PromptHTTPSubmissionTransport(
        wire_factory=factory, characterization=True,
    )
    history = PromptHTTPHistoryTransport(
        wire_factory=factory, characterization=True,
    )
    return HostOwnedHTTPIOWorker(
        submission, history, characterization=True, wait_timeout_seconds=5,
        join_timeout_seconds=0.05,
    )


def _storage_refs():
    roots = {}
    for purpose in _PURPOSES:
        root = object.__new__(WindowsProtectedRootCharacterization)
        root._purpose = purpose
        root._closed = False
        roots[purpose] = root
    capacity = object.__new__(WindowsProtectedStorageAdmissionCharacterization)
    capacity._closed = False
    capacity._invalid = False
    capacity._roots = dict(roots)
    return roots, capacity


def _host_lifecycle():
    values = ready()
    runtime, route, state, *_ = values
    assert start(values).status == "characterized_acceptance"
    assert runtime.opt_in_generation_original_host_lifecycle_for_characterization(
        state["project"], state["current_project_path"],
    ) == "bound_non_executing"
    lifecycle = runtime._generation_original_host_lifecycle
    return values, runtime, route, state, lifecycle


def _bound_claim(*, prompt_id=None, entered=None, release=None):
    values, runtime, route, state, lifecycle = _host_lifecycle()
    roots, capacity = _storage_refs()
    worker = _worker(prompt_id=prompt_id, entered=entered, release=release)
    assert runtime.bind_generation_worker_storage_for_characterization(
        worker, roots, capacity,
    ) == "bound_non_executing"
    return values, runtime, route, state, lifecycle, roots, capacity, worker


def _profile_a_storage_refs(project_path):
    roots = {}
    for index, purpose in enumerate(_PROFILE_A_PURPOSES):
        root = object.__new__(WindowsProtectedRootCharacterization)
        root._purpose = purpose
        root._closed = False
        roots[purpose] = root
    capacity = object.__new__(WindowsProtectedStorageAdmissionCharacterization)
    capacity._profile_a_root_set = True
    capacity._closed = False
    capacity._invalid = False
    capacity._roots = dict(roots)
    capacity._scope_lease = SimpleNamespace(_state="held")
    capacity._lock = threading.RLock()
    capacity._host_lifecycle_refs = []
    capacity._ledger = SimpleNamespace(
        _lock=threading.RLock(), _operations={}, _active_write=None,
        _uncertain={purpose: [0, 0] for purpose in _PROFILE_A_PURPOSES},
        close=lambda: None,
    )
    capacity.readiness = lambda: {
        "status": "characterization_only" if not capacity._closed else "unavailable",
        "root_set_contract": "profile_a_four_writable_roots",
        "scope_writer_lease": "held" if capacity._scope_lease._state == "held" else "released",
        "execution_available": False, "protected_storage_available": False,
        "promotion_available": False, "authorship": "unverified",
    }
    capacity.release_scope_writer_lease_if_settled_for_characterization = lambda: "retained_for_active_host"
    reference = object.__new__(WindowsProjectJsonReferenceCharacterization)
    reference._closed = False
    reference._path = Path(project_path)
    reference.readiness = lambda: {
        "status": "read_only_reference_observed" if not reference._closed else "closed",
        "read_access_only": True,
        "protected_root_acl_required": False,
        "project_save_allowed": False,
        "authorship": "unverified",
    }
    return roots, capacity, reference


def _profile_a_bound_claim(*, prompt_id=None):
    values, runtime, route, state, lifecycle = _host_lifecycle()
    roots, capacity, reference = _profile_a_storage_refs(lifecycle._project_path)
    assert runtime.bind_generation_profile_a_storage_for_characterization(
        capacity, reference,
    ) == "matched_reference_only"
    worker = _worker(prompt_id=prompt_id)
    return values, runtime, route, state, lifecycle, roots, capacity, reference, worker


def _ready_generation_at_project_path(project_path):
    from core import agent_facade
    from ui.agent_generation_executor_handoff import (
        capture_executor_human_start_for_characterization, handoff_generation_for_characterization,
    )
    from ui.agent_generation_executable_confirmation import (
        confirm_session_execution_details, prepare_session_executable_review,
    )
    from ui.agent_generation_executor_inbox import GenerationExecutorInbox
    from ui.agent_generation_job import GenerationJobRegistry
    from test_agent_generation_executable_manifest import host_for
    from test_agent_generation_review_custody import send, setup
    from test_agent_generation_preview import line

    runtime, route, _epoch, state, _args = setup()
    state["current_project_path"] = str(project_path)
    state["project"].prompt_lines = [
        line("scene", "Scene", line_type="separator"),
        line("illustration-001", "portable prompt"),
    ]
    runtime.generation_jobs = GenerationJobRegistry(characterization=True)
    runtime._generation_executor_inbox = GenerationExecutorInbox(characterization=True)
    epoch = runtime.synchronize_target(state["project"], state["current_project_path"])
    provider = host_for()
    binding = [
        agent_facade.candidate_observation_handles.project_identity(state["project"]),
        runtime._registration.route_id,
        state["current_project_path"],
        route._pairing_generation,
        epoch,
    ]
    preview = agent_facade.preview_generation(
        state["project"], "scene", run_count=1,
        host_context_provider=provider, observation_binding=binding,
    )
    args = {"scene_id": "scene", "run_count": 1, "expected_plan_id": preview["plan_id"]}
    assert send(runtime, route, epoch, state, args, provider=provider) == "completed"
    route.consume_reply(epoch)
    pending = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    assert prepare_session_executable_review(
        state, runtime, provider, pending["proposal_id"], pending["plan_id"],
        random_u64=lambda: 0,
    ) == "certified"
    held = runtime._executable_review
    assert confirm_session_execution_details(state, runtime, provider, held) == "confirmed"
    action = capture_executor_human_start_for_characterization(runtime)
    start = handoff_generation_for_characterization(
        state, runtime, provider, action,
        fake_worker=lambda offer: runtime._generation_executor_inbox.accept_for_characterization(
            runtime.generation_jobs, offer,
        )[0],
    )
    assert start.status == "characterized_acceptance"
    assert runtime.opt_in_generation_original_host_lifecycle_for_characterization(
        state["project"], state["current_project_path"],
    ) == "bound_non_executing"
    lifecycle = runtime._generation_original_host_lifecycle
    return runtime, route, state, lifecycle


@pytest.fixture
def native_profile_a_worker_storage(tmp_path):
    import sys

    from core import generation_windows_protected_storage as windows

    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    api = windows._api()
    user = windows._current_user(api)
    scope = tmp_path / "worker-profile-a-scope"
    api[2].CreateDirectory(str(scope), windows._security_attributes(api, user))
    roots = {}
    owner = reference = None
    try:
        for purpose in _PROFILE_A_PURPOSES:
            path = scope / purpose
            api[2].CreateDirectory(str(path), windows._security_attributes(api, user))
            roots[purpose] = windows.WindowsProtectedRootCharacterization.capture_for_characterization(
                str(scope), str(path), purpose,
                characterization=True, disposable_opt_in=True,
            )
        project_path = tmp_path / "ordinary-selected-project.json"
        project_path.write_text('{"disposable":true}', encoding="utf-8")
        reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
            str(project_path), characterization=True, disposable_opt_in=True,
        )
        owner = WindowsProtectedStorageAdmissionCharacterization.capture_profile_a_root_set_for_characterization(
            str(scope), roots, characterization=True, disposable_opt_in=True,
        )
        yield roots, owner, reference, project_path
    finally:
        if owner is not None:
            owner.close()
        if reference is not None:
            reference.close()
        for root in roots.values():
            root.close()


def _prepared(lifecycle, index=0):
    request = lifecycle._envelope.manifest.requests[index]
    return prepare_frozen_prompt_request(
        lifecycle._envelope.manifest, request, client_id=str(uuid.uuid4()),
    )


def test_exact_owner_binding_same_target_rerun_submission_history_and_no_job_progress():
    prompt_id = str(uuid.uuid4())
    values, runtime, _route, state, lifecycle, roots, capacity, worker = _bound_claim(
        prompt_id=prompt_id,
    )
    integration = lifecycle._worker_storage_integration
    assert type(integration) is OriginalHostWorkerStorageIntegration
    assert worker.observation_for_characterization().state == "created"
    assert integration._purpose_roots is not roots
    assert all(integration._purpose_roots[p] is roots[p] for p in _PURPOSES)
    before_job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    before_envelope = runtime._generation_executor_inbox._envelope
    before_inbox_state = runtime._generation_executor_inbox._state

    assert runtime.synchronize_target(state["project"], state["current_project_path"])
    assert runtime._generation_original_host_lifecycle is lifecycle
    assert lifecycle._worker_storage_integration is integration
    assert runtime.inspect_generation_worker_storage_for_characterization().protected_binding == "matched_reference_only"

    prepared = _prepared(lifecycle)
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    assert correlation is not None and correlation.prompt_id is None
    # Once bound, an unregistered caller cannot start transport work, even
    # though the Worker itself may be started by the explicit host harness.
    assert worker.start_for_characterization().state == "running"
    refused = worker.perform_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert refused.outcome.status == "unknown"
    assert worker.observation_for_characterization().accepted_operations == 0
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert status == "admitted_non_executing"
    completion = worker.perform_for_characterization("submission", prepared, None, correlation)
    assert completion.outcome.status == "accepted"
    foreign = replace(completion, correlation=replace(correlation, attempt_id=2))
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, foreign,
    ) == "foreign_non_authoritative"
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "observed_non_authoritative"

    history_correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="history", prompt_id=prompt_id,
    )
    assert history_correlation is not None
    assert runtime.generation_worker_http_correlation_for_characterization(
        0, kind="history", prompt_id=str(uuid.uuid4()),
    ) is None
    history_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "history", prepared, prompt_id, history_correlation,
    )
    assert status == "admitted_non_executing"
    history_completion = worker.perform_for_characterization(
        "history", prepared, prompt_id, history_correlation,
    )
    assert history_completion.outcome.status == "pending"
    assert runtime.observe_generation_worker_http_result_for_characterization(
        history_lease, history_completion,
    ) == "observed_non_authoritative"
    assert runtime.observe_generation_worker_http_result_for_characterization(
        history_lease, history_completion,
    ) == "duplicate_non_authoritative"
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) == before_job
    assert runtime._generation_executor_inbox._envelope is before_envelope
    assert runtime._generation_executor_inbox._state == before_inbox_state
    assert runtime.inspect_generation_worker_storage_for_characterization().execution_available is False
    assert not lifecycle.execution_available and not integration.protected_storage_available
    assert not integration.promotion_available and not integration.candidate_publication_allowed
    assert not integration.project_save_allowed and integration.authorship == "unverified"
    runtime.close()
    assert roots["private_journal"]._closed is False
    assert capacity._closed is False


def test_profile_a_worker_storage_uses_exact_four_roots_and_bound_project_reference():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert set(roots) == set(_PROFILE_A_PURPOSES)
    assert lifecycle._profile_a_storage_binding == (capacity, reference)
    assert capacity._host_lifecycle_refs == [lifecycle]

    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    integration = lifecycle._worker_storage_integration
    assert integration is not None and integration._profile_a is True
    assert set(integration._purpose_roots) == set(_PROFILE_A_PURPOSES)
    assert integration._project_reference is reference
    assert all(integration._purpose_roots[purpose] is roots[purpose]
               for purpose in _PROFILE_A_PURPOSES)
    assert integration.readiness().protected_binding == "matched_profile_a_reference_only"
    assert worker.observation_for_characterization().state == "created"

    # A same-target rerun keeps this exact association and the normal HTTP
    # correlation remains observational; no protected writer or job event is called.
    assert runtime.synchronize_target(state["project"], state["current_project_path"])
    assert lifecycle._worker_storage_integration is integration
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", _prepared(lifecycle), None, correlation,
    )
    assert status == "admitted_non_executing"
    assert worker.start_for_characterization().state == "running"
    completion = worker.perform_for_characterization(
        "submission", _prepared(lifecycle), None, correlation,
    )
    assert completion.outcome.status == "accepted"
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "observed_non_authoritative"
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["registered_count"] == 0
    assert not integration.execution_available
    assert not integration.protected_storage_available
    assert not integration.promotion_available
    assert not integration.candidate_publication_allowed
    assert not integration.project_save_allowed
    assert integration.authorship == "unverified"
    runtime.close()
    assert capacity._closed is False
    assert all(root._closed is False for root in roots.values())


def test_profile_a_worker_storage_binds_real_native_roots_and_project_reference(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _route, _state, lifecycle = _ready_generation_at_project_path(project_path)
    worker = _worker(prompt_id=str(uuid.uuid4()))
    try:
        assert runtime.bind_generation_profile_a_storage_for_characterization(
            capacity, reference,
        ) == "matched_reference_only"
        assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
            worker, roots, capacity, reference,
        ) == "bound_non_executing"
        integration = lifecycle._worker_storage_integration
        assert integration is not None
        assert integration._profile_a is True
        assert integration.readiness().protected_binding == "matched_profile_a_reference_only"
        assert worker.observation_for_characterization().state == "created"
        assert capacity._closed is False and reference._closed is False
        assert project_path.read_text(encoding="utf-8") == '{"disposable":true}'
        assert not integration.execution_available
        assert not integration.protected_storage_available
        assert not integration.promotion_available
        assert not integration.candidate_publication_allowed
        assert not integration.project_save_allowed
        assert integration.authorship == "unverified"
    finally:
        runtime.close()


@pytest.mark.parametrize("mismatch", [
    "wrong_root", "wrong_owner", "wrong_reference", "closed_reference",
    "wrong_project_path", "revoked_scope_lease", "retired_lifecycle",
])
def test_profile_a_worker_binding_rejects_changed_or_unbound_references(mismatch):
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim()
    if mismatch == "wrong_root":
        replacement = object.__new__(WindowsProtectedRootCharacterization)
        replacement._purpose, replacement._closed = "promoted_assets", False
        roots["promoted_assets"] = replacement
    elif mismatch == "wrong_owner":
        _other_roots, capacity, _other_reference = _profile_a_storage_refs(lifecycle._project_path)
    elif mismatch == "wrong_reference":
        _other_roots, _other_capacity, reference = _profile_a_storage_refs(lifecycle._project_path)
    elif mismatch == "closed_reference":
        reference._closed = True
    elif mismatch == "wrong_project_path":
        reference._path = Path("OTHER_PROJECT.json")
    elif mismatch == "revoked_scope_lease":
        capacity._scope_lease._state = "released"
    elif mismatch == "retired_lifecycle":
        runtime.synchronize_target(type(state["project"])(project_metadata={"name": "replacement"}),
                                  r"C:\PG\replacement.json")

    result = runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    )
    assert result != "bound_non_executing"
    assert lifecycle._worker_storage_integration is None
    assert worker._characterization_owner_claim is None
    runtime.close()


@pytest.mark.parametrize("drift", [
    "root_replaced", "capacity_closed", "scope_lease_revoked",
    "reference_closed", "profile_binding_removed", "project_switch",
])
def test_profile_a_drift_fences_correlation_and_retains_inflight_result(drift):
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    prepared = _prepared(lifecycle)
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    assert correlation is not None
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert status == "admitted_non_executing"
    assert worker.start_for_characterization().state == "running"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert completion.outcome.status == "accepted"

    if drift == "root_replaced":
        replacement = object.__new__(WindowsProtectedRootCharacterization)
        replacement._purpose, replacement._closed = "promoted_assets", False
        capacity._roots["promoted_assets"] = replacement
    elif drift == "capacity_closed":
        with capacity._lock:
            capacity._closed = True
    elif drift == "scope_lease_revoked":
        capacity._scope_lease._state = "released"
    elif drift == "reference_closed":
        reference._closed = True
    elif drift == "profile_binding_removed":
        with lifecycle._lock:
            lifecycle._profile_a_storage_binding = None
    elif drift == "project_switch":
        runtime.synchronize_target(
            type(state["project"])(project_metadata={"name": "replacement"}),
            r"C:\PG\replacement.json",
        )

    assert runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    ) is None
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "stale_non_authoritative"
    integration = lifecycle._worker_storage_integration
    assert integration is not None
    assert integration.readiness().retained_uncertain_operations == 1
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["registered_count"] == 0
    assert not integration.execution_available
    assert not integration.protected_storage_available
    assert integration.authorship == "unverified"
    runtime.close()


def test_profile_a_native_readiness_runs_outside_all_host_locks(monkeypatch):
    (_values, runtime, _route, _state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim()
    observed = []

    def assert_host_locks_released():
        try:
            publication_owned = getattr(runtime._publication_gate, "_is_owned", lambda: False)()
            assert publication_owned is False
            publication_acquired = runtime._publication_gate.acquire(blocking=False)
            assert publication_acquired
            runtime._publication_gate.release()
            for lock in (runtime.target_tracker._lock, runtime.generation_jobs._lock,
                         runtime._generation_executor_inbox._lock, lifecycle._lock):
                assert getattr(lock, "_is_owned", lambda: False)() is False
                acquired = lock.acquire(blocking=False)
                assert acquired
                lock.release()
        except Exception as exc:
            observed.append(repr(exc))
            raise
        observed.append(True)

    def capacity_readiness():
        assert_host_locks_released()
        return {"status": "characterization_only",
                "root_set_contract": "profile_a_four_writable_roots",
                "scope_writer_lease": "held"}

    def project_readiness():
        assert_host_locks_released()
        return {"status": "read_only_reference_observed"}

    monkeypatch.setattr(capacity, "readiness", capacity_readiness)
    monkeypatch.setattr(reference, "readiness", project_readiness)
    bind_result = runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    )
    assert bind_result == "bound_non_executing", (bind_result, observed)
    assert len(observed) == 2
    runtime.close()


def test_profile_a_capacity_close_during_native_observation_prevents_worker_claim(monkeypatch):
    (_values, runtime, _route, _state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim()
    entered, release = threading.Event(), threading.Event()
    result = []

    def blocked_readiness():
        entered.set()
        assert release.wait(3)
        return {"status": "unavailable", "root_set_contract": "profile_a_four_writable_roots",
                "scope_writer_lease": "held"}

    monkeypatch.setattr(capacity, "readiness", blocked_readiness)
    binder = threading.Thread(target=lambda: result.append(
        runtime.bind_generation_profile_a_worker_storage_for_characterization(
            worker, roots, capacity, reference,
        ),
    ))
    binder.start()
    try:
        assert entered.wait(3)
        with capacity._lock:
            capacity._closed = True
            capacity._scope_lease._state = "closed"
    finally:
        release.set()
        binder.join(3)
    assert not binder.is_alive()
    assert result == ["storage_observation_unavailable"]
    assert lifecycle._worker_storage_integration is None
    assert worker._characterization_owner_claim is None
    runtime.close()


def test_profile_a_capacity_close_serializes_with_worker_claim_and_fences_later_correlation():
    (_values, runtime, _route, _state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim()
    claim_entered, release_claim = threading.Event(), threading.Event()
    close_attempted, close_done = threading.Event(), threading.Event()
    bind_result, close_result = [], []
    original_claim = worker._claim_original_host_for_characterization

    def blocked_claim(owner_claim):
        claim_entered.set()
        assert release_claim.wait(3)
        return original_claim(owner_claim)

    def close_capacity():
        close_attempted.set()
        with capacity._lock:
            capacity._closed = True
            capacity._scope_lease._state = "closed"
        close_done.set()

    worker._claim_original_host_for_characterization = blocked_claim
    capacity.close = close_capacity
    binder = threading.Thread(target=lambda: bind_result.append(
        runtime.bind_generation_profile_a_worker_storage_for_characterization(
            worker, roots, capacity, reference,
        ),
    ))
    binder.start()
    try:
        assert claim_entered.wait(3)
        closer = threading.Thread(target=lambda: close_result.append(capacity.close()))
        closer.start()
        assert close_attempted.wait(3)
        assert not close_done.is_set()
    finally:
        release_claim.set()
        binder.join(3)
        if "closer" in locals():
            closer.join(3)
    assert not binder.is_alive()
    assert "closer" not in locals() or not closer.is_alive()
    assert bind_result == ["bound_non_executing"]
    assert close_done.is_set()
    assert runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    ) is None
    assert worker.observation_for_characterization().state == "closed"
    assert lifecycle._worker_storage_integration is not None
    runtime.close()


@pytest.mark.parametrize("invalidation", ["claim", "project_switch"])
def test_profile_a_host_invalidation_during_native_readiness_refuses_worker_binding(
        monkeypatch, invalidation):
    (_values, runtime, _route, _state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim()
    entered, release = threading.Event(), threading.Event()
    result = []
    actual_readiness = capacity.readiness

    def blocked_readiness():
        entered.set()
        assert release.wait(3)
        return actual_readiness()

    monkeypatch.setattr(capacity, "readiness", blocked_readiness)
    binder = threading.Thread(target=lambda: result.append(
        runtime.bind_generation_profile_a_worker_storage_for_characterization(
            worker, roots, capacity, reference,
        ),
    ))
    binder.start()
    try:
        assert entered.wait(3)
        if invalidation == "claim":
            runtime.generation_jobs.invalidate_execution_custody()
        else:
            runtime.synchronize_target(
                type(_state["project"])(project_metadata={"name": "replacement"}),
                r"C:\PG\replacement.json",
            )
    finally:
        release.set()
        binder.join(3)
    assert not binder.is_alive()
    assert result[0] in {"host_evidence_unavailable", "stale_host_binding"}
    assert lifecycle._worker_storage_integration is None
    assert worker._characterization_owner_claim is None
    assert capacity._closed is False
    runtime.close()


@pytest.mark.parametrize("bad_binding", ["wrong_root", "wrong_capacity", "worker_used"])
def test_binding_rejects_wrong_or_already_used_owner_without_starting_another_worker(bad_binding):
    values = ready()
    runtime, _route, state, *_ = values
    assert start(values).status == "characterized_acceptance"
    assert runtime.opt_in_generation_original_host_lifecycle_for_characterization(
        state["project"], state["current_project_path"],
    ) == "bound_non_executing"
    roots, capacity = _storage_refs()
    worker = _worker(prompt_id=str(uuid.uuid4()))
    if bad_binding == "wrong_root":
        replacement = object.__new__(WindowsProtectedRootCharacterization)
        replacement._purpose, replacement._closed = "promoted_assets", False
        roots["promoted_assets"] = replacement
    elif bad_binding == "wrong_capacity":
        capacity._roots["promoted_assets"] = object()
    else:
        assert worker.start_for_characterization().state == "running"
        # A Worker with accepted work is not a fresh host-owned dependency.
        request = runtime._generation_original_host_lifecycle._envelope.manifest.requests[0]
        lifecycle = runtime._generation_original_host_lifecycle
        prepared = prepare_frozen_prompt_request(
            lifecycle._envelope.manifest,
            request, client_id=str(uuid.uuid4()),
        )
        from ui.agent_generation_http_io_worker import HTTPIOCorrelation
        correlation = HTTPIOCorrelation(
            uuid.uuid4().hex, lifecycle._job_id, lifecycle._claim_id,
            lifecycle._manifest_identity, lifecycle._session_incarnation,
            lifecycle._process_incarnation, prepared.request_id, 0,
            request.illustration_id, request.run_index, request.workflow_identity, 1,
        )
        assert worker.perform_for_characterization(
            "submission", prepared, None, correlation,
        ).outcome.status == "accepted"
    assert runtime.bind_generation_worker_storage_for_characterization(
        worker, roots, capacity,
    ) != "bound_non_executing"
    assert runtime._generation_original_host_lifecycle._worker_storage_integration is None
    assert worker.observation_for_characterization().state in {"created", "running"}
    runtime.close()
    worker.close_for_characterization()


def test_one_worker_claim_is_exclusive_across_original_host_lifecycles_and_generations():
    values_a, runtime_a, _route_a, _state_a, lifecycle_a = _host_lifecycle()
    roots_a, capacity_a = _storage_refs()
    prompt_id = str(uuid.uuid4())
    worker = _worker(prompt_id=prompt_id)
    assert runtime_a.bind_generation_worker_storage_for_characterization(
        worker, roots_a, capacity_a,
    ) == "bound_non_executing"
    integration_a = lifecycle_a._worker_storage_integration
    assert worker._characterization_owner_claim is integration_a._worker_owner_claim

    _values_b, runtime_b, _route_b, _state_b, lifecycle_b = _host_lifecycle()
    roots_b, capacity_b = _storage_refs()
    assert runtime_b.bind_generation_worker_storage_for_characterization(
        worker, roots_b, capacity_b,
    ) == "worker_unavailable"
    assert lifecycle_b._worker_storage_integration is None
    assert lifecycle_a._worker_storage_integration is integration_a
    runtime_b.close()
    assert worker.observation_for_characterization().state == "created"
    assert integration_a.readiness().lifecycle_state == "bound_non_executing"

    prepared = _prepared(lifecycle_a)
    correlation = runtime_a.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    assert correlation is not None
    lease, status = runtime_a.begin_generation_worker_http_operation_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert status == "admitted_non_executing"
    assert worker.start_for_characterization().state == "running"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert completion.outcome.status == "accepted"
    assert runtime_a.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "observed_non_authoritative"

    runtime_a.close()
    closed = runtime_a.finish_generation_worker_storage_close_for_characterization()
    assert closed.lifecycle_state == "closed"
    assert worker.observation_for_characterization().state == "closed"
    _values_c, runtime_c, _route_c, _state_c, lifecycle_c = _host_lifecycle()
    roots_c, capacity_c = _storage_refs()
    assert runtime_c.bind_generation_worker_storage_for_characterization(
        worker, roots_c, capacity_c,
    ) == "worker_unavailable"
    assert lifecycle_c._worker_storage_integration is None
    runtime_c.close()


def test_two_concurrent_lifecycle_binds_have_exactly_one_worker_owner():
    _values_a, runtime_a, _route_a, _state_a, lifecycle_a = _host_lifecycle()
    _values_b, runtime_b, _route_b, _state_b, lifecycle_b = _host_lifecycle()
    roots_a, capacity_a = _storage_refs()
    roots_b, capacity_b = _storage_refs()
    worker = _worker(prompt_id=str(uuid.uuid4()))
    gate = threading.Barrier(3)
    outcomes = {}

    def bind(label, runtime, roots, capacity):
        gate.wait(timeout=3)
        outcomes[label] = runtime.bind_generation_worker_storage_for_characterization(
            worker, roots, capacity,
        )

    threads = [
        threading.Thread(target=bind, args=("a", runtime_a, roots_a, capacity_a)),
        threading.Thread(target=bind, args=("b", runtime_b, roots_b, capacity_b)),
    ]
    for thread in threads:
        thread.start()
    gate.wait(timeout=3)
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()

    assert sorted(outcomes.values()) == ["bound_non_executing", "worker_unavailable"]
    assert sum(lifecycle._worker_storage_integration is not None
               for lifecycle in (lifecycle_a, lifecycle_b)) == 1
    assert worker._characterization_owner_claim is not None
    runtime_a.close()
    runtime_b.close()
    assert worker.observation_for_characterization().state == "closed"


def test_worker_start_race_with_atomic_owner_claim_still_fences_unregistered_io():
    _values, runtime, _route, _state, lifecycle = _host_lifecycle()
    roots, capacity = _storage_refs()
    worker = _worker(prompt_id=str(uuid.uuid4()))
    gate = threading.Barrier(3)
    results = {}

    def start_worker():
        gate.wait(timeout=3)
        results["start"] = worker.start_for_characterization()

    def bind_worker():
        gate.wait(timeout=3)
        results["bind"] = runtime.bind_generation_worker_storage_for_characterization(
            worker, roots, capacity,
        )

    threads = [threading.Thread(target=start_worker), threading.Thread(target=bind_worker)]
    for thread in threads:
        thread.start()
    gate.wait(timeout=3)
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()

    assert results["start"].state == "running"
    assert results["bind"] == "bound_non_executing"
    assert lifecycle._worker_storage_integration is not None
    prepared = _prepared(lifecycle)
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    refusal = worker.perform_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert refusal.outcome.status == "unknown"
    assert worker.observation_for_characterization().accepted_operations == 0
    runtime.close()


def test_unowned_worker_admission_racing_bind_is_linearized_to_one_side():
    _values, runtime, _route, _state, lifecycle = _host_lifecycle()
    roots, capacity = _storage_refs()
    prompt_id = str(uuid.uuid4())
    worker = _worker(prompt_id=prompt_id)
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    request = lifecycle._envelope.manifest.requests[0]
    correlation = HTTPIOCorrelation(
        operation_id="pre-bind-attempt",
        job_id=lifecycle._envelope.job_id,
        claim_id=lifecycle._envelope.claim_id,
        manifest_identity=lifecycle._envelope.manifest.manifest_identity,
        session_identity=lifecycle._session_incarnation,
        process_identity=lifecycle._process_incarnation,
        request_id=request.request_id,
        request_index=request.request_index,
        illustration_id=request.illustration_id,
        run_index=request.run_index,
        workflow_identity=request.workflow_identity,
        attempt_id=1,
    )

    gate = threading.Barrier(3)
    results = {}

    def perform_unowned():
        gate.wait(timeout=3)
        results["perform"] = worker.perform_for_characterization(
            "submission", prepared, None, correlation,
        )

    def bind_owner():
        gate.wait(timeout=3)
        results["bind"] = runtime.bind_generation_worker_storage_for_characterization(
            worker, roots, capacity,
        )

    threads = [threading.Thread(target=perform_unowned), threading.Thread(target=bind_owner)]
    for thread in threads:
        thread.start()
    gate.wait(timeout=3)
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()

    if results["bind"] == "bound_non_executing":
        assert lifecycle._worker_storage_integration is not None
        assert results["perform"].outcome.status == "unknown"
        assert worker.observation_for_characterization().accepted_operations == 0
        runtime.close()
        closed = runtime.finish_generation_worker_storage_close_for_characterization()
        assert closed.lifecycle_state == "closed"
    else:
        assert results["bind"] == "worker_unavailable"
        assert lifecycle._worker_storage_integration is None
        assert results["perform"].outcome.status == "accepted"
        assert worker.observation_for_characterization().accepted_operations == 1
        runtime.close()
        assert worker.close_for_characterization().state == "closed"


def test_project_replacement_revokes_without_resurrection():
    values, runtime, route, state, lifecycle, roots, capacity, worker = _bound_claim(
        prompt_id=str(uuid.uuid4()),
    )
    integration = lifecycle._worker_storage_integration
    runtime.synchronize_target(type(state["project"])(project_metadata={"name": "replacement"}),
                              r"C:\PG\replacement.json")
    assert runtime._generation_original_host_lifecycle is not lifecycle
    assert integration.readiness().lifecycle_state == "closed"
    assert integration._purpose_roots["temporary_containment"] is roots["temporary_containment"]
    assert runtime._retired_generation_worker_storage_integrations == [integration]
    assert runtime.finish_generation_worker_storage_close_for_characterization().lifecycle_state == "closed"
    runtime.close()


@pytest.mark.parametrize("replacement", ["pairing", "claim"])
def test_pairing_or_live_claim_invalidation_fences_integrated_worker(replacement):
    _values, runtime, route, _state, lifecycle, roots, _capacity, worker = _bound_claim(
        prompt_id=str(uuid.uuid4()),
    )
    integration = lifecycle._worker_storage_integration
    if replacement == "pairing":
        assert route.release().status == "released"
    else:
        runtime.generation_jobs.invalidate_execution_custody()

    assert runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    ) is None
    assert runtime._generation_original_host_lifecycle is None
    assert lifecycle.readiness()["lifecycle_state"] == "closed"
    assert worker.observation_for_characterization().state == "closed"
    assert integration._purpose_roots["private_journal"] is roots["private_journal"]
    assert integration.readiness().execution_available is False
    runtime.close()


def test_capacity_owner_reference_drift_revokes_but_never_closes_roots():
    _values, runtime, _route, _state, lifecycle, roots, capacity, worker = _bound_claim(
        prompt_id=str(uuid.uuid4()),
    )
    integration = lifecycle._worker_storage_integration
    capacity._roots["promoted_assets"] = object()
    assert runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    ) is None
    assert integration.readiness().lifecycle_state == "closed"
    assert worker.observation_for_characterization().state == "closed"
    assert integration._purpose_roots["promoted_assets"] is roots["promoted_assets"]
    assert roots["promoted_assets"]._closed is False
    runtime.close()


def test_blocked_fake_worker_close_is_nonjoining_retains_roots_and_late_result_is_stale():
    entered, release = threading.Event(), threading.Event()
    values, runtime, _route, state, lifecycle, roots, capacity, worker = _bound_claim(
        prompt_id=str(uuid.uuid4()), entered=entered, release=release,
    )
    integration = lifecycle._worker_storage_integration
    prepared = _prepared(lifecycle)
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert status == "admitted_non_executing"
    assert worker.start_for_characterization().state == "running"
    result = []
    caller = threading.Thread(target=lambda: result.append(
        worker.perform_for_characterization("submission", prepared, None, correlation),
    ))
    try:
        caller.start()
        assert entered.wait(3)
        runtime.synchronize_target(type(state["project"])(project_metadata={"name": "next"}),
                                  r"C:\PG\next.json")
        observed = integration.readiness()
        assert observed.lifecycle_state == "uncertain"
        assert observed.retained_uncertain_operations == 1
        assert worker.observation_for_characterization().state == "close_pending"
        assert integration._purpose_roots["private_journal"] is roots["private_journal"]
        assert capacity._closed is False
        closing = runtime.finish_generation_worker_storage_close_for_characterization()
        assert closing.lifecycle_state == "close_pending"
        assert runtime.observe_generation_worker_http_result_for_characterization(
            lease, result[0] if result else None,
        ) == "stale_non_authoritative"
    finally:
        release.set()
        caller.join(3)
        assert not caller.is_alive()
        worker._thread.join(3)
        assert not worker._thread.is_alive()
    assert integration.observe_result_for_characterization(
        lease, result[0], worker.observation_for_characterization(), current=False,
    ) == "duplicate_non_authoritative"
    closed = runtime.finish_generation_worker_storage_close_for_characterization()
    assert closed.lifecycle_state == "uncertain"
    assert closed.retained_uncertain_operations == 1
    assert integration._purpose_roots["private_journal"] is roots["private_journal"]
    runtime.close()


def test_reentrant_runtime_close_from_fake_transport_does_not_join_worker_or_deadlock():
    entered, release = threading.Event(), threading.Event()
    returned = threading.Event()
    prompt_id = str(uuid.uuid4())
    values, runtime, _route, _state, lifecycle, roots, _capacity, worker = _bound_claim(
        prompt_id=prompt_id,
    )
    integration = lifecycle._worker_storage_integration

    def close_in_worker_callback():
        runtime.close()
        returned.set()

    def factory(_origin, _timeout):
        return _Connection(
            prompt_id=prompt_id, entered=entered, release=release,
            on_post=close_in_worker_callback,
        )

    worker._submission_transport._wire_factory = factory
    prepared = _prepared(lifecycle)
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert status == "admitted_non_executing"
    assert worker.start_for_characterization().state == "running"
    completion = []
    caller = threading.Thread(target=lambda: completion.append(
        worker.perform_for_characterization("submission", prepared, None, correlation),
    ))
    caller.start()
    try:
        assert entered.wait(3)
        assert returned.wait(3)
        assert runtime._closed is True
        assert integration.readiness().lifecycle_state == "uncertain"
        assert worker.observation_for_characterization().state == "close_pending"
        assert roots["private_journal"] is integration._purpose_roots["private_journal"]
        caller.join(3)
        assert not caller.is_alive()
        assert completion and completion[0].outcome.status == "unknown"
        assert runtime.observe_generation_worker_http_result_for_characterization(
            lease, completion[0],
        ) == "stale_non_authoritative"
    finally:
        release.set()
        caller.join(3)
        assert not caller.is_alive()
    closed = runtime.finish_generation_worker_storage_close_for_characterization()
    assert closed is not None
    assert closed.lifecycle_state == "uncertain"
    assert closed.retained_uncertain_operations == 1
