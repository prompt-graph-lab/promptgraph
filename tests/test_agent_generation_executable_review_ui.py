"""C2B-2 exact human acknowledgment, lifecycle fences and real Streamlit UI."""
import ast
import copy
from dataclasses import replace
import json
from pathlib import Path
import threading
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from core import agent_facade
from core.generation_executable_manifest import encode
from ui.agent_generation_executable_confirmation import (
    prepare_session_executable_review as prepare,
    inspect_session_executable_review as inspect,
    confirm_session_execution_details as confirm,
)
from ui.agent_generation_review_lifecycle import build_generation_review, resolve_generation_review
from ui.agent_generation_start_lifecycle import authorize_generation_start, capture_human_start_action
from ui.agent_generation_review_panel import GENERATION_REVIEW_ACTIVE_KEY
from ui import project_capture_safety as capture
from test_agent_generation_executable_manifest import host_for
from test_agent_generation_preview import line
from test_agent_generation_review_custody import setup, send


@pytest.fixture(autouse=True)
def safe_capture(monkeypatch):
    original = capture._streamlit_config.get_option
    monkeypatch.setattr(capture._streamlit_config, "get_option",
        lambda key: False if key == "runner.fastReruns" else original(key))


def queued(count=2, runs=1, provider=None, *, prompt_text=None, with_swap=False):
    runtime, route, epoch, state, args = setup()
    value = state["project"]
    value.prompt_lines = [line("scene", "Scene", line_type="separator")]
    value.prompt_lines += [line(f"illustration-{index:03}", prompt_text or f"prompt {index}", negative_prompt=f"negative {index}")
                           for index in range(count)]
    if with_swap:
        value.module_library = {"source": {"body": "red"}, "target": {"body": "gold"}}
        for item in value.prompt_lines[1:]:
            item.current_text, item.tokens = "red", ["red"]
    provider = provider or host_for()
    args["run_count"] = runs
    binding = [agent_facade.candidate_observation_handles.project_identity(value), runtime._registration.route_id,
               state["current_project_path"], route._pairing_generation, epoch]
    args["expected_plan_id"] = agent_facade.preview_generation(value, "scene", run_count=runs,
        host_context_provider=provider, observation_binding=binding)["plan_id"]
    assert send(runtime, route, epoch, state, args, provider=provider) == "completed"
    route.consume_reply(epoch)
    return runtime, route, epoch, state, args, provider


def prepared(count=2, runs=1, provider=None):
    values = queued(count, runs, provider)
    runtime, route, epoch, state, args, provider = values
    record = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    assert prepare(state, runtime, provider, record["proposal_id"], record["plan_id"], random_u64=lambda: 0) in {
        "certified", "uncertifiable"}
    return values


def identity(runtime):
    record = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    return record["proposal_id"], record["plan_id"]


def test_prepare_display_confirm_has_no_execution_or_project_side_effects():
    runtime, route, epoch, state, args, provider = queued(runs=3)
    before = copy.deepcopy(state)
    swap = runtime.inspect_review_custody()
    pending = runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian)
    with patch("urllib.request.urlopen", side_effect=AssertionError("submission")), \
         patch("threading.Thread.start", side_effect=AssertionError("worker")), \
         patch("builtins.open", side_effect=AssertionError("output")), \
         patch("core.comfy_prompt_request.prepare_prompt_request", side_effect=AssertionError("rerandomization")):
        assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: 0) == "certified"
        view, held = inspect(state, runtime, provider)
        assert view["state"] == "certified" and not view["human_confirmed"]
        assert confirm(state, runtime, provider, held) == "confirmed"
        assert inspect(state, runtime, provider)[0]["human_confirmed"]
        assert confirm(state, runtime, provider, held) == "already_confirmed"
        action = capture_human_start_action(runtime, *identity(runtime))
        assert authorize_generation_start(state, runtime, provider, action,
            certificate=runtime._executable_confirmation).status == "executable_review_required"
    assert not runtime.generation_jobs._jobs
    assert not view["execution_available"] and not view["job_submitted"]
    assert state == before and runtime.inspect_review_custody() == swap
    assert runtime.mailbox.inspect_review_custody(runtime.generation_review_custodian) == pending
    assert all(term not in json.dumps(view) for term in (
        "PRIVATE", "workflow_json", "node_id", "request_id", "settings", "comfyui_endpoint"))
    seeds = [seed["value"] for row in view["requests"] for seed in row["seeds"]]
    assert seeds == list(range(12))
    assert runtime._executable_confirmation.manifest_identity == held.review.manifest.manifest_identity
    assert runtime._executable_confirmation.projection_json == held.review.projection_json
    runtime.close()


def test_explicit_refresh_invalidates_before_randomization_and_rejects_old_callbacks():
    runtime, route, epoch, state, args, provider = prepared()
    old_view, old = inspect(state, runtime, provider)
    assert confirm(state, runtime, provider, old) == "confirmed"
    calls = []
    def random():
        assert runtime._executable_review is None and runtime._executable_confirmation is None
        calls.append(1)
        return 100
    assert prepare(state, runtime, provider, *identity(runtime), refresh=True,
        expected_review=old, random_u64=random) == "certified"
    view, fresh = inspect(state, runtime, provider)
    assert fresh is not old and calls and view["requests"] != old_view["requests"]
    assert not view["human_confirmed"]
    assert confirm(state, runtime, provider, old) == "identity_mismatch"
    assert prepare(state, runtime, provider, *identity(runtime), refresh=True, expected_review=old) == "identity_mismatch"
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: pytest.fail("reroll")) == "already_prepared"
    assert inspect(state, runtime, provider)[0] == view
    runtime.close()


@pytest.mark.parametrize("drift", ["scene", "prompt", "module", "workflow", "config", "switch", "save_as", "pairing", "expiry", "close", "reject", "dismiss"])
def test_exact_confirmation_invalidation(drift):
    runtime, route, epoch, state, args, provider = prepared()
    view, held = inspect(state, runtime, provider)
    assert confirm(state, runtime, provider, held) == "confirmed"
    if drift == "scene": state["project"].prompt_lines[0].current_text = "changed scene"
    elif drift == "prompt": state["project"].prompt_lines[1].current_text = "changed prompt"
    elif drift == "module": state["project"].module_library["new"] = {"body": "changed"}
    elif drift == "workflow": provider = host_for(change=lambda w: w["s"]["inputs"].update(steps=25))
    elif drift == "config": provider = host_for({"agent_generation_seed_policy": "preserve_u64"})
    elif drift == "switch": state["project"] = copy.deepcopy(state["project"])
    elif drift == "save_as": state["current_project_path"] = "SAVE_AS_PATH"
    elif drift == "pairing": runtime.generation_review_custodian._record.pairing_generation += 1
    elif drift == "expiry": runtime.generation_review_custodian._record.expires_at = 0
    elif drift == "close": runtime.close()
    else:
        assert resolve_generation_review(state, runtime, provider, *identity(runtime), drift) in {"rejected", "dismissed"}
    assert inspect(state, runtime, provider)[0]["state"] != "certified"
    assert runtime._executable_review is None and runtime._executable_confirmation is None
    assert confirm(state, runtime, provider, held) != "confirmed"
    assert not runtime.generation_jobs._jobs
    runtime.close()


def test_proposal_replacement_and_session_incarnation_refuse_old_callback():
    runtime, route, epoch, state, args, provider = prepared()
    old = runtime._executable_review
    assert resolve_generation_review(state, runtime, provider, *identity(runtime), "dismiss") == "dismissed"
    assert send(runtime, route, epoch, state, args, request_id="replacement", provider=provider) == "completed"
    route.consume_reply(epoch)
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: 1) == "certified"
    assert confirm(state, runtime, provider, old) == "identity_mismatch"
    held = runtime._executable_review
    assert confirm(state, runtime, provider, replace(held, session_incarnation="other")) == "identity_mismatch"
    runtime.close()


def test_temporary_read_failure_preserves_carrier_and_confirmation_without_new_action():
    runtime, route, epoch, state, args, provider = prepared()
    held = runtime._executable_review
    def unavailable(*args):
        raise FileNotFoundError("PRIVATE_PATH")
    assert confirm(state, runtime, unavailable, held) == "computation_failure"
    assert runtime._executable_confirmation is None and runtime._executable_review is held
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    assert confirm(state, runtime, provider, held) == "confirmed"
    acknowledgment = runtime._executable_confirmation
    assert inspect(state, runtime, unavailable)[0]["state"] == "computation_failure"
    assert runtime._executable_confirmation is acknowledgment
    assert inspect(state, runtime, provider)[0]["human_confirmed"]
    runtime.close()


@pytest.mark.parametrize("tamper", ["projection", "manifest", "client_values"])
def test_complete_manifest_and_display_comparison_refuses_tampering(tamper):
    runtime, route, epoch, state, args, provider = prepared()
    held = runtime._executable_review
    if tamper == "projection":
        value = json.loads(held.review.projection_json)
        value["requests"][0]["seeds"][0]["value"] = 123
        held = replace(held, review=replace(held.review, projection_json=encode(value)))
        runtime._executable_review = held
    elif tamper == "manifest":
        manifest = held.review.manifest
        request = replace(manifest.requests[0], workflow_json=b"{}")
        held = replace(held, review=replace(held.review, manifest=replace(manifest, requests=(request, *manifest.requests[1:]))))
        runtime._executable_review = held
    else:
        state["human_confirmed"] = True
        state["agent_generation_executable_confirm"] = held.review.manifest.manifest_identity
        assert runtime._executable_confirmation is None
        assert inspect(state, runtime, provider)[0]["human_confirmed"] is False
        assert confirm(state, runtime, provider, held.review.projection_json) == "invalid_review"
        runtime.close()
        return
    assert confirm(state, runtime, provider, held) == "invalid_review"
    assert runtime._executable_review is None and runtime._executable_confirmation is None
    runtime.close()


def test_concurrent_confirmation_records_exactly_one_acknowledgment():
    runtime, route, epoch, state, args, provider = prepared()
    held = runtime._executable_review
    barrier = threading.Barrier(2)
    original = inspect
    def simultaneous(*args):
        result = original(*args)
        barrier.wait(timeout=10)
        return result
    results = []
    with patch("ui.agent_generation_executable_confirmation.inspect_session_executable_review", side_effect=simultaneous):
        workers = [threading.Thread(target=lambda: results.append(confirm(state, runtime, provider, held))) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(timeout=15)
    assert sorted(results) == ["already_confirmed", "confirmed"]
    assert not runtime.generation_jobs._jobs and runtime.generation_review_custodian.inspect()["state"] == "pending"
    runtime.close()


def test_refresh_or_close_during_confirmation_cannot_publish():
    for transition in ("refresh", "close"):
        runtime, route, epoch, state, args, provider = prepared()
        held = runtime._executable_review
        original = inspect
        def interrupt(*values):
            result = original(*values)
            if transition == "close": runtime.close()
            else: prepare(state, runtime, provider, *identity(runtime), refresh=True, expected_review=held, random_u64=lambda: 9)
            return result
        with patch("ui.agent_generation_executable_confirmation.inspect_session_executable_review", side_effect=interrupt):
            assert confirm(state, runtime, provider, held) != "confirmed"
        assert runtime._executable_confirmation is None
        runtime.close()


def test_preparation_and_confirmation_computation_releases_all_owner_locks():
    runtime, route, epoch, state, args, provider = queued()
    def unlocked():
        route_record = runtime._registry._record_for_registration(runtime._registration)
        for lock in (runtime._publication_gate, route_record.operation_lock, runtime.mailbox._lock, runtime.generation_review_custodian._lock):
            assert lock.acquire(blocking=False)
            lock.release()
    def random():
        unlocked()
        assert prepare(state, runtime, provider, *identity(runtime)) == "preparing"
        return 0
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=random) == "certified"
    def checking(p, runs):
        unlocked()
        return provider(p, runs)
    assert confirm(state, runtime, checking, runtime._executable_review) == "confirmed"
    runtime.close()


def test_real_pairing_replacement_between_inspection_and_confirmation_fails_closed():
    runtime, route, epoch, state, args, provider = prepared()
    held = runtime._executable_review
    original = inspect
    def replace_pairing(*values):
        result = original(*values)
        assert route.release().status == "released"
        offer = runtime.arm_local_pairing().bootstrap
        assert runtime._registry.claim_pairing(offer.process_incarnation, offer.route_id, offer.capability).status == "paired"
        return result
    with patch("ui.agent_generation_executable_confirmation.inspect_session_executable_review", side_effect=replace_pairing):
        assert confirm(state, runtime, provider, held) == "stale"
    assert runtime._executable_review is None and runtime._executable_confirmation is None
    runtime.close()


def test_temporary_pairing_read_failure_is_unavailable_without_confirmation_or_dismissal():
    runtime, route, epoch, state, args, provider = prepared()
    held = runtime._executable_review
    with patch.object(type(runtime._registration), "inspect_pairing_generation", side_effect=OSError("PRIVATE")):
        assert confirm(state, runtime, provider, held) == "verification_unavailable"
    assert runtime._executable_review is held and runtime._executable_confirmation is None
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    assert confirm(state, runtime, provider, held) == "confirmed"
    runtime.close()


def test_failed_refresh_cannot_restore_old_confirmation_and_conflicting_ack_is_rejected():
    runtime, route, epoch, state, args, provider = prepared()
    held = runtime._executable_review
    assert confirm(state, runtime, provider, held) == "confirmed"
    runtime._executable_confirmation = replace(runtime._executable_confirmation, manifest_identity="different")
    assert confirm(state, runtime, provider, held) == "conflicting_confirmation"
    assert not inspect(state, runtime, provider)[0]["human_confirmed"]
    def unavailable(*args): raise FileNotFoundError("PRIVATE")
    assert prepare(state, runtime, unavailable, *identity(runtime), refresh=True, expected_review=held) == "computation_failure"
    assert runtime._executable_review is None and runtime._executable_confirmation is None
    assert confirm(state, runtime, provider, held) == "identity_mismatch"
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    runtime.close()


def test_generation_confirmation_preserves_independent_scene_module_swap_custody_and_ack():
    from ui.project_agent_session_pump import service_project_agent_session_request
    runtime, route, epoch, state, args, provider = queued(with_swap=True)
    intent = {"scene_id": "scene", "source_module_name": "source", "target_module_name": "target", "match_mode": "strict"}
    preview = agent_facade.preview_scene_module_swap(state["project"], intent)
    assert preview["valid"] and preview["changed_count"] == 2
    assert route.submit(epoch, {"request_id": "swap", "tool": "promptgraph_request_scene_module_swap_review",
        "arguments": {**intent, "expected_plan_id": preview["plan_id"]}}).status == "accepted"
    token = capture.begin_project_capture_run(state)
    assert service_project_agent_session_request(runtime, state, token, generation_context_provider=provider) == "completed"
    before = runtime.inspect_review_custody()
    assert before["state"] == "pending"
    assert prepare(state, runtime, provider, *identity(runtime), random_u64=lambda: 0) == "certified"
    assert confirm(state, runtime, provider, runtime._executable_review) == "confirmed"
    assert runtime.inspect_review_custody() == before
    assert resolve_generation_review(state, runtime, provider, *identity(runtime), "reject") == "rejected"
    assert runtime.inspect_review_custody() == before
    assert route.consume_reply(epoch).reply["result"]["status"] == "queued_for_review"
    runtime.close()


APP = '''
import streamlit as st
from ui.agent_generation_review_panel import render_generation_review_panel, render_generation_review_navigation, GENERATION_REVIEW_ACTIVE_KEY
from ui.agent_scene_module_swap_review_panel import render_agent_review_navigation, AGENT_REVIEW_ACTIVE_KEY
from ui.project_capture_safety import begin_project_capture_run
from ui.project_agent_session_pump import service_project_agent_session_request
runtime = st.session_state.runtime
provider = st.session_state.provider
token = begin_project_capture_run(st.session_state)
service_project_agent_session_request(runtime, st.session_state, token, generation_context_provider=provider)
render_agent_review_navigation(runtime, on_activate=lambda: st.session_state.__setitem__(GENERATION_REVIEW_ACTIVE_KEY, False))
render_generation_review_navigation(runtime, on_activate=lambda: st.session_state.__setitem__(AGENT_REVIEW_ACTIVE_KEY, False))
if st.session_state.get(GENERATION_REVIEW_ACTIVE_KEY, False):
    render_generation_review_panel(runtime, provider)
else:
    st.title("Project workspace")
'''


def app_for(state, runtime, provider, script=APP):
    app = AppTest.from_string(script, default_timeout=30)
    app.session_state["runtime"] = runtime
    app.session_state["provider"] = provider
    for key, value in state.items(): app.session_state[key] = value
    app.session_state[GENERATION_REVIEW_ACTIVE_KEY] = True
    return app


@pytest.mark.parametrize("count", [1, 20, 21, 100])
def test_apptest_complete_request_pagination_prepare_confirm_refresh(count):
    runtime, route, epoch, state, args, provider = queued(count)
    app = app_for(state, runtime, provider)
    with patch("urllib.request.urlopen", side_effect=AssertionError("submission")):
        app.run()
        next(b for b in app.button if b.label == "Prepare executable review").click().run()
        assert not app.exception
        view, held = inspect(state, runtime, provider)
        assert len(view["requests"]) == count and len(view["targets"]) == count
        labels = []
        for page in range((count + 19)//20):
            executable = [e for e in app.expander if e.label.startswith("Executable request ")]
            assert len(executable) == min(20, count - page*20)
            labels.extend(e.label for e in executable)
            if page < (count - 1)//20:
                next(b for b in app.button if b.label == "Next executable requests").click().run()
        assert [label.split(" · ")[1] for label in labels] == [f"illustration-{i:03}" for i in range(count)]
        next(b for b in app.button if b.label == "Confirm reviewed execution details").click().run()
        assert not app.exception and runtime._executable_confirmation is not None
        assert any("Confirmed:" in message.value for message in app.success)
        assert next(b for b in app.button if b.label == "Confirm reviewed execution details").disabled
        next(b for b in app.button if b.label == "Refresh executable review").click().run()
        assert not app.exception and runtime._executable_confirmation is None
        assert runtime._executable_review is not held
        assert len([e for e in app.expander if e.label.startswith("Executable request ")]) == min(20, count)
    assert not any(b.label in {"Start", "Generate", "Run", "Apply"} for b in app.button)
    assert not runtime.generation_jobs._jobs
    runtime.close()


def test_apptest_full_verified_prompts_multiple_runs_and_navigation_preserve_seeds():
    runtime, route, epoch, state, args, provider = queued(runs=3)
    app = app_for(state, runtime, provider)
    app.run()
    next(b for b in app.button if b.label == "Prepare executable review").click().run()
    held = runtime._executable_review
    assert len([e for e in app.expander if e.label.startswith("Executable request ")]) == 6
    assert {code.value for code in app.code} >= {"prompt 0", "prompt 1", "negative 0", "negative 1"}
    app.run()
    app.button(key="agent_generation_review_return").click().run()
    app.button(key="agent_generation_review_navigation").click().run()
    assert runtime._executable_review is held and not app.exception
    text = " ".join(str(e.value) for e in [*app.text, *app.caption, *app.code])
    assert all(term not in text for term in ("PRIVATE", "request_id", "node_id", "workflow_json"))
    runtime.close()


def test_apptest_untruncated_prompt_and_temporary_preflight_failure():
    text = "exact reviewed prompt " + "a"*3500
    runtime, route, epoch, state, args, provider = queued(count=1, prompt_text=text)
    app = app_for(state, runtime, provider)
    app.run()
    next(b for b in app.button if b.label == "Prepare executable review").click().run()
    assert not app.exception and text in [code.value for code in app.code]
    held = runtime._executable_review
    def unavailable(*args): raise FileNotFoundError("PRIVATE")
    app.session_state["provider"] = unavailable
    app.run()
    assert not app.exception and not any(b.label == "Confirm reviewed execution details" for b in app.button)
    assert runtime._executable_review is held and runtime._executable_confirmation is None
    app.session_state["provider"] = provider
    app.run()
    assert not app.exception and runtime._executable_review is held
    next(b for b in app.button if b.label == "Confirm reviewed execution details").click().run()
    assert runtime._executable_confirmation is not None
    runtime.close()


def test_apptest_uncertifiable_target_cannot_confirm_and_all_requests_remain_visible():
    base = host_for()
    def provider(p, runs):
        context = base(p, runs)
        original = context["request_builder"]
        def build(item, index):
            value = original(item, index)
            if item.id == "illustration-001": value["workflow_json"]["s"]["inputs"]["positive"] = ["missing", 0]
            return value
        context["request_builder"] = build
        return context
    runtime, route, epoch, state, args, provider = queued(provider=provider)
    app = app_for(state, runtime, provider)
    app.run()
    next(b for b in app.button if b.label == "Prepare executable review").click().run()
    assert not app.exception
    view, held = inspect(state, runtime, provider)
    assert view["state"] == "uncertifiable" and len(view["requests"]) == 2
    assert view["targets"][1]["blockers"]
    assert len([e for e in app.expander if e.label.startswith("Executable request ")]) == 2
    assert next(b for b in app.button if b.label == "Confirm reviewed execution details").disabled
    assert confirm(state, runtime, provider, held) == "uncertifiable"
    assert runtime._executable_confirmation is None
    runtime.close()


@pytest.mark.parametrize("target,label", [("project_management", "Project Management"),
    ("module_attribute_authoring", "Module / Attribute Authoring"), ("comfyui_settings", "ComfyUI Settings")])
def test_actual_management_navigation_retains_exact_review_and_confirmation(target, label):
    tree = ast.parse((Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8"))
    names = {"normalize_management_workspace_target", "reset_management_workspace_session_state",
        "open_management_workspace", "get_active_management_workspace", "activate_generation_review_navigation",
        "render_management_workspace_launchers"}
    definitions = '\n\n'.join(ast.unparse(node) for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names)
    script = APP[:APP.index('render_agent_review_navigation(runtime,')] + '''
ACTIVE_MANAGEMENT_WORKSPACE_KEY = "active_management_workspace"
MANAGEMENT_WORKSPACE_TARGETS = {
    "project_management": {"title": "Project Management"},
    "module_attribute_authoring": {"title": "Module / Attribute Authoring"},
    "comfyui_settings": {"title": "ComfyUI Settings"}}
''' + definitions + '''
render_generation_review_navigation(runtime, on_activate=activate_generation_review_navigation)
render_management_workspace_launchers()
if st.session_state.get(GENERATION_REVIEW_ACTIVE_KEY, False):
    render_generation_review_panel(runtime, provider)
elif get_active_management_workspace():
    st.title(MANAGEMENT_WORKSPACE_TARGETS[get_active_management_workspace()]["title"])
else:
    st.title("Project workspace")
'''
    runtime, route, epoch, state, args, provider = prepared()
    assert confirm(state, runtime, provider, runtime._executable_review) == "confirmed"
    held, acknowledgment = runtime._executable_review, runtime._executable_confirmation
    app = app_for(state, runtime, provider, script)
    app.run()
    next(b for b in app.button if b.label == label).click().run()
    assert app.title[0].value == label
    app.button(key="agent_generation_review_navigation").click().run()
    assert not app.exception and app.title[0].value == "Generation Review"
    assert runtime._executable_review is held and runtime._executable_confirmation is acknowledgment
    runtime.close()
