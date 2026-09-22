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


def publication_harness(failure=None):
    import os
    from core.candidate_record_normalization import _normalize_candidate_records

    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    names = {
        "load_project_json_into_session", "publish_loaded_project_to_session",
        "ensure_current_project_folder_layout", "_get_persistent_line_candidates",
        "_line_candidate_key",
    }
    nodes = [n for n in ast.parse(source).body
             if isinstance(n, ast.FunctionDef) and n.name in names]
    events = []
    error = RuntimeError("publication failed")

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

    nested = {"retained": []}
    original_candidates = [{"path": "image.png", "metadata": nested}]
    line = SimpleNamespace(id="line", generated_candidates=original_candidates)
    separator = SimpleNamespace(id="separator", line_type="separator", generated_candidates=["skip.png"])
    empty = SimpleNamespace(id="empty", generated_candidates=None)
    project = Project(source_directory="")
    project.prompt_lines = [line, separator, empty]
    state = State(project=object(), history=["undo"], settings={"old": True},
                  line_generated_candidates={"old": []}, current_project_path="old.json",
                  last_saved_at="saved", autosave_feedback="feedback", focused_line_id="old",
                  selected_node_ids=["old"], connect_mode=True,
                  startup_project_auto_open_error="previous error")
    before = dict(state)

    def prepare(path, **kwargs):
        assert path == "relative/project.json"
        assert state == before
        step("prepare")
        return project

    def layout(path):
        assert path == os.path.abspath("relative/project.json")
        assert state.project is project
        step("layout")
        if failure == "layout_oserror":
            raise OSError("layout denied")

    def remember(settings, path):
        assert settings is before["settings"]
        assert path == state.current_project_path
        step("remember")
        return {"recent": path}

    namespace = {
        "os": SimpleNamespace(path=SimpleNamespace(
            exists=lambda path: True,
            abspath=lambda path: (step("abspath"), os.path.abspath(path))[1],
            isabs=os.path.isabs)),
        "st": SimpleNamespace(session_state=state, warning=lambda message: events.append(("warning", message))),
        "prepare_project_json_open": prepare,
        "ensure_original_image_set_route": object(), "profile_block": nullcontext,
        "ensure_project_folder_layout": layout,
        "_normalize_candidate_records": _normalize_candidate_records,
        "remember_project": remember,
        "save_settings": lambda settings: step("save_settings"),
        "clear_module_rename_preview": lambda: step("clear_module_rename_preview"),
        "sync_text_areas": lambda: step("sync_text_areas"),
    }
    namespace.update({name: lambda name=name: step(name) for name in PUBLICATION_RESETS})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    persistent = namespace["_get_persistent_line_candidates"]

    def candidates(value):
        step("cache:" + value.id)
        return persistent(value)

    namespace["_get_persistent_line_candidates"] = candidates
    return SimpleNamespace(namespace=namespace, events=events, state=state, before=before,
                           project=project, line=line, separator=separator, empty=empty,
                           original_candidates=original_candidates, nested=nested, error=error)


def successful_publication_events():
    return ["prepare", "history", *PUBLICATION_RESETS, "project",
            "cache:line", "cache:line", "cache:empty", "line_generated_candidates",
            "abspath", "current_project_path", "layout", "project_folder_layout_ready",
            "last_saved_at", "autosave_feedback", "focused_line_id", "selected_node_ids",
            "connect_mode", "clear_module_rename_preview", "sync_text_areas",
            "remember", "settings", "save_settings", "pop:startup_project_auto_open_error"]


def test_publication_order_identity_mutation_and_shallow_cache():
    h = publication_harness()
    assert h.namespace["load_project_json_into_session"]("relative/project.json") is True
    assert h.events == successful_publication_events()
    assert h.state.project is h.project
    assert h.state.history == []
    assert h.line.generated_candidates is not h.original_candidates
    cached = h.state.line_generated_candidates["line"]
    assert cached is not h.line.generated_candidates
    assert cached[0] is h.line.generated_candidates[0]
    assert cached[0]["metadata"] is h.nested
    assert h.empty.generated_candidates == []
    assert h.separator.generated_candidates == ["skip.png"]
    assert set(h.state.line_generated_candidates) == {"line"}
    assert h.state.last_saved_at == h.state.autosave_feedback == ""
    assert h.state.focused_line_id is None
    assert h.state.selected_node_ids == []
    assert h.state.connect_mode is False
    assert "startup_project_auto_open_error" not in h.state


@pytest.mark.parametrize("failure", [PUBLICATION_RESETS[4], "cache:empty", "layout", "sync_text_areas", "save_settings"])
def test_publication_exceptions_keep_existing_partial_updates(failure):
    h = publication_harness(failure)
    with pytest.raises(RuntimeError) as caught:
        h.namespace["load_project_json_into_session"]("relative/project.json")
    assert caught.value is h.error
    expected = successful_publication_events()
    assert h.events == expected[:expected.index(failure) + 1]
    assert h.state.history == []
    assert h.state.project is (h.before["project"] if failure in PUBLICATION_RESETS else h.project)
    if failure in {PUBLICATION_RESETS[4], "cache:empty"}:
        assert h.state.line_generated_candidates is h.before["line_generated_candidates"]
        assert h.state.current_project_path == "old.json"
    if failure == "cache:empty":
        assert h.line.generated_candidates is not h.original_candidates
        assert h.empty.generated_candidates is None
    if failure == "layout":
        assert h.state.current_project_path != "old.json"
        assert h.state.last_saved_at == "saved"
    if failure != "save_settings":
        assert h.state.settings is h.before["settings"]
    else:
        assert h.state.settings == {"recent": h.state.current_project_path}
    assert h.state.startup_project_auto_open_error == "previous error"


def test_layout_oserror_warns_and_continues_through_settings():
    h = publication_harness("layout_oserror")
    assert h.namespace["load_project_json_into_session"]("relative/project.json") is True
    expected = successful_publication_events()
    expected.insert(expected.index("project_folder_layout_ready") + 1,
                    ("warning", "Project folders could not be created: layout denied"))
    assert h.events == expected
    assert h.state.project_folder_layout_ready is False
    assert "startup_project_auto_open_error" not in h.state


def test_manual_caller_owns_preparation_settings_and_missing_file_guard():
    h = publication_harness()
    h.namespace["os"].path.exists = lambda path: False
    assert h.namespace["load_project_json_into_session"]("missing.json") is False
    assert h.state == h.before
    assert h.events == [("warning", "Project file not found: missing.json")]

    h = publication_harness()
    h.namespace["publish_loaded_project_to_session"] = lambda project, path: h.events.append("publish")
    assert h.namespace["load_project_json_into_session"]("relative/project.json") is True
    assert h.events == ["prepare", "publish", "remember", "settings", "save_settings",
                        "pop:startup_project_auto_open_error"]

    h = publication_harness()
    assert h.namespace["publish_loaded_project_to_session"](h.project, "relative/project.json") is None
    assert h.state.settings is h.before["settings"]
    assert h.state.startup_project_auto_open_error == "previous error"
    assert h.events == successful_publication_events()[1:-4]
