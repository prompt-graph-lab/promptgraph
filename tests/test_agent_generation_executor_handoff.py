"""C2B-3 deterministic private inbox/claim ownership; no real execution."""
import copy
import ast
from dataclasses import FrozenInstanceError, replace
import json
import threading
from unittest.mock import patch
import uuid
from pathlib import Path

import pytest

from core.generation_executable_manifest import MAX_AGGREGATE_BYTES, MAX_WORKFLOW_BYTES
from ui.agent_generation_executable_confirmation import (
    confirm_session_execution_details as confirm, prepare_session_executable_review as prepare,
)
from ui.agent_generation_executor_handoff import (
    handoff_generation_for_characterization as handoff,
    deliver_executor_event_for_characterization as deliver,
    capture_executor_human_start_for_characterization as capture_start,
)
from ui.agent_generation_executor_inbox import (
    GenerationExecutorInbox, HandoffReceipt, ExecutorEvent, OutputReceipt,
    MAX_LATE_RECEIPTS, RESERVATION_TTL,
)
from ui.agent_generation_job import GenerationJobRegistry, WorkerEvent, ACTIVE_TTL
from ui.agent_generation_start_lifecycle import capture_human_start_action
from test_agent_generation_executable_review_ui import queued, identity, safe_capture


def ready(*, characterization=True, confirm_details=True):
    runtime, route, epoch, state, args, provider = queued(runs=2)
    if characterization:
        runtime.generation_jobs = GenerationJobRegistry(characterization=True)
        runtime._generation_executor_inbox = GenerationExecutorInbox(characterization=True)
        runtime.synchronize_target(state["project"], state["current_project_path"])
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: 0) == "certified"
    held = runtime._executable_review
    if confirm_details:
        assert confirm(state, runtime, provider, held) == "confirmed"
    action = capture_start(runtime)
    return runtime, route, state, provider, held, action


def accept(runtime, offer):
    return runtime._generation_executor_inbox.accept_for_characterization(runtime.generation_jobs, offer)


def event(offer, sequence, kind, *, index=0, count=0, receipt_id=None):
    outputs = OutputReceipt(receipt_id or uuid.uuid4().hex, count) if kind == "outputs_ready" else None
    return ExecutorEvent(offer.job_id, offer.claim_id, offer.manifest_identity,
                         WorkerEvent(sequence, index, kind, count), outputs)


def start(values, worker=None):
    runtime, route, state, provider, held, action = values
    return handoff(state, runtime, provider, action, fake_worker=worker or (lambda offer: accept(runtime, offer)[0]))


def test_exact_confirmation_claim_take_seed_identity_and_no_side_effects():
    values = ready()
    runtime, route, state, provider, held, action = values
    before, swap = copy.deepcopy(state), runtime.inspect_review_custody()
    taken = []
    def worker(offer):
        assert runtime.generation_jobs.snapshot(offer.job_id)["state"] == "claimed"
        assert runtime.generation_review_custodian.inspect_for_human_review()["state"] != "pending"
        receipt, envelope = accept(runtime, offer)
        taken.append(envelope)
        return receipt
    with patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
         patch("threading.Thread.start", side_effect=AssertionError("real worker")), \
         patch("builtins.open", side_effect=AssertionError("output")), \
         patch("core.comfy_prompt_request.prepare_prompt_request", side_effect=AssertionError("rerandomization")):
        result = start(values, worker)
    assert result.status == "characterized_acceptance"
    envelope = taken[0]
    assert envelope.manifest is held.review.manifest
    assert envelope.origin_identity == held.review.origin_identity
    assert envelope.binding.plan_identity == held.review.manifest.manifest_identity
    assert [r.request_index for r in envelope.manifest.requests] == [0, 1, 2, 3]
    assert [r.run_index for r in envelope.manifest.requests] == [1, 2, 1, 2]
    seeds = [json.loads(r.workflow_json)["s"]["inputs"]["seed"] for r in envelope.manifest.requests]
    assert seeds == [0, 2, 4, 6]
    with pytest.raises(FrozenInstanceError): envelope.manifest.seed_policy = "changed"
    assert state == before and runtime.inspect_review_custody() == swap
    assert runtime._executable_confirmation is None
    assert runtime.generation_jobs.snapshot(result.job_id)["registered_count"] == 0
    assert runtime.generation_jobs.snapshot(result.job_id)["save_state"] == "not_attempted"
    assert not runtime.generation_jobs.execution_available and not runtime._generation_executor_inbox.execution_available
    runtime.close()


@pytest.mark.parametrize("progress", ["running", "awaiting_result"])
def test_progress_before_handoff_returns_does_not_require_claimed_state(progress):
    values = ready()
    runtime, _, state, *_ = values
    def worker(offer):
        receipt, envelope = accept(runtime, offer)
        assert deliver(state, runtime, event(offer, 1, "submission_started")) == "accepted"
        if progress == "awaiting_result":
            assert deliver(state, runtime, event(offer, 2, "submitted")) == "accepted"
        return receipt
    result = start(values, worker)
    assert result.status == "characterized_acceptance"
    assert runtime.generation_jobs.snapshot(result.job_id)["state"] == progress
    runtime.close()


def test_double_human_claim_and_double_worker_acceptance_are_one_shot():
    values = ready()
    runtime, _, state, provider, held, action = values
    barrier = threading.Barrier(2)
    results, envelopes = [], []
    def worker(offer):
        receipt, envelope = accept(runtime, offer)
        envelopes.append(envelope)
        return receipt
    def click():
        barrier.wait()
        results.append(handoff(state, runtime, provider, action, fake_worker=worker))
    threads = [threading.Thread(target=click) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(timeout=5); assert not thread.is_alive()
    assert len(envelopes) == 1
    assert sum(r.status == "characterized_acceptance" for r in results) == 1
    assert len(runtime.generation_jobs._jobs) == 1
    offer = next(r for r in results if r.job_id)
    assert accept(runtime, offer)[0].status == "duplicate_acceptance"
    assert start(values, worker).status != "characterized_acceptance"
    assert len(envelopes) == 1
    runtime.close()


def test_concurrent_worker_acceptance_returns_exactly_one_envelope():
    values = ready()
    runtime = values[0]
    receipts, envelopes = [], []
    def worker(offer):
        barrier = threading.Barrier(2)
        def take():
            barrier.wait()
            receipt, envelope = accept(runtime, offer)
            receipts.append(receipt)
            if envelope is not None: envelopes.append(envelope)
        threads = [threading.Thread(target=take) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5); assert not thread.is_alive()
        return next(r for r in receipts if r.status == "accepted")
    assert start(values, worker).status == "characterized_acceptance"
    assert len(envelopes) == 1
    assert {r.status for r in receipts} == {"accepted", "duplicate_acceptance"}
    runtime.close()


def test_reservation_failure_preserves_confirmation_and_proposal():
    values = ready()
    runtime, _, state, _, held, _ = values
    pending = runtime.generation_review_custodian.inspect_for_human_review()
    confirmation = runtime._executable_confirmation
    reservation = runtime._generation_executor_inbox.reserve_for_characterization(held.review.manifest)
    assert reservation.status == "reserved"
    assert start(values).status == "capacity_unavailable"
    assert runtime.generation_review_custodian.inspect_for_human_review() == pending
    assert runtime._executable_confirmation is confirmation and not runtime.generation_jobs._jobs
    runtime._generation_executor_inbox.release_reservation(reservation)
    assert start(values).status == "characterized_acceptance"
    runtime.close()


@pytest.mark.parametrize("mutation", ["list", "mutable_bytes", "workflow_limit", "aggregate_limit", "index", "fingerprint", "field", "duplicate", "mutable_policy"])
def test_payload_bounds_and_deep_immutability(mutation):
    values = ready()
    runtime, _, _, _, held, _ = values
    manifest = held.review.manifest
    r = manifest.requests[0]
    if mutation == "list": manifest = replace(manifest, requests=list(manifest.requests))
    elif mutation == "mutable_bytes": manifest = replace(manifest, host_config_json=bytearray(b"{}"))
    elif mutation == "workflow_limit": manifest = replace(manifest, requests=(replace(r, workflow_json=b"x" * (MAX_WORKFLOW_BYTES + 1)),))
    elif mutation == "aggregate_limit": manifest = replace(manifest, host_config_json=b"x" * (MAX_AGGREGATE_BYTES + 1))
    elif mutation == "index": manifest = replace(manifest, requests=(replace(r, request_index=1),))
    elif mutation == "fingerprint": manifest = replace(manifest, requests=(replace(r, workflow_identity="0" * 64),))
    elif mutation == "field": manifest = replace(manifest, scene_id="x" * 161)
    elif mutation == "duplicate": manifest = replace(manifest, requests=(r, replace(r, request_index=1)))
    elif mutation == "mutable_policy": manifest = replace(manifest, seed_policy={"policy": "random_u64"})
    assert runtime._generation_executor_inbox.reserve_for_characterization(manifest).status == "invalid_payload"
    assert not runtime.generation_jobs._jobs
    runtime.close()


def test_reservation_expiry_does_not_claim_or_authorize_start():
    values = ready()
    runtime, _, _, _, held, _ = values
    clock = [10]
    inbox = runtime._generation_executor_inbox
    inbox._clock = lambda: clock[0]
    first = inbox.reserve_for_characterization(held.review.manifest)
    assert first.status == "reserved" and not runtime.generation_jobs._jobs
    clock[0] += RESERVATION_TTL
    second = inbox.reserve_for_characterization(held.review.manifest)
    assert second.status == "reserved" and second != first
    inbox.release_reservation(first)
    assert inbox.reserve_for_characterization(held.review.manifest).status == "capacity_unavailable"
    inbox.release_reservation(second)
    runtime.close()


@pytest.mark.parametrize("outcome", ["rejected", "unknown", "raise", "bare_accepted", "forged_accepted", "accepted_then_raise", "progress_then_reject"])
def test_definite_rejection_vs_unknown_and_no_retry(outcome):
    values = ready()
    runtime, _, state, *_ = values
    calls, offers = [], []
    def worker(offer):
        calls.append(1); offers.append(offer)
        if outcome in {"accepted_then_raise", "progress_then_reject"}:
            accept(runtime, offer)
        if outcome == "progress_then_reject":
            assert deliver(state, runtime, event(offer, 1, "submission_started")) == "accepted"
        if outcome in {"raise", "accepted_then_raise"}: raise TimeoutError("PRIVATE_ERROR")
        if outcome == "bare_accepted": return "accepted"
        return replace(offer, status="accepted" if outcome == "forged_accepted" else
                       "rejected" if outcome in {"rejected", "progress_then_reject"} else "unknown")
    result = start(values, worker)
    expected = "failed" if outcome == "rejected" else "submission_outcome_unknown"
    assert runtime.generation_jobs.snapshot(result.job_id)["state"] == expected
    assert result.status == ("handoff_rejected" if outcome == "rejected" else "handoff_unknown")
    assert start(values, worker).status != "characterized_acceptance" and len(calls) == 1
    assert accept(runtime, offers[0])[1] is None
    assert "PRIVATE_ERROR" not in repr(result)
    runtime.close()


def test_order_duplicate_conflict_and_output_receipts_do_not_publish():
    values = ready()
    runtime, _, state, *_ = values
    offer = start(values)
    started = event(offer, 1, "submission_started")
    assert deliver(state, runtime, event(offer, 2, "submitted")) == "event_out_of_order"
    assert deliver(state, runtime, event(offer, 1, "submission_started", index=1)) == "invalid_transition"
    assert deliver(state, runtime, started) == "accepted"
    assert deliver(state, runtime, started) == "duplicate_event"
    assert deliver(state, runtime, event(offer, 1, "failed")) == "event_conflict"
    assert deliver(state, runtime, event(offer, 2, "submitted")) == "accepted"
    outputs = event(offer, 3, "outputs_ready", count=2)
    assert deliver(state, runtime, replace(outputs, outputs=None)) == "invalid_event"
    assert deliver(state, runtime, outputs) == "accepted"
    assert deliver(state, runtime, outputs) == "duplicate_event"
    assert deliver(state, runtime, replace(outputs, outputs=OutputReceipt(uuid.uuid4().hex, 2))) == "event_conflict"
    assert deliver(state, runtime, event(offer, 4, "failed")) == "invalid_transition"
    snapshot = runtime.generation_jobs.snapshot(offer.job_id)
    assert snapshot["output_count"] == 2 and snapshot["registered_count"] == 0
    assert snapshot["state"] == "awaiting_result" and snapshot["save_state"] == "not_attempted"
    assert runtime._generation_executor_inbox.late_receipts() == ()
    assert deliver(state, runtime, replace(started, claim_id=uuid.uuid4().hex)) == "stale_receipt"
    assert deliver(state, runtime, replace(started, manifest_identity="0" * 64)) == "stale_receipt"
    runtime.close()


def test_only_definite_terminal_outcome_releases_worker_slot():
    values = ready()
    runtime, _, state, *_ = values
    offer = start(values)
    inbox, jobs = runtime._generation_executor_inbox, runtime.generation_jobs
    assert inbox.retire_settled_for_characterization(jobs, offer) == "recovery_required"
    sequence = 0
    for index in range(4):
        sequence += 1
        assert deliver(state, runtime, event(offer, sequence, "failed", index=index)) == "accepted"
    assert jobs.snapshot(offer.job_id)["state"] == "failed"
    assert inbox.retire_settled_for_characterization(jobs, offer) == "retired"
    assert inbox.reserve_for_characterization(values[4].review.manifest).status == "reserved"
    assert start(values).status != "characterized_acceptance"
    runtime.close()


@pytest.mark.parametrize("when", ["before_take", "after_take", "after_progress"])
@pytest.mark.parametrize("invalidation", ["switch", "save_as", "pairing", "close", "disarm"])
def test_acceptance_invalidation_race_and_late_outputs(when, invalidation):
    values = ready()
    runtime, route, state, *_ = values
    def invalidate():
        if invalidation == "switch": state["project"] = copy.deepcopy(state["project"])
        elif invalidation == "save_as": state["current_project_path"] = "SAVE_AS"
        elif invalidation == "pairing":
            route.release()
            bootstrap = runtime.arm_local_pairing().bootstrap
            assert runtime._registry.claim_pairing(bootstrap.process_incarnation, bootstrap.route_id, bootstrap.capability).status == "paired"
        elif invalidation == "close": runtime.close()
        else: runtime.disarm_launcher_rendezvous()
        if invalidation in {"switch", "save_as"}:
            runtime.synchronize_target(state["project"], state["current_project_path"])
    offers = []
    def worker(offer):
        offers.append(offer)
        if when == "before_take": invalidate()
        receipt, envelope = accept(runtime, offer)
        if when == "after_progress":
            assert deliver(state, runtime, event(offer, 1, "submission_started")) == "accepted"
        if when != "before_take": invalidate()
        return receipt
    result = start(values, worker)
    assert result.status != "characterized_acceptance"
    late = event(offers[0], 3, "outputs_ready", count=1)
    assert deliver(state, runtime, late) == "late_event"
    assert runtime._generation_executor_inbox.late_receipts() == (late,)
    assert deliver(state, runtime, late) == "late_event"
    assert len(runtime._generation_executor_inbox.late_receipts()) == 1
    assert accept(runtime, offers[0])[1] is None
    runtime.close()


@pytest.mark.parametrize("loss", ["no_progress", "after_submission", "worker_death"])
def test_worker_loss_lease_expiry_retains_unknown_no_restart(loss):
    values = ready()
    runtime, _, state, *_ = values
    clock = [10]
    runtime.generation_jobs._clock = lambda: clock[0]
    offer = start(values)
    if loss != "no_progress": assert deliver(state, runtime, event(offer, 1, "submission_started")) == "accepted"
    clock[0] += ACTIVE_TTL
    assert runtime.generation_jobs.snapshot(offer.job_id)["state"] == "unavailable"
    assert deliver(state, runtime, event(offer, 3, "outputs_ready", count=1)) == "late_event"
    assert accept(runtime, offer)[1] is None
    assert runtime._generation_executor_inbox.reserve_for_characterization(values[4].review.manifest).status == "capacity_unavailable"
    assert runtime.generation_jobs.snapshot(offer.job_id)["registered_count"] == 0
    runtime.close()


def test_late_receipt_budget_and_invalid_events_are_bounded():
    values = ready()
    runtime, _, state, *_ = values
    offer = start(values)
    runtime.close()
    for sequence in range(1, MAX_LATE_RECEIPTS + 4):
        assert deliver(state, runtime, event(offer, sequence, "outputs_ready", count=1)) == "late_event"
    late = runtime._generation_executor_inbox.late_receipts()
    assert len(late) == MAX_LATE_RECEIPTS and late[0].progress.sequence == 4
    assert deliver(state, runtime, replace(event(offer, 1, "outputs_ready", count=1),
        progress=WorkerEvent(1, 0, "PRIVATE_RAW_ERROR" * 10000))) == "invalid_event"
    assert deliver(state, runtime, event(offer, 1, "outputs_ready", index=99, count=1)) == "invalid_event"
    assert runtime._generation_executor_inbox.late_receipts() == late


@pytest.mark.parametrize("invalidation", ["expiry", "cancel", "changed_workflow", "changed_seed", "unconfirmed", "wrong_action", "wrong_confirmation"])
def test_before_claim_fresh_exact_review_required(invalidation):
    values = list(ready(confirm_details=invalidation != "unconfirmed"))
    runtime, _, state, provider, held, action = values
    if invalidation == "expiry": runtime.generation_review_custodian._record.expires_at = 0
    elif invalidation == "cancel": runtime.mailbox.cancel_review_custody(runtime.generation_review_custodian)
    elif invalidation == "changed_workflow":
        from test_agent_generation_executable_manifest import host_for
        values[3] = host_for(change=lambda w: w["s"]["inputs"].update(steps=99))
    elif invalidation == "changed_seed":
        request = held.review.manifest.requests[0]
        runtime._executable_review = replace(held, review=replace(held.review,
            manifest=replace(held.review.manifest, requests=(replace(request, workflow_json=b"{}"),))))
    elif invalidation == "wrong_action": values[5] = {"proposal_id": held.review.manifest.proposal_id}
    elif invalidation == "wrong_confirmation":
        runtime._executable_confirmation = replace(runtime._executable_confirmation, manifest_identity="0" * 64)
    assert start(values, lambda offer: pytest.fail("worker invoked")).status != "characterized_acceptance"
    assert not runtime.generation_jobs._jobs and runtime._generation_executor_inbox._state == "empty"
    runtime.close()


def test_production_and_public_ids_never_enable_inbox_or_start():
    values = ready(characterization=False)
    runtime, _, state, _, held, action = values
    assert start(values, lambda offer: pytest.fail("production worker")).status == "execution_unavailable"
    assert runtime._generation_executor_inbox.reserve_for_characterization(held.review.manifest).status == "execution_unavailable"
    assert not runtime.generation_jobs._jobs
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "pending"
    assert runtime._executable_confirmation is not None
    assert not runtime._generation_executor_inbox.execution_available
    runtime.close()


def test_no_production_start_or_mcp_inbox_access():
    from agent_adapters.mcp_adapter import PromptGraphMCPAdapter, get_tool_catalog
    adapter = PromptGraphMCPAdapter(lambda: pytest.fail("host accessed"))
    names = {entry["name"] for entry in get_tool_catalog()}
    for name in ("promptgraph_start_generation", "promptgraph_executor_inbox", "promptgraph_claim_generation"):
        assert name not in names
        assert adapter.call_tool(name, {"proposal_id": "public", "approved": True})["reason"] == "unknown_tool"
    root = Path(__file__).resolve().parents[1]
    for relative in ("app.py", "agent_adapters/mcp_adapter.py", "ui/project_agent_request_bridge.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert "ui.agent_generation_executor_handoff" not in imports


def test_reservation_expiring_during_final_claim_keeps_custody_recoverable():
    values = ready()
    runtime = values[0]
    times = iter([10, 10 + RESERVATION_TTL])
    runtime._generation_executor_inbox._clock = lambda: next(times)
    assert start(values, lambda offer: pytest.fail("worker")).status == "reservation_unavailable"
    assert not runtime.generation_jobs._jobs
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "pending"
    assert runtime._executable_confirmation is not None
    runtime.close()


@pytest.mark.parametrize("outcome", ["failed", "submission_unknown"])
def test_submission_outcomes_preserve_sequential_no_retry_boundary(outcome):
    values = ready()
    runtime, _, state, *_ = values
    offer = start(values)
    assert deliver(state, runtime, event(offer, 1, "submission_started")) == "accepted"
    assert deliver(state, runtime, event(offer, 2, outcome)) == "accepted"
    assert deliver(state, runtime, event(offer, 3, "submission_started", index=1)) == (
        "accepted" if outcome == "failed" else "late_event")
    assert accept(runtime, offer)[1] is None
    assert start(values).status != "characterized_acceptance"
    runtime.close()


def test_new_human_action_must_follow_exact_confirmation_and_refresh():
    values = list(ready(confirm_details=False))
    runtime, _, state, provider, held, action = values
    assert action is None and capture_start(runtime) is None
    assert confirm(state, runtime, provider, held) == "confirmed"
    old_action = capture_start(runtime)
    # C2A's IDs-only carrier cannot grant C2B-3 handoff authority.
    values[5] = capture_human_start_action(runtime, *identity(runtime))
    assert start(values).status == "invalid_human_action"
    assert prepare(state, runtime, provider, *identity(runtime), refresh=True,
                   expected_review=held, random_u64=lambda: 100) == "certified"
    assert capture_start(runtime) is None
    assert confirm(state, runtime, provider, runtime._executable_review) == "confirmed"
    values[5] = old_action
    assert start(values).status == "stale_human_action"
    assert not runtime.generation_jobs._jobs
    values[5] = capture_start(runtime)
    assert start(values).status == "characterized_acceptance"
    runtime.close()
