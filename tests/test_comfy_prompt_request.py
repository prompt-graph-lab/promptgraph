import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from core.comfy_prompt_request import prepare_prompt_request
from core.comfyui import generate_image_with_progress


class PromptRequestTests(unittest.TestCase):
    def test_request_bytes_seed_order_and_in_place_mutation(self):
        workflow = {'a': {'inputs': {'seed': True, 'noise_seed': 1.5,
                                    'text': '青'}},
                    'b': {'inputs': {'seed': 'keep'}}, 'other': None}
        inputs = workflow['a']['inputs']
        with patch('uuid.uuid4', return_value='client'), \
                patch('random.randint', side_effect=[11, 22]) as random_seed:
            address, client, request = prepare_prompt_request(workflow, 'https://host:8188/')
        self.assertEqual((address, client), ('host:8188', 'client'))
        self.assertEqual(request.full_url, 'http://host:8188/prompt')
        self.assertEqual(request.get_method(), 'POST')
        self.assertIs(inputs, workflow['a']['inputs'])
        self.assertEqual((inputs['seed'], inputs['noise_seed']), (11, 22))
        self.assertEqual(workflow['b']['inputs']['seed'], 'keep')
        self.assertEqual(random_seed.call_count, 2)
        random_seed.assert_called_with(0, 0xffffffffffffffff)
        self.assertEqual(request.data, json.dumps({'prompt': workflow, 'client_id': 'client'}).encode('utf-8'))

    def test_wrapped_workflow_is_not_unwrapped(self):
        workflow = {'nodes': {'a': {'inputs': {'seed': 1}}}}
        with patch('random.randint') as seed:
            prepare_prompt_request(workflow, 'host')
        seed.assert_not_called()
        self.assertEqual(workflow['nodes']['a']['inputs']['seed'], 1)

    def test_serialization_failure_keeps_prior_seed_mutation(self):
        workflow = {'a': {'inputs': {'seed': 1}}, 'invalid': object()}
        with patch('random.randint', return_value=42), self.assertRaises(TypeError):
            prepare_prompt_request(workflow, 'host')
        self.assertEqual(workflow['a']['inputs']['seed'], 42)

    def test_invalid_address_fails_before_uuid_or_mutation(self):
        with patch('uuid.uuid4') as uuid, self.assertRaises(AttributeError):
            prepare_prompt_request({}, None)
        uuid.assert_not_called()

    def test_generator_remains_lazy_and_connect_error_is_unchanged(self):
        workflow = {'a': {'inputs': {'seed': 1}}}
        with patch('random.randint', return_value=42), \
                patch('urllib.request.urlopen', side_effect=URLError('offline')) as send:
            generator = generate_image_with_progress(workflow, 'https://host/', 'unused', 'unused')
            self.assertEqual(workflow['a']['inputs']['seed'], 1)
            self.assertEqual(next(generator), {'type': 'status', 'text': 'Connecting to ComfyUI...', 'value': 0.0})
            self.assertEqual(workflow['a']['inputs']['seed'], 42)
            send.assert_not_called()
            with self.assertRaises(Exception) as caught:
                next(generator)
            self.assertEqual(str(caught.exception), 'Failed to connect to ComfyUI at host. Is it running? Error: <urlopen error offline>')

    def test_generator_preparation_error_precedes_first_status(self):
        with patch('urllib.request.urlopen') as send:
            generator = generate_image_with_progress({'bad': object()}, 'host', '', '')
            with self.assertRaises(TypeError):
                next(generator)
            send.assert_not_called()
