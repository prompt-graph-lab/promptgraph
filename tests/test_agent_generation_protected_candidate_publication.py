"""C2B-8D-11 protected Candidate integration; disposable Windows evidence only."""
import copy
import io
import json
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from PIL import Image
import pytest

from core import generation_windows_protected_assets as assets
from core import generation_windows_protected_storage as storage
from core.io import load_project_from_json, make_project_relative_path, resolve_project_asset_path
from ui.agent_generation_candidate_publication import GenerationCandidatePublication
from ui.agent_generation_executor_inbox import GenerationExecutorInbox, MAX_LATE_RECEIPTS
from ui.agent_generation_job import GenerationJobRegistry, MAX_EVENT_HISTORY
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


def _scenario(scope, api, *, approved_child=False, image_count=2, request_count=2):
    approved = scope
    if approved_child:
        approved = scope / "approved-output-child"
        api[2].CreateDirectory(str(approved), storage._security_attributes(api, storage._current_user(api)))

    base_provider = host_for()

    def provider(project, runs):
        host = base_provider(project, runs)
        host["generation_options"]["output_directory"] = str(approved)
        return host

    # The existing app save callback must receive a disposable exact path.
    import test_agent_generation_executable_review_ui as review_ui
    original_setup = review_ui.setup
    def setup_disposable_path():
        runtime, route, _epoch, state, args = original_setup()
        project_path = str(scope.parent / "protected-generation-project.json")
        state["current_project_path"] = project_path
        epoch = runtime.synchronize_target(state["project"], project_path)
        return runtime, route, epoch, state, args
    with patch.object(review_ui, "setup", setup_disposable_path):
        runtime, route, _epoch, state, _args, provider = queued(
            count=request_count, runs=1, provider=provider, with_swap=True)
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
        save_project=owners["save_agent_scene_module_swap_project"],
        characterization=True)
    return {
        "scope": scope, "approved": approved, "api": api, "runtime": runtime,
        "state": state, "values": values, "adapter": adapter, "sent": sent,
        "accepted": accepted, "protected": protected, "promoter": promoter,
        "promotion_receipt": promotion_receipt, "remote": promotion_receipt._accepted._remote,
        "freshness": freshness, "admission": admission, "admission_result": admission_result,
        "observation": admission_result.observation, "publisher": publisher,
        "promoters": [promoter], "promotion_receipts": [promotion_receipt],
    }


@pytest.fixture
def scenario(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api)
    yield case
    case["runtime"].close()
    for promoter in reversed(case["promoters"]):
        promoter.close()
    for receipt in reversed(case["promotion_receipts"]):
        receipt._acceptance_owner.close()
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
    assert case["publisher"].save_for_characterization() == "registration_incomplete"
    assert case["runtime"].generation_jobs.execution_available is False


def _register_all_protected_requests(case, *, progress_events_per_request=0):
    """Settle every request through the existing protected Candidate writer."""
    results = [case["publisher"].publish_protected_for_characterization(
        case["admission"], case["observation"])]
    assert results[0].registration_state == "registered"
    for index in range(1, len(case["adapter"]._envelope.manifest.requests)):
        adapter = case["adapter"]
        original_provider = adapter._result_provider
        if progress_events_per_request:
            def provider(prepared, prompt):
                for _ in range(progress_events_per_request):
                    assert adapter._emit("execution_progress") == "accepted"
                return original_provider(prepared, prompt)
            adapter._result_provider = provider
        try:
            adapter.advance_for_characterization()
        finally:
            adapter._result_provider = original_provider
        promoter, receipt, _freshness = protected_promotion_for_active_request(
            case["values"], case["adapter"], case["protected"])
        case["promoters"].append(promoter)
        case["promotion_receipts"].append(receipt)
        assert case["adapter"].accept_protected_promotion_for_characterization(
            promoter, receipt).status == "protected_outputs_ready"
        remote = receipt._accepted._remote
        admitted = case["admission"].admit_for_characterization(
            promoter, receipt, remote, index)
        assert admitted.status == "evidence_observed"
        result = case["publisher"].publish_protected_for_characterization(
            case["admission"], admitted.observation)
        assert result.registration_state == "registered"
        results.append(result)
    return tuple(results)


def _change_original_host_authority(case, change):
    state, runtime = case["state"], case["runtime"]
    if change == "project":
        state["project"] = copy.deepcopy(state["project"])
    elif change == "activation":
        original = state["project"]
        state["project"] = copy.deepcopy(original)
        runtime.synchronize_target(state["project"], state["current_project_path"])
        state["project"] = original
        runtime.synchronize_target(original, state["current_project_path"])
    elif change == "pairing":
        case["values"][1].release()
        bootstrap = runtime.arm_local_pairing().bootstrap
        assert runtime._registry.claim_pairing(
            bootstrap.process_incarnation, bootstrap.route_id, bootstrap.capability).status == "paired"


@pytest.mark.parametrize(("request_count", "image_count", "progress_events"),
                         [(1, 1, 0), (2, 2, 0), (8, 1, 8)])
def test_protected_candidate_json_save_reopens_exact_registered_provenance(
        protected_scope, request_count, image_count, progress_events):
    scope, api = protected_scope
    case = _scenario(scope, api, image_count=image_count, request_count=request_count)
    try:
        results = _register_all_protected_requests(
            case, progress_events_per_request=progress_events)
        assert all(result.registration_state == "registered" for result in results)
        if progress_events:
            job = case["runtime"].generation_jobs._jobs[case["accepted"].job_id]
            inbox = case["runtime"]._generation_executor_inbox
            first = case["observation"]
            first_sequences = (first._remote_event.progress.sequence,
                               first._outputs_ready_event.progress.sequence)
            assert job.event_count > MAX_EVENT_HISTORY
            assert all(sequence not in inbox._events and sequence not in job.events
                       for sequence in first_sequences)
        source, path = case["state"]["project"], case["state"]["current_project_path"]
        assert case["publisher"].save_for_characterization() == "saved"
        assert Path(path).is_file()
        snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
        assert snapshot["save_state"] == "saved"
        assert case["publisher"].save_for_characterization() == "saved"
        assert case["state"]["project"] is source

        reopened = load_project_from_json(path)
        reviewed_requests = json.loads(case["publisher"]._origin.review_json)["requests"]
        for index in range(request_count):
            request = case["adapter"]._envelope.manifest.requests[index]
            line = next(row for row in reopened.prompt_lines if row.id == request.illustration_id)
            records = [row for row in line.generated_candidates
                       if row.get("generation_provenance", {}).get("job_id") == case["accepted"].job_id
                       and row.get("generation_provenance", {}).get("request_index") == index]
            receipt = case["promotion_receipts"][index]
            assert len(records) == image_count
            assert tuple(row["generation_provenance"]["descriptor_identity"] for row in records) == tuple(
                image.descriptor_identity for image in receipt.images)
            assert tuple(row["generation_provenance"]["content_sha256"] for row in records) == tuple(
                image.promoted_image.content_sha256 for image in receipt.images)
            assert all(resolve_project_asset_path(row["path"], path) == receipt_path
                       for row, receipt_path in zip(records,
                           case["publisher"]._protected_candidate_paths(
                               case["publisher"]._protected_evidence[index][1])))
            review_row = reviewed_requests[index]
            expected_seed_rows = review_row["seeds"]
            expected_seeds = [row["value"] for row in expected_seed_rows
                              if row["input_key"] == "seed"]
            expected_seed = expected_seeds[0] if len(expected_seeds) == 1 else None
            assert all(row["generation_provenance"]["prompts"] == review_row["prompts"]
                       for row in records)
            assert all(row["generation_provenance"]["seeds"] == expected_seed_rows
                       for row in records)
            assert all(row["seed"] == expected_seed for row in records)
        first_request = case["adapter"]._envelope.manifest.requests[0]
        first_line = next(row for row in reopened.prompt_lines if row.id == first_request.illustration_id)
        first_candidate = next(row for row in first_line.generated_candidates
                               if row.get("generation_provenance", {}).get("job_id")
                                  == case["accepted"].job_id
                               and row.get("generation_provenance", {}).get("request_index") == 0)
        assert first_candidate["seed"] == 0
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


@pytest.mark.parametrize("evidence_gap", ["missing_settled_pair", "tampered_settled_pair"])
def test_protected_save_refuses_missing_or_tampered_settled_event_evidence(
        protected_scope, evidence_gap):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        assert case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"]).registration_state == "registered"
        proofs = case["publisher"]._protected_settled_event_evidence
        if evidence_gap == "missing_settled_pair":
            proofs.pop(0)
            expected = "registration_evidence_missing"
        else:
            from ui.agent_generation_executor_inbox import OutputReceipt
            proof = proofs[0]
            changed_output = replace(
                proof.outputs_ready_event,
                outputs=OutputReceipt("0" * 32, proof.outputs_ready_event.outputs.output_count))
            proofs[0] = replace(proof, outputs_ready_event=changed_output)
            expected = "save_not_authorized"
        calls = []
        case["publisher"]._save = lambda *args: calls.append(args) or True
        assert case["publisher"].save_for_characterization() == expected
        assert calls == []
        assert Path(case["state"]["current_project_path"]).exists() is False
        assert case["publisher"]._protected_evidence[0][1] is case["observation"]
        assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)[
            "save_state"] == "not_attempted"
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


def test_protected_save_remembers_late_output_after_bounded_log_eviction(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        assert case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"]).registration_state == "registered"
        inbox = case["runtime"]._generation_executor_inbox
        late_source = case["observation"]._outputs_ready_event
        for offset in range(MAX_LATE_RECEIPTS + 3):
            late_event = replace(
                late_source,
                progress=replace(late_source.progress, sequence=100 + offset))
            assert inbox.event_for_characterization(
                case["runtime"].generation_jobs, late_event, target_current=True) == "late_event"
        assert len(inbox._late) == MAX_LATE_RECEIPTS
        assert inbox._late_output_seen is True
        calls = []
        case["publisher"]._save = lambda *args: calls.append(args) or True
        assert case["publisher"].save_for_characterization() == "save_not_authorized"
        assert calls == []
        assert Path(case["state"]["current_project_path"]).exists() is False
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


@pytest.mark.parametrize("evidence_gap", ["missing_publication", "registry_count", "unsettled"])
def test_protected_save_refuses_missing_counts_or_unsettled_requests(protected_scope, evidence_gap):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        if evidence_gap != "unsettled":
            result = case["publisher"].publish_protected_for_characterization(
                case["admission"], case["observation"])
            assert result.registration_state == "registered"
        calls = []
        case["publisher"]._save = lambda *args: calls.append(args) or True
        if evidence_gap == "missing_publication":
            case["publisher"]._protected_evidence.clear()
            expected = "registration_evidence_missing"
        elif evidence_gap == "registry_count":
            job = case["runtime"].generation_jobs._jobs[case["accepted"].job_id]
            job.registered[0] = 0
            expected = "registration_incomplete"
        else:
            expected = "registration_incomplete"
        assert case["publisher"].save_for_characterization() == expected
        assert calls == [] and not Path(case["state"]["current_project_path"]).exists()
        assert case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)[
            "save_state"] == "not_attempted"
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


@pytest.mark.parametrize("drift", [
    "content", "acl", "project", "project_path", "source", "activation", "pairing",
    "candidate_provenance",
])
def test_protected_save_revalidates_assets_and_candidate_binding(protected_scope, drift):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        assert case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"]).registration_state == "registered"
        image = case["promotion_receipt"].images[0].promoted_image
        path = case["protected"]._files[(image.purpose, image.storage_identity)][0]
        if drift == "content":
            path.write_bytes(b"tampered after Candidate registration")
        elif drift == "acl":
            from test_generation_windows_protected_storage import mutate_disposable_acl
            mutate_disposable_acl(path, case["api"], "writable_principal")
        elif drift == "project_path":
            case["state"]["current_project_path"] += ".save-as"
        elif drift == "source":
            case["state"]["project"].prompt_lines[-1].current_text += " unrelated drift"
        elif drift in {"project", "activation", "pairing"}:
            _change_original_host_authority(case, drift)
        else:
            candidate = case["state"]["project"].prompt_lines[-1].generated_candidates[0]
            candidate["generation_provenance"]["content_sha256"] = "0" * 64
        calls = []
        case["publisher"]._save = lambda *args: calls.append(args) or True
        assert case["publisher"].save_for_characterization() == "save_not_authorized"
        assert case["publisher"].save_for_characterization() == "save_not_authorized"
        assert calls == []
        assert Path(case["state"]["current_project_path"]).exists() is False
        assert case["publisher"]._protected_evidence[0][1] is case["observation"]
        assert image.storage_identity == path.name and path.exists()
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


def test_protected_owner_closed_before_json_save_retains_evidence(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        assert case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"]).registration_state == "registered"
        case["promoter"].close()
        calls = []
        case["publisher"]._save = lambda *args: calls.append(args) or True
        assert case["publisher"].save_for_characterization() == "save_not_authorized"
        assert calls == []
        assert all(path.exists() for path, *_rest in case["protected"]._files.values())
    finally:
        case["runtime"].close()
        case["promoter"].close()
        case["promotion_receipt"]._acceptance_owner.close()
        case["protected"].close()


@pytest.mark.parametrize("callback_outcome", ["false", "raise_after_write"])
def test_protected_json_save_callback_outcomes_are_one_shot(protected_scope, callback_outcome):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        _register_all_protected_requests(case)
        original = case["publisher"]._save
        calls = []
        def save(*args):
            calls.append(args)
            if callback_outcome == "false":
                return False
            original(*args)
            raise OSError("simulated reply loss after JSON replacement")
        case["publisher"]._save = save
        expected = "save_failed" if callback_outcome == "false" else "save_uncertain"
        assert case["publisher"].save_for_characterization() == expected
        assert case["publisher"].save_for_characterization() == expected
        assert len(calls) == 1
        assert Path(case["state"]["current_project_path"]).exists() is (
            callback_outcome == "raise_after_write")
        snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
        assert snapshot["save_state"] == expected
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


def test_concurrent_protected_save_is_single_callback_and_runs_without_owner_locks(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        _register_all_protected_requests(case)
        runtime = case["runtime"]
        route = runtime._registry._record_for_registration(runtime._registration)
        owners = [runtime._publication_gate, route.operation_lock, runtime.generation_jobs._lock,
                  runtime._generation_executor_inbox._lock, runtime.mailbox._lock,
                  case["admission"]._lock, case["promoter"]._lock,
                  case["promotion_receipt"]._acceptance_owner._lock, case["protected"]._lock]
        original = case["publisher"]._save
        entered, release, calls = Event(), Event(), []
        def save(*args):
            assert all(not (lock._is_owned() if hasattr(lock, "_is_owned") else lock.locked())
                       for lock in owners)
            calls.append(args)
            entered.set()
            assert release.wait(10)
            return original(*args)
        case["publisher"]._save = save
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(case["publisher"].save_for_characterization)
            assert entered.wait(10)
            assert pool.submit(case["publisher"].save_for_characterization).result(10) == "saving"
            release.set()
            assert first.result(15) == "saved"
        assert len(calls) == 1
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


@pytest.mark.parametrize("terminal", [
    "promotion_close", "acceptance_close", "acceptance_invalidate", "protected_close",
    "admission_close", "runtime_close", "activation_drift", "pairing_drift",
])
def test_protected_owner_or_host_loss_during_json_save_is_uncertain(protected_scope, terminal):
    scope, api = protected_scope
    case = _scenario(scope, api, request_count=1, image_count=1)
    try:
        _register_all_protected_requests(case)
        original = case["publisher"]._save
        entered, release, terminal_started, terminal_ready, terminal_done = (
            Event(), Event(), Event(), Event(), Event())
        calls = []
        def save(*args):
            calls.append(args)
            entered.set()
            assert release.wait(10)
            return original(*args)
        case["publisher"]._save = save
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(case["publisher"].save_for_characterization)
            assert entered.wait(10)
            def terminal_action():
                terminal_started.set()
                if terminal == "activation_drift":
                    _change_original_host_authority(case, "activation")
                    terminal_ready.set()
                    terminal_done.set()
                    return
                if terminal == "pairing_drift":
                    _change_original_host_authority(case, "pairing")
                    terminal_ready.set()
                    terminal_done.set()
                    return
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
                terminal_ready.set()
                terminal_done.set()
            closer = pool.submit(terminal_action)
            assert terminal_started.wait(10)
            if terminal.endswith("_drift"):
                assert terminal_ready.wait(10)
            release.set()
            assert first.result(15) == "save_uncertain"
            closer.result(15)
        assert terminal_done.is_set() and len(calls) == 1
        assert case["publisher"].save_for_characterization() == "save_uncertain"
        assert case["publisher"]._save_callback_outcome == "saved"
        assert Path(case["state"]["current_project_path"]).is_file()
    finally:
        case["runtime"].close()
        for promoter in reversed(case["promoters"]):
            promoter.close()
        for receipt in reversed(case["promotion_receipts"]):
            receipt._acceptance_owner.close()
        case["protected"].close()


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


def test_partial_candidate_append_allows_next_distinct_request_without_resolving_uncertainty(protected_scope):
    scope, api = protected_scope
    case = _scenario(scope, api, image_count=2)
    next_promoter = next_receipt = None
    try:
        original_appender = case["publisher"]._appender
        calls = []

        def append_one_then_raise(line, records):
            calls.append(tuple(records))
            original_appender(line, records[:1])
            raise RuntimeError("injected partial Candidate append")

        case["publisher"]._appender = append_one_then_raise
        first = case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"])
        assert first.registration_state == "registration_uncertain"
        assert first.registered_count == 1
        assert case["publisher"].publish_protected_for_characterization(
            case["admission"], case["observation"]) == first
        assert len(calls) == 1 and len(calls[0]) == 2
        first_snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
        assert first_snapshot["requests"][0]["state"] == "partially_failed"
        assert first_snapshot["requests"][0]["registered_count"] == 1
        assert len(case["state"]["project"].prompt_lines[1].generated_candidates) == 1
        assert (case["state"]["project"] == case["publisher"]._expected
                == case["admission"]._candidate_expected)
        assert case["admission"]._origin.source_snapshot == case["admission"]._source_snapshot

        case["publisher"]._appender = original_appender
        case["adapter"].advance_for_characterization()
        assert case["adapter"]._index == 1 and len(case["sent"]) == 2
        next_promoter, next_receipt, _freshness = protected_promotion_for_active_request(
            case["values"], case["adapter"], case["protected"])
        assert case["adapter"].accept_protected_promotion_for_characterization(
            next_promoter, next_receipt).status == "protected_outputs_ready"
        next_remote = next_receipt._accepted._remote
        admitted = case["admission"].admit_for_characterization(
            next_promoter, next_receipt, next_remote, 1)
        assert admitted.status == "evidence_observed"
        second = case["publisher"].publish_protected_for_characterization(
            case["admission"], admitted.observation)
        assert second.registration_state == "registered" and second.registered_count == 2

        snapshot = case["runtime"].generation_jobs.snapshot(case["accepted"].job_id)
        assert snapshot["state"] == "partially_failed"
        assert snapshot["requests"][0]["state"] == "partially_failed"
        assert snapshot["requests"][0]["registered_count"] == 1
        assert snapshot["requests"][1]["state"] == "completed"
        assert snapshot["requests"][1]["registered_count"] == 2
        assert snapshot["save_state"] == "not_attempted"
        assert case["publisher"].save_for_characterization() == "registration_uncertain"
        assert len(case["state"]["history"]) == 2
    finally:
        case["runtime"].close()
        if next_promoter is not None:
            next_promoter.close()
        if next_receipt is not None:
            next_receipt._acceptance_owner.close()
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
