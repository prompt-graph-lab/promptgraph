"""Final Export planning contracts and frozen-base runtime differential tests."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import final_export_scope as planner
from core.operations import get_gallery_route_options, resolve_gallery_route_for_line
from core.prompt_line_selection import get_visible_prompt_lines, is_gallery_operation_prompt_line, is_route_separator
from core.project import Project, PromptLine
from core.route_operations import resolve_selected_route_export_lines

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / 'tests/fixtures/final_export_scope_legacy.py'
HELPERS = {'_gallery_route_anchor_line_id', '_gallery_route_options_with_counts',
           '_gallery_route_line_count', '_final_export_route_options', 'resolve_final_export_lines'}


def load(source):
    tree = ast.parse(source)
    nodes = [n for n in tree.body if
             (isinstance(n, ast.FunctionDef) and n.name in HELPERS) or
             (isinstance(n, ast.ImportFrom) and n.module == 'core.final_export_scope')]
    ns = dict(st=SimpleNamespace(session_state={}), get_visible_prompt_lines=get_visible_prompt_lines,
              is_gallery_operation_prompt_line=is_gallery_operation_prompt_line,
              is_route_separator=is_route_separator, get_gallery_route_options=get_gallery_route_options,
              resolve_gallery_route_for_line=resolve_gallery_route_for_line,
              resolve_selected_route_export_lines=resolve_selected_route_export_lines)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'scope-oracle', 'exec'), ns)
    return ns


def line(key, index, kind=None, deleted=False):
    return PromptLine(key, key, index, index, key, key, [key], line_type=kind, deleted=deleted)


def project_fixture():
    lines = [line('unrouted', 10), line('a', 1, 'separator'), line('a1', 5),
             line('workbench', 3, 'workbench'), line('deleted', 4, deleted=True),
             line('a2', 2), line('b', 6, 'separator'), line('b1', 7),
             line('empty', 8, 'separator'), line('tail', 9, 'workbench')]
    lines[2].generated_candidates = [{'path': 'one'}, {'path': 'two'}]
    lines[2].gallery_variants = [{'path': 'variant'}]
    return Project(prompt_lines=lines)


class FinalExportScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.legacy = FROZEN.read_text(encoding='utf-8')

    def setUp(self):
        self.old = load(self.legacy)
        self.new = load(self.app)
        self.project = project_fixture()

    def core(self, project, scope, route_id=None, selected_route_ids=None, anchor=''):
        normalized, lines = planner.prepare_final_export_scope(project, scope)
        options = ()
        if normalized == 'selected_route':
            route_id = str(route_id or '').strip()
            options = self.new['_final_export_route_options'](project)
        return planner.resolve_final_export_targets(project, normalized, lines,
            anchor_line_id=anchor, route_id=route_id, route_options=options,
            selected_route_ids=selected_route_ids)

    def assert_identical(self, actual, expected):
        self.assertEqual(set(actual), set(expected))
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual['lines']), len(expected['lines']))
        for left, right in zip(actual['lines'], expected['lines']):
            self.assertIs(left, right)
        for key in actual:
            if key != 'lines':
                self.assertEqual(actual[key], expected[key], key)

    def test_all_lines_filtering_display_order_and_invalid_scope_default(self):
        result = self.core(self.project, 'all_lines')
        self.assertEqual(result['line_ids'], ['a2', 'a1', 'b1', 'unrouted'])
        self.assertEqual(result['warnings'], [])
        for scope in ('unknown', '', None, False):
            self.assert_identical(self.core(self.project, scope), result)
        self.assertIs(result['lines'][0], self.project.prompt_lines[5])
        self.assertIsNone(result['route_line_count'])
        self.assertEqual(result['route_summaries'], [])

    def test_selected_route_normalization_membership_and_exact_warnings(self):
        result = self.core(self.project, 'selected_route', ' a ')
        self.assertEqual(result['line_ids'], ['a2', 'a1'])
        self.assertEqual(result['route_id'], 'a')
        self.assertEqual(result['route_label'], 'a')
        self.assertEqual(result['warnings'], [])
        for route in (None, '', False, 'missing'):
            self.assertEqual(self.core(self.project, 'selected_route', route)['warnings'], ['シーンが選択されていません。'])
        self.assertEqual(self.core(self.project, 'selected_route', 'empty')['warnings'],
                         ['選択されたシーンには書き出し対象イラストがありません。'])

    def test_current_route_anchor_precedence_and_invalid_anchor_does_not_fall_through(self):
        cases = [({'focused_line_id': 'a1', 'gallery_expanded_line_id': 'b1'}, ['b1'], 'a1'),
                 ({'gallery_expanded_line_id': 'b1'}, ['', None, 'a1', 'b1'], 'a1'),
                 ({'gallery_expanded_line_id': 'b1', 'gallery_selected_route_separator_id': 'a'}, [], 'b1'),
                 ({'gallery_selected_route_separator_id': 'a'}, [], 'a'),
                 ({'gallery_selected_route_separator_id': 'missing'}, [], ''),
                 ({'focused_line_id': 'missing', 'gallery_expanded_line_id': 'a1'}, ['b1'], 'missing')]
        for state, selected, anchor in cases:
            with self.subTest(state=state, selected=selected):
                self.new['st'].session_state = state
                self.assertEqual(self.new['_gallery_route_anchor_line_id'](self.project, selected), anchor)
                actual = self.new['resolve_final_export_lines'](self.project, 'current_route', selected_line_ids=selected)
                self.assert_identical(actual, self.core(self.project, 'current_route', anchor=anchor))
        self.assertEqual(self.core(self.project, 'current_route')['warnings'],
                         ['No current line is available to resolve a Route.'])

    def test_selected_routes_reuses_all_lower_resolver_fields_and_physical_order(self):
        selected = ['b', 'a', 'a', 'missing', 'a1']
        lower = resolve_selected_route_export_lines(self.project, selected)
        result = self.core(self.project, 'selected_routes', selected_route_ids=selected)
        self.assertEqual(result['line_ids'], ['a1', 'a2', 'b1'])
        self.assertEqual(result['route_line_count'], len(lower['target_lines']))
        for key in ('resolved_route_handles', 'resolved_route_labels', 'selected_route_count',
                    'selected_main_line_count', 'selected_workbench_count', 'selected_deleted_member_count',
                    'selected_candidate_count', 'selected_gallery_variant_count', 'route_summaries', 'diagnostics'):
            self.assertEqual(result[key], lower[key], key)
        self.assertEqual(result['warnings'], lower['diagnostics'])
        self.assertEqual([id(x) for x in result['lines']], [id(x) for x in lower['target_lines']])
        self.assertTrue(result['diagnostics'])

    def test_duplicate_overlapping_memberships_preserve_legacy_scope_difference(self):
        shared = line('same', 1)
        project = Project(prompt_lines=[line('a', 0, 'separator'), shared,
                                       line('b', 2, 'separator'), shared])
        selected = self.core(project, 'selected_route', 'a')
        self.assertEqual(selected['lines'], [shared, shared])
        self.assertIs(selected['lines'][0], selected['lines'][1])
        multi = self.core(project, 'selected_routes', selected_route_ids=['b', 'a', 'a'])
        self.assertEqual(multi['lines'], [])
        self.assertIn('ambiguous selected Route line id: same', multi['diagnostics'])

    def test_empty_inputs_all_fields_identity_determinism_and_no_mutation(self):
        for project in (None, Project(), self.project):
            for scope in ('all_lines', 'current_route', 'selected_route', 'selected_routes'):
                selected = ['b', 'a', 'missing']
                before = copy.deepcopy((project, selected))
                first = self.core(project, scope, 'a', selected, 'a1')
                second = self.core(project, scope, 'a', selected, 'a1')
                self.assert_identical(first, second)
                self.assertEqual((project, selected), before)
                for target in first['lines']:
                    self.assertTrue(any(target is source for source in project.prompt_lines))

    def test_preparation_failure_precedes_session_lookup(self):
        class ForbiddenState:
            def get(self, *args):
                raise AssertionError('session accessed too early')
        self.new['st'].session_state = ForbiddenState()
        with self.assertRaises(TypeError):
            self.new['resolve_final_export_lines'](Project(prompt_lines=None), 'current_route')

    def test_planner_has_no_ui_or_filesystem_dependency(self):
        with patch('builtins.open', side_effect=AssertionError('filesystem access')), \
             patch('os.stat', side_effect=AssertionError('filesystem access')):
            for scope in ('all_lines', 'current_route', 'selected_routes'):
                self.core(self.project, scope, selected_route_ids=['a'], anchor='a1')
            scope, lines = planner.prepare_final_export_scope(self.project, 'selected_route')
            planner.resolve_final_export_targets(self.project, scope, lines, route_id='a',
                route_options=[{'route_id': 'a', 'line_ids': ['a1']}])
        tree = ast.parse((ROOT / 'core/final_export_scope.py').read_text(encoding='utf-8'))
        self.assertEqual({n.module for n in tree.body if isinstance(n, ast.ImportFrom)},
                         {'core.prompt_line_selection', 'core.operations', 'core.route_operations'})

    def test_frozen_base_differential_fields_identities_exceptions_and_mutation(self):
        malformed = [None, Project(), SimpleNamespace(), Project(prompt_lines=None),
                     Project(prompt_lines='invalid'), self.project,
                     Project(prompt_lines=[line('a', 0, 'separator'), line('dup', 1), line('dup', 2)]),
                     Project(prompt_lines=[line('a', 0, 'separator'), line('a', 1, 'separator')])]
        cases = [('all_lines', None, None, None), ('invalid', None, None, None),
                 ('current_route', None, [], None), ('current_route', None, [None, 'a1'], None),
                 ('selected_route', ' a ', None, None), ('selected_route', None, None, None),
                 ('selected_route', 'empty', None, None),
                 ('selected_routes', None, None, ['b', 'a', 'a', 'missing', 'a1']),
                 ('selected_routes', None, None, []), ('selected_routes', None, None, 'a'),
                 ('selected_routes', None, None, 123), ([], None, None, None)]
        for project in malformed:
            for scope, route, selected, routes in cases:
                for state in ({}, {'focused_line_id': 'b1'}, {'gallery_selected_route_separator_id': 'a'}):
                    with self.subTest(scope=scope, state=state, project=project):
                        before = copy.deepcopy((project, selected, routes, state))
                        outcomes = []
                        for ns in (self.old, self.new, None):
                            try:
                                if ns is not None:
                                    ns['st'].session_state = state
                                    result = ns['resolve_final_export_lines'](project, scope, route, selected, routes)
                                else:
                                    normalized, active = planner.prepare_final_export_scope(project, scope)
                                    anchor, options, route_value = '', (), route
                                    if normalized == 'current_route':
                                        anchor = self.old['_gallery_route_anchor_line_id'](project, selected or [])
                                    elif normalized == 'selected_route':
                                        route_value = str(route or '').strip()
                                        options = self.old['_final_export_route_options'](project)
                                    result = planner.resolve_final_export_targets(project, normalized, active,
                                        anchor_line_id=anchor, route_id=route_value, route_options=options,
                                        selected_route_ids=routes)
                                outcomes.append(('result', result))
                            except Exception as exc:
                                outcomes.append(('error', (type(exc), str(exc))))
                        for outcome in outcomes[1:]:
                            self.assertEqual(outcomes[0][0], outcome[0])
                            if outcomes[0][0] == 'error':
                                self.assertEqual(outcomes[0], outcome)
                            else:
                                self.assert_identical(outcomes[0][1], outcome[1])
                        self.assertEqual((project, selected, routes, state), before)


if __name__ == '__main__':
    unittest.main()
