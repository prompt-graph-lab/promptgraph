import unittest
from types import SimpleNamespace as NS
from core.focus_token_node_projection import get_focus_token_node_pairs as pairs

class FocusTokenNodeProjectionTests(unittest.TestCase):
    def test_short_path_missing_nodes_and_falsey_ids(self):
        result = pairs(NS(nodes={'a': None}), NS(tokens=['x','y','z','tail'], node_path=['a','missing','']))
        self.assertEqual([{'index': 0, 'token': 'x', 'node_id': 'a', 'selectable': True},
                          {'index': 1, 'token': 'y', 'node_id': 'missing', 'selectable': False},
                          {'index': 2, 'token': 'z', 'node_id': '', 'selectable': False},
                          {'index': 3, 'token': 'tail', 'node_id': None, 'selectable': False}], result)

    def test_long_path_duplicates_and_literal_marker_prefixes(self):
        tokens = ['<mod:a>', '</mod:a>', ' <mod:a>', '<MOD:a>', 'x']
        line = NS(tokens=tokens, node_path=['a'] * 6)
        result = pairs(NS(nodes={'a': 1}), line)
        self.assertEqual([False, False, True, True, True], [r['selectable'] for r in result])
        self.assertEqual(tokens, [r['token'] for r in result])
        self.assertEqual(['a'] * 6, line.node_path)
        self.assertIs(tokens, line.tokens)

    def test_falsey_inputs_and_token_identity(self):
        self.assertEqual([], pairs(None, NS(tokens=None, node_path=None)))
        token = object()
        self.assertIs(token, pairs(NS(), NS(tokens=[token]))[0]['token'])
        with self.assertRaises(AttributeError):
            pairs(NS(nodes={'a': 1}), NS(tokens=[token], node_path=['a']))

    def test_node_path_is_consumed_before_tokens(self):
        events = []
        def path():
            events.append('path'); yield 'a'
            events.append('path end')
        def tokens():
            events.append('token'); yield 'x'
        self.assertTrue(pairs(NS(nodes={'a': 1}), NS(tokens=tokens(), node_path=path()))[0]['selectable'])
        self.assertEqual(['path', 'path end', 'token'], events)

    def test_membership_short_circuit(self):
        with self.assertRaises(TypeError):
            pairs(NS(nodes=None), NS(tokens=['x'], node_path=['a']))
        self.assertFalse(pairs(NS(nodes=None), NS(tokens=[None], node_path=[0]))[0]['selectable'])
