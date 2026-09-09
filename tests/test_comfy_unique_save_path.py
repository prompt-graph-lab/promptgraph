import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.comfyui import _unique_save_path


class UniqueSavePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_no_collision_creates_nothing_and_does_not_reserve(self):
        directory = self.root / 'not-created'
        expected = os.path.join(directory, 'image.png')
        self.assertEqual(_unique_save_path(directory, 'image.png'), expected)
        self.assertIs(type(_unique_save_path(directory, 'image.png')), str)
        self.assertFalse(directory.exists())
        # A second selection is identical: no reservation or directory creation.
        self.assertEqual(_unique_save_path(directory, 'image.png'), expected)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_single_collision_and_extension_conventions(self):
        for name, selected in [('image.png', 'image_1.png'), ('image', 'image_1'),
                               ('image.tar.gz', 'image.tar_1.gz'), ('.hidden', '.hidden_1'),
                               ('.hidden.png', '.hidden_1.png')]:
            with self.subTest(name=name):
                (self.root / name).touch()
                self.assertEqual(_unique_save_path(self.root, name), str(self.root / selected))
                self.assertFalse((self.root / selected).exists())

    def test_sequential_collisions_stop_at_first_gap(self):
        for name in ['image.png', 'image_1.png', 'image_2.png', 'image_4.png']:
            (self.root / name).touch()
        self.assertEqual(_unique_save_path(self.root, 'image.png'), str(self.root / 'image_3.png'))
        (self.root / 'image_3.png').touch()
        self.assertEqual(_unique_save_path(self.root, 'image.png'), str(self.root / 'image_5.png'))

    def test_directory_is_also_a_collision(self):
        (self.root / 'image.png').mkdir()
        self.assertEqual(_unique_save_path(self.root, 'image.png'), str(self.root / 'image_1.png'))

    def test_basename_uses_native_path_components(self):
        for name in [os.path.join('nested', 'image.png'), str(self.root / 'elsewhere' / 'image.png')]:
            with self.subTest(name=name):
                self.assertEqual(_unique_save_path(self.root, name), str(self.root / 'image.png'))
        # Trailing native separator produces an empty basename, not the fallback.
        name = 'nested' + os.sep
        candidate = os.path.join(str(self.root), '')
        stem, ext = os.path.splitext(candidate)
        self.assertEqual(_unique_save_path(self.root, name), f'{stem}_1{ext}')

    def test_falsey_name_fallback_and_truthy_invalid_type(self):
        for name in [None, '', False, 0]:
            with self.subTest(name=name):
                self.assertEqual(_unique_save_path(self.root, name), str(self.root / 'comfy_output.png'))
        (self.root / 'comfy_output.png').touch()
        self.assertEqual(_unique_save_path(self.root, None), str(self.root / 'comfy_output_1.png'))
        with self.assertRaises(TypeError):
            _unique_save_path(self.root, 1)

    def test_path_operation_exceptions_propagate_identically(self):
        for operation in ['basename', 'join', 'splitext', 'exists']:
            with self.subTest(operation=operation):
                error = RuntimeError(operation)
                with patch.object(os.path, operation, side_effect=error):
                    with self.assertRaises(RuntimeError) as caught:
                        _unique_save_path(str(self.root), 'image.png')
                self.assertIs(caught.exception, error)

    def test_exists_checks_initial_then_numbered_paths_in_order(self):
        initial = str(self.root / 'image.png')
        first = str(self.root / 'image_1.png')
        second = str(self.root / 'image_2.png')
        with patch.object(os.path, 'exists', side_effect=[True, True, False]) as exists:
            self.assertEqual(_unique_save_path(self.root, 'image.png'), second)
        self.assertEqual([c.args for c in exists.call_args_list], [(initial,), (first,), (second,)])
