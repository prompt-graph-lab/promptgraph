"""Read-only Graph display contracts; no UI or graph construction required."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from core import graph_display

NAMES = (
    'get_graph_node_ids_for_line', 'sort_graph_node_ids_for_display',
    'get_wrapped_graph_positions', 'get_initial_graph_display_node_ids',
    'get_branch_visual_hints', 'get_cooccurrence_overlay_edges',
)
F = vars(graph_display)


def node(depth=0, display='', count=0, previous=(), following=()):
    return NS(depth=depth, display=display, count=count,
              prev_node_ids=set(previous), next_node_ids=set(following))


class GraphDisplayTests(unittest.TestCase):
    def test_app_exposes_the_same_helpers_to_graph_renderer(self):
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8'))
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'core.graph_display']
        scope = {}
        exec(compile(ast.Module(body=imports, type_ignores=[]), 'app.py', 'exec'), scope)
        for name in NAMES:
            self.assertIs(scope[name], F[name])

    def test_line_membership_filters_missing_and_deduplicates(self):
        project = NS(nodes={'a': node()})
        line = NS(node_path=['a', 'missing', 'a'])
        before = copy.deepcopy((project, line))
        self.assertEqual(F[NAMES[0]](project, line), {'a'})
        self.assertEqual((project, line), before)
        self.assertEqual(F[NAMES[0]](None, line), set())
        self.assertEqual(F[NAMES[0]](project, None), set())
        with self.assertRaises(TypeError):
            F[NAMES[0]](project, NS(node_path=None))

    def test_sort_focus_first_occurrence_stable_ties_and_duplicates(self):
        project = NS(nodes={'a': node(2, 'z'), 'b': node(1, 'b'), 'c': node(1, 'b'), 'd': node(0, 'a')})
        order = ['c', 'b', 'missing', 'a', 'a', 'd']
        self.assertEqual(F[NAMES[1]](project, order), ['d', 'c', 'b', 'a', 'a'])
        self.assertEqual(F[NAMES[1]](project, order, NS(node_path=['a', 'd', 'a'])), ['a', 'a', 'd', 'c', 'b'])
        self.assertEqual(order, ['c', 'b', 'missing', 'a', 'a', 'd'])

    def test_wrapped_positions_center_partial_rows_and_truncate(self):
        f = F[NAMES[2]]
        self.assertEqual(f(['a', 'b', 'c'], 2, 5, 7), {'a': {'x': -2, 'y': 0}, 'b': {'x': 2, 'y': 0}, 'c': {'x': 0, 'y': 7}})
        self.assertEqual(f(['a', 'a'], 1), {'a': {'x': 0, 'y': 90}})
        self.assertEqual(f([], 0), {})
        with self.assertRaises(ZeroDivisionError):
            f(['a'], 0)

    def test_initial_depth_or_stable_count_rank_and_limit(self):
        f = F[NAMES[3]]
        self.assertEqual(f(None), set())
        project = NS(nodes={'a': node(2), 'b': node(3), 'c': node(-1)})
        self.assertEqual(f(project), {'a', 'c'})
        project = NS(nodes={str(i): node(100, count=1) for i in range(82)}, merge_by_word_only=True)
        self.assertEqual(f(project), {str(i) for i in range(80)})

    def test_branch_hints_threshold_weak_children_and_missing_nodes(self):
        project = NS(nodes={'p': node(count=10, following=['a', 'b', 'missing']), 'a': node(count=6, previous=['p']), 'b': node(count=7, previous=['p']), 'isolated': node(count=100)})
        before = copy.deepcopy(project)
        self.assertEqual(F[NAMES[4]](project, ['p', 'a', 'b', 'isolated', 'missing']), ({'p'}, {'p'}, {('p', 'a')}))
        self.assertEqual(F[NAMES[4]](project, ['p', 'a']), (set(), {'p'}, set()))
        self.assertEqual(F[NAMES[4]](None, ['a']), (set(), set(), set()))
        self.assertEqual(project, before)

    def test_overlay_unique_per_line_deleted_and_syntax_exclusion(self):
        project = NS(nodes={k: node() for k in 'abc'}, edges=[('b', 'a')], prompt_lines=[NS(node_path=['a', 'a', 'b', 'c']) for _ in range(3)] + [NS(node_path=['a', 'c'], deleted=True)])
        before = copy.deepcopy(project)
        self.assertEqual(F[NAMES[5]](project, ['a', 'b', 'c']), [('a', 'c', 3)])
        self.assertEqual(F[NAMES[5]](project, ['a', 'b', 'c'], max_edges_per_node=2), [('a', 'c', 3), ('b', 'c', 3)])
        self.assertEqual(F[NAMES[5]](project, ['a', 'b', 'c'], max_nodes_per_line=2), [])
        self.assertEqual(project, before)

    def test_overlay_display_order_limits_and_legacy_zero_edge_limit(self):
        project = NS(nodes={k: node() for k in 'abc'}, prompt_lines=[NS(node_path=['a', 'b', 'c'])])
        f = F[NAMES[5]]
        self.assertEqual(f(project, ['c', 'b', 'a'], min_count=1, max_edges_per_node=2), [('c', 'b', 1), ('c', 'a', 1), ('b', 'a', 1)])
        self.assertEqual(f(project, ['a', 'b', 'c'], min_count=1, max_edges=0), [('a', 'b', 1)])
        self.assertEqual(f(project, ['a', 'b', 'c'], min_count=1, max_edges_per_node=0), [])
        self.assertEqual(f(project, ['a', 'b', 'c']), [])
        self.assertEqual(f(None, ['a', 'b']), [])
        with self.assertRaises(TypeError):
            f(NS(nodes=project.nodes, edges=None), ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
