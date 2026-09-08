import copy
import unittest

from core.comfyui import _build_output_diagnostics as build
from core.comfyui import _format_output_diagnostics as format_diagnostics
from core.comfyui import COMFY_OUTPUT_POLL_ATTEMPTS


class OutputDiagnosticTests(unittest.TestCase):
    def args(self, **overrides):
        values = dict(prompt_id='p', history={}, prompt_history={}, outputs={}, workflow_json={},
                      save_image_node_ids=[], extraction={}, attempt_count=0, attempt_logs=[], last_history_fetch_error='')
        values.update(overrides)
        return values

    def test_exact_dictionary_order_and_normal_values(self):
        args = self.args(history={'p': {}}, prompt_history={'status': {'status_str': 'success', 'messages': [['ok', {}]]}},
                         outputs={'9': {}, '2': {}}, workflow_json={'9': {'class_type': 'SaveImage'}, '2': {'class_type': 'PreviewImage'}},
                         save_image_node_ids=['9'], extraction={'save_nodes_with_outputs': ['9'], 'save_node_output_keys': {'9': ['images']}},
                         attempt_count=1, attempt_logs=[{'attempt': 1}])
        before = copy.deepcopy(args)
        expected = dict(queued_prompt_id='p', history_prompt_ids_sample=['p'], target_history_found=True,
                        target_status='success', target_status_messages=[['ok', {}]], target_outputs_keys=['9', '2'],
                        save_image_node_ids=['9'], save_image_outputs_found=True, save_image_nodes_with_outputs=['9'],
                        save_image_node_output_keys={'9': ['images']}, workflow_node_count=2,
                        workflow_save_image_node_ids=['9'], workflow_output_node_ids=['9', '2'],
                        attempt_count=1, last_history_fetch_error='none', attempts=[{'attempt': 1}])
        result = build(**args)
        self.assertEqual(result, expected)
        self.assertEqual(list(result), list(expected))
        format_diagnostics(result)
        self.assertEqual(args, before)

    def test_history_sample_and_status_compatibility(self):
        for history, sample in [({}, []), (None, []), ([], []), ({i: {} for i in range(10)}, [str(i) for i in range(8)])]:
            self.assertEqual(build(**self.args(history=history))['history_prompt_ids_sample'], sample)
        for record, status in [({}, 'unknown'), (None, 'unknown'), ({'status': 'failed'}, 'failed'),
                               ({'status': {'status_str': 'running'}}, 'running'),
                               ({'status': {'completed': True}}, 'completed'),
                               ({'status': {'completed': False}}, 'not_completed'),
                               ({'status': {'status_str': '', 'completed': True}}, 'unknown')]:
            result = build(**self.args(prompt_history=record))
            self.assertEqual(result['target_status'], status)
            self.assertEqual(result['target_history_found'], bool(record))

    def test_slices_and_direct_aliases(self):
        messages = [[i, {}] for i in range(7)]
        for count in [0, 3, COMFY_OUTPUT_POLL_ATTEMPTS, COMFY_OUTPUT_POLL_ATTEMPTS + 3]:
            logs = [{'attempt': i} for i in range(count)]
            ids, nodes, keys = ['9'], ['9'], {'9': ['images']}
            result = build(**self.args(prompt_history={'status': {'messages': messages}}, attempt_logs=logs,
                                      save_image_node_ids=ids, extraction={'save_nodes_with_outputs': nodes, 'save_node_output_keys': keys}))
            self.assertEqual(result['attempts'], logs[-COMFY_OUTPUT_POLL_ATTEMPTS:])
            self.assertIsNot(result['attempts'], logs)
            if logs:
                self.assertIs(result['attempts'][-1], logs[-1])
            self.assertEqual(result['target_status_messages'], messages[:5])
            self.assertIsNot(result['target_status_messages'], messages)
            self.assertIs(result['target_status_messages'][0], messages[0])
            self.assertIs(result['save_image_node_ids'], ids)
            self.assertIs(result['save_image_nodes_with_outputs'], nodes)
            self.assertIs(result['save_image_node_output_keys'], keys)

    def test_workflow_shapes_classification_and_order(self):
        nodes = {'b': {'class_type': 'custom.PreviewImage'}, 9: {'type': 'custom.SaveImage'},
                 'a': {'class_type': 'SaveImage'}, 'ignored': None, 'other': {'class_type': 'NotSaveImage'}}
        for workflow in [nodes, {'nodes': nodes}]:
            result = build(**self.args(workflow_json=workflow))
            self.assertEqual(result['workflow_node_count'], 5)
            self.assertEqual(result['workflow_save_image_node_ids'], ['9', 'a'])
            self.assertEqual(result['workflow_output_node_ids'], ['b', '9', 'a'])
        for workflow in [{}, None, [], {'nodes': None}, {'nodes': []}]:
            result = build(**self.args(workflow_json=workflow))
            self.assertEqual(result['workflow_node_count'], 0)
            self.assertEqual(result['workflow_save_image_node_ids'], [])
            self.assertEqual(result['workflow_output_node_ids'], [])

    def test_outputs_extraction_truthiness_and_error_fallback(self):
        for outputs, expected in [({}, []), (None, []), ([], []), ({2: {}, 'a': {}}, [2, 'a'])]:
            self.assertEqual(build(**self.args(outputs=outputs))['target_outputs_keys'], expected)
        for value in [None, [], '', ['9'], 'yes', 1]:
            result = build(**self.args(extraction={'save_nodes_with_outputs': value}))
            self.assertEqual(result['save_image_outputs_found'], bool(value))
            self.assertIs(result['save_image_nodes_with_outputs'], value)
        for value in ['', None, False, 0, [], 'offline', 7, ['error']]:
            self.assertEqual(build(**self.args(last_history_fetch_error=value))['last_history_fetch_error'], value or 'none')

    def test_exact_formatted_message(self):
        diagnostics = dict(queued_prompt_id='p', attempt_count=3, target_history_found=[1], target_status='failed',
                           target_outputs_keys=['9'], workflow_save_image_node_ids=['9'],
                           save_image_nodes_with_outputs=[], save_image_node_output_keys={'9': ['images']},
                           last_history_fetch_error='offline', ignored='extra')
        self.assertEqual(format_diagnostics(diagnostics),
                         "No image was output by the workflow after polling Comfy history.\n"
                         "prompt_id: p\nattempts: 3\nhistory found: yes\nstatus: failed\n"
                         "outputs keys: ['9']\nSaveImage nodes in workflow: ['9']\n"
                         "SaveImage nodes with image outputs: []\nSaveImage output keys: {'9': ['images']}\n"
                         "last history fetch error: offline")

    def test_missing_and_none_formatting(self):
        expected = ('No image was output by the workflow after polling Comfy history.\n'
                    'prompt_id: None\nattempts: None\nhistory found: no\nstatus: None\n'
                    'outputs keys: None\nSaveImage nodes in workflow: None\n'
                    'SaveImage nodes with image outputs: None\nSaveImage output keys: None\n'
                    'last history fetch error: None')
        self.assertEqual(format_diagnostics({}), expected)
        self.assertEqual(format_diagnostics(dict.fromkeys(build(**self.args()))), expected)

    def test_malformed_inputs_and_custom_representation_propagate(self):
        for value in [None, [], 1]:
            with self.assertRaises(AttributeError):
                format_diagnostics(value)
        with self.assertRaises(AttributeError):
            build(**self.args(extraction=None))
        with self.assertRaises(TypeError):
            build(**self.args(attempt_logs=None))
        class Display:
            def __str__(self):
                return 'custom text'
            def __repr__(self):
                return 'custom repr'
        self.assertIn('prompt_id: custom text\n', format_diagnostics({'queued_prompt_id': Display()}))
        self.assertIn('outputs keys: [custom repr]\n', format_diagnostics({'target_outputs_keys': [Display()]}))
        class Broken:
            def __str__(self):
                raise ValueError('display failure')
        with self.assertRaisesRegex(ValueError, 'display failure'):
            format_diagnostics({'queued_prompt_id': Broken()})
