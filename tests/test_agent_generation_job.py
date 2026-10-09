"""Deterministic contracts for an inert session-owned job foundation."""

from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import FrozenInstanceError, replace
import json
import sys
import subprocess
import threading

import pytest

from ui.agent_generation_job import (
    ACTIVE_TTL, MAX_EVENT_HISTORY, MAX_JOBS, MAX_REQUESTS, PREPARED_TTL,
    TERMINAL_TTL, GenerationJobRegistry, JobRequest, WorkerEvent,
)


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


def owner(*, count=1, characterization=True):
    clock = Clock()
    registry = GenerationJobRegistry(clock=clock, characterization=characterization)
    registry.synchronize_target("a" * 32, "b" * 32)
    binding = registry.host_binding(pairing_generation=1, plan_identity="c" * 64)
    requests = [JobRequest(f"gallery_generation:line-{i}:1", f"line-{i}", 1, "d" * 64)
                for i in range(count)]
    receipt = registry.prepare(binding, requests)
    assert receipt.status == "prepared_not_started"
    return registry, binding, requests, receipt.job_id, clock


def claim(registry, binding, job_id, key="e" * 32):
    receipt = registry.claim_for_characterization(job_id, binding=binding, claim_key=key)
    assert receipt.status == "claimed"
    return receipt.claim_id


def outputs(registry, job_id, claim_id, index=0, sequence=1, count=1):
    for offset, kind in enumerate(("submission_started", "submitted", "outputs_ready")):
        assert registry.event_for_characterization(
            job_id, claim_id, WorkerEvent(sequence + offset, index, kind,
                                         count if kind == "outputs_ready" else 0)) == "accepted"


def publish(registry, binding, job_id, claim_id, index=0, count=1):
    assert registry.publication_for_characterization(
        job_id, claim_id, binding=binding, request_index=index,
        registered_count=count) == "accepted"


def test_production_owner_is_inert_even_with_exact_plan_claim_and_fake_events():
    registry, binding, _, job_id, _ = owner(characterization=False)
    assert registry.claim_for_characterization(job_id, binding=binding,
                                              claim_key="e" * 32).status == "execution_unavailable"
    assert registry.event_for_characterization(job_id, "e" * 32,
                                               WorkerEvent(1, 0, "submission_started")) == "execution_unavailable"
    assert registry.publication_for_characterization(
        job_id, "e" * 32, binding=binding, request_index=0,
        registered_count=1) == "execution_unavailable"
    assert registry.save_for_characterization(job_id, "e" * 32, binding=binding,
                                               outcome="saved") == "execution_unavailable"
    assert registry.snapshot(job_id)["state"] == "prepared_not_started"
    assert registry.snapshot(job_id)["execution_available"] is False
    assert not hasattr(registry, "start")
    with pytest.raises(TypeError):
        registry.prepare(binding, [], approved=True)


def test_one_active_job_per_session_and_independent_owners_and_origin():
    a, binding_a, requests_a, job_a, _ = owner()
    b, binding_b, requests_b, job_b, _ = owner()
    assert job_a != job_b and job_a not in {request.request_id for request in requests_a}
    assert a.prepare(binding_a, requests_a).status == "job_already_active"
    assert b.prepare(binding_b, requests_b).status == "job_already_active"
    assert b.snapshot(job_a)["state"] == "unavailable"
    assert a.cancel_before_submission(job_a) == "cancelled"
    assert a.prepare(binding_b, requests_a).status == "foreign_origin"
    assert a.prepare(binding_a, requests_a).status == "prepared_not_started"


@pytest.mark.parametrize("field,value", [
    ("plan_identity", "f" * 64), ("target_epoch", "f" * 32),
    ("activation_id", "f" * 32), ("pairing_generation", 2),
    ("session_id", "f" * 32), ("process_incarnation", "f" * 32),
])
def test_exact_origin_and_plan_required_before_fake_claim(field, value):
    registry, binding, _, job_id, _ = owner()
    assert registry.claim_for_characterization(
        job_id, binding=replace(binding, **{field: value}),
        claim_key="e" * 32).status == "claim_conflict"
    assert registry.snapshot(job_id)["revision"] == 1


def test_concurrent_one_shot_claim_persists_one_receipt_and_conflicts():
    registry, binding, _, job_id, _ = owner()
    barrier = threading.Barrier(8)

    def race(index):
        barrier.wait()
        return registry.claim_for_characterization(job_id, binding=binding, claim_key="e" * 32)

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(race, range(8)))
    assert [receipt.status for receipt in receipts].count("claimed") == 1
    assert [receipt.status for receipt in receipts].count("duplicate_claim") == 7
    assert len({receipt.claim_id for receipt in receipts}) == 1
    assert registry.snapshot(job_id)["revision"] == 2
    assert registry.claim_for_characterization(job_id, binding=binding,
                                              claim_key="f" * 32).status == "claim_conflict"


def test_ordered_events_revisions_duplicates_and_host_registration_before_completion():
    registry, binding, _, job_id, _ = owner(count=2)
    claim_id = claim(registry, binding, job_id)
    revisions = [registry.snapshot(job_id)["revision"]]
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(2, 0, "submitted")) == "event_out_of_order"
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(1, 1, "submission_started")) == "invalid_transition"
    for sequence, kind, count in [(1, "submission_started", 0), (2, "submitted", 0),
                                  (3, "outputs_ready", 2)]:
        assert registry.event_for_characterization(job_id, claim_id,
                                                   WorkerEvent(sequence, 0, kind, count)) == "accepted"
        revisions.append(registry.snapshot(job_id)["revision"])
    assert registry.snapshot(job_id)["state"] == "awaiting_result"
    assert registry.snapshot(job_id)["registered_count"] == 0
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(3, 0, "outputs_ready", 2)) == "duplicate_event"
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(3, 0, "outputs_ready", 1)) == "event_conflict"
    assert registry.snapshot(job_id)["revision"] == revisions[-1]
    publish(registry, binding, job_id, claim_id, count=2)
    outputs(registry, job_id, claim_id, index=1, sequence=4)
    publish(registry, binding, job_id, claim_id, index=1)
    assert registry.snapshot(job_id)["state"] == "completed"
    assert registry.snapshot(job_id)["registered_count"] == 3
    assert registry.snapshot(job_id)["save_state"] == "not_attempted"
    assert revisions == sorted(set(revisions))
    assert registry.publication_for_characterization(job_id, claim_id, binding=binding,
        request_index=1, registered_count=1) == "duplicate_publication"
    assert registry.publication_for_characterization(job_id, claim_id, binding=binding,
        request_index=1, registered_count=0) == "publication_conflict"
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(7, 1, "failed")) == "terminal"
    assert registry.claim_for_characterization(job_id, binding=binding,
                                              claim_key="e" * 32).status == "terminal"


@pytest.mark.parametrize("registered,expected", [(0, "failed"), (1, "partially_failed"),
                                                 (2, "completed")])
def test_partial_output_registration_truthful(registered, expected):
    registry, binding, _, job_id, _ = owner()
    claim_id = claim(registry, binding, job_id)
    outputs(registry, job_id, claim_id, count=2)
    publish(registry, binding, job_id, claim_id, count=registered)
    assert registry.snapshot(job_id)["state"] == expected


def test_partial_request_failure_and_save_failure_do_not_rollback_registration():
    registry, binding, _, job_id, _ = owner(count=2)
    claim_id = claim(registry, binding, job_id)
    outputs(registry, job_id, claim_id)
    publish(registry, binding, job_id, claim_id)
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(4, 1, "failed")) == "accepted"
    assert registry.snapshot(job_id)["state"] == "partially_failed"
    assert registry.save_for_characterization(job_id, claim_id, binding=binding,
                                               outcome="save_failed") == "accepted"
    view = registry.snapshot(job_id)
    assert view["registered_count"] == 1 and view["save_state"] == "save_failed"
    assert registry.save_for_characterization(job_id, claim_id, binding=binding,
                                               outcome="save_failed") == "duplicate_save"
    assert registry.save_for_characterization(job_id, claim_id, binding=binding,
                                               outcome="saved") == "save_conflict"


def test_ambiguous_submission_stops_unsent_requests_without_retry():
    registry, binding, _, job_id, _ = owner(count=2)
    claim_id = claim(registry, binding, job_id)
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(1, 0, "submission_started")) == "accepted"
    assert registry.snapshot(job_id)["state"] == "running"
    assert registry.cancel_before_submission(job_id) == "already_submitting"
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(2, 0, "submission_unknown")) == "accepted"
    assert registry.snapshot(job_id)["state"] == "submission_outcome_unknown"
    assert registry.snapshot(job_id)["requests"][1]["state"] == "unsent"
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(3, 1, "submission_started")) == "terminal"


@pytest.mark.parametrize("claimed", [False, True])
def test_pre_submit_cancellation_consumes_job_without_remote_action(claimed):
    registry, binding, _, job_id, _ = owner()
    if claimed:
        claim(registry, binding, job_id)
    assert registry.cancel_before_submission(job_id) == "cancelled"
    assert registry.cancel_before_submission(job_id) == "terminal"
    assert registry.claim_for_characterization(job_id, binding=binding,
                                              claim_key="e" * 32).status == "terminal"


@pytest.mark.parametrize("change", ["epoch", "activation", "plan", "pairing"])
def test_late_outputs_cannot_attach_after_origin_or_plan_drift(change):
    registry, binding, _, job_id, _ = owner()
    claim_id = claim(registry, binding, job_id)
    outputs(registry, job_id, claim_id)
    fresh = replace(binding, **{
        "epoch": {"target_epoch": "f" * 32},
        "activation": {"activation_id": "f" * 32},
        "plan": {"plan_identity": "f" * 64},
        "pairing": {"pairing_generation": 2},
    }[change])
    if change in {"epoch", "activation"}:
        registry.synchronize_target(fresh.target_epoch, fresh.activation_id)
    assert registry.publication_for_characterization(job_id, claim_id, binding=fresh,
        request_index=0, registered_count=1) == "stale_target"
    assert registry.snapshot(job_id)["state"] == "stale_target_outputs_not_registered"
    assert registry.snapshot(job_id)["output_count"] == 1
    assert registry.snapshot(job_id)["registered_count"] == 0
    registry.synchronize_target(binding.target_epoch, binding.activation_id)
    assert registry.publication_for_characterization(job_id, claim_id, binding=binding,
        request_index=0, registered_count=1) == "terminal"


def test_disconnect_has_no_cancellation_or_pairing_transfer_and_restart_is_unavailable():
    registry, binding, _, job_id, _ = owner()
    claim_id = claim(registry, binding, job_id)
    # Ordinary transport release does not call this owner; origin remains frozen.
    assert registry.snapshot(job_id)["state"] == "claimed"
    assert registry.claim_for_characterization(job_id, binding=replace(binding, pairing_generation=2),
                                              claim_key="e" * 32).status == "claim_conflict"
    other, _, _, _, _ = owner()
    assert other.snapshot(job_id)["state"] == "unavailable"
    registry.close()
    assert registry.snapshot(job_id)["state"] == "unavailable"
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(1, 0, "submission_started")) == "unavailable"


def test_expiry_retention_capacity_and_cleanup_are_bounded_and_not_renewed():
    registry, binding, requests, job_id, clock = owner()
    clock.now = PREPARED_TTL
    assert registry.snapshot(job_id)["state"] == "expired"
    clock.now += TERMINAL_TTL
    registry.cleanup()
    assert registry.snapshot(job_id)["state"] == "unavailable"
    job_id = registry.prepare(binding, requests).job_id
    claim(registry, binding, job_id)
    clock.now += ACTIVE_TTL - 1
    assert registry.claim_for_characterization(job_id, binding=binding,
                                              claim_key="e" * 32).status == "duplicate_claim"
    clock.now += 1
    assert registry.snapshot(job_id)["state"] == "unavailable"
    ids = []
    for _ in range(MAX_JOBS + 2):
        receipt = registry.prepare(binding, requests)
        ids.append(receipt.job_id)
        assert registry.cancel_before_submission(receipt.job_id) == "cancelled"
    assert len(registry._jobs) == MAX_JOBS
    assert registry.snapshot(ids[0])["state"] == "unavailable"


def test_detached_bounded_safe_snapshots_and_events_with_no_worker_streamlit_access(monkeypatch):
    # Reimporting the model while Streamlit/network owners are unavailable proves
    # fake-worker bookkeeping has no dependency on their context or services.
    imported = subprocess.run([sys.executable, "-c", "import sys; "
        "sys.modules.update({name: None for name in "
        "('streamlit', 'requests', 'core.comfyui', 'core.project')}); "
        "from ui.agent_generation_job import GenerationJobRegistry; "
        "assert GenerationJobRegistry().execution_available is False"],
        capture_output=True, text=True, check=False)
    assert imported.returncode == 0, imported.stderr
    with monkeypatch.context() as isolated:
        for name in ("streamlit", "requests", "core.comfyui", "core.project"):
            isolated.setitem(sys.modules, name, None)
        registry, binding, requests, job_id, _ = owner(count=MAX_REQUESTS)
        claim_id = claim(registry, binding, job_id)
        requests.clear()
        with ThreadPoolExecutor(max_workers=1) as worker:
            for index in range(MAX_REQUESTS):
                worker.submit(outputs, registry, job_id, claim_id, index, index * 3 + 1).result()
                publish(registry, binding, job_id, claim_id, index)
    snapshot = registry.snapshot(job_id)
    assert snapshot["request_count"] == MAX_REQUESTS
    assert len(snapshot["events"]) == MAX_EVENT_HISTORY and snapshot["events_truncated"]
    text = json.dumps(snapshot)
    for secret in (binding.session_id, binding.process_incarnation, binding.activation_id,
                   binding.plan_identity, claim_id, "gallery_generation:line", "workflow_json",
                   "current_project_path", "session_state"):
        assert secret not in text
    assert len(text) < 25000
    snapshot["requests"][0]["state"] = "spoof"
    snapshot["events"].clear()
    assert registry.snapshot(job_id)["requests"][0]["state"] == "completed"
    assert registry.event_for_characterization(job_id, claim_id,
                                               WorkerEvent(1, 0, "submission_started")) == "terminal"
    event = WorkerEvent(1, 0, "submitted")
    with pytest.raises(FrozenInstanceError):
        event.kind = "failed"


@pytest.mark.parametrize("event", [
    WorkerEvent(True, 0, "submitted"), WorkerEvent(1, True, "submitted"),
    WorkerEvent(1, 0, "outputs_ready", 17), WorkerEvent(1, 0, "outputs_ready", 0),
    WorkerEvent(1, 0, "failed", 1), WorkerEvent(1, 0, "registered"),
    {"sequence": 1, "request_index": 0, "kind": "submitted", "path": "secret"},
])
def test_untrusted_worker_payload_cannot_publish_or_disclose(event):
    registry, binding, _, job_id, _ = owner()
    claim_id = claim(registry, binding, job_id)
    assert registry.event_for_characterization(job_id, claim_id, event) == "invalid_event"
    assert registry.snapshot(job_id)["revision"] == 2


def test_request_limits_duplicate_runs_and_mutable_inputs_refused():
    registry, binding, requests, job_id, _ = owner()
    registry.cancel_before_submission(job_id)
    for invalid in ([], [requests[0]] * 101, [replace(requests[0], run_index=6)],
                    [replace(requests[0], run_index=True)],
                    [requests[0], replace(requests[0], request_id="another")],
                    [{"request_id": "x", "workflow_json": {}}]):
        assert registry.prepare(binding, invalid).status == "invalid_input"


@pytest.mark.parametrize("pairing", [True, 0, 2**64, "1"])
def test_pairing_shape_cannot_bypass_exact_claim_equality(pairing):
    registry, binding, _, job_id, _ = owner()
    malformed = replace(binding, pairing_generation=pairing)
    assert registry.claim_for_characterization(job_id, binding=malformed,
                                              claim_key="e" * 32).status == "invalid_input"
    assert registry.snapshot(job_id)["revision"] == 1


def test_concurrent_worker_duplicate_does_not_increase_revision_or_submit_twice():
    registry, binding, _, job_id, _ = owner()
    claim_id = claim(registry, binding, job_id)
    barrier = threading.Barrier(4)

    def race(index):
        barrier.wait()
        return registry.event_for_characterization(job_id, claim_id,
                                                   WorkerEvent(1, 0, "submission_started"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(race, range(4)))
    assert results.count("accepted") == 1 and results.count("duplicate_event") == 3
    assert registry.snapshot(job_id)["revision"] == 3
    assert registry.snapshot(job_id)["event_count"] == 1


def test_runtime_owns_target_switch_save_as_and_session_cleanup_without_project_mutation():
    from core.project import Project
    from ui.project_agent_session_pump import ProjectAgentSessionRuntime

    runtime = ProjectAgentSessionRuntime()
    project = Project(prompt_lines=[])
    original = copy.deepcopy(project)
    epoch = runtime.synchronize_target(project, "C:/host/one.json")
    binding = runtime.generation_jobs.host_binding(pairing_generation=1, plan_identity="c" * 64)
    request = [JobRequest("req", "line", 1, "d" * 64)]
    job = runtime.generation_jobs.prepare(binding, request).job_id
    assert runtime.generation_jobs.execution_available is False
    assert runtime.synchronize_target(project, "C:/host/one.json") == epoch
    assert runtime.generation_jobs.snapshot(job)["state"] == "prepared_not_started"
    assert runtime.synchronize_target(project, "C:/host/save-as.json") != epoch
    assert runtime.generation_jobs.snapshot(job)["state"] == "stale_target_outputs_not_registered"
    binding = runtime.generation_jobs.host_binding(pairing_generation=1, plan_identity="c" * 64)
    second = runtime.generation_jobs.prepare(binding, request).job_id
    runtime.synchronize_target(Project(prompt_lines=[]), "C:/host/save-as.json")
    assert runtime.generation_jobs.snapshot(second)["state"] == "stale_target_outputs_not_registered"
    assert project == original
    runtime.close()
    assert runtime.generation_jobs.snapshot(job)["state"] == "unavailable"
