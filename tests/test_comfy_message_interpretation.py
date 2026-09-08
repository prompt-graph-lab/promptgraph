import json
import unittest
from unittest.mock import Mock, patch

from core import comfyui
from core.comfy_message_interpretation import interpret_progress_message


class MessageInterpretationTests(unittest.TestCase):
    def test_direct_result_contract_and_read_only_non_string(self):
        payload = {'type': 'progress', 'data': {'value': 1}}
        self.assertEqual(interpret_progress_message(payload, 'p'), (False, None))
        self.assertEqual(payload, {'type': 'progress', 'data': {'value': 1}})
        self.assertEqual(interpret_progress_message('{"type":"execution_success","data":{"prompt_id":"p"}}', 'p'), (True, None))
        self.assertEqual(interpret_progress_message('{"type":"execution_start"}', 'p'),
                         (False, {'type': 'status', 'text': 'Execution started', 'value': 0.05}))
        with self.assertRaises(json.JSONDecodeError):
            interpret_progress_message('{', 'p')

    def observe(self, payload):
        socket = Mock()
        socket.recv.side_effect = [payload, json.dumps({'type': 'execution_success', 'data': {'prompt_id': 'p'}})]
        with patch.object(comfyui, 'prepare_prompt_request', return_value=('host', 'client', object())), \
                patch.object(comfyui, 'submit_prompt_request', return_value='p'), \
                patch.object(comfyui, 'connect_progress_socket', return_value=socket), \
                patch.object(comfyui.time, 'time', return_value=0):
            generator = comfyui.generate_image_with_progress({}, '', '', '')
            next(generator)
            next(generator)
            events = []
            try:
                while True:
                    event = next(generator)
                    events.append(event)
                    if event['text'] == 'Execution done. Fetching image...':
                        break
            except Exception as error:
                socket.close.assert_not_called()
                return events, error, socket.recv.call_count
            finally:
                generator.close()
            socket.close.assert_called_once_with()
            return events[:-1], None, socket.recv.call_count

    def test_ignored_payloads(self):
        payloads = [b'binary', None, 3, {}, '{}', '{"data": null}',
                    '{"type": "unknown", "data": null}',
                    '{"type": "executing", "data": {"prompt_id": "other"}}',
                    '{"type": "executing", "data": {"prompt_id": "p", "node": 0}}',
                    '{"type": "executing", "data": {"prompt_id": "p", "node": ""}}',
                    '{"type": "execution_success", "data": {"prompt_id": "other"}}']
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.observe(payload), ([], None, 2))

    def test_completion_id_and_node_semantics(self):
        for message in [{'type': 'executing', 'data': {'prompt_id': 'p'}},
                        {'type': 'executing', 'data': {'prompt_id': 'p', 'node': None}},
                        {'type': 'execution_success', 'data': {'prompt_id': 'p'}}]:
            with self.subTest(message=message):
                self.assertEqual(self.observe(json.dumps(message)), ([], None, 1))

    def test_start_ignores_data_shape(self):
        events, error, count = self.observe('{"type":"execution_start","data":null}')
        self.assertEqual(events, [{'type': 'status', 'text': 'Execution started', 'value': 0.05}])
        self.assertIsNone(error)
        self.assertEqual(count, 2)

    def test_progress_defaults_scaling_and_no_clamping(self):
        for data, value, text in [({}, .1, '0/1'), ({'value': 1, 'max': 2}, .5, '1/2'),
                                  ({'value': 1}, .9, '1/1'), ({'value': 2, 'max': 1}, 1.7, '2/1'),
                                  ({'value': -1, 'max': 1}, -.7, '-1/1')]:
            with self.subTest(data=data):
                events, error, _ = self.observe(json.dumps({'type': 'progress', 'data': data}))
                self.assertIsNone(error)
                self.assertEqual(events[0]['text'], f'Sampling... {text}')
                self.assertAlmostEqual(events[0]['value'], value)
                self.assertEqual(events[0]['type'], 'progress')
        for maximum in [0, -1]:
            self.assertEqual(self.observe(json.dumps({'type': 'progress', 'data': {'value': 'invalid', 'max': maximum}})), ([], None, 2))

    def test_malformed_payload_errors_remain_wrapped(self):
        for payload, cause in [('{', json.JSONDecodeError), ('[]', AttributeError),
                               ('null', AttributeError), ('42', AttributeError),
                               ('{"type":"progress","data":null}', AttributeError),
                               ('{"type":"progress","data":{"max":"1"}}', TypeError)]:
            with self.subTest(payload=payload):
                events, error, count = self.observe(payload)
                self.assertEqual(events, [])
                self.assertIs(type(error), Exception)
                self.assertIsInstance(error.__context__, cause)
                self.assertEqual(str(error), f'WebSocket error or execution failed: {error.__context__}')
                self.assertEqual(count, 1)

    def test_execution_error_text_and_defaults(self):
        for data, suffix in [({}, 'node  (): Unknown error'),
                             ({'node_id': '7', 'node_type': 'Sampler', 'exception_message': 'bad'}, 'node 7 (Sampler): bad')]:
            _, error, count = self.observe(json.dumps({'type': 'execution_error', 'data': data}))
            self.assertEqual(str(error), f'WebSocket error or execution failed: ComfyUI Execution Error in {suffix}')
            self.assertEqual(count, 1)
