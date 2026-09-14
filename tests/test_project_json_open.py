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
    publication = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
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
    for call in ast.walk(ast.Module(body=[node, publication], type_ignores=[])):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
            name = call.func.id
            if name.startswith("reset_") or name in {
                "ensure_current_project_folder_layout", "clear_module_rename_preview",
                "sync_text_areas", "save_settings",
            }:
                namespace[name] = lambda *args, name=name: events.append(name)
    exec(compile(ast.Module(body=[node, publication], type_ignores=[]), "app.py", "exec"), namespace)
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


PUBLICATION_RESETS = [
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


@pytest.mark.parametrize("failure", [None, "reset_graph_project_session_state", "cache", "layout", "sync_text_areas", "save_settings"])
def test_publication_order_and_partial_updates(failure):
    import os

    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    names = {"publish_loaded_project_to_session", "load_project_json_into_session",
             "ensure_current_project_folder_layout", "_get_persistent_line_candidates"}
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in names]
    events = []
    error = RuntimeError("publication failed")

    class State(dict):
        __getattr__ = dict.__getitem__

        def __setattr__(self, key, value):
            events.append(key)
            self[key] = value

    old_project = object()
    old_cache = {"old": []}
    state = State(project=old_project, history=["undo"], settings={},
                  line_generated_candidates=old_cache, current_project_path="old.json",
                  startup_project_auto_open_error="old error")
    record = {"path": "candidate.png"}
    candidates = [record]
    line = SimpleNamespace(id="line", generated_candidates=candidates)
    empty = SimpleNamespace(id="empty", generated_candidates=None)
    separator = SimpleNamespace(id="separator", line_type="separator", generated_candidates=[record])
    project = Project(source_directory="")
    project.prompt_lines = [line, empty, separator]

    def step(name, *args):
        events.append(name)
        if failure == name:
            raise error

    def normalize(value):
        step("cache")
        return list(value)  # Real accessor writes the normalized list back to the line.

    namespace = {
        "os": SimpleNamespace(path=SimpleNamespace(exists=lambda path: True, abspath=os.path.abspath)),
        "st": SimpleNamespace(session_state=state, warning=lambda message: step("warning")),
        "prepare_project_json_open": lambda *args, **kwargs: (step("prepare"), project)[1],
        "ensure_original_image_set_route": object(), "profile_block": nullcontext,
        "_line_candidate_key": lambda line: line.id,
        "_normalize_candidate_records": normalize,
        "ensure_project_folder_layout": lambda path: step("layout", path),
        "remember_project": lambda settings, path: (step("remember"), settings)[1],
    }
    for name in PUBLICATION_RESETS + ["clear_module_rename_preview", "sync_text_areas", "save_settings"]:
        namespace[name] = lambda *args, name=name: step(name)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    expected = ["prepare", "history", *PUBLICATION_RESETS, "project", "cache", "cache", "cache",
                "line_generated_candidates", "current_project_path", "layout", "project_folder_layout_ready",
                "last_saved_at", "autosave_feedback", "focused_line_id", "selected_node_ids", "connect_mode",
                "clear_module_rename_preview", "sync_text_areas", "remember", "settings", "save_settings"]
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
    assert state.project is (project if "project" in events else old_project)
    if "line_generated_candidates" in events:
        assert state.line_generated_candidates == {"line": [record]}
        assert line.generated_candidates is not candidates
        assert state.line_generated_candidates["line"] is not line.generated_candidates
        assert state.line_generated_candidates["line"][0] is line.generated_candidates[0] is record
        assert empty.generated_candidates == []
        assert separator.generated_candidates[0] is record
        assert state.current_project_path == os.path.abspath("relative/project.json")
    else:
        assert state.line_generated_candidates is old_cache
        assert state.current_project_path == "old.json"


@pytest.mark.parametrize("layout_error", [False, True])
def test_layout_oserror_warns_and_publication_continues(layout_error):
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
             and n.name in {"publish_loaded_project_to_session", "ensure_current_project_folder_layout"}]
    state = SimpleNamespace()
    warnings = []
    synced = []

    def layout(path):
        assert path == "/absolute/project.json"
        if layout_error:
            raise OSError("denied")

    namespace = {"st": SimpleNamespace(session_state=state, warning=warnings.append),
                 "os": SimpleNamespace(path=SimpleNamespace(abspath=lambda path: "/absolute/project.json")),
                 "ensure_project_folder_layout": layout,
                 "clear_module_rename_preview": lambda: None,
                 "sync_text_areas": lambda: synced.append(state.project)}
    namespace.update({name: lambda: None for name in PUBLICATION_RESETS})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    project = Project(source_directory="")
    assert namespace["publish_loaded_project_to_session"](project, "project.json") is None
    assert synced == [project]
    assert state.project_folder_layout_ready is (not layout_error)
    assert warnings == (["Project folders could not be created: denied"] if layout_error else [])
    assert state.last_saved_at == state.autosave_feedback == ""
    assert state.focused_line_id is None
    assert state.selected_node_ids == []
    assert state.connect_mode is False


def test_manual_caller_owns_preparation_settings_and_cleanup():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    functions = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    caller = ast.get_source_segment(source, functions["load_project_json_into_session"])
    helper = ast.get_source_segment(source, functions["publish_loaded_project_to_session"])
    ordered = ["os.path.exists", "prepare_project_json_open(",
               "publish_loaded_project_to_session(project, project_path)",
               "remember_project(", "save_settings(", 'pop("startup_project_auto_open_error", None)', "return True"]
    positions = [caller.index(token) for token in ordered]
    assert positions == sorted(positions)
    for token in ordered[:2] + ordered[3:]:
        assert token not in helper
    assert "st.session_state.project =" not in caller
