import unittest
from core.comfy_workflow_outputs import _workflow_output_nodes, _workflow_save_image_nodes


class WorkflowOutputsTests(unittest.TestCase):
    def test_falsey_class_fallback_exact_case_and_duplicate_string_ids(self):
        nodes = {1: {'class_type': '', 'type': 'SaveImage'},
                 '1': {'class_type': False, 'type': 'custom.SaveImage'},
                 'preview': {'class_type': 0, 'type': 'PreviewImage'},
                 'case': {'class_type': 'saveimage'},
                 'precedence': {'class_type': 'Other', 'type': 'SaveImage'}}
        self.assertEqual(_workflow_output_nodes(nodes), ['1', '1', 'preview'])
        self.assertEqual(_workflow_save_image_nodes(nodes), ['1', '1'])
        self.assertEqual(nodes[1]['class_type'], '')
