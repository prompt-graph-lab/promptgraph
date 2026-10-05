import asyncio
import copy
import sys
import threading
import types
import uuid
from unittest.mock import MagicMock

import streamlit
from streamlit.proto.ClientState_pb2 import ClientState
from streamlit.runtime.app_session import AppSession
from streamlit.runtime.memory_uploaded_file_manager import MemoryUploadedFileManager
from streamlit.runtime.pages_manager import PagesManager
from streamlit.runtime.runtime import Runtime
from streamlit.runtime.script_data import ScriptData
from streamlit.runtime.scriptrunner.script_cache import ScriptCache
from streamlit.testing.v1.util import patch_config_options

from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui import project_agent_session_pump as session_pump
from ui.project_capture_safety import (
    PROJECT_CAPTURE_RUN_TOKEN_KEY,
    begin_project_capture_run,
)


def _project(name):
    prompt = f"red shirt {name}"
    return build_graph(Project(
        prompt_lines=[PromptLine(
            id=f"illustration-{name}",
            original_file_name=f"{name}.png",
            original_index=0,
            current_index=0,
            original_text=prompt,
            current_text=prompt,
            tokens=parse_prompt(prompt),
        )],
        project_metadata={"session": name, "revision": 0},
    ))


async def _wait(event):
    assert await asyncio.to_thread(event.wait, 10), "timed out waiting for Streamlit ScriptRunner"


def _make_app_session(tmp_path, harness):
    script_path = tmp_path / f"agent_pump_{uuid.uuid4().hex}.py"
    harness_name = f"_promptgraph_agent_pump_harness_{uuid.uuid4().hex}"
    sys.modules[harness_name] = harness
    script_path.write_text(
        f"import streamlit as st\nimport {harness_name} as harness\nharness.run(st.session_state)\n",
        encoding="utf-8",
    )
    session = AppSession(
        ScriptData(str(script_path)),
        MemoryUploadedFileManager("/agent-pump-test/upload"),
        ScriptCache(),
        lambda: None,
        {"email": "agent-pump-test"},
        session_id_override=f"agent-pump-{uuid.uuid4().hex}",
    )
    runners = []
    create_scriptrunner = session._create_scriptrunner

    def record_scriptrunner(rerun_data):
        create_scriptrunner(rerun_data)
        runners.append(session._scriptrunner)

    session._create_scriptrunner = record_scriptrunner
    session._session_state["project"] = harness.project
    session._session_state["current_project_path"] = harness.project_path
    harness.session = session
    harness.runners = runners
    harness.run_count = 0
    harness.run_lock = threading.Lock()
    harness.first_run_finished = threading.Event()
    harness.request_run_finished = threading.Event()
    harness.before_service_entered = threading.Event()
    harness.release_before_service = threading.Event()
    harness.release_before_service.set()
    harness.pause_first_before_service = False
    harness.runtime = None
    harness.run_observations = []
    harness.fragment_id = None
    return session, harness_name


async def _cleanup_app_session(session, harness, harness_name):
    if harness.runtime is not None:
        harness.runtime.close()
    try:
        session.shutdown()
    except Exception:
        pass
    for runner in harness.runners:
        thread = getattr(runner, "_script_thread", None)
        if thread is not None:
            await asyncio.to_thread(thread.join, 10)
            assert not thread.is_alive(), "Streamlit ScriptRunner leaked"
    sys.modules.pop(harness_name, None)


def _harness(project, project_path):
    harness = types.ModuleType("agent_pump_harness")
    harness.project = project
    harness.project_path = project_path

    def run(session_state):
        token = begin_project_capture_run(session_state)
        runtime = session_pump.begin_project_agent_session_run(
            session_state,
            token,
        )
        harness.runtime = runtime
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        context = get_script_run_ctx()
        assert context is not None
        registration_sequence = context.fragment_storage.registration_sequence()
        session_pump.render_project_agent_request_pump()
        with harness.run_lock:
            harness.run_count += 1
            run_number = harness.run_count
        if harness.fragment_id is None:
            fragment_ids = context.fragment_storage.ids_registered_after(
                registration_sequence
            )
            assert fragment_ids
            harness.fragment_id = sorted(fragment_ids)[-1]
        if run_number == 1 and harness.pause_first_before_service:
            harness.before_service_entered.set()
            if not harness.release_before_service.wait(10):
                raise TimeoutError("full-run service gate was not released")
        status = session_pump.service_project_agent_session_request(
            runtime,
            session_state,
            token,
        )
        harness.run_observations.append({
            "number": run_number,
            "thread_id": threading.get_ident(),
            "token": token,
            "current_token": session_state.get(PROJECT_CAPTURE_RUN_TOKEN_KEY),
            "status": status,
        })
        if run_number == 1:
            harness.first_run_finished.set()
        else:
            harness.request_run_finished.set()

    harness.run = run
    return harness


def test_real_streamlit_fragment_wakes_only_its_session_and_dispatches_in_full_run(
    tmp_path, monkeypatch
):
    assert streamlit.__version__ == "1.60.0"

    previous_runtime = Runtime._instance
    previous_main = sys.modules.get("__main__")
    previous_pages_mode = PagesManager.uses_pages_directory
    Runtime._instance = MagicMock(spec=Runtime)
    Runtime._instance.media_file_mgr = MagicMock()
    Runtime._instance.cache_storage_manager = MagicMock()
    Runtime._instance.bidi_component_registry = MagicMock()
    PagesManager.uses_pages_directory = False
    config_context = patch_config_options({
        "runner.fastReruns": False,
        "server.fileWatcherType": "none",
        "server.runOnSave": False,
    })
    config_context.__enter__()

    dispatch_calls = []
    original_dispatch = session_pump.dispatch_project_agent_request

    def observe_dispatch(session_state, run_token, request):
        dispatch_calls.append({
            "session": session_state.get("project").project_metadata["session"],
            "run_token": run_token,
            "current_token": session_state.get(PROJECT_CAPTURE_RUN_TOKEN_KEY),
            "thread_id": threading.get_ident(),
            "request": copy.deepcopy(request),
        })
        return original_dispatch(session_state, run_token, request)

    monkeypatch.setattr(session_pump, "dispatch_project_agent_request", observe_dispatch)

    async def exercise():
        project_a = _project("a")
        project_b = _project("b")
        before_a = copy.deepcopy(project_a)
        before_b = copy.deepcopy(project_b)
        harness_a = _harness(project_a, r"C:\Projects\a\project.json")
        harness_b = _harness(project_b, r"C:\Projects\b\project.json")
        session_a, module_a = _make_app_session(tmp_path, harness_a)
        session_b, module_b = _make_app_session(tmp_path, harness_b)
        harness_b.pause_first_before_service = True
        harness_b.release_before_service.clear()
        cleanup_items = [
            (session_a, harness_a, module_a),
            (session_b, harness_b, module_b),
        ]
        try:
            session_a.request_rerun(None)
            session_b.request_rerun(None)
            await _wait(harness_a.first_run_finished)
            await _wait(harness_b.before_service_entered)

            assert harness_a.runtime is not harness_b.runtime
            epoch_a = harness_a.runtime.mailbox.target_epoch
            epoch_b = harness_b.runtime.mailbox.target_epoch
            assert epoch_a != epoch_b
            assert harness_b.runtime.mailbox.state == "idle"

            producer_thread_ids = []
            producer_results = []

            def test_only_producer():
                producer_thread_ids.append(threading.get_ident())
                producer_results.append(harness_a.runtime.mailbox.submit(
                    epoch_a,
                    {
                        "request_id": "session-a-request",
                        "tool": "promptgraph_project_summary",
                        "arguments": {},
                    },
                ))

            producer = threading.Thread(target=test_only_producer)
            producer.start()
            await asyncio.to_thread(producer.join, 2)
            assert not producer.is_alive()
            assert [item.status for item in producer_results] == ["accepted"]

            # This request arrives after the second session's initial
            # fragment tick but before its ordinary full-run service point.
            # The same full run must pick it up without a second wake.
            def test_only_b_producer():
                producer_thread_ids.append(threading.get_ident())
                producer_results.append(harness_b.runtime.mailbox.submit(
                    epoch_b,
                    {
                        "request_id": "session-b-request",
                        "tool": "promptgraph_project_summary",
                        "arguments": {},
                    },
                ))

            b_producer = threading.Thread(target=test_only_b_producer)
            b_producer.start()
            await asyncio.to_thread(b_producer.join, 2)
            assert not b_producer.is_alive()
            assert [item.status for item in producer_results] == ["accepted", "accepted"]
            harness_b.release_before_service.set()
            await _wait(harness_b.first_run_finished)

            fragment_state = ClientState()
            fragment_state.fragment_id = harness_a.fragment_id
            session_a.request_rerun(fragment_state)
            await _wait(harness_a.request_run_finished)

            assert harness_a.run_count == 2
            assert harness_b.run_count == 1
            assert len(dispatch_calls) == 2
            calls_by_session = {call["session"]: call for call in dispatch_calls}
            call_a = calls_by_session["a"]
            call_b = calls_by_session["b"]
            assert call_a["run_token"] == call_a["current_token"]
            assert call_a["request"]["request_id"] == "session-a-request"
            assert call_a["thread_id"] == harness_a.run_observations[-1]["thread_id"]
            assert call_b["run_token"] == call_b["current_token"]
            assert call_b["request"]["request_id"] == "session-b-request"
            assert call_b["thread_id"] == harness_b.run_observations[-1]["thread_id"]
            assert call_a["thread_id"] not in producer_thread_ids
            assert call_b["thread_id"] not in producer_thread_ids
            assert harness_a.runtime.mailbox.state == "reply_ready"
            assert harness_b.runtime.mailbox.state == "reply_ready"
            assert project_a == before_a
            assert project_b == before_b

            reply = harness_a.runtime.mailbox.consume_reply(epoch_a)
            assert reply.status == "completed"
            assert reply.reply["request_id"] == "session-a-request"
            assert reply.reply["status"] == "completed"
            assert reply.reply["result"]["ok"] is True
            assert harness_a.runtime.mailbox.state == "idle"
            b_reply = harness_b.runtime.mailbox.consume_reply(epoch_b)
            assert b_reply.status == "completed"
            assert b_reply.reply["request_id"] == "session-b-request"
        finally:
            for session, harness, harness_name in cleanup_items:
                await _cleanup_app_session(session, harness, harness_name)

    try:
        asyncio.run(exercise())
    finally:
        Runtime._instance = previous_runtime
        sys.modules["__main__"] = previous_main
        PagesManager.uses_pages_directory = previous_pages_mode
        config_context.__exit__(None, None, None)


def test_host_service_rejects_stale_run_token_before_dispatch(monkeypatch):
    runtime = session_pump.ProjectAgentSessionRuntime()
    project = _project("stale")
    state = {
        "project": project,
        "current_project_path": "",
        PROJECT_CAPTURE_RUN_TOKEN_KEY: "current-run",
    }
    runtime.begin_full_app_run(project, "")
    mailbox = runtime.mailbox
    mailbox.submit(mailbox.target_epoch, {"request_id": "req", "tool": "x", "arguments": {}})
    calls = []
    monkeypatch.setattr(
        session_pump,
        "dispatch_project_agent_request",
        lambda *_args: calls.append(True),
    )

    assert session_pump.service_project_agent_session_request(
        runtime,
        state,
        "old-run",
    ) == "stale_run"
    assert calls == []
    assert mailbox.state == "pending"


def test_session_target_epochs_and_cleanup_are_isolated():
    runtime_a = session_pump.ProjectAgentSessionRuntime()
    runtime_b = session_pump.ProjectAgentSessionRuntime()
    project_a = _project("isolation-a")
    project_b = _project("isolation-b")

    epoch_a = runtime_a.synchronize_target(project_a, r"C:\Projects\a\project.json")
    epoch_b = runtime_b.synchronize_target(project_b, r"C:\Projects\b\project.json")
    assert epoch_a != epoch_b

    assert runtime_a.mailbox.submit(
        epoch_a,
        {"request_id": "a-old-target", "tool": "x", "arguments": {}},
    ).status == "accepted"
    assert runtime_b.mailbox.state == "idle"

    replacement_a = _project("isolation-a-replacement")
    replacement_epoch_a = runtime_a.synchronize_target(
        replacement_a,
        r"C:\Projects\a\project.json",
    )
    assert replacement_epoch_a != epoch_a
    assert runtime_b.mailbox.target_epoch == epoch_b
    assert runtime_b.mailbox.state == "idle"
    assert runtime_a.mailbox.consume_reply(replacement_epoch_a).status == "stale_target"

    runtime_a.close()
    assert runtime_a.mailbox.state == "closed"
    assert runtime_b.mailbox.target_epoch == epoch_b
    assert runtime_b.mailbox.submit(
        epoch_b,
        {"request_id": "b-still-open", "tool": "x", "arguments": {}},
    ).status == "accepted"
    runtime_b.close()


def test_request_arriving_during_full_run_is_serviceable_without_second_wake():
    runtime = session_pump.ProjectAgentSessionRuntime()
    project = _project("during-run")
    state = {
        "project": project,
        "current_project_path": "",
        PROJECT_CAPTURE_RUN_TOKEN_KEY: "run-1",
    }
    runtime.begin_full_app_run(project, "")
    assert runtime.mailbox.submit(
        runtime.mailbox.target_epoch,
        {"request_id": "arrived-after-start", "tool": "x", "arguments": {}},
    ).status == "accepted"
    assert runtime.mailbox.fragment_tick() is False
    claim = runtime.mailbox._claim_for_service(runtime.mailbox.target_epoch)
    assert claim is not None
