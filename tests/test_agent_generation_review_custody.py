"""Generation custody and paired mailbox acceptance, without execution or UI."""
import copy
import threading
from unittest.mock import patch

import pytest
from agent_adapters.mcp_adapter import PromptGraphMCPAdapter
from core import agent_facade
from ui import project_capture_safety as capture
from ui.agent_generation_review_custody import AgentGenerationReviewCustodian
from ui.project_agent_request_bridge import dispatch_project_agent_request
from ui.project_agent_session_pump import ProjectAgentSessionRuntime, service_project_agent_session_request
from ui.project_agent_session_registry import ProjectAgentSessionRegistry
from test_agent_generation_preview import project, host


@pytest.fixture(autouse=True)
def safe_capture(monkeypatch):
    monkeypatch.setattr(capture._streamlit_config, "get_option", lambda key: False)


def setup():
    value = project()
    state = {"project": value, "current_project_path": "PRIVATE_PATH"}
    runtime = ProjectAgentSessionRuntime(_registry=ProjectAgentSessionRegistry())
    epoch = runtime.synchronize_target(value, state["current_project_path"])
    offer = runtime.arm_local_pairing().bootstrap
    route = runtime._registry.claim_pairing(offer.process_incarnation, offer.route_id, offer.capability).paired_route
    binding = [agent_facade.candidate_observation_handles.project_identity(value),
               runtime._registration.route_id, state["current_project_path"], route._pairing_generation, epoch]
    plan = agent_facade.preview_generation(value, "scene", host_context_provider=host, observation_binding=binding)
    args = {"scene_id": "scene", "run_count": 1, "expected_plan_id": plan["plan_id"]}
    return runtime, route, epoch, state, args


def send(runtime, route, epoch, state, args, request_id="r", provider=host):
    assert route.submit(epoch, {"request_id": request_id, "tool": "promptgraph_request_generation_review",
                                "arguments": args}).status == "accepted"
    token = capture.begin_project_capture_run(state)
    status = service_project_agent_session_request(runtime, state, token, generation_context_provider=provider)
    return status


def test_accept_detached_bounded_custody_ack_and_idempotent_retry():
    runtime, route, epoch, state, args = setup()
    before = copy.deepcopy(state)
    swap_before = runtime.inspect_review_custody()
    with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
        assert send(runtime, route, epoch, state, args) == "completed"
    review = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    assert review["state"] == "pending" and review["preview"]["job_submitted"] is False
    first = route.consume_reply(epoch).reply["result"]
    assert first["status"] == "queued_for_review" and first["expires_in_seconds"] == 900
    assert {k: v for k, v in state.items() if k != capture.PROJECT_CAPTURE_RUN_TOKEN_KEY} == before
    assert runtime.inspect_review_custody() == swap_before
    review["preview"]["illustrations"].clear()
    assert len(runtime.generation_review_custodian.inspect()["preview"]["illustrations"]) == 2
    assert send(runtime, route, epoch, state, args) == "completed"
    assert route.consume_reply(epoch).reply["result"] == first
    assert send(runtime, route, epoch, state, {**args, "run_count": 2}) == "completed"
    assert route.consume_reply(epoch).reply["result"]["reason"] == "request_id_conflict"
    assert send(runtime, route, epoch, state, args, "another") == "completed"
    assert route.consume_reply(epoch).reply["result"]["reason"] == "review_already_pending"
    assert not hasattr(runtime.generation_review_custodian, "_claim_pending_for_apply_locked")
    runtime.close()


@pytest.mark.parametrize("action", ["reject", "dismiss"])
def test_cancel_ack_and_scene_swap_isolation(action):
    runtime, route, epoch, state, args = setup()
    send(runtime, route, epoch, state, args)
    proposal = runtime.generation_review_custodian.inspect()["proposal_id"]
    # Another operation's cancellation must never retire this ACK.
    runtime.mailbox.cancel_review_custody(runtime.review_custodian)
    assert runtime.mailbox.state == "reply_ready"
    assert runtime.mailbox.resolve_review_proposal(runtime.generation_review_custodian, proposal, action) in {"rejected", "dismissed"}
    assert route.consume_reply(epoch).status == "review_cancelled"
    runtime.close()


def test_expiry_at_consume_and_target_save_as_and_close():
    runtime, route, epoch, state, args = setup()
    clock = [10.0]
    runtime.generation_review_custodian._clock = lambda: clock[0]
    # mailbox commit and custody must share the same monotonic domain.
    runtime.mailbox._clock = lambda: clock[0]
    send(runtime, route, epoch, state, args)
    clock[0] += 901
    assert route.consume_reply(epoch).status == "expired"
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "expired"
    assert send(runtime, route, epoch, state, args, "next") == "completed"
    runtime.synchronize_target(state["project"], "SAVE_AS_PATH")
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "stale"
    assert route.consume_reply(epoch).status == "stale_target"
    runtime.close()
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "session_unavailable"


@pytest.mark.parametrize("args", [{}, {"scene_id": "scene", "run_count": False, "expected_plan_id": "a"*64},
    {"scene_id": "scene", "run_count": 6, "expected_plan_id": "a"*64},
    {"scene_id": "scene", "run_count": 1, "expected_plan_id": "a"*64, "approved": True}])
def test_invalid_args_before_capture_and_standalone(args):
    def forbidden():
        raise AssertionError("capture")
    assert PromptGraphMCPAdapter(forbidden).call_tool("promptgraph_request_generation_review", args)["reason"] == "invalid_arguments"
    result = dispatch_project_agent_request({}, object(), {"request_id": "r", "tool": "promptgraph_request_generation_review", "arguments": args})
    assert result["result"]["reason"] == "invalid_arguments"


def test_standalone_valid_unavailable_and_stale_plan():
    runtime, route, epoch, state, args = setup()
    assert PromptGraphMCPAdapter(lambda: state["project"]).call_tool("promptgraph_request_generation_review", args)["reason"] == "host_review_unavailable"
    state["project"].prompt_lines[1].current_text = "changed"
    send(runtime, route, epoch, state, args)
    assert route.consume_reply(epoch).reply["result"]["reason"] == "stale_preview"
    assert runtime.generation_review_custodian.inspect()["state"] == "absent"
    runtime.close()


def test_positive_ack_cannot_be_consumed_before_custody_commit(monkeypatch):
    runtime, route, epoch, state, args = setup()
    entered, release, consumed = threading.Event(), threading.Event(), threading.Event()
    original = runtime.generation_review_custodian._commit_prepared_locked
    def blocked(*a, **kw):
        entered.set()
        assert release.wait(5)
        return original(*a, **kw)
    monkeypatch.setattr(runtime.generation_review_custodian, "_commit_prepared_locked", blocked)
    worker = threading.Thread(target=lambda: send(runtime, route, epoch, state, args))
    worker.start()
    assert entered.wait(5)
    result = []
    reader = threading.Thread(target=lambda: (result.append(runtime.mailbox.consume_reply(epoch)), consumed.set()))
    reader.start()
    assert not consumed.wait(.05)
    release.set()
    worker.join(5); reader.join(5)
    assert result[0].status == "completed" and runtime.generation_review_custodian.inspect()["state"] == "pending"
    runtime.close()


def test_cancel_during_preflight_aborts_preparation():
    runtime, route, epoch, state, args = setup()
    def cancelled(p, runs):
        runtime.disarm_launcher_rendezvous()
        return host(p, runs)
    send(runtime, route, epoch, state, args, provider=cancelled)
    reply = route.consume_reply(epoch)
    assert reply.status != "completed" or reply.reply["result"]["ok"] is False
    assert runtime.generation_review_custodian.inspect()["state"] == "absent"
    runtime.close()


def test_route_release_preserves_host_custody_cross_generation_replay_rejected():
    runtime, route, epoch, state, args = setup()
    send(runtime, route, epoch, state, args)
    route.consume_reply(epoch)
    assert route.release().status == "released"
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    offer = runtime.arm_local_pairing().bootstrap
    second = runtime._registry.claim_pairing(offer.process_incarnation, offer.route_id, offer.capability).paired_route
    send(runtime, second, epoch, state, args)
    assert second.consume_reply(epoch).reply["result"]["reason"] == "replay_not_accepted"
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "stale"
    runtime.close()


@pytest.mark.parametrize("failure", ["raise", "false", "deadline", "switch", "close"])
def test_commit_failure_never_leaves_positive_ack_or_pending_custody(monkeypatch, failure):
    runtime, route, epoch, state, args = setup()
    original = runtime.generation_review_custodian._commit_prepared_locked
    def fail(*a, **kw):
        if failure == "raise":
            raise RuntimeError("private")
        if failure == "false":
            return False
        return original(*a, **kw)
    monkeypatch.setattr(runtime.generation_review_custodian, "_commit_prepared_locked", fail)
    calls = 0
    def provider(p, runs):
        nonlocal calls
        calls += 1
        if calls == 3:
            if failure == "deadline":
                runtime.mailbox._deadline = 0
            elif failure == "switch":
                state["project"] = project()
            elif failure == "close":
                runtime.close()
        return host(p, runs)
    send(runtime, route, epoch, state, args, provider=provider)
    outcome = runtime.mailbox.consume_reply(epoch)
    assert outcome.status != "completed" or outcome.reply["result"]["ok"] is False
    assert runtime.generation_review_custodian.inspect().get("state") != "pending"
    runtime.close()


@pytest.mark.parametrize("invalid_workflow", [False, True])
def test_retry_revalidates_configuration_and_workflow(invalid_workflow):
    runtime, route, epoch, state, args = setup()
    send(runtime, route, epoch, state, args)
    route.consume_reply(epoch)
    def changed(p, runs):
        context = host(p, runs)
        context["generation_options"]["endpoint"] = "new"
        if invalid_workflow:
            original = context["request_builder"]
            def build(item, index):
                record = original(item, index)
                record["workflow_json"] = {}
                return record
            context["request_builder"] = build
        return context
    send(runtime, route, epoch, state, args, provider=changed)
    assert route.consume_reply(epoch).reply["result"]["reason"] == ("invalid_preview" if invalid_workflow else "stale_preview")
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "stale"
    runtime.close()


def test_envelope_limits_unknown_fields_and_prepared_expiry():
    clock = [0.0]
    custodian = AgentGenerationReviewCustodian(clock=lambda: clock[0])
    custodian.synchronize_target_epoch("epoch")
    plan = agent_facade.preview_generation(project(), "scene", host_context_provider=host)
    args = {"scene_id": "scene", "run_count": 1, "expected_plan_id": plan["plan_id"]}
    bad = {**plan, "workflow_json": {"private": "secret"}}
    assert custodian.prepare("bad", 1, "epoch", args, 1, bad).status == "invalid_preview"
    oversized = {**plan, "private": "x" * (8 * 1024 * 1024 + 1)}
    assert custodian.prepare("big", 1, "epoch", args, 1, oversized).status == "proposal_too_large"
    prepared = custodian.prepare("r", 1, "epoch", args, 1, plan)
    assert prepared.status == "prepared"
    assert custodian.inspect_for_human_review() == {"contract_version": "promptgraph.agent-generation-review.v1", "state": "prepared"}
    clock[0] = 121
    assert custodian.inspect()["state"] == "absent"
    assert custodian.check_request("r", 1, "epoch", args).status == "review_unavailable"


def test_mailbox_session_loss_closes_generation_custody():
    runtime, route, epoch, state, args = setup()
    send(runtime, route, epoch, state, args)
    route.consume_reply(epoch)
    runtime.mailbox.close()
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "session_unavailable"
    runtime.close()
