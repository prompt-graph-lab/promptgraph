import copy
from types import SimpleNamespace as NS
import unittest

from core import promptcloud_calculations as owner


class PromptCloudCalculationTests(unittest.TestCase):
    def test_sanitization_counts_merges_and_errors(self):
        freq = {' a\n b ': 2, 'a b': 3, '': 4, None: 9}
        before = copy.deepcopy(freq)
        self.assertEqual(owner.sanitize_promptcloud_frequencies(freq), ({'a b': 5}, 1, 2))
        self.assertEqual(freq, before)
        self.assertEqual(owner.sanitize_promptcloud_word(0), '')
        self.assertEqual(owner.sanitize_promptcloud_frequencies(None), ({}, 0, 0))
        with self.assertRaises(TypeError):
            owner.sanitize_promptcloud_frequencies({'a': None})

    def test_membership_raw_match_precedes_parser_and_eligibility(self):
        a = NS(id='a', tokens=[' blue\n sky '])
        b = NS(id='b', tokens=[], current_text='(blue sky:1.2), red')
        c = NS(id='c', tokens=['blue sky'], deleted=True)
        d = NS(id='d', tokens=['blue sky'], line_type='workbench')
        project = NS(prompt_lines=[a, b, c, d])
        before = copy.deepcopy(project)
        self.assertEqual(owner.line_ids_containing_word(project, 'blue sky'), ['a', 'b'])
        self.assertEqual(project, before)
        self.assertEqual(owner.line_ids_containing_word(None, 'x'), [])
        self.assertEqual(owner.line_ids_containing_word(project, ''), [])

    def test_frequencies_keep_literal_forms_and_duplicate_counts(self):
        line = NS(tokens=[' sky ', 'sky', '(sky:1.2)', '<mod:sky>', '', None])
        project = NS(prompt_lines=[line, NS(tokens=['x'], line_type='separator')])
        before = copy.deepcopy(project)
        self.assertEqual(owner.build_promptcloud_token_frequencies(project), (
            {'sky': 2, '(sky:1.2)': 1}, {'default': {'sky': 2, '(sky:1.2)': 1}}))
        self.assertEqual(project, before)
        self.assertEqual(owner.build_promptcloud_token_frequencies(None), ({}, {}))
