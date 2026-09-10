import unittest
from types import SimpleNamespace as NS
from core.nearby_line_selection import _get_nearby_lines

class NearbyLineSelectionTests(unittest.TestCase):
    def test_sort_filter_and_identity(self):
        a=NS(id='a',current_index=0)
        b=NS(id='b',current_index=1)
        c=NS(id='c',current_index=None)
        deleted=NS(id='d',current_index=0,deleted=True)
        source=[c,b,deleted,a]
        result=_get_nearby_lines(NS(prompt_lines=source),b)
        self.assertEqual([a,c],result)
        self.assertIs(a,result[0]); self.assertIs(c,result[1])
        self.assertEqual([c,b,deleted,a],source)

    def test_duplicate_id_first_position_and_stable_ties(self):
        a=NS(id='a',current_index=0); duplicate=NS(id='a',current_index=0)
        b=NS(id='b',current_index=0)
        self.assertEqual([], _get_nearby_lines(NS(prompt_lines=[a,duplicate,b]),duplicate,1))
        self.assertEqual([b], _get_nearby_lines(NS(prompt_lines=[a,duplicate,b]),duplicate,2))

    def test_missing_falsey_and_radius_semantics(self):
        self.assertEqual([],_get_nearby_lines(None,NS()))
        self.assertEqual([],_get_nearby_lines(NS(),NS(id='x')))
        line=NS(id='a'); p=NS(prompt_lines=[line,NS(id='b')])
        for radius in [0,-1]: self.assertEqual([],_get_nearby_lines(p,line,radius))
        with self.assertRaises(TypeError): _get_nearby_lines(p,line,0.5)

    def test_malformed_indices_propagate(self):
        p=NS(prompt_lines=[NS(id='a',current_index=1),NS(id='b',current_index='2')])
        with self.assertRaises(TypeError): _get_nearby_lines(p,p.prompt_lines[0])
