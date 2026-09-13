import ast
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core import project_json_open
from core.project import Project


@pytest.mark.parametrize("failure", [None, "load", "routes", "graph"])
def test_preparation_order_identity_and_failure(failure):
    events = []
    project = Project(source_directory="")
    alias = project.prompt_lines
    error = ValueError("preparation failed")

    def step(name):
        events.append(name)
        if failure == name:
            raise error

    def load(path):
        assert path == "relative/project.json"
        step("load")
        return project

    def routes(value):
        assert value is project
        step("routes")
        value.source_directory = "route mutation"
        return False  # Completion's falsey result must not replace the Project.

    def graph(value):
        assert value is project
        assert value.source_directory == "route mutation"
        assert value.prompt_lines is alias
        step("graph")
        return value

    @contextmanager
    def profile(label):
        events.append(("enter", label))
        try:
            yield
        finally:
            events.append(("exit", label))

    with patch.object(project_json_open, "load_project_from_json", load), patch.object(
        project_json_open, "build_graph", graph
    ):
        def prepare():
            return project_json_open.prepare_project_json_open(
                "relative/project.json", complete_routes=routes, profile_block=profile
            )

        if failure:
            with pytest.raises(ValueError) as caught:
                prepare()
            assert caught.value is error
        else:
            assert prepare() is project
            assert project.prompt_lines is alias

    expected = [
        ("enter", "Project load: read JSON"),
        "load",
        ("exit", "Project load: read JSON"),
    ]
    if failure != "load":
        expected.append("routes")
        if failure != "routes":
            expected.extend([
                ("enter", "Project load: build graph"),
                "graph",
                ("exit", "Project load: build graph"),
            ])
    assert events == expected


def test_returns_graph_result_without_copy_or_fallback():
    replacement = Project(source_directory="graph result")
    with patch.object(
        project_json_open,
        "load_project_from_json",
        return_value=Project(source_directory="loaded"),
    ), patch.object(
        project_json_open,
        "build_graph",
        return_value=replacement,
    ):
        result = project_json_open.prepare_project_json_open(
            "relative/project.json",
            complete_routes=lambda project: False,
            profile_block=lambda label: nullcontext(),
        )

    assert result is replacement


@pytest.mark.parametrize("failure", [None, "load", "routes", "graph"])
def test_caller_publishes_only_after_preparation(failure):
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                and n.name == "load_project_json_into_session")
    events = []

    class State(dict):
        __getattr__ = dict.__getitem__

        def __setattr__(self, key, value):
            events.append(key)
            self[key] = value

    old_project = object()
    state = State(project=old_project, history=["undo"], settings={})
    before = dict(state)
    project = Project(source_directory="")
    error = RuntimeError("failed")

    def step(name, value):
        assert state == before
        events.append(name)
        if name == failure:
            raise error
        return value

    namespace = {
        "os": SimpleNamespace(path=SimpleNamespace(exists=lambda path: True, abspath=lambda path: path)),
        "st": SimpleNamespace(session_state=state),
        "prepare_project_json_open": project_json_open.prepare_project_json_open,
        "ensure_original_image_set_route": lambda value: step("routes", False),
        "profile_block": nullcontext,
        "remember_project": lambda settings, path: settings,
    }
    for call in ast.walk(node):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            name = call.func.id
            if name.startswith("reset_") or name in {
                "ensure_current_project_folder_layout", "clear_module_rename_preview",
                "sync_text_areas", "save_settings",
            }:
                namespace[name] = lambda *args, name=name: events.append(name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), "app.py", "exec"), namespace)
    with patch.object(project_json_open, "load_project_from_json", lambda path: step("load", project)), patch.object(
        project_json_open, "build_graph", lambda value: step("graph", value)
    ):
        if failure:
            with pytest.raises(RuntimeError) as caught:
                namespace[node.name]("project.json")
            assert caught.value is error
            assert state == before
            assert events == ["load", "routes", "graph"][:["load", "routes", "graph"].index(failure) + 1]
        else:
            assert namespace[node.name]("project.json") is True
            assert events[:4] == ["load", "routes", "graph", "history"]
            assert state.project is project
            assert state.history == []
            assert state.line_generated_candidates == {}
            assert state.current_project_path == "project.json"
            assert events.index("reset_module_edit_scope_project_session_state") < events.index("project")
            assert events.index("project") < events.index("sync_text_areas") < events.index("save_settings")
