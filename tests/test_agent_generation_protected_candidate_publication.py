"""C2B-8D-11 protected Candidate integration; disposable Windows evidence only."""
import copy
import io
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest

from core import generation_windows_protected_assets as assets
from core import generation_windows_protected_storage as storage
from core.io import make_project_relative_path, resolve_project_asset_path
from ui.agent_generation_candidate_publication import GenerationCandidatePublication
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_job import GenerationJobRegistry
from ui.project_agent_session_pump import ProjectAgentSessionRuntime
from test_agent_generation_candidate_publication import app_owners
from test_agent_generation_comfy_executor import (
    harness, protected_promotion_for_active_request, result, successful_history,
)
from test_agent_generation_executable_manifest import host_for
from test_agent_generation_executable_review_ui import queued, identity, prepare, confirm
from test_agent_generation_executor_handoff import capture_start, start
from ui.agent_generation_protected_candidate_admission import GenerationProtectedCandidateAdmission


@pytest.fixture
def protected_scope(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    api = storage._api()
    scope = tmp_path / "owner-only-approved-output"
    api[2].CreateDirectory(str(scope), storage._security_attributes(api, storage._current_user(api)))
    yield scope, api


def _scenario(scope, api, *, approved_child=False, image_count=2):
    approved = scope
    if approved_child:
        approved = scope / "approved-output-child"
        api[2].CreateDirectory(str(approved), storage._security_attributes(api, storage._current_user(api)))

    base_provider = host_for()

    def provider(project, runs):
        host = base_provider(project, runs)
        host["generation_options"]["output_directory"] = str(approved)
        return host

    runtime, route, _epoch, state, _args, provider = queued(
        count=2, runs=1, provider=provider, with_swap=True)
    state["history"] = []
    runtime.generation_jobs = GenerationJobRegistry(characterization=True)
    runtime._generation_executor_inbox = GenerationExecutorInbox(characterization=True)
    runtime.synchronize_target(state["project"], state["current_project_path"])
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: 0) == "certified"
    held = runtime._executable_review
    assert confirm(state, runtime, provider, held) == "confirmed"
    values = (runtime, route, state, provider, held, capture_start(runtime))
    values, adapter, sent = harness(values, provider=lambda prepared, prompt: result(
        prepared, prompt, history_json=successful_history(prompt, image_count)))
    accepted = start(values, adapter.accept_and_run_for_characterization)
    protected = assets.WindowsProtectedAssetsCharacterization.provision_for_characterization(
        str(scope), characterization=True, disposable_opt_in=True)
    promoter, promotion_receipt, freshness = protected_promotion_for_active_request(
        values, adapter, protected)
    assert adapter.accept_protected_promotion_for_characterization(
        promoter, promotion_receipt).status == "protected_outputs_ready"
    admission = GenerationProtectedCandidateAdmission.create_for_characterization(
        state, runtime, adapter._envelope, characterization=True, disposable_opt_in=True)
    admission_result = admission.admit_for_characterization(
        promoter, promotion_receipt, promotion_receipt._accepted._remote, 0)
    assert admission_result.status == "evidence_observed"
    owners = app_owners(state)
    publisher = GenerationCandidatePublication.create_protected_for_characterization(
        state, runtime, adapter._envelope, approved_directory=str(approved),
        candidate_factory=owners["_make_generated_candidate_record"],
        candidate_appender=owners["_append_line_generated_candidates"],
        save_project=lambda *_args, **_kwargs: pytest.fail("Project save is out of scope"),
        characterization=True)
    return {
        "scope": scope, "approved": approved, "api": api, "runtime": runtime,
        "state": state, "values": values, "adapter": adapter, "sent": sent,
        "accepted": accepted, "protected": protected, "promoter": promoter,
        "promotion_receipt": promotion_receipt, "remote": promotion_receipt._accepted._remote,
        "freshness": freshness, "admission": admission, "admission_result": admission_result,
        "observation": admission_result.observation, "publisher": publisher,
    }


@pytest.fixture
def scenario(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api)
    yield case
    case["runtime"].close()
    case["promoter"].close()
    case["promotion_receipt"]._acceptance_owner.close()
    case["protected"].close()


@pytest.mark.parametrize("image_count", [1, 2])
def test_exact_protected_batch_uses_existing_candidate_writer_and_undo(protected_scope, image_count):
    scope, api = protected_scope
    case = _scenario(scope, api, image_count=image_count)
    try:
        _assert_exact_publication(case, image_count)
    finally:
        case["runtime"].close()
        case["promoter"].close()
        case["promotion_receipt"]._acceptance_owner.close()
        case["protected"].close()


def _assert_exact_publication(case, image_count):

    project_before = copy.deepcopy(case["state"]["project"])
    outcome = case["publisher"].publish_protected_for_characterization(
        case["admission"], case["observation"])

    assert outcome.registration_state == "registered"
    assert outcome.promotion_state == "protected_verified"
    assert outcome.registered_count == image_count
    assert case["publisher"].publish_protected_for_characterization(
        case["admission"], case["observation"]) == outcome
    assert case["publisher"].publish_for_characterization(
        object(), object(), object()).registration_state == "writer_mode_mismatch"
    assert len(case["sent"]) == 1 and case["adapter"]._index == 0

    project = case["state"]["project"]
    source_line = next(line for line in project.prompt_lines if line.id == "illustration-000")
    records = source_line.generated_candidates
    assert len(records) == image_count
    assert tuple(record["generation_provenance"]["descriptor_identity"] for record in records) == tuple(
        image.descriptor_identity for image in case["promotion_receipt"].images)
    assert tuple(record["generation_provenance"]["content_sha256"] for record in records) == tuple(
        image.promoted_image.content_sha256 for image in case["promotion_receipt"].images)
    assert all(Path(record["path"]).is_relative_to(case["approved"]) for record in records)
    assert all("local_receipt_identity" not in record["generation_provenance"] for record in records)
    assert records[0]["seed"] == 0 and records[0]["seed_mode"] == "frozen_execution"
    assert records[0]["prompt_text"] == "red" and records[0]["negative_prompt"] == "negative 0"
    assert case["state"]["history"] == [project_before]
    snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
    assert snapshot["requests"][0]["registered_count"] == image_count
    assert snapshot["requests"][0]["state"] == "completed"
    assert snapshot["save_state"] == "not_attempted"
    assert case["publisher"].save_for_characterization() == "protected_save_not_in_scope"
    assert case["runtime"].generation_jobs.execution_available is False


def test_protected_asset_path_must_be_under_exact_frozen_approved_output(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api, approved_child=True)
    appended = []
    case["publisher"]._appender = lambda line, records: appended.extend(records)
    try:
        outcome = case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"])
        assert outcome.registration_state == "registration_failed"
        assert appended == []
        assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)[
            "requests"][0]["registered_count"] == 0
        assert all(Path(row.promoted_image.storage_identity).name == row.promoted_image.storage_identity
                   for row in case["promotion_receipt"].images)
    finally:
        case["runtime"].close()
        case["promoter"].close()
        case["promotion_receipt"]._acceptance_owner.close()
        case["protected"].close()


@pytest.mark.parametrize("drift", ["content", "acl", "host_path", "source"])
def test_protected_candidate_rechecks_native_and_original_host_before_append(scenario, drift):
    case = scenario
    image = case["promotion_receipt"].images[0].promoted_image
    path = case["protected"]._files[(image.purpose, image.storage_identity)][0]
    original = path.read_bytes()
    if drift == "content":
        changed = io.BytesIO()
        Image.new("RGB", (31, 29), "black").save(changed, format="PNG")
        path.write_bytes(changed.getvalue())
    elif drift == "acl":
        from test_generation_windows_protected_storage import mutate_disposable_acl
        mutate_disposable_acl(path, case["api"], "writable_principal")
    elif drift == "host_path":
        case["state"]["current_project_path"] += ".save-as"
    else:
        case["state"]["project"].prompt_lines[-1].current_text += " changed"

    appended = []
    case["publisher"]._appender = lambda line, records: appended.extend(records)
    outcome = case["publisher"].publish_protected_for_characterization(
        case["admission"], case["observation"])
    assert outcome.registration_state in {"registration_failed", "stale_original_host"}
    assert appended == []
    assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)[
        "requests"][0]["registered_count"] == 0
    if drift == "content":
        assert path.exists() and path.read_bytes() != original
    else:
        assert path.exists()


@pytest.mark.parametrize("substitution", ["copied_observation", "copied_admission_result"])
def test_copied_admission_evidence_cannot_authorize_writer(scenario, substitution):
    case = scenario
    if substitution == "copied_observation":
        supplied = replace(case["observation"])
    else:
        supplied = replace(case["admission_result"],
                           observation=replace(case["observation"])).observation
    outcome = case["publisher"].publish_protected_for_characterization(case["admission"], supplied)
    assert outcome.registration_state == "admission_mismatch"
    assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)[
        "requests"][0]["registered_count"] == 0


@pytest.mark.parametrize("terminal", [
    "promotion_close", "acceptance_close", "acceptance_invalidate", "protected_close",
    "admission_close", "runtime_close",
])
def test_owner_close_waits_for_candidate_appender_commit(scenario, terminal):
    case = scenario
    entered, resume, close_done = threading.Event(), threading.Event(), threading.Event()
    original_appender = case["publisher"]._appender
    def blocked_appender(line, records):
        entered.set()
        assert resume.wait(10)
        original_appender(line, records)
    case["publisher"]._appender = blocked_appender
    publication = []
    worker = threading.Thread(target=lambda: publication.append(
        case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"])))
    worker.start()
    assert entered.wait(10)

    def close_owner():
        if terminal == "promotion_close":
            case["promoter"].close()
        elif terminal == "acceptance_close":
            case["promotion_receipt"]._acceptance_owner.close()
        elif terminal == "acceptance_invalidate":
            case["promotion_receipt"]._acceptance_owner.invalidate_for_characterization()
        elif terminal == "protected_close":
            case["protected"].close()
        elif terminal == "admission_close":
            case["admission"].close()
        else:
            case["runtime"].close()
        close_done.set()
    closer = threading.Thread(target=close_owner)
    closer.start()
    assert not close_done.wait(0.05)
    resume.set()
    worker.join(15)
    closer.join(15)
    assert not worker.is_alive() and not closer.is_alive()
    assert close_done.is_set()
    assert len(publication) == 1 and publication[0].registration_state == "registered"


@pytest.mark.parametrize("failure", ["before_mutation", "partial_then_raise"])
def test_appender_failure_is_observed_once_without_retry(scenario, failure):
    case = scenario
    original = case["publisher"]._appender
    calls = []

    def failing_appender(line, records):
        calls.append(tuple(records))
        if failure == "partial_then_raise":
            original(line, records[:1])
        raise RuntimeError("injected appender failure")

    case["publisher"]._appender = failing_appender
    first = case["publisher"].publish_protected_for_characterization(
        case["admission"], case["observation"])
    second = case["publisher"].publish_protected_for_characterization(
        case["admission"], case["observation"])

    assert first.registration_state == "registration_uncertain"
    assert second == first and len(calls) == 1
    expected_count = 1 if failure == "partial_then_raise" else 0
    assert first.registered_count == expected_count
    snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
    assert snapshot["requests"][0]["registered_count"] == expected_count
    assert snapshot["save_state"] == "not_attempted"


def test_next_request_waits_for_exact_prior_candidate_settlement(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api, image_count=1)
    try:
        first = case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"])
        assert first.registration_state == "registered"
        assert case["adapter"]._index == 0 and len(case["sent"]) == 1

        case["adapter"].advance_for_characterization()
        assert case["adapter"]._index == 1 and len(case["sent"]) == 2
        promoter, receipt, _freshness = protected_promotion_for_active_request(
            case["values"], case["adapter"], case["protected"])
        assert case["adapter"].accept_protected_promotion_for_characterization(
            promoter, receipt).status == "protected_outputs_ready"
        remote = receipt._accepted._remote
        admitted = case["admission"].admit_for_characterization(promoter, receipt, remote, 1)
        assert admitted.status == "evidence_observed"
        second = case["publisher"].publish_protected_for_characterization(
            case["admission"], admitted.observation)
        assert second.registration_state == "registered"
        assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)[
            "requests"][1]["registered_count"] == 1
    finally:
        case["runtime"].close()
        case["promoter"].close()
        case["promotion_receipt"]._acceptance_owner.close()
        case["protected"].close()


def test_candidate_path_uses_existing_relative_persistence_rule(scenario, tmp_path):
    path = str(scenario["promotion_receipt"].images[0].promoted_image.storage_identity)
    actual = scenario["protected"]._files[("promoted_assets", path)][0]
    inside_project = str(scenario["scope"] / "project.json")
    relative = make_project_relative_path(str(actual), inside_project)
    assert not os.path.isabs(relative)
    assert resolve_project_asset_path(relative, inside_project) == str(actual)
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    outside_project = str(outside_dir / "another-project.json")
    assert make_project_relative_path(str(actual), outside_project) == str(actual)
