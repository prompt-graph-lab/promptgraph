import copy
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from core.node_selection_matching import get_node_match_terms, remap_selected_nodes_for_line


class NodeSelectionMatchingTests(unittest.TestCase):
    def test_terms_preserve_literal_and_add_parser_base(self):
        project = NS(nodes={'a': NS(display=' Smile ', word='SMILE', original='(Smile:1.2)')})
        self.assertEqual({'smile', '(smile:1.2)'}, get_node_match_terms(project, 'a'))
        self.assertEqual(set(), get_node_match_terms(project, 'missing'))
        self.assertEqual(set(), get_node_match_terms(NS(), 'missing'))

    def test_exact_matches_keep_selection_order_and_duplicates_without_parsing(self):
        project = NS(nodes={'a': NS(), 'b': NS(), 'outside': NS()})
        with patch('core.parser.extract_node_metadata', side_effect=AssertionError('must stay lazy')):
            self.assertEqual(['b', 'a', 'b'], remap_selected_nodes_for_line(project, NS(node_path=['a', 'b']), ['b', 'outside', 'a', 'b']))

    def test_fallback_keeps_path_order_deduplicates_and_is_read_only(self):
        project = NS(nodes={'old': NS(word='SMILE'), 'a': NS(original='(smile:1.2)'), 'b': NS(display='smile'), 'c': NS(word='other')})
        line = NS(node_path=['b', 'missing', 'a', 'b', 'c'])
        before = copy.deepcopy((project, line))
        self.assertEqual(['b', 'a'], remap_selected_nodes_for_line(project, line, ['old', 'missing']))
        self.assertEqual(before, (project, line))

    def test_falsey_missing_inputs(self):
        self.assertEqual([], remap_selected_nodes_for_line(None, NS(), ['a']))
        self.assertEqual([], remap_selected_nodes_for_line(NS(nodes={}), None, ['a']))
        self.assertEqual([], remap_selected_nodes_for_line(NS(nodes={}), NS(), []))
        self.assertEqual([], remap_selected_nodes_for_line(NS(nodes={}), NS(), ['missing']))

    def test_parser_exception_propagates(self):
        project = NS(nodes={'a': NS(word='x')})
        with patch('core.parser.extract_node_metadata', side_effect=ValueError('parser')):
            with self.assertRaisesRegex(ValueError, 'parser'):
                get_node_match_terms(project, 'a')

    def test_falsey_node_and_unicode_lower_semantics(self):
        project = NS(nodes={'empty': None, 'a': NS(word='Straße')})
        self.assertEqual(set(), get_node_match_terms(project, 'empty'))
        self.assertEqual({'straße'}, get_node_match_terms(project, 'a'))

    def test_retained_app_caller_uses_import_and_updates_state_in_order(self):
        import ast
        from pathlib import Path
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_bytes())
        nodes = [n for n in tree.body if
                 (isinstance(n, ast.ImportFrom) and n.module == 'core.node_selection_matching') or
                 (isinstance(n, ast.FunctionDef) and n.name == 'preserve_focus_selection_context')]
        class State(dict):
            __getattr__ = dict.__getitem__
            __setattr__ = dict.__setitem__
        state = State(connect_nodes=['a', 'old'])
        observed = []
        project = NS(nodes={'old': NS(word='x'), 'a': NS(word='x')})
        ns = {'st': NS(session_state=state),
              'sanitize_selected_node_ids': lambda p: observed.append((p, state.selected_node_ids[:], state.connect_nodes[:]))}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<app caller>', 'exec'), ns)
        ns['preserve_focus_selection_context'](project, NS(node_path=['a']), ['old'])
        self.assertEqual([(project, ['a'], ['a'])], observed)
