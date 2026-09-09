import builtins
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

from core import comfyui


class DownloadPhaseTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.output = os.path.join(self.root, 'images')
        self.order = []
        self.infos = [{'filename': 'one.png'}, {'filename': 'two.png'}]
        self.result = dict(history={}, prompt_history={}, outputs={},
                           extraction={'output_node_ids': ['9'], 'output_keys_by_node': {'9': ['images']},
                                       'image_like_fields': ['images'], 'save_nodes_with_outputs': ['9']},
                           image_infos=self.infos, attempt_logs=[{'attempt': 1}],
                           last_history_fetch_error=None, save_image_node_ids=['9'])
        for name, value in [('prepare_prompt_request', ('normalized:8188', 'client', 'request')),
                            ('submit_prompt_request', 'prompt'), ('connect_progress_socket', Mock()),
                            ('interpret_progress_message', (True, None))]:
            self.stack.enter_context(patch.object(comfyui, name, return_value=value))
        self.poll = self.stack.enter_context(patch.object(comfyui, '_poll_comfy_output_history', return_value=self.result))
        self.warning = self.stack.enter_context(patch.object(comfyui.logger, 'warning'))
        self.http = self.stack.enter_context(patch.object(comfyui.urllib.request, 'urlopen', side_effect=self.response))

    def response(self, url):
        self.order.append(('http', url))
        owner = self
        class Response:
            def __enter__(self):
                owner.order.append('enter')
                return self
            def read(self):
                owner.order.append('read')
                return b'\x00offline\xff'
            def __exit__(self, *args):
                owner.order.append('exit')
        return Response()

    def boundary(self):
        generator = comfyui.generate_image_with_progress({}, 'raw', self.output, 'prefix')
        self.addCleanup(generator.close)
        for _ in range(3):
            next(generator)
        self.poll.assert_not_called()
        self.assertFalse(os.path.exists(self.output))
        self.http.assert_not_called()
        return generator

    def urls(self):
        return [f'http://normalized:8188/view?filename={name}&subfolder=&type=output' for name in ['one.png', 'two.png']]

    def test_success_order_bytes_urls_paths_and_exact_done(self):
        generator = self.boundary()
        real_open = builtins.open
        real_unique = comfyui._unique_save_path
        real_makedirs = os.makedirs
        def opening(path, mode):
            self.order.append(('open', path, mode))
            return real_open(path, mode)
        def unique(directory, name):
            self.order.append(('unique', directory, name))
            return real_unique(directory, name)
        def mkdir(path, **kwargs):
            self.order.append(('mkdir', path, kwargs))
            return real_makedirs(path, **kwargs)
        with patch('builtins.open', side_effect=opening), patch.object(comfyui, '_unique_save_path', side_effect=unique), patch.object(os, 'makedirs', side_effect=mkdir):
            done = next(generator)
        paths = [os.path.join(self.output, 'prefix_' + name) for name in ['one.png', 'two.png']]
        self.assertEqual(done, dict(type='done', text='Completed!', value=1.0, path=paths[0], paths=paths,
                                   prompt_id='prompt', output_node_ids=['9'], output_keys_by_node={'9': ['images']},
                                   image_like_fields=['images'], comfy_output_diagnostics=dict(attempt_count=1,
                                   attempts=[{'attempt': 1}], save_image_node_ids=['9'], save_image_nodes_with_outputs=['9']),
                                   images=self.infos, attempted_view_urls=self.urls(), saved_paths=paths, download_errors=[]))
        self.assertIs(done['paths'], done['saved_paths'])
        self.assertIs(done['images'], self.infos)
        expected = [('mkdir', self.output, {'exist_ok': True})]
        for name, path, url in zip(['one.png', 'two.png'], paths, self.urls()):
            expected += [('unique', self.output, 'prefix_' + name), ('http', url), 'enter', 'read', ('open', path, 'wb'), 'exit']
            self.assertEqual(Path(path).read_bytes(), b'\x00offline\xff')
        self.assertEqual(self.order, expected)
        self.warning.assert_not_called()
        self.assertEqual(list(generator), [])

    def test_urlencode_explicit_values_and_original_filename_for_path(self):
        self.infos[:] = [{'filename': 'a b&+.png', 'subfolder': 'folder/x y', 'type': None}]
        with patch.object(comfyui, '_unique_save_path', return_value=os.path.join(self.output, 'safe.png')) as unique:
            done = next(self.boundary())
        url = 'http://normalized:8188/view?filename=a+b%26%2B.png&subfolder=folder%2Fx+y&type=None'
        self.http.assert_called_once_with(url)
        self.assertEqual(done['attempted_view_urls'], [url])
        unique.assert_called_once_with(self.output, 'prefix_a b&+.png')

    def test_pre_download_failures_propagate_without_warning(self):
        for stage in ['directory', 'record', 'missing_filename', 'urlencode', 'unique']:
            with self.subTest(stage=stage), ExitStack() as stack:
                self.poll.reset_mock()
                self.http.reset_mock()
                self.infos[:] = [{'filename': 'one.png'}]
                # Each subcase has its own not-yet-created directory.
                self.output = os.path.join(self.root, stage)
                error = RuntimeError(stage)
                expected = RuntimeError
                if stage == 'record':
                    self.infos[:] = [None]
                    expected = TypeError
                elif stage == 'missing_filename':
                    self.infos[:] = [{}]
                    expected = KeyError
                else:
                    target, attr = {'directory': (os, 'makedirs'), 'urlencode': (comfyui.urllib.parse, 'urlencode'), 'unique': (comfyui, '_unique_save_path')}[stage]
                    stack.enter_context(patch.object(target, attr, side_effect=error))
                with self.assertRaises(expected) as caught:
                    next(self.boundary())
                if expected is RuntimeError:
                    self.assertIs(caught.exception, error)
                self.http.assert_not_called()
                self.warning.assert_not_called()

    def test_caught_failures_warn_then_continue_to_partial_success(self):
        for stage in ['http', 'enter', 'read', 'open', 'write', 'exit']:
            with self.subTest(stage=stage), ExitStack() as stack:
                self.output = os.path.join(self.root, stage)
                self.poll.reset_mock()
                self.http.reset_mock()
                self.warning.reset_mock()
                original_response = self.response
                calls = []
                def response(url):
                    calls.append(url)
                    if len(calls) > 1:
                        return original_response(url)
                    if stage == 'http':
                        raise OSError('broken')
                    from unittest.mock import MagicMock
                    response = MagicMock()
                    response.__enter__.return_value = response
                    response.read.return_value = b'data'
                    if stage in ['enter', 'read', 'exit']:
                        getattr(response, {'enter': '__enter__', 'read': 'read', 'exit': '__exit__'}[stage]).side_effect = OSError('broken')
                    return response
                self.http.side_effect = response
                real_open = builtins.open
                def opening(path, mode):
                    if path.endswith('one.png') and stage == 'open':
                        raise OSError('broken')
                    if path.endswith('one.png') and stage == 'write':
                        from unittest.mock import MagicMock
                        handle = MagicMock()
                        handle.__enter__.return_value = handle
                        handle.write.side_effect = OSError('broken')
                        return handle
                    return real_open(path, mode)
                stack.enter_context(patch('builtins.open', side_effect=opening))
                generator = self.boundary()
                text = 'Failed to download image one.png: broken'
                self.assertEqual(next(generator), {'type': 'warning', 'text': text, 'value': .95})
                self.assertEqual(calls, self.urls()[:1])
                self.warning.assert_called_once_with(text)
                done = next(generator)
                path = os.path.join(self.output, 'prefix_two.png')
                self.assertEqual(done['path'], path)
                self.assertEqual(done['saved_paths'], [path])
                self.assertEqual(done['download_errors'], [text])
                self.assertEqual(done['attempted_view_urls'], self.urls())
                self.assertEqual(list(generator), [])

    def test_total_failure_warnings_then_exact_generic_exception(self):
        self.http.side_effect = OSError('offline')
        generator = self.boundary()
        errors = [f'Failed to download image {name}: offline' for name in ['one.png', 'two.png']]
        for text in errors:
            self.assertEqual(next(generator), {'type': 'warning', 'text': text, 'value': .95})
        with self.assertRaises(Exception) as caught:
            next(generator)
        self.assertIs(type(caught.exception), Exception)
        self.assertEqual(str(caught.exception),
                         "No ComfyUI image outputs could be downloaded. Prompt id: prompt. "
                         "Output node ids seen: ['9']. Output keys by node: {'9': ['images']}. "
                         "Image-like fields seen: ['images']. "
                         f"Attempted /view URLs: {self.urls()}. Attempted 2 image record(s). Download errors: {errors}")
        self.assertEqual(list(generator), [])
