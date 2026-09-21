"""Frozen-base differential and focused contracts for Final Export planning."""

import ast
import copy
from functools import lru_cache
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from core.final_export_targets import resolve_final_export_targets
from core.operations import get_gallery_route_options, resolve_gallery_route_for_line
from core.project import Project, PromptLine
from core.prompt_line_selection import (
    get_visible_prompt_lines,
    is_gallery_operation_prompt_line,
    is_route_separator,
)
from core.route_operations import resolve_selected_route_export_lines


ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = {
    "_gallery_route_anchor_line_id", "_gallery_route_options_with_counts",
    "_final_export_route_options", "_gallery_route_line_count", "resolve_final_export_lines",
}


@lru_cache(maxsize=None)
def resolver_code(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    assert {node.name for node in nodes} == FUNCTIONS
    return compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec")


def load_resolver(path, state=None):
    """Execute just the real app functions; never import Streamlit/app startup."""
    namespace = {
        "st": SimpleNamespace(session_state=dict(state or {})),
        "get_visible_prompt_lines": get_visible_prompt_lines,
        "is_gallery_operation_prompt_line": is_gallery_operation_prompt_line,
        "is_route_separator": is_route_separator,
        "get_gallery_route_options": get_gallery_route_options,
        "resolve_gallery_route_for_line": resolve_gallery_route_for_line,
        "resolve_selected_route_export_lines": resolve_selected_route_export_lines,
        "resolve_final_export_targets": resolve_final_export_targets,
    }
    exec(resolver_code(path), namespace)
    return namespace


def line(id, index=0, kind=None, deleted=False):
    return PromptLine(
        id=id, original_file_name=id, original_index=index, current_index=index,
        original_text=id, current_text=id, tokens=[id], line_type=kind, deleted=deleted,
    )


def project_case(case="normal"):
    if case == "none":
        return None
    if case == "empty":
        return Project(prompt_lines=[])
    if case == "invalid_lines":
        return Project(prompt_lines=None)
    lines = [
        line("head", 0), line("r1", 1, "separator"), line("a", 8),
        line("work", 3, "workbench"), line("deleted", 4, deleted=True),
        line("b", 2), line("r2", 6, "separator"), line("c", 7),
        line("empty", 9, "separator"), line("dead_route", 10, "separator", True),
        line("tail", 11), line("last", 12, "separator"),
    ]
    lines[2].generated_candidates = [{"path": "missing.png"}, {"path": "trash.png", "trashed": True}]
    lines[2].gallery_variants = [{"path": "variant.png", "kind": "gallery_variant"}]
    if case == "duplicate_members":
        lines[7].id = "a"  # overlapping ids in two selected routes
    elif case == "duplicate_routes":
        lines[6].id = "r1"
    elif case == "falsey_ids":
        lines[2].id = ""
        lines[5].id = None
    elif case == "bad_indexes":
        lines[2].current_index = "bad"
    elif case == "tied_indexes":
        for item in lines:
            item.current_index = None
    return Project(prompt_lines=lines)


def outcome(call):
    try:
        return (None, call())
    except Exception as error:
        return (type(error), error.args)


def assert_same(actual, expected):
    assert actual[0] is expected[0]
    if expected[0] is not None:
        assert actual[1] == expected[1]
        return
    actual, expected = actual[1], expected[1]
    assert actual.keys() == expected.keys()
    assert len(actual["lines"]) == len(expected["lines"])
    assert all(a is b for a, b in zip(actual["lines"], expected["lines"]))
    assert {k: v for k, v in actual.items() if k != "lines"} == {
        k: v for k, v in expected.items() if k != "lines"
    }


def direct_plan(namespace, project, scope, route_id=None, selected_line_ids=None, selected_route_ids=None):
    """Explicit normalized-input boundary for the standalone core API."""
    scope = scope if scope in {"all_lines", "current_route", "selected_route", "selected_routes"} else "all_lines"
    active = [item for item in get_visible_prompt_lines(project) if not getattr(item, "deleted", False)]
    prompts = [item for item in active if is_gallery_operation_prompt_line(item)]
    anchor = ""
    options = ()
    if scope == "current_route":
        anchor = namespace["_gallery_route_anchor_line_id"](project, selected_line_ids or [])
    elif scope == "selected_route":
        route_id = str(route_id or "").strip()
        options = namespace["_final_export_route_options"](project)
    before = copy.deepcopy((prompts, options, selected_route_ids))
    result = resolve_final_export_targets(
        project, scope, prompts, anchor_line_id=anchor, route_id=route_id,
        route_options=options, selected_route_ids=selected_route_ids,
    )
    assert (prompts, options, selected_route_ids) == before
    return result


CASES = [
    {"scope": "all_lines"}, {"scope": "unknown"}, {"scope": None},
    {"scope": []},
    *({"scope": "current_route", "selected_line_ids": ids} for ids in (None, [], ["", "a", "c"], ["head"], ["missing"], ["last"], ["deleted"])),
    *({"scope": "selected_route", "route_id": id} for id in (None, "", " r1 ", "r2", "last", "missing", "dead_route", 0, 7)),
    *({"scope": "selected_routes", "selected_route_ids": ids} for ids in (
        None, [], ["r2", "r1", "r1"], ["r2", "missing", "a", "dead_route", "r1", "r2"],
        ["last"], "r1", [None, "", " r1 "], {"r2", "r1"}, 12,
    )),
]


@pytest.mark.parametrize("case", ["normal", "none", "empty", "invalid_lines", "duplicate_members", "duplicate_routes", "falsey_ids", "bad_indexes", "tied_indexes"])
@pytest.mark.parametrize("kwargs", CASES)
def test_frozen_base_differential(case, kwargs):
    project = project_case(case)
    snapshot = copy.deepcopy((project, kwargs))
    old = load_resolver(ROOT / "tests/fixtures/final_export_legacy.py")
    new = load_resolver(ROOT / "app.py")
    expected = outcome(lambda: old["resolve_final_export_lines"](project, **kwargs))
    assert_same(outcome(lambda: new["resolve_final_export_lines"](project, **kwargs)), expected)
    assert_same(outcome(lambda: direct_plan(old, project, **kwargs)), expected)
    assert_same(outcome(lambda: direct_plan(old, project, **kwargs)), expected)
    assert (project, kwargs) == snapshot


@pytest.mark.parametrize("state,selected,anchor", [
    ({"focused_line_id": "a", "gallery_expanded_line_id": "c", "gallery_selected_route_separator_id": "r2"}, ["c"], "a"),
    ({"focused_line_id": "missing", "gallery_expanded_line_id": "c"}, ["a"], "missing"),
    ({"gallery_expanded_line_id": "c", "gallery_selected_route_separator_id": "r2"}, [None, "", "a", "c"], "a"),
    ({"gallery_expanded_line_id": "c", "gallery_selected_route_separator_id": "r1"}, [], "c"),
    ({"gallery_selected_route_separator_id": "r2"}, [], "r2"),
    ({"gallery_selected_route_separator_id": "missing"}, [], ""),
    ({"gallery_selected_route_separator_id": "dead_route"}, [], ""),
    ({"gallery_selected_route_separator_id": "a"}, [], ""),
])
def test_anchor_precedence_and_fallback(state, selected, anchor):
    project = project_case()
    old = load_resolver(ROOT / "tests/fixtures/final_export_legacy.py", state)
    new = load_resolver(ROOT / "app.py", state)
    assert new["_gallery_route_anchor_line_id"](project, selected) == anchor
    expected = outcome(lambda: old["resolve_final_export_lines"](project, "current_route", selected_line_ids=selected))
    assert_same(outcome(lambda: new["resolve_final_export_lines"](project, "current_route", selected_line_ids=selected)), expected)
    assert new["st"].session_state == state


def test_filtering_identity_and_scope_order():
    project = project_case()
    app = load_resolver(ROOT / "app.py")
    resolve = app["resolve_final_export_lines"]
    assert resolve(project, "all_lines")["line_ids"] == ["head", "b", "c", "a", "tail"]
    selected = resolve(project, "selected_route", route_id=" r1 ")
    assert selected["line_ids"] == ["b", "a"]
    assert selected["lines"][1] is project.prompt_lines[2]
    # The visible-order count is intentionally different from route membership.
    assert selected["route_line_count"] == 1
    multiple = resolve(project, "selected_routes", selected_route_ids=["r2", "r1", "r1"])
    assert multiple["line_ids"] == ["a", "b", "c"]
    assert multiple["resolved_route_handles"] == ["r1", "r2"]
    assert multiple["selected_main_line_count"] == 3
    assert multiple["selected_workbench_count"] == 1
    assert multiple["selected_deleted_member_count"] == 1
    assert multiple["selected_candidate_count"] == 1
    assert multiple["selected_gallery_variant_count"] == 1
    lower = resolve_selected_route_export_lines(project, ["r2", "r1", "r1"])
    for key in ("route_summaries", "diagnostics", "resolved_route_labels", "selected_route_count"):
        assert multiple[key] == lower[key]


def test_selected_route_warnings_and_invalid_scope():
    app = load_resolver(ROOT / "app.py")
    project = project_case()
    resolve = app["resolve_final_export_lines"]
    assert resolve(project, "selected_route")["warnings"] == ["シーンが選択されていません。"]
    assert resolve(project, "selected_route", "last")["warnings"] == ["選択されたシーンには書き出し対象イラストがありません。"]
    assert resolve(project, "selected_routes", selected_route_ids=[])["warnings"] == ["選択されたシーンには書き出し対象イラストがありません。"]
    assert resolve(project, "current_route")["warnings"] == ["No current line is available to resolve a Route."]
    assert_same(outcome(lambda: resolve(project, "bogus")), outcome(lambda: resolve(project, "all_lines")))


def test_app_keeps_preparation_and_exception_order():
    for path in (ROOT / "tests/fixtures/final_export_legacy.py", ROOT / "app.py"):
        namespace = load_resolver(path)
        events = []
        error = RuntimeError("visible lines failure")

        def fail(project):
            events.append("visible")
            raise error

        namespace["get_visible_prompt_lines"] = fail
        namespace["_gallery_route_anchor_line_id"] = lambda *args: events.append("anchor")
        with pytest.raises(RuntimeError) as caught:
            namespace["resolve_final_export_lines"](project_case(), "current_route")
        assert caught.value is error
        assert events == ["visible"]


def test_core_uses_lower_resolver_and_preserves_exception(monkeypatch):
    from core import final_export_targets
    project = project_case()
    ids = ["r1"]
    error = ValueError("route resolution failed")

    def fail(actual_project, actual_ids):
        assert actual_project is project
        assert actual_ids is ids
        raise error

    monkeypatch.setattr(final_export_targets, "resolve_selected_route_export_lines", fail)
    with pytest.raises(ValueError) as caught:
        resolve_final_export_targets(project, "selected_routes", [], selected_route_ids=ids)
    assert caught.value is error


def test_core_import_and_calls_need_no_ui_or_filesystem():
    script = '''
import sys
class NoUI:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'streamlit', 'app', 'ui'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, NoUI())
from core.final_export_targets import resolve_final_export_targets
from core.project import Project
from unittest.mock import patch
project = Project(prompt_lines=[])
with patch('builtins.open', side_effect=AssertionError('filesystem open')), patch('os.stat', side_effect=AssertionError('filesystem stat')), patch('os.listdir', side_effect=AssertionError('filesystem list')):
    for scope in ('all_lines', 'current_route', 'selected_route', 'selected_routes'):
        assert resolve_final_export_targets(project, scope, [])['lines'] == []
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
