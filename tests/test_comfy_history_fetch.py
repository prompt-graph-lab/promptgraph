import json
import unittest
from unittest.mock import MagicMock, patch

from core import comfyui
from core.comfy_history_fetch import fetch_comfy_history


class HistoryFetchTests(unittest.TestCase):
    def test_order_raw_url_and_decoded_identity(self):
        events = []
        raw = b'{"history": []}'
        decoded = {'history': []}
        response = MagicMock()
        response.__enter__.side_effect = lambda: events.append('enter') or response
        response.read.side_effect = lambda: events.append('read') or raw
        response.__exit__.side_effect = lambda *args: events.append('exit')
        def http(url):
            events.append('open')
            return response
        def decode(value):
            self.assertIs(value, raw)
            events.append('decode')
            return decoded
        with patch('urllib.request.urlopen', side_effect=http) as request, patch('json.loads', side_effect=decode):
            self.assertIs(fetch_comfy_history('http://host/', 'p /?x'), decoded)
            events.append('return')
        request.assert_called_once_with('http://http://host//history/p /?x')
        self.assertEqual(events, ['open', 'enter', 'read', 'decode', 'exit', 'return'])
        self.assertIs(comfyui._fetch_comfy_history, fetch_comfy_history)

    def test_real_json_accepts_non_object_results(self):
        for raw, expected in [(b'{"p": {}}', {'p': {}}), (b'[1]', [1]), (b'null', None), (b'false', False)]:
            with self.subTest(raw=raw):
                response = MagicMock()
                response.__enter__.return_value = response
                response.read.return_value = raw
                with patch('urllib.request.urlopen', return_value=response):
                    self.assertEqual(fetch_comfy_history('host', 'p'), expected)
        response.read.return_value = b'invalid'
        with patch('urllib.request.urlopen', return_value=response):
            with self.assertRaises(json.JSONDecodeError):
                fetch_comfy_history('host', 'p')

    def test_exceptions_propagate_unchanged_including_exit(self):
        for stage in ['open', 'enter', 'read', 'decode', 'exit']:
            with self.subTest(stage=stage):
                error = RuntimeError(stage)
                response = MagicMock()
                response.__enter__.return_value = response
                response.__exit__.return_value = False
                with patch('urllib.request.urlopen', return_value=response) as http, patch('json.loads', return_value={}) as decode:
                    operation = {'open': http, 'enter': response.__enter__, 'read': response.read,
                                 'decode': decode, 'exit': response.__exit__}[stage]
                    operation.side_effect = error
                    with self.assertRaises(RuntimeError) as caught:
                        fetch_comfy_history('host', 'p')
                self.assertIs(caught.exception, error)
                if stage == 'exit':
                    decode.assert_called_once()
