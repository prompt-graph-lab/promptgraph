"""Compatibility with the frozen app preflight and the real app import boundary."""

import ast
from dataclasses import asdict
from datetime import datetime
import ntpath
import os
from pathlib import Path
import posixpath
import shutil
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import project_directory_duplication as planner


ROOT = Path(__file__).resolve().parents[1]
FROZEN = (ROOT / 'tests/fixtures/project_directory_duplication_frozen.py.txt').read_text(encoding='utf-8')
APP = (ROOT / 'app.py').read_text(encoding='utf-8')
NAMES = {
    '_sanitize_duplicate_project_dir_name', '_source_project_directory',
    '_default_duplicate_project_dir_name', '_duplicate_project_destination_dir',
    'duplicate_current_project_directory',
}


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


def load_functions(source, state, *, preflight=False):
    """Execute real imports/functions without starting Streamlit's page body."""
    body = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.ImportFrom) and node.module == 'core':
            if any(alias.name == 'project_directory_duplication' for alias in node.names):
                body.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            if preflight and node.name == 'duplicate_current_project_directory':
                # Freeze the old read-only boundary immediately before the save try.
                node.body = node.body[:next(i for i, n in enumerate(node.body) if isinstance(n, ast.Try))]
                class Capture(ast.NodeTransformer):
                    def visit_Return(self, n):
                        return ast.copy_location(ast.Return(value=ast.Call(
                            func=ast.Name(id='capture', ctx=ast.Load()),
                            args=[ast.Call(func=ast.Name(id='locals', ctx=ast.Load()), args=[], keywords=[]), n.value],
                            keywords=[],
                        )), n)
                node = Capture().visit(node)
                node.body.append(ast.parse('return capture(locals(), (True, ""))').body[0])
            body.append(node)
    namespace = {'os': os, 'st': SimpleNamespace(session_state=state)}
    def capture(values, result):
        return {
            'source_project_path': values.get('source_project_path', ''),
            'source_project_dir': values.get('source_project_dir', ''),
            'destination_dir': values.get('destination_dir', ''),
            'error': result[1],
        }
    namespace['capture'] = capture
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), '<duplication-app-boundary>', 'exec'), namespace)
    return namespace


@pytest.mark.parametrize('name, expected', [
    (None, ''), (False, ''), (0, ''), ('', ''), ('  . ..  ', ''),
    ('  My Project. ', 'My Project'), ('a/b\\c<>:"|?*', 'a_b_c_______'),
    ('CON', 'CON'), ('NUL.txt', 'NUL.txt'), ('日本語', '日本語'),
    (123, '123'), ('a\x00b', 'a\x00b'),
])
def test_name_normalization(name, expected):
    assert planner.sanitize_duplicate_project_dir_name(name) == expected


@pytest.mark.parametrize('path', [None, False, 0, '', 'relative/project.json', '~/Project/project.json',
                                    '../Project/./project.json', Path('Project/project.json'), '/', b'Project/project.json'])
def test_source_normalization_matches_frozen(path):
    old = load_functions(FROZEN, State(current_project_path=path))
    assert planner.source_project_directory(path) == old['_source_project_directory']()


@pytest.mark.parametrize('path', ['', None, 'Project/project.json', '~/Project/project.json', '/', Path('Project/project.json')])
@pytest.mark.parametrize('name', ['', None, ' .. ', 'A/B', 'CON', 'Copy'])
def test_destination_matches_frozen(path, name):
    old = load_functions(FROZEN, State(current_project_path=path))
    assert planner.duplicate_project_destination_dir(path, name) == old['_duplicate_project_destination_dir'](name)


@pytest.mark.parametrize('path', ['', None, 'Project/project.json', '/', '~/Project/project.json'])
@pytest.mark.parametrize('collisions', [0, 1, 3])
def test_default_collision_order_matches_frozen(path, collisions):
    old = load_functions(FROZEN, State(current_project_path=path))
    old_calls, new_calls = [], []
    def exists(calls):
        def check(value):
            calls.append(value)
            return len(calls) <= collisions
        return check
    old['os'] = SimpleNamespace(path=SimpleNamespace(
        abspath=os.path.abspath, expanduser=os.path.expanduser,
        dirname=os.path.dirname, basename=os.path.basename, join=os.path.join,
        exists=exists(old_calls),
    ))
    expected = old['_default_duplicate_project_dir_name']()
    actual = planner.default_duplicate_project_dir_name(path, exists=exists(new_calls))
    assert (actual, new_calls) == (expected, old_calls)
    if path:
        stem = (os.path.basename(planner.source_project_directory(path)[1]) or 'Project') + '_copy'
        assert [os.path.basename(p) for p in new_calls] == [stem] + [f'{stem}_{i}' for i in range(1, collisions + 1)]
    else:
        assert actual == 'MyProject_copy'
        assert not new_calls


CASES = [
    (False, object(), object(), True, True, False),
    (True, '', 'Copy', True, True, False),
    (True, None, 'Copy', True, True, False),
    (True, 'Project/p.json', 'Copy', False, False, True),
    (True, 'Project/p.json', 'Copy', True, False, True),
    (True, 'Project/p.json', '', True, True, False),
    (True, 'Project/p.json', ' . ', True, True, True),
    (True, 'Project/p.json', None, True, True, False),
    (True, 'Project/p.json', 'Copy', True, True, True),
    (True, 'Project/p.json', 'Copy', True, True, False),
    (True, '~/Project/p.json', 'A/B\\C:*', True, True, False),
    (True, Path('Project/p.json'), 'CON', True, True, False),
    (True, '/', 42, True, True, False),
    (True, 'C:\\Projects\\Original\\p.json', 'New', True, True, False),
    (True, '\\\\server\\share\\Original\\p.json', 'New', True, True, False),
    (True, 42, 'Copy', True, True, False),
    (True, b'Project/p.json', 'Copy', True, True, False),
]


def observation(call):
    try:
        return ('return', call())
    except Exception as exc:
        return ('raise', type(exc), str(exc))


@pytest.mark.parametrize('path_module', [ntpath, posixpath])
@pytest.mark.parametrize('available,path,name,file_ok,dir_ok,dest_exists', CASES)
@pytest.mark.parametrize('failure', [None, 'isfile', 'isdir', 'exists', 'expanduser', 'abspath'])
def test_preflight_fields_order_and_failures_match_frozen(monkeypatch, path_module, available, path, name, file_ok, dir_ok, dest_exists, failure):
    events = []
    error = OSError('filesystem observation failed')
    def traced(label, fn):
        def run(*args):
            events.append((label, args))
            if label == failure:
                raise error
            return fn(*args)
        return run
    fake_path = SimpleNamespace(**{
        label: traced(label, getattr(path_module, label))
        for label in ('expanduser', 'abspath', 'dirname', 'basename', 'join')
    })
    for label, value in [('isfile', file_ok), ('isdir', dir_ok), ('exists', dest_exists)]:
        setattr(fake_path, label, traced(label, lambda _, value=value: value))
    fake_os = SimpleNamespace(path=fake_path)
    old = load_functions(FROZEN, State(project=available, current_project_path=path), preflight=True)
    old['os'] = fake_os
    monkeypatch.setattr(planner, 'os', fake_os)
    expected = observation(lambda: old['duplicate_current_project_directory'](name))
    old_events = list(events)
    events.clear()
    actual = observation(lambda: asdict(planner.plan_project_directory_duplication(
        path, name, project_available=available,
        isfile=fake_path.isfile, isdir=fake_path.isdir, exists=fake_path.exists,
    )))
    assert actual == expected
    assert events == old_events


def test_predicate_exception_identity_and_default_failure():
    error = PermissionError('denied')
    def fail(_):
        raise error
    with pytest.raises(PermissionError) as caught:
        planner.plan_project_directory_duplication('P/p.json', 'Copy', project_available=True,
            isfile=fail, isdir=lambda _: True, exists=lambda _: False)
    assert caught.value is error
    with pytest.raises(PermissionError) as caught:
        planner.default_duplicate_project_dir_name('P/p.json', exists=fail)
    assert caught.value is error


@pytest.mark.parametrize('blocked', [False, True])
@pytest.mark.parametrize('save_failure', [False, True])
def test_actual_app_import_and_write_boundary(monkeypatch, blocked, save_failure):
    project = object()
    state = State(project=project, current_project_path='Project/p.json')
    app = load_functions(APP, state)
    assert app['project_directory_duplication'] is planner
    calls = []
    original = planner.plan_project_directory_duplication
    def plan(*args, **kwargs):
        calls.append('plan')
        result = original(*args, **kwargs)
        calls.append(result)
        return result
    monkeypatch.setattr(planner, 'plan_project_directory_duplication', plan)
    # Patch the app's observation surface only; no real files or copies needed.
    app['os'] = SimpleNamespace(path=SimpleNamespace(
        isfile=lambda _: True, isdir=lambda _: True, exists=lambda _: blocked,
    ))
    def save(value, path):
        calls.append(('save', value, path))
        if save_failure:
            raise OSError('save failed')
    app.update(
        save_project_to_json=save,
        ensure_current_project_folder_layout=lambda path: calls.append(('layout', path)),
        shutil=SimpleNamespace(copytree=lambda *args, **kwargs: calls.append(('copy', args, kwargs)), ignore_patterns=shutil.ignore_patterns),
        _find_copied_project_json=lambda *args: calls.append(('find', args)) or 'copied.json',
        load_project_json_into_session=lambda path: calls.append(('load', path)) or True,
        request_project_directory_discovery_refresh=lambda: calls.append('refresh'),
        datetime=datetime,
    )
    success, message = app['duplicate_current_project_directory']('A/B')
    result = calls[1]
    assert calls[0] == 'plan'
    if blocked:
        assert not success and message == result.error
        assert len(calls) == 2
    elif save_failure:
        assert not success and message == '複製前のプロジェクト保存に失敗しました: save failed'
        assert len(calls) == 3
    else:
        assert success
        assert calls[2:4] == [('save', project, result.source_project_path), ('layout', result.source_project_path)]
        assert calls[4][0:2] == ('copy', (result.source_project_dir, result.destination_dir))
        ignored = ['.promptgraph_cache', '.x.tmp', '.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.DS_Store', 'Thumbs.db']
        assert calls[4][2]['ignore']('unused', ignored + ['project.json', 'refs']) == set(ignored)
        assert calls[5:] == [('find', (result.destination_dir, result.source_project_path)), ('load', 'copied.json'), 'refresh']
        assert state.autosave_feedback == 'project duplicated'
        assert state.last_saved_at


def test_app_helpers_reach_imported_owner(monkeypatch):
    app = load_functions(APP, State(current_project_path='Project/p.json'))
    for wrapper, owner, args in [
        ('_sanitize_duplicate_project_dir_name', 'sanitize_duplicate_project_dir_name', ('A/B',)),
        ('_source_project_directory', 'source_project_directory', ()),
        ('_default_duplicate_project_dir_name', 'default_duplicate_project_dir_name', ()),
        ('_duplicate_project_destination_dir', 'duplicate_project_destination_dir', ('Copy',)),
    ]:
        spy = Mock(wraps=getattr(planner, owner))
        monkeypatch.setattr(planner, owner, spy)
        app[wrapper](*args)
        spy.assert_called_once()
