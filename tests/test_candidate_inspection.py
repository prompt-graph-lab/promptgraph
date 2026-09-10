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

    def test_prompt_metadata_source_gate_and_field_priority(self):
        record={'source':'manual_import','prompt_text':' p ','negative':' n '}
        self.assertEqual(c._candidate_prompt_metadata(record),{})
        record['candidate_prompt_source']='imported_image_metadata'
        before=copy.deepcopy(record)
        self.assertEqual(c._candidate_prompt_metadata(record),{'positive_prompt':'p','negative_prompt':'n'})
        self.assertEqual(record,before)
        self.assertEqual(c._candidate_prompt_metadata({'prompt_text':' ','positive_prompt':'fallback'}),{})
        self.assertEqual(c._candidate_prompt_metadata({'negative_prompt':7}),{'positive_prompt':'','negative_prompt':'7'})

    def test_prompt_text_priority_nested_fallback_and_json_rejection(self):
        record={'source_prompt':' {} ', 'prompt_text':9,'metadata':{'prompt':' chosen '},'source_raw_metadata':{'prompt':'later'}}
        self.assertEqual(c.get_candidate_prompt_text(record),'chosen')
        self.assertEqual(c.get_candidate_prompt_text({'prompt':'{broken'}),'{broken')
        self.assertEqual(c.get_candidate_prompt_text({'source_prompt':'first','prompt_text':'second'}),'first')
        self.assertEqual(c.get_candidate_prompt_text({'prompt':'[]'}),'')
        self.assertFalse(c._looks_like_workflow_json_prompt('"text"'))
        self.assertIsNone(c._candidate_nested_value({'x':[]},'x','key'))
        self.assertEqual(c.get_candidate_prompt_text(None),'')

    def test_original_prompt_comparison_and_parser_error_fallback(self):
        line=NS(original_text=' a, b ',current_text='a,b')
        self.assertFalse(c.is_line_prompt_changed_from_original(line))
        self.assertEqual(c._prompt_original_status_label(line),'Prompt: original')
        line.current_text='b,a'
        self.assertEqual(c._prompt_original_status_label(line),'Prompt: edited')
        self.assertEqual(c._prompt_original_status_label(NS(current_text='x')),'Prompt: no original')
        with patch.object(c,'parse_prompt',side_effect=ValueError('legacy')):
            self.assertEqual(c.normalize_prompt_for_revert_compare(' a ,, b '),['a','b'])
        self.assertEqual(c.normalize_prompt_for_revert_compare(None),[])
