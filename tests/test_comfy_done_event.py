import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from core import comfyui


class DoneEventTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.written = []
        self.result = dict(history={}, prompt_history={}, outputs={}, extraction={},
                           image_infos=[{'filename': 'image.png'}], attempt_logs=[],
                           last_history_fetch_error=None, save_image_node_ids=[])
        for name, value in [('prepare_prompt_request', ('offline', 'client', 'request')),
                            ('submit_prompt_request', 'prompt'), ('connect_progress_socket', Mock()),
                            ('interpret_progress_message', (True, None)),
                            ('_poll_comfy_output_history', self.result)]:
            self.stack.enter_context(patch.object(comfyui, name, return_value=value))
        self.stack.enter_context(patch.object(comfyui, 'download_image_to_path', side_effect=self.download))
        self.warning = self.stack.enter_context(patch.object(comfyui.logger, 'warning'))

    def download(self, url, path):
        Path(path).write_bytes(b'offline bytes')
        self.written.append(Path(path))

    def boundary(self):
        generator = comfyui.generate_image_with_progress({}, 'offline', str(self.root), 'prefix')
        self.addCleanup(generator.close)
        for _ in range(3):
            self.assertEqual(next(generator)['type'], 'status')
        return generator

    def test_missing_defaults(self):
        done = next(self.boundary())
        self.assertEqual([done[k] for k in ['output_node_ids', 'output_keys_by_node', 'image_like_fields']], [[], {}, []])
        self.assertEqual(done['comfy_output_diagnostics']['save_image_nodes_with_outputs'], [])
        self.assertEqual(done['comfy_output_diagnostics']['attempt_count'], 0)

    def test_present_falsey_values_are_not_defaulted(self):
        keys = ['output_node_ids', 'output_keys_by_node', 'image_like_fields', 'save_nodes_with_outputs']
        for value in [None, False, 0, [], {}, '']:
            with self.subTest(value=value):
                self.result['extraction'] = dict.fromkeys(keys, value)
                done = next(self.boundary())
                for key in keys[:3]:
                    self.assertEqual(done[key], value)
                self.assertEqual(done['comfy_output_diagnostics']['save_image_nodes_with_outputs'], value)

    def test_containers_pass_through_and_attempt_count_is_length(self):
        extraction = dict(output_node_ids=['9'], output_keys_by_node={'9': ['images']},
                          image_like_fields=['images'], save_nodes_with_outputs=['9'])
        self.result['extraction'] = extraction
        self.result['attempt_logs'] = ({'attempt': 7}, {'attempt': 99})
        self.result['save_image_node_ids'] = ['9']
        done = next(self.boundary())
        for key in ['output_node_ids', 'output_keys_by_node', 'image_like_fields']:
            self.assertIs(done[key], extraction[key])
        diagnostics = done['comfy_output_diagnostics']
        self.assertEqual(diagnostics['attempt_count'], 2)
        self.assertIs(diagnostics['attempts'], self.result['attempt_logs'])
        self.assertIs(diagnostics['save_image_node_ids'], self.result['save_image_node_ids'])
        self.assertIs(diagnostics['save_image_nodes_with_outputs'], extraction['save_nodes_with_outputs'])

    def test_assembly_failures_follow_write_and_bypass_download_warning(self):
        for malformed_logs in [True, False]:
            with self.subTest(malformed_logs=malformed_logs):
                calls = []
                error = RuntimeError('final metadata')
                def get(key, default):
                    calls.append(key)
                    if key == 'save_nodes_with_outputs':
                        self.assertEqual(self.written[-1].read_bytes(), b'offline bytes')
                        raise error
                    return default
                self.result['extraction'] = Mock(get=Mock(side_effect=get))
                self.result['attempt_logs'] = None if malformed_logs else []
                generator = self.boundary()
                before = len(self.written)
                with self.assertRaises(TypeError if malformed_logs else RuntimeError) as caught:
                    next(generator)
                if not malformed_logs:
                    self.assertIs(caught.exception, error)
                self.assertEqual(len(self.written), before + 1)
                self.assertEqual(self.written[-1].read_bytes(), b'offline bytes')
                expected = ['output_node_ids', 'output_keys_by_node', 'image_like_fields']
                self.assertEqual(calls, expected if malformed_logs else expected + ['save_nodes_with_outputs'])
                self.warning.assert_not_called()
                self.assertEqual(list(generator), [])
