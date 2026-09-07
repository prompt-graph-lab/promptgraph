import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from core.comfy_prompt_submission import submit_prompt_request
from core.comfyui import generate_image_with_progress


class PromptSubmissionTests(unittest.TestCase):
    def response(self, payload):
        context = MagicMock()
        context.__enter__.return_value.read.return_value = payload
        return context

    def test_success_exact_request_and_context_lifetime(self):
        events = []
        request = object()
        context = self.response(b'{"prompt_id": "id"}')
        context.__enter__.side_effect = lambda: events.append('enter') or context
        context.read.side_effect = lambda: events.append('read') or b'{"prompt_id": "id"}'
        context.__exit__.side_effect = lambda *args: events.append('exit') or False
        with patch('urllib.request.urlopen', return_value=context) as send:
            self.assertEqual(submit_prompt_request(request, 'host'), 'id')
        send.assert_called_once_with(request)
        self.assertEqual(events, ['enter', 'read', 'exit'])
        context.__exit__.assert_called_once_with(None, None, None)

    def test_falsey_and_missing_id_fail_after_context_exit(self):
        for payload in [{}, {'prompt_id': None}, {'prompt_id': ''}, {'prompt_id': 0}, {'prompt_id': False}, {'prompt_id': []}]:
            with self.subTest(payload=payload):
                context = self.response(json.dumps(payload).encode())
                with patch('urllib.request.urlopen', return_value=context), self.assertRaisesRegex(Exception, '^Failed to get prompt_id from ComfyUI\\.$'):
                    submit_prompt_request(object(), 'host')
                context.__exit__.assert_called_once_with(None, None, None)

    def test_truthy_id_is_returned_without_type_coercion(self):
        with patch('urllib.request.urlopen', return_value=self.response(b'{"prompt_id": [1]}')):
            self.assertEqual(submit_prompt_request(object(), 'host'), [1])

    def test_urlerror_translation_including_read_and_exit(self):
        for stage in ['open', 'read', 'exit']:
            with self.subTest(stage=stage):
                context = self.response(b'{"prompt_id": "id"}')
                error = URLError('offline')
                if stage == 'read':
                    context.__enter__.return_value.read.side_effect = error
                if stage == 'exit':
                    context.__exit__.side_effect = error
                with patch('urllib.request.urlopen', side_effect=error if stage == 'open' else None, return_value=context), self.assertRaises(Exception) as caught:
                    submit_prompt_request(object(), 'host')
                self.assertIs(type(caught.exception), Exception)
                self.assertEqual(str(caught.exception), 'Failed to connect to ComfyUI at host. Is it running? Error: <urlopen error offline>')
                self.assertIs(caught.exception.__context__, error)

    def test_decode_and_shape_errors_are_not_translated(self):
        for payload, error in [(b'{', json.JSONDecodeError), (b'[]', AttributeError)]:
            with self.subTest(payload=payload):
                context = self.response(payload)
                with patch('urllib.request.urlopen', return_value=context), self.assertRaises(error):
                    submit_prompt_request(object(), 'host')
                self.assertIs(context.__exit__.call_args.args[0], error)

    def test_exit_error_precedes_missing_id_validation(self):
        context = self.response(b'{}')
        error = RuntimeError('close failed')
        context.__exit__.side_effect = error
        with patch('urllib.request.urlopen', return_value=context), self.assertRaises(RuntimeError) as caught:
            submit_prompt_request(object(), 'host')
        self.assertIs(caught.exception, error)

    def test_generator_event_order_and_laziness(self):
        events = []
        request = object()
        context = self.response(b'{"prompt_id": "id"}')
        context.__enter__.return_value.read.side_effect = lambda: events.append('read') or b'{"prompt_id": "id"}'
        context.__exit__.side_effect = lambda *args: events.append('exit') or False
        with patch('core.comfyui.prepare_prompt_request', side_effect=lambda *args: events.append('prepare') or ('host', 'client', request)), \
                patch('urllib.request.urlopen', side_effect=lambda req: events.append(('submit', req)) or context), \
                patch('core.comfyui.websocket.WebSocket') as websocket:
            generator = generate_image_with_progress({}, 'host', '', '')
            self.assertEqual(events, [])
            self.assertEqual(next(generator), {'type': 'status', 'text': 'Connecting to ComfyUI...', 'value': 0.0})
            self.assertEqual(events, ['prepare'])
            self.assertEqual(next(generator), {'type': 'status', 'text': 'Prompt queued. Waiting for execution...', 'value': 0.0})
            self.assertEqual(events, ['prepare', ('submit', request), 'read', 'exit'])
            websocket.assert_not_called()
            generator.close()
