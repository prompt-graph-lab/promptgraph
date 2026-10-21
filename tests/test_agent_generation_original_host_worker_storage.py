"""C2B-8D-19B worker/storage association; offline characterization only."""

import json
import io
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.comfy_http_history import PromptHTTPHistoryTransport
from core.comfy_http_submission import PromptHTTPSubmissionTransport
from core.comfy_prompt_request import prepare_frozen_prompt_request
from core.generation_storage_admission import (
    CapacityEstimate, ProtectedStorageCapacityLimits,
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
        return _Response((f'{{"prompt_id":"{self.prompt_id}"}}').encode("ascii"))

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


def _ready_generation_at_project_path(project_path, *, run_count=1):
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
