import unittest
from core.comfy_workflow_metadata import _load_json_from_text, _is_executable_comfy_workflow

class WorkflowMetadataTests(unittest.TestCase):
    def test_json_inputs_and_unexpected_valid_types(self):
        for value in [None, {}, 0, '', ' ', '{bad']:
            self.assertIsNone(_load_json_from_text(value))
        for text, expected in [('[]', []), ('false', False), ('0', 0), ('"x"', 'x'), ('null', None)]:
            self.assertEqual(expected, _load_json_from_text(text))

    def test_shape_requires_only_dictionary_inputs(self):
        for value in [None, [], {'inputs': {}}, {'x': {'inputs': []}}, {'x': None}]:
            self.assertFalse(_is_executable_comfy_workflow(value))
        self.assertTrue(_is_executable_comfy_workflow({'x': {'inputs': {}}}))

    def test_shape_short_circuits(self):
        class Bad(dict):
            def get(self, key): raise RuntimeError('visited')
        self.assertTrue(_is_executable_comfy_workflow({'a': {'inputs': {}}, 'b': Bad()}))
        with self.assertRaises(RuntimeError):
            _is_executable_comfy_workflow({'a': Bad(), 'b': {'inputs': {}}})
