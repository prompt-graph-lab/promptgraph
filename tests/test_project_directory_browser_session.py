"""Characterize browser cache publication and selection transition ordering."""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.project_discovery import normalize_project_discovery_path, resolve_cached_project_discovery


class Session(dict):
    def __getattr__(self, key):
        return self[key]

    def __setattr__(self, key, value):
        self[key] = value


@pytest.fixture
def browser():
    state = Session()
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
               and n.module == "ui.project_directory_browser_session"]
    if imports:
        from ui import project_directory_browser_session as owner
        with patch.object(owner, "st", SimpleNamespace(session_state=state)):
            yield state, vars(owner)
    else:
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"request_project_directory_discovery_refresh",
                                "_get_project_directory_discovery_snapshot",
                                "_normalize_project_directory_browser_selection"}]
        assert len(nodes) == 3
        ns = dict(st=SimpleNamespace(session_state=state),
                  normalize_project_discovery_path=normalize_project_discovery_path,
                  resolve_cached_project_discovery=resolve_cached_project_discovery)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "app.py", "exec"), ns)
        yield state, ns


@pytest.mark.parametrize("generation, expected", [(None, 1), (False, 1), ("", 1), ("2", 3), (-2, -1)])
def test_refresh_preserves_cache_until_next_resolution(browser, generation, expected):
    state, ns = browser
    cache = object()
    state.update(project_directory_discovery_cache=cache,
                 project_directory_discovery_refresh_generation=generation)
    ns["request_project_directory_discovery_refresh"]()
    assert state.project_directory_discovery_refresh_generation == expected
    assert state.project_directory_discovery_cache is cache


def test_invalid_generation_leaves_state_unchanged(browser):
    state, ns = browser
    state.project_directory_discovery_refresh_generation = "invalid"
    before = dict(state)
    with pytest.raises(ValueError):
        ns["request_project_directory_discovery_refresh"]()
    assert state == before


def test_resolution_passes_raw_context_and_publishes_exact_objects_after_success(browser):
    state, ns = browser
    old, cache, snapshot = {}, {}, {}
    state.update(project_directory_discovery_cache=old,
                 project_directory_discovery_refresh_generation=None, current_project_path=None)
    def resolve(previous, **kwargs):
        assert previous is old
        assert state.project_directory_discovery_cache is old
        assert kwargs == dict(root=" raw root ", refresh_generation=None, current_open_project_path=None)
        return snapshot, cache, False
    with patch.dict(ns, resolve_cached_project_discovery=resolve):
        assert ns["_get_project_directory_discovery_snapshot"](" raw root ") is snapshot
    assert state.project_directory_discovery_cache is cache
    def fail(*args, **kwargs):
        raise OSError("discovery failed")
    with patch.dict(ns, resolve_cached_project_discovery=fail):
        with pytest.raises(OSError, match="discovery failed"):
            ns["_get_project_directory_discovery_snapshot"]("root")
    assert state.project_directory_discovery_cache is cache


def test_root_change_clears_selection_before_entry_failure(browser):
    state, ns = browser
    state.update(project_directory_selection_root="old", project_directory_selected_path="selected")
    with patch.dict(ns, normalize_project_discovery_path=lambda root: "new"):
        with pytest.raises(AttributeError):
            ns["_normalize_project_directory_browser_selection"]("root", [None])
    assert state == {"project_directory_selection_root": "new"}


def test_selection_preserves_valid_value_then_uses_first_nonempty_entry(browser):
    state, ns = browser
    state.update(project_directory_selection_root="root", project_directory_selected_path="a")
    entries = [{"project_path": value} for value in [None, 0, "z", "a", "z"]]
    with patch.dict(ns, normalize_project_discovery_path=lambda root: root):
        select = ns["_normalize_project_directory_browser_selection"]
        assert select("root", entries) == "a"
        assert select("changed", entries) == "z"
        assert select("changed", []) == ""
        assert "project_directory_selected_path" not in state


def test_entry_path_is_evaluated_twice_and_empty_selection_is_removed(browser):
    state, ns = browser
    state.update(project_directory_selection_root="root", project_directory_selected_path="")
    calls = []
    class Entry:
        def get(self, key):
            calls.append(key)
            return "first" if len(calls) == 1 else "second"
    with patch.dict(ns, normalize_project_discovery_path=lambda root: root):
        select = ns["_normalize_project_directory_browser_selection"]
        assert select("root", []) == ""
        assert "project_directory_selected_path" not in state
        assert select("root", [Entry()]) == "second"
    assert calls == ["project_path", "project_path"]
