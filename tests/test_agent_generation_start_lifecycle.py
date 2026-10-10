"""No-I/O characterization of the private C2A host authorization boundary."""
import copy
import json
from dataclasses import FrozenInstanceError, replace
import threading
from unittest.mock import patch
import pytest
from core import agent_facade
from ui.agent_generation_job import GenerationJobRegistry
from ui.agent_generation_start_lifecycle import (
    authorize_generation_start, capture_human_start_action, certificate_for_characterization,
    _manifest, MAX_FIELD_CHARS)
from test_agent_generation_review_ui import host as _host, safe_capture
from test_agent_generation_review_custody import setup, send
from test_agent_generation_preview import line


def host(project, runs):
    context = _host(project, runs)
    # Exact destination field names supplied by app._prepare_agent_generation_context.
    context["generation_options"]["comfyui_endpoint"] = context["generation_options"].pop("endpoint")
    context["generation_options"]["output_directory"] = "private_output"
    return context


def queued(count=2, consume=False, with_swap=False):
    runtime, route, epoch, state, args = setup()
    project = state["project"]
    project.prompt_lines = [line("scene", "Scene", line_type="separator")]
    project.prompt_lines += [line(f"illustration-{index:03}", f"prompt {index}",
                            negative_prompt=f"negative {index}") for index in range(count)]
    project.prompt_lines += [line("scratch", line_type="workbench"), line("deleted", deleted=True)]
    if with_swap:
        project.module_library = {"source": {"body": "red"}, "target": {"body": "gold"}}
        for item in project.prompt_lines[1:count+1]:
            item.current_text, item.tokens = "red", ["red"]
    binding = [agent_facade.candidate_observation_handles.project_identity(project),
               runtime._registration.route_id, state["current_project_path"], route._pairing_generation, epoch]
    args["expected_plan_id"] = agent_facade.preview_generation(project, "scene", host_context_provider=host,
                                                    observation_binding=binding)["plan_id"]
    assert send(runtime, route, epoch, state, args, provider=host) == "completed"
    if consume:
        route.consume_reply(epoch)
    return runtime, route, epoch, state, args


def prepared(characterization=True):
    runtime, route, epoch, state, args = queued(2)
    if characterization:
        runtime.generation_jobs = GenerationJobRegistry(characterization=True)
        runtime.synchronize_target(state["project"], state["current_project_path"])
    record = runtime.generation_review_custodian.inspect()
    action = capture_human_start_action(runtime, record["proposal_id"], record["plan_id"])
    binding = [agent_facade.candidate_observation_handles.project_identity(state["project"]),
               runtime._registration.route_id, state["current_project_path"], route._pairing_generation, epoch]
    preflight = {}
    preview = agent_facade.preview_generation(state["project"], "scene", host_context_provider=host,
                                               observation_binding=binding, _host_preflight=preflight)
    certificate = certificate_for_characterization(preview, preflight, destination="PRIVATE_ENDPOINT",
                                                    output_location="private_output", seed_policy="frozen_fixture")
    return runtime, state, action, certificate, preview, preflight


def authorize(runtime, state, action, certificate, accept=lambda *a: "accepted", provider=host):
    return authorize_generation_start(state, runtime, provider, action,
                    certificate=certificate, acceptance_for_characterization=accept)


def test_production_current_uncertified_review_never_claims_or_consumes():
    runtime, state, action, certificate, _, _ = prepared(False)
    result = authorize(runtime, state, action, certificate, lambda *a: pytest.fail("executor"))
    assert result.status == "executable_review_required" and result.job_id is None
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    assert not runtime.generation_jobs._jobs
    runtime.close()


def test_exact_fake_authorization_private_immutable_manifest_and_no_mutation():
    runtime, state, action, certificate, preview, preflight = prepared()
    original = copy.deepcopy(state)
    swap = runtime.inspect_review_custody()
    with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
        result = authorize(runtime, state, action, certificate)
    assert result.status == "characterized_acceptance"
    assert state == original and runtime.inspect_review_custody() == swap
    assert [r.illustration_id for r in result.manifest.requests] == ["illustration-000", "illustration-001"]
    with pytest.raises(FrozenInstanceError):
        result.manifest.destination = "other"
    assert type(result.manifest.requests[0].workflow_json) is bytes
    options = json.loads(result.manifest.parameters_json)
    assert result.manifest.destination == options["comfyui_endpoint"]
    assert result.manifest.output_location == options["output_directory"]
    assert "endpoint" not in options and "output_location" not in preflight
    preflight["workflow_plan"].clear()
    assert result.manifest.requests[0].workflow_json
    snapshot = str(runtime.generation_jobs.snapshot(result.job_id))
    assert all(secret not in snapshot for secret in ["private_endpoint", "private_output", "workflow_json", action.nonce])
    assert authorize(runtime, state, action, certificate).status != "characterized_acceptance"
    runtime.close()


@pytest.mark.parametrize("change", ["prompt", "module", "scene", "config", "output_directory", "workflow", "save_as", "switch", "close", "expiry"])
def test_drift_or_closed_origin_refuses_before_claim(change):
    runtime, state, action, certificate, _, _ = prepared()
    provider = host
    if change == "prompt":
        state["project"].prompt_lines[1].current_text = "changed"
    elif change == "module":
        state["project"].module_library["new"] = {"body": "changed"}
    elif change == "scene":
        state["project"].prompt_lines[0].id = "other"
    elif change == "save_as":
        state["current_project_path"] = "NEW_PATH"
    elif change == "switch":
        state["project"] = copy.deepcopy(state["project"])
    elif change == "close":
        runtime.close()
    elif change == "expiry":
        runtime.generation_review_custodian._record.expires_at = 0
    else:
        def provider(p, runs):
            context = host(p, runs)
            if change == "config":
                context["generation_options"]["comfyui_endpoint"] = "changed"
            elif change == "output_directory":
                context["generation_options"]["output_directory"] = "changed"
            else:
                original = context["request_builder"]
                def build(line, index):
                    item = original(line, index)
                    item["workflow_json"]["2"]["inputs"]["filename_prefix"] = "changed"
                    return item
                context["request_builder"] = build
            return context
    assert authorize(runtime, state, action, certificate, provider=provider).status != "characterized_acceptance"
    assert not runtime.generation_jobs._jobs
    runtime.close()


@pytest.mark.parametrize("failure", ["certificate", "executor", "preflight"])
def test_failed_preparation_preserves_pending_and_allows_exact_recovery(failure):
    runtime, state, action, certificate, _, _ = prepared()
    provider = host
    accept = lambda *a: "accepted"
    bad = certificate
    if failure == "certificate":
        bad = replace(certificate, executable_identity="0" * 64)
    elif failure == "executor":
        accept = None
    else:
        def provider(*a):
            raise ValueError("private")
    assert authorize(runtime, state, action, bad, accept, provider).status != "characterized_acceptance"
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    assert not runtime.generation_jobs._jobs
    assert authorize(runtime, state, action, certificate).status == "characterized_acceptance"
    runtime.close()


@pytest.mark.parametrize("outcome,terminal", [("rejected", "failed"), ("unknown", "submission_outcome_unknown"),
                                             (None, "submission_outcome_unknown")])
def test_handoff_failure_consumes_once_no_retry_or_runnable_manifest(outcome, terminal):
    runtime, state, action, certificate, _, _ = prepared()
    calls = []
    def acceptance(receipt, manifest):
        calls.append(receipt)
        if outcome is None:
            raise RuntimeError("private lost response")
        return outcome
    result = authorize(runtime, state, action, certificate, acceptance)
    assert result.manifest is None and result.claim_id is None
    assert runtime.generation_jobs.snapshot(result.job_id)["state"] == terminal
    assert authorize(runtime, state, action, certificate, acceptance).status != "characterized_acceptance"
    assert len(calls) == 1
    runtime.close()


def test_concurrent_double_action_only_one_claim_and_no_locks_during_acceptance():
    runtime, state, action, certificate, _, _ = prepared()
    barrier = threading.Barrier(2)
    calls, results = [], []
    def provider(p, runs):
        # Barrier only on each thread's first provider read, during preflight.
        if not getattr(local, "seen", False):
            local.seen = True
            barrier.wait(timeout=5)
        return host(p, runs)
    local = threading.local()
    def accept(receipt, manifest):
        assert runtime._publication_gate.acquire(blocking=False)
        runtime._publication_gate.release()
        assert runtime.mailbox._lock.acquire(blocking=False)
        runtime.mailbox._lock.release()
        calls.append(receipt)
        return "accepted"
    def run():
        results.append(authorize(runtime, state, action, certificate, accept, provider))
    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers: worker.start()
    for worker in workers:
        worker.join(timeout=10)
        assert not worker.is_alive()
    assert len(calls) == 1 and sum(r.status == "characterized_acceptance" for r in results) == 1
    assert len(runtime.generation_jobs._jobs) == 1
    runtime.close()


def test_wrong_proposal_foreign_session_and_busy_job_fail_closed():
    runtime, state, action, certificate, _, _ = prepared()
    assert authorize(runtime, state, replace(action, proposal_id="wrong"), certificate).status == "identity_mismatch"
    assert authorize(runtime, state, replace(action, session_incarnation="foreign"), certificate).status == "invalid_human_action"
    binding = runtime.generation_jobs.host_binding(pairing_generation=1, plan_identity="0" * 64)
    from ui.agent_generation_job import JobRequest
    runtime.generation_jobs.prepare(binding, [JobRequest("prior", "old", 1, "0" * 64)])
    assert authorize(runtime, state, action, certificate).status == "job_already_active"
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    runtime.close()


def test_manifest_bounds_and_matching_plan_does_not_certify_changed_executable():
    runtime, state, action, certificate, preview, preflight = prepared()
    changed = copy.deepcopy(preflight)
    changed["workflow_plan"]["illustration-000"]["workflow_json"]["2"]["inputs"]["filename_prefix"] = "evil"
    with pytest.raises(ValueError): _manifest(action, preview, changed, certificate)
    with pytest.raises(ValueError):
        _manifest(action, preview, preflight, replace(certificate, output_location="x" * (MAX_FIELD_CHARS + 1)))
    runtime.close()

@pytest.mark.parametrize("boundary", ["workflow", "aggregate", "field"])
def test_manifest_size_limits_fail_before_claim(monkeypatch, boundary):
    import ui.agent_generation_start_lifecycle as owner
    runtime, state, action, certificate, _, _ = prepared()
    monkeypatch.setattr(owner, {"workflow": "MAX_WORKFLOW_BYTES", "aggregate": "MAX_MANIFEST_BYTES",
                              "field": "MAX_FIELD_CHARS"}[boundary], 1)
    assert authorize(runtime, state, action, certificate).status == "preparation_failed"
    assert not runtime.generation_jobs._jobs
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    runtime.close()


def test_runtime_close_during_handoff_never_returns_runnable_manifest():
    runtime, state, action, certificate, _, _ = prepared()
    def close(receipt, manifest):
        assert manifest.job_id == receipt.job_id and manifest.claim_id == receipt.claim_id
        runtime.close()
        return "accepted"
    result = authorize(runtime, state, action, certificate, close)
    assert result.status == "handoff_invalidated" and result.manifest is None


def test_human_claim_does_not_retire_other_custodian_ack():
    from ui import project_capture_safety as capture
    from ui.project_agent_session_pump import service_project_agent_session_request
    runtime, route, epoch, state, args = queued(consume=True, with_swap=True)
    runtime.generation_jobs = GenerationJobRegistry(characterization=True)
    runtime.synchronize_target(state["project"], state["current_project_path"])
    intent = {"scene_id": "scene", "source_module_name": "source", "target_module_name": "target", "match_mode": "strict"}
    swap_preview = agent_facade.preview_scene_module_swap(state["project"], intent)
    assert route.submit(epoch, {"request_id": "swap", "tool": "promptgraph_request_scene_module_swap_review",
                 "arguments": {**intent, "expected_plan_id": swap_preview["plan_id"]}}).status == "accepted"
    token = capture.begin_project_capture_run(state)
    assert service_project_agent_session_request(runtime, state, token, generation_context_provider=host) == "completed"
    swap_before = runtime.inspect_review_custody()
    record = runtime.generation_review_custodian.inspect()
    action = capture_human_start_action(runtime, record["proposal_id"], record["plan_id"])
    preflight = {}
    binding = [agent_facade.candidate_observation_handles.project_identity(state["project"]),
               runtime._registration.route_id, state["current_project_path"], route._pairing_generation, epoch]
    preview = agent_facade.preview_generation(state["project"], "scene", host_context_provider=host,
                                    observation_binding=binding, _host_preflight=preflight)
    certificate = certificate_for_characterization(preview, preflight, destination="PRIVATE_ENDPOINT",
                                               output_location="private_output", seed_policy="frozen_fixture")
    assert authorize(runtime, state, action, certificate).status == "characterized_acceptance"
    assert runtime.inspect_review_custody() == swap_before
    assert route.consume_reply(epoch).reply["result"]["status"] == "queued_for_review"
    runtime.close()
