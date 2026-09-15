import ast
from datetime import datetime
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.project import Project


SOURCE = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
RESETS = [
    "reset_lightweight_fork_session_state",
    "reset_gallery_route_action_session_state",
    "reset_gallery_selected_route_session_state",
    "reset_management_workspace_session_state",
    "reset_graph_project_session_state",
    "reset_project_assets_operation_state",
    "reset_module_attribute_authoring_project_session_state",
    "reset_insert_module_reference_project_session_state",
    "reset_module_candidate_project_session_state",
    "reset_attribute_group_swap_project_session_state",
    "reset_module_edit_scope_project_session_state",
]
PUBLICATION = [
    "history", *RESETS, "project", "abspath", "current_project_path", "layout",
    "project_folder_layout_ready", "now", "last_saved_at", "autosave_feedback",
    "focused_line_id", "highlighted_line_id", "selected_node_ids", "selected_lines",
    "connect_mode", "connect_nodes", "line_generated_candidates",
    "clear_module_rename_preview", "sync_text_areas",
]
EVENTS = ["construct", "graph", *PUBLICATION, "remember", "settings", "save_settings",
          "pop:startup_project_auto_open_error"]


def harness(failure=None):
    events = []
    error = RuntimeError("step failed")

    def step(name):
        events.append(name)
        if name == failure:
            raise error

    class State(dict):
        __getattr__ = dict.__getitem__

        def __setattr__(self, key, value):
            step(key)
            self[key] = value

        def pop(self, key, default=None):
            step("pop:" + key)
            return super().pop(key, default)

    state = State(project=object(), history=["undo"], settings={"old": True},
                  current_project_path="old.json", last_saved_at="old timestamp",
                  autosave_feedback="old feedback", focused_line_id="old",
                  highlighted_line_id="old", selected_node_ids=["old"],
                  selected_lines={"old": True}, connect_mode=True, connect_nodes=["old"],
                  line_generated_candidates={"old": []}, startup_project_auto_open_error="old error")
    before = dict(state)
    constructed = Project(source_directory="")
    replacement = Project(source_directory="graph replacement")
    lines = replacement.prompt_lines

    def construct(**kwargs):
        assert kwargs == {"source_directory": ""}
        assert state == before
        step("construct")
        return constructed

    def graph(project):
        assert project is constructed
        assert state == before
        step("graph")
        return replacement

    def layout(path):
        assert path == os.path.abspath("relative/project.json")
        assert state.project is replacement
        step("layout")
        if failure == "layout_oserror":
            raise OSError("denied")

    def remember(settings, path):
        assert settings is before["settings"]
        assert path == state.current_project_path
        step("remember")
        return {"recent": path}

    namespace = {
        "st": SimpleNamespace(session_state=state, warning=lambda message: events.append(("warning", message))),
        "os": SimpleNamespace(path=SimpleNamespace(abspath=lambda path: (step("abspath"), os.path.abspath(path))[1])),
        "datetime": SimpleNamespace(now=lambda: (step("now"), datetime(2026, 9, 15, 12, 34, 56))[1]),
        "Project": construct, "build_graph": graph,
        "ensure_project_folder_layout": layout, "remember_project": remember,
    }
    for name in [*RESETS, "clear_module_rename_preview", "sync_text_areas", "save_settings"]:
        namespace[name] = lambda *args, name=name: step(name)
    names = {"set_new_workspace_project", "publish_new_project_to_session", "ensure_current_project_folder_layout"}
    nodes = [n for n in ast.parse(SOURCE).body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    return SimpleNamespace(ns=namespace, state=state, before=before, events=events,
                           error=error, project=replacement, lines=lines)


def test_new_project_order_identity_and_state():
    h = harness()
    assert h.ns["set_new_workspace_project"]("relative/project.json") is None
    assert h.events == EVENTS
    assert h.state.project is h.project
    assert h.project.prompt_lines is h.lines
    assert h.state.last_saved_at == "2026-09-15 12:34:56"
    assert h.state.autosave_feedback == "project created"
    for key in ["focused_line_id", "highlighted_line_id"]:
        assert h.state[key] is None
    for key in ["history", "selected_node_ids", "connect_nodes"]:
        assert h.state[key] == []
        assert h.before[key] == ["undo" if key == "history" else "old"]
    for key in ["selected_lines", "line_generated_candidates"]:
        assert h.state[key] == {}
        assert h.state[key] is not h.before[key]
    assert h.state.connect_mode is False
    assert "startup_project_auto_open_error" not in h.state


@pytest.mark.parametrize("failure", ["construct", "graph", *RESETS, "layout", "now",
                                     "clear_module_rename_preview", "sync_text_areas", "save_settings"])
def test_failures_propagate_and_retain_partial_updates(failure):
    h = harness(failure)
    with pytest.raises(RuntimeError) as caught:
        h.ns["set_new_workspace_project"]("relative/project.json")
    assert caught.value is h.error
    assert h.events == EVENTS[:EVENTS.index(failure) + 1]
    if failure in {"construct", "graph"}:
        assert h.state == h.before
    else:
        assert h.state.history == []
        assert h.state.project is (h.before["project"] if failure in RESETS else h.project)
        if failure in RESETS:
            assert h.state.current_project_path == "old.json"
        if failure in [*RESETS, "layout", "now"]:
            assert h.state.last_saved_at == "old timestamp"
            assert h.state.line_generated_candidates is h.before["line_generated_candidates"]
        else:
            assert h.state.line_generated_candidates == {}
            assert h.state.last_saved_at == "2026-09-15 12:34:56"
        if failure == "save_settings":
            assert h.state.settings == {"recent": h.state.current_project_path}
        else:
            assert h.state.settings is h.before["settings"]
    assert h.state.startup_project_auto_open_error == "old error"


def test_layout_oserror_warns_and_continues():
    h = harness("layout_oserror")
    h.ns["set_new_workspace_project"]("relative/project.json")
    expected = EVENTS.copy()
    expected.insert(expected.index("project_folder_layout_ready") + 1,
                    ("warning", "Project folders could not be created: denied"))
    assert h.events == expected
    assert h.state.project_folder_layout_ready is False
    assert h.state.autosave_feedback == "project created"


def test_publication_seam_keeps_construction_and_settings_in_caller():
    h = harness()
    assert h.ns["publish_new_project_to_session"](h.project, "relative/project.json") is None
    assert h.events == PUBLICATION
    assert h.state.project is h.project
    assert h.state.settings is h.before["settings"]
    assert h.state.startup_project_auto_open_error == "old error"

    h = harness()
    def publish(project, path):
        assert project is h.project
        assert path == "relative/project.json"
        h.events.append("publish")
    h.ns["publish_new_project_to_session"] = publish
    h.ns["set_new_workspace_project"]("relative/project.json")
    assert h.events == ["construct", "graph", "publish", "remember", "settings",
                        "save_settings", "pop:startup_project_auto_open_error"]


@pytest.mark.parametrize("failure", [None, "construct", "graph", "sync_text_areas", "save_settings"])
def test_ui_success_branch_owns_discovery_feedback_and_rerun(failure):
    h = harness(failure)
    renderer = next(n for n in ast.parse(SOURCE).body
                    if isinstance(n, ast.FunctionDef) and n.name == "render_new_project_management_section")
    success = next(n.orelse for n in ast.walk(renderer)
                   if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "error")
    h.ns.update(project_path="relative/project.json",
                request_project_directory_discovery_refresh=lambda: h.events.append("discovery"))
    h.ns["st"].success = lambda message: h.events.append(("success", message))
    h.ns["st"].rerun = lambda: h.events.append("rerun")
    code = compile(ast.Module(body=success, type_ignores=[]), "app.py", "exec")
    if failure:
        with pytest.raises(RuntimeError) as caught:
            exec(code, h.ns)
        assert caught.value is h.error
        assert h.events == EVENTS[:EVENTS.index(failure) + 1]
    else:
        exec(code, h.ns)
        assert h.events == EVENTS + ["discovery", ("success", "プロジェクトを作成しました。"), "rerun"]
