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
    publisher = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                     and n.name == "publish_loaded_project_to_session")
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
    for call in ast.walk(ast.Module(body=[node, publisher], type_ignores=[])):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            name = call.func.id
            if name.startswith("reset_") or name in {
                "ensure_current_project_folder_layout", "clear_module_rename_preview",
                "sync_text_areas", "save_settings",
            }:
                namespace[name] = lambda *args, name=name: events.append(name)
    exec(compile(ast.Module(body=[node, publisher], type_ignores=[]), "app.py", "exec"), namespace)
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


@pytest.mark.parametrize("failure", [None, "reset_graph_project_session_state", "cache", "sync_text_areas", "save_settings"])
def test_publication_order_and_partial_updates(failure):
    import os

    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    names = {"load_project_json_into_session", "publish_loaded_project_to_session"}
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in names]
    events = []
    error = RuntimeError("publication failed")

    class State(dict):
        __getattr__ = dict.__getitem__

        def __setattr__(self, key, value):
            events.append(key)
            self[key] = value

        def pop(self, key, default=None):
            events.append("pop:" + key)
            return super().pop(key, default)

    old_project = object()
    old_cache = {"old": []}
    settings = {}
    state = State(project=old_project, history=["undo"], settings=settings,
                  line_generated_candidates=old_cache, current_project_path="old.json",
                  startup_project_auto_open_error="old error", focused_line_id="old")
    line = SimpleNamespace(id="one")
    project = SimpleNamespace(prompt_lines=[line])
    record = {"path": "image.png"}
    candidates = [record]

    def step(name, result=None):
        events.append(name)
        if name == failure:
            raise error
        return result

    def cache(value):
        assert value is line
        return step("cache", candidates)

    def remember(value, path):
        assert value is settings
        assert path == os.path.abspath("relative/project.json")
        return step("remember_project", {"remembered": path})

    namespace = {
        "os": SimpleNamespace(path=SimpleNamespace(exists=lambda path: True, abspath=os.path.abspath)),
        "st": SimpleNamespace(session_state=state),
        "prepare_project_json_open": lambda *args, **kwargs: step("prepare", project),
        "ensure_original_image_set_route": object(), "profile_block": nullcontext,
        "_line_candidate_key": lambda value: step("key", value.id),
        "_get_persistent_line_candidates": cache,
        "remember_project": remember,
    }
    for name in RESET_ORDER + ["ensure_current_project_folder_layout", "clear_module_rename_preview", "sync_text_areas", "save_settings"]:
        namespace[name] = lambda *args, name=name: step(name)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    expected = ["prepare", "history", *RESET_ORDER, "project", "cache", "key", "cache",
                "line_generated_candidates", "current_project_path", "ensure_current_project_folder_layout",
                "last_saved_at", "autosave_feedback", "focused_line_id", "selected_node_ids", "connect_mode",
                "clear_module_rename_preview", "sync_text_areas", "remember_project", "settings", "save_settings",
                "pop:startup_project_auto_open_error"]
    if failure:
        with pytest.raises(RuntimeError) as caught:
            namespace["load_project_json_into_session"]("relative/project.json")
        assert caught.value is error
        assert events == expected[:expected.index(failure) + 1]
        assert state.startup_project_auto_open_error == "old error"
    else:
        assert namespace["load_project_json_into_session"]("relative/project.json") is True
        assert events == expected
        assert "startup_project_auto_open_error" not in state
    assert state.history == []
    assert state.project is (old_project if failure in RESET_ORDER else project)
    if failure in RESET_ORDER or failure == "cache":
        assert state.line_generated_candidates is old_cache
        assert state.current_project_path == "old.json"
        assert state.focused_line_id == "old"
    else:
        assert state.line_generated_candidates["one"] is not candidates
        assert state.line_generated_candidates["one"][0] is record
        assert state.current_project_path == os.path.abspath("relative/project.json")
        assert state.focused_line_id is None
        assert state.selected_node_ids == []
        assert state.connect_mode is False
    if failure != "save_settings" and failure is not None:
        assert state.settings is settings


def test_real_candidate_mutation_and_layout_oserror_continue():
    import os

    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    names = {"publish_loaded_project_to_session", "_get_persistent_line_candidates",
             "_line_candidate_key", "_normalize_candidate_record", "_normalize_candidate_records",
             "ensure_current_project_folder_layout"}
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in names]
    class State(dict):
        __getattr__ = dict.__getitem__
        __setattr__ = dict.__setitem__

    nested = {"keep": True}
    original = [{"path": "a.png", "nested": nested}, {"path": "a.png"}]
    line = SimpleNamespace(id=1, generated_candidates=original)
    empty = SimpleNamespace(id=2, generated_candidates=None)
    separator = SimpleNamespace(id=3, line_type="separator", generated_candidates=original)
    project = SimpleNamespace(prompt_lines=[line, empty, separator])
    state = State()
    events = []

    def layout(path):
        assert path == os.path.abspath("relative/project.json")
        assert state.project is project
        events.append("layout")
        raise OSError("denied")

    namespace = {
        "os": os, "st": SimpleNamespace(session_state=state, warning=lambda message: events.append(message)),
        "_candidate_path": lambda candidate: candidate.get("path", "") if isinstance(candidate, dict) else candidate,
        "_normalize_candidate_path": lambda path: path,
        "ensure_project_folder_layout": layout,
        "clear_module_rename_preview": lambda: events.append("clear preview"),
        "sync_text_areas": lambda: events.append("sync"),
    }
    namespace.update({name: lambda: None for name in RESET_ORDER})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    assert namespace["publish_loaded_project_to_session"](project, "relative/project.json") is None
    assert state.project is project
    assert line.generated_candidates is not original
    assert len(line.generated_candidates) == 1
    assert line.generated_candidates[0] is not original[0]
    assert state.line_generated_candidates == {"1": line.generated_candidates}
    assert state.line_generated_candidates["1"] is not line.generated_candidates
    assert state.line_generated_candidates["1"][0] is line.generated_candidates[0]
    assert line.generated_candidates[0]["nested"] is nested
    assert empty.generated_candidates == []
    assert separator.generated_candidates is original
    assert state.project_folder_layout_ready is False
    assert events == ["layout", "Project folders could not be created: denied", "clear preview", "sync"]


def test_manual_caller_keeps_preparation_and_settings_outside_publication():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    functions = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    def calls(name):
        return [n.func.id for n in ast.walk(functions[name])
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    caller = calls("load_project_json_into_session")
    publisher = calls("publish_loaded_project_to_session")
    for name in ("prepare_project_json_open", "remember_project", "save_settings"):
        assert caller.count(name) == 1
        assert name not in publisher
    assert caller.count("publish_loaded_project_to_session") == 1
    owners = [name for name in functions if "publish_loaded_project_to_session" in calls(name)]
    assert owners == ["load_project_json_into_session"]
