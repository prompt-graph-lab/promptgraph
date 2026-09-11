"""Characterize rename widget/durable precedence before and after extraction."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


class Session(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


@pytest.fixture
def rename():
    state = Session()
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
               and n.module == "ui.module_rename_session"]
    if imports:
        from ui import module_rename_session as owner
        namespace = {}
        exec(compile(ast.Module(body=imports, type_ignores=[]), "app.py", "exec"), namespace)
        with patch.object(owner, "st", SimpleNamespace(session_state=state)):
            yield state, namespace
    else:
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"clear_module_rename_preview", "initialize_module_rename_selection",
                                "initialize_module_rename_new_name_draft", "sync_module_rename_selected_widget",
                                "sync_module_rename_new_name_widget"}]
        assert len(nodes) == 5
        namespace = {"st": SimpleNamespace(session_state=state)}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), namespace)
        yield state, namespace


def test_selection_durable_wins_but_existing_name_widget_survives(rename):
    state, ns = rename
    preview = object()
    state.update(module_rename_selected="pose", _module_rename_selected_widget="style",
                 module_rename_new_name="  durable  ", _module_rename_new_name_widget="  typing  ",
                 module_rename_preview=preview)
    assert ns["initialize_module_rename_selection"](["style", "pose", "pose"]) == "pose"
    assert state._module_rename_selected_widget == "pose"
    assert ns["initialize_module_rename_new_name_draft"]() == "durable"
    assert state._module_rename_new_name_widget == "  typing  "
    assert state.module_rename_preview is preview
    ns["sync_module_rename_new_name_widget"]()
    assert state.module_rename_new_name == "typing"
    assert state._module_rename_new_name_widget == "  typing  "


@pytest.mark.parametrize("value", [None, "", 0, False])
def test_falsey_callbacks_and_empty_options_preserve_unrelated_draft(rename, value):
    state, ns = rename
    state.update(module_rename_selected="pose", _module_rename_selected_widget=value,
                 module_rename_new_name="old", _module_rename_new_name_widget=value,
                 module_rename_preview={"old_name": "pose"})
    ns["sync_module_rename_selected_widget"]()
    assert state.module_rename_selected == "pose"
    ns["sync_module_rename_new_name_widget"]()
    assert state.module_rename_new_name == ""
    assert ns["initialize_module_rename_selection"](None) == ""
    assert "module_rename_selected" not in state
    assert "_module_rename_selected_widget" not in state
    assert "module_rename_preview" in state
    ns["clear_module_rename_preview"]()
    ns["clear_module_rename_preview"]()
    assert "module_rename_preview" not in state
    assert "_module_rename_new_name_widget" in state


def test_options_are_eager_and_fail_before_state_changes(rename):
    state, ns = rename
    state.module_rename_selected = "missing"
    def options():
        yield "first"
        raise RuntimeError("options failed")
    with pytest.raises(RuntimeError, match="options failed"):
        ns["initialize_module_rename_selection"](options())
    assert state == {"module_rename_selected": "missing"}
    assert ns["initialize_module_rename_selection"](iter(["z", "a", "z"])) == "z"
