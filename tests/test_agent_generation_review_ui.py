"""Host freshness, exact callbacks and real Streamlit full-run review navigation."""
import ast
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest
from core import agent_facade
from ui.agent_generation_review_lifecycle import build_generation_review, resolve_generation_review
from ui.agent_generation_review_panel import _page_rows, GENERATION_REVIEW_ACTIVE_KEY
from ui import project_capture_safety as capture
from test_agent_generation_review_custody import setup, send
from test_agent_generation_preview import line, host


@pytest.fixture(autouse=True)
def safe_capture(monkeypatch):
    original = capture._streamlit_config.get_option
    monkeypatch.setattr(capture._streamlit_config, "get_option", lambda key: False if key == "runner.fastReruns" else original(key))


def queued(count=2, consume=False, with_swap=False):
    runtime, route, epoch, state, args = setup()
    value = state["project"]
    value.prompt_lines = [line("scene", "Scene", line_type="separator")]
    value.prompt_lines += [line(f"illustration-{index:03}", f"prompt {index}", negative_prompt=f"negative {index}") for index in range(count)]
    value.prompt_lines += [line("scratch", line_type="workbench"), line("deleted", deleted=True)]
    if with_swap:
        value.module_library = {"source": {"body": "red"}, "target": {"body": "gold"}}
        for item in value.prompt_lines[1:count+1]:
            item.current_text = "red"
            item.tokens = ["red"]
    binding = [agent_facade.candidate_observation_handles.project_identity(value), runtime._registration.route_id,
               state["current_project_path"], route._pairing_generation, epoch]
    args["expected_plan_id"] = agent_facade.preview_generation(value, "scene", host_context_provider=host,
                                                observation_binding=binding)["plan_id"]
    send(runtime, route, epoch, state, args)
    if consume:
        route.consume_reply(epoch)
    return runtime, route, epoch, state, args


@pytest.mark.parametrize("count", [1, 20, 21, 100])
def test_complete_safe_projection_and_page_coverage_without_side_effects(count):
    runtime, route, epoch, state, args = queued(count)
    before = copy.deepcopy(state)
    swap_before = runtime.inspect_review_custody()
    with patch("urllib.request.urlopen", side_effect=AssertionError("network")):
        review = build_generation_review(state, runtime, host)
    assert review["state"] == "pending_current"
    rows = review["illustrations"]
    assert [row["illustration_id"] for row in rows] == [f"illustration-{i:03}" for i in range(count)]
    pages = [_page_rows(rows, i)[3] for i in range((count + 19)//20)]
    assert [row for page in pages for row in page] == rows and all(len(page) <= 20 for page in pages)
    assert review["skipped_count"] == 2 and review["blocked_count"] == 0
    assert state == before and runtime.inspect_review_custody() == swap_before
    assert "PRIVATE" not in json.dumps(review) and "workflow_json" not in json.dumps(review)
    runtime.close()


@pytest.mark.parametrize("drift", ["prompt", "module", "configuration", "workflow"])
def test_genuine_drift_stales_exact_proposal_and_retires_undelivered_ack(drift):
    runtime, route, epoch, state, args = queued()
    provider = host
    if drift == "prompt":
        state["project"].prompt_lines[1].current_text = "new"
    elif drift == "module":
        state["project"].module_library["new"] = {"body": "new"}
    else:
        def provider(p, runs):
            context = host(p, runs)
            if drift == "configuration":
                context["generation_options"]["endpoint"] = "new"
            else:
                original = context["request_builder"]
                def build(item, index):
                    value = original(item, index)
                    value["workflow_json"]["2"]["inputs"]["filename_prefix"] = "new"
                    return value
                context["request_builder"] = build
            return context
    assert build_generation_review(state, runtime, provider)["state"] == "stale"
    assert route.consume_reply(epoch).status == "stale_target"
    runtime.close()


def test_temporary_failure_preserves_pending_and_recovers_without_actions():
    runtime, route, epoch, state, args = queued()
    def unavailable(*a):
        raise FileNotFoundError("PRIVATE_PATH")
    assert build_generation_review(state, runtime, unavailable) == {"state": "computation_failure"}
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    assert build_generation_review(state, runtime, host)["state"] == "pending_current"
    assert route.consume_reply(epoch).reply["result"]["ok"]
    runtime.close()


def test_temporary_failure_still_rechecks_live_target_after_computation():
    runtime, route, epoch, state, args = queued()
    def unavailable(*a):
        state["current_project_path"] = "SAVE_AS_PATH"
        raise FileNotFoundError("PRIVATE_PATH")
    assert build_generation_review(state, runtime, unavailable)["state"] == "stale"
    assert route.consume_reply(epoch).status == "stale_target"
    runtime.close()


@pytest.mark.parametrize("change", ["switch", "save_as", "expiry", "disarm", "close"])
def test_lifecycle_invalidation(change):
    runtime, route, epoch, state, args = queued()
    if change == "switch":
        state["project"] = copy.deepcopy(state["project"])
    elif change == "save_as":
        state["current_project_path"] = "NEW_PATH"
    elif change == "expiry":
        runtime.generation_review_custodian._record.expires_at = 0
    elif change == "disarm":
        runtime.disarm_launcher_rendezvous()
    else:
        runtime.close()
    result = build_generation_review(state, runtime, host)
    assert result["state"] == {"switch": "stale", "save_as": "stale", "expiry": "expired",
                               "disarm": "dismissed", "close": "session_unavailable"}[change]
    runtime.close()


@pytest.mark.parametrize("action", ["reject", "dismiss"])
def test_action_revalidates_identity_and_content_and_duplicate_click(action):
    runtime, route, epoch, state, args = queued()
    review = build_generation_review(state, runtime, host)
    identity = (review["proposal_id"], review["plan_id"])
    assert resolve_generation_review(state, runtime, host, "wrong", identity[1], action) == "identity_mismatch"
    assert resolve_generation_review(state, runtime, host, *identity, action) in {"rejected", "dismissed"}
    assert route.consume_reply(epoch).status == "review_cancelled"
    assert resolve_generation_review(state, runtime, host, *identity, action) == "identity_mismatch"
    runtime.close()


def test_action_time_drift_and_target_change_during_verification():
    runtime, route, epoch, state, args = queued()
    review = build_generation_review(state, runtime, host)
    state["project"].prompt_lines[1].current_text = "new"
    assert resolve_generation_review(state, runtime, host, review["proposal_id"], review["plan_id"], "reject") == "stale"
    runtime.close()
    runtime, route, epoch, state, args = queued()
    def switch(p, runs):
        state["project"] = copy.deepcopy(p)
        return host(p, runs)
    assert build_generation_review(state, runtime, switch)["state"] == "stale"
    runtime.close()


APP = '''
import streamlit as st
from ui.agent_generation_review_panel import render_generation_review_navigation, render_generation_review_panel, GENERATION_REVIEW_ACTIVE_KEY
from ui.agent_scene_module_swap_review_panel import render_agent_review_navigation, AGENT_REVIEW_ACTIVE_KEY
from ui.project_capture_safety import begin_project_capture_run
from ui.project_agent_session_pump import service_project_agent_session_request
from test_agent_generation_preview import host
runtime = st.session_state.runtime
token = begin_project_capture_run(st.session_state)
service_project_agent_session_request(runtime, st.session_state, token, generation_context_provider=host)
render_agent_review_navigation(runtime, on_activate=lambda: st.session_state.__setitem__(GENERATION_REVIEW_ACTIVE_KEY, False))
render_generation_review_navigation(runtime, on_activate=lambda: st.session_state.__setitem__(AGENT_REVIEW_ACTIVE_KEY, False))
if st.session_state.get(GENERATION_REVIEW_ACTIVE_KEY, False):
    render_generation_review_panel(runtime, host)
else:
    st.title("Project workspace")
'''


@pytest.mark.parametrize("count", [1, 20, 21, 100])
def test_real_apptest_navigation_full_reruns_all_pages_and_return(count):
    runtime, route, epoch, state, args = queued(count, consume=True)
    original = copy.deepcopy(state["project"])
    app = AppTest.from_string(APP)
    app.session_state["runtime"] = runtime
    for key, value in state.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception
    app.button(key="agent_generation_review_navigation").click().run()
    assert not app.exception and app.title[0].value == "Generation Review"
    labels = [item.label for item in app.expander]
    assert len(labels) == min(20, count)
    for page in range(1, (count+19)//20):
        next_button = next(b for b in app.button if b.label == "Next Illustrations")
        next_button.click().run()
        assert not app.exception
        labels += [item.label for item in app.expander]
    assert len(labels) == count and len(set(labels)) == count
    assert all(word not in [b.label for b in app.button] for word in ("Approve", "Start", "Run", "Generate", "Apply"))
    assert any("No generation has started" in info.value for info in app.info)
    assert any("Workflow source: Host-configured shared workflow" == item.value for item in app.text)
    assert any("Endpoint policy: Host-configured (address hidden)" == item.value for item in app.text)
    app.button(key="agent_generation_review_return").click().run()
    assert app.title[0].value == "Project workspace" and runtime.generation_review_custodian.inspect()["state"] == "pending"
    app.button(key="agent_generation_review_navigation").click().run()
    next(b for b in app.button if b.label == "Reject proposal").click().run()
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "rejected"
    assert state["project"] == original
    runtime.close()


def test_normal_app_navigation_wiring_and_fragment_stays_wake_only():
    root = Path(__file__).resolve().parents[1]
    source = (root/"app.py").read_text(encoding="utf-8")
    assert 'render_generation_review_panel(_PROJECT_AGENT_SESSION_RUNTIME, _prepare_agent_generation_context)' in source
    assert 'render_generation_review_navigation(_PROJECT_AGENT_SESSION_RUNTIME' in source
    tree = ast.parse((root/"ui/project_agent_session_pump.py").read_text(encoding="utf-8"))
    fragment = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'render_project_agent_request_pump')
    assert not any(isinstance(node, ast.Name) and node.id in {'preview_generation', 'build_generation_review', 'render_generation_review_panel'}
                   for node in ast.walk(fragment))


def test_route_release_preserves_review_and_new_pairing_stales_it():
    runtime, route, epoch, state, args = queued(consume=True)
    assert route.release().status == "released"
    assert build_generation_review(state, runtime, host)["state"] == "pending_current"
    offer = runtime.arm_local_pairing().bootstrap
    runtime._registry.claim_pairing(offer.process_incarnation, offer.route_id, offer.capability)
    assert build_generation_review(state, runtime, host)["state"] == "stale"
    runtime.close()


def test_scene_module_swap_coexists_and_generation_action_does_not_retire_its_ack():
    from ui.project_agent_session_pump import service_project_agent_session_request
    runtime, route, epoch, state, args = queued(consume=True, with_swap=True)
    intent = {"scene_id": "scene", "source_module_name": "source", "target_module_name": "target", "match_mode": "strict"}
    preview = agent_facade.preview_scene_module_swap(state["project"], intent)
    assert preview["valid"] and preview["changed_count"] == 2
    assert route.submit(epoch, {"request_id": "swap", "tool": "promptgraph_request_scene_module_swap_review",
        "arguments": {**intent, "expected_plan_id": preview["plan_id"]}}).status == "accepted"
    token = capture.begin_project_capture_run(state)
    assert service_project_agent_session_request(runtime, state, token, generation_context_provider=host) == "completed"
    swap_before = runtime.inspect_review_custody()
    review = build_generation_review(state, runtime, host)
    assert review["state"] == "pending_current" and swap_before["state"] == "pending"
    assert resolve_generation_review(state, runtime, host, review["proposal_id"], review["plan_id"], "dismiss") == "dismissed"
    assert runtime.inspect_review_custody() == swap_before
    assert route.consume_reply(epoch).reply["result"]["status"] == "queued_for_review"
    runtime.close()


def test_apptest_dismiss_and_new_identity_resets_page():
    runtime, route, epoch, state, args = queued(21, consume=True)
    app = AppTest.from_string(APP)
    app.session_state["runtime"] = runtime
    for key, value in state.items():
        app.session_state[key] = value
    app.session_state[GENERATION_REVIEW_ACTIVE_KEY] = True
    app.run()
    next(b for b in app.button if b.label == "Next Illustrations").click().run()
    assert len(app.expander) == 1
    next(b for b in app.button if b.label == "Dismiss proposal").click().run()
    assert runtime.generation_review_custodian.inspect_for_human_review()["state"] == "dismissed"
    send(runtime, route, epoch, state, args, request_id="fresh")
    route.consume_reply(epoch)
    app.run()
    assert not app.exception and len(app.expander) == 20
    assert app.expander[0].label.startswith("Illustration 1 ·")
    runtime.close()


def test_apptest_temporary_failure_has_no_resolution_controls():
    runtime, route, epoch, state, args = queued(consume=True)
    script = APP.replace('render_generation_review_panel(runtime, host)',
        'render_generation_review_panel(runtime, lambda *a: (_ for _ in ()).throw(FileNotFoundError()))')
    app = AppTest.from_string(script)
    app.session_state["runtime"] = runtime
    for key, value in state.items():
        app.session_state[key] = value
    app.session_state[GENERATION_REVIEW_ACTIVE_KEY] = True
    app.run()
    assert not app.exception and not app.expander
    assert not any(b.label in {"Reject proposal", "Dismiss proposal"} for b in app.button)
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    runtime.close()


@pytest.mark.parametrize("malformed", ["intent", "identity", "envelope"])
def test_malformed_host_record_fails_closed_without_actions(malformed):
    runtime, route, epoch, state, args = queued()
    record = runtime.generation_review_custodian._record
    if malformed == "intent":
        record.intent["run_count"] = False
    elif malformed == "identity":
        record.plan_id = "wrong"
    else:
        record.preview["workflow_json"] = {"secret": "private"}
    assert build_generation_review(state, runtime, host)["state"] == "validation_failure"
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    runtime.close()


@pytest.mark.parametrize("target,label", [("project_management", "Project Management"),
    ("module_attribute_authoring", "Module / Attribute Authoring"), ("comfyui_settings", "ComfyUI Settings")])
def test_actual_management_navigation_owners_switch_immediately_and_leave_no_destination(target, label):
    # Execute the production navigation owners in a real normal-run AppTest,
    # avoiding unrelated production app startup/configuration dependencies.
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root/"app.py").read_text(encoding="utf-8"))
    names = {"normalize_management_workspace_target", "reset_management_workspace_session_state",
             "open_management_workspace", "get_active_management_workspace",
             "activate_generation_review_navigation", "render_management_workspace_launchers"}
    definitions = '\n\n'.join(ast.unparse(node) for node in tree.body
                              if isinstance(node, ast.FunctionDef) and node.name in names)
    script = APP[:APP.index('render_agent_review_navigation(runtime,')] + '''
ACTIVE_MANAGEMENT_WORKSPACE_KEY = "active_management_workspace"
MANAGEMENT_WORKSPACE_TARGETS = {
    "project_management": {"title": "Project Management"},
    "module_attribute_authoring": {"title": "Module / Attribute Authoring"},
    "comfyui_settings": {"title": "ComfyUI Settings"}}
''' + definitions + '''
render_agent_review_navigation(runtime, on_activate=lambda: st.session_state.__setitem__(GENERATION_REVIEW_ACTIVE_KEY, False))
render_generation_review_navigation(runtime, on_activate=activate_generation_review_navigation)
render_management_workspace_launchers()
if st.session_state.get(GENERATION_REVIEW_ACTIVE_KEY, False):
    render_generation_review_panel(runtime, host)
elif get_active_management_workspace():
    st.title(MANAGEMENT_WORKSPACE_TARGETS[get_active_management_workspace()]["title"])
else:
    st.title("Project workspace")
'''
    runtime, route, epoch, state, args = queued(consume=True)
    before = copy.deepcopy(state["project"])
    app = AppTest.from_string(script)
    app.session_state["runtime"] = runtime
    for key, value in state.items():
        app.session_state[key] = value
    app.session_state[GENERATION_REVIEW_ACTIVE_KEY] = True
    with patch("urllib.request.urlopen", side_effect=AssertionError("execution")):
        app.run()
        assert app.title[0].value == "Generation Review"
        next(b for b in app.button if b.label == label).click().run()
        assert not app.exception and app.title[0].value == label
        assert app.session_state[GENERATION_REVIEW_ACTIVE_KEY] is False
        app.button(key="agent_generation_review_navigation").click().run()
        assert app.title[0].value == "Generation Review"
        assert app.session_state["active_management_workspace"] == ""
        app.button(key="agent_generation_review_return").click().run()
        assert app.title[0].value == "Project workspace"
    assert runtime.generation_review_custodian.inspect()["state"] == "pending"
    assert state["project"] == before
    runtime.close()
