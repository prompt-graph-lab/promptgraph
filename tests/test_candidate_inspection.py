import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from core import candidate_inspection as c


class CandidateInspectionTests(unittest.TestCase):
    def test_path_values_do_not_resolve_or_normalize(self):
        for value, expected in [(None,''), ({'path':0},''), ({'path':' ../x '},' ../x '), (7,'7')]:
            self.assertEqual(c._candidate_path(value),expected)
        path=[]
        line=NS(selected_candidate_path='',generated_image_path=path)
        self.assertIs(c._selected_candidate_path(line),path)
        self.assertIsNone(c._selected_candidate_path(NS()))
