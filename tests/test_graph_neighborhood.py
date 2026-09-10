import unittest
from types import SimpleNamespace as NS
from core.graph_neighborhood import get_neighborhood_node_ids as neighborhood

class GraphNeighborhoodTests(unittest.TestCase):
    def test_early_returns(self):
        self.assertIsNone(neighborhood(None, ['a'], 1))
        self.assertIsNone(neighborhood(NS(), [], 1))
        self.assertIsNone(neighborhood(NS(), ['a'], None))
        self.assertEqual(set(), neighborhood(NS(nodes={}, edges=[None]), ['missing'], 1.5))

    def test_bidirectional_cycles_duplicates_and_external_endpoints(self):
        p = NS(nodes={'a': 1, 'b': 1}, edges=[('a','b'), ('a','b'), ('b','b'), ('outside','b')])
        self.assertEqual({'a','b'}, neighborhood(p, ['a','a','missing'], 1))
        self.assertEqual({'a','b','outside'}, neighborhood(p, ['a'], 2))
        self.assertEqual({'a','b','outside'}, neighborhood(p, ['b'], 20))
        self.assertEqual([('a','b'), ('a','b'), ('b','b'), ('outside','b')], p.edges)

    def test_step_types_and_nonpositive_values(self):
        p = NS(nodes={'a': 1}, edges=[('a','b')])
        for steps in [0, -2, False]:
            self.assertEqual({'a'}, neighborhood(p, ['a'], steps))
        self.assertEqual({'a','b'}, neighborhood(p, ['a'], True))
        with self.assertRaises(TypeError):
            neighborhood(p, ['a'], 1.0)

    def test_edges_are_eager_even_for_zero_steps(self):
        for edge, error in [(('a',), ValueError), (None, TypeError), (([], 'b'), TypeError)]:
            with self.subTest(edge=edge), self.assertRaises(error):
                neighborhood(NS(nodes={'a': 1}, edges=[edge]), ['a'], 0)
