import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.comfy_image_download import download_image_to_path


class ImageDownloadTests(unittest.TestCase):
    def test_real_bytes_and_context_order_before_return(self):
        events = []
        data = b'\x00offline\xff'
        real_open = open
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'image.bin'
            class Response:
                def __enter__(self):
                    events.append('response enter')
                    return self
                def read(self):
                    events.append('read')
                    return data
                def __exit__(self, *args):
                    events.append('response exit')
            class File:
                def __enter__(self):
                    self.file = real_open(path, 'wb')
                    events.append('file enter')
                    return self
                def write(self, value):
                    events.append('write')
                    self.file.write(value)
                def __exit__(self, *args):
                    self.file.close()
                    events.append('file exit')
            def http(url):
                events.append('http')
                return Response()
            def local(target, mode):
                self.assertIs(target, path)
                self.assertEqual(mode, 'wb')
                events.append('open')
                return File()
            with patch('urllib.request.urlopen', side_effect=http) as request, patch('builtins.open', side_effect=local):
                self.assertIsNone(download_image_to_path('unchanged URL', path))
                events.append('return')
            request.assert_called_once_with('unchanged URL')
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(events, ['http', 'response enter', 'read', 'open', 'file enter', 'write', 'file exit', 'response exit', 'return'])

    def test_exceptions_propagate_identically(self):
        for stage in ['http', 'response enter', 'read', 'open', 'file enter', 'write', 'file exit', 'response exit']:
            with self.subTest(stage=stage):
                error = OSError(stage)
                response = MagicMock()
                response.__enter__.return_value = response
                response.read.return_value = b'data'
                response.__exit__.return_value = False
                file = MagicMock()
                file.__enter__.return_value = file
                file.__exit__.return_value = False
                with patch('urllib.request.urlopen', return_value=response) as http, patch('builtins.open', return_value=file) as local:
                    operation = {'http': http, 'response enter': response.__enter__, 'read': response.read,
                                 'open': local, 'file enter': file.__enter__, 'write': file.write,
                                 'file exit': file.__exit__, 'response exit': response.__exit__}[stage]
                    operation.side_effect = error
                    with self.assertRaises(OSError) as caught:
                        download_image_to_path('offline', 'unused')
                self.assertIs(caught.exception, error)
