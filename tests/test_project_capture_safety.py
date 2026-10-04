"""Project capture safety tests, including real Streamlit 1.60.0 reruns."""

import asyncio
import copy
import json
import sys
import threading
import types
import uuid
from unittest.mock import MagicMock

import pytest
import streamlit
from streamlit.runtime.app_session import AppSession
from streamlit.runtime.memory_uploaded_file_manager import MemoryUploadedFileManager
from streamlit.runtime.pages_manager import PagesManager
from streamlit.runtime.runtime import Runtime
from streamlit.runtime.script_data import ScriptData
from streamlit.runtime.scriptrunner.script_cache import ScriptCache
from streamlit.testing.v1.util import patch_config_options

from core.agent_facade import (
    get_illustration,
    list_illustrations,
    observe_scenes,
    preview_batch_replace,
    summarize_project,
)
from core.graph_builder import build_graph
from core.parser import parse_prompt
from core.project import Project, PromptLine
from ui import project_capture_safety as capture_safety


def _line(line_id: str, prompt: str, *, line_type: str | None = None) -> PromptLine:
    return PromptLine(
        id=line_id,
        original_file_name=f"{line_id}.png",
        original_index=0,
        current_index=0,
        original_text=prompt,
        current_text=prompt,
        tokens=parse_prompt(prompt),
        line_type=line_type,
    )


def _project() -> Project:
    return build_graph(Project(
        prompt_lines=[
            _line("baseline", "baseline prompt"),
            _line("scene-1", "First Scene", line_type="separator"),
            _line("illustration-1", "red shirt"),
        ],
        project_metadata={"revision": 0},
    ))


def _set_fast_reruns(monkeypatch, value):
    monkeypatch.setattr(
        capture_safety._streamlit_config,
        "get_option",
        lambda key: value if key == "runner.fastReruns" else None,
    )


def test_fast_reruns_rejects_before_cloning(monkeypatch):
    _set_fast_reruns(monkeypatch, True)
    project = _project()
    session = {"project": project}
    token = capture_safety.begin_project_capture_run(session)

    def must_not_clone(self):
        raise AssertionError("fast-rerun mode must reject before clone")

    monkeypatch.setattr(Project, "clone", must_not_clone)
    result = capture_safety.capture_active_project(session, token)

    assert not result.ok
    assert result.capture is None
    assert result.reason == "overlapping_reruns_enabled"


def test_unknown_rerun_mode_fails_closed(monkeypatch):
    _set_fast_reruns(monkeypatch, None)
    session = {"project": _project()}
    token = capture_safety.begin_project_capture_run(session)

    result = capture_safety.capture_active_project(session, token)

    assert not result.ok
    assert result.reason == "capture_mode_unavailable"


def test_rerun_mode_change_during_clone_discards_snapshot(monkeypatch):
    project = _project()
    session = {"project": project}
    token = capture_safety.begin_project_capture_run(session)
    values = iter((False, True))
    monkeypatch.setattr(
        capture_safety._streamlit_config,
        "get_option",
        lambda key: next(values) if key == "runner.fastReruns" else None,
    )

    result = capture_safety.capture_active_project(session, token)

    assert not result.ok
    assert result.capture is None
    assert result.reason == "capture_mode_changed"


@pytest.mark.parametrize(
    ("project_value", "expected_reason"),
    [(None, "missing_project"), (object(), "invalid_project")],
)
def test_missing_or_invalid_project_fails_closed(monkeypatch, project_value, expected_reason):
    _set_fast_reruns(monkeypatch, False)
    session = {"project": project_value}
    token = capture_safety.begin_project_capture_run(session)

    result = capture_safety.capture_active_project(session, token)

    assert not result.ok
    assert result.reason == expected_reason


def test_missing_or_stale_run_token_fails_closed(monkeypatch):
    _set_fast_reruns(monkeypatch, False)
    session = {"project": _project()}
    token = capture_safety.begin_project_capture_run(session)

    missing = capture_safety.capture_active_project(session, None)
    assert not missing.ok
    assert missing.reason == "run_not_current"

    capture_safety.begin_project_capture_run(session)
    stale = capture_safety.capture_active_project(session, token)
    assert not stale.ok
    assert stale.reason == "run_not_current"


def test_capture_clone_failure_is_bounded_and_does_not_leak(monkeypatch):
    _set_fast_reruns(monkeypatch, False)
    project = _project()
    session = {"project": project}
    token = capture_safety.begin_project_capture_run(session)

    def fail_clone(self):
        raise RuntimeError("C:\\private\\project\\secret.json")

    monkeypatch.setattr(Project, "clone", fail_clone)
    result = capture_safety.capture_active_project(session, token)

    assert not result.ok
    assert result.reason == "capture_failed"
    assert "private" not in repr(result)
    assert session["project"] is project


def test_project_replacement_during_clone_invalidates_capture(monkeypatch):
    _set_fast_reruns(monkeypatch, False)
    project = _project()
    replacement = _project()
    session = {"project": project}
    token = capture_safety.begin_project_capture_run(session)
    original_clone = Project.clone

    def replace_during_clone(self):
        snapshot = original_clone(self)
        session["project"] = replacement
        return snapshot

    monkeypatch.setattr(Project, "clone", replace_during_clone)
    result = capture_safety.capture_active_project(session, token)

    assert not result.ok
    assert result.capture is None
    assert result.reason == "project_changed"
    assert session["project"] is replacement


def test_capture_isolated_snapshot_runs_existing_facade_and_invalidates(monkeypatch):
    _set_fast_reruns(monkeypatch, False)
    project = _project()
    project.prompt_lines[2].current_text = "blue shirt"
    project.prompt_lines[2].tokens = parse_prompt("blue shirt")
    project.project_metadata["revision"] = 7
    session = {"project": project}
    token = capture_safety.begin_project_capture_run(session)

    result = capture_safety.capture_active_project(session, token)

    assert result.ok
    assert result.reason == ""
    captured = result.capture
    assert captured is not None
    snapshot = captured.project
    assert snapshot is not project
    assert snapshot.prompt_lines[2] is not project.prompt_lines[2]
    assert snapshot.prompt_lines[2].current_text == "blue shirt"
    assert snapshot.project_metadata == {"revision": 7}
    assert capture_safety.is_capture_current(session, captured, token)

    request = {
        "illustration_ids": ["illustration-1"],
        "find_text": "blue",
        "replace_text": "green",
        "match_mode": "contains_token",
    }
    before_project = copy.deepcopy(project)
    before_snapshot = copy.deepcopy(snapshot)
    facade_results = {
        "summary": summarize_project(snapshot),
        "scenes": observe_scenes(snapshot),
        "illustrations": list_illustrations(snapshot),
        "illustration": get_illustration(snapshot, "illustration-1"),
        "preview": preview_batch_replace(snapshot, request),
    }
    source_results = {
        "summary": summarize_project(project),
        "scenes": observe_scenes(project),
        "illustrations": list_illustrations(project),
        "illustration": get_illustration(project, "illustration-1"),
        "preview": preview_batch_replace(project, request),
    }
    assert facade_results == source_results
    json.dumps(facade_results)
    assert project == before_project
    assert snapshot == before_snapshot

    project.prompt_lines[2].current_text = "changed live after capture"
    project.project_metadata["revision"] = 8
    assert snapshot.prompt_lines[2].current_text == "blue shirt"
    assert snapshot.project_metadata["revision"] == 7

    snapshot.prompt_lines[2].current_text = "changed snapshot after capture"
    assert project.prompt_lines[2].current_text == "changed live after capture"
    assert project.project_metadata["revision"] == 8

    newer_token = capture_safety.begin_project_capture_run(session)
    assert newer_token != token
    assert not capture_safety.is_capture_current(session, captured, token)
    assert not capture_safety.is_capture_current(session, captured, newer_token)


def test_capture_currentness_rejects_project_replacement(monkeypatch):
    _set_fast_reruns(monkeypatch, False)
    session = {"project": _project()}
    token = capture_safety.begin_project_capture_run(session)
    result = capture_safety.capture_active_project(session, token)
    assert result.ok

    session["project"] = _project()
    assert not capture_safety.is_capture_current(session, result.capture, token)


class _BlockingInfo(dict):
    """Pause Project deepcopy after prompt text but before Project metadata."""

    def __init__(self, started: threading.Event, release: threading.Event):
        super().__init__({"source": "test"})
        self.started = started
        self.release = release

    def __deepcopy__(self, memo):
        self.started.set()
        if not self.release.wait(10):
            raise TimeoutError("test barrier was not released")
        result = dict(self)
        memo[id(self)] = result
        return result


async def _wait(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 10), "timed out waiting for Streamlit run"


async def _make_app_session(tmp_path, harness, *, fast_reruns: bool):
    script_path = tmp_path / f"capture_app_{uuid.uuid4().hex}.py"
    harness_name = f"_promptgraph_capture_harness_{uuid.uuid4().hex}"
    sys.modules[harness_name] = harness
    script_path.write_text(
        f"import streamlit as st\nimport {harness_name} as harness\nharness.run(st.session_state)\n",
        encoding="utf-8",
    )

    overrides = {
        "runner.fastReruns": fast_reruns,
        "server.fileWatcherType": "none",
        "server.runOnSave": False,
    }
    config_context = patch_config_options(overrides)
    config_context.__enter__()
    previous_runtime = Runtime._instance
    previous_main = sys.modules.get("__main__")
    Runtime._instance = MagicMock(spec=Runtime)
    Runtime._instance.media_file_mgr = MagicMock()
    Runtime._instance.cache_storage_manager = MagicMock()
    Runtime._instance.bidi_component_registry = MagicMock()
    previous_pages_mode = PagesManager.uses_pages_directory
    PagesManager.uses_pages_directory = False

    session = AppSession(
        ScriptData(str(script_path)),
        MemoryUploadedFileManager("/capture-test/upload"),
        ScriptCache(),
        lambda: None,
        {"email": "capture-test"},
        session_id_override=f"capture-test-{uuid.uuid4().hex}",
    )
    runners = []
    create_scriptrunner = session._create_scriptrunner

    def record_scriptrunner(rerun_data):
        create_scriptrunner(rerun_data)
        runners.append(session._scriptrunner)

    session._create_scriptrunner = record_scriptrunner
    session._session_state["project"] = harness.project
    harness.session = session
    harness.runners = runners
    harness.run_count = 0
    harness.run_lock = threading.Lock()

    return session, harness_name, config_context, previous_runtime, previous_main, previous_pages_mode


async def _cleanup_app_session(session, harness, harness_name, config_context,
                               previous_runtime, previous_main, previous_pages_mode):
    for event in getattr(harness, "release_events", ()):
        event.set()
    try:
        session.shutdown()
    except Exception:
        pass
    for runner in getattr(harness, "runners", ()):
        thread = getattr(runner, "_script_thread", None)
        if thread is not None:
            await asyncio.to_thread(thread.join, 10)
            assert not thread.is_alive(), "Streamlit ScriptRunner leaked"
    Runtime._instance = previous_runtime
    sys.modules["__main__"] = previous_main
    PagesManager.uses_pages_directory = previous_pages_mode
    config_context.__exit__(None, None, None)
    sys.modules.pop(harness_name, None)


def test_real_fast_rerun_overlap_rejects_capture_and_proves_naive_clone_torn(
    tmp_path, monkeypatch
):
    assert streamlit.__version__ == "1.60.0"

    clone_started = threading.Event()
    release_clone = threading.Event()
    harness = types.ModuleType("fast_rerun_harness")
    project = _project()
    project.prompt_lines[2].source_generation_info = _BlockingInfo(clone_started, release_clone)
    harness.project = project
    harness.release_events = (release_clone,)
    harness.clone_calls = 0
    clone_lock = threading.Lock()
    original_clone = Project.clone

    def counted_clone(self):
        with clone_lock:
            harness.clone_calls += 1
        return original_clone(self)

    monkeypatch.setattr(Project, "clone", counted_clone)

    def run(session_state):
        token = capture_safety.begin_project_capture_run(session_state)
        project_in_run = session_state.get("project")
        with harness.run_lock:
            harness.run_count += 1
            run_number = harness.run_count
        if run_number == 1:
            harness.old_run_token = token
            harness.first_project_reference = project_in_run
            harness.first_started.set()
            harness.naive_snapshot = project_in_run.clone()
            harness.old_clone_finished.set()
        elif run_number == 2:
            harness.new_run_token = token
            harness.old_run_is_current = capture_safety._run_is_current(
                session_state, harness.old_run_token
            )
            harness.new_run_is_current = capture_safety._run_is_current(
                session_state, token
            )
            before_gate_clone_count = harness.clone_calls
            harness.capture_result = capture_safety.capture_active_project(session_state, token)
            harness.gate_clone_count = harness.clone_calls - before_gate_clone_count
            project_in_run.prompt_lines[2].current_text = "new prompt"
            project_in_run.project_metadata["revision"] = 2
            harness.new_run_mutated.set()
            release_clone.set()
            harness.new_run_finished.set()

    harness.run = run
    harness.first_started = threading.Event()
    harness.new_run_mutated = threading.Event()
    harness.old_clone_finished = threading.Event()
    harness.new_run_finished = threading.Event()

    async def exercise():
        with patch_config_options({
            "runner.fastReruns": True,
            "server.fileWatcherType": "none",
            "server.runOnSave": False,
        }):
            session, harness_name, config_context, previous_runtime, previous_main, previous_pages_mode = await _make_app_session(
                tmp_path, harness, fast_reruns=True
            )
            try:
                session.request_rerun(None)
                await _wait(clone_started)
                old_runner = session._scriptrunner
                session.request_rerun(None)
                new_runner = session._scriptrunner
                assert new_runner is not old_runner
                await _wait(harness.new_run_finished)
                await _wait(harness.old_clone_finished)
                assert len(harness.runners) == 2
                assert harness.runners[0] is old_runner
                assert harness.runners[1] is new_runner
                assert harness.capture_result.reason == "overlapping_reruns_enabled"
                assert harness.gate_clone_count == 0
                assert harness.clone_calls == 1
                assert harness.old_run_token != harness.new_run_token
                assert harness.first_project_reference is project
                assert harness.naive_snapshot.prompt_lines[2].current_text == "red shirt"
                assert harness.naive_snapshot.project_metadata["revision"] == 2
                assert not harness.old_run_is_current
                assert harness.new_run_is_current
                assert project.prompt_lines[2].current_text == "new prompt"
            finally:
                await _cleanup_app_session(
                    session, harness, harness_name, config_context,
                    previous_runtime, previous_main, previous_pages_mode,
                )

    asyncio.run(exercise())


def test_real_serialized_rerun_captures_consistent_snapshot_and_runs_facade(
    tmp_path,
):
    assert streamlit.__version__ == "1.60.0"

    harness = types.ModuleType("serialized_rerun_harness")
    harness.project = _project()
    harness.release_events = (threading.Event(),)
    harness.first_started = threading.Event()
    harness.allow_first_finish = harness.release_events[0]
    harness.first_finished = threading.Event()
    harness.second_started = threading.Event()
    harness.second_finished = threading.Event()
    harness.third_finished = threading.Event()
    harness.run_tokens = []
    harness.facade_results = None
    harness.capture = None
    harness.first_runner = None

    def run(session_state):
        token = capture_safety.begin_project_capture_run(session_state)
        with harness.run_lock:
            harness.run_count += 1
            run_number = harness.run_count
        project_in_run = session_state.get("project")
        harness.run_tokens.append(token)
        if run_number == 1:
            harness.first_started.set()
            if not harness.allow_first_finish.wait(10):
                raise TimeoutError("first Streamlit run was not released")
            project_in_run.prompt_lines[2].current_text = "blue shirt"
            project_in_run.prompt_lines[2].tokens = parse_prompt("blue shirt")
            project_in_run.project_metadata["revision"] = 1
            harness.first_finished.set()
        elif run_number == 2:
            harness.second_started.set()
            result = capture_safety.capture_active_project(session_state, token)
            harness.capture_result = result
            harness.capture = result.capture
            assert result.ok
            snapshot = result.capture.project
            request = {
                "illustration_ids": ["illustration-1"],
                "find_text": "blue",
                "replace_text": "green",
                "match_mode": "contains_token",
            }
            harness.facade_results = {
                "summary": summarize_project(snapshot),
                "scenes": observe_scenes(snapshot),
                "illustrations": list_illustrations(snapshot),
                "illustration": get_illustration(snapshot, "illustration-1"),
                "preview": preview_batch_replace(snapshot, request),
            }
            harness.source_facade_results = {
                "summary": summarize_project(project_in_run),
                "scenes": observe_scenes(project_in_run),
                "illustrations": list_illustrations(project_in_run),
                "illustration": get_illustration(project_in_run, "illustration-1"),
                "preview": preview_batch_replace(project_in_run, request),
            }
            harness.current_during_run = capture_safety.is_capture_current(
                session_state, result.capture, token
            )
            project_in_run.prompt_lines[2].current_text = "later live edit"
            project_in_run.project_metadata["revision"] = 2
            harness.second_finished.set()
        elif run_number == 3:
            harness.old_capture_current_in_new_run = capture_safety.is_capture_current(
                session_state, harness.capture, token
            )
            harness.third_finished.set()

    harness.run = run

    async def exercise():
        with patch_config_options({
            "runner.fastReruns": False,
            "server.fileWatcherType": "none",
            "server.runOnSave": False,
        }):
            session, harness_name, config_context, previous_runtime, previous_main, previous_pages_mode = await _make_app_session(
                tmp_path, harness, fast_reruns=False
            )
            try:
                session.request_rerun(None)
                await _wait(harness.first_started)
                original_runner = session._scriptrunner
                session.request_rerun(None)
                assert session._scriptrunner is original_runner
                await asyncio.sleep(0.1)
                assert harness.run_count == 1
                assert not harness.second_started.is_set()
                harness.allow_first_finish.set()
                await _wait(harness.second_finished)
                assert len(harness.runners) == 1
                assert harness.run_tokens[0] != harness.run_tokens[1]
                assert harness.current_during_run
                assert harness.capture.project.prompt_lines[2].current_text == "blue shirt"
                assert harness.capture.project.project_metadata["revision"] == 1
                assert harness.facade_results == harness.source_facade_results
                json.dumps(harness.facade_results)
                live_project = harness.project
                assert live_project.prompt_lines[2].current_text == "later live edit"
                assert live_project.project_metadata["revision"] == 2
                assert harness.capture.project.prompt_lines[2].current_text == "blue shirt"
                assert harness.capture.project.project_metadata["revision"] == 1
                harness.capture.project.prompt_lines[2].current_text = "snapshot-only edit"
                assert live_project.prompt_lines[2].current_text == "later live edit"

                session.request_rerun(None)
                await _wait(harness.third_finished)
                assert harness.run_tokens[2] != harness.run_tokens[1]
                assert not harness.old_capture_current_in_new_run
            finally:
                await _cleanup_app_session(
                    session, harness, harness_name, config_context,
                    previous_runtime, previous_main, previous_pages_mode,
                )

    asyncio.run(exercise())
