"""PR-D: compose the product host with its existing transport/domain owners.

The Windows test starts the official launcher subprocess and real Named Pipes.
Other tests use a real paired route and full app.py Streamlit AppTest runs;
faults/clocks are explicitly simulated at owner seams. No browser is driven.
"""

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import uuid

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from streamlit.runtime.scriptrunner import get_script_run_ctx
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1 import app_test as streamlit_app_test
from streamlit.testing.v1.util import patch_config_options

from core import module_swap_selected_routes, settings
from core.agent_facade import preview_scene_module_swap
from core.graph_builder import build_graph
from core.io import load_project_from_json
from core.operations import normalize_module_library
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui import project_agent_request_bridge as bridge
from ui import project_agent_session_pump as pump
from ui.agent_scene_module_swap_review_panel import AGENT_REVIEW_ACTIVE_KEY, _ack_widget_key
from ui.agent_scene_module_swap_approval_lifecycle import DEFAULT_PROPOSAL_TTL_SECONDS
from ui.project_agent_named_pipe import WindowsNamedPipeBroker


ROOT = Path(__file__).resolve().parents[1]
PREVIEW = "promptgraph_preview_scene_module_swap"
REQUEST_REVIEW = "promptgraph_request_scene_module_swap_review"


def _project(count=1):
    def line(line_id, text, index, *, separator=False):
        return PromptLine(
            id=line_id, original_file_name=f"{line_id}.png",
            original_index=index, current_index=index,
            original_text=text, current_text=text,
            tokens=[] if separator else parse_prompt(text),
            line_type="separator" if separator else None,
            separator_label=text if separator else None,
            negative_prompt="preserved negative",
        )

    lines = [line("scene-a", "Scene A", 0, separator=True)]
    lines.extend(line(f"a-{i:03}", f"red, blue, detail {i}", i + 1) for i in range(count))
    lines.extend([
        line("scene-b", "Scene B", count + 1, separator=True),
        line("b-000", "red, blue, outside", count + 2),
    ])
    project = build_graph(Project(
        prompt_lines=lines,
        project_metadata={"unknown_future_field": {"preserve": [1, 2]},
                          "image_imports": [], "candidate_images": [],
                          "comfyui_workflows": [], "generation_jobs": []},
        module_library={
            "source": {"body": "red, blue", "core_tokens": ["red", "blue"]},
            "target": {"body": "gold, green", "core_tokens": ["gold", "green"]},
        }, attribute_groups={},
    ))
    # Match real loaded/authored Projects before crossing persistence: the
    # normal save owner fills Module defaults in place as existing behavior.
    normalize_module_library(project)
    return project


def _intent():
    return dict(scene_id="scene-a", source_module_name="source",
                target_module_name="target", match_mode="strict")


def _run(app):
    app.run(timeout=30)
    assert not app.exception, [element.message for element in app.exception]


def _button(app, label):
    return next(button for button in app.button if button.label == label)


@pytest.fixture
def hosts(tmp_path, monkeypatch):
    """Full product shell, with filesystem settings confined to temporary data."""
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(tmp_path / "settings.json"))
    made = []
    observed = []
    real_begin = pump.begin_project_agent_session_run
    real_runner = streamlit_app_test.LocalScriptRunner

    def isolated_runner(script_path, session_state, pages_manager, **kwargs):
        # Streamlit 1.60 AppTest hardcodes "test session id". Assign the
        # ScriptRunner identity before start so the real session-scoped
        # cache_resource owner can distinguish two AppTest browser fixtures.
        runner = real_runner(script_path, session_state, pages_manager, **kwargs)
        runner._session_id = session_state["pr_d_test_session_id"]
        return runner

    monkeypatch.setattr(streamlit_app_test, "LocalScriptRunner", isolated_runner)

    def observe_begin(*args, **kwargs):
        runtime = real_begin(*args, **kwargs)
        observed.append(runtime)
        return runtime

    monkeypatch.setattr(pump, "begin_project_agent_session_run", observe_begin)

    def make(count=1):
        destination = tmp_path / f"host-{len(made)}" / "project.json"
        destination.parent.mkdir()
        project = _project(count)
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
        app.session_state["pr_d_test_session_id"] = f"pr-d-{uuid.uuid4().hex}"
        app.session_state["project"] = project
        app.session_state["current_project_path"] = str(destination)
        app.session_state["startup_project_auto_open_attempted"] = True
        app.session_state["settings"] = {
            **settings._default_settings(),
            "global_module_library_dir": str(tmp_path / "modules"),
            "projects_root_directory": str(tmp_path / "projects"),
        }
        app.session_state[AGENT_REVIEW_ACTIVE_KEY] = True
        app.session_state["focused_line_id"] = "a-000"
        _run(app)
        host = SimpleNamespace(app=app, runtime=observed[-1], project=project,
                               path=destination, captures=[], core_calls=[], publications=[])
        real_publish = host.runtime.publish_review_apply

        def observe_publish(*args, **kwargs):
            result = real_publish(*args, **kwargs)
            if result == "published":
                host.publications.append(kwargs["updated_project"])
            return result

        monkeypatch.setattr(host.runtime, "publish_review_apply", observe_publish)
        made.append(host)
        return host

    real_capture = bridge.capture_active_project

    def observe_capture(state, token):
        context = get_script_run_ctx()
        assert context is not None  # Never capture on the pipe/gateway thread.
        result = real_capture(state, token)
        for host in made:
            if state.get("project") is host.project:
                host.captures.append((context.session_id, token, result.reason))
        return result

    monkeypatch.setattr(bridge, "capture_active_project", observe_capture)
    real_apply = module_swap_selected_routes.apply_selected_routes_module_swap

    def observe_apply(project, scenes, **kwargs):
        assert get_script_run_ctx() is not None
        for host in made:
            if project is host.project:
                host.core_calls.append((list(scenes), kwargs))
        return real_apply(project, scenes, **kwargs)

    monkeypatch.setattr("ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
                        observe_apply)
    try:
        with patch_config_options({"runner.fastReruns": False, "server.fileWatcherType": "none"}):
            yield make
    finally:
        for host in made:
            host.runtime.close()


def _pair(host):
    offer = host.runtime.arm_local_pairing()
    assert offer.status == "armed"
    bootstrap = offer.bootstrap
    paired = host.runtime._registry.claim_pairing(
        bootstrap.process_incarnation, bootstrap.route_id, bootstrap.capability,
    )
    assert paired.status == "paired"
    return paired.paired_route


def _request(host, route, tool, arguments, request_id="review-1"):
    epoch = host.runtime.mailbox.target_epoch
    assert route.submit(epoch, dict(request_id=request_id, tool=tool,
                                    arguments=arguments)).status == "accepted"
    _run(host.app)
    outcome = route.consume_reply(epoch)
    assert outcome.status == "completed"
    return outcome.reply["result"]


def _queue(host, route):
    preview = _request(host, route, PREVIEW, _intent(), "preview-1")
    assert preview == preview_scene_module_swap(host.project, _intent())
    assert host.runtime.inspect_review_custody()["state"] == "absent"
    arguments = {**_intent(), "expected_plan_id": preview["plan_id"]}
    ack = _request(host, route, REQUEST_REVIEW, arguments)
    assert ack["status"] == "queued_for_review"
    assert host.runtime.inspect_review_custody()["preview"] == preview
    return arguments, ack


def _acknowledge(host, ack):
    assert _button(host.app, "Approve and Apply").disabled
    host.app.checkbox(key=_ack_widget_key((ack["proposal_id"], ack["plan_id"]))).check()
    _run(host.app)
    assert not _button(host.app, "Approve and Apply").disabled
    assert host.app.session_state["project"] is host.project
    assert host.app.session_state["history"] == []
    assert host.core_calls == []
    assert not host.path.exists()


@pytest.mark.skipif(os.name != "nt", reason="official launcher and real Windows Named Pipes")
def test_official_stdio_named_pipe_to_full_app_review_apply_and_autosave(
    hosts, tmp_path, monkeypatch,
):
    host = hosts(101)
    original = deepcopy(host.project)
    # Both ends resolve the official fixed rendezvous in the same isolated
    # Windows temp directory. No private launcher argument or fake pipe API.
    pipe_temp = tmp_path / "pipe-temp"
    pipe_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(pipe_temp))
    broker = WindowsNamedPipeBroker(host.runtime._registry)
    submitted = queue.Queue()
    released = threading.Event()
    real_submit = host.runtime.mailbox.submit
    real_consume = host.runtime.mailbox.consume_reply
    real_finished = broker._endpoint_finished
    committed_acks = []

    def observe_submit(*args, **kwargs):
        result = real_submit(*args, **kwargs)
        if result.status == "accepted":
            submitted.put(args[1]["tool"])
        return result

    def observe_consume(*args, **kwargs):
        # Pending custody must exist before the positive ACK can be consumed.
        with host.runtime.mailbox._lock:
            result = real_consume(*args, **kwargs)
            if result.reply and result.reply.get("result", {}).get("status") == "queued_for_review":
                record = host.runtime.inspect_review_custody()
                assert record["state"] == "pending"
                assert record["proposal_id"] == result.reply["result"]["proposal_id"]
                committed_acks.append(record["proposal_id"])
        return result

    def observe_finished(lease, outcome):
        real_finished(lease, outcome)
        if outcome == "released":
            released.set()

    monkeypatch.setattr(host.runtime.mailbox, "submit", observe_submit)
    monkeypatch.setattr(host.runtime.mailbox, "consume_reply", observe_consume)
    monkeypatch.setattr(broker, "_endpoint_finished", observe_finished)
    assert host.runtime.arm_launcher_rendezvous(broker).status == "ready"
    rendezvous = broker._api.launcher_rendezvous_path()
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "agent_adapters.mcp_named_pipe_launcher"],
        cwd=str(ROOT), env={"PYTHONPATH": str(ROOT), "TMP": str(pipe_temp), "TEMP": str(pipe_temp)},
    )

    async def call(client, tool, arguments):
        task = asyncio.create_task(client.call_tool(tool, arguments))
        try:
            assert await asyncio.to_thread(submitted.get, True, 10) == tool
            await asyncio.to_thread(_run, host.app)
            return await asyncio.wait_for(task, 15)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def exercise():
        async with asyncio.timeout(120):
            async with Client(stdio_client(parameters), read_timeout_seconds=20) as client:
                listed = await client.list_tools()
                names = [tool.name for tool in listed.tools]
                assert len(names) == 9
                assert not any("apply" in name or "decision" in name for name in names)
                result = await call(client, PREVIEW, _intent())
                assert not result.is_error
                preview = result.structured_content
                assert preview == preview_scene_module_swap(host.project, _intent())
                assert preview["target_count"] == 101
                assert preview["review_rows_truncated"] is True
                assert host.runtime.inspect_review_custody()["state"] == "absent"
                args = {**_intent(), "expected_plan_id": preview["plan_id"]}
                for field, value in (("approved", True), ("proposal_id", preview["plan_id"]),
                                     ("agent_id", "trusted-host")):
                    forged = await call(client, REQUEST_REVIEW, {**args, field: value})
                    assert forged.structured_content["reason"] == "invalid_arguments"
                    assert host.runtime.inspect_review_custody()["state"] == "absent"
                mismatched = await call(client, REQUEST_REVIEW, {**args, "expected_plan_id": "0" * 64})
                assert mismatched.structured_content["reason"] == "stale_preview"
                queued = await call(client, REQUEST_REVIEW, args)
                ack = queued.structured_content
                assert ack["status"] == "queued_for_review"
                assert committed_acks == [ack["proposal_id"]]
                assert host.runtime.inspect_review_custody()["preview"] == preview
                assert len(host.captures) == 3  # Preview, stale plan, fresh request.
                assert "preview" not in ack and "approved" not in ack
                assert host.project == original and not host.path.exists()
                seen = []
                for page in range(6):
                    values = [element.value for element in host.app.code]
                    page_ids = [value for value in values if value.startswith("a-")]
                    seen.extend(page_ids)
                    for line_id in page_ids:
                        i = int(line_id.split("-")[1])
                        assert f"red, blue, detail {i}" in values
                        assert f"gold, green, detail {i}" in values
                    if page < 5:
                        _button(host.app, "Next Illustrations").click()
                        await asyncio.to_thread(_run, host.app)
                assert seen == [f"a-{i:03}" for i in range(101)]
                await asyncio.to_thread(_acknowledge, host, ack)
                _button(host.app, "Approve and Apply").click()
                await asyncio.to_thread(_run, host.app)
                applied = host.app.session_state["project"]
                assert applied is not host.project
                assert len(host.publications) == 1
                assert host.publications[0] is applied
                assert len(host.app.session_state["history"]) == 1
                assert host.app.session_state["history"][0] == original
                assert host.core_calls[0][0] == ["scene-a"]
                assert len(host.core_calls) == 1
                assert host.core_calls[0][1]["project_path"] == ""
                assert host.core_calls[0][1]["disabled_modules"] is None
                assert host.runtime.inspect_review_custody()["state"] == "applied"
                persisted = load_project_from_json(host.path)
                for result_project in (applied, persisted):
                    assert [line.current_text for line in result_project.prompt_lines[1:102]] == [
                        f"gold, green, detail {i}" for i in range(101)
                    ]
                    assert result_project.prompt_lines[-1] == original.prompt_lines[-1]
                    assert result_project.project_metadata["unknown_future_field"] == original.project_metadata["unknown_future_field"]
                    assert all(line.negative_prompt == "preserved negative" for line in result_project.prompt_lines)
                assert host.project == original
                assert applied.module_library == original.module_library
                assert applied.project_metadata == original.project_metadata
                # Check the actual serialized definitions as well as reopened
                # prompts; default normalization must not drop authored data.
                raw_saved = json.loads(host.path.read_text(encoding="utf-8"))
                assert raw_saved["module_library"] == original.module_library
                assert raw_saved["project_metadata"] == original.project_metadata
                assert "Agent Scene Module Swap applied" in host.app.session_state["autosave_feedback"]
                # Ordinary agent observations remain facade-shaped; no human
                # decision or Apply result is added to the transport response.
                after = await call(client, PREVIEW, _intent())
                assert after.structured_content == preview_scene_module_swap(applied, _intent())
                assert after.structured_content["changed_count"] == 0
                assert not {"proposal_id", "save_succeeded", "approved", "human_decision"}.intersection(after.structured_content)

    try:
        asyncio.run(exercise())
        assert released.wait(10)
        assert host.runtime.launcher_rendezvous_status().status == "released"
        assert not Path(rendezvous).exists()
        assert host.runtime.inspect_review_custody()["state"] == "applied"
        host.app.button(key="shortcut_undo").click()
        _run(host.app)
        assert host.app.session_state["project"] == original
        assert host.app.session_state["history"] == []
        assert len(host.core_calls) == 1
        # Existing Undo restores memory; it does not silently resave the file.
        assert load_project_from_json(host.path).prompt_lines[1].current_text == "gold, green, detail 0"
    finally:
        host.runtime.close()
        broker.close()


@pytest.mark.parametrize("change", ["project", "save_as", "prompt", "module", "expiry", "dismiss"])
def test_paired_proposal_staged_in_full_app_becomes_unapprovable(hosts, change):
    host = hosts()
    route = _pair(host)
    _args, ack = _queue(host, route)
    _acknowledge(host, ack)
    if change == "project":
        host.app.session_state["project"] = _project()
    elif change == "save_as":
        saved_as = host.path.with_name("save-as.json")
        host.app.text_input(key="save_project_json_path").set_value(str(saved_as))
        _run(host.app)
        host.app.button(key="save_project_as_json_button").click()
        _run(host.app)
        assert host.app.session_state["current_project_path"] == str(saved_as)
        assert load_project_from_json(saved_as).prompt_lines[1].current_text == "red, blue, detail 0"
    elif change == "prompt":
        line = host.project.prompt_lines[1]
        line.current_text += ", human edit"
        line.tokens = parse_prompt(line.current_text)
    elif change == "module":
        host.project.module_library["target"]["body"] = "silver, violet"
    elif change == "expiry":
        now = host.runtime.review_custodian._clock()
        host.runtime.review_custodian._clock = lambda: now + DEFAULT_PROPOSAL_TTL_SECONDS
    else:
        _button(host.app, "Dismiss proposal").click()
    _run(host.app)
    assert not any(button.label == "Approve and Apply" for button in host.app.button)
    assert host.app.session_state["history"] == []
    assert host.core_calls == []
    assert not host.path.exists()
    assert _ack_widget_key((ack["proposal_id"], ack["plan_id"])) not in host.app.session_state
    route.release()


def test_pair_generation_session_isolation_and_ordinary_release_vs_disarm(hosts):
    a, b = hosts(), hosts()
    assert a.runtime is not b.runtime
    route_a, route_b = _pair(a), _pair(b)
    args, ack = _queue(a, route_a)
    before = a.runtime.review_custodian.inspect()
    retry = _request(a, route_a, REQUEST_REVIEW, args)
    assert retry == ack
    assert a.runtime.review_custodian.inspect()["expires_at"] == before["expires_at"]
    assert len(a.captures) == 2  # Preview + fresh explicit request, no retry capture.
    assert b.runtime.inspect_review_custody()["state"] == "absent"
    assert not any(isinstance(checkbox.key, str) and checkbox.key.startswith("agent_scene_module_swap_review_ack_")
                   for checkbox in b.app.checkbox)
    assert route_a.release().status == "released"
    _run(a.app)
    assert a.runtime.inspect_review_custody()["state"] == "pending"
    next_route = _pair(a)
    replay = _request(a, next_route, REQUEST_REVIEW, args)
    assert replay["reason"] == "replay_not_accepted"
    assert "proposal_id" not in replay
    assert a.runtime.inspect_review_custody()["proposal_id"] == ack["proposal_id"]
    # Same JSON intent/correlation ID in another browser has separate custody.
    other = _request(b, route_b, REQUEST_REVIEW, args)
    assert other["status"] == "queued_for_review"
    assert other["proposal_id"] != ack["proposal_id"]
    assert {capture[0] for capture in a.captures}.isdisjoint(capture[0] for capture in b.captures)
    a.runtime.disarm_launcher_rendezvous()
    _run(a.app)
    assert a.runtime.inspect_review_custody()["state"] == "dismissed"
    assert a.runtime.review_custodian.inspect()["state"] == "absent"
    assert b.runtime.inspect_review_custody()["state"] == "pending"
    a.runtime.close()
    assert b.runtime.inspect_review_custody()["state"] == "pending"
    assert a.core_calls == b.core_calls == []
    next_route.release()
    route_b.release()


def test_busy_and_expired_mailbox_request_cannot_create_a_review(hosts):
    host = hosts()
    route = _pair(host)
    args = {**_intent(), "expected_plan_id": preview_scene_module_swap(host.project, _intent())["plan_id"]}
    epoch = host.runtime.mailbox.target_epoch
    request = dict(request_id="waiting", tool=REQUEST_REVIEW, arguments=args)
    assert route.submit(epoch, request).status == "accepted"
    assert route.submit(epoch, {**request, "request_id": "second"}).status == "busy"
    # Simulated monotonic expiry, not a wall-clock sleep race.
    real_clock = host.runtime.mailbox._clock
    host.runtime.mailbox._clock = lambda: real_clock() + 121
    _run(host.app)
    assert route.consume_reply(epoch).status == "expired"
    assert host.runtime.inspect_review_custody()["state"] == "absent"
    assert host.captures == host.core_calls == []
    assert not host.path.exists()
    route.release()


def test_no_op_explicit_request_after_real_preview_is_not_queued(hosts):
    host = hosts()
    route = _pair(host)
    host.project.module_library["target"] = deepcopy(host.project.module_library["source"])
    intent = _intent()
    preview = _request(host, route, PREVIEW, intent, "no-op-preview")
    assert preview["valid"] is True
    assert preview["changed_count"] == 0
    result = _request(host, route, REQUEST_REVIEW, {**intent, "expected_plan_id": preview["plan_id"]})
    assert result["reason"] == "no_op_preview"
    assert host.runtime.inspect_review_custody()["state"] == "absent"
    assert host.core_calls == []
    route.release()


@pytest.mark.parametrize("failure", ["core", "disarm", "close", "target_during_core",
                                     "autosave", "target_after_publication"])
def test_full_app_approval_failure_safety_at_real_owner_boundaries(hosts, monkeypatch, failure):
    host = hosts()
    route = _pair(host)
    _args, ack = _queue(host, route)
    _acknowledge(host, ack)
    original = deepcopy(host.project)
    real_core = module_swap_selected_routes.apply_selected_routes_module_swap
    core_entered, revocation_finished = threading.Event(), threading.Event()
    revoker = None
    revoker_errors = []
    if failure == "autosave":
        def fail_save(*_args, **_kwargs):
            raise OSError("simulated persistence failure")
        # Streamlit callbacks retain the prior run's app globals. Inject at
        # the real persistence writer, below that imported callback binding.
        monkeypatch.setattr("core.io._write_project_json", fail_save)
    elif failure == "target_after_publication":
        real_reconcile = host.runtime.reconcile_published_review_apply

        def switch_before_reconciliation(**kwargs):
            # Publication has committed; the new active target must never be
            # reconciled/saved using the old proposal or applied replacement.
            assert len(kwargs["session_state"]["history"]) == 1
            kwargs["session_state"]["project"] = _project()
            kwargs["session_state"]["current_project_path"] = str(host.path.with_name("other.json"))
            return real_reconcile(**kwargs)

        monkeypatch.setattr(host.runtime, "reconcile_published_review_apply", switch_before_reconciliation)
    else:
        def controlled_core(project, scenes, **kwargs):
            host.core_calls.append((list(scenes), kwargs))
            if failure == "core":
                raise RuntimeError("simulated core failure")
            result = real_core(project, scenes, **kwargs)
            if failure == "target_during_core":
                # Simulate supported host navigation at the owner seam, while
                # retaining the real core clone result for rejection.
                context = get_script_run_ctx()
                context.session_state["project"] = _project()
                context.session_state["current_project_path"] = str(host.path.with_name("other.json"))
            else:
                core_entered.set()
                assert revocation_finished.wait(10)
            return result

        monkeypatch.setattr("ui.agent_scene_module_swap_apply_lifecycle.apply_selected_routes_module_swap",
                            controlled_core)
        if failure in {"disarm", "close"}:
            def revoke():
                try:
                    assert core_entered.wait(10)
                    if failure == "disarm":
                        host.runtime.disarm_launcher_rendezvous()
                    else:
                        host.runtime.close()
                except BaseException as exc:
                    revoker_errors.append(exc)
                finally:
                    revocation_finished.set()

            revoker = threading.Thread(target=revoke)
            revoker.start()
    try:
        _button(host.app, "Approve and Apply").click()
        _run(host.app)
    finally:
        if revoker:
            revocation_finished.set()
            revoker.join(10)
            assert not revoker.is_alive()
        route.release()
    assert not revoker_errors
    assert host.project == original
    assert len(host.core_calls) == 1
    assert not host.path.exists()
    assert not host.path.with_name("other.json").exists()
    if failure in {"autosave", "target_after_publication"}:
        assert len(host.app.session_state["history"]) == 1
        assert host.app.session_state["history"][0] == original
        if failure == "autosave":
            assert host.runtime.inspect_review_custody()["state"] == "applied_save_failed"
            assert host.app.session_state["project"].prompt_lines[1].current_text == "gold, green, detail 0"
        else:
            assert host.app.session_state["project"].prompt_lines[1].current_text == "red, blue, detail 0"
    else:
        assert host.app.session_state["history"] == []
        if failure != "target_during_core":
            assert host.app.session_state["project"] is host.project
    # A full rerun after failure never turns a consumed approval into a retry.
    _run(host.app)
    assert len(host.core_calls) == 1
