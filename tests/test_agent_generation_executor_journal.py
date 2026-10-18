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
from core import generation_multi_request_journal as multi_journal
from core import generation_protected_journal as protected_journal
from core import generation_windows_protected_storage as protected_storage
from core.comfy_http_submission import PromptHTTPPolicy
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
from ui.agent_generation_http_executor import compose_http_executor_for_characterization
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


def ready_generation(tmp_path, illustration_count, *, host_provider=None):
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
    provider = host_provider or host_for()
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


def test_multi_request_journal_settles_pre_send_rejection_and_execution_failure_before_next_send(tmp_path):
    values = ready_generation(tmp_path, 2)
    runtime, *_ = values
    session_record = runtime._registry._record_for_registration(runtime._registration)

    lock_observations = []

    def lock_held(lock):
        is_owned = getattr(lock, "_is_owned", None)
        if callable(is_owned):
            return is_owned()
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()
            return False
        return True

    def host_locks_held():
        return (lock_held(runtime._publication_gate), lock_held(session_record.operation_lock),
                lock_held(runtime.generation_jobs._lock),
                lock_held(runtime._generation_executor_inbox._lock))

    def journal_fault(boundary):
        lock_observations.append(("journal", boundary, host_locks_held()))

    context, approved_journal_root = context_for(
        values, tmp_path, operation_id="multi-failed", fault=journal_fault)
    attempts = []

    def transport(prepared):
        lock_observations.append(("transport", prepared.request_index, host_locks_held()))
        attempts.append(prepared.request_index)
        if prepared.request_index == 0:
            return SubmissionResult("rejected_before_submission")
        return SubmissionResult("accepted", json.dumps({"prompt_id": str(uuid.uuid4())}).encode())

    adapter, sent = executor(values, context, transport=transport,
        provider=lambda prepared, prompt: ExecutionResult(
            prepared.request_id, prompt, "execution_failed"))
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert attempts == [0, 1] and [item.request_index for item in sent] == [0, 1], (
        adapter.observation(), context.inspection_for_characterization())
    assert any(item[0] == "journal" for item in lock_observations)
    assert any(item[0] == "transport" for item in lock_observations)
    assert all(not any(item[2]) for item in lock_observations), lock_observations
    assert adapter.observation().status == "requests_settled"
    diagnostic = context.inspection_for_characterization()
    assert diagnostic["execution_available"] is False
    assert diagnostic["protected_storage_available"] is False
    assert diagnostic["promotion_available"] is False
    assert diagnostic["candidate_publication_allowed"] is False
    assert diagnostic["authorship"] == "unverified"
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-failed.json")
    assert reopened.revision == 6 and reopened.next_request_index == 2
    assert [(type(event), event.request_index) for event in reopened.events] == [
        (multi_journal.SubmissionIntent, 0),
        (multi_journal.SubmissionOutcome, 0),
        (multi_journal.RequestSettlement, 0),
        (multi_journal.SubmissionIntent, 1),
        (multi_journal.SubmissionOutcome, 1),
        (multi_journal.RequestSettlement, 1),
    ]
    assert reopened.events[1].outcome == "pre_send_rejected"
    assert reopened.events[2].disposition == "pre_send_rejected"
    assert reopened.events[4].outcome == "accepted"
    assert reopened.events[5].disposition == "execution_failed"
    assert reopened.events[4].prompt_id == reopened.events[5].prompt_id
    snapshot = values[0].generation_jobs.snapshot(adapter._envelope.job_id)
    assert [item["state"] for item in snapshot["requests"]] == ["failed", "failed"]
    assert len(adapter._prompts) == 1
    assert adapter.advance_for_characterization().status == "requests_settled"
    assert attempts == [0, 1]
    values[0].close()


def test_multi_request_journal_requires_candidate_registration_before_completed_settlement(tmp_path, monkeypatch):
    output = tmp_path / "durable-output"
    output.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    import core.comfy_output_containment as containment
    monkeypatch.setattr(containment.tempfile, "tempdir", str(staging))
    base_provider = host_for()

    def host_provider(project, runs):
        host = base_provider(project, runs)
        host["generation_options"]["output_directory"] = str(output)
        return host

    values = ready_generation(tmp_path, 2, host_provider=host_provider)
    runtime, _, state, *_ = values
    state["history"] = []
    context, approved_journal_root = context_for(values, tmp_path, operation_id="multi-candidate")
    descriptors = [{"filename": "remote.png", "subfolder": "private", "type": "output"}]

    def result_provider(prepared, prompt):
        if prepared.request_index == 0:
            from test_comfy_output_containment import successful_metadata
            return ExecutionResult(prepared.request_id, prompt, "ready",
                                   successful_metadata(prompt, descriptors))
        return ExecutionResult(prepared.request_id, prompt, "execution_failed")

    adapter, sent = executor(values, context, provider=result_provider)
    assert accepted(values, adapter).status == "characterized_acceptance"
    from core.comfy_output_containment import ContainedOutputStore
    from test_comfy_output_containment import image_bytes, stream_provider, contain
    from ui.agent_generation_candidate_publication import GenerationCandidatePublication
    from ui.agent_generation_executor_handoff import local_output_custody_current_for_characterization
    from test_agent_generation_candidate_publication import app_owners

    adapter._local_gate = lambda envelope, remote, local: local_output_custody_current_for_characterization(
        state, runtime, envelope, remote, local)
    store = ContainedOutputStore.create_for_characterization(characterization=True)
    contained = contain(adapter, store, stream_provider(image_bytes()))
    assert contained.status == "local_outputs_ready", (contained, adapter.observation(), sent, adapter.remote_receipts())
    owners = app_owners(state)
    publisher = GenerationCandidatePublication.create_for_characterization(
        state, runtime, adapter._envelope, approved_directory=str(output),
        candidate_factory=owners["_make_generated_candidate_record"],
        candidate_appender=owners["_append_line_generated_candidates"],
        save_project=owners["save_agent_scene_module_swap_project"], characterization=True)
    remote = next(item for item in adapter.remote_receipts() if item.request_index == 0)
    local = next(item for item in adapter.local_receipts() if item.request_index == 0)
    receipt = publisher.publish_for_characterization(store, remote, local)
    assert receipt.registration_state == "registered" and receipt.registered_count == 1
    assert adapter.advance_for_characterization().status == "requests_settled"
    assert len(sent) == 2 and [item.request_index for item in sent] == [0, 1]
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-candidate.json")
    settlements = [event for event in reopened.events if type(event) is multi_journal.RequestSettlement]
    assert [event.disposition for event in settlements] == ["execution_completed", "execution_failed"]
    snapshot = runtime.generation_jobs.snapshot(adapter._envelope.job_id)
    assert snapshot["requests"][0]["registered_count"] == 1
    assert snapshot["requests"][1]["registered_count"] == 0
    assert len(state["project"].prompt_lines[1].generated_candidates) == 1
    assert runtime.generation_jobs.snapshot(adapter._envelope.job_id)["save_state"] == "not_attempted"
    runtime.close()


def test_multi_request_partial_candidate_registration_does_not_settle_or_advance(tmp_path, monkeypatch):
    output = tmp_path / "partial-output"
    output.mkdir()
    staging = tmp_path / "partial-staging"
    staging.mkdir()
    import core.comfy_output_containment as containment
    monkeypatch.setattr(containment.tempfile, "tempdir", str(staging))
    base_provider = host_for()

    def host_provider(project, runs):
        host = base_provider(project, runs)
        host["generation_options"]["output_directory"] = str(output)
        return host

    values = ready_generation(tmp_path, 2, host_provider=host_provider)
    runtime, _, state, *_ = values
    state["history"] = []
    context, approved_journal_root = context_for(values, tmp_path, operation_id="multi-partial")
    descriptors = [
        {"filename": "remote-one.png", "subfolder": "private", "type": "output"},
        {"filename": "remote-two.png", "subfolder": "private", "type": "output"},
    ]

    def result_provider(prepared, prompt):
        if prepared.request_index == 0:
            from test_comfy_output_containment import successful_metadata
            return ExecutionResult(prepared.request_id, prompt, "ready",
                                   successful_metadata(prompt, descriptors))
        return ExecutionResult(prepared.request_id, prompt, "execution_failed")

    adapter, sent = executor(values, context, provider=result_provider)
    assert accepted(values, adapter).status == "characterized_acceptance"
    from core.comfy_output_containment import ContainedOutputStore
    from test_comfy_output_containment import image_bytes, stream_provider, contain
    from ui.agent_generation_candidate_publication import GenerationCandidatePublication
    from ui.agent_generation_executor_handoff import local_output_custody_current_for_characterization
    from test_agent_generation_candidate_publication import app_owners

    adapter._local_gate = lambda envelope, remote, local: local_output_custody_current_for_characterization(
        state, runtime, envelope, remote, local)
    store = ContainedOutputStore.create_for_characterization(characterization=True)
    contained = contain(adapter, store, stream_provider(lambda lookup: image_bytes()))
    assert contained.status == "local_outputs_ready"
    owners = app_owners(state)
    publisher = GenerationCandidatePublication.create_for_characterization(
        state, runtime, adapter._envelope, approved_directory=str(output),
        candidate_factory=owners["_make_generated_candidate_record"],
        candidate_appender=owners["_append_line_generated_candidates"],
        save_project=owners["save_agent_scene_module_swap_project"], characterization=True)
    original_appender = publisher._appender

    def append_one_then_fail(line, records):
        original_appender(line, records[:1])
        raise RuntimeError("partial publication remains uncertain")

    publisher._appender = append_one_then_fail
    remote = next(item for item in adapter.remote_receipts() if item.request_index == 0)
    local = next(item for item in adapter.local_receipts() if item.request_index == 0)
    publication = publisher.publish_for_characterization(store, remote, local)
    assert publication.registration_state == "registration_uncertain"
    assert publication.registered_count == 1
    assert runtime.generation_jobs.snapshot(adapter._envelope.job_id)["requests"][0]["state"] == "partially_failed"
    adapter.advance_for_characterization()
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-partial.json")
    assert reopened.revision == 2 and reopened.next_request_index == 0
    assert not any(type(event) is multi_journal.RequestSettlement for event in reopened.events)
    assert [item.request_index for item in sent] == [0]
    assert len(state["project"].prompt_lines[1].generated_candidates) == 1
    assert runtime.generation_jobs.snapshot(adapter._envelope.job_id)["save_state"] == "not_attempted"
    runtime.close()


def test_multi_request_authority_events_survive_diagnostic_eviction(tmp_path):
    values = ready_generation(tmp_path, 22)
    context, approved_journal_root = context_for(values, tmp_path, operation_id="multi-long")
    adapter, sent = executor(values, context,
        provider=lambda prepared, prompt: ExecutionResult(prepared.request_id, prompt, "execution_failed"))
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert len(sent) == 22
    job = values[0].generation_jobs._jobs[adapter._envelope.job_id]
    inbox = values[0]._generation_executor_inbox
    assert job.event_count == 66 and len(job.events) == 64
    assert len(job.authority_events) == 66 and len(inbox._events) == 64
    assert len(inbox._authority_events) == 66
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-long.json")
    assert reopened.revision == 66 and reopened.next_request_index == 22
    assert sum(type(event) is multi_journal.RequestSettlement for event in reopened.events) == 22
    assert adapter.observation().status == "requests_settled"
    values[0].close()


def test_multi_request_intent_ack_failure_blocks_the_next_transport_call(tmp_path):
    values = ready_generation(tmp_path, 2)
    after_replace = 0

    def fault(boundary):
        nonlocal after_replace
        if boundary == "after_replace_before_ack":
            after_replace += 1
            if after_replace == 4:
                raise RuntimeError("second request intent acknowledgement lost")

    context, approved_journal_root = context_for(
        values, tmp_path, operation_id="multi-intent-ack", fault=fault)
    attempts = []

    def transport(prepared):
        attempts.append(prepared.request_index)
        return SubmissionResult("rejected_before_submission")

    adapter, sent = executor(values, context, transport=transport)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert attempts == [0] and [item.request_index for item in sent] == [0]
    assert adapter.observation().status == "journal_intent_unacknowledged"
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-intent-ack.json")
    assert reopened.revision == 4 and reopened.events[-1].request_index == 1
    assert type(reopened.events[-1]) is multi_journal.SubmissionIntent
    assert reopened.state == "intent_outcome_unknown"
    assert context.inspection_for_characterization()["state"] == "uncertain"
    assert adapter.advance_for_characterization().status == "journal_intent_unacknowledged"
    assert attempts == [0]
    values[0].close()


def test_multi_request_accepted_but_pending_does_not_authorize_the_next_send(tmp_path):
    values = ready_generation(tmp_path, 2)
    context, approved_journal_root = context_for(values, tmp_path, operation_id="multi-pending")
    adapter, sent = executor(values, context, provider=lambda prepared, prompt: ExecutionResult(
        prepared.request_id, prompt, "pending"))
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert [item.request_index for item in sent] == [0]
    assert adapter.observation().status == "awaiting_remote_result"
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-pending.json")
    assert reopened.revision == 2 and reopened.next_request_index == 0
    assert type(reopened.events[0]) is multi_journal.SubmissionIntent
    assert reopened.events[1].outcome == "accepted"
    assert adapter.advance_for_characterization().status == "awaiting_remote_result"
    assert [item.request_index for item in sent] == [0]
    values[0].close()


def test_multi_request_duplicate_accepted_prompt_stops_before_a_later_request(tmp_path):
    values = ready_generation(tmp_path, 3)
    context, approved_journal_root = context_for(values, tmp_path, operation_id="multi-duplicate-prompt")
    duplicate_prompt = str(uuid.uuid4())
    attempts = []

    def transport(prepared):
        attempts.append(prepared.request_index)
        return SubmissionResult("accepted", json.dumps({"prompt_id": duplicate_prompt}).encode())

    adapter, sent = executor(values, context, transport=transport,
        provider=lambda prepared, prompt: ExecutionResult(
            prepared.request_id, prompt, "execution_failed"))
    assert accepted(values, adapter).status in {"characterized_acceptance", "handoff_invalidated"}
    assert attempts == [0, 1] and [item.request_index for item in sent] == [0, 1]
    assert adapter.observation().status == "submission_outcome_unknown"
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-duplicate-prompt.json")
    assert reopened.revision == 5 and reopened.next_request_index == 1
    assert reopened.events[-1].request_index == 1
    assert type(reopened.events[-1]) is multi_journal.SubmissionOutcome
    assert reopened.events[-1].outcome == "unknown"
    assert reopened.state == "submission_outcome_unknown"
    assert adapter.advance_for_characterization().status == "submission_outcome_unknown"
    assert attempts == [0, 1]
    values[0].close()


def test_multi_request_settlement_ack_failure_pins_divergence_and_stops_sequence(tmp_path):
    values = ready_generation(tmp_path, 2)
    after_replace = 0

    def fault(boundary):
        nonlocal after_replace
        if boundary == "after_replace_before_ack":
            after_replace += 1
            if after_replace == 3:
                raise RuntimeError("first settlement acknowledgement lost")

    context, approved_journal_root = context_for(
        values, tmp_path, operation_id="multi-settlement-ack", fault=fault)
    attempts = []

    def transport(prepared):
        attempts.append(prepared.request_index)
        return SubmissionResult("rejected_before_submission")

    adapter, sent = executor(values, context, transport=transport)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert attempts == [0] and [item.request_index for item in sent] == [0]
    assert adapter.observation().status == "journal_settlement_unavailable"
    assert context.inspection_for_characterization()["state"] == "uncertain"
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-settlement-ack.json")
    assert reopened.revision == 3 and reopened.next_request_index == 1
    assert type(reopened.events[-1]) is multi_journal.RequestSettlement
    assert reopened.events[-1].disposition == "pre_send_rejected"
    assert adapter.advance_for_characterization().status == "journal_settlement_unavailable"
    assert attempts == [0]
    values[0].close()


def test_multi_request_outcome_ack_failure_after_possible_send_never_advances(tmp_path):
    values = ready_generation(tmp_path, 2)
    after_replace = 0

    def fault(boundary):
        nonlocal after_replace
        if boundary == "after_replace_before_ack":
            after_replace += 1
            if after_replace == 2:
                raise RuntimeError("first submission outcome acknowledgement lost")

    context, approved_journal_root = context_for(
        values, tmp_path, operation_id="multi-outcome-ack", fault=fault)
    attempts = []

    def transport(prepared):
        attempts.append(prepared.request_index)
        return SubmissionResult("accepted", json.dumps({"prompt_id": str(uuid.uuid4())}).encode())

    adapter, sent = executor(values, context, transport=transport)
    assert accepted(values, adapter).status in {"characterized_acceptance", "handoff_invalidated"}
    assert attempts == [0] and [item.request_index for item in sent] == [0]
    assert adapter.observation().status == "submission_outcome_unknown"
    assert context.inspection_for_characterization()["state"] == "uncertain"
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-outcome-ack.json")
    assert reopened.revision == 2 and reopened.next_request_index == 0
    assert type(reopened.events[-1]) is multi_journal.SubmissionOutcome
    assert reopened.events[-1].outcome == "accepted"
    assert reopened.trust == "inspect_only" and reopened.execution_available is False
    assert adapter.advance_for_characterization().status == "submission_outcome_unknown"
    assert attempts == [0]
    values[0].close()


@pytest.mark.parametrize("drift", ["project", "path", "activation", "pairing", "session", "session_close"])
def test_multi_request_host_drift_after_intent_ack_prevents_next_send(tmp_path, drift):
    case = tmp_path / drift
    case.mkdir()
    values = ready_generation(case, 2)
    runtime, route, state, *_ = values
    after_replace = 0

    def fault(boundary):
        nonlocal after_replace
        if boundary != "after_replace_before_ack":
            return
        after_replace += 1
        # Request 0 consumes three revisions. Drift is introduced after request
        # 1's intent replaces the file but before it may claim the send.
        if after_replace != 4:
            return
        if drift == "project":
            state["project"].prompt_lines[1].current_text = "changed at final send gate"
        elif drift == "path":
            state["current_project_path"] += ".changed"
        elif drift == "activation":
            runtime.synchronize_target(state["project"], state["current_project_path"] + ".changed")
        elif drift == "pairing":
            runtime._registry.release_pairing(route)
        elif drift == "session":
            runtime.generation_jobs._session_incarnation = uuid.uuid4().hex
        else:
            runtime.close()

    context, approved_journal_root = context_for(
        values, case, operation_id=f"multi-drift-{drift}", fault=fault)
    attempts = []

    def transport(prepared):
        attempts.append(prepared.request_index)
        return SubmissionResult("rejected_before_submission")

    adapter, sent = executor(values, context, transport=transport)
    accepted(values, adapter)
    assert attempts == [0] and [item.request_index for item in sent] == [0]
    assert context.inspection_for_characterization()["state"] in {"no_send", "uncertain"}
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, f"multi-drift-{drift}.json")
    assert reopened.revision == 4 and type(reopened.events[-1]) is multi_journal.SubmissionIntent
    assert adapter.advance_for_characterization().status in {
        "journal_host_invalidated_before_send", "journal_intent_unacknowledged",
        "host_invalidated", "handoff_invalidated"}
    assert attempts == [0]
    if drift != "session_close":
        runtime.close()


def test_multi_request_unknown_transport_result_does_not_advance_or_retry(tmp_path):
    values = ready_generation(tmp_path, 2)
    context, approved_journal_root = context_for(values, tmp_path, operation_id="multi-unknown")
    attempts = []

    def transport(prepared):
        attempts.append(prepared.request_index)
        raise OSError("possible send, response lost")

    adapter, sent = executor(values, context, transport=transport)
    assert accepted(values, adapter).status in {"characterized_acceptance", "handoff_invalidated"}
    assert attempts == [0] and [item.request_index for item in sent] == [0]
    assert adapter.observation().status == "submission_outcome_unknown"
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-unknown.json")
    assert reopened.revision == 2 and reopened.next_request_index == 0
    assert reopened.events[-1].outcome == "unknown"
    assert adapter.advance_for_characterization().status == "submission_outcome_unknown"
    assert attempts == [0]
    values[0].close()


def test_multi_request_concurrent_and_reentrant_advance_do_not_duplicate_sends(tmp_path):
    values = ready_generation(tmp_path, 2)
    context, approved_journal_root = context_for(values, tmp_path, operation_id="multi-reentrant")
    entered, release, competing_started = threading.Event(), threading.Event(), threading.Event()
    attempts, holder, handoff_results = [], {}, []

    def transport(prepared):
        attempts.append(prepared.request_index)
        if prepared.request_index == 0:
            # Reentrant advance observes the submitting phase and cannot claim
            # a second request. Another thread then waits behind the same
            # serialization lock until the exact result and settlement finish.
            holder["adapter"].advance_for_characterization()
            entered.set()
            assert release.wait(5)
        return SubmissionResult("rejected_before_submission")

    adapter, sent = executor(values, context, transport=transport)
    holder["adapter"] = adapter
    worker = threading.Thread(target=lambda: handoff_results.append(accepted(values, adapter)))
    worker.start()
    assert entered.wait(5)

    def competing_advance():
        competing_started.set()
        adapter.advance_for_characterization()

    competitor = threading.Thread(target=competing_advance)
    competitor.start()
    assert competing_started.wait(5)
    release.set()
    worker.join(5)
    competitor.join(5)
    assert not worker.is_alive() and not competitor.is_alive()
    assert handoff_results[0].status == "characterized_acceptance"
    assert attempts == [0, 1] and [item.request_index for item in sent] == [0, 1]
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "multi-reentrant.json")
    assert reopened.revision == 6 and reopened.next_request_index == 2
    assert sum(type(event) is multi_journal.SubmissionIntent for event in reopened.events) == 2
    values[0].close()


class _OfflineHTTPResponse:
    def __init__(self, body, status=200):
        self.body, self.status = body, status
        self.closed = False
        self.finished = False

    def read(self, size, timeout):
        assert 0 < size <= 8192 and 0 < timeout <= 10
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk

    def finish(self):
        assert self.body == b""
        self.finished = True

    def close(self):
        self.closed = True


class _OfflineSubmissionFactory:
    def __init__(self, responses, *, connect_failures=(), post_error=None, post_hook=None):
        self.responses = list(responses)
        self.connect_failures = set(connect_failures)
        self.post_error, self.post_hook = post_error, post_hook
        self.connections = 0
        self.posts = []
        self.origins = []
        self.closed = 0

    def __call__(self, origin, connect_timeout):
        index = self.connections
        self.connections += 1
        self.origins.append((origin, connect_timeout))
        factory = self

        class Connection:
            def connect(self):
                if index in factory.connect_failures:
                    raise OSError("offline connect refusal")

            def post_prompt(self, body, timeout):
                factory.posts.append((index, body, timeout))
                if factory.post_hook is not None:
                    factory.post_hook(index, body)
                if factory.post_error is not None:
                    raise factory.post_error
                return _OfflineHTTPResponse(factory.responses.pop(0))

            def close(self):
                factory.closed += 1

        return Connection()


class _OfflineHistoryFactory:
    def __init__(self, responses_by_prompt, *, get_hook=None):
        self.responses_by_prompt = {key: list(value) for key, value in responses_by_prompt.items()}
        self.get_hook = get_hook
        self.gets = []
        self.origins = []
        self.closed = 0

    def __call__(self, origin, connect_timeout):
        self.origins.append((origin, connect_timeout))
        factory = self

        class Connection:
            def connect(self):
                pass

            def get_history(self, prompt_id, timeout):
                factory.gets.append((prompt_id, timeout))
                if factory.get_hook is not None:
                    factory.get_hook(prompt_id)
                responses = factory.responses_by_prompt.get(prompt_id, [])
                body = responses.pop(0) if responses else b"{}"
                return _OfflineHTTPResponse(body)

            def post_prompt(self, *args):
                raise AssertionError("history wire cannot POST")

            def close(self):
                factory.closed += 1

        return Connection()


def _http_composition(values, context, submission_wire, history_wire):
    runtime, _, state, *_ = values
    return compose_http_executor_for_characterization(
        state, runtime, context,
        submission_wire_factory=submission_wire,
        history_wire_factory=history_wire,
        policy=PromptHTTPPolicy(2, 10), characterization=True)


def _run_http_handoff(values, composition):
    runtime, _, state, provider, _, action, *_ = values
    return handoff(state, runtime, provider, action,
                   fake_worker=composition.accept_offer_for_characterization)


def test_offline_http_composition_requires_exact_host_and_explicit_injected_wires(tmp_path):
    from core.comfy_http_history import stdlib_history_wire_for_characterization
    from core.comfy_http_submission import stdlib_prompt_wire_for_characterization

    values = ready_one_request(tmp_path)
    runtime, _, state, *_ = values
    context, _ = context_for(values, tmp_path)
    kwargs = {"submission_wire_factory": _OfflineSubmissionFactory([]),
              "history_wire_factory": _OfflineHistoryFactory({}),
              "policy": PromptHTTPPolicy(2, 10)}
    with pytest.raises(ValueError, match="offline_http_executor_unavailable"):
        compose_http_executor_for_characterization(
            dict(state), runtime, context, characterization=True, **kwargs)
    with pytest.raises(ValueError, match="offline_http_executor_unavailable"):
        compose_http_executor_for_characterization(
            state, runtime, context, submission_wire_factory=stdlib_prompt_wire_for_characterization,
            history_wire_factory=stdlib_history_wire_for_characterization,
            policy=PromptHTTPPolicy(2, 10), characterization=True)
    with pytest.raises(ValueError, match="offline_http_executor_unavailable"):
        compose_http_executor_for_characterization(
            state, runtime, context, **kwargs)
    assert context.inspection_for_characterization()["state"] == "unbound"
    values[0].close()


def test_offline_http_composition_orders_journaled_post_and_exact_history_before_output_event(
        tmp_path, monkeypatch):
    from test_comfy_output_containment import successful_metadata
    from ui import agent_generation_http_executor as composition_module

    values = ready_generation(tmp_path, 3)
    runtime, _, state, *_ = values
    project_before = copy.deepcopy(state["project"])
    prompt_id = str(uuid.uuid4())
    order, delivered_events = [], []

    def host_locks_held():
        session_record = runtime._registry._record_for_registration(runtime._registration)
        locks = (runtime._publication_gate, session_record.operation_lock,
                 runtime.generation_jobs._lock, runtime._generation_executor_inbox._lock)
        held = []
        for lock in locks:
            is_owned = getattr(lock, "_is_owned", None)
            if callable(is_owned):
                held.append(is_owned())
            else:
                acquired = lock.acquire(blocking=False)
                if acquired:
                    lock.release()
                held.append(not acquired)
        return any(held)

    def journal_fault(boundary):
        assert not host_locks_held()
        order.append(("journal", boundary))

    context, journal_root = context_for(
        values, tmp_path, operation_id="http-success-after-rejection", fault=journal_fault)
    history_body = successful_metadata(prompt_id)

    def post_hook(index, body):
        assert index == 1
        assert not host_locks_held()
        reopened = multi_journal.reopen_multi_request_journal(
            journal_root, "http-success-after-rejection.json")
        assert reopened.revision == 4
        assert type(reopened.events[0]) is multi_journal.SubmissionIntent
        assert reopened.events[0].request_index == 0
        assert reopened.events[2].disposition == "pre_send_rejected"
        assert type(reopened.events[3]) is multi_journal.SubmissionIntent
        assert reopened.events[3].request_index == 1
        order.append(("post", len(body)))

    def history_hook(current_prompt):
        assert current_prompt == prompt_id
        assert not host_locks_held()
        reopened = multi_journal.reopen_multi_request_journal(
            journal_root, "http-success-after-rejection.json")
        assert reopened.revision == 5 and reopened.events[-1].outcome == "accepted"
        order.append(("history", current_prompt))

    def submit_response(body):
        return json.dumps({"prompt_id": prompt_id}, separators=(",", ":")).encode()

    class SubmissionFactory(_OfflineSubmissionFactory):
        def __init__(self):
            super().__init__([submit_response(None)], connect_failures={0}, post_hook=post_hook)

    submission_wire = SubmissionFactory()
    history_wire = _OfflineHistoryFactory({prompt_id: [history_body]}, get_hook=history_hook)
    original_deliver = composition_module.deliver_executor_event_for_characterization

    def observed_deliver(current_state, current_runtime, event):
        delivered_events.append(event)
        order.append(("host_event", event.progress.kind))
        return original_deliver(current_state, current_runtime, event)

    monkeypatch.setattr(composition_module, "deliver_executor_event_for_characterization", observed_deliver)
    composed = _http_composition(values, context, submission_wire, history_wire)
    assert composed.execution_available is False
    assert composed.protected_storage_available is False
    assert composed.promotion_available is False
    assert composed.candidate_publication_allowed is False
    assert composed.authorship == "unverified"

    accepted_receipt = _run_http_handoff(values, composed)
    assert accepted_receipt.status == "characterized_acceptance"
    assert composed.observation_for_characterization().status == "awaiting_download"
    assert len(submission_wire.posts) == 1
    assert len(history_wire.gets) == 1 and history_wire.gets[0][0] == prompt_id
    envelope = runtime._generation_publication_origin.envelope
    request = envelope.manifest.requests[1]
    client_id = str(uuid.uuid5(uuid.NAMESPACE_OID, "|".join((
        envelope.job_id, envelope.claim_id, envelope.manifest.manifest_identity, request.request_id))))
    from core.comfy_prompt_request import prepare_frozen_prompt_request
    expected = prepare_frozen_prompt_request(envelope.manifest, request, client_id=client_id)
    assert submission_wire.posts[0][1] == expected.body_json
    assert submission_wire.connections == 2 and submission_wire.origins[1] == history_wire.origins[0]
    assert submission_wire.closed == 2 and history_wire.closed == 1
    assert submission_wire.closed and history_wire.closed

    event_kinds = [event.progress.kind for event in delivered_events]
    start_indices = [index for index, kind in enumerate(event_kinds) if kind == "submission_started"]
    assert len(start_indices) == 2 and start_indices[-1] < event_kinds.index("submitted")
    assert "outputs_ready" not in event_kinds
    assert "remote_outputs_ready" in event_kinds
    remote_event = next(event for event in delivered_events if event.progress.kind == "remote_outputs_ready")
    assert remote_event.outputs.output_count == 1
    assert str(values[-1]) not in repr(remote_event)
    before_replace_indices = [index for index, item in enumerate(order)
                              if item == ("journal", "before_replace")]
    assert len(before_replace_indices) == 5
    start_event_indices = [index for index, item in enumerate(order)
                           if item == ("host_event", "submission_started")]
    assert len(start_event_indices) == 2
    assert (start_event_indices[-1] < before_replace_indices[3]
            < next(index for index, item in enumerate(order) if item[0] == "post")
            < before_replace_indices[4] < order.index(("host_event", "submitted"))
            < next(index for index, item in enumerate(order) if item[0] == "history"))

    reopened = multi_journal.reopen_multi_request_journal(
        journal_root, "http-success-after-rejection.json")
    assert reopened.revision == 5 and reopened.next_request_index == 1
    assert [type(event) for event in reopened.events] == [
        multi_journal.SubmissionIntent, multi_journal.SubmissionOutcome,
        multi_journal.RequestSettlement, multi_journal.SubmissionIntent,
        multi_journal.SubmissionOutcome]
    assert reopened.events[-1].outcome == "accepted"
    assert reopened.trust == "inspect_only" and reopened.authorship == "unverified"
    before_posts = len(submission_wire.posts)
    assert composed.advance_for_characterization().status == "awaiting_download"
    assert len(submission_wire.posts) == before_posts == 1
    assert state["project"] == project_before
    assert runtime.generation_jobs.snapshot(accepted_receipt.job_id)["save_state"] == "not_attempted"
    rows = runtime.generation_jobs.snapshot(accepted_receipt.job_id)["requests"]
    assert [row["state"] for row in rows] == ["failed", "awaiting_download", "unsent"]
    runtime.close()


def test_offline_http_pending_history_can_be_explicitly_reread_without_post_retry(tmp_path):
    from test_comfy_output_containment import successful_metadata

    values = ready_one_request(tmp_path)
    context, journal_root = context_for(values, tmp_path)
    prompt_id = str(uuid.uuid4())
    submission_wire = _OfflineSubmissionFactory([
        json.dumps({"prompt_id": prompt_id}, separators=(",", ":")).encode()])
    composition_holder = {}
    reentrant_observations = []

    def reenter_during_initial_history(current_prompt):
        assert current_prompt == prompt_id
        reentrant_observations.append(
            composition_holder["value"].read_current_history_for_characterization())

    history_wire = _OfflineHistoryFactory(
        {prompt_id: [b"{}", successful_metadata(prompt_id)]},
        get_hook=reenter_during_initial_history)
    composed = _http_composition(values, context, submission_wire, history_wire)
    composition_holder["value"] = composed
    assert _run_http_handoff(values, composed).status == "characterized_acceptance"
    assert composed.observation_for_characterization().status == "awaiting_remote_result"
    assert len(submission_wire.posts) == 1 and len(history_wire.gets) == 1
    assert len(reentrant_observations) == 1

    reread = composed.read_current_history_for_characterization()
    assert reread.status == "awaiting_download"
    assert len(submission_wire.posts) == 1 and len(history_wire.gets) == 2
    # Once completed metadata is retained, a late explicit poll is fenced.
    fenced = composed.read_current_history_for_characterization()
    assert fenced.status == "awaiting_download"
    assert len(submission_wire.posts) == 1 and len(history_wire.gets) == 2
    reopened = journal.reopen_journal(journal_root, "operation.json")
    assert reopened.revision == 2 and reopened.observations[-1].outcome == "accepted"
    values[0].close()


def test_offline_http_pre_send_failures_settle_before_next_request_and_response_loss_never_retries(
        tmp_path):
    values = ready_generation(tmp_path, 2)
    context, approved_journal_root = context_for(values, tmp_path, operation_id="http-pre-send")
    submission_wire = _OfflineSubmissionFactory([], connect_failures={0, 1})
    history_wire = _OfflineHistoryFactory({})
    composed = _http_composition(values, context, submission_wire, history_wire)
    assert _run_http_handoff(values, composed).status == "characterized_acceptance"
    assert composed.observation_for_characterization().status == "requests_settled"
    assert submission_wire.connections == 2 and submission_wire.posts == []
    assert history_wire.gets == []
    reopened = multi_journal.reopen_multi_request_journal(
        approved_journal_root, "http-pre-send.json")
    assert reopened.revision == 6 and reopened.next_request_index == 2
    assert [event.outcome for event in reopened.events if type(event) is multi_journal.SubmissionOutcome] == [
        "pre_send_rejected", "pre_send_rejected"]
    assert [event.disposition for event in reopened.events if type(event) is multi_journal.RequestSettlement] == [
        "pre_send_rejected", "pre_send_rejected"]
    values[0].close()

    uncertain_values = ready_generation(tmp_path / "uncertain", 2)
    uncertain_context, uncertain_root = context_for(
        uncertain_values, tmp_path / "uncertain", operation_id="http-response-loss")
    lost_wire = _OfflineSubmissionFactory([], post_error=OSError("response lost"))
    no_history = _OfflineHistoryFactory({})
    uncertain = _http_composition(uncertain_values, uncertain_context, lost_wire, no_history)
    _run_http_handoff(uncertain_values, uncertain)
    assert uncertain.observation_for_characterization().status == "submission_outcome_unknown"
    assert len(lost_wire.posts) == 1 and no_history.gets == []
    assert uncertain.advance_for_characterization().status == "submission_outcome_unknown"
    assert len(lost_wire.posts) == 1
    unresolved = multi_journal.reopen_multi_request_journal(
        uncertain_root, "http-response-loss.json")
    assert unresolved.revision == 2 and unresolved.next_request_index == 0
    assert unresolved.events[-1].outcome == "unknown"
    uncertain_values[0].close()


def test_offline_http_reentrant_and_concurrent_advance_during_post_never_duplicate_send(tmp_path):
    values = ready_generation(tmp_path, 2)
    context, _ = context_for(values, tmp_path, operation_id="http-concurrent")
    prompt_id = str(uuid.uuid4())
    entered, release, competing_started = threading.Event(), threading.Event(), threading.Event()
    holder, results = {}, []

    def post_hook(index, body):
        if index == 0:
            holder["composition"].advance_for_characterization()
            assert len(submission_wire.posts) == 1
            entered.set()
            assert release.wait(5)

    submission_wire = _OfflineSubmissionFactory([
        json.dumps({"prompt_id": prompt_id}, separators=(",", ":")).encode()], post_hook=post_hook)
    history_wire = _OfflineHistoryFactory({prompt_id: [b"{}"]})
    composed = _http_composition(values, context, submission_wire, history_wire)
    holder["composition"] = composed
    worker = threading.Thread(target=lambda: results.append(_run_http_handoff(values, composed)))
    worker.start()
    assert entered.wait(5)

    def advance_concurrently():
        competing_started.set()
        composed.advance_for_characterization()

    competitor = threading.Thread(target=advance_concurrently)
    competitor.start()
    assert competing_started.wait(5)
    release.set()
    worker.join(5)
    competitor.join(5)
    assert not worker.is_alive() and not competitor.is_alive()
    assert results and results[0].status == "characterized_acceptance"
    assert len(submission_wire.posts) == 1 and history_wire.gets == [(prompt_id, 10)]
    assert composed.observation_for_characterization().status == "awaiting_remote_result"
    assert composed.advance_for_characterization().status == "awaiting_remote_result"
    assert len(submission_wire.posts) == 1
    values[0].close()


def test_offline_http_close_during_possible_send_never_replays_or_reads_history(tmp_path):
    values = ready_one_request(tmp_path)
    runtime = values[0]
    context, journal_root = context_for(values, tmp_path, operation_id="http-close")
    prompt_id = str(uuid.uuid4())

    def close_after_post_invocation(index, body):
        runtime.close()

    submission_wire = _OfflineSubmissionFactory([
        json.dumps({"prompt_id": prompt_id}, separators=(",", ":")).encode()],
        post_hook=close_after_post_invocation)
    history_wire = _OfflineHistoryFactory({prompt_id: [b"{}"]})
    composed = _http_composition(values, context, submission_wire, history_wire)
    _run_http_handoff(values, composed)
    assert len(submission_wire.posts) == 1
    assert history_wire.gets == []
    status = composed.observation_for_characterization().status
    assert status in {"host_invalidated", "submission_outcome_unknown"}
    assert composed.advance_for_characterization().status == status
    assert len(submission_wire.posts) == 1
    reopened = journal.reopen_journal(journal_root, "http-close.json")
    assert reopened.revision in {1, 2}
    assert reopened.observations[0].checkpoint == "submission_intent"
    if reopened.revision == 2:
        assert reopened.observations[1].outcome == "accepted"


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


def test_multi_request_manifest_uses_the_separate_multi_request_journal_contract(tmp_path):
    values = ready_generation(tmp_path, 2)
    context, journal_root = context_for(values, tmp_path, operation_id="multi-default")
    adapter, sent = executor(values, context)
    assert accepted(values, adapter).status == "characterized_acceptance"
    assert [item.request_index for item in sent] == [0, 1]
    assert adapter.observation().status == "requests_settled"
    reopened = multi_journal.reopen_multi_request_journal(journal_root, "multi-default.json")
    assert reopened.revision == 6 and reopened.next_request_index == 2
    assert [event.disposition for event in reopened.events
            if type(event) is multi_journal.RequestSettlement] == ["execution_failed", "execution_failed"]
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
