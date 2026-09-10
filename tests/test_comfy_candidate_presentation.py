import unittest
from core.comfy_candidate_presentation import _comfy_candidate_label, _candidate_default_index

class ComfyCandidatePresentationTests(unittest.TestCase):
    def test_exact_labels_falsey_preview_and_required_fields(self):
        candidate={'node_id':0,'class_type':None,'role':'positive','text_preview':False}
        self.assertEqual('0 - None - positive',_comfy_candidate_label(candidate))
        candidate['text_preview']='  text  '
        self.assertEqual('0 - None - positive -   text  ',_comfy_candidate_label(candidate))
        with self.assertRaises(KeyError): _comfy_candidate_label({})

    def test_first_role_match_and_lazy_later_candidates(self):
        self.assertEqual(1,_candidate_default_index([{'role':'other'},{'role':'x'},None], 'x', 7))
        self.assertEqual(0,_candidate_default_index([{}, {'role':None}], None))
        with self.assertRaises(AttributeError): _candidate_default_index([None], 'x')

    def test_fallback_is_not_clamped_or_coerced(self):
        marker=object()
        self.assertIs(marker,_candidate_default_index([{}], 'x', marker))
        self.assertEqual(-3,_candidate_default_index([{}], 'x', -3))
        self.assertEqual(0,_candidate_default_index([], 'x', marker))

    def test_empty_iterator_retains_truthy_fallback(self):
        self.assertEqual(8,_candidate_default_index(iter([]), 'x', 8))
