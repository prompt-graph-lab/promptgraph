import ast
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.project import Project


RESET_ORDER = [
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


@pytest.fixture(scope="module")
def app_functions():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    return {node.name: node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef)}


@pytest.mark.parametrize("failure", [
    None, "construct", "graph", "reset_graph_project_session_state",
    "layout", "sync_text_areas", "save_settings", "layout_oserror",
])
def test_new_project_publication_order_identity_and_partial_failure(app_functions, failure):
    events = []
    error = OSError("denied") if failure == "layout_oserror" else RuntimeError("failed")

    class State(dict):
        __getattr__ = dict.__getitem__

        def __setattr__(self, name, value):
            events.append(name)
            self[name] = value

        def pop(self, name, default=None):
            events.append("pop:" + name)
            return super().pop(name, default)

    old_project = object()
    old_history = ["undo"]
    settings = {}
    old_selection = ["old node"]
    state = State(project=old_project, history=old_history, settings=settings,
                  current_project_path="old.json", selected_node_ids=old_selection,
                  startup_project_auto_open_error="old error")
    before = dict(state)
    constructed = Project(source_directory="")
    prepared = Project(source_directory="graph result")
    line_alias = prepared.prompt_lines
    path = os.path.join("relative", "new-project.json")
    absolute_path = os.path.abspath(path)
    remembered = {"recent": absolute_path}

    def step(name, result=None):
        events.append(name)
        if failure == name:
            raise error
        return result

    def construct(**kwargs):
        assert kwargs == {"source_directory": ""}
        assert state == before
        return step("construct", constructed)

    def graph(project):
        assert project is constructed
        assert state == before
        project.source_directory = "graph mutation"
        return step("graph", prepared)

    def layout(value):
        assert value is state.current_project_path
        assert value == absolute_path
        assert state.project is prepared
        step("layout")
        if failure == "layout_oserror":
            raise error

    def now():
        return step("now", datetime(2026, 1, 2, 3, 4, 5))

    def remember(value, value_path):
        assert value is settings
        assert value_path is state.current_project_path
        return step("remember_project", remembered)

    def save(value):
        assert value is remembered
        step("save_settings")

    namespace = {
        "st": SimpleNamespace(session_state=state, warning=lambda text: step("warning:" + text)),
        "os": os, "datetime": SimpleNamespace(now=now),
        "Project": construct, "build_graph": graph,
        "ensure_project_folder_layout": layout,
        "remember_project": remember, "save_settings": save,
    }
    for name in RESET_ORDER + ["clear_module_rename_preview", "sync_text_areas"]:
        namespace[name] = lambda name=name: step(name)
    nodes = [app_functions[name] for name in (
        "set_new_workspace_project", "publish_new_project_to_session",
        "ensure_current_project_folder_layout",
    )]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    expected = [
        "construct", "graph", "history", *RESET_ORDER, "project", "current_project_path",
        "layout", "project_folder_layout_ready",
    ]
    if failure == "layout_oserror":
        expected.append("warning:Project folders could not be created: denied")
    expected += [
        "now", "last_saved_at", "autosave_feedback", "focused_line_id", "highlighted_line_id",
        "selected_node_ids", "selected_lines", "connect_mode", "connect_nodes",
        "line_generated_candidates", "clear_module_rename_preview", "sync_text_areas",
        "remember_project", "settings", "save_settings", "pop:startup_project_auto_open_error",
    ]
    if failure and failure != "layout_oserror":
        with pytest.raises(type(error)) as caught:
            namespace["set_new_workspace_project"](path)
        assert caught.value is error
        assert events == expected[:expected.index(failure) + 1]
        assert state.startup_project_auto_open_error == "old error"
    else:
        assert namespace["set_new_workspace_project"](path) is None
        assert events == expected
        assert "startup_project_auto_open_error" not in state

    if failure in ("construct", "graph"):
        assert state == before
        assert state.history is old_history
    else:
        assert state.history == []
        assert old_history == ["undo"]
        if failure in RESET_ORDER:
            assert state.project is old_project
            assert state.current_project_path == "old.json"
        else:
            assert state.project is prepared
            assert prepared.prompt_lines is line_alias
            assert constructed.source_directory == "graph mutation"
            assert state.current_project_path == absolute_path
            if failure != "layout":
                assert state.project_folder_layout_ready is (failure != "layout_oserror")
                assert state.last_saved_at == "2026-01-02 03:04:05"
                assert state.autosave_feedback == "project created"
                assert state.focused_line_id is None
                assert state.highlighted_line_id is None
                assert state.selected_node_ids == []
                assert state.selected_lines == {}
                assert state.connect_mode is False
                assert state.connect_nodes == []
                assert state.line_generated_candidates == {}
        assert old_selection == ["old node"]
    if "settings" in events:
        assert state.settings is remembered
    else:
        assert state.settings is settings


def test_publication_boundary_keeps_construction_and_persistence_in_caller(app_functions):
    caller = app_functions["set_new_workspace_project"]
    publisher = app_functions["publish_new_project_to_session"]
    assert ast.unparse(caller.body[0]) == "project = build_graph(Project(source_directory=''))"
    assert ast.unparse(caller.body[1]) == "publish_new_project_to_session(project, project_path)"
    assert ast.unparse(caller.body[2]) == (
        "st.session_state.settings = remember_project(st.session_state.settings, "
        "st.session_state.current_project_path)"
    )
    assert ast.unparse(caller.body[3]) == "save_settings(st.session_state.settings)"
    assert ast.unparse(caller.body[4]) == "st.session_state.pop('startup_project_auto_open_error', None)"
    assert len(caller.body) == 5

    def calls(node):
        return [call.func.id for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)]

    assert not {"Project", "build_graph", "remember_project", "save_settings",
                "request_project_directory_discovery_refresh"}.intersection(calls(publisher))
    assert [name for name, node in app_functions.items()
            if "publish_new_project_to_session" in calls(node)] == ["set_new_workspace_project"]
