import json
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from core import comfyui


class WebSocketSetupTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.socket = Mock()
        self.constructor = self.stack.enter_context(patch.object(comfyui.websocket, 'WebSocket', return_value=self.socket))
        self.prepare = self.stack.enter_context(patch.object(comfyui, 'prepare_prompt_request', return_value=('host:8188', 'client', 'request')))
        self.submit = self.stack.enter_context(patch.object(comfyui, 'submit_prompt_request', return_value='prompt'))
        self.clock = self.stack.enter_context(patch.object(comfyui.time, 'time', return_value=0))
        self.poll = self.stack.enter_context(patch.object(comfyui, '_poll_comfy_output_history'))
        self.generator = comfyui.generate_image_with_progress({}, 'host', '', '', timeout=3)
        self.addCleanup(self.generator.close)

    def queued(self):
        self.assertEqual(next(self.generator)['text'], 'Connecting to ComfyUI...')
        self.assertEqual(next(self.generator)['text'], 'Prompt queued. Waiting for execution...')
        self.constructor.assert_not_called()

    def test_lazy_setup_and_success_order(self):
        self.prepare.assert_not_called()
        self.submit.assert_not_called()
        self.constructor.assert_not_called()
        self.assertEqual(next(self.generator)['text'], 'Connecting to ComfyUI...')
        self.prepare.assert_called_once()
        self.submit.assert_not_called()
        self.assertEqual(next(self.generator)['text'], 'Prompt queued. Waiting for execution...')
        self.submit.assert_called_once_with('request', 'host:8188')
        self.constructor.assert_not_called()
        self.socket.recv.return_value = json.dumps({'type': 'execution_start'})
        self.assertEqual(next(self.generator)['text'], 'Execution started')
        self.assertEqual([call[0] for call in self.socket.mock_calls], ['connect', 'settimeout', 'recv'])
        self.socket.connect.assert_called_once_with('ws://host:8188/ws?clientId=client')
        self.socket.settimeout.assert_called_once_with(1.0)

    def test_constructor_failure_is_unwrapped(self):
        self.queued()
        error = RuntimeError('constructor')
        self.constructor.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            next(self.generator)
        self.assertIs(caught.exception, error)
        self.socket.close.assert_not_called()

    def test_connect_and_timeout_setup_failures_do_not_close(self):
        # Separate generators pin both setup stages without changing cleanup.
        for stage in ['connect', 'settimeout']:
            with self.subTest(stage=stage):
                socket = Mock()
                error = ValueError(stage)
                getattr(socket, stage).side_effect = error
                self.constructor.return_value = socket
                generator = comfyui.generate_image_with_progress({}, 'host', '', '')
                next(generator)
                next(generator)
                with self.assertRaises(Exception) as caught:
                    next(generator)
                self.assertIs(type(caught.exception), Exception)
                self.assertEqual(str(caught.exception), f'Failed to connect to ComfyUI WebSocket: {stage}')
                self.assertIs(caught.exception.__context__, error)
                socket.close.assert_not_called()
                if stage == 'connect':
                    socket.settimeout.assert_not_called()

    def test_completion_closes_before_fetch_status(self):
        for message in [{'type': 'execution_success', 'data': {'prompt_id': 'prompt'}},
                        {'type': 'executing', 'data': {'prompt_id': 'prompt', 'node': None}}]:
            with self.subTest(message=message):
                self.socket.reset_mock()
                self.socket.recv.return_value = json.dumps(message)
                generator = comfyui.generate_image_with_progress({}, 'host', '', '')
                next(generator)
                next(generator)
                self.assertEqual(next(generator)['text'], 'Execution done. Fetching image...')
                self.socket.close.assert_called_once_with()
                self.poll.assert_not_called()
                generator.close()
                self.socket.close.assert_called_once_with()

    def test_execution_timeout_closes_before_raising(self):
        self.queued()
        self.clock.side_effect = [0, 4]
        with self.assertRaisesRegex(Exception, r'^ComfyUI execution timeout \(3s exceeded\)$'):
            next(self.generator)
        self.socket.close.assert_called_once_with()
        self.socket.recv.assert_not_called()

    def test_receive_failure_wraps_without_close(self):
        self.queued()
        error = ValueError('receive')
        self.socket.recv.side_effect = error
        with self.assertRaises(Exception) as caught:
            next(self.generator)
        self.assertEqual(str(caught.exception), 'WebSocket error or execution failed: receive')
        self.assertIs(caught.exception.__context__, error)
        self.socket.close.assert_not_called()

    def test_execution_error_wraps_without_close(self):
        self.queued()
        self.socket.recv.return_value = json.dumps({'type': 'execution_error', 'data': {'node_id': '7', 'node_type': 'Sampler', 'exception_message': 'bad'}})
        with self.assertRaises(Exception) as caught:
            next(self.generator)
        self.assertEqual(str(caught.exception), 'WebSocket error or execution failed: ComfyUI Execution Error in node 7 (Sampler): bad')
        self.socket.close.assert_not_called()

    def test_receive_timeout_retries_until_execution_timeout(self):
        self.queued()
        self.clock.side_effect = [0, 0, 4]
        self.socket.recv.side_effect = comfyui.websocket.WebSocketTimeoutException()
        with self.assertRaisesRegex(Exception, 'ComfyUI execution timeout'):
            next(self.generator)
        self.socket.recv.assert_called_once()
        self.socket.close.assert_called_once()

    def test_early_close_before_setup_does_not_construct(self):
        self.queued()
        self.generator.close()
        self.constructor.assert_not_called()

    def test_early_close_during_execution_does_not_close_socket(self):
        self.queued()
        self.socket.recv.return_value = json.dumps({'type': 'execution_start'})
        next(self.generator)
        self.generator.close()
        self.socket.close.assert_not_called()

    def test_event_identity_suspension_and_injected_error_remain_inside_handler(self):
        self.queued()
        event = {'type': 'progress', 'text': 'sentinel', 'value': .5}
        with patch.object(comfyui, 'interpret_progress_message', return_value=(False, event)):
            self.assertIs(next(self.generator), event)
            self.socket.recv.assert_called_once()
            self.socket.close.assert_not_called()
            self.poll.assert_not_called()
            error = ValueError('injected at yield')
            with self.assertRaises(Exception) as caught:
                self.generator.throw(error)
        self.assertIs(type(caught.exception), Exception)
        self.assertEqual(str(caught.exception), 'WebSocket error or execution failed: injected at yield')
        self.assertIs(caught.exception.__context__, error)
        self.assertIsNone(caught.exception.__cause__)
        self.socket.recv.assert_called_once()
        self.socket.close.assert_not_called()
