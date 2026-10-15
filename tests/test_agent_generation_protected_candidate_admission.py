"""C2B-8D-10 admission observations; disposable native protected files only."""
import copy
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
import io
import threading

import pytest
from PIL import Image

from core import generation_windows_protected_assets as assets
from core import generation_windows_protected_promotion as promotion
from core import generation_windows_protected_storage as storage
from test_agent_generation_comfy_executor import (
    harness, protected_promotion_for_active_request, result, successful_history,
)
from test_agent_generation_executor_handoff import ready, start
from test_generation_windows_protected_storage import mutate_disposable_acl, native_scope
from ui.agent_generation_protected_candidate_admission import GenerationProtectedCandidateAdmission


@pytest.fixture
def protected_assets_owner(native_scope):
    scope, _ = native_scope
    with assets.WindowsProtectedAssetsCharacterization.provision_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True) as owner:
        yield owner, scope, storage._api()


@pytest.fixture
def scenario(protected_assets_owner):
    protected, scope, api = protected_assets_owner
    case = build_scenario(protected, api, 1)
    case["scope"] = scope
    yield case
    case["runtime"].close()


def build_scenario(protected, api, image_count):
    values = ready()
    values, adapter, sent = harness(values, provider=lambda prepared, prompt: result(
        prepared, prompt, history_json=successful_history(prompt, image_count)))
    accepted = start(values, adapter.accept_and_run_for_characterization)
    promoter, receipt, freshness = protected_promotion_for_active_request(values, adapter, protected)
    emitted = adapter.accept_protected_promotion_for_characterization(promoter, receipt)
    assert emitted.status == "protected_outputs_ready"
    runtime, _, state, *_ = values
    admission = GenerationProtectedCandidateAdmission.create_for_characterization(
        state, runtime, adapter._envelope, characterization=True, disposable_opt_in=True)
    return {
        "protected": protected, "api": api, "values": values, "runtime": runtime,
        "state": state, "adapter": adapter, "sent": sent, "accepted": accepted,
        "promoter": promoter, "receipt": receipt, "remote": receipt._accepted._remote,
        "freshness": freshness, "admission": admission,
    }


def test_exact_protected_promotion_and_accepted_host_event_issue_observation(scenario):
    case = scenario
    runtime, state = case["runtime"], case["state"]
    project_before = copy.deepcopy(state["project"])
    state_before = copy.deepcopy(state)

    result = case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0)

    assert result.status == "evidence_observed" and result.request_index == 0
    observation = result.observation
    assert observation._runtime is runtime
    assert observation._project is runtime._generation_publication_origin.project
    assert observation._origin is runtime._generation_publication_origin
    assert observation._promotion_owner is case["promoter"]
    assert observation._promotion_receipt is case["receipt"]
    assert observation._remote_receipt is case["remote"]
    assert observation._outputs_ready_event.outputs.receipt_id == case["receipt"].identity[:32]
    assert observation._outputs_ready_event.progress.kind == "outputs_ready"
    assert observation._remote_event.progress.kind == "remote_outputs_ready"
    with pytest.raises(FrozenInstanceError):
        observation.identity = "changed"

    duplicate = case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0)
    assert duplicate.status == "duplicate_observed" and duplicate.observation is observation
    assert state["project"] == project_before
    assert state == state_before
    job = runtime.generation_jobs.snapshot(case["accepted"].job_id)
    assert job["requests"][0]["state"] == "awaiting_host_registration"
    assert job["requests"][0]["registered_count"] == 0
    assert job["save_state"] == "not_attempted"
    assert runtime._generation_candidate_publication is None
    assert runtime.generation_jobs.execution_available is False
    assert case["admission"].candidate_publication_allowed is False
    assert case["admission"].project_save_allowed is False
    assert case["admission"].authorship == "unverified"


def test_complete_multi_image_descriptor_order_is_bound_to_admission(scenario):
    scope = scenario["scope"].parent / "multi-image-owner-only-scope"
    api = scenario["api"]
    api[2].CreateDirectory(str(scope), storage._security_attributes(api, storage._current_user(api)))
    with assets.WindowsProtectedAssetsCharacterization.provision_for_characterization(
            str(scope), characterization=True, disposable_opt_in=True) as protected:
        case = build_scenario(protected, scenario["api"], 2)
        try:
            result = case["admission"].admit_for_characterization(
                case["promoter"], case["receipt"], case["remote"], 0)
            assert result.status == "evidence_observed"
            assert tuple(row.descriptor_identity for row in case["receipt"].images) == tuple(
                descriptor.identity for descriptor in case["remote"].images)
            assert result.observation._outputs_ready_event.outputs.output_count == 2
            assert tuple(row.promoted_image.content_sha256 for row in case["receipt"].images) == tuple(
                row.promoted_image.content_sha256 for row in result.observation._promotion_receipt.images)
            assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)[
                "requests"][0]["registered_count"] == 0
        finally:
            case["runtime"].close()


@pytest.mark.parametrize("substitution", [
    "copy", "identity", "malformed_acceptance", "cross_owner", "wrong_remote", "wrong_index",
])
def test_copied_substituted_or_cross_owner_evidence_does_not_admit(scenario, substitution):
    case = scenario
    receipt, promoter, remote, index = case["receipt"], case["promoter"], case["remote"], 0
    if substitution == "copy":
        receipt = replace(receipt)
    elif substitution == "identity":
        receipt = replace(receipt, identity="0" * 64)
    elif substitution == "malformed_acceptance":
        receipt = replace(receipt, _accepted=object())
    elif substitution == "cross_owner":
        promoter = promotion.ProtectedDurablePromotionCharacterization.create_for_characterization(
            case["protected"], receipt._acceptance_owner, receipt._accepted,
            characterization=True, disposable_opt_in=True)
    elif substitution == "wrong_remote":
        remote = replace(remote)
    else:
        index = 1

    result = case["admission"].admit_for_characterization(promoter, receipt, remote, index)

    assert result.status == "receipt_mismatch"
    assert case["admission"].readiness()["attempt_count"] == 0
    assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)["registered_count"] == 0


@pytest.mark.parametrize("corruption", [
    "missing_output", "missing_remote", "duplicate_output", "duplicate_remote",
    "conflicting_output", "stale_output_sequence",
])
def test_missing_duplicate_or_conflicting_event_evidence_is_retained_as_uncertain(scenario, corruption):
    case = scenario
    inbox = case["runtime"]._generation_executor_inbox
    output_sequence, output_event = next((sequence, event) for sequence, event in inbox._events.items()
        if event.progress.kind == "outputs_ready")
    remote_sequence, remote_event = next((sequence, event) for sequence, event in inbox._events.items()
        if event.progress.kind == "remote_outputs_ready")
    if corruption == "missing_output":
        del inbox._events[output_sequence]
    elif corruption == "missing_remote":
        del inbox._events[remote_sequence]
    elif corruption == "duplicate_output":
        inbox._events[output_sequence + 1] = replace(output_event,
            progress=replace(output_event.progress, sequence=output_sequence + 1))
    elif corruption == "duplicate_remote":
        sequence = max(inbox._events) + 1
        inbox._events[sequence] = replace(remote_event,
            progress=replace(remote_event.progress, sequence=sequence))
    elif corruption == "stale_output_sequence":
        inbox._events[output_sequence] = replace(output_event,
            progress=replace(output_event.progress, sequence=output_sequence - 1))
    else:
        inbox._events[output_sequence] = replace(output_event,
            outputs=replace(output_event.outputs, receipt_id="f" * 32))

    result = case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0)

    assert result.status == "host_or_event_unavailable"
    assert case["admission"]._attempts[0].status == "uncertain"
    assert case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0).status == "duplicate_uncertain"
    assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)["registered_count"] == 0


@pytest.mark.parametrize("drift", ["project", "path", "source", "pairing", "activation"])
def test_original_host_project_path_source_and_pairing_drift_block_admission(scenario, drift):
    case = scenario
    state, runtime = case["state"], case["runtime"]
    if drift == "project":
        state["project"] = copy.deepcopy(state["project"])
    elif drift == "path":
        state["current_project_path"] += ".save-as"
    elif drift == "source":
        state["project"].prompt_lines[-1].current_text += " changed"
    elif drift == "activation":
        original_project = state["project"]
        state["project"] = copy.deepcopy(original_project)
        runtime.synchronize_target(state["project"], state["current_project_path"])
        state["project"] = original_project
        runtime.synchronize_target(state["project"], state["current_project_path"])
    else:
        case["values"][1].release()
        bootstrap = runtime.arm_local_pairing().bootstrap
        assert runtime._registry.claim_pairing(
            bootstrap.process_incarnation, bootstrap.route_id, bootstrap.capability).status == "paired"

    result = case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0)

    assert result.status == "host_or_event_unavailable"
    assert case["admission"]._attempts[0].status == "uncertain"
    assert runtime.generation_jobs.snapshot(case["accepted"].job_id)["registered_count"] == 0


@pytest.mark.parametrize("drift", ["content", "acl", "freshness"])
def test_native_promotion_or_original_host_freshness_drift_blocks_admission(scenario, drift):
    case = scenario
    image = case["receipt"].images[0].promoted_image
    path = case["protected"]._files[(image.purpose, image.storage_identity)][0]
    original = path.read_bytes()
    if drift == "content":
        changed = io.BytesIO()
        Image.new("RGB", (41, 42), "black").save(changed, format="PNG")
        path.write_bytes(changed.getvalue())
    elif drift == "acl":
        mutate_disposable_acl(path, case["api"], "writable_principal")
    else:
        case["admission"]._host_freshness_for_admission = lambda *_: False

    result = case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0)

    assert result.status == "promotion_uncertain"
    assert case["admission"]._attempts[0].status == "uncertain"
    assert path.exists()
    if drift == "content":
        assert path.read_bytes() != original
    assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)["registered_count"] == 0


@pytest.mark.parametrize("revocation", ["promotion_close", "acceptance_close", "acceptance_invalidate", "protected_close", "runtime_close"])
def test_owner_or_session_revocation_before_admission_is_fail_closed(scenario, revocation):
    case = scenario
    if revocation == "promotion_close":
        case["promoter"].close()
    elif revocation == "acceptance_close":
        case["receipt"]._acceptance_owner.close()
    elif revocation == "acceptance_invalidate":
        case["receipt"]._acceptance_owner.invalidate_for_characterization()
    elif revocation == "protected_close":
        case["protected"].close()
    else:
        case["runtime"].close()

    result = case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0)

    assert result.status == ("unavailable" if revocation == "runtime_close" else "host_or_event_unavailable")
    snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
    if revocation == "runtime_close":
        assert snapshot["state"] == "unavailable"
    else:
        assert snapshot["registered_count"] == 0


@pytest.mark.parametrize("revocation", ["promotion_close", "acceptance_invalidate", "protected_close", "admission_close", "runtime_close"])
def test_revocation_during_unlocked_native_verification_prevents_issue(scenario, revocation):
    case = scenario
    entered, resume = threading.Event(), threading.Event()
    original = case["promoter"]._inspect_for_candidate_admission_for_characterization

    def pause(supplied, host_freshness):
        entered.set()
        assert resume.wait(5)
        return original(supplied, host_freshness)

    case["promoter"]._inspect_for_candidate_admission_for_characterization = pause
    results = []
    thread = threading.Thread(target=lambda: results.append(case["admission"].admit_for_characterization(
        case["promoter"], case["receipt"], case["remote"], 0)))
    thread.start()
    assert entered.wait(5)
    if revocation == "promotion_close":
        case["promoter"].close()
    elif revocation == "acceptance_invalidate":
        case["receipt"]._acceptance_owner.invalidate_for_characterization()
    elif revocation == "protected_close":
        case["protected"].close()
    elif revocation == "admission_close":
        case["admission"].close()
    else:
        case["runtime"].close()
    resume.set()
    thread.join(10)

    assert not thread.is_alive()
    assert len(results) == 1 and results[0].status != "evidence_observed"
    assert results[0].observation is None
    snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
    if revocation == "runtime_close":
        assert snapshot["state"] == "unavailable"
    else:
        assert snapshot["registered_count"] == 0


def test_promotion_close_waits_for_final_admission_commit(scenario):
    case = scenario
    entered, resume, close_started, close_done, inspection_complete = (
        threading.Event(), threading.Event(), threading.Event(), threading.Event(), threading.Event())
    original_evidence = case["admission"]._host_evidence
    original_inspect = case["promoter"]._inspect_for_candidate_admission_for_characterization

    @contextmanager
    def paused_evidence(promotion_owner, receipt, remote, index):
        with original_evidence(promotion_owner, receipt, remote, index) as evidence:
            if inspection_complete.is_set():
                entered.set()
                assert resume.wait(5)
            yield evidence

    def signal_inspection_complete(receipt, host_freshness):
        result = original_inspect(receipt, host_freshness)
        inspection_complete.set()
        return result

    case["admission"]._host_evidence = paused_evidence
    case["promoter"]._inspect_for_candidate_admission_for_characterization = signal_inspection_complete
    results = []
    admission_thread = threading.Thread(target=lambda: results.append(
        case["admission"].admit_for_characterization(
            case["promoter"], case["receipt"], case["remote"], 0)))
    admission_thread.start()
    assert entered.wait(10)

    def close_promotion():
        close_started.set()
        case["promoter"].close()
        close_done.set()

    close_thread = threading.Thread(target=close_promotion)
    close_thread.start()
    assert close_started.wait(5)
    assert not close_done.is_set()
    resume.set()
    admission_thread.join(10)
    close_thread.join(10)

    assert not admission_thread.is_alive() and not close_thread.is_alive()
    assert len(results) == 1 and results[0].status == "evidence_observed"
    assert close_done.is_set()
    assert case["promoter"].readiness()["promotion"] == "closed"


def test_admission_owner_requires_explicit_characterization_opt_in(scenario):
    case = scenario
    assert GenerationProtectedCandidateAdmission.execution_available is False
    assert GenerationProtectedCandidateAdmission.protected_storage_available is False
    assert GenerationProtectedCandidateAdmission.promotion_available is False
    assert GenerationProtectedCandidateAdmission.candidate_publication_allowed is False
    with pytest.raises(ValueError, match="execution_unavailable"):
        GenerationProtectedCandidateAdmission.create_for_characterization(
            case["state"], case["runtime"], case["adapter"]._envelope)
