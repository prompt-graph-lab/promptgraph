"""C2B-8D-14: Journal intent gates the existing offline executor send."""
import copy
import json
from dataclasses import replace
from pathlib import Path
import sys
import threading
import uuid

import pytest

from core import generation_ownership_journal as journal
from core import generation_protected_journal as protected_journal
from core import generation_windows_protected_storage as protected_storage
from core.comfy_http_submission import SubmissionResult
from ui.agent_generation_comfy_executor import ComfyExecutorAdapter, ExecutionResult
from ui import agent_generation_executor_journal as executor_journal
from ui.agent_generation_executor_handoff import (
    capture_executor_human_start_for_characterization as capture_start,
    deliver_executor_event_for_characterization as deliver,
    handoff_generation_for_characterization as handoff,
)
from ui.agent_generation_executor_inbox import GenerationExecutorInbox
from ui.agent_generation_executor_journal import (
    create_executor_journal_intent_for_characterization,
)
from ui.agent_generation_executable_confirmation import (
    confirm_session_execution_details as confirm,
    prepare_session_executable_review as prepare,
)
from ui.agent_generation_job import GenerationJobRegistry
from test_agent_generation_executable_manifest import host_for
from test_agent_generation_preview import line
from test_agent_generation_review_custody import send, setup


@pytest.fixture
def native_scope(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows native characterization only")
    pytest.importorskip("win32security")
    api = protected_storage._api()
    scope = tmp_path / "executor-journal-scope"
    api[2].CreateDirectory(str(scope), protected_storage._security_attributes(
        api, protected_storage._current_user(api)))
    return scope, api


def ready_generation(tmp_path, illustration_count):
    runtime, route, epoch, state, args = setup()
    runtime.generation_jobs = GenerationJobRegistry(characterization=True)
    runtime._generation_executor_inbox = GenerationExecutorInbox(characterization=True)
    state["project"].prompt_lines = [line("scene", "Scene", line_type="separator")]
    state["project"].prompt_lines.extend(
        line(f"illustration-{index}", "red", negative_prompt="blur")
        for index in range(illustration_count))
    project_directory = tmp_path / "project-root"
    project_directory.mkdir(parents=True)
    project_file = project_directory / "project.json"
    project_file.write_text('{"prompt_lines":[]}', encoding="utf-8")
    state["current_project_path"] = str(project_file)
    epoch = runtime.synchronize_target(state["project"], state["current_project_path"])
    provider = host_for()
    from core import agent_facade
    binding = [agent_facade.candidate_observation_handles.project_identity(state["project"]),
               runtime._registration.route_id, state["current_project_path"], route._pairing_generation, epoch]
    plan = agent_facade.preview_generation(state["project"], "scene", run_count=1,
        host_context_provider=provider, observation_binding=binding)
    assert plan["ok"] and plan["valid"] and plan["request_count"] == illustration_count
    args = {"scene_id": "scene", "run_count": 1, "expected_plan_id": plan["plan_id"]}
    assert send(runtime, route, epoch, state, args, provider=provider) == "completed"
    route.consume_reply(epoch)
    custody = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    assert custody["proposal_id"] and custody["plan_id"] == plan["plan_id"]
    assert prepare(state, runtime, provider, custody["proposal_id"], custody["plan_id"],
                   random_u64=lambda: 0) == "certified"
    held = runtime._executable_review
    assert confirm(state, runtime, provider, held) == "confirmed"
    action = capture_start(runtime)
    return runtime, route, state, provider, held, action, project_directory, project_file


def ready_one_request(tmp_path):
    return ready_generation(tmp_path, 1)


def approved_roots(tmp_path):
    project_root = journal.ApprovedRoot.capture_for_characterization(
        "project", str(tmp_path / "project-root"), characterization=True)
    journal_directory = tmp_path / "journal-root"
    journal_directory.mkdir(exist_ok=True)
    journal_root = journal.ApprovedRoot.capture_for_characterization(
        "journal", str(journal_directory), characterization=True)
    return project_root, journal_root


def context_for(values, tmp_path, *, operation_id="operation", fault=lambda _: None,
                journal_root=None):
    runtime, _, state, *_ = values
    project_root, approved_journal_root = approved_roots(tmp_path)
    owner = journal_root or approved_journal_root
    context = create_executor_journal_intent_for_characterization(
        state, runtime, project_root=project_root, project_relative_path="project.json",
        journal_root=owner, operation_id=operation_id,
        characterization=True, disposable_opt_in=True, journal_fault=fault)
    return context, approved_journal_root


def executor(values, context, *, transport=None, event_sink=None, provider=None):
    runtime, _, state, *_ = values
    sent = []
    def send_request(prepared):
        sent.append(prepared)
        return (transport(prepared) if transport else SubmissionResult(
            "accepted", json.dumps({"prompt_id": str(uuid.uuid4())}).encode()))
    sink = event_sink or (lambda event: deliver(state, runtime, event))
    adapter = ComfyExecutorAdapter(runtime.generation_jobs, runtime._generation_executor_inbox,
        fake_transport=send_request,
        fake_result_provider=provider or (lambda prepared, prompt: ExecutionResult(
            prepared.request_id, prompt, "execution_failed")),
        host_event_sink=sink, characterization=True, journal_intent_owner=context)
    return adapter, sent


def accepted(values, adapter):
    runtime, route, state, provider, held, action, *_ = values
    return handoff(state, runtime, provider, action, fake_worker=adapter.accept_and_run_for_characterization)


def test_acknowledged_exact_intent_precedes_existing_executor_transport(tmp_path):
    values = ready_one_request(tmp_path)
    before_project = copy.deepcopy(values[2])
    events = []
    context, journal_root = context_for(values, tmp_path,
        fault=lambda point: events.append(point))
    def transport(prepared):
        reopened = journal.reopen_journal(journal_root, "operation.json")
        assert reopened.revision == 1
        assert reopened.observations == (journal.Observation("submission_intent", "intent", requests=(
            journal.RequestObservation(prepared.request_id, prepared.request_index,
                                       prepared.workflow_identity, "intent"),)),)
        events.append("transport")
        return SubmissionResult("accepted", json.dumps({"prompt_id": str(uuid.uuid4())}).encode())
    runtime, _, state, *_ = values
    def sink(event):
        result = deliver(state, runtime, event)
        if event.progress.kind == "submission_started":
            events.append("submission_started")
        return result
    adapter, sent = executor(values, context, transport=transport, event_sink=sink)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert len(sent) == 1, (adapter.observation(), context.inspection_for_characterization(), events)
    assert events.index("submission_started") < events.index("before_replace") < events.index("transport")
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 2 and reopened.observations[0].checkpoint == "submission_intent"
    assert reopened.observations[1].checkpoint == "submission_observed"
    assert reopened.observations[1].outcome == "accepted"
    assert reopened.observations[1].requests[0].prompt_id in adapter._prompts
    assert reopened.operation.job_id == adapter._envelope.job_id
    assert reopened.operation.claim_id == adapter._envelope.claim_id
    assert reopened.operation.manifest_identity == adapter._envelope.manifest.manifest_identity
    assert reopened.operation.process_identity == adapter._envelope.binding.process_incarnation
    assert reopened.operation.session_identity == adapter._envelope.binding.session_id
    assert reopened.operation.requests == (journal.FrozenRequestCorrelation(
        sent[0].request_id, 0, "illustration-0", 1,
        sent[0].workflow_identity),)
    assert reopened.trust == "inspect_only" and reopened.authenticity == "unverified"
    diagnostic = context.inspection_for_characterization()
    assert diagnostic["execution_available"] is False
    assert diagnostic["protected_storage_available"] is False
    assert diagnostic["promotion_available"] is False
    assert diagnostic["candidate_publication_allowed"] is False
    assert diagnostic["authorship"] == "unverified"
    assert values[2] == before_project
    values[0].close()


@pytest.mark.parametrize("failure,revision", [("before_replace", 0), ("after_replace_before_ack", 1)])
def test_uncertain_intent_ack_never_invokes_transport_and_reopen_is_inspect_only(
        tmp_path, failure, revision):
    values = ready_one_request(tmp_path)
    def fault(point):
        if point == failure:
            raise RuntimeError("injected journal failure")
    context, journal_root = context_for(values, tmp_path, fault=fault)
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert sent == []
    assert adapter.observation().status == "journal_intent_unacknowledged"
    assert context.inspection_for_characterization()["state"] == "uncertain"
    target = Path(journal_root.path) / "operation.json"
    if revision:
        reopened = journal.reopen_journal(journal_root, target.name)
        assert reopened.revision == 1 and reopened.trust == "inspect_only"
        assert "submission_intent_outcome_unknown" in reopened.uncertainties
    else:
        assert not target.exists()
        inventory = journal.inspect_inventory(journal_root)
        assert any(name.endswith(".tmp") for name, _ in inventory.errors)
    assert adapter.advance_for_characterization().status == "journal_intent_unacknowledged"
    assert sent == []
    values[0].close()


def test_conflicting_preexisting_journal_and_unaccepted_start_event_both_send_nothing(tmp_path):
    values = ready_one_request(tmp_path)
    conflict = Path(tmp_path / "journal-root" / "operation.json")
    conflict.parent.mkdir(exist_ok=True)
    conflict.write_bytes(b"retained conflicting evidence")
    context, journal_root = context_for(values, tmp_path)
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert sent == [] and conflict.read_bytes() == b"retained conflicting evidence"
    assert context.inspection_for_characterization()["state"] == "uncertain"
    values[0].close()
    values = ready_one_request(tmp_path / "second")
    context, _ = context_for(values, tmp_path / "second")
    adapter, sent = executor(values, context, event_sink=lambda event: "unavailable")
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert sent == []
    assert not (tmp_path / "second" / "journal-root" / "operation.json").exists()
    values[0].close()


def test_writer_digest_ack_mismatch_withholds_the_send(tmp_path, monkeypatch):
    values = ready_one_request(tmp_path)
    context, journal_root = context_for(values, tmp_path)
    original = journal.OfflineJournalWriter.append_for_characterization
    def wrong_digest_ack(writer, observation):
        result = original(writer, observation)
        return replace(result, digest="0" * 64)
    monkeypatch.setattr(journal.OfflineJournalWriter, "append_for_characterization", wrong_digest_ack)
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert sent == []
    assert adapter.observation().status == "journal_intent_unacknowledged"
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 1 and reopened.trust == "inspect_only"
    assert reopened.observations[0].checkpoint == "submission_intent"
    assert "submission_intent_outcome_unknown" in reopened.uncertainties
    values[0].close()


def test_source_edit_between_detached_check_and_final_send_gate_prevents_send(tmp_path, monkeypatch):
    values = ready_one_request(tmp_path)
    runtime, _, state, *_ = values
    intent_replaced = threading.Event()
    detached_clone_ready = threading.Event()
    release_clone = threading.Event()
    paused = False

    def fault(point):
        if point == "after_replace_before_ack":
            intent_replaced.set()

    context, journal_root = context_for(values, tmp_path, fault=fault)
    adapter, sent = executor(values, context)
    original_deepcopy = copy.deepcopy

    def pause_final_project_clone(value, memo=None):
        nonlocal paused
        cloned = original_deepcopy(value) if memo is None else original_deepcopy(value, memo)
        origin = runtime._generation_publication_origin
        if (intent_replaced.is_set() and origin is not None and value is origin.project and not paused):
            paused = True
            detached_clone_ready.set()
            assert release_clone.wait(5)
        return cloned

    monkeypatch.setattr(executor_journal.copy, "deepcopy", pause_final_project_clone)
    outcomes, errors = [], []

    def run_handoff():
        try:
            outcomes.append(accepted(values, adapter))
        except BaseException as error:
            errors.append(error)

    worker = threading.Thread(target=run_handoff)
    worker.start()
    assert detached_clone_ready.wait(5), "final detached Project clone was not reached"
    origin = runtime._generation_publication_origin
    assert origin is not None and origin.project == origin.source_snapshot
    host_route = runtime._registry._record_for_registration(runtime._registration)
    assert host_route is not None

    # Model a cooperating host edit through the same serialized mutation
    # gates used by the final send claim. The worker is paused after its
    # detached copy but before acquiring these gates.
    try:
        with runtime._publication_gate:
            with host_route.operation_lock:
                assert state["project"] is origin.project
                state["project"].prompt_lines[1].current_text = "edited after detached check"
    finally:
        release_clone.set()
    worker.join(10)
    assert not worker.is_alive()
    assert errors == []
    assert paused is True
    assert len(outcomes) == 1
    assert outcomes[0].status in {"characterized_acceptance", "handoff_invalidated"}
    assert sent == []
    assert adapter.observation().status in {
        "journal_host_invalidated_before_send", "host_invalidated", "handoff_invalidated"}
    assert context.inspection_for_characterization()["state"] == "no_send"

    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 1
    assert reopened.observations[0].checkpoint == "submission_intent"
    assert reopened.trust == "inspect_only" and reopened.authenticity == "unverified"
    assert adapter.advance_for_characterization().status in {
        "journal_host_invalidated_before_send", "host_invalidated", "handoff_invalidated"}
    assert sent == []
    assert journal.reopen_journal(journal_root, "operation.json").revision == 1
    runtime.close()


@pytest.mark.parametrize("drift", ["project", "path", "activation", "pairing", "session", "process", "session_close"])
def test_host_invalidation_after_intent_ack_prevents_send(tmp_path, drift, monkeypatch):
    case = tmp_path / drift
    case.mkdir()
    values = ready_one_request(case)
    runtime, route, state, *_ = values
    triggered = False
    def fault(point):
        nonlocal triggered
        if point != "after_replace_before_ack" or triggered:
            return
        triggered = True
        if drift == "project":
            state["project"] = copy.deepcopy(state["project"])
        elif drift == "path":
            state["current_project_path"] += ".changed"
        elif drift == "activation":
            runtime.synchronize_target(state["project"], state["current_project_path"] + ".changed")
        elif drift == "pairing":
            runtime._registry.release_pairing(route)
        elif drift == "session":
            runtime.generation_jobs._session_incarnation = uuid.uuid4().hex
        elif drift == "process":
            monkeypatch.setattr(executor_journal, "_PROCESS_INCARNATION", uuid.uuid4().hex)
        else:
            runtime.close()
    context, journal_root = context_for(values, case, fault=fault)
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status in {"characterized_acceptance", "handoff_invalidated"}
    assert sent == []
    assert adapter.observation().status in {"journal_host_invalidated_before_send", "journal_intent_unacknowledged"}
    assert journal.reopen_journal(journal_root, "operation.json").revision == 1
    if drift != "session_close":
        runtime.close()


def test_transport_response_loss_is_unknown_and_reentrant_or_duplicate_advance_cannot_resend(tmp_path):
    values = ready_one_request(tmp_path)
    context, journal_root = context_for(values, tmp_path)
    calls, holder = [], {}
    def transport(prepared):
        calls.append(prepared)
        holder["adapter"].advance_for_characterization()
        raise OSError("response lost")
    adapter, sent = executor(values, context, transport=transport)
    holder["adapter"] = adapter
    assert accepted(values, adapter).status in {"characterized_acceptance", "handoff_invalidated"}
    assert len(sent) == 1 and len(calls) == 1
    assert adapter.observation().status == "submission_outcome_unknown"
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 2 and reopened.observations[-1].outcome == "unknown"
    assert "submission_observed_unknown" in reopened.uncertainties
    assert adapter.advance_for_characterization().status == "submission_outcome_unknown"
    assert len(sent) == 1
    values[0].close()


def test_definite_pre_send_rejection_is_recorded_failed_without_retry(tmp_path):
    values = ready_one_request(tmp_path)
    context, journal_root = context_for(values, tmp_path)
    calls = []
    adapter, sent = executor(values, context,
        transport=lambda prepared: (calls.append(prepared) or SubmissionResult("rejected_before_submission")))
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert len(calls) == 1 and len(sent) == 1
    assert adapter.observation().status == "requests_settled"
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 2 and reopened.observations[-1].outcome == "failed"
    assert reopened.observations[-1].requests[0].outcome == "failed"
    assert adapter.advance_for_characterization().status == "requests_settled"
    assert len(calls) == 1
    values[0].close()


def test_concurrent_advance_waits_for_one_send_and_never_claims_a_second(tmp_path):
    values = ready_one_request(tmp_path)
    context, _ = context_for(values, tmp_path)
    entered, release = threading.Event(), threading.Event()
    def transport(prepared):
        entered.set()
        assert release.wait(5)
        return SubmissionResult("accepted", json.dumps({"prompt_id": str(uuid.uuid4())}).encode())
    adapter, sent = executor(values, context, transport=transport)
    result = []
    worker = threading.Thread(target=lambda: result.append(accepted(values, adapter)))
    worker.start()
    assert entered.wait(5)
    second_started = threading.Event()
    def advance_again():
        second_started.set()
        adapter.advance_for_characterization()
    second = threading.Thread(target=advance_again)
    second.start()
    assert second_started.wait(5)
    release.set()
    worker.join(5)
    second.join(5)
    assert not worker.is_alive() and not second.is_alive()
    assert result[0].status == "characterized_acceptance"
    assert len(sent) == 1
    values[0].close()


def test_close_during_intent_append_keeps_uncertain_intent_without_sending(tmp_path):
    values = ready_one_request(tmp_path)
    holder, closed = {}, threading.Event()
    def fault(point):
        if point == "before_replace":
            thread = threading.Thread(target=lambda: (holder["context"].close(), closed.set()))
            thread.start()
            assert closed.wait(5)
            thread.join(5)
            assert not thread.is_alive()
    context, journal_root = context_for(values, tmp_path, fault=fault)
    holder["context"] = context
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert sent == []
    assert context.inspection_for_characterization()["state"] == "uncertain"
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert (reopened.revision == 1 and reopened.trust == "inspect_only"
            and reopened.authenticity == "unverified" and reopened.execution_available is False)
    values[0].close()


def test_close_after_possible_send_pins_unknown_without_erasing_intent(tmp_path):
    values = ready_one_request(tmp_path)
    context, journal_root = context_for(values, tmp_path)
    def close_during_transport(prepared):
        context.close()
        return SubmissionResult("accepted", json.dumps({"prompt_id": str(uuid.uuid4())}).encode())
    adapter, sent = executor(values, context, transport=close_during_transport)
    assert accepted(values, adapter).status in {"characterized_acceptance", "handoff_invalidated"}
    assert len(sent) == 1
    assert adapter.observation().status == "submission_outcome_unknown"
    diagnostic = context.inspection_for_characterization()
    assert diagnostic["state"] == "uncertain" and diagnostic["closed"] is True
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 1 and reopened.observations[0].checkpoint == "submission_intent"
    assert reopened.trust == "inspect_only" and reopened.authenticity == "unverified"
    values[0].close()


def test_result_ack_failure_after_possible_send_never_retries_or_advances_another_request(tmp_path):
    values = ready_one_request(tmp_path)
    append_count = 0
    def fault(point):
        nonlocal append_count
        if point == "after_replace_before_ack":
            append_count += 1
            if append_count == 2:
                raise RuntimeError("result ack lost")
    context, journal_root = context_for(values, tmp_path, fault=fault)
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status in {"characterized_acceptance", "handoff_invalidated"}
    assert len(sent) == 1
    assert adapter.observation().status == "submission_outcome_unknown"
    job = values[0].generation_jobs.snapshot(adapter._envelope.job_id)
    assert job["requests"][0]["state"] == "submission_outcome_unknown"
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 2 and reopened.observations[-1].outcome == "accepted"
    assert reopened.trust == "inspect_only" and reopened.authenticity == "unverified"
    assert adapter.advance_for_characterization().status == "submission_outcome_unknown"
    assert len(sent) == 1
    values[0].close()


def test_multi_request_manifest_is_refused_by_this_one_request_journal_scope(tmp_path):
    values = ready_generation(tmp_path, 2)
    context, journal_root = context_for(values, tmp_path)
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert sent == []
    assert not (Path(journal_root.path) / "operation.json").exists()
    assert adapter.observation().status == "journal_binding_unavailable"
    assert values[0].generation_jobs.snapshot(adapter._envelope.job_id)["requests"][1]["state"] == "unsent"
    values[0].close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native protected Journal characterization only")
def test_windows_protected_journal_native_acknowledges_before_send(tmp_path, native_scope):
    scope, api = native_scope
    case = tmp_path / "native"
    case.mkdir()
    values = ready_one_request(case)
    root_owner = protected_journal.WindowsProtectedJournalCharacterization.provision_for_characterization(
        str(scope), characterization=True, disposable_opt_in=True)
    context, _ = context_for(values, case, journal_root=root_owner)
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert len(sent) == 1
    reopened = root_owner.reopen_journal_for_characterization("operation.json")
    assert reopened.revision == 2 and reopened.trust == "inspect_only"
    assert root_owner.readiness()["journal_lifecycle"] == "protected_observation"
    for path in root_owner._native._path.iterdir():
        handle = protected_storage._open(path, False, api)
        try:
            assert protected_storage._acl(handle, api, protected_storage._current_user(api))
        finally:
            handle.Close()
    values[0].close()
    root_owner.close()
