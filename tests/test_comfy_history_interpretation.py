import unittest
from core.comfy_history_interpretation import _history_outputs, _history_prompt_record, _history_prompt_ids_sample


class HistoryInterpretationTests(unittest.TestCase):
    def test_selection_and_dict_only_outputs(self):
        record = {'outputs': {'x': {}}}
        for history in [{'p': record, 'other': {}}, {'arbitrary': record}]:
            self.assertIs(_history_prompt_record(history, 'p'), record)
            self.assertIs(_history_outputs(history, 'p'), record['outputs'])
        for history in [None, [], {'p': None}, {'other': []}, {'p': None, 'other': record}]:
            self.assertEqual(_history_prompt_record(history, 'p'), {})
            self.assertEqual(_history_outputs(history, 'p'), {})
        for value in [None, [], False, 'text']:
            self.assertEqual(_history_outputs({'p': {'outputs': value}}, 'p'), {})
        empty = {}
        self.assertIs(_history_prompt_record({'p': empty, 'other': record}, 'p'), empty)

    def test_sampling_native_slice_and_conversion_contract(self):
        history = {9: {}, 'b': {}, None: {}}
        for limit, expected in [(None, ['9','b','None']), (-1, ['9','b']), (0, []), (True, ['9'])]:
            self.assertEqual(_history_prompt_ids_sample(history, limit), expected)
        with self.assertRaises(TypeError):
            _history_prompt_ids_sample(history, 1.5)
        self.assertEqual(_history_prompt_ids_sample(None, 1.5), [])
