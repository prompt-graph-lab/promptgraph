"""C2B-8D-19B worker/storage association; offline characterization only."""

import copy
import json
import io
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.comfy_http_history import PromptHTTPHistoryTransport
from core.comfy_http_submission import PromptHTTPSubmissionTransport
from core.comfy_prompt_request import prepare_frozen_prompt_request
from core.generation_storage_admission import (
    CapacityEstimate, PROFILE_A_DUAL_CUSTODY_CAPACITY_POLICY,
    ProtectedStorageCapacityLimits,
    WindowsProtectedStorageAdmissionCharacterization, _CapacityLedger,
)
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
    def __init__(self, *, prompt_id=None, entered=None, release=None, on_post=None,
                 history_body_ref=None):
        self.prompt_id = prompt_id
        self.entered = entered
        self.release = release
        self.on_post = on_post
        self.history_body_ref = history_body_ref or [b"{}"]
        self.closed = False

    def connect(self):
        return None

    def post_prompt(self, _body, _timeout):
        if self.on_post is not None:
            self.on_post()
        if self.entered is not None:
            self.entered.set()
            assert self.release.wait(3)
        prompt_id = self.prompt_id() if callable(self.prompt_id) else self.prompt_id
        return _Response((f'{{"prompt_id":"{prompt_id}"}}').encode("ascii"))

    def get_history(self, _prompt_id, _timeout):
        return _Response(self.history_body_ref[0])

    def close(self):
        self.closed = True


def _worker(*, prompt_id=None, entered=None, release=None, on_post=None):
    history_body_ref = [b"{}"]

    def factory(_origin, _timeout):
        return _Connection(
            prompt_id=prompt_id, entered=entered, release=release, on_post=on_post,
            history_body_ref=history_body_ref,
        )

    submission = PromptHTTPSubmissionTransport(
        wire_factory=factory, characterization=True,
    )
    history = PromptHTTPHistoryTransport(
        wire_factory=factory, characterization=True,
    )
    worker = HostOwnedHTTPIOWorker(
        submission, history, characterization=True, wait_timeout_seconds=5,
        join_timeout_seconds=0.05,
    )
    # Tests may install bounded offline history bytes after the host request is
    # prepared but before the Worker performs its explicit history operation.
    worker._test_history_body_ref = history_body_ref
    return worker


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


def _configure_portable_profile_a_capacity(
        capacity, *, asset_bytes=16 * 1024, available_free_bytes=1024 * 1024):
    """Use the real ledger with filesystem refresh injected for portable tests."""
    ledger = _CapacityLedger(
        replace(
            ProtectedStorageCapacityLimits(),
            shared_temporary_and_promoted_bytes=asset_bytes,
            retained_uncertain_bytes=asset_bytes,
            shared_temporary_and_promoted_entries=16,
        ),
        owner_identity=capacity,
    )
    ledger.set_initial_inventory(
        {purpose: {} for purpose in _PROFILE_A_PURPOSES},
        available_free_bytes=available_free_bytes,
    )
    capacity._ledger = ledger
    capacity._refresh = lambda: None
    capacity.begin_operation_for_characterization = ledger.begin_operation
    capacity.reserve_for_characterization = lambda operation, estimates: ledger.reserve(
        operation, estimates,
    )
    capacity.cancel_before_write_for_characterization = ledger.cancel_before_write

    def readiness():
        view = ledger.readiness()
        view.update({
            "status": "unavailable" if capacity._closed or capacity._invalid
            else "characterization_only",
            "root_set_contract": "profile_a_four_writable_roots",
            "scope_writer_lease": "held" if capacity._scope_lease._state == "held"
            else "released",
            "execution_available": False,
            "protected_storage_available": False,
            "promotion_available": False,
            "candidate_publication_allowed": False,
            "project_save_allowed": False,
            "authorship": "unverified",
        })
        return view

    capacity.readiness = readiness
    return ledger


def _profile_a_submission_lease(runtime, lifecycle, worker):
    from ui.agent_generation_original_host_worker_storage import GenerationWorkerOperationLease

    if lifecycle._worker_storage_integration is None:
        assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
            worker, lifecycle._profile_a_storage_binding[0]._roots,
            lifecycle._profile_a_storage_binding[0], lifecycle._profile_a_storage_binding[1],
        ) == "bound_non_executing"
    else:
        assert lifecycle._worker_storage_integration._worker is worker
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", _prepared(lifecycle), None, correlation,
    )
    assert status == "admitted_non_executing"
    assert type(lease) is GenerationWorkerOperationLease
    return lease


def _history_json_for(prepared, prompt_id, *, descriptor_count=1, completed=True,
                      status_str="success", include_status=True):
    nodes = tuple(prepared.output_nodes)
    assert nodes and descriptor_count >= len(nodes)
    outputs = {}
    remaining = descriptor_count
    for node_index, (node_id, bucket) in enumerate(nodes):
        count = (remaining - (len(nodes) - node_index - 1)
                 if node_index == 0 else 1)
        images = [{
            "filename": f"remote-{node_index}-{image_index}.png",
            "subfolder": "",
            "type": bucket,
        } for image_index in range(count)]
        outputs[node_id] = {"images": images}
        remaining -= count
    record = {"outputs": outputs}
    if include_status:
        record["status"] = {"completed": completed, "status_str": status_str}
    return json.dumps({prompt_id: record}, separators=(",", ":")).encode("utf-8")


def _profile_a_history_observed(*, descriptor_count=1, estimate_bytes=32 * 1024 * 1024,
                                estimate_entries=1, history_json=None,
                                history_transport_result=None, include_status=True,
                                completed=True):
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, _state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    ledger = _configure_portable_profile_a_capacity(
        capacity, asset_bytes=256 * 1024 * 1024,
        available_free_bytes=512 * 1024 * 1024,
    )
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    submission_correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    submission_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", prepared, None, submission_correlation,
    )
    assert status == "admitted_non_executing"
    preadmission, status = runtime.pre_admit_generation_worker_staging_for_characterization(
        submission_lease, CapacityEstimate(estimate_bytes, estimate_entries),
    )
    assert status == "pre_admitted_non_authoritative"
    submission = worker.perform_for_characterization(
        "submission", prepared, None, submission_correlation,
    )
    assert runtime.observe_generation_worker_http_result_for_characterization(
        submission_lease, submission,
    ) == "observed_non_authoritative"
    accepted_prompt_id = prompt_id
    if history_json is None:
        history_json = _history_json_for(
            prepared, prompt_id, descriptor_count=descriptor_count,
            include_status=include_status, completed=completed,
        )
    worker._test_history_body_ref[0] = history_json
    if history_transport_result is not None:
        worker._history_transport = lambda _prepared, _prompt_id: history_transport_result
    history_correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="history", prompt_id=accepted_prompt_id,
    )
    history_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "history", prepared, accepted_prompt_id, history_correlation,
    )
    assert status == "admitted_non_executing"
    history = worker.perform_for_characterization(
        "history", prepared, accepted_prompt_id, history_correlation,
    )
    observed_status = runtime.observe_generation_worker_http_result_for_characterization(
        history_lease, history,
    )
    return (runtime, lifecycle, roots, capacity, reference, worker, ledger,
            prepared, submission_lease, preadmission, submission,
            history_lease, history, observed_status, prompt_id)


def _profile_a_prospective_history_observed(
        native_profile_a_worker_storage, *, descriptor_count=1,
        include_status=True, completed=True, host_provider=None,
        estimate_bytes=32 * 1024 * 1024, estimate_entries=1):
    """Run the genuine prospective 19G-B/C path on disposable native roots."""
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _route, state, lifecycle = _ready_generation_at_project_path(
        project_path, host_provider=host_provider,
    )
    prompt_id = str(uuid.uuid4())
    worker = _worker(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_storage_for_characterization(
        capacity, reference,
    ) == "matched_reference_only"
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)

    submission_lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    preadmission, status = runtime.pre_admit_generation_worker_staging_for_characterization(
            submission_lease, CapacityEstimate(estimate_bytes, estimate_entries),
    )
    assert status == "pre_admitted_non_authoritative"

    submission = worker.perform_for_characterization(
        "submission", prepared, None, submission_lease.correlation,
    )
    assert submission.outcome.status == "accepted"
    submitted_status = runtime.observe_generation_worker_http_result_for_characterization(
        submission_lease, submission,
    )
    assert submitted_status == "submitted_event_accepted_non_authoritative"

    history_json = _history_json_for(
        prepared, prompt_id, descriptor_count=descriptor_count,
        include_status=include_status, completed=completed,
    )
    worker._test_history_body_ref[0] = history_json
    history_correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="history", prompt_id=prompt_id,
    )
    history_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "history", prepared, prompt_id, history_correlation,
    )
    assert status == "admitted_non_executing"
    history = worker.perform_for_characterization(
        "history", prepared, prompt_id, history_correlation,
    )
    observed_history_status = runtime.observe_generation_worker_http_result_for_characterization(
        history_lease, history,
    )
    return (runtime, state, lifecycle, roots, capacity, reference, project_path,
            worker, prepared, submission_lease, preadmission, submission,
            history_lease, history, history_json, observed_history_status)


def _ready_generation_at_project_path(project_path, *, run_count=1, host_provider=None):
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
    provider = host_provider if host_provider is not None else host_for()
    binding = [
        agent_facade.candidate_observation_handles.project_identity(state["project"]),
        runtime._registration.route_id,
        state["current_project_path"],
        route._pairing_generation,
        epoch,
    ]
    preview = agent_facade.preview_generation(
        state["project"], "scene", run_count=run_count,
        host_context_provider=provider, observation_binding=binding,
    )
    args = {"scene_id": "scene", "run_count": run_count,
            "expected_plan_id": preview["plan_id"]}
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


@pytest.fixture
def native_profile_a_dual_custody_worker_storage(tmp_path):
    import sys

    from core import generation_windows_protected_storage as windows

    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    api = windows._api()
    user = windows._current_user(api)
    scope = tmp_path / "worker-profile-a-dual-custody-scope"
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
        project_path = tmp_path / "ordinary-selected-project-dual-custody.json"
        project_path.write_text('{"disposable":true}', encoding="utf-8")
        reference = windows.WindowsProjectJsonReferenceCharacterization.capture_for_characterization(
            str(project_path), characterization=True, disposable_opt_in=True,
        )
        owner = WindowsProtectedStorageAdmissionCharacterization.capture_profile_a_root_set_for_characterization(
            str(scope), roots, characterization=True, disposable_opt_in=True,
            asset_capacity_policy=PROFILE_A_DUAL_CUSTODY_CAPACITY_POLICY,
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
    prepared = _prepared(lifecycle)
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", prepared, None, correlation,
    )
    assert status == "admitted_non_executing"
    assert worker.start_for_characterization().state == "running"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, correlation,
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


def test_profile_a_pre_send_seam_accepts_exact_started_event_before_worker_admission():
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerExecutorEventChainObservation,
    )

    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)

    before = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert type(before) is GenerationWorkerExecutorEventChainObservation
    assert before.profile_a_event_kinds == ()
    assert before.candidate_eligibility == "not_established"
    assert before.next_required_event == "submission_started"

    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    assert lease.kind == "submission" and lease.correlation is not None
    job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    assert job["event_count"] == 1
    assert job["requests"][0]["state"] == "submitting"
    inbox_events = tuple(runtime._generation_executor_inbox._authority_events)
    assert len(inbox_events) == 1
    assert inbox_events[0].progress.kind == "submission_started"
    assert inbox_events[0].progress.sequence == 1
    assert inbox_events[0].progress.request_index == 0
    assert inbox_events[0].outputs is None

    # The exact first operation is one-shot; a duplicate call cannot add a
    # second source event or obtain a second Worker admission.
    duplicate, duplicate_status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert duplicate is None
    assert duplicate_status == "executor_event_chain_conflict"
    assert len(runtime._generation_executor_inbox._authority_events) == 1

    capacity_before = capacity.readiness()
    project_before = copy.deepcopy(state["project"])
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    assert completion.outcome.status == "accepted"
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "submitted_event_accepted_non_authoritative"

    submitted_attempt = lifecycle._worker_storage_integration._profile_a_submitted_event_attempts[0]
    submitted_event = submitted_attempt.event
    assert submitted_attempt.state == "events_accepted"
    assert submitted_attempt.completion is completion
    assert submitted_attempt.prepared is prepared
    assert submitted_event.progress.sequence == 2
    assert submitted_event.progress.request_index == 0
    assert submitted_event.progress.kind == "submitted"
    assert submitted_event.progress.output_count == 0
    assert submitted_event.progress.prompt_id == prompt_id
    assert submitted_event.outputs is None
    inbox = runtime._generation_executor_inbox
    assert inbox._events[2] is submitted_event
    assert sum(item is submitted_event for item in inbox._authority_events) == 1
    job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    assert job["event_count"] == 2
    assert job["requests"][0]["state"] == "awaiting_result"
    assert job["requests"][0]["registered_count"] == 0
    assert job["registered_count"] == 0
    assert capacity.readiness() == capacity_before
    assert state["project"] == project_before
    history_correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="history", prompt_id=prompt_id,
    )
    assert history_correlation is not None

    # Re-observing the same completion is duplicate evidence, not a second
    # event or a second send.
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "duplicate_non_authoritative"
    assert tuple(inbox._authority_events) == (inbox_events[0], submitted_event)
    assert worker.observation_for_characterization().accepted_operations == 1

    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert audit.profile_a_event_kinds == ("submission_started", "submitted")
    assert audit.accepted_event_kinds == ("submission_started", "submitted")
    assert audit.next_required_event == "remote_outputs_ready"
    assert audit.candidate_eligibility == "not_established"
    integration = lifecycle._worker_storage_integration

    # Eviction from both bounded event owners must not turn a consumed
    # one-shot submitted event into a new submission opportunity.
    with runtime.generation_jobs._lock:
        with inbox._lock:
            retained_job = runtime.generation_jobs._authorized_locked(
                lifecycle._job_id, lifecycle._claim_id,
            )
            retained_job.events.clear()
            retained_job.authority_events.clear()
            inbox._events.clear()
            inbox._authority_events.clear()
    evicted_audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert evicted_audit.status == "event_chain_conflict"
    assert evicted_audit.profile_a_event_kinds == ()
    assert evicted_audit.next_required_event is None
    retry_after_eviction, retry_status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert retry_after_eviction is None
    assert retry_status == "executor_event_chain_conflict"
    assert integration.execution_available is False
    assert integration.protected_storage_available is False
    assert integration.promotion_available is False
    assert integration.candidate_publication_allowed is False
    assert integration.authorship == "unverified"
    runtime.close()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_successful_history_accepts_one_source_bound_remote_outputs_event(
        native_profile_a_worker_storage, descriptor_count):
    from core.generation_storage_admission import _profile_a_executor_event_is_unresolved
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerExecutorEventChainObservation,
    )

    (runtime, state, lifecycle, roots, capacity, _reference, project_path,
     worker, prepared, _submission_lease, preadmission, _submission,
     _history_lease, _history, _history_json, observed_history_status) = (
        _profile_a_prospective_history_observed(
            native_profile_a_worker_storage, descriptor_count=descriptor_count,
        )
    )
    project_before = copy.deepcopy(state["project"])
    project_file_before = project_path.read_bytes()
    ledger_operations_before = set(capacity._ledger._operations)
    ledger_reservations_before = set(capacity._ledger._reservations)
    integration = lifecycle._worker_storage_integration
    try:
        assert observed_history_status == "observed_non_authoritative"
        before_event_count = len(runtime._generation_executor_inbox._authority_events)
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"
        assert evidence is not None and evidence.descriptor_count == descriptor_count

        attempt = integration._storage_preadmission_attempts[0]
        remote_event_attempt = integration._profile_a_remote_outputs_ready_event_attempts[0]
        event = remote_event_attempt.event
        assert _profile_a_executor_event_is_unresolved(integration) is False
        inbox = runtime._generation_executor_inbox
        assert remote_event_attempt.state == "events_accepted"
        assert remote_event_attempt.preadmission_attempt is attempt
        assert remote_event_attempt.remote_receipt is attempt.remote_receipt
        assert remote_event_attempt.evidence is evidence
        assert event is inbox._events[event.progress.sequence]
        assert sum(item is event for item in inbox._authority_events) == 1
        assert event.progress.kind == "remote_outputs_ready"
        assert event.progress.sequence == 3
        assert event.progress.output_count == descriptor_count
        assert event.progress.prompt_id is None
        assert event.outputs.receipt_id == attempt.remote_receipt.identity[:32]
        assert event.outputs.output_count == descriptor_count
        assert tuple(image.identity for image in attempt.remote_receipt.images) == tuple(
            sorted(image.identity for image in attempt.remote_receipt.images)
        )
        assert len(inbox._authority_events) == before_event_count + 1
        assert tuple(item.progress.kind for item in inbox._authority_events) == (
            "submission_started", "submitted", "remote_outputs_ready",
        )

        with runtime.generation_jobs._lock:
            job = runtime.generation_jobs._authorized_locked(
                lifecycle._job_id, lifecycle._claim_id,
            )
            assert job.request_states[0] == "awaiting_download"
            assert job.remote_outputs[0] == descriptor_count
            assert job.registered[0] == 0
            assert sum(job.registered) == 0
            assert job.event_count == 3

        audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
            state, 0, characterization=True, disposable_opt_in=True,
        )
        assert type(audit) is GenerationWorkerExecutorEventChainObservation
        assert audit.accepted_event_kinds == (
            "submission_started", "submitted", "remote_outputs_ready",
        )
        assert audit.profile_a_event_kinds == audit.accepted_event_kinds
        assert audit.next_required_event == "outputs_ready"
        assert audit.candidate_eligibility == "not_established"
        assert audit.execution_available is False
        assert audit.protected_storage_available is False
        assert audit.promotion_available is False
        assert audit.candidate_publication_allowed is False
        assert audit.project_save_allowed is False
        assert audit.authorship == "unverified"

        # Event publication creates no local image, destination reservation,
        # promotion, Candidate record or Project mutation.
        assert set(capacity._ledger._operations) == ledger_operations_before
        assert set(capacity._ledger._reservations) == ledger_reservations_before
        assert state["project"] == project_before
        assert project_path.read_bytes() == project_file_before
        assert all(not any(root._path.iterdir()) for root in roots.values())

        duplicate, duplicate_status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert duplicate is None
        assert duplicate_status == "remote_output_evidence_unavailable"
        assert len(inbox._authority_events) == before_event_count + 1
        assert worker.observation_for_characterization().accepted_operations == 2
        assert prepared.request_index == 0
    finally:
        runtime.close()


def test_profile_a_statusless_ready_history_never_emits_remote_outputs_event(
        native_profile_a_worker_storage):
    (runtime, state, lifecycle, _roots, _capacity, _reference, _project_path,
     _worker_instance, _prepared_request, _submission_lease, preadmission,
     _submission, _history_lease, _history, _history_json,
     observed_history_status) = _profile_a_prospective_history_observed(
        native_profile_a_worker_storage, include_status=False,
    )
    integration = lifecycle._worker_storage_integration
    try:
        assert observed_history_status == "observed_non_authoritative"
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert evidence is None
        assert status == "remote_output_descriptor_policy_failed"
        assert integration._profile_a_remote_outputs_ready_event_attempts == {}
        inbox = runtime._generation_executor_inbox
        assert tuple(event.progress.kind for event in inbox._authority_events) == (
            "submission_started", "submitted",
        )
        audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
            state, 0, characterization=True, disposable_opt_in=True,
        )
        assert audit.status == "profile_a_submitted_event_observed"
        assert audit.profile_a_event_kinds == ("submission_started", "submitted")
        assert audit.next_required_event == "remote_outputs_ready"
        with runtime.generation_jobs._lock:
            job = runtime.generation_jobs._authorized_locked(
                lifecycle._job_id, lifecycle._claim_id,
            )
            assert job.request_states[0] == "awaiting_result"
            assert job.remote_outputs[0] == 0
    finally:
        runtime.close()


@pytest.mark.parametrize(("source_kind", "mutation"), [
    ("submission_started", "events_removed"),
    ("submitted", "events_replaced"),
    ("submission_started", "authority_missing"),
    ("submitted", "authority_duplicated"),
])
def test_profile_a_writer_handoff_rechecks_exact_prior_inbox_event_custody(
        native_profile_a_worker_storage, source_kind, mutation):
    """Accepted remote output cannot outlive its exact Inbox event prefix."""
    (runtime, state, lifecycle, roots, capacity, _reference, project_path,
     _worker_instance, _prepared_request, _submission_lease, preadmission,
     _submission, _history_lease, _history, _history_json,
     observed_history_status) = _profile_a_prospective_history_observed(
        native_profile_a_worker_storage,
    )
    integration = lifecycle._worker_storage_integration
    try:
        assert observed_history_status == "observed_non_authoritative"
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"
        assert evidence is not None

        inbox = runtime._generation_executor_inbox
        marker = integration._profile_a_remote_outputs_ready_event_attempts[0]
        remote_event = marker.event
        assert marker.state == "events_accepted"
        assert inbox._events[remote_event.progress.sequence] is remote_event
        assert sum(item is remote_event for item in inbox._authority_events) == 1

        if source_kind == "submission_started":
            source_event = integration._profile_a_submission_started_events[0]
        else:
            source_event = integration._profile_a_submitted_event_attempts[0].event
        source_sequence = source_event.progress.sequence
        assert inbox._events[source_sequence] is source_event
        assert sum(item is source_event for item in inbox._authority_events) == 1

        # Model loss or substitution in either Inbox custody surface after the
        # remote event was accepted, while leaving Job progress and that third
        # remote event intact.
        with runtime.generation_jobs._lock:
            with inbox._lock:
                if mutation == "events_removed":
                    inbox._events.pop(source_sequence)
                elif mutation == "events_replaced":
                    inbox._events[source_sequence] = replace(source_event)
                elif mutation == "authority_missing":
                    inbox._authority_events[:] = [
                        item for item in inbox._authority_events
                        if item is not source_event
                    ]
                else:
                    assert mutation == "authority_duplicated"
                    inbox._authority_events.append(source_event)

        assert inbox._events.get(remote_event.progress.sequence) is remote_event
        with runtime.generation_jobs._lock:
            job = runtime.generation_jobs._authorized_locked(
                lifecycle._job_id, lifecycle._claim_id,
            )
            assert job.events.get(remote_event.progress.sequence) == remote_event.progress
            assert job.request_states[0] == "awaiting_download"
            assert job.remote_outputs[0] == remote_event.progress.output_count
            assert job.registered[0] == 0

        audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
            state, 0, characterization=True, disposable_opt_in=True,
        )
        assert audit.status == "event_chain_conflict"
        assert audit.next_required_event is None
        assert audit.candidate_eligibility == "not_established"

        attempt = integration._storage_preadmission_attempts[0]
        from core.generation_windows_protected_assets import (
            WindowsProtectedAssetsCharacterization,
        )
        writer_owner = object.__new__(WindowsProtectedAssetsCharacterization)
        operations_before = set(capacity._ledger._operations)
        reservations_before = set(capacity._ledger._reservations)
        root_entries_before = {
            purpose: tuple(root._path.iterdir()) for purpose, root in roots.items()
        }
        project_before = copy.deepcopy(state["project"])
        project_file_before = project_path.read_bytes()

        handoff, refusal = integration._begin_single_image_writer_handoff_locked(
            lifecycle, evidence, writer_owner, allow_batch=True,
        )
        assert handoff is None
        assert refusal == "remote_outputs_ready_event_required"
        assert attempt.writer_handoff_state == "not_started"
        assert attempt.writer_owner is None
        assert set(capacity._ledger._operations) == operations_before
        assert set(capacity._ledger._reservations) == reservations_before
        assert {purpose: tuple(root._path.iterdir())
                for purpose, root in roots.items()} == root_entries_before
        assert state["project"] == project_before
        assert project_path.read_bytes() == project_file_before
        assert runtime.generation_jobs.snapshot(lifecycle._job_id)["registered_count"] == 0
    finally:
        runtime.close()


def test_profile_a_remote_outputs_event_ack_loss_is_unbound_and_retains_capacity(
        native_profile_a_worker_storage):
    from core.generation_storage_admission import _profile_a_executor_event_is_unresolved

    (runtime, state, lifecycle, _roots, capacity, _reference, _project_path,
     _worker_instance, _prepared_request, _submission_lease, preadmission,
     _submission, _history_lease, _history, _history_json,
     observed_history_status) = _profile_a_prospective_history_observed(
        native_profile_a_worker_storage,
    )
    integration = lifecycle._worker_storage_integration
    inbox = runtime._generation_executor_inbox
    original_event = inbox.event_for_characterization

    def accept_then_lose_ack(jobs, event, *, target_current):
        result = original_event(jobs, event, target_current=target_current)
        if event.progress.kind == "remote_outputs_ready" and result == "accepted":
            raise RuntimeError("synthetic_ack_loss")
        return result

    inbox.event_for_characterization = accept_then_lose_ack
    try:
        assert observed_history_status == "observed_non_authoritative"
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert evidence is not None
        assert status == "remote_outputs_ready_event_uncertain"
        marker = integration._profile_a_remote_outputs_ready_event_attempts[0]
        assert marker.state == "retained_uncertain"
        assert _profile_a_executor_event_is_unresolved(integration) is True
        assert marker.event is inbox._events[marker.event.progress.sequence]
        audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
            state, 0, characterization=True, disposable_opt_in=True,
        )
        assert audit.status == "remote_outputs_ready_event_uncertain"
        assert audit.profile_a_event_kinds == ("submission_started", "submitted")
        assert audit.next_required_event is None
        assert audit.candidate_eligibility == "not_established"
        assert len([event for event in inbox._authority_events
                    if event.progress.kind == "remote_outputs_ready"]) == 1

        # An unbound event cannot start protected Writer handoff, even though
        # the validated remote metadata remains privately inspectable.
        from core.generation_windows_protected_assets import (
            WindowsProtectedAssetsCharacterization,
        )
        writer_owner = object.__new__(WindowsProtectedAssetsCharacterization)
        handoff, refusal = integration._begin_single_image_writer_handoff_locked(
            lifecycle, evidence, writer_owner, allow_batch=True,
        )
        assert handoff is None
        assert refusal == "remote_outputs_ready_event_required"
    finally:
        runtime.close()
    assert capacity._scope_lease_retention_reason() == "uncertain"


def test_profile_a_remote_outputs_event_commit_serializes_worker_and_capacity_close(
        native_profile_a_worker_storage):
    (runtime, _state, lifecycle, _roots, capacity, _reference, _project_path,
     _worker_instance, _prepared_request, _submission_lease, preadmission,
     _submission, _history_lease, _history, _history_json,
     _observed_history_status) = _profile_a_prospective_history_observed(
        native_profile_a_worker_storage,
    )
    integration = lifecycle._worker_storage_integration
    worker = integration._worker
    inbox = runtime._generation_executor_inbox
    accepted, release = threading.Event(), threading.Event()
    worker_close_started, worker_close_done = threading.Event(), threading.Event()
    capacity_close_started, capacity_close_done = threading.Event(), threading.Event()
    result, errors = [], []
    original_event = inbox.event_for_characterization

    def accept_then_pause(jobs, event, *, target_current):
        observation = original_event(jobs, event, target_current=target_current)
        if event.progress.kind == "remote_outputs_ready" and observation == "accepted":
            accepted.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test did not release paused remote event commit")
        return observation

    inbox.event_for_characterization = accept_then_pause

    def observe_remote_outputs():
        try:
            result.append(runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
                preadmission,
            ))
        except BaseException as exc:
            errors.append(exc)

    def close_worker():
        worker_close_started.set()
        worker.request_close_for_characterization()
        worker_close_done.set()

    def close_capacity():
        capacity_close_started.set()
        capacity.close()
        capacity_close_done.set()

    observer = threading.Thread(target=observe_remote_outputs)
    worker_closer = threading.Thread(target=close_worker)
    capacity_closer = threading.Thread(target=close_capacity)
    try:
        assert _observed_history_status == "observed_non_authoritative"
        observer.start()
        assert accepted.wait(timeout=5)

        worker_lock_acquired = worker._lock.acquire(blocking=False)
        if worker_lock_acquired:
            worker._lock.release()
        capacity_lock_acquired = capacity._lock.acquire(blocking=False)
        if capacity_lock_acquired:
            capacity._lock.release()
        assert not worker_lock_acquired
        assert not capacity_lock_acquired

        worker_closer.start()
        capacity_closer.start()
        assert worker_close_started.wait(timeout=2)
        assert capacity_close_started.wait(timeout=2)
        assert not worker_close_done.is_set()
        assert not capacity_close_done.is_set()

        release.set()
        observer.join(timeout=5)
        worker_closer.join(timeout=5)
        capacity_closer.join(timeout=5)
        assert not errors
        assert all(not thread.is_alive()
                   for thread in (observer, worker_closer, capacity_closer))
        assert result and result[0][0] is not None
        assert result[0][1] == "remote_output_writer_evidence_observed_non_authoritative"
        assert worker_close_done.is_set()
        assert capacity_close_done.is_set()

        marker = integration._profile_a_remote_outputs_ready_event_attempts[0]
        assert marker.state == "events_accepted"
        assert marker.event is inbox._events[marker.event.progress.sequence]
        assert sum(item is marker.event for item in inbox._authority_events) == 1
        snapshot = runtime.generation_jobs.snapshot(lifecycle._job_id)
        assert snapshot["requests"][0]["state"] == "awaiting_download"
        assert snapshot["requests"][0]["remote_output_count"] == len(
            marker.remote_receipt.images,
        )
        assert snapshot["registered_count"] == 0
        assert capacity._closed is True
    finally:
        release.set()
        for thread in (observer, worker_closer, capacity_closer):
            if thread.ident is not None:
                thread.join(timeout=5)
        runtime.close()


def test_profile_a_copied_remote_outputs_event_is_not_source_bound(
        native_profile_a_worker_storage):
    (runtime, state, lifecycle, _roots, _capacity, _reference, _project_path,
     _worker_instance, _prepared_request, _submission_lease, preadmission,
     _submission, _history_lease, _history, _history_json,
     _observed_history_status) = _profile_a_prospective_history_observed(
        native_profile_a_worker_storage,
    )
    try:
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"
        assert evidence is not None
        inbox = runtime._generation_executor_inbox
        marker = lifecycle._worker_storage_integration._profile_a_remote_outputs_ready_event_attempts[0]
        event = marker.event
        inbox._events[event.progress.sequence] = replace(event)
        audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
            state, 0, characterization=True, disposable_opt_in=True,
        )
        assert audit.status == "event_chain_conflict"
        assert audit.profile_a_event_kinds == ("submission_started", "submitted")
        assert audit.next_required_event is None
        assert audit.candidate_eligibility == "not_established"
    finally:
        runtime.close()


@pytest.mark.parametrize("owner", ["job_registry", "inbox"])
def test_profile_a_remote_outputs_event_requires_current_exact_submitted_source(
        native_profile_a_worker_storage, owner):
    (runtime, _state, lifecycle, _roots, _capacity, _reference, _project_path,
     _worker_instance, _prepared_request, _submission_lease, preadmission,
     _submission, _history_lease, _history, _history_json,
     _observed_history_status) = _profile_a_prospective_history_observed(
        native_profile_a_worker_storage,
    )
    integration = lifecycle._worker_storage_integration
    try:
        submitted = integration._profile_a_submitted_event_attempts[0].event
        if owner == "job_registry":
            with runtime.generation_jobs._lock:
                job = runtime.generation_jobs._authorized_locked(
                    lifecycle._job_id, lifecycle._claim_id,
                )
                job.events[submitted.progress.sequence] = replace(
                    submitted.progress, kind="execution_progress", prompt_id=None,
                )
        else:
            runtime._generation_executor_inbox._events[
                submitted.progress.sequence
            ] = replace(submitted)

        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert evidence is not None
        assert status == "remote_outputs_ready_event_refused"
        marker = integration._profile_a_remote_outputs_ready_event_attempts[0]
        assert marker.state == "refused"
        inbox = runtime._generation_executor_inbox
        assert not any(event.progress.kind == "remote_outputs_ready"
                       for event in inbox._authority_events)
        snapshot = runtime.generation_jobs.snapshot(lifecycle._job_id)
        assert snapshot["requests"][0]["state"] == "awaiting_result"
        assert snapshot["remote_output_count"] == 0
        assert snapshot["registered_count"] == 0
    finally:
        runtime.close()


def test_profile_a_copied_completion_does_not_consume_valid_submitted_event_claim():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    assert completion.outcome.status == "accepted"

    copied = replace(completion)
    assert copied is not completion
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, copied,
    ) == "foreign_non_authoritative"
    integration = lifecycle._worker_storage_integration
    assert integration._profile_a_submitted_event_attempts == {}
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["event_count"] == 1

    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "submitted_event_accepted_non_authoritative"
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["event_count"] == 2
    assert worker.observation_for_characterization().accepted_operations == 1
    runtime.close()


def test_profile_a_unknown_submission_completion_never_emits_submitted_or_retries():
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id="invalid prompt id")
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    assert completion.outcome.status == "unknown"
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "uncertain_non_authoritative"

    integration = lifecycle._worker_storage_integration
    marker = integration._profile_a_submitted_event_attempts[0]
    assert marker.state == "retained_uncertain"
    assert marker.event is None
    inbox = runtime._generation_executor_inbox
    assert tuple(event.progress.kind for event in inbox._authority_events) == (
        "submission_started",
    )
    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert audit.profile_a_event_kinds == ("submission_started",)
    assert audit.next_required_event is None
    assert audit.status == "submitted_event_uncertain"
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["registered_count"] == 0
    retry, retry_status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, _prepared(lifecycle), characterization=True, disposable_opt_in=True,
    )
    assert retry is None
    assert retry_status == "executor_event_chain_conflict"
    runtime.close()


def test_profile_a_rejected_before_send_completion_has_no_submitted_event():
    from core.comfy_http_submission import SubmissionResult

    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim()
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    worker._submission_transport = lambda _prepared: SubmissionResult(
        "rejected_before_submission",
    )
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    assert completion.outcome.status == "rejected_before_submission"
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "observed_non_authoritative"

    marker = lifecycle._worker_storage_integration._profile_a_submitted_event_attempts[0]
    assert marker.state == "submission_rejected"
    assert marker.event is None
    assert tuple(event.progress.kind for event in runtime._generation_executor_inbox._authority_events) == (
        "submission_started",
    )
    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert audit.profile_a_event_kinds == ("submission_started",)
    assert audit.next_required_event is None
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["registered_count"] == 0
    retry, retry_status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert retry is None
    assert retry_status == "executor_event_chain_conflict"
    runtime.close()


def test_profile_a_submitted_event_binding_failure_retains_accepted_unbound_evidence_and_blocks_rebind():
    from core.generation_storage_admission import _profile_a_submitted_event_is_unresolved

    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    inbox = runtime._generation_executor_inbox
    accept = inbox.event_for_characterization

    def accept_then_lose_ack(jobs, event, *, target_current):
        result = accept(jobs, event, target_current=target_current)
        if event.progress.kind == "submitted":
            return "unknown" if result == "accepted" else result
        return result

    inbox.event_for_characterization = accept_then_lose_ack
    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "uncertain_non_authoritative"

    integration = lifecycle._worker_storage_integration
    marker = integration._profile_a_submitted_event_attempts[0]
    assert marker.state == "retained_uncertain"
    assert marker.event is inbox._events[2]
    assert marker.event.progress.prompt_id == prompt_id
    assert _profile_a_submitted_event_is_unresolved(integration)
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["requests"][0]["state"] == "awaiting_result"
    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert audit.status == "submitted_event_unbound"
    assert audit.accepted_event_kinds == ("submission_started", "submitted")
    assert audit.profile_a_event_kinds == ("submission_started",)
    assert audit.next_required_event is None
    assert runtime.generation_worker_http_correlation_for_characterization(
        0, kind="history", prompt_id=prompt_id,
    ) is None

    runtime.close()
    assert lifecycle._state == "closed"
    assert capacity._closed is False
    # Isolate the new pending-marker retention guard from the already-present
    # uncertain lease and integration-state guards. This models a closed
    # lifecycle whose private accepted-event marker itself remains unresolved.
    integration._state = "closed"
    integration._uncertain_leases.clear()
    assert capacity._scope_lease_retention_reason() == "uncertain"
    original_references = tuple(capacity._host_lifecycle_refs)
    assert original_references == (lifecycle,)
    second_runtime, _route, _state, second_lifecycle = _ready_generation_at_project_path(
        lifecycle._project_path,
    )
    try:
        with pytest.raises(ValueError, match="profile_a_storage_lifecycle_unsettled"):
            capacity._bind_profile_a_lifecycle_for_characterization(
                second_lifecycle, reference,
            )
        assert tuple(capacity._host_lifecycle_refs) == original_references
    finally:
        second_runtime.close()


def test_profile_a_concurrent_completion_observations_publish_one_submitted_event():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )

    barrier = threading.Barrier(3)
    results = []
    errors = []

    def observe():
        try:
            barrier.wait(timeout=3)
            results.append(runtime.observe_generation_worker_http_result_for_characterization(
                lease, completion,
            ))
        except BaseException as exc:  # propagate worker-thread failures to the test
            errors.append(exc)

    observers = [threading.Thread(target=observe) for _ in range(2)]
    for observer in observers:
        observer.start()
    barrier.wait(timeout=3)
    for observer in observers:
        observer.join(timeout=3)

    assert not errors
    assert all(not observer.is_alive() for observer in observers)
    assert results.count("submitted_event_accepted_non_authoritative") == 1
    assert results.count("duplicate_non_authoritative") == 1
    assert tuple(event.progress.kind for event in runtime._generation_executor_inbox._authority_events) == (
        "submission_started", "submitted",
    )
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["event_count"] == 2
    assert worker.observation_for_characterization().accepted_operations == 1
    runtime.close()


def test_profile_a_submitted_event_commit_serializes_worker_and_capacity_close():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )

    accepted = threading.Event()
    release = threading.Event()
    result = []
    errors = []
    inbox = runtime._generation_executor_inbox
    accept = inbox.event_for_characterization

    def accept_then_pause(jobs, event, *, target_current):
        observation = accept(jobs, event, target_current=target_current)
        if event.progress.kind == "submitted" and observation == "accepted":
            accepted.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test did not release paused submitted commit")
        return observation

    inbox.event_for_characterization = accept_then_pause

    def observe_completion():
        try:
            result.append(runtime.observe_generation_worker_http_result_for_characterization(
                lease, completion,
            ))
        except BaseException as exc:
            errors.append(exc)

    observer = threading.Thread(target=observe_completion)
    observer.start()
    assert accepted.wait(timeout=3)

    worker_lock_acquired = worker._lock.acquire(blocking=False)
    if worker_lock_acquired:
        worker._lock.release()
    capacity_lock_acquired = capacity._lock.acquire(blocking=False)
    if capacity_lock_acquired:
        capacity._lock.release()
    assert not worker_lock_acquired
    assert not capacity_lock_acquired

    worker_close_started, worker_close_done = threading.Event(), threading.Event()
    capacity_close_started, capacity_close_done = threading.Event(), threading.Event()

    def close_worker():
        worker_close_started.set()
        worker.request_close_for_characterization()
        worker_close_done.set()

    def close_capacity():
        capacity_close_started.set()
        capacity.close()
        capacity_close_done.set()

    worker_closer = threading.Thread(target=close_worker)
    capacity_closer = threading.Thread(target=close_capacity)
    worker_closer.start()
    capacity_closer.start()
    assert worker_close_started.wait(timeout=2)
    assert capacity_close_started.wait(timeout=2)
    assert not worker_close_done.is_set()
    assert not capacity_close_done.is_set()

    release.set()
    observer.join(timeout=3)
    worker_closer.join(timeout=3)
    capacity_closer.join(timeout=3)
    assert not errors
    assert result == ["submitted_event_accepted_non_authoritative"]
    assert all(not thread.is_alive()
               for thread in (observer, worker_closer, capacity_closer))
    assert worker_close_done.is_set()
    assert capacity_close_done.is_set()
    marker = lifecycle._worker_storage_integration._profile_a_submitted_event_attempts[0]
    assert marker.state == "events_accepted"
    assert marker.event is inbox._events[2]
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["requests"][0]["state"] == "awaiting_result"
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["registered_count"] == 0
    runtime.close()


def test_profile_a_worker_close_before_submitted_commit_fails_closed():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert status == "admitted_with_submission_started"
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    worker.request_close_for_characterization()

    assert runtime.observe_generation_worker_http_result_for_characterization(
        lease, completion,
    ) == "uncertain_non_authoritative"
    assert tuple(event.progress.kind for event in runtime._generation_executor_inbox._authority_events) == (
        "submission_started",
    )
    assert lifecycle._worker_storage_integration._profile_a_submitted_event_attempts == {}
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["requests"][0]["state"] == "submitting"
    runtime.close()


def test_profile_a_pre_send_seam_does_not_upgrade_existing_fake_event_progress():
    from ui.agent_generation_executor_handoff import deliver_executor_event_for_characterization
    from ui.agent_generation_executor_inbox import ExecutorEvent
    from ui.agent_generation_job import WorkerEvent

    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    prepared = _prepared(lifecycle)
    envelope = lifecycle._envelope
    assert deliver_executor_event_for_characterization(
        state, runtime, ExecutorEvent(
            envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity,
            WorkerEvent(1, 0, "submission_started"),
        ),
    ) == "accepted"

    lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
        state, prepared, characterization=True, disposable_opt_in=True,
    )
    assert lease is None
    assert status == "executor_event_chain_conflict"
    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert audit.accepted_event_kinds == ("submission_started",)
    assert audit.profile_a_event_kinds == ()
    assert audit.candidate_eligibility == "not_established"
    assert worker.observation_for_characterization().accepted_operations == 0
    runtime.close()


def test_profile_a_pre_send_event_commit_serializes_with_host_close():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    prepared = _prepared(lifecycle)
    integration = lifecycle._worker_storage_integration
    event_commit_entered = threading.Event()
    release_event_commit = threading.Event()
    close_started = threading.Event()
    close_finished = threading.Event()
    original_activate = integration._activate_profile_a_submission_after_event_for_characterization

    def pause_after_event_acceptance(lease, event):
        event_commit_entered.set()
        assert release_event_commit.wait(5)
        return original_activate(lease, event)

    integration._activate_profile_a_submission_after_event_for_characterization = (
        pause_after_event_acceptance
    )
    result = []

    def begin():
        result.append(runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
            state, prepared, characterization=True, disposable_opt_in=True,
        ))

    def close_host():
        close_started.set()
        runtime.close()
        close_finished.set()

    begin_thread = threading.Thread(target=begin)
    close_thread = threading.Thread(target=close_host)
    begin_thread.start()
    assert event_commit_entered.wait(5)
    accepted_before_close = tuple(runtime._generation_executor_inbox._authority_events)
    assert len(accepted_before_close) == 1
    assert accepted_before_close[0].progress.kind == "submission_started"
    close_thread.start()
    assert close_started.wait(5)
    release_event_commit.set()
    begin_thread.join(5)
    close_thread.join(5)
    assert not begin_thread.is_alive()
    assert not close_thread.is_alive()
    assert close_finished.is_set()
    assert len(result) == 1
    lease, status = result[0]
    assert status == "admitted_with_submission_started"

    # Close wins before the caller can use the returned correlation. The
    # registered Worker is closed and cannot cross its transport boundary.
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    # The close path clears the exact Worker registration, so the later caller
    # is rejected as unknown before queue admission rather than being given a
    # synthetic pre-send result.
    assert completion.outcome.status == "unknown"
    assert worker.observation_for_characterization().accepted_operations == 0


def test_profile_a_pre_send_event_commit_serializes_with_host_disarm():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    integration = lifecycle._worker_storage_integration
    event_commit_entered = threading.Event()
    release_event_commit = threading.Event()
    disarm_started = threading.Event()
    disarm_finished = threading.Event()
    original_activate = integration._activate_profile_a_submission_after_event_for_characterization

    def pause_after_event_acceptance(lease, event):
        event_commit_entered.set()
        assert release_event_commit.wait(5)
        return original_activate(lease, event)

    integration._activate_profile_a_submission_after_event_for_characterization = (
        pause_after_event_acceptance
    )
    result = []

    def begin():
        result.append(runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
            state, prepared, characterization=True, disposable_opt_in=True,
        ))

    def disarm_host():
        disarm_started.set()
        runtime.disarm_launcher_rendezvous()
        disarm_finished.set()

    begin_thread = threading.Thread(target=begin)
    disarm_thread = threading.Thread(target=disarm_host)
    begin_thread.start()
    assert event_commit_entered.wait(5)
    disarm_thread.start()
    assert disarm_started.wait(5)
    release_event_commit.set()
    begin_thread.join(5)
    disarm_thread.join(5)
    assert not begin_thread.is_alive()
    assert not disarm_thread.is_alive()
    assert disarm_finished.is_set()
    assert len(result) == 1
    lease, status = result[0]
    assert status == "admitted_with_submission_started"

    # Host disarm invalidates the exact Claim and Worker registration before a
    # later caller can use the returned correlation.
    completion = worker.perform_for_characterization(
        "submission", prepared, None, lease.correlation,
    )
    assert completion.outcome.status == "unknown"
    assert worker.observation_for_characterization().accepted_operations == 0
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["state"] == "unavailable"


def test_profile_a_pre_send_event_refuses_capacity_closed_before_worker_admission():
    prompt_id = str(uuid.uuid4())
    (_values, runtime, _route, state, lifecycle, roots, capacity,
     reference, worker) = _profile_a_bound_claim(prompt_id=prompt_id)
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    prepared = _prepared(lifecycle)
    integration = lifecycle._worker_storage_integration
    event_commit_entered = threading.Event()
    release_event_commit = threading.Event()
    original_activate = integration._activate_profile_a_submission_after_event_for_characterization

    def pause_after_event_acceptance(lease, event):
        event_commit_entered.set()
        assert release_event_commit.wait(5)
        return original_activate(lease, event)

    integration._activate_profile_a_submission_after_event_for_characterization = (
        pause_after_event_acceptance
    )
    result = []
    begin_thread = threading.Thread(target=lambda: result.append(
        runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
            state, prepared, characterization=True, disposable_opt_in=True,
        )
    ))
    begin_thread.start()
    assert event_commit_entered.wait(5)
    capacity.close()
    release_event_commit.set()
    begin_thread.join(5)
    assert not begin_thread.is_alive()
    assert len(result) == 1
    lease, status = result[0]
    assert lease is None
    assert status == "worker_admission_after_event_refused"

    # The Job/Inbox event remains visible as accepted, but has no private
    # Profile A source binding and cannot be retried/upgraded after capacity
    # ownership was lost.
    event = runtime._generation_executor_inbox._authority_events[0]
    assert event.progress.kind == "submission_started"
    assert integration._profile_a_submission_started_events == {}
    assert worker.observation_for_characterization().accepted_operations == 0
    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        state, 0, characterization=True, disposable_opt_in=True,
    )
    assert audit.accepted_event_kinds == ("submission_started",)
    assert audit.profile_a_event_kinds == ()
    assert audit.candidate_eligibility == "not_established"
    runtime.close()


def test_profile_a_exact_success_history_publishes_non_authoritative_writer_evidence_once():
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerRemoteOutputWriterEvidence,
    )

    (runtime, lifecycle, _roots, capacity, _reference, worker, _ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed()
    assert observed_status == "observed_non_authoritative"

    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    )
    assert type(evidence) is GenerationWorkerRemoteOutputWriterEvidence
    assert status == "remote_output_writer_evidence_observed_non_authoritative"
    integration = lifecycle._worker_storage_integration
    attempt = integration._storage_preadmission_attempts[0]
    assert attempt.evidence is evidence
    assert attempt.evidence_state == "evidence_published"
    assert attempt.remote_receipt.execution_succeeded is True
    assert evidence.descriptor_count == 1
    assert evidence.request_byte_upper_bound == 32 * 1024 * 1024
    assert evidence.write_authorized is False
    assert evidence.writer_admission_issued is False
    assert evidence.remote_metadata_only is True
    assert evidence.image_bytes_verified is False
    assert evidence.image_content_verified is False
    assert evidence.execution_available is False
    assert evidence.protected_storage_available is False
    assert evidence.promotion_available is False
    assert evidence.candidate_publication_allowed is False
    assert evidence.project_save_allowed is False
    assert evidence.authorship == "unverified"
    assert integration.execution_available is False
    assert integration.protected_storage_available is False
    assert integration.promotion_available is False
    assert integration.candidate_publication_allowed is False
    assert integration.project_save_allowed is False
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["registered_count"] == 0
    assert worker.observation_for_characterization().state == "running"
    completed_operations = worker.observation_for_characterization().completed_operations
    later_history = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="history", prompt_id=_prompt_id,
    )
    # An evidence-published attempt cannot be superseded by another Worker
    # completion before the later writer handoff resolves its reservation.
    assert runtime.begin_generation_worker_http_operation_for_characterization(
        "history", _prepared_request, _prompt_id, later_history,
    ) == (None, "remote_output_evidence_in_progress")
    assert worker.observation_for_characterization().completed_operations == completed_operations
    assert runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    ) == (None, "remote_output_evidence_unavailable")
    assert capacity._closed is False
    runtime.close()


def test_profile_a_statusless_history_never_publishes_writer_evidence_and_releases_safe_reservation():
    (runtime, lifecycle, _roots, _capacity, _reference, _worker, _ledger,
     _prepared_request, _submission_lease, _preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed(
        include_status=False,
    )
    assert observed_status == "observed_non_authoritative"
    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        _preadmission,
    )
    assert evidence is None
    assert status == "remote_output_descriptor_policy_failed"
    attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
    assert attempt.evidence is None
    assert attempt.remote_receipt is None
    assert attempt.evidence_state == "refused"
    assert attempt.state == "cancelled"
    runtime.close()


def test_profile_a_unsuccessful_history_never_publishes_writer_evidence():
    (runtime, lifecycle, _roots, _capacity, _reference, _worker, _ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed(
        completed=False,
    )
    assert observed_status == "observed_non_authoritative"
    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    )
    assert evidence is None
    assert status == "remote_history_validation_failed"
    attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
    assert attempt.evidence is None
    assert attempt.remote_receipt is None
    assert attempt.state == "cancelled"
    runtime.close()


def test_profile_a_writer_evidence_rejects_copied_preadmission_and_cross_owner_observation():
    (runtime_a, lifecycle_a, _roots_a, _capacity_a, _reference_a, worker_a, _ledger_a,
     _prepared_a, _submission_lease_a, preadmission_a, _submission_a,
     _history_lease_a, _history_a, observed_status, _prompt_id) = _profile_a_history_observed()
    assert observed_status == "observed_non_authoritative"
    copied = replace(preadmission_a)
    assert runtime_a.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        copied,
    ) == (None, "remote_output_evidence_unavailable")

    (_values_b, runtime_b, _route_b, _state_b, lifecycle_b, roots_b, capacity_b,
     reference_b, worker_b) = _profile_a_bound_claim(prompt_id=str(uuid.uuid4()))
    _configure_portable_profile_a_capacity(
        capacity_b, asset_bytes=256 * 1024 * 1024,
        available_free_bytes=512 * 1024 * 1024,
    )
    assert runtime_b.bind_generation_profile_a_worker_storage_for_characterization(
        worker_b, roots_b, capacity_b, reference_b,
    ) == "bound_non_executing"
    assert runtime_b.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission_a,
    ) == (None, "remote_output_evidence_unavailable")
    attempt_a = lifecycle_a._worker_storage_integration._storage_preadmission_attempts[0]
    assert attempt_a.evidence is None
    assert attempt_a.evidence_state == "history_observed"
    runtime_a.close()
    runtime_b.close()


def test_profile_a_writer_evidence_rejects_copied_worker_completion_and_retains_reservation():
    (runtime, lifecycle, _roots, _capacity, _reference, _worker, ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, history, observed_status, _prompt_id) = _profile_a_history_observed()
    assert observed_status == "observed_non_authoritative"
    attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
    attempt.history_completion = replace(history)

    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    )
    assert evidence is None
    assert status == "worker_history_evidence_unavailable"
    assert attempt.evidence is None
    assert attempt.evidence_state == "uncertain"
    assert ledger.readiness()["roots"][1]["reserved_bytes"] == 32 * 1024 * 1024
    runtime.close()


@pytest.mark.parametrize("estimate_bytes", [
    32 * 1024 * 1024 - 1,
    128 * 1024 * 1024 + 1,
])
def test_profile_a_writer_evidence_refuses_estimates_outside_image_and_request_bounds(
        estimate_bytes):
    (runtime, lifecycle, _roots, _capacity, _reference, _worker, _ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed(
        estimate_bytes=estimate_bytes,
    )
    assert observed_status == "observed_non_authoritative"
    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    )
    assert evidence is None
    assert status == "writer_capacity_policy_incompatible"
    attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
    assert attempt.evidence is None
    assert attempt.state == "cancelled"
    runtime.close()


def test_profile_a_writer_evidence_requires_enough_reserved_entries_for_every_descriptor():
    (runtime, lifecycle, _roots, _capacity, _reference, _worker, _ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed(
        descriptor_count=2, estimate_bytes=64 * 1024 * 1024, estimate_entries=1,
    )
    assert observed_status == "observed_non_authoritative"
    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    )
    assert evidence is None
    assert status == "writer_capacity_policy_incompatible"
    attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
    assert attempt.evidence is None
    assert attempt.state == "cancelled"
    runtime.close()


def test_profile_a_writer_evidence_accepts_maximum_bounded_descriptor_batch():
    (runtime, lifecycle, _roots, _capacity, _reference, _worker, _ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed(
        descriptor_count=16, estimate_bytes=128 * 1024 * 1024, estimate_entries=16,
    )
    assert observed_status == "observed_non_authoritative"
    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    )
    assert status == "remote_output_writer_evidence_observed_non_authoritative"
    assert evidence.descriptor_count == evidence.max_images == 16
    assert evidence.request_byte_upper_bound == evidence.max_request_bytes == 128 * 1024 * 1024
    assert evidence.request_entry_upper_bound == 16
    assert lifecycle._worker_storage_integration._storage_preadmission_attempts[0].evidence is evidence
    runtime.close()


def test_profile_a_writer_evidence_rejects_more_than_maximum_descriptors():
    (runtime, lifecycle, _roots, _capacity, _reference, _worker, _ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed(
        descriptor_count=17, estimate_bytes=128 * 1024 * 1024, estimate_entries=16,
    )
    assert observed_status == "observed_non_authoritative"
    evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
        preadmission,
    )
    assert evidence is None
    assert status == "remote_history_validation_failed"
    attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
    assert attempt.evidence is None
    assert attempt.state == "cancelled"
    runtime.close()


@pytest.mark.parametrize("invalidation", [
    "runtime_close", "claim", "project_switch", "worker_revocation", "capacity_close",
])
def test_profile_a_writer_evidence_readiness_race_fences_invalidation(invalidation):
    entered, release = threading.Event(), threading.Event()
    invalidated = threading.Event()
    (runtime, lifecycle, _roots, capacity, reference, _worker, _ledger,
     _prepared_request, _submission_lease, preadmission, _submission,
     _history_lease, _history, observed_status, _prompt_id) = _profile_a_history_observed()
    assert observed_status == "observed_non_authoritative"
    assert capacity._lock._is_owned() is False
    assert lifecycle._lock.locked() is False
    actual_capacity_readiness = capacity.readiness

    def blocked_readiness():
        assert not capacity._lock._is_owned()
        assert not lifecycle._lock.locked()
        entered.set()
        assert release.wait(3)
        return actual_capacity_readiness()

    capacity.readiness = blocked_readiness
    results = []
    caller = threading.Thread(target=lambda: results.append(
        runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        ),
    ))
    caller.start()
    invalidator = None
    try:
        assert entered.wait(3)
        # The native readiness callback must not retain host or lifecycle locks;
        # invalidation can proceed while it is blocked on this barrier.
        assert not lifecycle._lock.locked()
        def invalidate():
            if invalidation == "runtime_close":
                runtime.close()
            elif invalidation == "claim":
                runtime.generation_jobs.invalidate_execution_custody()
            elif invalidation == "project_switch":
                project = lifecycle._project_ref()
                runtime.synchronize_target(type(project)(project_metadata={"name": "replacement"}),
                                           r"C:\PG\replacement.json")
            elif invalidation == "worker_revocation":
                lifecycle._worker_storage_integration.revoke("job_claim_replaced")
            else:
                capacity.close()
            invalidated.set()

        invalidator = threading.Thread(target=invalidate)
        invalidator.start()
        assert invalidated.wait(3)
    finally:
        release.set()
        caller.join(3)
        assert not caller.is_alive()
        if invalidator is not None:
            invalidator.join(3)
            assert not invalidator.is_alive()
    assert results and results[0][0] is None
    attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
    assert attempt.evidence is None
    assert attempt.evidence_state != "evidence_published"
    runtime.close()


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


def test_profile_a_writer_evidence_rechecks_native_roots_without_writing_files(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _route, _state, lifecycle = _ready_generation_at_project_path(project_path)
    prompt_id = str(uuid.uuid4())
    worker = _worker(prompt_id=prompt_id)
    try:
        assert runtime.bind_generation_profile_a_storage_for_characterization(
            capacity, reference,
        ) == "matched_reference_only"
        assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
            worker, roots, capacity, reference,
        ) == "bound_non_executing"
        assert worker.start_for_characterization().state == "running"

        prepared = _prepared(lifecycle)
        submission_correlation = runtime.generation_worker_http_correlation_for_characterization(
            0, kind="submission",
        )
        submission_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
            "submission", prepared, None, submission_correlation,
        )
        assert status == "admitted_non_executing"
        preadmission, status = runtime.pre_admit_generation_worker_staging_for_characterization(
            submission_lease, CapacityEstimate(32 * 1024 * 1024, 1),
        )
        assert status == "pre_admitted_non_authoritative"
        submission = worker.perform_for_characterization(
            "submission", prepared, None, submission_correlation,
        )
        assert runtime.observe_generation_worker_http_result_for_characterization(
            submission_lease, submission,
        ) == "observed_non_authoritative"

        history_json = _history_json_for(prepared, prompt_id)
        worker._test_history_body_ref[0] = history_json
        history_correlation = runtime.generation_worker_http_correlation_for_characterization(
            0, kind="history", prompt_id=prompt_id,
        )
        history_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
            "history", prepared, prompt_id, history_correlation,
        )
        assert status == "admitted_non_executing"
        history = worker.perform_for_characterization(
            "history", prepared, prompt_id, history_correlation,
        )
        assert runtime.observe_generation_worker_http_result_for_characterization(
            history_lease, history,
        ) == "observed_non_authoritative"

        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"
        assert evidence is not None and evidence.descriptor_count == 1
        assert evidence.write_authorized is False
        assert capacity.readiness()["native_root_identity"] == "observed_unchanged"
        assert reference.readiness()["status"] == "read_only_reference_observed"
        assert all(not any(root._path.iterdir()) for root in roots.values())
        assert project_path.read_text(encoding="utf-8") == '{"disposable":true}'
    finally:
        runtime.close()


def test_profile_a_staging_preadmission_uses_native_capacity_and_project_observations(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    before_project = project_path.read_bytes()
    runtime, _route, _state, lifecycle = _ready_generation_at_project_path(project_path)
    worker = _worker()
    assert runtime.bind_generation_profile_a_storage_for_characterization(
        capacity, reference,
    ) == "matched_reference_only"
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    lease = _profile_a_submission_lease(runtime, lifecycle, worker)
    actual_capacity_readiness = capacity.readiness
    actual_project_readiness = reference.readiness
    assert actual_capacity_readiness()["status"] == "characterization_only"
    assert actual_project_readiness()["status"] == "read_only_reference_observed"
    observed_views = []
    readiness_errors = []
    integration = lifecycle._worker_storage_integration
    actual_publish = integration._publish_staging_preadmission_locked

    def capture_views(current_lifecycle, current_lease, attempt, capacity_view, project_view):
        observed_views.append((capacity_view, project_view))
        return actual_publish(
            current_lifecycle, current_lease, attempt, capacity_view, project_view,
        )

    def assert_no_host_locks():
        assert not runtime._publication_gate.locked()
        lifecycle_lock_acquired = lifecycle._lock.acquire(blocking=False)
        assert lifecycle_lock_acquired
        if lifecycle_lock_acquired:
            lifecycle._lock.release()
        assert not runtime.generation_jobs._lock._is_owned()
        assert not runtime._generation_executor_inbox._lock._is_owned()

    def capacity_readiness():
        try:
            assert_no_host_locks()
        except Exception as exc:
            readiness_errors.append(repr(exc))
            raise
        return actual_capacity_readiness()

    def project_readiness():
        try:
            assert_no_host_locks()
        except Exception as exc:
            readiness_errors.append(repr(exc))
            raise
        return actual_project_readiness()

    monkeypatch.setattr(capacity, "readiness", capacity_readiness)
    monkeypatch.setattr(reference, "readiness", project_readiness)
    integration._publish_staging_preadmission_locked = capture_views
    try:
        observation, status = runtime.pre_admit_generation_worker_staging_for_characterization(
            lease, CapacityEstimate(8192, 1),
        )
        assert status == "pre_admitted_non_authoritative", (status, readiness_errors)
        assert observed_views and observed_views[0][0]["status"] == "characterization_only", observed_views
        assert observed_views[0][1]["status"] == "read_only_reference_observed", observed_views
        assert status == "pre_admitted_non_authoritative"
        assert observation.write_authorized is False
        assert capacity._ledger._active_write is None
        assert capacity._ledger._reserved["temporary_containment"] == [8192, 1]
        assert list(roots["temporary_containment"]._path.iterdir()) == []
        assert project_path.read_bytes() == before_project
        assert worker.observation_for_characterization().state == "created"
        assert runtime.cancel_generation_worker_staging_preadmission_for_characterization(
            observation,
        ) == "cancelled_before_write"
        assert capacity._ledger._reserved["temporary_containment"] == [0, 0]
    finally:
        runtime.close()


def test_profile_a_worker_staging_preadmission_is_exact_bounded_and_non_authoritative():
    (_values, runtime, _route, _state, lifecycle, _roots, capacity,
     _reference, worker) = _profile_a_bound_claim()
    ledger = _configure_portable_profile_a_capacity(capacity)
    lease = _profile_a_submission_lease(runtime, lifecycle, worker)
    estimate = CapacityEstimate(4096, 2)
    before_job = runtime.generation_jobs.snapshot(lifecycle._job_id)

    observation, status = runtime.pre_admit_generation_worker_staging_for_characterization(
        lease, estimate,
    )

    assert status == "pre_admitted_non_authoritative"
    assert observation.status == "pre_admitted_non_authoritative"
    assert observation.purpose == "temporary_containment"
    assert (observation.request_index, observation.byte_upper_bound,
            observation.entry_upper_bound) == (0, 4096, 2)
    assert observation.write_authorized is False
    assert observation.execution_available is False
    assert observation.protected_storage_available is False
    assert observation.promotion_available is False
    assert observation.candidate_publication_allowed is False
    assert observation.project_save_allowed is False
    assert observation.authorship == "unverified"
    assert not {"correlation", "reservation", "capacity_operation", "path"} & set(
        observation.__dataclass_fields__
    )
    assert ledger._reserved["temporary_containment"] == [4096, 2]
    assert ledger._active_write is None
    assert worker.observation_for_characterization().state == "created"
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) == before_job

    assert runtime.pre_admit_generation_worker_staging_for_characterization(
        replace(lease), estimate,
    ) == (None, "operation_lease_mismatch")
    assert runtime.pre_admit_generation_worker_staging_for_characterization(
        lease, estimate,
    ) == (None, "preadmission_already_attempted")
    assert runtime.cancel_generation_worker_staging_preadmission_for_characterization(
        replace(observation),
    ) == "foreign_or_settled_preadmission"
    assert runtime.cancel_generation_worker_staging_preadmission_for_characterization(
        observation,
    ) == "cancelled_before_write"
    assert ledger._reserved["temporary_containment"] == [0, 0]
    assert ledger._active_write is None
    assert runtime.cancel_generation_worker_staging_preadmission_for_characterization(
        observation,
    ) == "foreign_or_settled_preadmission"
    runtime.close()


def test_profile_a_staging_preadmission_refuses_capacity_exhaustion_and_invalid_estimate():
    (_values, runtime, _route, _state, lifecycle, _roots, capacity,
     _reference, worker) = _profile_a_bound_claim()
    ledger = _configure_portable_profile_a_capacity(capacity, asset_bytes=10)
    lease = _profile_a_submission_lease(runtime, lifecycle, worker)
    competing_promotion = capacity.begin_operation_for_characterization(
        "characterization-promotion-capacity-reservation",
    )
    capacity.reserve_for_characterization(
        competing_promotion, {"promoted_assets": CapacityEstimate(7, 1)},
    )

    assert runtime.pre_admit_generation_worker_staging_for_characterization(
        lease, CapacityEstimate(4, 1),
    ) == (None, "capacity_refused")
    assert ledger._reserved["temporary_containment"] == [0, 0]
    assert ledger._reserved["promoted_assets"] == [7, 1]
    assert runtime.pre_admit_generation_worker_staging_for_characterization(
        lease, CapacityEstimate(1, 1),
    ) == (None, "preadmission_already_attempted")

    other = _worker()
    assert runtime.pre_admit_generation_worker_staging_for_characterization(
        lease, CapacityEstimate(0, 1),
    ) == (None, "invalid_capacity_estimate")
    assert other.observation_for_characterization().state == "created"
    runtime.close()


def test_profile_a_staging_preadmission_rejects_cross_lifecycle_lease():
    (_values_a, runtime_a, _route_a, _state_a, lifecycle_a, _roots_a, capacity_a,
     _reference_a, worker_a) = _profile_a_bound_claim()
    ledger_a = _configure_portable_profile_a_capacity(capacity_a)
    lease_a = _profile_a_submission_lease(runtime_a, lifecycle_a, worker_a)

    (_values_b, runtime_b, _route_b, _state_b, lifecycle_b, _roots_b, capacity_b,
     _reference_b, worker_b) = _profile_a_bound_claim()
    ledger_b = _configure_portable_profile_a_capacity(capacity_b)
    lease_b = _profile_a_submission_lease(runtime_b, lifecycle_b, worker_b)

    assert runtime_b.pre_admit_generation_worker_staging_for_characterization(
        lease_a, CapacityEstimate(1024, 1),
    ) == (None, "operation_lease_mismatch")
    assert ledger_b._reserved["temporary_containment"] == [0, 0]
    observation, status = runtime_b.pre_admit_generation_worker_staging_for_characterization(
        lease_b, CapacityEstimate(1024, 1),
    )
    assert status == "pre_admitted_non_authoritative"
    assert observation.request_index == 0
    assert ledger_a._reserved["temporary_containment"] == [0, 0]
    assert ledger_b._reserved["temporary_containment"] == [1024, 1]
    runtime_a.close()
    runtime_b.close()


def test_profile_a_staging_preadmission_refuses_observed_free_capacity_shortage():
    (_values, runtime, _route, _state, lifecycle, _roots, capacity,
     _reference, worker) = _profile_a_bound_claim()
    ledger = _configure_portable_profile_a_capacity(capacity)
    ledger._available_free_bytes = 1023
    lease = _profile_a_submission_lease(runtime, lifecycle, worker)

    assert runtime.pre_admit_generation_worker_staging_for_characterization(
        lease, CapacityEstimate(1024, 1),
    ) == (None, "capacity_refused")
    assert ledger._reserved["temporary_containment"] == [0, 0]
    assert ledger._active_write is None
    runtime.close()


def test_legacy_five_root_worker_binding_does_not_gain_profile_a_preadmission():
    (_values, runtime, _route, _state, lifecycle, _roots, _capacity, _worker_obj) = _bound_claim()
    correlation = runtime.generation_worker_http_correlation_for_characterization(
        0, kind="submission",
    )
    lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
        "submission", _prepared(lifecycle), None, correlation,
    )
    assert status == "admitted_non_executing"
    assert runtime.pre_admit_generation_worker_staging_for_characterization(
        lease, CapacityEstimate(1024, 1),
    ) == (None, "profile_a_required")
    runtime.close()


@pytest.mark.parametrize("invalidation", ["claim", "project_switch", "worker_revocation"])
def test_profile_a_claim_or_project_invalidation_during_reserve_cancels_pre_admission(
        invalidation):
    (_values, runtime, _route, state, lifecycle, _roots, capacity,
     _reference, worker) = _profile_a_bound_claim()
    ledger = _configure_portable_profile_a_capacity(capacity)
    lease = _profile_a_submission_lease(runtime, lifecycle, worker)
    reserved, release = threading.Event(), threading.Event()
    actual_reserve = capacity.reserve_for_characterization
    result = []

    def blocked_reserve(operation, estimates):
        token = actual_reserve(operation, estimates)
        reserved.set()
        assert release.wait(3)
        return token

    capacity.reserve_for_characterization = blocked_reserve
    thread = threading.Thread(target=lambda: result.append(
        runtime.pre_admit_generation_worker_staging_for_characterization(
            lease, CapacityEstimate(2048, 1),
        ),
    ))
    thread.start()
    try:
        assert reserved.wait(3)
        if invalidation == "claim":
            runtime.generation_jobs.invalidate_execution_custody()
        elif invalidation == "project_switch":
            runtime.synchronize_target(
                type(state["project"])(project_metadata={"name": "replacement"}),
                r"C:\PG\replacement.json",
            )
        else:
            lifecycle._worker_storage_integration.revoke("job_claim_replaced")
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert result[0][0] is None
    assert result[0][1] in {
        "cancelled_before_publication", "host_evidence_unavailable", "stale_host_binding",
        "host_or_capacity_changed",
    }
    assert ledger._reserved["temporary_containment"] == [0, 0]
    assert ledger._uncertain["temporary_containment"] == [0, 0]
    assert ledger._active_write is None
    runtime.close()


@pytest.mark.parametrize("drift", ["close", "scope_lease_loss"])
def test_profile_a_capacity_close_or_scope_loss_fences_pre_admission(drift):
    (_values, runtime, _route, _state, lifecycle, _roots, capacity,
     _reference, worker) = _profile_a_bound_claim()
    ledger = _configure_portable_profile_a_capacity(capacity)
    lease = _profile_a_submission_lease(runtime, lifecycle, worker)
    reserved, release = threading.Event(), threading.Event()
    actual_reserve = capacity.reserve_for_characterization
    result = []

    def blocked_reserve(operation, estimates):
        token = actual_reserve(operation, estimates)
        reserved.set()
        assert release.wait(3)
        return token

    capacity.reserve_for_characterization = blocked_reserve
    thread = threading.Thread(target=lambda: result.append(
        runtime.pre_admit_generation_worker_staging_for_characterization(
            lease, CapacityEstimate(3072, 1),
        ),
    ))
    thread.start()
    try:
        assert reserved.wait(3)
        if drift == "close":
            capacity.close()
        else:
            capacity._scope_lease._state = "released"
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert result[0] == (None, "storage_observation_unavailable")
    assert ledger._reserved["temporary_containment"] == [0, 0]
    if drift == "close":
        assert ledger._uncertain["temporary_containment"] == [3072, 1]
    else:
        assert ledger._uncertain["temporary_containment"] == [0, 0]
    assert ledger._active_write is None
    runtime.close()


def test_profile_a_claim_invalidation_cannot_interleave_final_preadmission_publication():
    (_values, runtime, _route, state, lifecycle, _roots, capacity,
     _reference, worker) = _profile_a_bound_claim()
    ledger = _configure_portable_profile_a_capacity(capacity)
    lease = _profile_a_submission_lease(runtime, lifecycle, worker)
    integration = lifecycle._worker_storage_integration
    entered, release, invalidator_started, invalidated = (
        threading.Event(), threading.Event(), threading.Event(), threading.Event(),
    )
    actual_publish = integration._publish_staging_preadmission_locked
    result = []

    def blocked_publish(*args):
        entered.set()
        assert release.wait(3)
        return actual_publish(*args)

    integration._publish_staging_preadmission_locked = blocked_publish
    preadmitter = threading.Thread(target=lambda: result.append(
        runtime.pre_admit_generation_worker_staging_for_characterization(
            lease, CapacityEstimate(1024, 1),
        ),
    ))

    def invalidate_claim():
        invalidator_started.set()
        runtime.generation_jobs.invalidate_execution_custody()
        invalidated.set()

    invalidator = threading.Thread(target=invalidate_claim)
    preadmitter.start()
    try:
        assert entered.wait(3)
        invalidator.start()
        assert invalidator_started.wait(3)
    finally:
        release.set()
        preadmitter.join(3)
        invalidator.join(3)
    assert not preadmitter.is_alive() and not invalidator.is_alive()
    assert invalidated.is_set()
    assert result[0][1] in {"pre_admitted_non_authoritative", "host_evidence_unavailable"}
    if result[0][0] is not None:
        assert result[0][0].write_authorized is False
        runtime.synchronize_target(
            type(state["project"])(project_metadata={"name": "after-invalidation"}),
            r"C:\PG\after-invalidation.json",
        )
    assert ledger._reserved["temporary_containment"] == [0, 0]
    assert ledger._active_write is None
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


def _native_profile_a_writer_handoff(
        roots, capacity, reference, project_path, *, descriptor_count=1,
        run_count=1, request_index=0):
    from core import generation_windows_protected_assets as assets

    runtime, _route, _state, lifecycle = _ready_generation_at_project_path(
        project_path, run_count=run_count,
    )
    prompt_id = str(uuid.uuid4())
    worker = _worker(prompt_id=prompt_id)
    try:
        assert runtime.bind_generation_profile_a_storage_for_characterization(
            capacity, reference,
        ) == "matched_reference_only"
        assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
            worker, roots, capacity, reference,
        ) == "bound_non_executing"
        assert worker.start_for_characterization().state == "running"
        prepared = _prepared(lifecycle, request_index)
        submission_correlation = runtime.generation_worker_http_correlation_for_characterization(
            request_index, kind="submission",
        )
        submission_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
            "submission", prepared, None, submission_correlation,
        )
        assert status == "admitted_non_executing"
        estimate = CapacityEstimate(
            min(32 * 1024 * 1024 * descriptor_count, 128 * 1024 * 1024),
            descriptor_count,
        )
        preadmission, status = runtime.pre_admit_generation_worker_staging_for_characterization(
            submission_lease, estimate,
        )
        assert status == "pre_admitted_non_authoritative"
        submission = worker.perform_for_characterization(
            "submission", prepared, None, submission_correlation,
        )
        assert runtime.observe_generation_worker_http_result_for_characterization(
            submission_lease, submission,
        ) == "observed_non_authoritative"

        worker._test_history_body_ref[0] = _history_json_for(
            prepared, prompt_id, descriptor_count=descriptor_count,
        )
        history_correlation = runtime.generation_worker_http_correlation_for_characterization(
            request_index, kind="history", prompt_id=prompt_id,
        )
        history_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
            "history", prepared, prompt_id, history_correlation,
        )
        assert status == "admitted_non_executing"
        history = worker.perform_for_characterization(
            "history", prepared, prompt_id, history_correlation,
        )
        assert runtime.observe_generation_worker_http_result_for_characterization(
            history_lease, history,
        ) == "observed_non_authoritative"
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"
        assert evidence.descriptor_count == descriptor_count
        attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[request_index]
        writer = assets.WindowsProtectedAssetsCharacterization.borrow_profile_a_writer_for_characterization(
            capacity, characterization=True, disposable_opt_in=True,
        )
        return runtime, lifecycle, worker, prepared, preadmission, evidence, attempt, writer
    except BaseException:
        runtime.close()
        raise


class _WriterDownloadStream:
    def __init__(self, data, *, declared_length=None, on_call=None, on_read=None, on_close=None):
        from core.comfy_output_containment import DownloadStream

        self._data = io.BytesIO(data)
        self._length = len(data) if declared_length is None else declared_length
        self._on_call, self._on_read, self._on_close = on_call, on_read, on_close
        self.lookups = []
        self.closed = 0
        self._stream_type = DownloadStream

    def __call__(self, lookup):
        self.lookups.append(lookup)
        if self._on_call is not None:
            self._on_call()
        return self._stream_type(self._length, self.read, self.close)

    def read(self, size):
        if self._on_read is not None:
            self._on_read()
        return self._data.read(size)

    def close(self):
        self.closed += 1
        if self._on_close is not None:
            self._on_close()
        self._data.close()


class _WriterDownloadBatchProvider:
    def __init__(self, data, *, fail_at=None, on_call=None, on_read=None, on_close=None):
        self.data, self.fail_at, self.on_call = data, fail_at, on_call
        self.on_read, self.on_close = on_read, on_close
        self.lookups, self.streams = [], []

    def __call__(self, lookup):
        index = len(self.lookups)
        self.lookups.append(lookup)
        if self.on_call is not None:
            self.on_call(index)
        if index == self.fail_at:
            raise RuntimeError("injected batch stream failure")
        stream = _WriterDownloadStream(
            self.data, on_read=self.on_read, on_close=self.on_close,
        )
        self.streams.append(stream)
        return stream(lookup)


def _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, *, descriptor_count=1):
    from test_comfy_output_containment import image_bytes
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedWriterObservation,
    )

    runtime, lifecycle, worker, prepared, preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=descriptor_count,
        )
    )
    data = image_bytes()
    provider = (_WriterDownloadStream(data) if descriptor_count == 1
                else _WriterDownloadBatchProvider(data))
    stage = (runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization
             if descriptor_count == 1 else
             runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization)
    observation, status = stage(
        evidence, writer, stream_provider=provider,
        characterization=True, disposable_opt_in=True,
    )
    assert type(observation) is GenerationWorkerProtectedWriterObservation, status
    assert observation.verified_image_count == descriptor_count
    return (runtime, lifecycle, worker, prepared, preadmission, evidence,
            attempt, writer, observation, provider, data)


def _publish_profile_a_promotion_for_candidate_preflight(
        roots, capacity, reference, project_path, *, descriptor_count=1):
    (runtime, lifecycle, worker, prepared, preadmission, evidence,
     attempt, writer, staged, provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=descriptor_count,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_host_publication_deferred")
    publication, status = runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_published_non_authoritative"
    assert publication is attempt.promotion_publication_observation
    return (runtime, lifecycle, worker, prepared, attempt, writer, accepted,
            preflight, publication, provider, data)


def _publish_profile_a_source_bound_promotion_for_outputs_ready(
        native_profile_a_dual_custody_worker_storage, *, descriptor_count=1,
        host_provider=None):
    """Compose genuine 19G-B/C/D events with native staging and Promotion."""
    from core import generation_windows_protected_assets as assets
    from test_comfy_output_containment import image_bytes
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedWriterObservation,
    )

    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _state, lifecycle, _roots, _capacity, _reference, _path,
     worker, prepared, _submission_lease, preadmission, _submission,
     _history_lease, _history, _history_json, history_status) = (
        _profile_a_prospective_history_observed(
            native_profile_a_dual_custody_worker_storage,
            descriptor_count=descriptor_count,
            host_provider=host_provider,
            estimate_bytes=min(32 * 1024 * 1024 * descriptor_count,
                               128 * 1024 * 1024),
            estimate_entries=descriptor_count,
        )
    )
    try:
        assert history_status == "observed_non_authoritative"
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"
        assert evidence.descriptor_count == descriptor_count
        attempt = lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
        writer = assets.WindowsProtectedAssetsCharacterization.borrow_profile_a_writer_for_characterization(
            capacity, characterization=True, disposable_opt_in=True,
        )
        data = image_bytes()
        provider = (_WriterDownloadStream(data) if descriptor_count == 1
                    else _WriterDownloadBatchProvider(data))
        stage = (runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization
                 if descriptor_count == 1 else
                 runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization)
        staged, status = stage(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert type(staged) is GenerationWorkerProtectedWriterObservation, status
        assert staged.verified_image_count == descriptor_count
        accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_batch_accepted_non_authoritative"
        preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
            accepted, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_promotion_preflight_non_authoritative"
        assert runtime.promote_generation_worker_accepted_output_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_promotion_host_publication_deferred")
        publication, status = runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_promotion_published_non_authoritative"
        assert publication is attempt.promotion_publication_observation
        return (runtime, lifecycle, worker, prepared, attempt, writer, accepted,
                preflight, publication, provider, data)
    except BaseException:
        runtime.close()
        raise


def _profile_a_host_provider_with_output_directory(output_directory):
    from test_agent_generation_executable_manifest import host_for

    base = host_for()

    def provider(project, run_count):
        host = base(project, run_count)
        host["generation_options"]["output_directory"] = str(output_directory)
        return host

    return provider


def _prepare_profile_a_candidate_publication(
        native_profile_a_dual_custody_worker_storage, output_directory,
        *, descriptor_count=1):
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedCandidateAdmissionObservation,
    )

    output_directory.mkdir()
    host_provider = _profile_a_host_provider_with_output_directory(output_directory)
    (runtime, lifecycle, worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
            descriptor_count=descriptor_count,
            host_provider=host_provider,
        )
    )
    state = runtime._generation_host_state
    state["history"] = []
    outputs_ready, event_status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert event_status == "protected_outputs_ready_event_accepted_non_authoritative"
    admission, admission_status = runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
        outputs_ready, characterization=True, disposable_opt_in=True,
    )
    assert admission_status == "protected_candidate_admission_evidence_observed"
    assert type(admission) is GenerationWorkerProtectedCandidateAdmissionObservation
    return runtime, lifecycle, worker, attempt, writer, state, output_directory, admission


def _prepare_profile_a_two_request_candidate_publications(
        native_profile_a_dual_custody_worker_storage, output_directory,
        *, after_request=None):
    """Compose two genuine sequential requests through the same Host/Worker."""
    from core import generation_windows_protected_assets as assets
    from test_comfy_output_containment import image_bytes
    from test_agent_generation_candidate_publication import app_owners
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedCandidateAdmissionObservation,
    )

    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    output_directory.mkdir()
    host_provider = _profile_a_host_provider_with_output_directory(output_directory)
    runtime, _route, state, lifecycle = _ready_generation_at_project_path(
        project_path, run_count=2, host_provider=host_provider,
    )
    requests = lifecycle._envelope.manifest.requests
    assert len(requests) == 2
    assert runtime.bind_generation_profile_a_storage_for_characterization(
        capacity, reference,
    ) == "matched_reference_only"
    prompt_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    pending_prompt_ids = list(prompt_ids)
    worker = _worker(prompt_id=lambda: pending_prompt_ids.pop(0))
    assert runtime.bind_generation_profile_a_worker_storage_for_characterization(
        worker, roots, capacity, reference,
    ) == "bound_non_executing"
    assert worker.start_for_characterization().state == "running"
    writer = assets.WindowsProtectedAssetsCharacterization.borrow_profile_a_writer_for_characterization(
        capacity, characterization=True, disposable_opt_in=True,
    )
    state["history"] = []
    owners = app_owners(state)
    owners["_PROJECT_AGENT_SESSION_RUNTIME"] = runtime
    locators, attempts = [], []
    data = image_bytes()

    for request_index, request in enumerate(requests):
        prepared = _prepared(lifecycle, request_index)
        submission_lease, status = runtime.begin_profile_a_worker_submission_with_executor_event_for_characterization(
            state, prepared, characterization=True, disposable_opt_in=True,
        )
        assert status == "admitted_with_submission_started"
        preadmission, status = runtime.pre_admit_generation_worker_staging_for_characterization(
            submission_lease, CapacityEstimate(32 * 1024 * 1024, 1),
        )
        assert status == "pre_admitted_non_authoritative"
        submission = worker.perform_for_characterization(
            "submission", prepared, None, submission_lease.correlation,
        )
        assert submission.outcome.status == "accepted"
        assert runtime.observe_generation_worker_http_result_for_characterization(
            submission_lease, submission,
        ) == "submitted_event_accepted_non_authoritative"

        prompt_id = prompt_ids[request_index]
        worker._test_history_body_ref[0] = _history_json_for(prepared, prompt_id)
        history_correlation = runtime.generation_worker_http_correlation_for_characterization(
            request_index, kind="history", prompt_id=prompt_id,
        )
        history_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
            "history", prepared, prompt_id, history_correlation,
        )
        assert status == "admitted_non_executing"
        history = worker.perform_for_characterization(
            "history", prepared, prompt_id, history_correlation,
        )
        assert runtime.observe_generation_worker_http_result_for_characterization(
            history_lease, history,
        ) == "observed_non_authoritative"
        evidence, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"
        provider = _WriterDownloadStream(data)
        staged, status = runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_staged_non_authoritative"
        accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_batch_accepted_non_authoritative"
        preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
            accepted, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_promotion_preflight_non_authoritative"
        assert runtime.promote_generation_worker_accepted_output_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_promotion_host_publication_deferred")
        promotion, status = runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_promotion_published_non_authoritative"
        outputs_ready, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
            promotion, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_outputs_ready_event_accepted_non_authoritative"
        admission, status = runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
            outputs_ready, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_candidate_admission_evidence_observed"
        assert type(admission) is GenerationWorkerProtectedCandidateAdmissionObservation
        locator, status = owners[
            "publish_profile_a_generation_candidates_for_characterization"
        ](admission)
        assert status == "protected_candidate_publication_registered"
        locators.append(locator)
        attempts.append(lifecycle._worker_storage_integration._storage_preadmission_attempts[
            request_index
        ])
        if after_request is not None:
            after_request(request_index, locator, runtime, lifecycle, state, owners)
        if request_index == 0:
            snapshot = runtime.generation_jobs.snapshot(lifecycle._job_id)
            assert snapshot["requests"][0]["state"] == "completed"
            assert snapshot["requests"][1]["state"] == "unsent"

    return runtime, lifecycle, worker, writer, state, output_directory, owners, locators, attempts


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_genuine_candidate_admission_uses_existing_gallery_writer_without_save(
        native_profile_a_dual_custody_worker_storage, tmp_path, descriptor_count):
    from test_agent_generation_candidate_publication import app_owners
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedCandidatePublicationObservation,
    )

    (runtime, lifecycle, _worker, attempt, writer, state, output_directory,
     admission) = _prepare_profile_a_candidate_publication(
        native_profile_a_dual_custody_worker_storage,
        tmp_path / "comfy-output",
        descriptor_count=descriptor_count,
    )
    project = state["project"]
    project_path = lifecycle._project_path
    project_before = copy.deepcopy(project)
    project_file_before = Path(project_path).read_bytes()
    capacity = lifecycle._worker_storage_integration._capacity_owner
    integration = lifecycle._worker_storage_integration
    job_before = runtime.generation_jobs.snapshot(lifecycle._job_id)
    ledger_operations_before = set(capacity._ledger._operations)
    ledger_reservations_before = set(capacity._ledger._reservations)
    promoted_root = writer._roots["promoted_assets"]._path
    promoted_files_before = set(promoted_root.iterdir())
    assert json.loads(runtime._generation_publication_origin.envelope.manifest.host_config_json)[
        "output_directory"
    ] == str(output_directory)
    assert Path(writer._roots["promoted_assets"]._path) != output_directory
    assert not Path(writer._roots["promoted_assets"]._path).is_relative_to(output_directory)

    owners = app_owners(state)
    owners["_PROJECT_AGENT_SESSION_RUNTIME"] = runtime
    assert owners["publish_profile_a_generation_candidates_for_characterization"].__code__.co_argcount == 1

    # Runtime callers cannot replace the Gallery owners by supplying callable
    # names that resemble the trusted app callbacks. The app wrapper below
    # issues the opaque bundle from its actual owner references.
    fake_callback_calls = []

    def _make_generated_candidate_record(*args, **kwargs):
        fake_callback_calls.append("factory")
        return None

    def _append_line_generated_candidates(*args, **kwargs):
        fake_callback_calls.append("appender")

    def save_agent_scene_module_swap_project(*args, **kwargs):
        fake_callback_calls.append("save")
        return True

    from ui.agent_generation_candidate_publication import (
        _profile_a_host_gallery_callbacks_for_current_app_run,
    )

    # The old generic issuer no longer exists. The current host capture path
    # accepts no callback arguments and only succeeds while called by the
    # actual app.py entrypoint, so same-named functions cannot mint a bundle.
    with pytest.raises(TypeError):
        _profile_a_host_gallery_callbacks_for_current_app_run(
            runtime, state,
            candidate_factory=_make_generated_candidate_record,
            candidate_appender=_append_line_generated_candidates,
            save_project=save_agent_scene_module_swap_project,
        )
    refused, refusal_status = runtime._publish_profile_a_generation_candidates_for_characterization(
        admission, state=state,
        characterization=True, disposable_opt_in=True,
    )
    assert refused is None
    assert refusal_status == "protected_candidate_publication_callbacks_unavailable"
    assert fake_callback_calls == []
    assert runtime._generation_candidate_publication is None
    assert attempt.protected_candidate_publication_state == "not_started"
    assert state["project"] == project_before
    assert state["history"] == []
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) == job_before

    # Equal-valued copies do not stand in for the exact G-F locator and do not
    # consume the one-shot Candidate publication attempt.
    copied, copied_status = owners[
        "publish_profile_a_generation_candidates_for_characterization"
    ](replace(admission))
    assert copied is None
    assert copied_status == "protected_candidate_publication_evidence_unavailable"
    assert attempt.protected_candidate_publication_state == "not_started"
    assert project == project_before
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) == job_before

    result, status = owners[
        "publish_profile_a_generation_candidates_for_characterization"
    ](admission)
    assert status == "protected_candidate_publication_registered"
    assert type(result) is GenerationWorkerProtectedCandidatePublicationObservation
    assert result.status == "protected_candidate_publication_registered_non_authoritative"
    assert result.request_index == 0
    assert result.registered_candidate_count == descriptor_count
    assert result.expected_candidate_count == descriptor_count
    assert result.registration_state == "registered"
    assert result.execution_available is False
    assert result.protected_storage_available is False
    assert result.promotion_available is False
    assert result.candidate_publication_allowed is False
    assert result.project_save_allowed is False
    assert result.authorship == "unverified"

    line = next(line for line in project.prompt_lines if line.id == "illustration-001")
    candidates = line.generated_candidates
    assert len(candidates) == descriptor_count
    assert [item["generation_provenance"]["output_index"] for item in candidates] == list(
        range(1, descriptor_count + 1)
    )
    for item in candidates:
        candidate_path = Path(item["path"])
        assert candidate_path.parent == promoted_root
        assert candidate_path.is_file()
        provenance = item["generation_provenance"]
        assert provenance["protected_promotion_identity"] == attempt.promotion_receipt.identity
        assert provenance["protected_candidate_admission_identity"] == (
            attempt.protected_candidate_admission_result.observation.identity
        )
        assert provenance["descriptor_identity"] in {
            descriptor.identity for descriptor in attempt.remote_receipt.images
        }
    assert owners["_append_line_generated_candidates"].__name__ == "_append_line_generated_candidates"

    # Existing Undo/Job owners settle the in-memory Candidate append. The
    # Profile A path never invokes Project JSON persistence.
    assert len(state["history"]) == 1
    assert state["history"][0] == project_before
    job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    assert job["requests"][0]["registered_count"] == descriptor_count
    assert job["requests"][0]["state"] == "completed"
    assert job["state"] == "completed"
    assert attempt.protected_candidate_publication_state == "observed"
    assert attempt.protected_candidate_publication_locator is admission
    assert attempt.protected_candidate_publication_receipt.promotion_state == "protected_verified"
    assert attempt.protected_candidate_publication_receipt.registration_state == "registered"
    assert attempt.protected_candidate_publication_receipt.registered_count == descriptor_count
    publication_owner = runtime._generation_candidate_publication
    assert publication_owner._mode == "profile_a_protected"
    assert publication_owner._save_state == "not_attempted"
    assert publication_owner._save_callback_outcome == "not_attempted"
    assert publication_owner.save_for_characterization() == "save_not_authorized"
    assert Path(project_path).read_bytes() == project_file_before
    assert list(output_directory.iterdir()) == []
    assert set(promoted_root.iterdir()) == promoted_files_before
    assert set(capacity._ledger._operations) == ledger_operations_before
    assert set(capacity._ledger._reservations) == ledger_reservations_before
    assert integration._profile_a_candidate_publication_replay(admission) == (
        result, "protected_candidate_publication_already_observed",
    )
    duplicate, duplicate_status = owners[
        "publish_profile_a_generation_candidates_for_characterization"
    ](admission)
    assert duplicate is result
    assert duplicate_status == "protected_candidate_publication_already_observed"
    assert len(line.generated_candidates) == descriptor_count
    assert len(state["history"]) == 1

    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_genuine_registered_candidates_save_once_through_existing_project_writer(
        native_profile_a_dual_custody_worker_storage, tmp_path, descriptor_count):
    from core.io import load_project_from_json, resolve_project_asset_path
    from test_agent_generation_candidate_publication import app_owners
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedCandidatePublicationObservation,
        GenerationWorkerProtectedProjectSaveObservation,
    )

    (runtime, lifecycle, _worker, attempt, writer, state, output_directory,
     admission) = _prepare_profile_a_candidate_publication(
        native_profile_a_dual_custody_worker_storage,
        tmp_path / "comfy-output",
        descriptor_count=descriptor_count,
    )
    project = state["project"]
    project_path = lifecycle._project_path
    project_identity = id(project)
    original_json = Path(project_path).read_bytes()
    capacity = lifecycle._worker_storage_integration._capacity_owner
    integration = lifecycle._worker_storage_integration
    ledger_operations = set(capacity._ledger._operations)
    ledger_reservations = set(capacity._ledger._reservations)
    promoted_root = writer._roots["promoted_assets"]._path
    promoted_files = set(promoted_root.iterdir())
    history_before = copy.deepcopy(state["history"])

    owners = app_owners(state)
    owners["_PROJECT_AGENT_SESSION_RUNTIME"] = runtime
    locator, publication_status = owners[
        "publish_profile_a_generation_candidates_for_characterization"
    ](admission)
    assert publication_status == "protected_candidate_publication_registered"
    assert type(locator) is GenerationWorkerProtectedCandidatePublicationObservation
    assert len(state["history"]) == len(history_before) + 1
    publisher = runtime._generation_candidate_publication
    assert publisher._save_state == "not_attempted"
    assert publisher.save_for_characterization() == "save_not_authorized"
    from ui.agent_generation_candidate_publication import PublicationReceipt
    publication_receipt = publisher._records.get(locator.request_index)
    assert type(publication_receipt) is PublicationReceipt
    assert publication_receipt.request_index == locator.request_index
    assert publication_receipt.registration_state == "registered"
    assert publication_receipt.promotion_state == "protected_verified"
    assert publication_receipt.registered_count == locator.registered_candidate_count

    copied, copied_status = owners[
        "save_profile_a_generation_project_for_characterization"
    ](replace(locator))
    assert copied is None
    assert copied_status == "profile_a_project_save_evidence_unavailable"
    assert publisher._save_state == "not_attempted"
    assert integration._profile_a_project_save_state == "not_started"
    assert Path(project_path).read_bytes() == original_json

    saved, save_status = owners[
        "save_profile_a_generation_project_for_characterization"
    ](locator)
    assert save_status == "profile_a_project_saved"
    assert type(saved) is GenerationWorkerProtectedProjectSaveObservation
    assert saved.request_count == 1
    assert saved.registered_candidate_count == descriptor_count
    assert saved.save_state == "saved"
    assert saved.execution_available is False
    assert saved.protected_storage_available is False
    assert saved.promotion_available is False
    assert saved.candidate_publication_allowed is False
    assert saved.project_save_allowed is False
    assert saved.authorship == "unverified"
    assert id(state["project"]) == project_identity

    line = next(line for line in state["project"].prompt_lines
                if line.id == "illustration-001")
    in_memory_candidates = copy.deepcopy(line.generated_candidates)
    assert len(in_memory_candidates) == descriptor_count
    assert len(state["history"]) == len(history_before) + 1
    job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    assert job["save_state"] == "saved"
    assert job["requests"][0]["registered_count"] == descriptor_count
    assert job["requests"][0]["state"] == "completed"
    assert len(list(output_directory.iterdir())) == 0
    assert set(promoted_root.iterdir()) == promoted_files
    assert set(capacity._ledger._operations) == ledger_operations
    assert set(capacity._ledger._reservations) == ledger_reservations

    reopened = load_project_from_json(project_path)
    reopened_line = next(line for line in reopened.prompt_lines
                         if line.id == "illustration-001")
    reopened_candidates = reopened_line.generated_candidates
    assert len(reopened_candidates) == descriptor_count
    assert [row["generation_provenance"]["output_index"]
            for row in reopened_candidates] == list(range(1, descriptor_count + 1))
    for row, original in zip(reopened_candidates, in_memory_candidates):
        assert row["generation_provenance"] == original["generation_provenance"]
        resolved = Path(resolve_project_asset_path(row["path"], project_path))
        assert resolved == Path(original["path"])
        assert resolved.parent == promoted_root
        assert resolved.is_file()
    assert integration._project_reference.readiness()["status"] == "read_only_reference_observed"

    replay, replay_status = owners[
        "save_profile_a_generation_project_for_characterization"
    ](locator)
    assert replay is saved
    assert replay_status == "profile_a_project_save_already_observed"
    assert Path(project_path).read_bytes() != original_json

    written_json = Path(project_path).read_bytes()
    replay, replay_status = owners[
        "save_profile_a_generation_project_for_characterization"
    ](locator)
    assert replay is saved
    assert replay_status == "profile_a_project_save_already_observed"
    assert Path(project_path).read_bytes() == written_json
    assert len(state["history"]) == len(history_before) + 1
    assert len(line.generated_candidates) == descriptor_count
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["save_state"] == "saved"

    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def _profile_a_registered_candidate_save_locator(
        native_profile_a_dual_custody_worker_storage, tmp_path, *,
        writer_hook_factory=None):
    """Prepare a genuine G-G locator and optionally fault the existing JSON writer."""
    (runtime, lifecycle, _worker, _attempt, writer, state, output_directory,
     admission) = _prepare_profile_a_candidate_publication(
        native_profile_a_dual_custody_worker_storage,
        tmp_path / "comfy-output",
    )
    from test_agent_generation_candidate_publication import app_owners

    owners = app_owners(state)
    owners["_PROJECT_AGENT_SESSION_RUNTIME"] = runtime
    if writer_hook_factory is not None:
        original_writer = owners["save_project_to_json"]
        owners["_issue222_original_json_writer"] = original_writer
        owners["save_project_to_json"] = writer_hook_factory(
            original_writer, runtime,
        )
    locator, status = owners[
        "publish_profile_a_generation_candidates_for_characterization"
    ](admission)
    assert status == "protected_candidate_publication_registered"
    return runtime, lifecycle, writer, state, output_directory, owners, locator


def test_profile_a_project_save_definitive_writer_refusal_is_one_shot_and_keeps_json_unchanged(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    calls = []

    def callback_factory(_original_writer, _runtime):
        def refuse_before_write(_project, _project_path):
            calls.append("called")
            raise OSError("injected refusal before Project JSON write")
        return refuse_before_write

    runtime, lifecycle, writer, state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=callback_factory,
        )
    )
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    publisher = runtime._generation_candidate_publication
    integration = lifecycle._worker_storage_integration
    try:
        observation, status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert status == "profile_a_project_save_failed"
        assert observation.save_state == "save_failed"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() == original_json
        assert publisher._save_state == "save_failed"
        assert integration._profile_a_project_save_state == "save_failed"
        assert runtime.generation_jobs.snapshot(lifecycle._job_id)["save_state"] == "save_failed"

        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay is observation
        assert replay_status == "profile_a_project_save_already_observed"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() == original_json
    finally:
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_project_save_write_then_lost_ack_is_retained_uncertain_without_retry(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    calls = []

    def callback_factory(original_writer, _runtime):
        def write_then_lose_ack(project, project_path):
            calls.append("called")
            original_writer(project, project_path)
            raise OSError("lost save acknowledgement")
        return write_then_lose_ack

    runtime, lifecycle, writer, _state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=callback_factory,
        )
    )
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    publisher = runtime._generation_candidate_publication
    integration = lifecycle._worker_storage_integration
    try:
        observation, status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert status == "profile_a_project_save_uncertain"
        assert observation.save_state == "retained_uncertain"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() != original_json
        assert publisher._save_state == "save_uncertain"
        assert integration._profile_a_project_save_state == "retained_uncertain"

        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay is observation
        assert replay_status == "profile_a_project_save_already_observed"
        assert calls == ["called"]
    finally:
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_project_save_host_close_during_writer_retains_uncertain_evidence(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    calls = []

    def callback_factory(original_writer, runtime):
        def write_then_close_host(project, project_path):
            calls.append("called")
            result = original_writer(project, project_path)
            runtime.close()
            return result
        return write_then_close_host

    runtime, lifecycle, writer, _state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=callback_factory,
        )
    )
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    integration = lifecycle._worker_storage_integration
    try:
        observation, status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert status == "profile_a_project_save_uncertain"
        assert observation.save_state == "retained_uncertain"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() != original_json
        assert integration._profile_a_project_save_state == "retained_uncertain"

        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay is observation
        assert replay.save_state == "retained_uncertain"
        assert replay_status == "profile_a_project_save_already_observed"
        assert calls == ["called"]
    finally:
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


@pytest.mark.parametrize("owner_kind", ["capacity", "promotion", "admission"])
def test_profile_a_project_save_owner_close_during_writer_is_one_shot_uncertain(
        native_profile_a_dual_custody_worker_storage, tmp_path, monkeypatch, owner_kind):
    entered = threading.Event()
    continue_write = threading.Event()
    close_entered = threading.Event()
    calls = []

    def writer_hook_factory(original_writer, _runtime):
        def pause_after_write(project, project_path):
            calls.append("called")
            original_writer(project, project_path)
            entered.set()
            assert continue_write.wait(5)
        return pause_after_write

    runtime, lifecycle, writer, _state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=writer_hook_factory,
        )
    )
    integration = lifecycle._worker_storage_integration
    capacity = integration._capacity_owner
    attempt = integration._storage_preadmission_attempts[locator.request_index]
    if owner_kind == "capacity":
        terminal_owner = capacity
        boundary = capacity._project_save_boundary
        original_terminal = boundary.revoke

        def close_after_save_lease():
            close_entered.set()
            return original_terminal()

        monkeypatch.setattr(boundary, "revoke", close_after_save_lease)
        close_owner = terminal_owner.close
    elif owner_kind == "promotion":
        terminal_owner = attempt.promotion_owner
        original_terminal = terminal_owner._revoke_project_save_for_characterization

        def close_after_save_lease():
            close_entered.set()
            return original_terminal()

        monkeypatch.setattr(
            terminal_owner, "_revoke_project_save_for_characterization",
            close_after_save_lease,
        )
        close_owner = terminal_owner.close
    else:
        terminal_owner = runtime._generation_protected_candidate_admission
        original_terminal = terminal_owner._close_under_runtime_gate

        def close_admission():
            close_entered.set()
            return original_terminal()

        monkeypatch.setattr(terminal_owner, "_close_under_runtime_gate", close_admission)
        close_owner = terminal_owner.close

    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    publisher = runtime._generation_candidate_publication
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        saving = pool.submit(
            owners["save_profile_a_generation_project_for_characterization"], locator,
        )
        assert entered.wait(5)
        closing = pool.submit(close_owner)
        assert close_entered.wait(5)
        if owner_kind != "admission":
            # Capacity and Promotion close wait at their exact save lease.
            assert not closing.done()
        else:
            # Admission close is host-gated but does not wait for file I/O.
            closing.result(timeout=5)
        continue_write.set()
        observation, status = saving.result(timeout=10)
        closing.result(timeout=10)

        assert status == "profile_a_project_save_uncertain"
        assert observation.save_state == "retained_uncertain"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() != original_json
        assert publisher._save_state == "save_uncertain"
        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay is observation
        assert replay_status == "profile_a_project_save_already_observed"
        assert calls == ["called"]
    finally:
        continue_write.set()
        pool.shutdown(wait=True, cancel_futures=True)
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_capacity_invalidation_during_save_does_not_deadlock_or_confirm_save(
        native_profile_a_dual_custody_worker_storage, tmp_path, monkeypatch):
    callback_entered = threading.Event()
    continue_callback = threading.Event()
    native_check_failed = threading.Event()
    drain_started = threading.Event()
    calls = []

    def writer_hook_factory(original_writer, _runtime):
        def write_then_pause(project, project_path):
            calls.append("called")
            original_writer(project, project_path)
            callback_entered.set()
            assert continue_callback.wait(5)
            return True
        return write_then_pause

    runtime, lifecycle, writer, state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=writer_hook_factory,
        )
    )
    integration = lifecycle._worker_storage_integration
    capacity = integration._capacity_owner
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    project = state["project"]
    line = next(row for row in project.prompt_lines if row.id == "illustration-001")
    candidate_count = len(line.generated_candidates)
    history_count = len(state["history"])
    publisher = runtime._generation_candidate_publication

    def fail_native_root_check():
        native_check_failed.set()
        raise ValueError("native_root_changed")

    save_boundary = capacity._project_save_boundary
    original_drain = save_boundary.revoke_or_defer

    def observed_drain():
        drain_started.set()
        return original_drain()

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        saving = pool.submit(
            owners["save_profile_a_generation_project_for_characterization"], locator,
        )
        assert callback_entered.wait(5)
        # Force a real readiness refresh failure only after the save has crossed
        # the actual app writer boundary and is holding its capacity save lease.
        monkeypatch.setattr(capacity, "_check_roots", fail_native_root_check)
        monkeypatch.setattr(save_boundary, "revoke_or_defer", observed_drain)
        invalidating = pool.submit(capacity.readiness)
        assert native_check_failed.wait(5)
        assert drain_started.wait(5)
        assert not invalidating.done()

        continue_callback.set()
        observation, status = saving.result(timeout=10)
        invalidated_readiness = invalidating.result(timeout=10)

        assert status == "profile_a_project_save_uncertain"
        assert observation.save_state == "retained_uncertain"
        assert publisher._save_state == "save_uncertain"
        assert publisher._save_callback_outcome == "saved"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() != original_json
        assert capacity._invalid is True
        assert invalidated_readiness["native_root_identity"] == "unsafe_or_unavailable"
        assert invalidated_readiness["filesystem"] == "unverified"
        assert len(line.generated_candidates) == candidate_count
        assert len(state["history"]) == history_count

        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay is observation
        assert replay_status == "profile_a_project_save_already_observed"
        assert calls == ["called"]

        runtime.close()
        capacity.close()
        assert capacity._scope_lease.readiness()["status"] == "retained_uncertain"
        assert Path(capacity._scope_lease._path).exists()
    finally:
        continue_callback.set()
        pool.shutdown(wait=True, cancel_futures=True)
        runtime.close()
        capacity.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_save_thread_native_drift_readiness_is_unverified_and_uncertain(
        native_profile_a_dual_custody_worker_storage, tmp_path, monkeypatch):
    callback_returned = threading.Event()
    native_check_failed = threading.Event()
    calls = []

    def writer_hook_factory(original_writer, _runtime):
        def write_then_mark(project, project_path):
            calls.append("called")
            result = original_writer(project, project_path)
            callback_returned.set()
            return result
        return write_then_mark

    runtime, lifecycle, writer, state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=writer_hook_factory,
        )
    )
    integration = lifecycle._worker_storage_integration
    capacity = integration._capacity_owner
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    project = state["project"]
    line = next(row for row in project.prompt_lines if row.id == "illustration-001")
    candidate_count = len(line.generated_candidates)
    history_count = len(state["history"])
    publisher = runtime._generation_candidate_publication
    original_check = capacity._check_roots
    original_readiness = capacity.readiness
    post_callback_views = []

    def fail_after_save_callback():
        if callback_returned.is_set():
            native_check_failed.set()
            raise ValueError("native_root_changed")
        return original_check()

    def capture_readiness():
        result = original_readiness()
        if callback_returned.is_set():
            post_callback_views.append(result)
        return result

    monkeypatch.setattr(capacity, "_check_roots", fail_after_save_callback)
    monkeypatch.setattr(capacity, "readiness", capture_readiness)
    try:
        observation, status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert native_check_failed.is_set()
        assert post_callback_views
        assert all(view["native_root_identity"] == "unsafe_or_unavailable"
                   and view["filesystem"] == "unverified"
                   for view in post_callback_views)
        assert status == "profile_a_project_save_uncertain"
        assert observation.save_state == "retained_uncertain"
        assert publisher._save_state == "save_uncertain"
        assert publisher._save_callback_outcome == "saved"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() != original_json
        assert len(line.generated_candidates) == candidate_count
        assert len(state["history"]) == history_count

        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay is observation
        assert replay_status == "profile_a_project_save_already_observed"
        assert calls == ["called"]

        runtime.close()
        capacity.close()
        assert capacity._scope_lease.readiness()["status"] == "retained_uncertain"
        assert Path(capacity._scope_lease._path).exists()
    finally:
        runtime.close()
        capacity.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_project_save_job_ack_loss_after_replace_is_uncertain_and_not_retried(
        native_profile_a_dual_custody_worker_storage, tmp_path, monkeypatch):
    calls = []

    def callback_factory(original_writer, _runtime):
        def counted_writer(project, project_path):
            calls.append("called")
            return original_writer(project, project_path)
        return counted_writer

    runtime, lifecycle, writer, _state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=callback_factory,
        )
    )
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    publisher = runtime._generation_candidate_publication
    integration = lifecycle._worker_storage_integration
    monkeypatch.setattr(
        runtime.generation_jobs, "save_for_characterization",
        lambda *_args, **_kwargs: "acknowledgement_unknown",
    )
    try:
        observation, status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert status == "profile_a_project_save_uncertain"
        assert observation.save_state == "retained_uncertain"
        assert calls == ["called"]
        assert Path(project_path).read_bytes() != original_json
        assert publisher._save_state == "save_uncertain"
        assert integration._profile_a_project_save_state == "retained_uncertain"

        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay is observation
        assert replay_status == "profile_a_project_save_already_observed"
        assert calls == ["called"]
    finally:
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_project_save_host_close_during_native_revalidation_is_uncertain_without_write(
        native_profile_a_dual_custody_worker_storage, tmp_path, monkeypatch):
    entered = threading.Event()
    continue_readiness = threading.Event()
    calls = []

    def callback_factory(original_writer, _runtime):
        def counted_writer(project, project_path):
            calls.append("called")
            return original_writer(project, project_path)
        return counted_writer

    runtime, lifecycle, writer, _state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=callback_factory,
        )
    )
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    publisher = runtime._generation_candidate_publication
    integration = lifecycle._worker_storage_integration
    project_reference = integration._project_reference
    original_readiness = project_reference.readiness

    def pause_native_readiness():
        entered.set()
        assert continue_readiness.wait(5)
        return original_readiness()

    monkeypatch.setattr(project_reference, "readiness", pause_native_readiness)
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        saving = pool.submit(
            owners["save_profile_a_generation_project_for_characterization"], locator,
        )
        assert entered.wait(5)
        assert publisher._save_state == "saving"
        runtime.close()
        continue_readiness.set()
        observation, status = saving.result(timeout=5)
        assert status == "profile_a_project_save_uncertain"
        assert observation.save_state == "retained_uncertain"
        assert calls == []
        assert Path(project_path).read_bytes() == original_json
        assert publisher._save_state == "save_uncertain"
        assert integration._profile_a_project_save_state == "retained_uncertain"
    finally:
        continue_readiness.set()
        pool.shutdown(wait=True, cancel_futures=True)
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_project_save_concurrent_replay_cannot_call_writer_twice(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    entered = threading.Event()
    continue_write = threading.Event()
    calls = []

    def callback_factory(original_writer, _runtime):
        def pause_after_write(project, project_path):
            calls.append("called")
            result = original_writer(project, project_path)
            entered.set()
            assert continue_write.wait(5)
            return result
        return pause_after_write

    runtime, lifecycle, writer, _state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=callback_factory,
        )
    )
    integration = lifecycle._worker_storage_integration
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        first = pool.submit(
            owners["save_profile_a_generation_project_for_characterization"], locator,
        )
        assert entered.wait(5)
        replay, replay_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert replay_status == "profile_a_project_save_in_progress"
        assert replay.save_state == "saving"
        assert calls == ["called"]
        continue_write.set()
        observation, status = first.result(timeout=5)
        assert status == "profile_a_project_saved"
        assert observation.save_state == "saved"
        assert calls == ["called"]
    finally:
        continue_write.set()
        pool.shutdown(wait=True, cancel_futures=True)
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_project_save_prewrite_path_drift_does_not_consume_one_shot_attempt(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    calls = []

    def callback_factory(original_writer, _runtime):
        def counted_writer(project, project_path):
            calls.append("called")
            return original_writer(project, project_path)
        return counted_writer

    runtime, lifecycle, writer, state, _output, owners, locator = (
        _profile_a_registered_candidate_save_locator(
            native_profile_a_dual_custody_worker_storage, tmp_path,
            writer_hook_factory=callback_factory,
        )
    )
    project_path = lifecycle._project_path
    original_json = Path(project_path).read_bytes()
    publisher = runtime._generation_candidate_publication
    integration = lifecycle._worker_storage_integration
    try:
        state["current_project_path"] = project_path + ".changed"
        refused, refusal_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert refused is None
        assert refusal_status == "profile_a_project_save_target_mismatch"
        assert calls == []
        assert publisher._save_state == "not_attempted"
        assert integration._profile_a_project_save_state == "not_started"
        assert Path(project_path).read_bytes() == original_json

        state["current_project_path"] = project_path
        saved, save_status = owners[
            "save_profile_a_generation_project_for_characterization"
        ](locator)
        assert save_status == "profile_a_project_saved"
        assert saved.save_state == "saved"
        assert calls == ["called"]
    finally:
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_two_sequential_candidate_requests_share_one_job_save_after_complete_registration(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    from core.io import load_project_from_json, resolve_project_asset_path

    partial_save_attempts = []

    def attempt_partial_save_after_first(index, locator, _runtime, _lifecycle, _state, owners):
        if index == 0:
            partial_save_attempts.append(owners[
                "save_profile_a_generation_project_for_characterization"
            ](locator))

    (runtime, lifecycle, worker, writer, state, output_directory,
     owners, locators, attempts) = _prepare_profile_a_two_request_candidate_publications(
        native_profile_a_dual_custody_worker_storage,
        tmp_path / "comfy-output",
        after_request=attempt_partial_save_after_first,
    )
    project_path = lifecycle._project_path
    project_before_save = copy.deepcopy(state["project"])
    original_json = Path(project_path).read_bytes()
    publisher = runtime._generation_candidate_publication
    integration = lifecycle._worker_storage_integration
    assert len(locators) == 2
    assert [item.request_index for item in locators] == [0, 1]
    assert publisher._save_state == "not_attempted"
    assert len(state["history"]) == 2

    # The exact request-0 locator cannot authorize a Job save while request 1
    # is still unsent. That refusal does not consume the later exact save.
    assert len(partial_save_attempts) == 1
    refused, refusal_status = partial_save_attempts[0]
    assert refused is None
    assert refusal_status == "registration_incomplete"
    assert publisher._save_state == "not_attempted"
    assert integration._profile_a_project_save_state == "not_started"
    assert Path(project_path).read_bytes() == original_json
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["requests"][1]["state"] == "completed"

    # Diagnostic event maps are bounded. The Publisher retains the exact
    # accepted event pair for request 0, so an evicted diagnostic copy does
    # not erase its privately held save evidence.
    job = runtime.generation_jobs._jobs[lifecycle._job_id]
    inbox = runtime._generation_executor_inbox
    request_zero_sequences = [
        sequence for sequence, event in inbox._events.items()
        if event.progress.request_index == 0
        and event.progress.kind in {"remote_outputs_ready", "outputs_ready"}
    ]
    assert len(request_zero_sequences) == 2
    with runtime.generation_jobs._lock:
        for sequence in request_zero_sequences:
            job.events.pop(sequence, None)
    with inbox._lock:
        for sequence in request_zero_sequences:
            inbox._events.pop(sequence, None)

    history_before_save = copy.deepcopy(state["history"])
    capacity = integration._capacity_owner
    ledger_operations = set(capacity._ledger._operations)
    ledger_reservations = set(capacity._ledger._reservations)
    saved, save_status = owners[
        "save_profile_a_generation_project_for_characterization"
    ](locators[1])
    assert save_status == "profile_a_project_saved"
    assert saved.request_count == 2
    assert saved.registered_candidate_count == 2
    assert saved.save_state == "saved"
    assert state["history"] == history_before_save
    assert state["project"] is not None
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["save_state"] == "saved"
    assert set(capacity._ledger._operations) == ledger_operations
    assert set(capacity._ledger._reservations) == ledger_reservations

    in_memory = next(line for line in state["project"].prompt_lines
                     if line.id == "illustration-001").generated_candidates
    assert [item["generation_provenance"]["request_index"] for item in in_memory] == [0, 1]
    assert [item["run_index"] for item in in_memory] == [1, 2]
    reopened = load_project_from_json(project_path)
    persisted = next(line for line in reopened.prompt_lines
                     if line.id == "illustration-001").generated_candidates
    assert [item["generation_provenance"]["request_index"] for item in persisted] == [0, 1]
    for item in persisted:
        path = Path(resolve_project_asset_path(item["path"], project_path))
        assert path.is_file()
        assert path.parent == writer._roots["promoted_assets"]._path
    assert len(next(line for line in project_before_save.prompt_lines
                    if line.id == "illustration-001").generated_candidates) == 2

    runtime.close()
    worker.close_for_characterization()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_candidate_publication_rejects_comfy_output_inside_private_scope(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    from test_agent_generation_candidate_publication import app_owners

    roots, capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    output_directory = Path(capacity._scope) / "comfy-output-overlap"
    (runtime, lifecycle, _worker, attempt, writer, state, _output_directory,
     admission) = _prepare_profile_a_candidate_publication(
        native_profile_a_dual_custody_worker_storage, output_directory,
    )
    owners = app_owners(state)
    owners["_PROJECT_AGENT_SESSION_RUNTIME"] = runtime
    project_before = copy.deepcopy(state["project"])
    job_before = runtime.generation_jobs.snapshot(lifecycle._job_id)
    result, status = owners[
        "publish_profile_a_generation_candidates_for_characterization"
    ](admission)

    assert status == "protected_candidate_publication_uncertain"
    assert result.status == "protected_candidate_publication_uncertain"
    assert attempt.protected_candidate_publication_state == "retained_uncertain"
    assert runtime._generation_candidate_publication is None
    assert state["project"] == project_before
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) == job_before
    assert next(line for line in state["project"].prompt_lines
                if line.id == "illustration-001").generated_candidates == []
    assert list(output_directory.iterdir()) == []
    assert all(not list(root._path.glob("*.tmp")) for root in roots.values())
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_candidate_publication_retains_uncertain_close_race(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    from test_agent_generation_candidate_publication import app_owners

    (runtime, lifecycle, _worker, attempt, writer, state, _output_directory,
     admission) = _prepare_profile_a_candidate_publication(
        native_profile_a_dual_custody_worker_storage,
        tmp_path / "comfy-output-race",
    )
    owners = app_owners(state)
    owners["_PROJECT_AGENT_SESSION_RUNTIME"] = runtime
    promoter = attempt.promotion_owner
    original_inspect = promoter._inspect_for_candidate_admission_for_characterization
    entered, release = threading.Event(), threading.Event()

    def blocked_inspect(receipt, freshness):
        entered.set()
        assert release.wait(5)
        return original_inspect(receipt, freshness)

    promoter._inspect_for_candidate_admission_for_characterization = blocked_inspect
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            owners["publish_profile_a_generation_candidates_for_characterization"], admission,
        )
        assert entered.wait(5)
        runtime.close()
        assert attempt.protected_candidate_publication_state == "retained_uncertain"
        release.set()
        result, status = future.result(timeout=10)

    assert result is not None
    assert result.status == "protected_candidate_publication_uncertain"
    assert result.registration_state == "registration_uncertain"
    assert status == "protected_candidate_publication_uncertain"
    project = state["project"]
    line = next(line for line in project.prompt_lines if line.id == "illustration-001")
    assert line.generated_candidates == []
    publisher = runtime._generation_candidate_publication
    assert publisher._records[0].registered_count == 0
    assert publisher._records[0].registration_state != "registered"
    duplicate, duplicate_status = owners[
        "publish_profile_a_generation_candidates_for_characterization"
    ](admission)
    assert duplicate is result
    assert duplicate_status == "protected_candidate_publication_uncertain"
    assert line.generated_candidates == []
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_candidate_publication_serializes_capacity_close_at_commit_boundary(
        native_profile_a_dual_custody_worker_storage, tmp_path):
    from test_agent_generation_candidate_publication import app_owners

    (runtime, _lifecycle, _worker, attempt, writer, state, _output_directory,
     admission) = _prepare_profile_a_candidate_publication(
        native_profile_a_dual_custody_worker_storage,
        tmp_path / "comfy-output-capacity-close",
    )
    owners = app_owners(state)
    owners["_PROJECT_AGENT_SESSION_RUNTIME"] = runtime
    capacity = runtime._generation_original_host_lifecycle._worker_storage_integration._capacity_owner
    original_persistent_appender = owners["_append_persistent_line_candidates"]
    appender_entered, release_appender = threading.Event(), threading.Event()
    close_entered, close_done = threading.Event(), threading.Event()
    original_revoke = capacity._candidate_publication_boundary.revoke
    publication_result = []

    def blocked_persistent_appender(*args, **kwargs):
        appender_entered.set()
        assert release_appender.wait(5)
        return original_persistent_appender(*args, **kwargs)

    def revoke_and_signal():
        close_entered.set()
        return original_revoke()

    # Keep the trusted app callback identity intact; pause at its lower-level
    # in-memory Candidate append boundary instead.
    owners["_append_persistent_line_candidates"] = blocked_persistent_appender
    capacity._candidate_publication_boundary.revoke = revoke_and_signal

    def publish():
        publication_result.append(
            owners["publish_profile_a_generation_candidates_for_characterization"](admission)
        )

    def close_capacity():
        capacity.close()
        close_done.set()

    publish_thread = threading.Thread(target=publish)
    close_thread = None
    try:
        publish_thread.start()
        assert appender_entered.wait(10)
        close_thread = threading.Thread(target=close_capacity)
        close_thread.start()
        assert close_entered.wait(5)
        assert capacity._candidate_publication_revoking is True
        assert close_done.is_set() is False
        assert publish_thread.is_alive()
        release_appender.set()
        publish_thread.join(10)
        close_thread.join(10)
        assert not publish_thread.is_alive()
        assert not close_thread.is_alive()
        assert close_done.is_set()
        assert capacity._closed is True
        result, status = publication_result[0]
        assert status == "protected_candidate_publication_registered"
        assert result.registration_state == "registered"
        assert attempt.protected_candidate_publication_state == "observed"
        line = next(line for line in state["project"].prompt_lines if line.id == "illustration-001")
        assert len(line.generated_candidates) == 1
    finally:
        release_appender.set()
        publish_thread.join(10)
        if close_thread is not None:
            close_thread.join(10)
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def _assert_uncertain_promotion_prevents_profile_a_host_rebind(
        capacity, reference, project_path, original_lifecycle, original_integration):
    assert original_lifecycle._state == "closed"
    assert original_integration._state == "closed"
    assert not original_integration._uncertain_leases
    assert capacity._scope_lease._state == "held"
    assert capacity._scope_lease.readiness()["status"] == "held"
    assert capacity._scope_lease_retention_reason() == "uncertain"
    original_references = tuple(capacity._host_lifecycle_refs)
    assert original_references == (original_lifecycle,)

    second_runtime, _route, _state, second_lifecycle = _ready_generation_at_project_path(
        project_path,
    )
    try:
        assert second_lifecycle is not original_lifecycle
        # In the in-flight case a partial CREATE_NEW invalidates the capacity
        # owner before any later binding can reach lifecycle publication. The
        # privately committed case specifically exercises lifecycle retention.
        expected_error = ("profile_a_storage_unavailable" if capacity._invalid
                          else "profile_a_storage_lifecycle_unsettled")
        with pytest.raises(ValueError, match=expected_error):
            capacity._bind_profile_a_lifecycle_for_characterization(
                second_lifecycle, reference,
            )
        host_status = second_runtime.bind_generation_profile_a_storage_for_characterization(
            capacity, reference,
        )
        assert host_status in {
            "storage_binding_unavailable", "storage_observation_unavailable",
        }
        assert tuple(capacity._host_lifecycle_refs) == original_references
        assert original_lifecycle in capacity._host_lifecycle_refs
        assert second_lifecycle not in capacity._host_lifecycle_refs
        assert capacity._scope_lease._state == "held"
        assert capacity._scope_lease_retention_reason() == "uncertain"
    finally:
        second_runtime.close()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_staged_images_accept_as_exact_private_batch_without_new_write(
        native_profile_a_worker_storage, descriptor_count):
    from core import generation_windows_protected_assets as assets
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedAcceptanceObservation,
    )

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, prepared, _preadmission, _evidence,
     attempt, writer, staged, provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=descriptor_count,
    )
    operation_keys = set(capacity._ledger._operations)
    reservation_keys = set(capacity._ledger._reservations)
    file_keys = set(writer._files)
    write_count = len(writer._stream_attempts)
    expected_ids = tuple(item.identity for item in attempt.remote_receipt.images)
    try:
        accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        )
        assert type(accepted_observation) is GenerationWorkerProtectedAcceptanceObservation, status
        assert status == "protected_image_batch_accepted_non_authoritative"
        assert (accepted_observation.request_index,
                accepted_observation.accepted_image_count) == (0, descriptor_count)
        assert accepted_observation.execution_available is False
        assert accepted_observation.protected_storage_available is False
        assert accepted_observation.promotion_available is False
        assert accepted_observation.candidate_publication_allowed is False
        assert accepted_observation.project_save_allowed is False
        assert accepted_observation.authorship == "unverified"
        assert not ({"batch_receipt", "accepted", "acceptance_owner", "images", "paths",
                     "native_handle", "write_admission"}
                    & set(accepted_observation.__dataclass_fields__))

        key = (prepared.request_id, attempt.remote_receipt.identity)
        batch = writer._stream_batches[key]
        accepted = writer._stream_batch_acceptances[key]
        assert type(batch) is assets.VerifiedProtectedImageBatchReceipt
        assert batch.observations is attempt.acceptance_observations
        assert tuple(item.descriptor_identity for item in batch.observations) == expected_ids
        assert type(accepted).__name__ == "AcceptedProtectedOutputBatch"
        assert attempt.acceptance_owner._receipt is accepted
        assert attempt.acceptance_state == "accepted_non_authoritative"
        assert set(capacity._ledger._operations) == operation_keys
        assert set(capacity._ledger._reservations) == reservation_keys
        assert set(writer._files) == file_keys
        assert len(writer._stream_attempts) == write_count == descriptor_count
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
        assert capacity._ledger._reservations[attempt.reservation]["write"] is attempt.writer_admission
        assert capacity._ledger._reservations[attempt.reservation]["completed_observed_delta"][
            "temporary_containment"
        ] == (len(data) * descriptor_count, descriptor_count)

        with pytest.raises(ValueError, match="profile_a_writer_handoff_required"):
            writer.commit_verified_remote_image_batch_for_characterization(
                runtime._generation_original_host_lifecycle._envelope,
                prepared, attempt.remote_receipt, attempt.acceptance_observations,
                host_freshness=lambda *_args: True,
            )
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_evidence_unavailable")
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()
        assert capacity._scope_lease._state == "released"


@pytest.mark.parametrize("descriptor_count", [1, 2])
def test_profile_a_accepted_batch_reserves_exact_destination_capacity_without_promotion(
        native_profile_a_worker_storage, descriptor_count):
    from core.generation_windows_protected_promotion import (
        ProtectedDurablePromotionCharacterization,
    )
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedPromotionPreflightObservation,
    )

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=descriptor_count,
    )
    accepted_observation, accepted_status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert accepted_status == "protected_image_batch_accepted_non_authoritative"
    assert attempt.acceptance_observation is accepted_observation
    accepted = attempt.accepted_batch
    before_files = dict(writer._files)
    before_promotions = dict(writer._stream_promotions)
    before_operations = set(capacity._ledger._operations)
    before_reservations = set(capacity._ledger._reservations)
    source_operation = capacity._ledger._reservations[attempt.reservation]
    assert source_operation["state"] == "completed"

    copied = replace(accepted_observation)
    assert copied == accepted_observation and copied is not accepted_observation
    assert runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        copied, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_preflight_evidence_unavailable")

    result, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )
    assert type(result) is GenerationWorkerProtectedPromotionPreflightObservation
    assert status == "protected_promotion_preflight_non_authoritative"
    assert (result.status, result.request_index, result.reserved_image_count) == (
        "protected_promotion_preflight_non_authoritative", 0, descriptor_count,
    )
    assert result.execution_available is False
    assert result.protected_storage_available is False
    assert result.promotion_available is False
    assert result.candidate_publication_allowed is False
    assert result.project_save_allowed is False
    assert result.authorship == "unverified"
    assert not ({"operation", "reservation", "write_admission", "paths", "images", "receipt"}
                & set(result.__dataclass_fields__))

    assert attempt.promotion_preflight_observation is result
    assert attempt.promotion_preflight_state == "reserved_non_authoritative"
    assert set(capacity._ledger._operations) == before_operations | {
        attempt.promotion_capacity_operation,
    }
    assert set(capacity._ledger._reservations) == before_reservations | {
        attempt.promotion_capacity_reservation,
    }
    destination_record = capacity._ledger._reservations[attempt.promotion_capacity_reservation]
    assert destination_record["state"] == "reserved"
    assert destination_record.get("write") is None
    assert destination_record["estimates"] == {
        "promoted_assets": (len(data) * descriptor_count, descriptor_count),
    }
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    assert capacity._ledger._reserved["promoted_assets"] == [len(data) * descriptor_count,
                                                               descriptor_count]
    assert writer._files == before_files
    assert writer._stream_promotions == before_promotions == {}
    assert accepted._protected_owner is writer
    assert not attempt.promotion_preflight_observation.promotion_available
    with pytest.raises(ValueError, match="profile_a_promotion_host_bridge_required"):
        ProtectedDurablePromotionCharacterization.create_for_characterization(
            writer, attempt.acceptance_owner, accepted,
            characterization=True, disposable_opt_in=True,
        )
    assert runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_preflight_evidence_unavailable")

    try:
        assert runtime.cancel_generation_worker_promotion_preflight_for_characterization(
            result,
        ) == "cancelled_before_write"
        assert destination_record["state"] == "cancelled"
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
        assert writer._files == before_files
        assert writer._stream_promotions == {}
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_promotion_preflight_refuses_shared_capacity_before_destination_write(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=2,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    source_bytes = len(data) * 2
    # Keep enough room for the observed staging source, but not for its full
    # promoted copy. The real ledger must reject before any destination file.
    capacity._ledger._limits = replace(
        capacity._ledger._limits,
        shared_temporary_and_promoted_bytes=source_bytes * 2 - 1,
    )
    before_files = dict(writer._files)
    before_reservations = set(capacity._ledger._reservations)
    result, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )
    assert result is None
    assert status == "shared_asset_capacity_exceeded"
    assert attempt.promotion_preflight_state == "refused"
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    assert capacity._ledger._reserved["promoted_assets"] == [0, 0]
    assert writer._files == before_files
    assert set(capacity._ledger._reservations) == before_reservations
    assert not writer._stream_promotions
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_promotion_preflight_refuses_full_batch_entry_capacity(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=16,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    before_files = dict(writer._files)
    before_reservations = set(capacity._ledger._reservations)
    before_promoted_reserved = list(capacity._ledger._reserved["promoted_assets"])

    result, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )

    # The existing shared entry ceiling is 16. Retaining the 16 staging
    # images means there is no room to reserve a second 16-file destination.
    # Refusal is the safe result until a separately reviewed capacity policy
    # can account for the retained source and destination together.
    assert result is None
    assert status == "shared_asset_capacity_exceeded"
    assert attempt.promotion_preflight_state == "refused"
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    assert capacity._ledger._reservations[attempt.reservation]["completed_observed_delta"][
        "temporary_containment"
    ] == (len(data) * 16, 16)
    assert capacity._ledger._reserved["promoted_assets"] == before_promoted_reserved == [0, 0]
    assert writer._files == before_files
    assert set(capacity._ledger._reservations) == before_reservations
    assert not writer._stream_promotions
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_dual_custody_preflights_exact_sixteen_image_batch_without_promotion_write(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=16,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    assert len(writer._files) == 16
    with pytest.raises(ValueError, match="profile_a_writer_handoff_required"):
        writer.create_image_for_characterization("promoted_assets", data)
    with pytest.raises(ValueError, match="profile_a_writer_handoff_required"):
        writer.create_image_with_admission_for_characterization(
            capacity, "unissued-promotion-operation", "promoted_assets", data,
            characterization=True, disposable_opt_in=True,
        )
    before_files = dict(writer._files)
    before_stream_attempts = tuple(writer._stream_attempts)
    before_provider_lookups = tuple(provider.lookups)
    before_provider_streams = tuple(provider.streams)
    before_promotions = dict(writer._stream_promotions)
    before_promotion_entries = set(path.name for path in roots["promoted_assets"]._path.iterdir())

    result, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )

    assert status == "protected_promotion_preflight_non_authoritative"
    assert result is not None and result.reserved_image_count == 16
    assert result.execution_available is False
    assert result.protected_storage_available is False
    assert result.promotion_available is False
    assert result.candidate_publication_allowed is False
    assert result.project_save_allowed is False
    assert result.authorship == "unverified"
    assert tuple(provider.lookups) == before_provider_lookups
    assert tuple(provider.streams) == before_provider_streams
    assert tuple(writer._stream_attempts) == before_stream_attempts
    assert writer._files == before_files
    assert writer._stream_promotions == before_promotions
    assert set(path.name for path in roots["promoted_assets"]._path.iterdir()) == before_promotion_entries == set()

    capacity_view = capacity.readiness()
    assert capacity_view["asset_capacity_policy"] == "profile_a_dual_custody_16x16_v1"
    assert capacity_view["shared_asset_entry_limit"] == 32
    assert capacity_view["shared_asset_byte_limit"] == 256 * 1024 * 1024
    rows = {row["purpose"]: row for row in capacity_view["roots"]}
    assert rows["temporary_containment"]["observed_used_entries"] == 16
    assert rows["temporary_containment"]["observed_used_bytes"] == len(data) * 16
    assert rows["promoted_assets"]["reserved_entries"] == 16
    assert rows["promoted_assets"]["reserved_bytes"] == len(data) * 16
    assert (rows["temporary_containment"]["observed_used_entries"]
            + rows["promoted_assets"]["reserved_entries"]) == 32
    assert (rows["temporary_containment"]["observed_used_bytes"]
            + rows["promoted_assets"]["reserved_bytes"]) == len(data) * 32

    writer_view = writer.readiness()
    assert writer_view["asset_capacity_policy"] == "profile_a_dual_custody_16x16_v1"
    assert writer_view["inventory_entry_limit"] == 32
    assert writer_view["purpose_entry_limits"] == {
        "temporary_containment": 16, "promoted_assets": 16,
    }
    assert writer_view["retained_file_count"] == 16
    assert len(writer._inventory()) == 16
    assert {purpose for purpose, _root, _path in writer._inventory()} == {"temporary_containment"}

    runtime.close()
    assert attempt.promotion_preflight_state == "cancelled"
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation]["state"] == "cancelled"
    assert writer._files == before_files
    assert writer._stream_promotions == before_promotions
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_original_host_promotion_commits_exact_reserved_batch_privately(
        native_profile_a_dual_custody_worker_storage, descriptor_count):
    from core import generation_windows_protected_promotion as promotion

    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=descriptor_count,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    operation, reservation = (attempt.promotion_capacity_operation,
                              attempt.promotion_capacity_reservation)
    operations_before = set(capacity._ledger._operations)
    reservations_before = set(capacity._ledger._reservations)
    source_bytes = tuple(
        writer._bytes(writer._files[(item.image.purpose, item.image.storage_identity)])
        for item in attempt.acceptance_observations
    )
    source_records = tuple(
        writer._files[(item.image.purpose, item.image.storage_identity)]
        for item in attempt.acceptance_observations
    )

    public_result, status = runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )

    assert public_result is None
    assert status == "protected_promotion_host_publication_deferred"
    assert attempt.promotion_preflight_state == "private_committed_host_publication_pending"
    receipt = attempt.promotion_receipt
    promoter = attempt.promotion_owner
    assert type(receipt) is promotion.VerifiedProtectedPromotionReceipt
    assert promoter._receipt is receipt
    assert writer._stream_promotions[(attempt.prepared.request_id,
                                      attempt.remote_receipt.identity)] is receipt
    assert len(receipt.images) == descriptor_count
    assert tuple(row.descriptor_identity for row in receipt.images) == tuple(
        descriptor.identity for descriptor in attempt.remote_receipt.images)
    assert set(capacity._ledger._operations) == operations_before
    assert set(capacity._ledger._reservations) == reservations_before
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    destination_record = capacity._ledger._reservations[reservation]
    assert destination_record["operation"] is operation
    assert destination_record["state"] == "completed"
    assert destination_record["completed_observed_delta"]["promoted_assets"] == (
        len(data) * descriptor_count, descriptor_count,
    )
    assert destination_record["completed_observed_delta"]["temporary_containment"] == (0, 0)
    assert len(writer._files) == descriptor_count * 2
    assert tuple(writer._bytes(record) for record in source_records) == source_bytes
    for row, expected_bytes in zip(receipt.images, source_bytes):
        image = row.promoted_image
        key = ("promoted_assets", image.storage_identity)
        record = writer._files[key]
        assert record[0].parent == roots["promoted_assets"]._path
        assert record[1] is not None and record[2] is not None and record[3] is not None
        assert writer._observe(image.storage_identity, "promoted_assets", record[0].suffix[1:]) == image
        assert writer._bytes(record) == expected_bytes
        assert image.storage_identity != row.source_observation.image.storage_identity
        assert image.content_sha256 == row.source_observation.image.content_sha256
    assert writer.readiness()["inventory_entry_limit"] == 32
    rows = {row["purpose"]: row for row in capacity.readiness()["roots"]}
    assert (rows["temporary_containment"]["observed_used_entries"],
            rows["promoted_assets"]["observed_used_entries"]) == (
                descriptor_count, descriptor_count,
            )
    assert (rows["temporary_containment"]["observed_used_bytes"]
            + rows["promoted_assets"]["observed_used_bytes"]) == len(data) * descriptor_count * 2
    assert promoter.execution_available is False
    assert promoter.protected_storage_available is False
    assert promoter.promotion_available is False
    assert promoter.candidate_publication_allowed is False
    assert promoter.project_save_allowed is False
    assert promoter.authorship == "unverified"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_preflight_evidence_unavailable")

    runtime.close()
    assert attempt.promotion_preflight_state == "retained_uncertain"
    assert capacity._scope_lease_retention_reason() == "uncertain"
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_original_host_promotion_publishes_exact_batch_count_once(
        native_profile_a_dual_custody_worker_storage, descriptor_count):
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedPromotionObservation,
    )

    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=descriptor_count,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_host_publication_deferred")

    operation_keys = set(capacity._ledger._operations)
    reservation_keys = set(capacity._ledger._reservations)
    file_keys = set(writer._files)
    stream_attempts = tuple(writer._stream_attempts)
    promotion_receipt = attempt.promotion_receipt
    destination_delta = capacity._ledger._reservations[
        attempt.promotion_capacity_reservation
    ]["completed_observed_delta"]

    # Equal fields on a copied preflight are not custody and must not consume
    # the exact observation retained by the original Host attempt.
    assert runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
        replace(preflight), characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_publication_evidence_unavailable")
    assert attempt.promotion_preflight_state == "private_committed_host_publication_pending"
    assert capacity._ledger._reservations[
        attempt.promotion_capacity_reservation
    ]["state"] == "completed"

    result, status = runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_published_non_authoritative"
    assert type(result) is GenerationWorkerProtectedPromotionObservation
    assert result.request_index == attempt.lease.request_index
    assert result.promoted_image_count == descriptor_count
    assert result.execution_available is False
    assert result.protected_storage_available is False
    assert result.promotion_available is False
    assert result.candidate_publication_allowed is False
    assert result.project_save_allowed is False
    assert result.authorship == "unverified"
    assert set(result.__dataclass_fields__) == {
        "status", "request_index", "promoted_image_count", "execution_available",
        "protected_storage_available", "promotion_available",
        "candidate_publication_allowed", "project_save_allowed", "authorship",
    }
    assert attempt.promotion_publication_observation is result
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert attempt.promotion_receipt is promotion_receipt
    assert attempt.promotion_owner._receipt is promotion_receipt
    assert capacity._ledger._reservations[
        attempt.promotion_capacity_reservation
    ]["state"] == "completed"
    assert capacity._ledger._reservations[
        attempt.promotion_capacity_reservation
    ]["completed_observed_delta"] == destination_delta
    assert set(capacity._ledger._operations) == operation_keys
    assert set(capacity._ledger._reservations) == reservation_keys
    assert set(writer._files) == file_keys
    assert tuple(writer._stream_attempts) == stream_attempts

    assert runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_publication_evidence_unavailable")
    assert attempt.promotion_publication_observation is result
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    assert attempt.promotion_publication_observation is result
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    writer.close()
    assert capacity._scope_lease_retention_reason() == "settled"
    capacity.close()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_published_promotion_emits_one_exact_outputs_ready_event(
        native_profile_a_dual_custody_worker_storage, descriptor_count):
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerExecutorEventChainObservation,
        GenerationWorkerProtectedOutputsReadyObservation,
    )

    _roots, capacity, _reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
            descriptor_count=descriptor_count,
        )
    )
    project = lifecycle._project_ref()
    project_before = copy.deepcopy(project)
    project_file_before = project_path.read_bytes()
    job_before = runtime.generation_jobs.snapshot(lifecycle._job_id)
    integration = lifecycle._worker_storage_integration
    inbox = runtime._generation_executor_inbox
    event_count_before = len(inbox._authority_events)
    ledger_operations_before = set(capacity._ledger._operations)
    ledger_reservations_before = set(capacity._ledger._reservations)
    file_keys_before = set(writer._files)
    promotion_receipt = attempt.promotion_receipt
    remote_receipt = attempt.remote_receipt

    result, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )

    assert status == "protected_outputs_ready_event_accepted_non_authoritative"
    assert type(result) is GenerationWorkerProtectedOutputsReadyObservation
    assert (result.request_index, result.output_count) == (0, descriptor_count)
    assert result.candidate_eligibility == "not_established"
    assert result.execution_available is False
    assert result.protected_storage_available is False
    assert result.promotion_available is False
    assert result.candidate_publication_allowed is False
    assert result.project_save_allowed is False
    assert result.authorship == "unverified"
    assert not ({"promotion_receipt", "remote_receipt", "event", "images", "paths"}
                & set(result.__dataclass_fields__))

    marker = integration._profile_a_outputs_ready_event_attempts[0]
    event = marker.event
    assert marker.state == "events_accepted"
    assert marker.preadmission_attempt is attempt
    assert marker.promotion_observation is publication
    assert marker.promotion_receipt is promotion_receipt
    assert marker.remote_receipt is remote_receipt
    assert promotion_receipt._promotion_owner is marker.promotion_owner
    assert promotion_receipt.remote_receipt_identity == remote_receipt.identity
    assert type(event).__name__ == "ExecutorEvent"
    assert event.progress.kind == "outputs_ready"
    assert event.progress.sequence == 4
    assert event.progress.request_index == 0
    assert event.progress.prompt_id is None and event.progress.cause is None
    assert event.progress.output_count == descriptor_count
    assert event.outputs.receipt_id == promotion_receipt.identity[:32]
    assert event.outputs.receipt_id != remote_receipt.identity[:32]
    assert event.outputs.output_count == descriptor_count
    assert inbox._events[event.progress.sequence] is event
    assert sum(item is event for item in inbox._authority_events) == 1
    assert len(inbox._authority_events) == event_count_before + 1
    assert tuple(item.progress.kind for item in inbox._authority_events) == (
        "submission_started", "submitted", "remote_outputs_ready", "outputs_ready",
    )

    job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    assert job["event_count"] == 4
    assert job["requests"][0]["state"] == "awaiting_host_registration"
    assert job["requests"][0]["remote_output_count"] == descriptor_count
    assert job["requests"][0]["output_count"] == descriptor_count
    assert job["requests"][0]["registered_count"] == 0
    assert job["registered_count"] == 0
    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        {"project": project, "current_project_path": lifecycle._project_path},
        0, characterization=True, disposable_opt_in=True,
    )
    assert type(audit) is GenerationWorkerExecutorEventChainObservation
    assert audit.status == "profile_a_outputs_ready_event_observed"
    assert audit.accepted_event_kinds == (
        "submission_started", "submitted", "remote_outputs_ready", "outputs_ready",
    )
    assert audit.profile_a_event_kinds == audit.accepted_event_kinds
    assert audit.next_required_event is None
    assert audit.candidate_eligibility == "not_established"
    assert audit.execution_available is False
    assert audit.protected_storage_available is False
    assert audit.promotion_available is False
    assert audit.candidate_publication_allowed is False
    assert audit.project_save_allowed is False
    assert audit.authorship == "unverified"
    assert runtime._generation_protected_candidate_admission is None
    assert set(capacity._ledger._operations) == ledger_operations_before
    assert set(capacity._ledger._reservations) == ledger_reservations_before
    assert set(writer._files) == file_keys_before
    assert project == project_before
    assert project_path.read_bytes() == project_file_before
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) != job_before

    duplicate, duplicate_status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert duplicate is None
    assert duplicate_status == "protected_outputs_ready_evidence_unavailable"
    assert len(inbox._authority_events) == event_count_before + 1
    assert marker.event is event and marker.state == "events_accepted"
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_outputs_ready_rejects_copied_locator_then_accepts_exact_observation(
        native_profile_a_dual_custody_worker_storage):
    _roots, _capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
        )
    )
    integration = lifecycle._worker_storage_integration
    inbox = runtime._generation_executor_inbox
    assert runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        replace(publication), characterization=True, disposable_opt_in=True,
    ) == (None, "protected_outputs_ready_evidence_unavailable")
    assert integration._profile_a_outputs_ready_event_attempts == {}
    assert not any(event.progress.kind == "outputs_ready" for event in inbox._events.values())
    result, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_outputs_ready_event_accepted_non_authoritative"
    assert result.output_count == len(attempt.promotion_receipt.images)
    assert len([event for event in inbox._authority_events
                if event.progress.kind == "outputs_ready"]) == 1
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_genuine_candidate_admission_is_read_only_and_one_shot(
        native_profile_a_dual_custody_worker_storage, descriptor_count, monkeypatch):
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedCandidateAdmissionObservation,
        GenerationWorkerProtectedCandidateAdmissionPreflightObservation,
    )
    from ui.agent_generation_protected_candidate_admission import (
        GenerationProtectedCandidateAdmission,
        ProtectedCandidateAdmissionObservation,
        ProtectedCandidateAdmissionResult,
    )

    def forbidden_candidate_commit(*_args, **_kwargs):
        raise AssertionError("G-F must not enter Candidate publication custody")

    monkeypatch.setattr(
        GenerationProtectedCandidateAdmission,
        "_candidate_publication_commit_for_characterization",
        forbidden_candidate_commit,
    )

    roots, capacity, _reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
            descriptor_count=descriptor_count,
        )
    )
    project = lifecycle._project_ref()
    project_before = copy.deepcopy(project)
    project_file_before = project_path.read_bytes()
    candidates_before = tuple(tuple(line.generated_candidates) for line in project.prompt_lines)
    job_before = runtime.generation_jobs.snapshot(lifecycle._job_id)
    integration = lifecycle._worker_storage_integration
    inbox = runtime._generation_executor_inbox
    inbox_events_before = tuple(inbox._events.items())
    inbox_authority_before = tuple(inbox._authority_events)
    ledger_operations_before = set(capacity._ledger._operations)
    ledger_reservations_before = set(capacity._ledger._reservations)
    writer_file_keys_before = set(writer._files)

    outputs_ready, event_status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert event_status == "protected_outputs_ready_event_accepted_non_authoritative"
    output_marker = integration._profile_a_outputs_ready_event_attempts[0]
    assert output_marker.observation is outputs_ready

    if descriptor_count == 1:
        source_event = integration._profile_a_submission_started_events[0]
        source_sequence = source_event.progress.sequence
        inbox._events[source_sequence] = replace(source_event)
        assert runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
            outputs_ready, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_candidate_admission_evidence_unavailable")
        inbox._events[source_sequence] = source_event
        source_position = next(
            index for index, item in enumerate(inbox._authority_events)
            if item is source_event
        )
        inbox._authority_events[source_position] = replace(source_event)
        assert runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
            outputs_ready, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_candidate_admission_evidence_unavailable")
        inbox._authority_events[source_position] = source_event
        assert attempt.protected_candidate_admission_state == "not_started"

    # Equal-valued copies do not consume the genuine one-shot bridge.
    assert runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
        replace(outputs_ready), characterization=True, disposable_opt_in=True,
    ) == (None, "protected_candidate_admission_evidence_unavailable")
    assert attempt.protected_candidate_admission_state == "not_started"

    # The older 19G-A preflight is an independent non-authoritative observation.
    # Exercise it on both sides of G-F without letting it claim G-F's attempt.
    run_legacy_preflight_before = descriptor_count == 1
    if run_legacy_preflight_before:
        legacy, legacy_status = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
            publication, characterization=True, disposable_opt_in=True,
        )
        assert legacy_status == "protected_candidate_admission_preflight_non_authoritative"
        assert type(legacy) is GenerationWorkerProtectedCandidateAdmissionPreflightObservation
        assert legacy.candidate_eligibility == "not_established"

    project_before_gf = copy.deepcopy(project)
    project_file_before_gf = project_path.read_bytes()
    candidate_before_gf = tuple(tuple(line.generated_candidates) for line in project.prompt_lines)
    job_before_gf = runtime.generation_jobs.snapshot(lifecycle._job_id)
    events_before_gf = tuple(inbox._events.items())
    authority_before_gf = tuple(inbox._authority_events)
    ledger_operations_gf = set(capacity._ledger._operations)
    ledger_reservations_gf = set(capacity._ledger._reservations)
    writer_file_keys_gf = set(writer._files)

    result, status = runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
        outputs_ready, characterization=True, disposable_opt_in=True,
    )

    assert status == "protected_candidate_admission_evidence_observed"
    assert type(result) is GenerationWorkerProtectedCandidateAdmissionObservation
    assert result.status == status
    assert result.request_index == 0
    assert result.verified_promoted_image_count == descriptor_count
    assert result.candidate_eligibility == "evidence_observed"
    assert result.execution_available is False
    assert result.protected_storage_available is False
    assert result.promotion_available is False
    assert result.candidate_publication_allowed is False
    assert result.project_save_allowed is False
    assert result.authorship == "unverified"
    assert not ({"observation", "receipt", "remote", "images", "paths", "owner"}
                & set(result.__dataclass_fields__))

    owner = runtime._generation_protected_candidate_admission
    assert type(owner) is GenerationProtectedCandidateAdmission
    private_result = attempt.protected_candidate_admission_result
    assert type(private_result) is ProtectedCandidateAdmissionResult
    assert private_result.status == "evidence_observed"
    assert private_result.request_index == 0
    assert type(private_result.observation) is ProtectedCandidateAdmissionObservation
    assert owner._attempts[0].result is private_result
    assert attempt.protected_candidate_admission_owner is owner
    assert attempt.protected_candidate_admission_observation is result
    assert attempt.protected_candidate_admission_state == "observed"
    private_observation = private_result.observation
    assert private_observation._promotion_owner is attempt.promotion_owner
    assert private_observation._promotion_receipt is attempt.promotion_receipt
    assert private_observation._remote_receipt is attempt.remote_receipt
    assert private_observation._remote_event is integration._profile_a_remote_outputs_ready_event_attempts[0].event
    assert private_observation._outputs_ready_event is output_marker.event

    if not run_legacy_preflight_before and descriptor_count == 2:
        legacy, legacy_status = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
            publication, characterization=True, disposable_opt_in=True,
        )
        assert legacy_status == "protected_candidate_admission_preflight_non_authoritative"
        assert type(legacy) is GenerationWorkerProtectedCandidateAdmissionPreflightObservation
        assert legacy.candidate_eligibility == "not_established"
        assert attempt.protected_candidate_admission_state == "observed"
        assert attempt.protected_candidate_admission_observation is result

    duplicate, duplicate_status = runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
        outputs_ready, characterization=True, disposable_opt_in=True,
    )
    assert duplicate is None
    assert duplicate_status == "protected_candidate_admission_already_observed"
    assert len(owner._attempts) == 1
    assert owner._attempts[0].result is private_result

    assert tuple(item.progress.kind for item in inbox._authority_events) == (
        "submission_started", "submitted", "remote_outputs_ready", "outputs_ready",
    )
    assert tuple(inbox._events.items()) == events_before_gf
    assert tuple(inbox._authority_events) == authority_before_gf
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) == job_before_gf
    assert runtime.generation_jobs.snapshot(lifecycle._job_id)["requests"][0]["registered_count"] == 0
    assert set(capacity._ledger._operations) == ledger_operations_gf
    assert set(capacity._ledger._reservations) == ledger_reservations_gf
    assert set(writer._files) == writer_file_keys_gf
    assert project == project_before_gf == project_before
    assert project_path.read_bytes() == project_file_before_gf == project_file_before
    assert tuple(tuple(line.generated_candidates) for line in project.prompt_lines) == candidate_before_gf
    assert candidates_before == candidate_before_gf
    assert job_before != job_before_gf
    assert ledger_operations_before == ledger_operations_gf
    assert ledger_reservations_before == ledger_reservations_gf
    assert writer_file_keys_before == writer_file_keys_gf
    assert runtime._generation_protected_candidate_admission is owner

    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_genuine_candidate_admission_retains_host_close_race(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    roots, capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
            descriptor_count=1,
        )
    )
    integration = lifecycle._worker_storage_integration
    outputs_ready, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_outputs_ready_event_accepted_non_authoritative"

    inspect_entered, release_inspect = threading.Event(), threading.Event()
    promotion_owner = attempt.promotion_owner
    original_inspect = promotion_owner._inspect_for_candidate_admission_for_characterization

    def paused_inspection(receipt, host_freshness):
        inspect_entered.set()
        assert release_inspect.wait(10)
        return original_inspect(receipt, host_freshness)

    monkeypatch.setattr(
        promotion_owner, "_inspect_for_candidate_admission_for_characterization",
        paused_inspection,
    )
    results = []
    observer = threading.Thread(
        target=lambda: results.append(
            runtime.observe_generation_worker_protected_candidate_admission_for_characterization(
                outputs_ready, characterization=True, disposable_opt_in=True,
            )
        ),
        daemon=True,
    )
    observer.start()
    try:
        assert inspect_entered.wait(10)
        # Native Admission verification has released the runtime/Job/Inbox and
        # protected-owner locks. Host close must complete while it is paused.
        runtime.close()
        assert runtime._closed is True
        assert runtime._generation_host_state is None
    finally:
        release_inspect.set()
        observer.join(20)

    assert not observer.is_alive()
    assert len(results) == 1
    assert results[0][0] is None
    assert results[0][1] != "protected_candidate_admission_evidence_observed"
    assert attempt.protected_candidate_admission_state == "retained_uncertain"
    assert attempt.protected_candidate_admission_observation is None
    assert integration._profile_a_outputs_ready_event_attempts[0].observation is outputs_ready
    # The capacity owner is still live, so its cross-process lease stays held
    # rather than being released after the uncertain Host close race.
    assert capacity.readiness()["scope_writer_lease"] == "held"

    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_outputs_ready_known_inbox_refusal_is_not_retained_uncertain(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    from core.generation_storage_admission import _profile_a_executor_event_is_unresolved

    _roots, capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, _attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
        )
    )
    integration = lifecycle._worker_storage_integration
    inbox = runtime._generation_executor_inbox
    original = inbox.event_for_characterization

    def refuse_without_mutation(jobs, event, *, target_current):
        if event.progress.kind == "outputs_ready":
            return "acceptance_required"
        return original(jobs, event, target_current=target_current)

    monkeypatch.setattr(inbox, "event_for_characterization", refuse_without_mutation)
    result, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert result is None
    assert status == "protected_outputs_ready_event_refused"
    marker = integration._profile_a_outputs_ready_event_attempts[0]
    assert marker.state == "refused"
    assert marker.event is not None
    assert not any(event.progress.kind == "outputs_ready"
                   for event in inbox._events.values())
    assert not any(event.progress.kind == "outputs_ready"
                   for event in inbox._authority_events)
    job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    assert job["event_count"] == 3
    assert job["requests"][0]["state"] == "awaiting_download"
    assert _profile_a_executor_event_is_unresolved(integration) is False
    assert runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_outputs_ready_evidence_unavailable")

    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    assert capacity._scope_lease_retention_reason() == "settled"
    capacity.close()


def test_profile_a_outputs_ready_lost_ack_retains_unbound_event_without_replay(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    from core.generation_storage_admission import _profile_a_executor_event_is_unresolved

    _roots, capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
        )
    )
    inbox = runtime._generation_executor_inbox
    original = inbox.event_for_characterization

    def accept_then_lose_ack(jobs, event, *, target_current):
        accepted = original(jobs, event, target_current=target_current)
        if event.progress.kind == "outputs_ready" and accepted == "accepted":
            raise RuntimeError("simulated lost acknowledgment")
        return accepted

    monkeypatch.setattr(inbox, "event_for_characterization", accept_then_lose_ack)
    result, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert result is None and status == "protected_outputs_ready_event_uncertain"
    marker = lifecycle._worker_storage_integration._profile_a_outputs_ready_event_attempts[0]
    assert marker.state == "retained_uncertain"
    assert marker.event is inbox._events[4]
    assert marker.event.progress.kind == "outputs_ready"
    assert tuple(event.progress.kind for event in inbox._authority_events) == (
        "submission_started", "submitted", "remote_outputs_ready", "outputs_ready",
    )
    job = runtime.generation_jobs.snapshot(lifecycle._job_id)
    assert job["requests"][0]["state"] == "awaiting_host_registration"
    assert job["requests"][0]["registered_count"] == 0
    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        {"project": lifecycle._project_ref(),
         "current_project_path": lifecycle._project_path},
        0, characterization=True, disposable_opt_in=True,
    )
    assert audit.status == "outputs_ready_event_uncertain"
    assert audit.accepted_event_kinds[-1] == "outputs_ready"
    assert audit.profile_a_event_kinds == (
        "submission_started", "submitted", "remote_outputs_ready",
    )
    assert audit.candidate_eligibility == "not_established"
    assert _profile_a_executor_event_is_unresolved(lifecycle._worker_storage_integration)
    duplicate = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert duplicate == (None, "protected_outputs_ready_evidence_unavailable")
    assert len([event for event in inbox._authority_events
                if event.progress.kind == "outputs_ready"]) == 1
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation][
        "state"
    ] == "completed"
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    assert capacity._scope_lease_retention_reason() == "uncertain"


@pytest.mark.parametrize("drift", ["content", "acl"])
def test_profile_a_outputs_ready_native_drift_refuses_event_and_retains_promotion(
        native_profile_a_dual_custody_worker_storage, drift):
    roots, capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
        )
    )
    promoted = attempt.promotion_receipt.images[0].promoted_image
    record = writer._files[("promoted_assets", promoted.storage_identity)]
    if drift == "content":
        record[0].write_bytes(b"changed after published promotion")
    else:
        from test_generation_windows_protected_storage import mutate_disposable_acl

        mutate_disposable_acl(
            record[0], roots["promoted_assets"]._api, "writable_principal",
        )
    result, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert result is None and status == "protected_outputs_ready_event_uncertain"
    marker = lifecycle._worker_storage_integration._profile_a_outputs_ready_event_attempts[0]
    assert marker.state == "retained_uncertain"
    assert not any(event.progress.kind == "outputs_ready"
                   for event in runtime._generation_executor_inbox._authority_events)
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation][
        "state"
    ] == "completed"
    if drift == "acl":
        from test_generation_windows_protected_storage import mutate_disposable_acl

        mutate_disposable_acl(record[0], roots["promoted_assets"]._api, "original")
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    assert capacity._scope_lease_retention_reason() == "uncertain"


def test_profile_a_outputs_ready_claim_serializes_duplicate_and_host_close(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    from core.generation_storage_admission import _profile_a_executor_event_is_unresolved

    roots, capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
        )
    )
    entered, release = threading.Event(), threading.Event()
    original = writer._observe
    first = True
    results, errors = [], []

    def pause_native_observation(name, purpose, extension):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(10)
        return original(name, purpose, extension)

    monkeypatch.setattr(writer, "_observe", pause_native_observation)

    def publish():
        try:
            results.append(runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
                publication, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=publish)
    thread.start()
    try:
        assert entered.wait(10)
        marker = lifecycle._worker_storage_integration._profile_a_outputs_ready_event_attempts[0]
        assert marker.state == "claim_in_progress"
        duplicate = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
            publication, characterization=True, disposable_opt_in=True,
        )
        assert duplicate == (None, "protected_outputs_ready_evidence_unavailable")
        runtime.close()
    finally:
        release.set()
        thread.join(20)

    assert not thread.is_alive() and not errors
    assert results == [(None, "protected_outputs_ready_event_uncertain")]
    assert marker.state == "retained_uncertain"
    assert not any(event.progress.kind == "outputs_ready"
                   for event in runtime._generation_executor_inbox._authority_events)
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation][
        "state"
    ] == "completed"
    assert _profile_a_executor_event_is_unresolved(lifecycle._worker_storage_integration)
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    assert capacity._scope_lease_retention_reason() == "uncertain"


def test_profile_a_outputs_ready_audit_rejects_each_evicted_event_identity(
        native_profile_a_dual_custody_worker_storage):
    _roots, _capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker, _prepared, _attempt, writer, _accepted,
     _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_source_bound_promotion_for_outputs_ready(
            native_profile_a_dual_custody_worker_storage,
        )
    )
    try:
        result, status = runtime.publish_generation_worker_protected_outputs_ready_for_characterization(
            publication, characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_outputs_ready_event_accepted_non_authoritative"
        assert result.output_count == 1
        job_owner = runtime.generation_jobs
        inbox = runtime._generation_executor_inbox
        with job_owner._lock:
            with inbox._lock:
                job = job_owner._authorized_locked(lifecycle._job_id, lifecycle._claim_id)
                originals = {
                    event.progress.kind: event
                    for event in inbox._authority_events
                    if event.progress.kind in {
                        "submission_started", "submitted",
                        "remote_outputs_ready", "outputs_ready",
                    }
                }
                assert set(originals) == {
                    "submission_started", "submitted",
                    "remote_outputs_ready", "outputs_ready",
                }
                for kind, event in originals.items():
                    sequence = event.progress.sequence
                    inbox._events.pop(sequence)
                    audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
                        {"project": lifecycle._project_ref(),
                         "current_project_path": lifecycle._project_path},
                        0, characterization=True, disposable_opt_in=True,
                    )
                    assert audit.status == "event_chain_conflict", kind
                    inbox._events[sequence] = event
        final_audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
            {"project": lifecycle._project_ref(),
             "current_project_path": lifecycle._project_path},
            0, characterization=True, disposable_opt_in=True,
        )
        assert final_audit.status == "profile_a_outputs_ready_event_observed"
        assert final_audit.candidate_eligibility == "not_established"
    finally:
        runtime.close()
        writer.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_original_host_promotion_publication_drift_retains_completed_evidence(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_host_publication_deferred")

    receipt = attempt.promotion_receipt
    destination_reservation = attempt.promotion_capacity_reservation
    destination_path = roots["promoted_assets"]._path / "unmanaged-publication-drift.bin"
    destination_path.write_bytes(b"retained drift evidence")
    source_bytes = tuple(
        writer._bytes(writer._files[(item.image.purpose, item.image.storage_identity)])
        for item in attempt.acceptance_observations
    )
    destination_bytes = tuple(
        writer._bytes(writer._files[("promoted_assets", row.promoted_image.storage_identity)])
        for row in receipt.images
    )

    result, status = runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )
    assert result is None
    assert status == "protected_promotion_publication_uncertain"
    assert attempt.promotion_publication_state == "retained_uncertain"
    assert attempt.promotion_preflight_state == "retained_uncertain"
    record = capacity._ledger._reservations[destination_reservation]
    assert record["state"] == "uncertain"
    assert record["uncertain_completed_delta"] == record["completed_observed_delta"]
    assert capacity._ledger._operations[attempt.promotion_capacity_operation]["state"] == "uncertain"
    assert attempt.promotion_receipt is receipt
    assert attempt.promotion_owner._receipt is receipt
    assert destination_path.read_bytes() == b"retained drift evidence"
    assert tuple(
        writer._bytes(writer._files[(item.image.purpose, item.image.storage_identity)])
        for item in attempt.acceptance_observations
    ) == source_bytes
    assert tuple(
        writer._bytes(writer._files[("promoted_assets", row.promoted_image.storage_identity)])
        for row in receipt.images
    ) == destination_bytes == (data,)
    assert capacity._scope_lease._state == "held"
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    writer.close()


@pytest.mark.parametrize("descriptor_count", [1, 2, 16])
def test_profile_a_published_promotion_candidate_admission_is_read_only_and_one_shot(
        native_profile_a_dual_custody_worker_storage, descriptor_count):
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedCandidateAdmissionPreflightObservation,
    )

    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, attempt, writer,
     accepted, _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_promotion_for_candidate_preflight(
            roots, capacity, reference, project_path, descriptor_count=descriptor_count,
        )
    )
    project = lifecycle._project_ref()
    project_before = copy.deepcopy(project)
    candidate_baseline = tuple(
        tuple(line.generated_candidates) for line in project.prompt_lines
    )
    job_before = runtime.generation_jobs.snapshot(lifecycle._job_id)
    inbox_events_before = tuple(runtime._generation_executor_inbox._events.items())
    authority_events_before = tuple(runtime._generation_executor_inbox._authority_events)
    assert not any(
        event.progress.kind in {"remote_outputs_ready", "outputs_ready"}
        for event in runtime._generation_executor_inbox._events.values()
    )
    ledger_operations_before = set(capacity._ledger._operations)
    ledger_reservations_before = set(capacity._ledger._reservations)
    file_keys_before = set(writer._files)
    publication_origin_before = runtime._generation_publication_origin
    promotion_receipt = attempt.promotion_receipt
    promotion_state = attempt.promotion_preflight_state

    # Equal-looking value copies are not the exact Host-published observation;
    # rejecting one must leave the original one-shot evidence available.
    assert runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication,
    ) == (None, "execution_unavailable")
    assert runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        replace(publication), characterization=True, disposable_opt_in=True,
    ) == (None, "protected_candidate_admission_evidence_unavailable")
    result, status = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )

    assert status == "protected_candidate_admission_preflight_non_authoritative"
    assert type(result) is GenerationWorkerProtectedCandidateAdmissionPreflightObservation
    assert result.request_index == attempt.lease.request_index
    assert result.verified_promoted_image_count == descriptor_count
    assert result.candidate_eligibility == "not_established"
    assert result.execution_available is False
    assert result.protected_storage_available is False
    assert result.promotion_available is False
    assert result.candidate_publication_allowed is False
    assert result.project_save_allowed is False
    assert result.authorship == "unverified"
    assert attempt.candidate_admission_observation is result
    assert attempt.candidate_admission_state == "preflight_observed_non_authoritative"
    event_audit = runtime.inspect_profile_a_worker_executor_event_chain_for_characterization(
        {"project": project, "current_project_path": lifecycle._project_path},
        attempt.lease.request_index, characterization=True, disposable_opt_in=True,
    )
    assert event_audit.accepted_event_kinds == ()
    assert event_audit.profile_a_event_kinds == ()
    assert event_audit.next_required_event == "submission_started"
    assert event_audit.candidate_eligibility == "not_established"
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_receipt is promotion_receipt
    assert attempt.promotion_preflight_state == promotion_state == "promoted_non_authoritative"
    assert runtime._generation_publication_origin is publication_origin_before
    assert runtime._generation_protected_candidate_admission is None
    assert project == project_before
    assert tuple(tuple(line.generated_candidates) for line in project.prompt_lines) == candidate_baseline
    assert runtime.generation_jobs.snapshot(lifecycle._job_id) == job_before
    assert tuple(runtime._generation_executor_inbox._events.items()) == inbox_events_before
    assert not any(
        event.progress.kind in {"remote_outputs_ready", "outputs_ready"}
        for event in runtime._generation_executor_inbox._events.values()
    )
    assert tuple(runtime._generation_executor_inbox._authority_events) == authority_events_before
    assert set(capacity._ledger._operations) == ledger_operations_before
    assert set(capacity._ledger._reservations) == ledger_reservations_before
    assert set(writer._files) == file_keys_before
    assert runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_candidate_admission_evidence_unavailable")
    foreign_runtime, _route, _state, _lifecycle = _ready_generation_at_project_path(
        project_path,
    )
    assert foreign_runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_candidate_admission_unavailable")
    foreign_runtime.close()
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    capacity.close()
    assert capacity._scope_lease._state == "released"
    assert not capacity._scope_lease._path.exists()


@pytest.mark.parametrize("drift", ["content", "acl"])
def test_profile_a_candidate_admission_preflight_file_drift_retains_published_promotion(
        native_profile_a_dual_custody_worker_storage, drift):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, attempt, writer,
     _accepted, _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_promotion_for_candidate_preflight(
            roots, capacity, reference, project_path,
        )
    )
    receipt = attempt.promotion_receipt
    image = receipt.images[0].promoted_image
    record = writer._files[("promoted_assets", image.storage_identity)]
    if drift == "content":
        record[0].write_bytes(b"changed retained evidence")
    else:
        from test_generation_windows_protected_storage import mutate_disposable_acl

        mutate_disposable_acl(record[0], roots["promoted_assets"]._api, "writable_principal")

    result, status = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )

    assert result is None
    assert status == "protected_candidate_admission_preflight_uncertain"
    assert attempt.candidate_admission_state == "retained_uncertain"
    assert attempt.candidate_admission_observation is None
    assert attempt.cancel_requested is False
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert attempt.promotion_receipt is receipt
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation]["state"] == "completed"
    assert capacity._scope_lease._state == "held"
    if drift == "acl":
        from test_generation_windows_protected_storage import mutate_disposable_acl

        mutate_disposable_acl(record[0], roots["promoted_assets"]._api, "original")
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    writer.close()
    capacity.close()
    assert capacity._scope_lease._state == "retained_uncertain"
    assert capacity._scope_lease._path.exists()


def test_profile_a_candidate_admission_uncertainty_after_host_close_blocks_rebind(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, attempt, writer,
     _accepted, _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_promotion_for_candidate_preflight(
            roots, capacity, reference, project_path,
        )
    )
    image = attempt.promotion_receipt.images[0].promoted_image
    writer._files[("promoted_assets", image.storage_identity)][0].write_bytes(
        b"changed retained evidence",
    )
    result, status = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )
    assert result is None
    assert status == "protected_candidate_admission_preflight_uncertain"
    assert attempt.candidate_admission_state == "retained_uncertain"
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"

    original_integration = lifecycle._worker_storage_integration
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    assert lifecycle._state == "closed"
    assert original_integration._state == "closed"
    assert capacity._scope_lease._state == "held"
    assert capacity._scope_lease_retention_reason() == "uncertain"
    original_references = tuple(capacity._host_lifecycle_refs)
    assert original_references == (lifecycle,)

    second_runtime, _route, _state, second_lifecycle = _ready_generation_at_project_path(
        project_path,
    )
    try:
        assert second_lifecycle is not lifecycle
        with pytest.raises(ValueError, match="profile_a_storage_lifecycle_unsettled"):
            capacity._bind_profile_a_lifecycle_for_characterization(
                second_lifecycle, reference,
            )
        host_status = second_runtime.bind_generation_profile_a_storage_for_characterization(
            capacity, reference,
        )
        assert host_status in {
            "storage_binding_unavailable", "storage_observation_unavailable",
        }
        assert tuple(capacity._host_lifecycle_refs) == original_references
        assert lifecycle in capacity._host_lifecycle_refs
        assert second_lifecycle not in capacity._host_lifecycle_refs
        assert capacity._scope_lease._state == "held"
        assert capacity._scope_lease_retention_reason() == "uncertain"
    finally:
        second_runtime.close()

    writer.close()
    capacity.close()
    assert capacity._scope_lease._state == "retained_uncertain"
    assert capacity._scope_lease._path.exists()


def test_profile_a_candidate_admission_preflight_rejects_changed_original_project_snapshot(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, attempt, writer,
     _accepted, _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_promotion_for_candidate_preflight(
            roots, capacity, reference, project_path,
        )
    )
    origin = runtime._generation_publication_origin
    assert origin.project is lifecycle._project_ref()
    origin.project.prompt_lines[0].negative_prompt += " changed after frozen review"

    result, status = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )

    assert result is None
    assert status == "protected_candidate_admission_preflight_uncertain"
    assert attempt.candidate_admission_state == "retained_uncertain"
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation]["state"] == "completed"
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    capacity.close()
    assert capacity._scope_lease._state == "retained_uncertain"
    assert capacity._scope_lease._path.exists()


def test_profile_a_candidate_admission_preflight_rejects_changed_original_project_path(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, attempt, writer,
     _accepted, _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_promotion_for_candidate_preflight(
            roots, capacity, reference, project_path,
        )
    )
    runtime.synchronize_target(
        lifecycle._project_ref(),
        str(project_path.with_name("different-selected-project.json")),
    )

    result, status = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
        publication, characterization=True, disposable_opt_in=True,
    )

    assert result is None
    assert status == "protected_candidate_admission_unavailable"
    assert attempt.candidate_admission_state == "not_started"
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation]["state"] == "completed"
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_candidate_admission_preflight_serializes_duplicate_and_host_close(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, attempt, writer,
     _accepted, _promotion_preflight, publication, _provider, _data) = (
        _publish_profile_a_promotion_for_candidate_preflight(
            roots, capacity, reference, project_path,
        )
    )
    entered, release = threading.Event(), threading.Event()
    original = writer._observe
    first = True

    def pause_observation(name, purpose, extension):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(10)
        return original(name, purpose, extension)

    monkeypatch.setattr(writer, "_observe", pause_observation)
    results, errors = [], []

    def run_preflight():
        try:
            results.append(runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
                publication, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run_preflight)
    thread.start()
    try:
        assert entered.wait(10)
        assert attempt.candidate_admission_state == "in_progress"
        duplicate = runtime.preflight_generation_worker_protected_candidate_admission_for_characterization(
            publication, characterization=True, disposable_opt_in=True,
        )
        assert duplicate == (None, "protected_candidate_admission_evidence_unavailable")
        runtime.close()
    finally:
        release.set()
        thread.join(20)

    assert not thread.is_alive() and not errors
    assert results == [(None, "protected_candidate_admission_preflight_uncertain")]
    assert attempt.candidate_admission_state == "retained_uncertain"
    assert attempt.candidate_admission_observation is None
    assert attempt.cancel_requested is False
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_publication_observation is publication
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation]["state"] == "completed"
    assert capacity._scope_lease._state == "held"
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    capacity.close()
    assert capacity._scope_lease._state == "retained_uncertain"
    assert capacity._scope_lease._path.exists()


@pytest.mark.parametrize("close_owner", ["host", "capacity", "promotion"])
def test_profile_a_promotion_publication_close_race_compensates_without_retry(
        native_profile_a_dual_custody_worker_storage, monkeypatch, close_owner):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_host_publication_deferred")

    entered_scan = threading.Event()
    release_scan = threading.Event()
    original_scan = capacity._scan
    results = []

    def blocked_scan():
        entered_scan.set()
        if not release_scan.wait(10):
            raise RuntimeError("publication scan barrier timed out")
        return original_scan()

    monkeypatch.setattr(capacity, "_scan", blocked_scan)

    def publish():
        results.append(runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        ))

    publisher = threading.Thread(target=publish)
    publisher.start()
    promoter_closer = None
    try:
        assert entered_scan.wait(10)
        if close_owner == "host":
            runtime.close()
            assert attempt.promotion_publication_state == "retained_uncertain"
        elif close_owner == "capacity":
            capacity.close()
            # Capacity close revokes the ledger immediately; the Host attempt
            # is converted to retained uncertainty when its out-of-lock scan
            # returns and the one-shot commit revalidates the closed owner.
            assert attempt.promotion_publication_state == "in_progress"
        else:
            boundary = attempt.promotion_owner._profile_a_host_publication_boundary
            boundary_revoke = boundary.revoke
            closing_boundary = threading.Event()

            def observe_boundary_revoke():
                closing_boundary.set()
                return boundary_revoke()

            monkeypatch.setattr(boundary, "revoke", observe_boundary_revoke)
            promoter_closer = threading.Thread(target=attempt.promotion_owner.close)
            promoter_closer.start()
            assert closing_boundary.wait(10)
            assert attempt.promotion_owner._revoking is True
            assert attempt.promotion_publication_state == "in_progress"
        release_scan.set()
        publisher.join(10)
        assert not publisher.is_alive()
        if promoter_closer is not None:
            promoter_closer.join(10)
            assert not promoter_closer.is_alive()
    finally:
        release_scan.set()
        publisher.join(10)
        if promoter_closer is not None:
            promoter_closer.join(10)
    assert results == [(None, "protected_promotion_publication_uncertain")]
    assert attempt.promotion_publication_state == "retained_uncertain"
    assert attempt.promotion_preflight_state == "retained_uncertain"
    record = capacity._ledger._reservations[attempt.promotion_capacity_reservation]
    assert record["state"] == "uncertain"
    assert capacity._scope_lease._state in {"held", "retained_uncertain"}
    assert len(writer._files) == 2
    if close_owner != "host":
        runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    writer.close()


def test_profile_a_original_host_promotion_publication_competing_call_is_one_shot(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_host_publication_deferred")

    entered_scan = threading.Event()
    release_scan = threading.Event()
    original_scan = capacity._scan
    results = []

    def blocked_scan():
        entered_scan.set()
        if not release_scan.wait(10):
            raise RuntimeError("competing publication scan barrier timed out")
        return original_scan()

    monkeypatch.setattr(capacity, "_scan", blocked_scan)

    def publish():
        results.append(runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        ))

    publisher = threading.Thread(target=publish)
    publisher.start()
    try:
        assert entered_scan.wait(10)
        duplicate = runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        )
        assert duplicate == (None, "protected_promotion_publication_evidence_unavailable")
        assert attempt.promotion_publication_state == "in_progress"
        release_scan.set()
        publisher.join(10)
        assert not publisher.is_alive()
    finally:
        release_scan.set()
        publisher.join(10)
    assert len(results) == 1
    result, status = results[0]
    assert status == "protected_promotion_published_non_authoritative"
    assert result is attempt.promotion_publication_observation
    assert attempt.promotion_publication_state == "published_non_authoritative"
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    writer.close()
    assert capacity._scope_lease_retention_reason() == "settled"
    capacity.close()


def test_profile_a_original_host_promotion_publication_reentrant_close_is_fenced(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_host_publication_deferred")

    original_scan = capacity._scan
    reentrant_errors = []

    def reentrant_scan():
        try:
            attempt.promotion_owner.close()
        except ValueError as error:
            reentrant_errors.append(str(error))
        return original_scan()

    monkeypatch.setattr(capacity, "_scan", reentrant_scan)
    result, status = runtime.publish_generation_worker_accepted_output_promotion_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_published_non_authoritative"
    assert result is attempt.promotion_publication_observation
    assert reentrant_errors == ["protected_event_reentrant_revocation"]
    assert attempt.promotion_publication_state == "published_non_authoritative"
    assert attempt.promotion_preflight_state == "promoted_non_authoritative"
    assert attempt.promotion_owner._closed is False
    assert attempt.promotion_owner._revoking is False
    assert len(writer._files) == 2
    assert capacity._ledger._reservations[
        attempt.promotion_capacity_reservation
    ]["state"] == "completed"
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    writer.close()
    assert capacity._scope_lease_retention_reason() == "settled"
    capacity.close()


def test_profile_a_private_promotion_uncertainty_prevents_closed_host_rebind(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_host_publication_deferred")
    integration = lifecycle._worker_storage_integration
    assert attempt.promotion_preflight_state == "private_committed_host_publication_pending"
    assert attempt.promotion_receipt is attempt.promotion_owner._receipt

    runtime.close()
    assert attempt.promotion_preflight_state == "retained_uncertain"
    closed = runtime.finish_generation_worker_storage_close_for_characterization()
    assert closed is not None and closed.lifecycle_state == "closed"
    assert attempt.promotion_receipt is attempt.promotion_owner._receipt
    _assert_uncertain_promotion_prevents_profile_a_host_rebind(
        capacity, reference, project_path, lifecycle, integration,
    )
    writer.close()


def test_profile_a_original_host_promotion_retains_full_reservation_after_partial_create(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=2,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    operation, reservation = attempt.promotion_capacity_operation, attempt.promotion_capacity_reservation
    source_records = tuple(
        writer._files[(item.image.purpose, item.image.storage_identity)]
        for item in attempt.acceptance_observations
    )
    creates = []

    def fail_after_second_create(boundary):
        if boundary == "after_file_create":
            creates.append(boundary)
            if len(creates) == 2:
                raise RuntimeError("disposable second promotion create failure")

    writer._fault = fail_after_second_create
    public_result, status = runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )

    assert public_result is None
    assert status == "protected_promotion_uncertain"
    assert len(creates) == 2
    assert attempt.promotion_preflight_state == "retained_uncertain"
    assert attempt.promotion_receipt is None
    assert attempt.promotion_owner._receipt is None
    assert writer._stream_promotions == {}
    assert capacity._ledger._operations[operation]["state"] == "retained_uncertain"
    record = capacity._ledger._reservations[reservation]
    assert record["state"] == "retained_uncertain"
    assert record["estimates"]["promoted_assets"] == (len(data) * 2, 2)
    assert capacity._ledger._active_write is None
    assert capacity._ledger._uncertain["promoted_assets"] == [len(data) * 2, 2]
    assert len(writer._files) == 4  # two staged sources and both retained CREATE_NEW targets
    assert tuple(writer._bytes(row) for row in source_records) == (data, data)
    destinations = [row for row in writer._files.values() if row[0].parent == roots["promoted_assets"]._path]
    assert len(destinations) == 2
    assert sorted(len(row[0].read_bytes()) for row in destinations) == [0, len(data)]
    assert all(row[1] is not None and row[2] is not None and row[3] is not None
               for row in destinations)
    assert capacity._scope_lease_retention_reason() == "uncertain"

    # A failed attempt is one-shot. Retained evidence is never overwritten or retried.
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_preflight_evidence_unavailable")
    assert len(writer._files) == 4
    assert writer._stream_promotions == {}
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_original_host_promotion_compensates_completed_ledger_after_lost_ack(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=2,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    operation, reservation = attempt.promotion_capacity_operation, attempt.promotion_capacity_reservation
    complete = capacity._ledger.complete_write

    def complete_then_lose_ack(*args, **kwargs):
        complete(*args, **kwargs)
        raise RuntimeError("disposable aggregate completion acknowledgement loss")

    monkeypatch.setattr(capacity._ledger, "complete_write", complete_then_lose_ack)
    public_result, status = runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )

    assert public_result is None
    assert status == "protected_promotion_uncertain"
    assert attempt.promotion_preflight_state == "retained_uncertain"
    assert attempt.promotion_receipt is None
    assert attempt.promotion_owner._receipt is None
    assert writer._stream_promotions == {}
    record = capacity._ledger._reservations[reservation]
    assert record["state"] == "uncertain"
    assert capacity._ledger._operations[operation]["state"] == "uncertain"
    assert record["completed_observed_delta"]["promoted_assets"] == (len(data) * 2, 2)
    assert record["uncertain_completed_delta"] == record["completed_observed_delta"]
    assert capacity._ledger._uncertain["promoted_assets"] == [len(data) * 2, 2]
    assert capacity._ledger._observed["promoted_assets"] == [0, 0]
    assert capacity._ledger._active_write is None
    assert len(writer._files) == 4
    assert all(row[0].exists() for row in writer._files.values())
    assert sorted(len(row[0].read_bytes()) for row in writer._files.values()
                  if row[0].parent == roots["promoted_assets"]._path) == [len(data), len(data)]
    assert capacity._scope_lease_retention_reason() == "uncertain"

    # The exact completed-delta compensation is idempotent for this reservation.
    capacity._ledger.retain_completed_write_as_uncertain(
        operation, attempt.promotion_write_admission, record["completed_observed_delta"],
    )
    assert capacity._ledger._uncertain["promoted_assets"] == [len(data) * 2, 2]
    assert capacity._ledger._observed["promoted_assets"] == [0, 0]
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_original_host_promotion_host_close_at_create_retains_uncertain_batch(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=2,
    )
    integration = lifecycle._worker_storage_integration
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    operation, reservation = attempt.promotion_capacity_operation, attempt.promotion_capacity_reservation
    entered, release = threading.Event(), threading.Event()
    close_finished = threading.Event()
    close_errors, results, errors = [], [], []

    def pause_after_first_create(boundary):
        if boundary == "after_file_create":
            entered.set()
            assert release.wait(10)

    writer._fault = pause_after_first_create

    def promote():
        try:
            results.append(runtime.promote_generation_worker_accepted_output_for_characterization(
                preflight, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as error:
            errors.append(error)

    def close_host():
        try:
            runtime.close()
        except BaseException as error:
            close_errors.append(error)
        finally:
            close_finished.set()

    promote_thread = threading.Thread(target=promote)
    close_thread = None
    try:
        promote_thread.start()
        assert entered.wait(10)
        close_thread = threading.Thread(target=close_host)
        close_thread.start()
        assert close_finished.wait(10), "Host close must not wait on native CREATE_NEW callback"
    finally:
        release.set()
        promote_thread.join(20)
        if close_thread is not None:
            close_thread.join(10)

    assert not promote_thread.is_alive()
    assert close_thread is None or not close_thread.is_alive()
    assert not errors and not close_errors
    assert results == [(None, "protected_promotion_uncertain")]
    assert attempt.promotion_preflight_state == "retained_uncertain"
    assert attempt.promotion_receipt is None
    assert attempt.promotion_owner._receipt is None
    assert writer._stream_promotions == {}
    assert capacity._ledger._operations[operation]["state"] == "retained_uncertain"
    record = capacity._ledger._reservations[reservation]
    assert record["state"] == "retained_uncertain"
    assert capacity._ledger._uncertain["promoted_assets"] == [len(data) * 2, 2]
    assert capacity._ledger._active_write is None
    assert capacity._scope_lease_retention_reason() == "uncertain"
    assert len([row for row in writer._files.values()
                if row[0].parent == roots["promoted_assets"]._path]) == 1
    assert all(path.exists() for purpose, _root, path in writer._inventory()
               if purpose in {"temporary_containment", "promoted_assets"})
    assert not writer._stream_promotions
    closed = runtime.finish_generation_worker_storage_close_for_characterization()
    assert closed is not None and closed.lifecycle_state == "closed"
    _assert_uncertain_promotion_prevents_profile_a_host_rebind(
        capacity, reference, project_path, lifecycle, integration,
    )
    writer.close()


def test_profile_a_original_host_promotion_rejects_copied_preflight_observation(
        native_profile_a_dual_custody_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    copied = replace(preflight)
    assert copied == preflight and copied is not preflight
    before_files = dict(writer._files)
    before_promotions = dict(writer._stream_promotions)
    record = capacity._ledger._reservations[attempt.promotion_capacity_reservation]

    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        copied, characterization=True, disposable_opt_in=True,
    ) == (None, "protected_promotion_preflight_evidence_unavailable")
    assert record["state"] == "reserved"
    assert writer._files == before_files
    assert writer._stream_promotions == before_promotions
    assert attempt.promotion_receipt is None
    assert runtime.promote_generation_worker_accepted_output_for_characterization(
        preflight, characterization=True, disposable_opt_in=True,
    )[1] == "protected_promotion_host_publication_deferred"
    runtime.close()
    assert record["state"] == "uncertain"
    assert attempt.promotion_preflight_state == "retained_uncertain"
    assert record["uncertain_completed_delta"] == record["completed_observed_delta"]
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_original_host_promotion_competing_call_cannot_create_twice(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=2,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    entered, release = threading.Event(), threading.Event()
    original = attempt.acceptance_owner._inspect_for_promotion_preflight_for_characterization
    first = True

    def pause_first_writer_inspection(batch, freshness):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(10)
        return original(batch, freshness)

    monkeypatch.setattr(attempt.acceptance_owner,
                        "_inspect_for_promotion_preflight_for_characterization",
                        pause_first_writer_inspection)
    results, errors = [], []

    def run_first():
        try:
            results.append(runtime.promote_generation_worker_accepted_output_for_characterization(
                preflight, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run_first)
    thread.start()
    try:
        assert entered.wait(10)
        # The Writer has claimed this one-shot attempt, but the first native
        # source revalidation precedes destination write admission.
        assert attempt.promotion_preflight_state == "promotion_claiming"
        record = capacity._ledger._reservations[attempt.promotion_capacity_reservation]
        assert record["state"] == "reserved"
        duplicate = runtime.promote_generation_worker_accepted_output_for_characterization(
            preflight, characterization=True, disposable_opt_in=True,
        )
        assert duplicate == (None, "protected_promotion_preflight_evidence_unavailable")
        assert record["state"] == "reserved"
        assert not any(row[0].parent == roots["promoted_assets"]._path
                       for row in writer._files.values())
    finally:
        release.set()
        thread.join(20)

    assert not thread.is_alive() and not errors
    assert results == [(None, "protected_promotion_host_publication_deferred")]
    assert attempt.promotion_preflight_state == "private_committed_host_publication_pending"
    assert attempt.promotion_create_attempt_count == 2
    assert len(attempt.promotion_create_descriptor_identities) == 2
    assert attempt.promotion_owner._receipt is attempt.promotion_receipt
    assert len(attempt.promotion_receipt.images) == 2
    assert len([row for row in writer._files.values()
                if row[0].parent == roots["promoted_assets"]._path]) == 2
    assert record["state"] == "completed"
    assert len(writer._stream_promotions) == 1
    runtime.close()
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_original_host_promotion_cancels_exact_write_before_first_create_on_host_loss(
        native_profile_a_dual_custody_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_dual_custody_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    preflight, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    entered, release = threading.Event(), threading.Event()
    original = attempt.acceptance_owner._inspect_for_promotion_preflight_for_characterization
    inspections = 0

    def pause_second_writer_inspection(batch, freshness):
        nonlocal inspections
        inspections += 1
        if inspections == 2:
            entered.set()
            assert release.wait(10)
        return original(batch, freshness)

    monkeypatch.setattr(attempt.acceptance_owner,
                        "_inspect_for_promotion_preflight_for_characterization",
                        pause_second_writer_inspection)
    results, errors = [], []

    def run_promotion():
        try:
            results.append(runtime.promote_generation_worker_accepted_output_for_characterization(
                preflight, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run_promotion)
    thread.start()
    try:
        assert entered.wait(10)
        record = capacity._ledger._reservations[attempt.promotion_capacity_reservation]
        assert record["state"] == "writing"
        runtime.synchronize_target(
            lifecycle._project_ref(),
            str(project_path.with_name("profile-a-promotion-host-changed.json")),
        )
    finally:
        release.set()
        thread.join(20)

    assert not thread.is_alive() and not errors
    # The acceptance owner marks a failed post-claim freshness observation
    # uncertain, even though the exact destination reservation is safely
    # cancelled before any CREATE_NEW attempt.
    assert results == [(None, "protected_promotion_uncertain")]
    assert attempt.promotion_preflight_state == "cancelled"
    assert attempt.promotion_create_attempt_count == 0
    assert record["state"] == "cancelled"
    assert capacity._ledger._operations[attempt.promotion_capacity_operation]["state"] == "cancelled"
    assert capacity._ledger._active_write is None
    assert writer._stream_promotions == {}
    assert attempt.promotion_receipt is None
    assert not any(row[0].parent == roots["promoted_assets"]._path
                   for row in writer._files.values())
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_dual_custody_writer_rejects_ad_hoc_containment_limits_before_borrow(
        native_profile_a_dual_custody_worker_storage):
    from core.comfy_output_containment import ContainmentLimits
    from core.generation_windows_protected_assets import WindowsProtectedAssetsCharacterization

    roots, capacity, _reference, _project_path = native_profile_a_dual_custody_worker_storage
    with pytest.raises(ValueError, match="profile_a_capacity_policy_mismatch"):
        WindowsProtectedAssetsCharacterization.borrow_profile_a_writer_for_characterization(
            capacity,
            limits=replace(ContainmentLimits(), images=15),
            characterization=True, disposable_opt_in=True,
        )


def test_profile_a_promotion_preflight_close_cancels_only_destination_reservation(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    before_files = dict(writer._files)
    result, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_promotion_preflight_non_authoritative"
    destination_record = capacity._ledger._reservations[attempt.promotion_capacity_reservation]
    assert destination_record["estimates"]["promoted_assets"] == (len(data), 1)

    runtime.close()
    assert attempt.promotion_preflight_state == "cancelled"
    assert destination_record["state"] == "cancelled"
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    assert writer._files == before_files
    assert not writer._stream_promotions
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_promotion_preflight_host_drift_after_reservation_cancels_before_write(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    before_files = dict(writer._files)
    original_reserve = capacity.reserve_for_characterization

    def reserve_then_change_target(operation, estimates):
        reservation = original_reserve(operation, estimates)
        runtime.synchronize_target(
            lifecycle._project_ref(), str(project_path.with_name("changed-selected-project.json")),
        )
        return reservation

    monkeypatch.setattr(capacity, "reserve_for_characterization", reserve_then_change_target)
    result, status = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )
    assert result is None
    assert status == "protected_promotion_preflight_refused"
    assert attempt.promotion_preflight_state == "cancelled"
    promotion_reservation = next(
        record for token, record in capacity._ledger._reservations.items()
        if record["estimates"].get("promoted_assets") is not None
    )
    assert promotion_reservation["state"] == "cancelled"
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    assert writer._files == before_files
    assert not writer._stream_promotions
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_promotion_preflight_capacity_close_during_revalidation_retains_reservation(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    entered, release = threading.Event(), threading.Event()
    original = attempt.acceptance_owner._inspect_for_promotion_preflight_for_characterization
    inspections = 0

    def block_second_inspection(accepted, freshness):
        nonlocal inspections
        inspections += 1
        if inspections == 2:
            entered.set()
            assert release.wait(10)
        return original(accepted, freshness)

    monkeypatch.setattr(
        attempt.acceptance_owner,
        "_inspect_for_promotion_preflight_for_characterization",
        block_second_inspection,
    )
    results, errors = [], []

    def run_preflight():
        try:
            results.append(runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
                accepted_observation, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run_preflight)
    thread.start()
    try:
        assert entered.wait(10)
        destination_record = next(
            record for record in capacity._ledger._reservations.values()
            if record["estimates"].get("promoted_assets") is not None
        )
        assert destination_record["state"] == "reserved"
        capacity.close()
    finally:
        release.set()
        thread.join(10)

    assert not thread.is_alive()
    assert not errors
    assert results and results[0][0] is None
    assert results[0][1] == "protected_promotion_preflight_refused"
    assert attempt.promotion_preflight_observation is None
    assert attempt.promotion_preflight_state == "retained_uncertain"
    assert destination_record["state"] == "retained_uncertain"
    assert capacity._ledger._uncertain["promoted_assets"][1] == 1
    assert not writer._stream_promotions
    writer.close()
    runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_promotion_preflight_competing_call_is_one_shot_and_cannot_publish_twice(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    accepted_observation, status = runtime.accept_generation_worker_staged_output_for_characterization(
        staged, characterization=True, disposable_opt_in=True,
    )
    assert status == "protected_image_batch_accepted_non_authoritative"
    entered, release = threading.Event(), threading.Event()
    original = attempt.acceptance_owner._inspect_for_promotion_preflight_for_characterization

    def blocked_inspection(accepted, freshness):
        entered.set()
        assert release.wait(3)
        return original(accepted, freshness)

    monkeypatch.setattr(attempt.acceptance_owner,
                        "_inspect_for_promotion_preflight_for_characterization",
                        blocked_inspection)
    results = []
    errors = []

    def run_preflight():
        try:
            results.append(runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
                accepted_observation, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=run_preflight)
    thread.start()
    assert entered.wait(3)
    second = runtime.preflight_generation_worker_accepted_output_promotion_for_characterization(
        accepted_observation, characterization=True, disposable_opt_in=True,
    )
    assert second == (None, "protected_promotion_preflight_evidence_unavailable")
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert not errors
    assert len(results) == 1
    result, status = results[0]
    assert status == "protected_promotion_preflight_non_authoritative"
    assert attempt.promotion_preflight_observation is result
    assert len(capacity._ledger._reservations) == 2
    assert writer._stream_promotions == {}
    runtime.close()
    assert capacity._ledger._reservations[attempt.promotion_capacity_reservation]["state"] == "cancelled"
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    writer.close()
    runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_staged_acceptance_rejects_copied_observation_and_native_drift(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    try:
        copied = replace(staged)
        assert copied == staged and copied is not staged
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            copied, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_evidence_unavailable")
        image = attempt.writer_image_observation.image
        path = writer._files[(image.purpose, image.storage_identity)][0]
        with path.open("ab") as output:
            output.write(b"tamper")
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_failed")
        assert attempt.acceptance_state == "retained_uncertain"
        assert attempt.writer_handoff_state == "retained_uncertain"
        assert writer._stream_batches == {}
        assert writer._stream_batch_acceptances == {}
        assert capacity._ledger._reservations[attempt.reservation]["state"] in {
            "uncertain", "retained_uncertain",
        }
        assert path.exists()
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


@pytest.mark.parametrize("mutation", ["completed_delta", "stream_attempt_identity"])
def test_profile_a_single_image_acceptance_requires_exact_completed_write_binding(
        native_profile_a_worker_storage, mutation):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    record = capacity._ledger._reservations[attempt.reservation]
    if mutation == "completed_delta":
        delta = record["completed_observed_delta"]
        delta["temporary_containment"] = (
            delta["temporary_containment"][0] + 1,
            delta["temporary_containment"][1],
        )
    else:
        binding = record["asset_stream_completion"]
        copied_attempt = tuple(list(binding[2]))
        assert copied_attempt == binding[2] and copied_attempt is not binding[2]
        record["asset_stream_completion"] = (
            binding[0], binding[1], copied_attempt, binding[3],
        )

    # The aggregate inventory remains sufficient in both cases; acceptance
    # must rely on this reservation's exact completion evidence instead.
    observed_staging = capacity._ledger._observed["temporary_containment"]
    assert observed_staging[0] >= len(data) and observed_staging[1] >= 1
    try:
        result, status = runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        )
        assert result is None
        assert status == "protected_acceptance_failed"
        assert attempt.acceptance_state == "retained_uncertain"
        assert attempt.acceptance_owner is None
        assert attempt.accepted_batch is None
        assert writer._stream_batches == {}
        assert writer._stream_batch_acceptances == {}
        assert record["state"] in {"completed", "uncertain", "retained_uncertain"}
        assert capacity._invalid is True
        capacity.close()
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()


@pytest.mark.parametrize("mutation", ["missing", "reordered", "duplicate", "substituted"])
def test_profile_a_acceptance_requires_complete_ordered_exact_descriptor_observations(
        native_profile_a_worker_storage, mutation):
    from dataclasses import replace as copy_dataclass

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=2,
    )
    original = attempt.acceptance_observations
    if mutation == "missing":
        changed = original[:-1]
    elif mutation == "reordered":
        changed = tuple(reversed(original))
    elif mutation == "duplicate":
        changed = (original[0], original[0])
    else:
        changed = (copy_dataclass(original[0]), original[1])
    attempt.writer_image_observations = changed
    attempt.acceptance_observations = changed
    try:
        result, status = runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        )
        assert result is None
        if mutation == "missing":
            assert status == "protected_acceptance_batch_incomplete"
            assert attempt.acceptance_state == "not_started"
        else:
            assert status == "protected_acceptance_failed"
            assert attempt.acceptance_state == "retained_uncertain"
        assert not writer._stream_batches
        assert not writer._stream_batch_acceptances
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()


def test_profile_a_staged_acceptance_rechecks_real_native_acl_and_retains_evidence(
        native_profile_a_worker_storage):
    from test_generation_windows_protected_storage import mutate_disposable_acl

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    image = attempt.writer_image_observation.image
    path = writer._files[(image.purpose, image.storage_identity)][0]
    try:
        mutate_disposable_acl(path, roots["temporary_containment"]._api, "writable_principal")
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_failed")
        assert attempt.acceptance_state == "retained_uncertain"
        assert writer._stream_batches == {}
        assert writer._stream_batch_acceptances == {}
        assert path.exists()
        assert capacity._ledger._reservations[attempt.reservation]["state"] in {
            "uncertain", "retained_uncertain",
        }
        capacity.close()
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_staged_acceptance_rejects_changed_completed_ledger_delta(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path, descriptor_count=2,
    )
    delta = capacity._ledger._reservations[attempt.reservation]["completed_observed_delta"]
    delta["temporary_containment"] = (
        delta["temporary_containment"][0] + 1,
        delta["temporary_containment"][1],
    )
    try:
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_failed")
        assert attempt.acceptance_state == "retained_uncertain"
        assert writer._stream_batches == {}
        assert writer._stream_batch_acceptances == {}
        assert capacity._invalid is True
        capacity.close()
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_staged_acceptance_is_one_shot_under_concurrent_calls(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    original_inspect = writer.inspect_verified_remote_image_for_characterization
    inspect_entered, allow_inspect = threading.Event(), threading.Event()
    first_result, first_errors = [], []

    def blocked_inspect(observation):
        for lock in (runtime._publication_gate, lifecycle._lock,
                     runtime.generation_jobs._lock,
                     runtime._generation_executor_inbox._lock,
                     capacity._lock, capacity._ledger._lock):
            acquired = lock.acquire(blocking=False)
            assert acquired
            if acquired:
                lock.release()
        inspect_entered.set()
        assert allow_inspect.wait(5)
        return original_inspect(observation)

    monkeypatch.setattr(writer, "inspect_verified_remote_image_for_characterization",
                        blocked_inspect)

    def accept_first():
        try:
            first_result.append(runtime.accept_generation_worker_staged_output_for_characterization(
                staged, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as exc:
            first_errors.append(exc)

    thread = threading.Thread(target=accept_first)
    try:
        thread.start()
        assert inspect_entered.wait(5), (first_result, first_errors)
        second = runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        )
        assert second == (None, "protected_acceptance_evidence_unavailable")
        allow_inspect.set()
        thread.join(10)
        assert not thread.is_alive() and not first_errors
        assert len(first_result) == 1
        assert first_result[0][1] == "protected_image_batch_accepted_non_authoritative"
        assert len(writer._stream_batch_acceptances) == 1
        assert attempt.acceptance_state == "accepted_non_authoritative"
    finally:
        allow_inspect.set()
        thread.join(5)
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


@pytest.mark.parametrize("close_owner", ["writer", "capacity"])
def test_profile_a_acceptance_close_race_with_native_revalidation_retains_scope_evidence(
        native_profile_a_worker_storage, monkeypatch, close_owner):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    original_inspect = writer.inspect_verified_remote_image_for_characterization
    inspect_entered, allow_inspect = threading.Event(), threading.Event()
    result, errors = [], []

    def blocked_inspect(observation):
        for lock in (runtime._publication_gate, lifecycle._lock,
                     runtime.generation_jobs._lock,
                     runtime._generation_executor_inbox._lock,
                     capacity._lock, capacity._ledger._lock):
            acquired = lock.acquire(blocking=False)
            assert acquired
            if acquired:
                lock.release()
        inspect_entered.set()
        assert allow_inspect.wait(5)
        return original_inspect(observation)

    monkeypatch.setattr(writer, "inspect_verified_remote_image_for_characterization",
                        blocked_inspect)

    def accept():
        try:
            result.append(runtime.accept_generation_worker_staged_output_for_characterization(
                staged, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=accept)
    try:
        thread.start()
        assert inspect_entered.wait(5)
        if close_owner == "writer":
            writer.close()
        else:
            capacity.close()
        assert capacity._scope_lease._path.exists()
        allow_inspect.set()
        thread.join(10)
        assert not thread.is_alive() and not errors
        assert result == [(None, "protected_acceptance_failed")]
        assert attempt.acceptance_state == "retained_uncertain"
        assert writer._stream_batch_acceptances == {}
        assert capacity._ledger._reservations[attempt.reservation]["state"] in {
            "uncertain", "retained_uncertain",
        }
        if close_owner == "writer":
            capacity.close()
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        allow_inspect.set()
        thread.join(5)
        if not writer._closed:
            writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()


def test_profile_a_acceptance_double_call_and_post_commit_host_loss_are_fenced(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    integration = lifecycle._worker_storage_integration
    original_publish = integration._publish_profile_a_acceptance_locked

    def lose_host_before_publication(*args, **kwargs):
        integration._state = "uncertain"
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(integration, "_publish_profile_a_acceptance_locked",
                        lose_host_before_publication)
    try:
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_host_changed")
        assert attempt.accepted_batch is not None
        assert writer._stream_batch_acceptances[
            (attempt.prepared.request_id, attempt.remote_receipt.identity)
        ] is attempt.accepted_batch
        assert attempt.acceptance_owner._invalid is True
        assert attempt.acceptance_state == "retained_uncertain"
        assert capacity._ledger._reservations[attempt.reservation]["state"] in {
            "uncertain", "retained_uncertain",
        }
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_evidence_unavailable")
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()


def test_profile_a_acceptance_capacity_close_after_last_readiness_fails_commit(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    original_readiness = capacity.readiness
    integration = lifecycle._worker_storage_integration
    original_matches = integration._profile_a_acceptance_matches_locked
    readiness_calls = []
    close_at_final_match = [False]

    def close_after_second_readiness():
        result = original_readiness()
        readiness_calls.append(result)
        if len(readiness_calls) == 2:
            close_at_final_match[0] = True
        return result

    def close_after_final_match(*args, **kwargs):
        result = original_matches(*args, **kwargs)
        if close_at_final_match[0] and result:
            close_at_final_match[0] = False
            capacity.close()
        return result

    monkeypatch.setattr(capacity, "readiness", close_after_second_readiness)
    monkeypatch.setattr(integration, "_profile_a_acceptance_matches_locked",
                        close_after_final_match)
    try:
        result = runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        )
        assert result == (None, "protected_acceptance_capacity_changed")
        assert attempt.acceptance_state == "retained_uncertain"
        assert writer._stream_batch_acceptances
        assert attempt.acceptance_owner._invalid is True
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()


def test_profile_a_acceptance_close_after_private_acceptance_fails_host_publication(
        native_profile_a_worker_storage, monkeypatch):
    from core.comfy_output_containment import ProtectedOutputAcceptanceCharacterization

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    original_inspect = ProtectedOutputAcceptanceCharacterization.inspect_for_characterization
    inspect_entered, allow_publish = threading.Event(), threading.Event()
    owners, result, errors = [], [], []

    def inspect_then_pause(owner, accepted=None):
        receipt = original_inspect(owner, accepted)
        if owner._protected_owner is writer:
            owners.append(owner)
            inspect_entered.set()
            assert allow_publish.wait(5)
        return receipt

    monkeypatch.setattr(ProtectedOutputAcceptanceCharacterization,
                        "inspect_for_characterization", inspect_then_pause)

    def accept():
        try:
            result.append(runtime.accept_generation_worker_staged_output_for_characterization(
                staged, characterization=True, disposable_opt_in=True,
            ))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=accept)
    try:
        thread.start()
        assert inspect_entered.wait(5), (result, errors)
        assert len(owners) == 1
        owners[0].close()
        allow_publish.set()
        thread.join(10)
        assert not thread.is_alive() and not errors
        assert result == [(None, "protected_acceptance_owner_changed")]
        assert owners[0]._closed is True
        assert attempt.acceptance_state == "retained_uncertain"
        assert writer._stream_batch_acceptances
        assert capacity._ledger._reservations[attempt.reservation]["state"] in {
            "uncertain", "retained_uncertain",
        }
    finally:
        allow_publish.set()
        thread.join(5)
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()


@pytest.mark.parametrize("drift", ["claim", "project_path"])
def test_profile_a_acceptance_host_claim_or_project_drift_during_native_read_retains(
        native_profile_a_worker_storage, monkeypatch, drift):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    (runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, _evidence,
     attempt, writer, staged, _provider, _data) = _stage_profile_a_for_acceptance(
        roots, capacity, reference, project_path,
    )
    original_inspect = writer.inspect_verified_remote_image_for_characterization
    original_claim = lifecycle._claim_id
    original_path = runtime.target_tracker._project_path

    def drift_then_inspect(observation):
        if drift == "claim":
            lifecycle._claim_id = "changed-claim"
        else:
            runtime.target_tracker._project_path = "changed-project.json"
        return original_inspect(observation)

    monkeypatch.setattr(writer, "inspect_verified_remote_image_for_characterization",
                        drift_then_inspect)
    try:
        assert runtime.accept_generation_worker_staged_output_for_characterization(
            staged, characterization=True, disposable_opt_in=True,
        ) == (None, "protected_acceptance_failed")
        assert attempt.acceptance_state == "retained_uncertain"
        assert not writer._stream_batches
        assert not writer._stream_batch_acceptances
        assert capacity._ledger._reservations[attempt.reservation]["state"] in {
            "uncertain", "retained_uncertain",
        }
    finally:
        lifecycle._claim_id = original_claim
        runtime.target_tracker._project_path = original_path
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()


def test_profile_a_single_image_writer_handoff_reuses_exact_reservation_and_is_non_authoritative(
        native_profile_a_worker_storage, monkeypatch):
    import hashlib

    from core import generation_windows_protected_storage as windows
    from test_comfy_output_containment import image_bytes
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedWriterObservation,
    )

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker_instance, prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    integration = lifecycle._worker_storage_integration
    operation, reservation = attempt.capacity_operation, attempt.reservation
    data = image_bytes()
    provider = _WriterDownloadStream(data)
    operation_keys = set(capacity._ledger._operations)
    reservation_keys = set(capacity._ledger._reservations)
    original_capacity_readiness = capacity.readiness
    original_project_readiness = reference.readiness
    original_writer_readiness = writer.readiness
    readiness_calls = []

    def assert_host_locks_released():
        assert not runtime._publication_gate.locked()
        acquired = lifecycle._lock.acquire(blocking=False)
        assert acquired
        if acquired:
            lifecycle._lock.release()
        assert not runtime.generation_jobs._lock._is_owned()
        assert not runtime._generation_executor_inbox._lock._is_owned()

    def capacity_readiness():
        assert_host_locks_released()
        readiness_calls.append("capacity")
        return original_capacity_readiness()

    def project_readiness():
        assert_host_locks_released()
        readiness_calls.append("project")
        return original_project_readiness()

    def writer_readiness():
        assert_host_locks_released()
        readiness_calls.append("writer")
        return original_writer_readiness()

    monkeypatch.setattr(capacity, "readiness", capacity_readiness)
    monkeypatch.setattr(reference, "readiness", project_readiness)
    monkeypatch.setattr(writer, "readiness", writer_readiness)
    provider._on_call = provider._on_read = provider._on_close = assert_host_locks_released
    try:
        assert writer._roots["temporary_containment"] is roots["temporary_containment"]
        assert writer._roots["promoted_assets"] is roots["promoted_assets"]
        assert writer._owns_roots is False
        assert writer._profile_a_capacity_owner is capacity
        with pytest.raises(ValueError, match="profile_a_writer_handoff_required"):
            writer.create_image_for_characterization(
                "temporary_containment", data, extension="png",
            )
        assert not list(roots["temporary_containment"]._path.iterdir())

        observation, status = runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert type(observation) is GenerationWorkerProtectedWriterObservation, status
        assert status == "protected_image_staged_non_authoritative"
        assert (observation.request_index, observation.verified_image_count,
                observation.capacity_accounted) == (0, 1, True)
        assert observation.write_authorized is False
        assert observation.execution_available is False
        assert observation.protected_storage_available is False
        assert observation.promotion_available is False
        assert observation.candidate_publication_allowed is False
        assert observation.project_save_allowed is False
        assert observation.authorship == "unverified"
        assert not ({"image", "path", "descriptor", "receipt", "write_admission"}
                    & set(observation.__dataclass_fields__))

        remote = attempt.remote_receipt
        assert provider.lookups[0].descriptor_identity == remote.images[0].identity
        assert provider.closed == 1
        assert set(capacity._ledger._operations) == operation_keys
        assert set(capacity._ledger._reservations) == reservation_keys
        assert len(operation_keys) == len(reservation_keys) == 1
        assert capacity._ledger._operations[operation]["state"] == "completed"
        assert capacity._ledger._reservations[reservation]["state"] == "completed"
        assert capacity._ledger._reservations[reservation]["write"] is attempt.writer_admission
        assert capacity._ledger._active_write is None
        assert attempt.writer_handoff_state == "staged_non_authoritative"
        assert attempt.writer_image_observation is writer._stream_images[
            (prepared.request_id, remote.images[0].identity)
        ]

        image = attempt.writer_image_observation.image
        path, handle, identity, acl = writer._files[(image.purpose, image.storage_identity)]
        assert path.parent == roots["temporary_containment"]._path
        assert path.read_bytes() == data
        assert image.content_sha256 == hashlib.sha256(data).hexdigest()
        assert image.byte_count == len(data)
        assert windows._identity(handle) == identity == windows._ordinary(path, directory=False)
        assert windows._acl(handle, roots["temporary_containment"]._api,
                            roots["temporary_containment"]._user) == acl[0]
        assert image.image_format == "PNG"
        assert not list(roots["promoted_assets"]._path.iterdir())
        row = next(item for item in capacity.readiness()["roots"]
                   if item["purpose"] == "temporary_containment")
        assert (row["reserved_bytes"], row["reserved_entries"],
                row["observed_used_bytes"], row["observed_used_entries"],
                row["retained_uncertain_bytes"], row["retained_uncertain_entries"]) == (
                    0, 0, len(data), 1, 0, 0,
                )
        assert readiness_calls.count("capacity") >= 2
        assert readiness_calls.count("project") >= 2
        assert readiness_calls.count("writer") >= 2
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "writer_handoff_evidence_unavailable")
        assert len(provider.lookups) == 1
    finally:
        writer.close()
        assert all(root._closed is False for root in roots.values())
        assert capacity.readiness()["status"] == "characterization_only"
        runtime.close()


def test_profile_a_post_write_claim_invalidation_compensates_completed_capacity_and_retains_scope_lease(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    provider = _WriterDownloadStream(image_bytes())
    original_readiness = writer.readiness
    readiness_calls = 0
    compensation_entered = threading.Event()
    continue_compensation = threading.Event()
    stage_thread = None
    stage_result = []
    original_compensation = capacity.retain_completed_asset_stream_write_uncertain_for_characterization

    def revoke_after_completed_native_write():
        nonlocal readiness_calls
        readiness_calls += 1
        # The first readiness is preflight; the second is post-write, after
        # complete_asset_write_for_characterization committed the ledger.
        if readiness_calls == 2:
            lifecycle.close()
        return original_readiness()

    def pause_compensation(*args):
        compensation_entered.set()
        assert continue_compensation.wait(5)
        return original_compensation(*args)

    monkeypatch.setattr(writer, "readiness", revoke_after_completed_native_write)
    monkeypatch.setattr(
        capacity, "retain_completed_asset_stream_write_uncertain_for_characterization",
        pause_compensation,
    )

    def stage():
        stage_result.append(
            runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
                evidence, writer, stream_provider=provider,
                characterization=True, disposable_opt_in=True,
            )
        )

    try:
        stage_thread = threading.Thread(target=stage)
        stage_thread.start()
        assert compensation_entered.wait(5)
        assert readiness_calls == 2
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
        assert attempt.writer_handoff_state == "create_boundary_crossed"

        # Close races the host's final publication and the exact ledger
        # compensation. The unresolved handoff itself must retain the marker.
        capacity.close()
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        continue_compensation.set()
        if stage_thread is not None:
            stage_thread.join(5)
            assert not stage_thread.is_alive()
        writer.close()
        runtime.close()

    assert stage_result == [(None, "host_or_writer_changed")]
    assert provider.closed == 1 and len(provider.lookups) == 1
    assert attempt.writer_image_observation is None
    assert attempt.writer_handoff_state == "retained_uncertain"
    assert attempt.evidence_state == "uncertain"
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "uncertain"
    assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "uncertain"
    assert capacity._ledger._observed["temporary_containment"] == [0, 0]
    assert capacity._ledger._uncertain["temporary_containment"] == [32 * 1024 * 1024, 1]
    files = list(roots["temporary_containment"]._path.iterdir())
    assert len(files) == 1 and files[0].read_bytes() == image_bytes()
    assert capacity._scope_lease._state == "retained_uncertain"
    assert capacity._scope_lease._path.exists()


def test_profile_a_post_batch_commit_claim_invalidation_compensates_exact_aggregate_and_retains_scope_lease(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )
    provider = _WriterDownloadBatchProvider(image_bytes())
    original_readiness = writer.readiness
    readiness_calls = 0
    compensation_entered = threading.Event()
    continue_compensation = threading.Event()
    stage_thread = None
    stage_result = []
    original_compensation = capacity.retain_completed_asset_stream_batch_uncertain_for_characterization

    def revoke_after_completed_native_batch():
        nonlocal readiness_calls
        readiness_calls += 1
        if readiness_calls == 2:
            lifecycle.close()
        return original_readiness()

    def pause_compensation(*args):
        compensation_entered.set()
        assert continue_compensation.wait(5)
        return original_compensation(*args)

    monkeypatch.setattr(writer, "readiness", revoke_after_completed_native_batch)
    monkeypatch.setattr(
        capacity, "retain_completed_asset_stream_batch_uncertain_for_characterization",
        pause_compensation,
    )

    def stage():
        stage_result.append(
            runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
                evidence, writer, stream_provider=provider,
                characterization=True, disposable_opt_in=True,
            )
        )

    try:
        stage_thread = threading.Thread(target=stage)
        stage_thread.start()
        assert compensation_entered.wait(5)
        assert readiness_calls == 2
        record = capacity._ledger._reservations[attempt.reservation]
        assert record["state"] == "completed"
        assert record["completed_observed_delta"]["temporary_containment"] == (
            2 * len(image_bytes()), 2,
        )
        assert attempt.writer_handoff_state == "create_boundary_crossed"
        capacity.close()
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        continue_compensation.set()
        if stage_thread is not None:
            stage_thread.join(5)
            assert not stage_thread.is_alive()
        writer.close()
        runtime.close()

    assert stage_result == [(None, "host_or_writer_changed")]
    assert len(provider.lookups) == len(provider.streams) == 2
    assert all(item.closed == 1 for item in provider.streams)
    assert attempt.writer_image_observations == ()
    assert attempt.writer_handoff_state == "retained_uncertain"
    assert attempt.evidence_state == "uncertain"
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "uncertain"
    assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "uncertain"
    assert capacity._ledger._observed["temporary_containment"] == [0, 0]
    assert capacity._ledger._uncertain["temporary_containment"] == [64 * 1024 * 1024, 2]
    files = list(roots["temporary_containment"]._path.iterdir())
    assert len(files) == 2 and all(path.read_bytes() == image_bytes() for path in files)
    assert capacity._scope_lease._state == "retained_uncertain"
    assert capacity._scope_lease._path.exists()


def test_profile_a_final_writer_publication_failure_reason_is_preserved(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    integration = lifecycle._worker_storage_integration
    provider = _WriterDownloadStream(image_bytes())
    monkeypatch.setattr(
        integration, "_publish_single_image_writer_observation_locked",
        lambda *_args: (None, "writer_handoff_accounting_unavailable"),
    )
    try:
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "writer_handoff_accounting_unavailable")
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "uncertain"
        assert attempt.writer_image_observation is None
    finally:
        writer.close()
        runtime.close()


def test_profile_a_settled_writer_publication_allows_clean_scope_lease_release(
        native_profile_a_worker_storage):
    from test_comfy_output_containment import image_bytes

    _roots, capacity, _reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(_roots, capacity, _reference, project_path)
    )
    try:
        observation, status = runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=_WriterDownloadStream(image_bytes()),
            characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_staged_non_authoritative"
        assert observation.verified_image_count == 1
        assert attempt.writer_handoff_state == "staged_non_authoritative"
    finally:
        writer.close()
        runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    capacity.close()
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    assert capacity._scope_lease._state == "released"
    assert not capacity._scope_lease._path.exists()


def test_profile_a_writer_handoff_reuses_one_borrowed_owner_for_sequential_requests(
        native_profile_a_worker_storage):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, worker, _prepared_request, _preadmission, evidence0, attempt0, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, run_count=2,
        )
    )
    try:
        first, status = runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence0, writer, stream_provider=_WriterDownloadStream(image_bytes()),
            characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_staged_non_authoritative"
        assert first.request_index == 0
        assert attempt0.writer_handoff_state == "staged_non_authoritative"

        prepared1 = _prepared(lifecycle, 1)
        submission_correlation = runtime.generation_worker_http_correlation_for_characterization(
            1, kind="submission",
        )
        submission_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
            "submission", prepared1, None, submission_correlation,
        )
        assert status == "admitted_non_executing"
        preadmission1, status = runtime.pre_admit_generation_worker_staging_for_characterization(
            submission_lease, CapacityEstimate(32 * 1024 * 1024, 1),
        )
        assert status == "pre_admitted_non_authoritative"
        prompt_id1 = str(uuid.uuid4())
        worker._submission_transport._wire_factory = lambda _origin, _timeout: _Connection(
            prompt_id=prompt_id1, history_body_ref=worker._test_history_body_ref,
        )
        submission1 = worker.perform_for_characterization(
            "submission", prepared1, None, submission_correlation,
        )
        submission_status = runtime.observe_generation_worker_http_result_for_characterization(
            submission_lease, submission1,
        )
        assert submission_status == "observed_non_authoritative", (
            submission_status, submission1.outcome, worker.observation_for_characterization(),
        )

        worker._test_history_body_ref[0] = _history_json_for(prepared1, prompt_id1)
        history_correlation = runtime.generation_worker_http_correlation_for_characterization(
            1, kind="history", prompt_id=prompt_id1,
        )
        history_lease, status = runtime.begin_generation_worker_http_operation_for_characterization(
            "history", prepared1, prompt_id1, history_correlation,
        )
        assert status == "admitted_non_executing"
        history1 = worker.perform_for_characterization(
            "history", prepared1, prompt_id1, history_correlation,
        )
        assert runtime.observe_generation_worker_http_result_for_characterization(
            history_lease, history1,
        ) == "observed_non_authoritative"
        evidence1, status = runtime.observe_generation_worker_remote_output_writer_evidence_for_characterization(
            preadmission1,
        )
        assert status == "remote_output_writer_evidence_observed_non_authoritative"

        attempt1 = lifecycle._worker_storage_integration._storage_preadmission_attempts[1]
        assert attempt1.reservation is not attempt0.reservation
        assert attempt1.capacity_operation is not attempt0.capacity_operation
        from core.generation_windows_protected_assets import (
            WindowsProtectedAssetsCharacterization,
        )
        alternate_writer = WindowsProtectedAssetsCharacterization.borrow_profile_a_writer_for_characterization(
            capacity, characterization=True, disposable_opt_in=True,
        )
        alternate_provider = _WriterDownloadStream(image_bytes())
        try:
            assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
                evidence1, alternate_writer, stream_provider=alternate_provider,
                characterization=True, disposable_opt_in=True,
            ) == (None, "writer_handoff_owner_mismatch")
            assert alternate_writer._profile_a_handoff_integration is None
            assert alternate_provider.lookups == []
            assert len(writer._files) == 1
        finally:
            alternate_writer.close()
        second, status = runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence1, writer, stream_provider=_WriterDownloadStream(image_bytes()),
            characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_staged_non_authoritative"
        assert second.request_index == 1
        assert attempt1.writer_handoff_state == "staged_non_authoritative"
        assert writer._profile_a_handoff_integration is lifecycle._worker_storage_integration
        assert len(writer._files) == len(writer._images) == 2
        assert len(capacity._ledger._reservations) == 2
        assert all(record["state"] == "completed"
                   for record in capacity._ledger._reservations.values())
    finally:
        writer.close()
        assert all(root._closed is False for root in roots.values())
        runtime.close()


@pytest.mark.parametrize("descriptor_count", [2, 16])
def test_profile_a_multi_image_writer_batch_uses_one_reservation_and_publishes_count_only(
        native_profile_a_worker_storage, descriptor_count):
    import hashlib

    from core import generation_windows_protected_storage as windows
    from test_comfy_output_containment import image_bytes
    from ui.agent_generation_original_host_worker_storage import (
        GenerationWorkerProtectedWriterObservation,
    )

    roots, capacity, _reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, _reference, project_path, descriptor_count=descriptor_count,
        )
    )
    data = image_bytes()

    def assert_host_locks_released():
        assert not runtime._publication_gate.locked()
        acquired = lifecycle._lock.acquire(blocking=False)
        assert acquired
        if acquired:
            lifecycle._lock.release()
        assert not runtime.generation_jobs._lock._is_owned()
        assert not runtime._generation_executor_inbox._lock._is_owned()

    provider = _WriterDownloadBatchProvider(
        data,
        on_call=lambda _index: assert_host_locks_released(),
        on_read=assert_host_locks_released,
        on_close=assert_host_locks_released,
    )
    operation_keys, reservation_keys = set(capacity._ledger._operations), set(
        capacity._ledger._reservations,
    )
    try:
        observation, status = runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert type(observation) is GenerationWorkerProtectedWriterObservation
        assert status == "protected_image_batch_staged_non_authoritative"
        assert (observation.request_index, observation.verified_image_count,
                observation.capacity_accounted) == (0, descriptor_count, True)
        assert observation.write_authorized is False
        assert observation.execution_available is False
        assert observation.protected_storage_available is False
        assert observation.promotion_available is False
        assert observation.candidate_publication_allowed is False
        assert observation.project_save_allowed is False
        assert observation.authorship == "unverified"
        assert not ({"images", "image", "paths", "descriptor", "write_admission"}
                    & set(observation.__dataclass_fields__))

        remote = attempt.remote_receipt
        expected_ids = tuple(item.identity for item in remote.images)
        assert tuple(item.descriptor_identity for item in attempt.writer_image_observations) == expected_ids
        assert attempt.writer_image_observations is writer._profile_a_stream_batches[
            (attempt.prepared.request_id, remote.identity)
        ]
        assert len(provider.lookups) == len(provider.streams) == descriptor_count
        assert tuple(item.descriptor_identity for item in provider.lookups) == expected_ids
        assert all(item.closed == 1 for item in provider.streams)
        assert set(capacity._ledger._operations) == operation_keys
        assert set(capacity._ledger._reservations) == reservation_keys
        assert len(operation_keys) == len(reservation_keys) == 1
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "completed"
        record = capacity._ledger._reservations[attempt.reservation]
        assert record["state"] == "completed"
        assert record["write"] is attempt.writer_admission
        assert record["completed_observed_delta"]["temporary_containment"] == (
            len(data) * descriptor_count, descriptor_count,
        )
        assert capacity._ledger._active_write is None
        assert attempt.writer_create_attempt_count == descriptor_count
        assert attempt.writer_handoff_state == "staged_non_authoritative"
        assert len(writer._files) == len(writer._images) == descriptor_count
        for descriptor_id, image_observation in zip(expected_ids, attempt.writer_image_observations):
            assert writer._stream_images[(attempt.prepared.request_id, descriptor_id)] is image_observation
            image = image_observation.image
            path, handle, identity, acl = writer._files[(image.purpose, image.storage_identity)]
            assert path.parent == roots["temporary_containment"]._path
            assert path.read_bytes() == data
            assert image.content_sha256 == hashlib.sha256(data).hexdigest()
            assert image.byte_count == len(data)
            assert windows._identity(handle) == identity == windows._ordinary(path, directory=False)
            assert windows._acl(handle, roots["temporary_containment"]._api,
                                roots["temporary_containment"]._user) == acl[0]
            assert image.image_format == "PNG"
        row = next(item for item in capacity.readiness()["roots"]
                   if item["purpose"] == "temporary_containment")
        assert (row["reserved_bytes"], row["reserved_entries"],
                row["observed_used_bytes"], row["observed_used_entries"],
                row["retained_uncertain_bytes"], row["retained_uncertain_entries"]) == (
                    0, 0, len(data) * descriptor_count, descriptor_count, 0, 0,
                )
        assert runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "writer_handoff_evidence_unavailable")
        assert len(provider.lookups) == descriptor_count
    finally:
        writer.close()
        runtime.close()
    runtime.finish_generation_worker_storage_close_for_characterization()
    capacity.close()
    assert capacity._ledger._reservations[attempt.reservation]["state"] == "completed"
    assert capacity._scope_lease._state == "released"
    assert not capacity._scope_lease._path.exists()


def test_profile_a_multi_image_capacity_compensation_is_exactly_idempotent(
        native_profile_a_worker_storage):
    from core import generation_windows_protected_storage as windows
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )
    data = image_bytes()
    provider = _WriterDownloadBatchProvider(data)

    def capacity_row():
        return next(item for item in capacity._ledger.readiness()["roots"]
                    if item["purpose"] == "temporary_containment")

    def retained_file_evidence(*, reopen=False):
        observed = {}
        root = roots["temporary_containment"]
        for key, (path, handle, identity, _acl) in writer._files.items():
            checked_handle = windows._open(path, False, root._api) if reopen else handle
            try:
                observed[key] = (
                    path, path.read_bytes(), identity, windows._identity(checked_handle),
                    windows._ordinary(path, directory=False),
                    windows._acl(checked_handle, root._api, root._user),
                )
            finally:
                if reopen:
                    checked_handle.Close()
        return observed

    try:
        observation, status = runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert observation is not None
        assert status == "protected_image_batch_staged_non_authoritative"
        observations = attempt.writer_image_observations
        assert len(observations) == 2
        assert observations is writer._profile_a_stream_batches[
            (attempt.prepared.request_id, attempt.remote_receipt.identity)
        ]
        assert all(item.image.purpose == "temporary_containment"
                   for item in observations)

        files_before = retained_file_evidence()
        assert len(files_before) == 2
        assert all(row[1] == data and row[2] == row[3] == row[4]
                   for row in files_before.values())
        lease_path = capacity._scope_lease._path
        assert capacity._scope_lease._state == "held" and lease_path.exists()
        lease_identity_before = capacity._scope_lease._identity_value()
        lease_acl_before = capacity._scope_lease._acl
        assert lease_identity_before == capacity._scope_lease._identity
        assert capacity._scope_lease._api[2].GetFileSize(
            capacity._scope_lease._handle,
        ) == 0

        capacity.retain_completed_asset_stream_batch_uncertain_for_characterization(
            attempt.capacity_operation, attempt.writer_admission, writer, observations,
        )
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "uncertain"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "uncertain"
        first_row = capacity_row()
        first_counters = (
            first_row["reserved_bytes"], first_row["reserved_entries"],
            first_row["observed_used_bytes"], first_row["observed_used_entries"],
            first_row["retained_uncertain_bytes"], first_row["retained_uncertain_entries"],
            tuple(capacity._ledger._observed["temporary_containment"]),
            tuple(capacity._ledger._uncertain["temporary_containment"]),
        )
        assert first_counters == (
            0, 0, 0, 0, 64 * 1024 * 1024, 2, (0, 0), (64 * 1024 * 1024, 2),
        )

        # Repeating only the exact owner/token/ordered-observation tuple is a
        # no-op after the ledger's real terminal state became `uncertain`.
        capacity.retain_completed_asset_stream_batch_uncertain_for_characterization(
            attempt.capacity_operation, attempt.writer_admission, writer, observations,
        )
        second_row = capacity_row()
        second_counters = (
            second_row["reserved_bytes"], second_row["reserved_entries"],
            second_row["observed_used_bytes"], second_row["observed_used_entries"],
            second_row["retained_uncertain_bytes"], second_row["retained_uncertain_entries"],
            tuple(capacity._ledger._observed["temporary_containment"]),
            tuple(capacity._ledger._uncertain["temporary_containment"]),
        )
        assert second_counters == first_counters
        assert capacity._scope_lease._state == "held"
        assert (lease_path.exists()
                and capacity._scope_lease._identity_value() == lease_identity_before
                and capacity._scope_lease._acl == lease_acl_before
                and capacity._scope_lease._api[2].GetFileSize(
                    capacity._scope_lease._handle,
                ) == 0)
        assert retained_file_evidence() == files_before

        with pytest.raises(ValueError, match="write_admission_unavailable"):
            capacity.retain_completed_asset_stream_batch_uncertain_for_characterization(
                attempt.capacity_operation, object(), writer, observations,
            )
        with pytest.raises(ValueError, match="write_admission_unavailable"):
            capacity.retain_completed_asset_stream_batch_uncertain_for_characterization(
                attempt.capacity_operation, attempt.writer_admission, writer,
                tuple(reversed(observations)),
            )
        assert (
            tuple(capacity._ledger._observed["temporary_containment"]),
            tuple(capacity._ledger._uncertain["temporary_containment"]),
        ) == ((0, 0), (64 * 1024 * 1024, 2))
        assert retained_file_evidence() == files_before
    finally:
        writer.close()
        runtime.close()
        runtime.finish_generation_worker_storage_close_for_characterization()
        capacity.close()

    assert capacity._scope_lease._state == "retained_uncertain"
    assert capacity._scope_lease._path.exists()
    assert capacity._scope_lease._identity == lease_identity_before
    assert capacity._scope_lease._acl == lease_acl_before
    assert retained_file_evidence(reopen=True) == files_before


def test_profile_a_multi_image_writer_failure_after_first_create_retains_whole_reservation(
        native_profile_a_worker_storage):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )
    provider = _WriterDownloadBatchProvider(image_bytes(), fail_at=1)
    try:
        assert runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        assert len(provider.lookups) == 2
        assert len(provider.streams) == 1 and provider.streams[0].closed == 1
        assert attempt.writer_create_attempt_count == 2
        assert attempt.writer_handoff_state == "retained_uncertain"
        assert attempt.evidence_state == "uncertain"
        assert attempt.writer_image_observation is None
        assert attempt.writer_image_observations == ()
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "retained_uncertain"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "retained_uncertain"
        assert capacity._ledger._active_write is None
        assert capacity._ledger._observed["temporary_containment"] == [0, 0]
        assert capacity._ledger._uncertain["temporary_containment"] == [64 * 1024 * 1024, 2]
        files = list(roots["temporary_containment"]._path.iterdir())
        assert len(files) == 2
        assert sorted(path.stat().st_size for path in files) == [0, len(image_bytes())]
        assert not writer._stream_images
        assert len(writer._stream_pending_images) == 1
        assert runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "writer_handoff_evidence_unavailable")
        assert len(provider.lookups) == 2
        capacity.close()
        assert capacity._scope_lease._state == "retained_uncertain"
        assert capacity._scope_lease._path.exists()
    finally:
        writer.close()
        runtime.close()


@pytest.mark.parametrize("invalidation", ["claim", "project_reference", "capacity_close"])
def test_profile_a_multi_image_host_or_capacity_invalidation_between_images_retains_all_possible_files(
        native_profile_a_worker_storage, invalidation):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )

    def invalidate_after_first_image(index):
        if index == 1:
            if invalidation == "claim":
                runtime.generation_jobs.invalidate_execution_custody()
            elif invalidation == "project_reference":
                reference.close()
            else:
                capacity.close()

    provider = _WriterDownloadBatchProvider(image_bytes(), on_call=invalidate_after_first_image)
    try:
        assert runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        assert len(provider.lookups) == len(provider.streams) == 2
        assert all(stream.closed == 1 for stream in provider.streams)
        assert attempt.writer_create_attempt_count == 2
        assert attempt.writer_handoff_state == "retained_uncertain"
        assert attempt.evidence_state == "uncertain"
        assert attempt.writer_image_observation is None
        assert attempt.writer_image_observations == ()
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "retained_uncertain"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "retained_uncertain"
        assert capacity._ledger._active_write is None
        assert capacity._ledger._observed["temporary_containment"] == [0, 0]
        assert capacity._ledger._uncertain["temporary_containment"] == [64 * 1024 * 1024, 2]
        files = list(roots["temporary_containment"]._path.iterdir())
        assert len(files) == 2
        assert sorted(path.stat().st_size for path in files) == [0, len(image_bytes())]
        assert not writer._stream_images
        assert len(writer._stream_pending_images) == 1
        repeated = runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert repeated[0] is None
        assert repeated[1] in {"host_evidence_unavailable", "writer_handoff_evidence_unavailable"}
        assert len(provider.lookups) == 2
        if invalidation == "capacity_close":
            assert capacity._scope_lease._state == "retained_uncertain"
            assert capacity._scope_lease._path.exists()
    finally:
        writer.close()
        runtime.close()


def test_profile_a_multi_image_native_inventory_mismatch_withholds_batch_publication(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )
    armed = False
    original_scan = capacity._scan

    def corrupt_aggregate_inventory_after_both_streams():
        nonlocal armed
        inventory = original_scan()
        if armed:
            armed = False
            staged = inventory["temporary_containment"]
            name = sorted(staged)[0]
            identity, byte_count, acl = staged[name]
            staged[name] = (identity, byte_count + 1, acl)
        return inventory

    monkeypatch.setattr(capacity, "_scan", corrupt_aggregate_inventory_after_both_streams)

    def arm_after_second_stream(index):
        nonlocal armed
        if index == 1:
            armed = True

    provider = _WriterDownloadBatchProvider(image_bytes(), on_call=arm_after_second_stream)
    try:
        assert runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        assert not armed
        assert len(provider.lookups) == len(provider.streams) == 2
        assert all(stream.closed == 1 for stream in provider.streams)
        assert attempt.writer_handoff_state == "retained_uncertain"
        assert attempt.evidence_state == "uncertain"
        assert attempt.writer_image_observations == ()
        assert writer._uncertain is True
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "retained_uncertain"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "retained_uncertain"
        assert capacity._ledger._observed["temporary_containment"] == [0, 0]
        assert capacity._ledger._uncertain["temporary_containment"] == [64 * 1024 * 1024, 2]
        files = list(roots["temporary_containment"]._path.iterdir())
        assert len(files) == 2 and all(path.read_bytes() == image_bytes() for path in files)
    finally:
        writer.close()
        runtime.close()


def test_profile_a_multi_image_writer_close_waits_for_uncertain_batch_without_deadlock(
        native_profile_a_worker_storage):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )
    stream_entered = threading.Event()
    continue_stream = threading.Event()
    close_waiting = threading.Event()
    stage_result, close_result = [], []

    class _SignallingEvent:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def set(self):
            self.wrapped.set()

        def clear(self):
            self.wrapped.clear()

        def wait(self, timeout=None):
            close_waiting.set()
            return self.wrapped.wait(timeout)

    writer._capacity_idle = _SignallingEvent(writer._capacity_idle)

    def pause_second_stream(index):
        if index == 1:
            stream_entered.set()
            assert continue_stream.wait(5)

    provider = _WriterDownloadBatchProvider(image_bytes(), on_call=pause_second_stream)
    stage_thread = threading.Thread(target=lambda: stage_result.append(
        runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ),
    ))
    close_thread = threading.Thread(target=lambda: close_result.append(writer.close()))
    try:
        stage_thread.start()
        assert stream_entered.wait(5)
        close_thread.start()
        assert close_waiting.wait(5)
        continue_stream.set()
        stage_thread.join(5)
        close_thread.join(5)
        assert not stage_thread.is_alive() and not close_thread.is_alive()
        assert stage_result == [(None, "protected_writer_stage_failed")]
        assert close_result == [None]
        assert len(provider.lookups) == len(provider.streams) == 2
        assert all(stream.closed == 1 for stream in provider.streams)
        assert attempt.writer_handoff_state == "retained_uncertain"
        assert attempt.writer_image_observations == ()
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "retained_uncertain"
        assert capacity._ledger._uncertain["temporary_containment"] == [64 * 1024 * 1024, 2]
        files = list(roots["temporary_containment"]._path.iterdir())
        assert len(files) == 2
        assert sorted(path.stat().st_size for path in files) == [0, len(image_bytes())]
    finally:
        continue_stream.set()
        if stage_thread.is_alive():
            stage_thread.join(5)
        if close_thread.is_alive():
            close_thread.join(5)
        writer.close()
        runtime.close()
        capacity.close()


def test_profile_a_multi_image_writer_refuses_insufficient_reserved_bytes_before_create(
        native_profile_a_worker_storage, monkeypatch):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker, _prepared, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )
    provider = _WriterDownloadBatchProvider(b"unused")
    monkeypatch.setattr(capacity, "_staging_reservation_covers_for_characterization",
                        lambda *_args: False)
    try:
        assert runtime.stage_generation_worker_remote_output_batch_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "writer_handoff_reservation_unavailable")
        assert provider.lookups == []
        assert not writer._files and not writer._unobserved_files
        assert capacity._ledger._active_write is None
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "reserved"
        assert not list(roots["temporary_containment"]._path.iterdir())
        lifecycle = runtime._generation_original_host_lifecycle
        lifecycle._worker_storage_integration._cancel_staging_preadmission_attempt(attempt)
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "cancelled"
    finally:
        writer.close()
        runtime.close()


def test_profile_a_writer_handoff_refuses_multiple_descriptors_before_admission(
        native_profile_a_worker_storage):
    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(
            roots, capacity, reference, project_path, descriptor_count=2,
        )
    )
    provider = _WriterDownloadStream(b"unused")
    try:
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "single_image_output_required")
        assert provider.lookups == []
        assert writer._stream_attempts == set()
        assert not writer._files and not writer._unobserved_files
        assert capacity._ledger._active_write is None
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "cancelled"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "cancelled"
        assert capacity._ledger._reserved["temporary_containment"] == [0, 0]
        assert capacity._ledger._uncertain["temporary_containment"] == [0, 0]
        assert not list(roots["temporary_containment"]._path.iterdir())
    finally:
        writer.close()
        runtime.close()


def test_profile_a_writer_handoff_rejects_copied_evidence_but_keeps_exact_evidence_usable(
        native_profile_a_worker_storage):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, _attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    provider = _WriterDownloadStream(image_bytes())
    try:
        for forged in (replace(evidence), replace(evidence, request_index=1),
                       replace(evidence, descriptor_count=2)):
            assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
                forged, writer, stream_provider=provider,
                characterization=True, disposable_opt_in=True,
            ) == (None, "writer_handoff_evidence_unavailable")
        assert provider.lookups == []
        assert not writer._files
        observation, status = runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_staged_non_authoritative"
        assert observation.write_authorized is False
        assert len(provider.lookups) == 1
    finally:
        writer.close()
        runtime.close()


def test_profile_a_writer_handoff_rejects_foreign_borrowed_writer_owner(
        native_profile_a_worker_storage, tmp_path):
    from core import generation_windows_protected_assets as assets
    from core import generation_windows_protected_storage as windows
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, _attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    api = windows._api()
    user = windows._current_user(api)
    foreign_scope = tmp_path / "foreign-profile-a-scope"
    api[2].CreateDirectory(str(foreign_scope), windows._security_attributes(api, user))
    foreign_roots = {}
    foreign_capacity = None
    foreign_writer = None
    provider = _WriterDownloadStream(image_bytes())
    try:
        for purpose in _PROFILE_A_PURPOSES:
            path = foreign_scope / purpose
            api[2].CreateDirectory(str(path), windows._security_attributes(api, user))
            foreign_roots[purpose] = windows.WindowsProtectedRootCharacterization.capture_for_characterization(
                str(foreign_scope), str(path), purpose,
                characterization=True, disposable_opt_in=True,
            )
        foreign_capacity = WindowsProtectedStorageAdmissionCharacterization.capture_profile_a_root_set_for_characterization(
            str(foreign_scope), foreign_roots,
            characterization=True, disposable_opt_in=True,
        )
        foreign_writer = assets.WindowsProtectedAssetsCharacterization.borrow_profile_a_writer_for_characterization(
            foreign_capacity, characterization=True, disposable_opt_in=True,
        )
        attempt = _lifecycle._worker_storage_integration._storage_preadmission_attempts[0]
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, foreign_writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "writer_handoff_root_mismatch")
        assert provider.lookups == []
        assert foreign_capacity._ledger._reservations == {}
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "reserved"
        assert not list(foreign_roots["temporary_containment"]._path.iterdir())

        observation, status = runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        )
        assert status == "protected_image_staged_non_authoritative"
        assert observation.verified_image_count == 1
        assert len(provider.lookups) == 1
    finally:
        if foreign_writer is not None:
            foreign_writer.close()
        if foreign_capacity is not None:
            foreign_capacity.close()
        for root in foreign_roots.values():
            root.close()
        writer.close()
        runtime.close()


def test_profile_a_writer_handoff_cancels_exact_admission_on_host_revocation_before_create(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    original_admit = capacity.admit_write_for_characterization
    provider = _WriterDownloadStream(image_bytes())

    def admit_then_revoke(operation, reservation):
        token = original_admit(operation, reservation)
        lifecycle.close()
        return token

    monkeypatch.setattr(capacity, "admit_write_for_characterization", admit_then_revoke)
    try:
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        assert attempt.writer_create_boundary_crossed is False
        assert provider.lookups == []
        assert not writer._files and not writer._unobserved_files
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "cancelled"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "cancelled"
        assert capacity._ledger._active_write is None
        assert capacity._ledger._reserved["temporary_containment"] == [0, 0]
        assert capacity._ledger._uncertain["temporary_containment"] == [0, 0]
        assert attempt.state == "cancelled"
        assert attempt.writer_handoff_state == "refused"
        assert not writer._uncertain
        assert not list(roots["temporary_containment"]._path.iterdir())
    finally:
        writer.close()
        runtime.close()


def test_profile_a_writer_close_before_create_cancels_unused_admission(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    original_admit = capacity.admit_write_for_characterization
    close_started = threading.Event()
    close_thread = None
    provider = _WriterDownloadStream(image_bytes())

    def admit_then_start_close(operation, reservation):
        nonlocal close_thread
        token = original_admit(operation, reservation)

        def close_writer():
            close_started.set()
            writer.close()

        close_thread = threading.Thread(target=close_writer)
        close_thread.start()
        assert close_started.wait(5)
        assert writer._revoking_event.wait(5)
        return token

    monkeypatch.setattr(capacity, "admit_write_for_characterization", admit_then_start_close)
    try:
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        close_thread.join(5)
        assert not close_thread.is_alive()
        assert writer._closed is True
        assert attempt.writer_create_boundary_crossed is False
        assert provider.lookups == []
        assert not writer._files and not writer._unobserved_files
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "cancelled"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "cancelled"
        assert capacity._ledger._active_write is None
        assert capacity._ledger._uncertain["temporary_containment"] == [0, 0]
        assert all(root._closed is False for root in roots.values())
    finally:
        if close_thread is not None:
            close_thread.join(5)
        if not writer._closed:
            writer.close()
        runtime.close()


def test_profile_a_scope_lease_loss_before_create_cancels_unused_admission(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    original_project_readiness = reference.readiness
    calls = 0
    provider = _WriterDownloadStream(image_bytes())

    def lose_lease_on_final_project_observation():
        nonlocal calls
        calls += 1
        view = original_project_readiness()
        if calls == 2:
            capacity._scope_lease._state = "released"
        return view

    monkeypatch.setattr(reference, "readiness", lose_lease_on_final_project_observation)
    try:
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        assert calls == 2
        assert attempt.writer_create_boundary_crossed is False
        assert provider.lookups == []
        assert not writer._files and not writer._unobserved_files
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "cancelled"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "cancelled"
        assert capacity._ledger._active_write is None
        assert capacity._ledger._uncertain["temporary_containment"] == [0, 0]
    finally:
        writer.close()
        runtime.close()


def test_profile_a_capacity_close_after_write_admission_retains_without_create(
        native_profile_a_worker_storage, monkeypatch):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    original_admit = capacity.admit_write_for_characterization
    provider = _WriterDownloadStream(image_bytes())

    def admit_then_close(operation, reservation):
        token = original_admit(operation, reservation)
        capacity.close()
        return token

    monkeypatch.setattr(capacity, "admit_write_for_characterization", admit_then_close)
    try:
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        assert attempt.writer_create_boundary_crossed is False
        assert provider.lookups == []
        assert not writer._files and not writer._unobserved_files
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "retained_uncertain"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "retained_uncertain"
        assert capacity._ledger._active_write is None
        assert capacity._ledger._uncertain["temporary_containment"] == [32 * 1024 * 1024, 1]
        assert attempt.writer_handoff_state == "retained_uncertain"
    finally:
        writer.close()
        runtime.close()


@pytest.mark.parametrize("failure", ["short", "oversized", "decode", "readback"])
def test_profile_a_writer_stream_failure_retains_file_and_exact_capacity(
        native_profile_a_worker_storage, failure):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    data = image_bytes() if failure != "decode" else b"not an image"
    declared_length = len(data) + 1 if failure == "short" else (
        32 * 1024 * 1024 + 1 if failure == "oversized" else len(data)
    )
    provider = _WriterDownloadStream(data, declared_length=declared_length)

    def mutate_after_sync(boundary):
        if boundary == "after_file_sync" and failure == "readback":
            path = next(iter(writer._files.values()))[0]
            path.write_bytes(b"changed after flush")

    writer._fault = mutate_after_sync
    try:
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "protected_writer_stage_failed")
        assert provider.closed == 1
        assert writer._uncertain is True
        assert attempt.writer_handoff_state == "retained_uncertain"
        assert attempt.evidence_state == "uncertain"
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "retained_uncertain"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "retained_uncertain"
        assert capacity._ledger._uncertain["temporary_containment"] == [32 * 1024 * 1024, 1]
        files = list(roots["temporary_containment"]._path.iterdir())
        assert len(files) == 1
        if failure == "oversized":
            assert files[0].read_bytes() == b""
        assert provider.lookups[0].descriptor_identity == attempt.remote_receipt.images[0].identity
        assert len(writer._stream_attempts) == 1
        assert runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=provider,
            characterization=True, disposable_opt_in=True,
        ) == (None, "writer_handoff_evidence_unavailable")
        assert len(provider.lookups) == 1
    finally:
        writer.close()
        runtime.close()


def test_profile_a_writer_close_after_create_retains_native_file_and_capacity(
        native_profile_a_worker_storage):
    from test_comfy_output_containment import image_bytes

    roots, capacity, reference, project_path = native_profile_a_worker_storage
    runtime, _lifecycle, _worker_instance, _prepared_request, _preadmission, evidence, attempt, writer = (
        _native_profile_a_writer_handoff(roots, capacity, reference, project_path)
    )
    created = threading.Event()
    continue_writer = threading.Event()
    close_finished = threading.Event()
    stream_provider = _WriterDownloadStream(image_bytes())
    stage_result = []
    close_errors = []

    def pause_after_create(boundary):
        if boundary == "after_file_create":
            created.set()
            assert continue_writer.wait(5)

    writer._fault = pause_after_create

    def stage():
        stage_result.append(runtime.stage_generation_worker_remote_output_with_protected_writer_for_characterization(
            evidence, writer, stream_provider=stream_provider,
            characterization=True, disposable_opt_in=True,
        ))

    def close_writer():
        try:
            writer.close()
        except BaseException as exc:
            close_errors.append(exc)
        finally:
            close_finished.set()

    stage_thread = threading.Thread(target=stage)
    close_thread = None
    try:
        stage_thread.start()
        assert created.wait(5)
        close_thread = threading.Thread(target=close_writer)
        close_thread.start()
        assert writer._revoking_event.wait(5)
        continue_writer.set()
        stage_thread.join(5)
        close_thread.join(5)
        assert not stage_thread.is_alive()
        assert not close_thread.is_alive()
        assert close_finished.is_set() and not close_errors
        assert stage_result == [(None, "protected_writer_stage_failed")]
        assert stream_provider.lookups == []
        assert writer._closed and writer._uncertain
        assert capacity._ledger._reservations[attempt.reservation]["state"] == "retained_uncertain"
        assert capacity._ledger._operations[attempt.capacity_operation]["state"] == "retained_uncertain"
        assert capacity._ledger._active_write is None
        assert capacity._ledger._reserved["temporary_containment"] == [0, 0]
        assert capacity._ledger._uncertain["temporary_containment"] == [32 * 1024 * 1024, 1]
        files = list(roots["temporary_containment"]._path.iterdir())
        assert len(files) == 1
        assert files[0].read_bytes() == b""
        assert all(root._closed is False for root in roots.values())
    finally:
        continue_writer.set()
        stage_thread.join(5)
        if close_thread is not None:
            close_thread.join(5)
        if not writer._closed:
            writer.close()
        runtime.close()
