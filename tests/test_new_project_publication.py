import ast
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.project import Project


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
OUTSIDE = ["remember", "settings", "save_settings", "pop:startup_project_auto_open_error"]
ORDER = ["construct", "graph", *PUBLICATION, *OUTSIDE]


def harness(failure=None):
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    names = {"set_new_workspace_project", "publish_new_project_to_session",
             "ensure_current_project_folder_layout"}
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

    state = State(project=object(), history=["undo"], settings={"old": []},
                  current_project_path="old.json", last_saved_at="old time",
                  line_generated_candidates={"old": []},
                  startup_project_auto_open_error="old warning")
    before = dict(state)
    constructed = Project(source_directory="")
    published = Project(source_directory="graph replacement")
    lines = published.prompt_lines
    remembered = {"recent": []}

    def construct(**kwargs):
        assert kwargs == {"source_directory": ""}
        assert state == before
        step("construct")
        return constructed

    def graph(project):
        assert project is constructed
        assert state == before
        step("graph")
        return published

    def layout(path):
        assert path == os.path.abspath("relative/project.json")
        assert state.project is published
        step("layout")
        if failure == "layout_oserror":
            raise OSError("layout denied")

    def remember(settings, path):
        assert settings is before["settings"]
        assert path == state.current_project_path
        step("remember")
        return remembered

    def save(settings):
        assert settings is remembered
        step("save_settings")

    namespace = {
        "Project": construct, "build_graph": graph,
        "st": SimpleNamespace(session_state=state, warning=lambda value: events.append(("warning", value))),
        "os": SimpleNamespace(path=SimpleNamespace(
            abspath=lambda path: (step("abspath"), os.path.abspath(path))[1])),
        "datetime": SimpleNamespace(now=lambda: (step("now"), datetime(2026, 9, 15, 12, 34, 56))[1]),
        "ensure_project_folder_layout": layout, "remember_project": remember,
        "save_settings": save,
    }
    for name in [*RESETS, "clear_module_rename_preview", "sync_text_areas"]:
        namespace[name] = lambda name=name: step(name)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
    return SimpleNamespace(namespace=namespace, events=events, state=state, before=before,
                           project=published, lines=lines, remembered=remembered, error=error)


def test_new_project_publication_order_identity_and_values():
    h = harness()
    assert h.namespace["set_new_workspace_project"]("relative/project.json") is None
    assert h.events == ORDER
    assert h.state.project is h.project
    assert h.project.prompt_lines is h.lines
    assert h.state.current_project_path == os.path.abspath("relative/project.json")
    assert h.state.project_folder_layout_ready is True
    assert h.state.last_saved_at == "2026-09-15 12:34:56"
    assert h.state.autosave_feedback == "project created"
    assert h.state.focused_line_id is h.state.highlighted_line_id is None
    assert h.state.connect_mode is False
    for key in ("history", "selected_node_ids", "connect_nodes"):
        assert h.state[key] == []
    for key in ("selected_lines", "line_generated_candidates"):
        assert h.state[key] == {}
    assert h.state.history is not h.before["history"]
    assert h.state.line_generated_candidates is not h.before["line_generated_candidates"]
    assert h.state.settings is h.remembered
    assert "startup_project_auto_open_error" not in h.state


@pytest.mark.parametrize("failure", ["construct", "graph", *RESETS, "abspath", "layout",
                                     "now", "clear_module_rename_preview", "sync_text_areas",
                                     "remember", "save_settings"])
def test_failures_propagate_and_leave_ordered_partial_publication(failure):
    h = harness(failure)
    with pytest.raises(RuntimeError) as caught:
        h.namespace["set_new_workspace_project"]("relative/project.json")
    assert caught.value is h.error
    assert h.events == ORDER[:ORDER.index(failure) + 1]
    if failure in {"construct", "graph"}:
        assert h.state == h.before
    else:
        assert h.state.history == []
        assert h.state.project is (h.before["project"] if failure in RESETS else h.project)
    if failure == "layout":
        assert h.state.current_project_path == os.path.abspath("relative/project.json")
        assert h.state.last_saved_at == "old time"
    assert h.state.settings is (h.remembered if failure == "save_settings" else h.before["settings"])
    assert h.state.startup_project_auto_open_error == "old warning"


def test_layout_oserror_retains_warning_and_continues():
    h = harness("layout_oserror")
    h.namespace["set_new_workspace_project"]("relative/project.json")
    expected = ORDER.copy()
    expected.insert(expected.index("project_folder_layout_ready") + 1,
                    ("warning", "Project folders could not be created: layout denied"))
    assert h.events == expected
    assert h.state.project_folder_layout_ready is False
    assert h.state.settings is h.remembered


def test_seam_excludes_construction_settings_and_startup_warning_cleanup():
    h = harness()
    assert h.namespace["publish_new_project_to_session"](h.project, "relative/project.json") is None
    assert h.events == PUBLICATION
    assert h.state.settings is h.before["settings"]
    assert h.state.startup_project_auto_open_error == "old warning"

    h = harness()

    def publish(project, path):
        assert project is h.project
        assert path == "relative/project.json"
        assert h.state == h.before
        h.events.append("publish")

    h.namespace["publish_new_project_to_session"] = publish
    assert h.namespace["set_new_workspace_project"]("relative/project.json") is None
    assert h.events == ["construct", "graph", "publish", *OUTSIDE]
