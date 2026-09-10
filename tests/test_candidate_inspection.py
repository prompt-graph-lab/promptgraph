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

    def test_caption_retains_falsey_index_values(self):
        self.assertEqual(c._candidate_metadata_caption({'created_at':'t','source':'s','run_index':0,'origin_line_index':False}),'t / s / run 0 / line False')
        self.assertEqual(c._candidate_metadata_caption(None),'')
        self.assertEqual(c._candidate_metadata_caption({'created_at':0,'source':'','run_index':None}),'')

    def test_flags_and_partition_preserve_order_and_record_identity(self):
        active={'pinned':'false'}; trash={'trashed':1}; records=[active,trash,None,trash]
        self.assertTrue(c._candidate_is_pinned(active))
        self.assertFalse(c._candidate_is_trashed(None))
        result=c._active_candidates(records)
        self.assertEqual(result,[active,None]); self.assertIs(result[0],active)
        self.assertEqual(c._trashed_candidates(records),[trash,trash])
        self.assertIs(c._trashed_candidates(records)[0],trash)
        self.assertEqual(c._active_candidates(None),[])

    def test_display_sort_is_stable_and_keeps_records(self):
        a={}; b={'pinned':True}; d={'pinned':1}; records=[a,b,None,d]
        result=c._sort_candidates_for_display(records)
        self.assertEqual(result,[b,d,a,None]); self.assertIs(result[0],b)
        self.assertEqual(records,[a,b,None,d])
        with self.assertRaises(TypeError): c._sort_candidates_for_display(None)

    def test_provenance_values_preserve_alias_and_seed_zero(self):
        value=['workflow']; record={'workflow':0,'workflow_path':value,'seed':0}
        self.assertIs(c._candidate_prompt_value(record,'workflow','workflow_path'),value)
        self.assertEqual(c._candidate_route_candidate_workflow(record),"['workflow']")
        self.assertEqual(c._candidate_route_candidate_seed(record),0)
        self.assertEqual(c._candidate_prompt_value(None,'x'),'')
        self.assertIsNone(c._candidate_route_candidate_seed(None))

    def test_swap_lineage_projection_does_not_adopt_or_mutate(self):
        seed=[]; candidate={'seed':seed,'source':'s','workflow_name':'w'}; previous={'path':None,'field':'image_path'}
        self.assertEqual(c._candidate_image_swap_lineage_info(candidate,'new',previous,'time'),{
            'mode':'swap_main_image_with_candidate','new_main_image_path':'new','previous_main_image_path':'',
            'previous_main_image_field':'image_path','swapped_at':'time','candidate_source':'s','candidate_seed':[], 'candidate_workflow':'w'})
        self.assertIs(c._candidate_image_swap_lineage_info(candidate,'new',previous,'time')['candidate_seed'],seed)
        self.assertEqual(previous,{'path':None,'field':'image_path'})
        with self.assertRaises(AttributeError): c._candidate_image_swap_lineage_info({},'x',None,'t')
