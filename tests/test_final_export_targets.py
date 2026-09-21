import ast
import builtins
import copy
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import final_export_targets as planner
from core.operations import get_gallery_route_options, resolve_gallery_route_for_line
from core.project import Project, PromptLine
from core.prompt_line_selection import (
    get_visible_prompt_lines, is_gallery_operation_prompt_line, is_route_separator,
)
from core.route_operations import resolve_selected_route_export_lines

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / 'tests/fixtures/final_export_targets_frozen.py'
APP = ROOT / 'app.py'
NAMES = {
    '_gallery_route_anchor_line_id', '_gallery_route_line_count',
    '_gallery_route_options_with_counts', '_final_export_route_options',
    'resolve_final_export_lines',
}


@lru_cache(maxsize=2)
def resolver_code(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
    return compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec")


def load_resolver(path, session):
    namespace = dict(
        st=SimpleNamespace(session_state=session),
        get_visible_prompt_lines=get_visible_prompt_lines,
        is_gallery_operation_prompt_line=is_gallery_operation_prompt_line,
        is_route_separator=is_route_separator,
        get_gallery_route_options=get_gallery_route_options,
        resolve_gallery_route_for_line=resolve_gallery_route_for_line,
        resolve_selected_route_export_lines=resolve_selected_route_export_lines,
        get_final_export_prompt_lines=planner.get_final_export_prompt_lines,
        get_final_export_route_options=planner.get_final_export_route_options,
        resolve_final_export_targets=planner.resolve_final_export_targets,
    )
    exec(resolver_code(path), namespace)
    return namespace


def line(identifier, index, kind=None, deleted=False):
    return PromptLine(
        id=identifier, original_file_name=identifier, original_index=index,
        current_index=index, original_text=identifier, current_text=identifier,
        tokens=[identifier], line_type=kind, deleted=deleted,
    )


def project(kind='normal'):
    if kind == 'empty':
        return Project(prompt_lines=[])
    if kind == 'none':
        return None
    if kind == 'invalid':
        return Project(prompt_lines=None)
    lines = [
        line('orphan', 8), line('a', 0, 'separator'), line('a1', 7),
        line('work', 2, 'workbench'), line('gone', 3, deleted=True),
        line('b', 4, 'separator'), line('b1', 1), line('empty', 9, 'separator'),
        line('dead_route', 10, 'separator', True),
    ]
    lines[2].generated_candidates = [{'path': 'not-on-disk.png'}]
    lines[2].gallery_variants = [{'path': 'variant.png', 'kind': 'gallery_variant'}]
    if kind == 'overlap':
        # Repeated references and IDs spanning scene boundaries are realistic
        # persisted ambiguity; the lower resolver excludes ambiguous members.
        lines.insert(6, lines[2])
        lines.insert(3, line('a1', 3))
    if kind == 'duplicate_routes':
        lines.append(line('a', 12, 'separator'))
        lines.append(line('tail', 13))
    return Project(prompt_lines=lines)


def outcome(call):
    try:
        return ('value', call())
    except Exception as error:
        return ('error', type(error), error.args)


def assert_same(left, right):
    assert left[0] == right[0]
    if left[0] == 'error':
        assert left == right
        return
    expected, actual = left[1], right[1]
    assert actual.keys() == expected.keys()
    assert actual == expected  # Every field, including diagnostic/summary order.
    assert len(actual['lines']) == len(expected['lines'])
    assert all(a is b for a, b in zip(actual['lines'], expected['lines']))


CASES = [
    ('all_lines', None, None, None),
    ('bogus', None, [], []),
    (None, None, None, None),
    ([], None, None, None),  # Preserve unhashable-scope exception.
    ('current_route', None, [None, '', 'b1', 'a1'], None),
    ('current_route', None, [], None),
    ('current_route', None, ['orphan'], None),
    ('selected_route', ' a ', None, None),
    ('selected_route', 'empty', None, None),
    ('selected_route', 'missing', None, None),
    ('selected_route', None, None, None),
    ('selected_route', 0, None, None),
    ('selected_routes', None, None, ['b', 'a', 'a', 'missing', 'a1', 'dead_route']),
    ('selected_routes', None, None, ['empty']),
    ('selected_routes', None, None, []),
    ('selected_routes', None, None, None),
    ('selected_routes', None, None, 'a'),
    ('selected_routes', None, None, [None, '', ' a ', 0]),
]


@pytest.mark.parametrize('kind', ['normal', 'empty', 'none', 'invalid', 'overlap', 'duplicate_routes'])
@pytest.mark.parametrize('scope,route_id,selected,route_ids', CASES)
def test_frozen_differential(kind, scope, route_id, selected, route_ids):
    value = project(kind)
    session = {'gallery_expanded_line_id': 'a1'}
    before = copy.deepcopy((value, selected, route_ids, session))
    original_lines = list(value.prompt_lines or []) if value else []
    original_collection = value.prompt_lines if value else None
    legacy = load_resolver(FROZEN, session)
    app = load_resolver(APP, session)
    args = (value, scope, route_id, selected, route_ids)
    expected = outcome(lambda: legacy['resolve_final_export_lines'](*args))
    assert_same(expected, outcome(lambda: app['resolve_final_export_lines'](*args)))
    anchor = legacy['_gallery_route_anchor_line_id'](value, selected or []) if scope == 'current_route' else ''
    call = lambda: planner.resolve_final_export_targets(
        value, scope, route_id, route_ids, anchor_line_id=anchor,
    )
    assert_same(expected, outcome(call))
    assert_same(expected, outcome(call))
    assert (value, selected, route_ids, session) == before
    if value:
        assert value.prompt_lines is original_collection
        assert all(a is b for a, b in zip(value.prompt_lines or [], original_lines))


@pytest.mark.parametrize('session,selected,anchor', [
    ({'focused_line_id': 'missing', 'gallery_expanded_line_id': 'a1'}, ['b1'], 'missing'),
    ({'focused_line_id': 'a1'}, ['b1'], 'a1'),
    ({'gallery_expanded_line_id': 'a1'}, [None, '', 'b1', 'a1'], 'b1'),
    ({'gallery_expanded_line_id': 'a1'}, [], 'a1'),
    ({'gallery_selected_route_separator_id': 'b'}, None, 'b'),
    ({'gallery_selected_route_separator_id': 'missing'}, [], ''),
    ({'gallery_selected_route_separator_id': 'dead_route'}, [], ''),
    ({}, None, ''),
])
def test_app_anchor_precedence_and_fallback(session, selected, anchor):
    value = project()
    legacy = load_resolver(FROZEN, session)
    app = load_resolver(APP, session)
    assert app['_gallery_route_anchor_line_id'](value, selected) == anchor
    expected = legacy['resolve_final_export_lines'](value, 'current_route', selected_line_ids=selected)
    actual = app['resolve_final_export_lines'](value, 'current_route', selected_line_ids=selected)
    assert_same(('value', expected), ('value', actual))
    assert_same(('value', expected), ('value', planner.resolve_final_export_targets(value, 'current_route', anchor_line_id=anchor)))


def test_selected_route_warnings_and_order():
    value = project()
    assert planner.resolve_final_export_targets(value, 'selected_route', 'missing')['warnings'] == ['シーンが選択されていません。']
    assert planner.resolve_final_export_targets(value, 'selected_route', 'empty')['warnings'] == ['選択されたシーンには書き出し対象イラストがありません。']
    assert planner.resolve_final_export_targets(value, 'all_lines')['line_ids'] == ['b1', 'a1', 'orphan']
    assert planner.resolve_final_export_targets(value, 'selected_route', ' a ')['line_ids'] == ['a1']


def test_multiple_routes_reuse_all_lower_resolver_fields():
    value = project()
    selected = ['b', 'a', 'a', 'missing', 'dead_route', 'work']
    lower = resolve_selected_route_export_lines(value, selected)
    result = planner.resolve_final_export_targets(value, 'selected_routes', selected_route_ids=selected)
    assert result['line_ids'] == ['a1', 'b1']
    assert result['selected_candidate_count'] > 0
    assert result['selected_gallery_variant_count'] > 0
    for key in result:
        if key.startswith('selected_') or key in {'route_summaries', 'diagnostics', 'resolved_route_handles', 'resolved_route_labels'}:
            assert result[key] == lower[key]
    assert result['warnings'] == lower['diagnostics']
    assert result['route_line_count'] == len(lower['target_lines'])
    assert all(a is b for a, b in zip(result['lines'], lower['target_lines']))


def test_filter_failure_precedes_session_lookup():
    class NoSession(dict):
        def get(self, *args):
            pytest.fail('Session lookup must follow successful active-line preparation')
    for path in (FROZEN, APP):
        resolver = load_resolver(path, NoSession())['resolve_final_export_lines']
        with pytest.raises(TypeError):
            resolver(Project(prompt_lines=None), 'current_route')


def test_lower_exception_propagates_unchanged(monkeypatch):
    error = RuntimeError('lower resolver failure')
    def fail(*args):
        raise error
    monkeypatch.setattr(planner, 'resolve_selected_route_export_lines', fail)
    with pytest.raises(RuntimeError) as caught:
        planner.resolve_final_export_targets(project(), 'selected_routes', selected_route_ids=['a'])
    assert caught.value is error


def test_no_ui_or_filesystem_execution(monkeypatch):
    value = project()
    def fail(*args, **kwargs):
        pytest.fail('Target planning attempted filesystem access')
    monkeypatch.setattr(builtins, 'open', fail)
    monkeypatch.setattr(Path, 'open', fail)
    for scope, route_id, selected, route_ids in CASES:
        if isinstance(scope, list):
            continue
        planner.resolve_final_export_targets(value, scope, route_id, route_ids, anchor_line_id='a1')


def test_app_delegation_and_pure_owner_import_boundary():
    tree = ast.parse(APP.read_text(encoding='utf-8'))
    wrapper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'resolve_final_export_lines')
    calls = [n.func.id for n in ast.walk(wrapper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert calls == ['get_final_export_prompt_lines', 'resolve_final_export_targets', '_gallery_route_anchor_line_id']
    pure_tree = ast.parse(Path(planner.__file__).read_text(encoding='utf-8'))
    imports = [n.module for n in pure_tree.body if isinstance(n, ast.ImportFrom)]
    assert imports == ['core.operations', 'core.prompt_line_selection', 'core.route_operations']
    assert not any(isinstance(n, ast.Import) for n in ast.walk(pure_tree))


@pytest.mark.parametrize('kind', ['normal', 'empty', 'none', 'overlap', 'duplicate_routes'])
def test_route_options_keep_legacy_visible_counts(kind):
    value = project(kind)
    expected = load_resolver(FROZEN, {})['_final_export_route_options'](value)
    assert planner.get_final_export_route_options(value) == expected
    assert load_resolver(APP, {})['_final_export_route_options'](value) == expected


def test_import_and_plan_without_streamlit():
    import subprocess
    import sys
    code = '''
import sys
sys.modules['streamlit'] = None
from core.final_export_targets import resolve_final_export_targets
from core.project import Project
assert resolve_final_export_targets(Project(prompt_lines=[]), 'all_lines')['lines'] == []
'''
    subprocess.run([sys.executable, '-c', code], cwd=ROOT, check=True, capture_output=True, text=True)
