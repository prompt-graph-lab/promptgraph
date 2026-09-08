import unittest
from contextlib import ExitStack
from unittest.mock import Mock, call, patch

from core import comfyui

REAL_BUILD = comfyui._build_output_diagnostics
REAL_FORMAT = comfyui._format_output_diagnostics


class MissingOutputIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.workflow = {'original': {}}
        self.result = dict(history={}, prompt_history={}, outputs={}, extraction={}, image_infos=[],
                           attempt_logs=[{'attempt': 1}], last_history_fetch_error='offline', save_image_node_ids=['9'])
        self.order = []
        def patched(name, **kwargs):
            return self.stack.enter_context(patch.object(comfyui, name, **kwargs))
        patched('prepare_prompt_request', return_value=('host', 'client', 'request'))
        patched('submit_prompt_request', return_value='p')
        patched('connect_progress_socket', return_value=Mock())
        patched('interpret_progress_message', return_value=(True, None))
        self.poll = patched('_poll_comfy_output_history', side_effect=lambda *args: self.order.append('poll') or self.result)
        self.diagnostics = {'evidence': 'same object'}
        self.build = patched('_build_output_diagnostics', side_effect=lambda **kwargs: self.order.append('build') or self.diagnostics)
        self.warning = self.stack.enter_context(patch.object(comfyui.logger, 'warning', side_effect=lambda *args: self.order.append('warning')))
        self.format = patched('_format_output_diagnostics', side_effect=lambda obj: self.order.append('format') or 'exact\nmessage')
        self.later = [self.stack.enter_context(patch.object(comfyui.os, 'makedirs')),
                      self.stack.enter_context(patch.object(comfyui.urllib.parse, 'urlencode')),
                      patched('_unique_save_path'),
                      self.stack.enter_context(patch.object(comfyui.urllib.request, 'urlopen')),
                      self.stack.enter_context(patch('builtins.open'))]

    def boundary(self):
        generator = comfyui.generate_image_with_progress(self.workflow, 'input-host', 'output', 'prefix')
        self.addCleanup(generator.close)
        self.assertEqual(next(generator)['text'], 'Connecting to ComfyUI...')
        self.assertEqual(next(generator)['text'], 'Prompt queued. Waiting for execution...')
        self.assertEqual(next(generator), {'type': 'status', 'text': 'Execution done. Fetching image...', 'value': .95})
        self.poll.assert_not_called()
        return generator

    def test_missing_output_order_arguments_alias_and_short_circuit(self):
        generator = self.boundary()
        with self.assertRaises(comfyui.ComfyOutputError) as caught:
            next(generator)
        self.assertEqual(self.order, ['poll', 'build', 'warning', 'format'])
        self.poll.assert_called_once_with('host', 'p', self.workflow)
        self.assertIs(self.poll.call_args.args[2], self.workflow)
        expected = dict(prompt_id='p', workflow_json=self.workflow, attempt_count=1)
        expected.update({key: self.result[key] for key in ['history', 'prompt_history', 'outputs', 'save_image_node_ids', 'extraction', 'attempt_logs', 'last_history_fetch_error']})
        self.build.assert_called_once_with(**expected)
        for key, value in expected.items():
            if key not in ['prompt_id', 'attempt_count']:
                self.assertIs(self.build.call_args.kwargs[key], value)
        self.warning.assert_called_once_with('Comfy output missing after polling: %s', self.diagnostics)
        self.format.assert_called_once_with(self.diagnostics)
        self.assertEqual(caught.exception.args, ('exact\nmessage',))
        self.assertIs(caught.exception.diagnostics, self.diagnostics)
        for effect in self.later:
            effect.assert_not_called()
        with self.assertRaises(StopIteration):
            next(generator)

    def test_required_result_keys_and_read_order(self):
        keys = ['history', 'prompt_history', 'outputs', 'extraction', 'image_infos', 'attempt_logs', 'last_history_fetch_error', 'save_image_node_ids']
        for key in keys:
            with self.subTest(key=key):
                saved = self.result.pop(key)
                self.poll.reset_mock()
                with self.assertRaises(KeyError) as caught:
                    next(self.boundary())
                self.assertEqual(caught.exception.args, (key,))
                self.result[key] = saved
        self.build.assert_not_called()

    def test_real_diagnostic_helpers_integrate_with_error(self):
        self.build.side_effect = REAL_BUILD
        self.format.side_effect = REAL_FORMAT
        with self.assertRaises(comfyui.ComfyOutputError) as caught:
            next(self.boundary())
        diagnostics = self.warning.call_args.args[1]
        self.assertIs(caught.exception.diagnostics, diagnostics)
        self.assertEqual(caught.exception.args, (REAL_FORMAT(diagnostics),))
        self.assertEqual(diagnostics['attempt_count'], 1)
        self.assertEqual(diagnostics['last_history_fetch_error'], 'offline')

    def test_extraction_metadata_read_before_branch(self):
        extraction = Mock()
        extraction.get.side_effect = [[], {}, []]
        self.result['extraction'] = extraction
        with self.assertRaises(comfyui.ComfyOutputError):
            next(self.boundary())
        self.assertEqual(extraction.get.call_args_list, [call('output_node_ids', []), call('output_keys_by_node', {}), call('image_like_fields', [])])

    def test_malformed_extraction_and_attempt_logs_propagate(self):
        for key, error in [('extraction', AttributeError), ('attempt_logs', TypeError)]:
            with self.subTest(key=key):
                saved = self.result[key]
                self.result[key] = None
                self.poll.reset_mock()
                with self.assertRaises(error):
                    next(self.boundary())
                self.result[key] = saved
        self.build.assert_not_called()

    def test_falsey_image_infos_and_diagnostics(self):
        for value in [None, [], (), '', 0, False]:
            with self.subTest(value=value):
                self.result['image_infos'] = value
                self.poll.reset_mock()
                with self.assertRaises(comfyui.ComfyOutputError):
                    next(self.boundary())
        self.diagnostics = {}
        self.poll.reset_mock()
        with self.assertRaises(comfyui.ComfyOutputError) as caught:
            next(self.boundary())
        self.assertEqual(caught.exception.diagnostics, {})
        self.assertIsNot(caught.exception.diagnostics, self.diagnostics)

    def test_truthy_image_infos_proceed_only_to_download_phase(self):
        for value in [[{'filename': 'x.png'}], 'unusual', 1]:
            with self.subTest(value=value):
                self.result['image_infos'] = value
                sentinel = RuntimeError('download phase reached')
                self.later[0].side_effect = sentinel
                self.poll.reset_mock()
                with self.assertRaises(RuntimeError) as caught:
                    next(self.boundary())
                self.assertIs(caught.exception, sentinel)
        self.build.assert_not_called()
        self.warning.assert_not_called()
        self.format.assert_not_called()

    def test_poll_builder_logger_formatter_exceptions_propagate(self):
        for name in ['poll', 'build', 'warning', 'format']:
            with self.subTest(name=name):
                target = getattr(self, name)
                original = target.side_effect
                error = ValueError(name)
                target.side_effect = error
                self.poll.reset_mock()
                with self.assertRaises(ValueError) as caught:
                    next(self.boundary())
                self.assertIs(caught.exception, error)
                target.side_effect = original
        for effect in self.later:
            effect.assert_not_called()
