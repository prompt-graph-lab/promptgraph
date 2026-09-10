import copy
import unittest
from types import SimpleNamespace as NS
from core.module_scope_inspection import preview_module_scope


def line(tokens, **kw):
    return NS(tokens=tokens, id='line', original_file_name='x', current_index=2,
              current_text='raw', **kw)


class ModuleScopeInspectionTests(unittest.TestCase):
    def test_nested_duplicates_and_deleted_lines(self):
        project = NS(prompt_lines=[line(['<mod:a>', 'x', '<mod:a>', 'x', '</mod:a>', 'y', '</mod:a>']), line(['<mod:a>z</mod:a>'], deleted=True)])
        before = copy.deepcopy(project)
        result = preview_module_scope(project, 'a')
        self.assertEqual(3, result['range_token_count'])
        self.assertEqual(['x', 'x', 'y'], result['examples'][0]['range_tokens'])
        self.assertEqual(3, result['examples'][0]['line_number'])
        self.assertEqual(before, project)

    def test_malformed_inline_and_unclosed_counts_without_examples(self):
        project = NS(prompt_lines=[line(['</mod:a>', '<mod:a>x</mod:b>', '<mod:a>', 'x'])])
        result = preview_module_scope(project, 'a', example_limit=0)
        self.assertEqual(3, result['malformed_count'])
        self.assertEqual(1, result['affected_line_count'])
        self.assertEqual(1, result['token_count'])
        self.assertEqual([], result['examples'])

    def test_empty_inline_is_still_an_occurrence(self):
        result = preview_module_scope(NS(prompt_lines=[line(['<mod:a></mod:a>'])]), 'a')
        self.assertEqual(1, result['inline_module_count'])
        self.assertEqual([''], result['examples'][0]['inline_contents'])

    def test_empty_closed_scope_and_other_unmatched_close(self):
        result = preview_module_scope(NS(prompt_lines=[line(['<mod:a>', '</mod:b>', '</mod:a>'])]), 'a')
        self.assertEqual(0, result['affected_line_count'])
        self.assertEqual([], result['examples'])

    def test_bad_token_exception_propagates_but_deleted_is_lazy(self):
        with self.assertRaises(AttributeError):
            preview_module_scope(NS(prompt_lines=[line([None])]), 'a')
        self.assertEqual(0, preview_module_scope(NS(prompt_lines=[line([None], deleted=True)]), 'a')['token_count'])
