import copy
import unittest
from core.lora_mapping_presentation import (
    _lora_loader_candidate_label, _lora_ref_weight_label, _dedupe_lora_reference_options,
    _lora_reference_option_label, _safe_float_or_default, _lora_strength_defaults,
    _lora_reference_signature, _mapped_lora_option_label, _key_fragment,
)

class LoraMappingPresentationTests(unittest.TestCase):
    def test_exact_labels_and_required_fields(self):
        self.assertEqual('1 - Lora -  - model= - clip= - missing: a, b', _lora_loader_candidate_label({'node_id': 1, 'class_type': 'Lora', 'missing_fields': ['a','b']}))
        with self.assertRaises(KeyError): _lora_loader_candidate_label({})
        self.assertEqual('x', _lora_reference_option_label({'name':'x'}))
        self.assertEqual('x - weights: 1, 2', _lora_reference_option_label({'name':'x','weights':['1','2']}))
        self.assertEqual('mapped', _mapped_lora_option_label({'label':'mapped','weights':None}))
        self.assertEqual('mapped - weights: 1', _mapped_lora_option_label({'label':'mapped','weights':['1']}))
        with self.assertRaises(TypeError): _mapped_lora_option_label({'label':'x','weights':[1]})

    def test_grouping_stable_case_ties_and_first_nonempty_weights(self):
        refs=[{'name':'b'}, {'name':'a','model_weight':0}, {'name':'A','model_weight':'2'},
              {'name':'a','model_weight':'1'}, {'name':'a','model_weight':'3','clip_weight':'4'},
              {'name':'a','model_weight':'1'}, {'name':''}]
        before=copy.deepcopy(refs)
        result=_dedupe_lora_reference_options(refs)
        self.assertEqual(['a','A','b'], [r['name'] for r in result])
        self.assertEqual({'name':'a','weights':['1','3/4'],'model_weight':'1','clip_weight':'4'},result[0])
        self.assertEqual(before,refs)
        self.assertEqual('',_lora_ref_weight_label({'model_weight':False}))
        self.assertEqual(2,_lora_ref_weight_label({'clip_weight':2}))

    def test_numeric_fallback_identity_and_exceptions(self):
        fallback=object()
        self.assertIs(fallback,_safe_float_or_default('bad',fallback))
        self.assertEqual((1.0,1.0),_lora_strength_defaults())
        self.assertEqual((0.0,0.0),_lora_strength_defaults(False,None))
        self.assertEqual((2.0,3.0),_lora_strength_defaults('2','3'))
        class Bad:
            def __float__(self): raise OverflowError('overflow')
        with self.assertRaises(OverflowError): _safe_float_or_default(Bad(),1)

    def test_signature_keeps_duplicates_and_sorts_raw_pairs(self):
        self.assertEqual((('',''),('a','1'),('a','1'),('b','2')), _lora_reference_signature([{'line_id':'b','raw':'2'},{'line_id':'a','raw':'1'},{},{'line_id':'a','raw':'1'}]))
        with self.assertRaises(TypeError): _lora_reference_signature([{'line_id':None},{'line_id':'x'}])

    def test_key_fragment_unicode_falsey_and_truncation(self):
        self.assertEqual('empty',_key_fragment(0))
        self.assertEqual('青_a_',_key_fragment('青-a!'))
        self.assertEqual('x'*80,_key_fragment('x'*81))
        self.assertEqual('_',_key_fragment('!'))

    def test_malformed_reference_exceptions(self):
        with self.assertRaises(AttributeError): _dedupe_lora_reference_options([None])
        with self.assertRaises(TypeError): _dedupe_lora_reference_options([{'name':['x']}])
        with self.assertRaises(AttributeError): _dedupe_lora_reference_options([{'name':1}])
