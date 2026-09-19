import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

from core import project_save_as_safety as safety

normalize = safety.normalize_project_save_as_path
inspect = safety.inspect_project_save_as_destination
build = safety.build_project_save_as_pending_overwrite
fresh = safety.project_save_as_confirmation_is_fresh


class SaveAsSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'target.json'
        self.source = self.root / 'source.json'
        self.project = object()

    def pending(self):
        return build(inspect(self.target), self.source, self.project)

    def check(self, pending):
        return fresh(pending, self.target, self.source, self.project)

    def test_normalization(self):
        for value in ('', '  ', '\x00', b'file', None, 123):
            with self.subTest(value=value):
                self.assertEqual('', normalize(value))
        self.assertEqual(str(self.target), normalize(self.target))
        self.assertEqual(str(self.target), normalize('  ' + str(self.target) + '  '))
        self.assertEqual(os.path.abspath('MixedCase.json'), normalize('MixedCase.json'))
        self.assertEqual(os.path.abspath(os.path.expanduser('~/MixedCase.json')), normalize('~/MixedCase.json'))
        for error in (TypeError, ValueError):
            with patch.object(safety.os, 'fspath', side_effect=error):
                self.assertEqual('', normalize('x'))
        with patch.object(safety.os, 'fspath', side_effect=OSError):
            with self.assertRaises(OSError):
                normalize('x')
        for error in (OSError, TypeError, ValueError):
            with patch.object(safety.os.path, 'expanduser', side_effect=error):
                self.assertEqual('', normalize('x'))
        with patch.object(safety.os.path, 'expanduser', return_value='expanded') as expand, patch.object(safety.os.path, 'abspath', return_value='Absolute') as absolute:
            self.assertEqual('Absolute', normalize(' ~/x '))
            expand.assert_called_once_with('~/x')
            absolute.assert_called_once_with('expanded')

    def test_missing_directory_and_invalid_parent(self):
        expected = dict(normalized_path=str(self.target), occupied=False, kind='missing', size=None, mtime_ns=None, device=None, inode=None, sha256='')
        self.assertEqual(expected, inspect(self.target))
        self.assertFalse(self.target.exists())
        for path in ('', '\x00', self.root / 'absent' / 'file'):
            with self.assertRaises(ValueError):
                inspect(path)
        self.target.mkdir()
        expected.update(occupied=True, kind='directory')
        self.assertEqual(expected, inspect(self.target))

    def test_regular_file_complete_hash_and_no_mutation(self):
        data = b'a' * (1024 * 1024 + 7)
        self.target.write_bytes(data)
        before = self.target.stat()
        snapshot = inspect(self.target)
        self.assertEqual(dict(normalized_path=str(self.target), occupied=True, kind='file', size=len(data), mtime_ns=before.st_mtime_ns, device=before.st_dev, inode=before.st_ino, sha256=hashlib.sha256(data).hexdigest()), snapshot)
        self.assertTrue(self.check(self.pending())[0])
        self.assertEqual(data, self.target.read_bytes())
        self.assertEqual(before.st_mtime_ns, self.target.stat().st_mtime_ns)
        self.assertEqual([self.target], list(self.root.iterdir()))

    def test_symlink_and_broken_symlink(self):
        backing = self.root / 'backing'
        backing.write_bytes(b'original')
        try:
            self.target.symlink_to(backing)
        except OSError as error:
            self.skipTest(f'Symlink creation unavailable: {error}')
        for broken in (False, True):
            if broken:
                backing.unlink()
            snapshot = inspect(self.target)
            self.assertEqual('unsupported', snapshot['kind'])
            self.assertTrue(snapshot['occupied'])
            self.assertFalse(self.check(self.pending())[0])
            self.assertTrue(self.target.is_symlink())

    def test_symlink_classification_does_not_follow_or_open(self):
        # Exercise both link states even on Windows without symlink privileges.
        for destination_exists in (True, False):
            with patch.object(safety.os.path, 'lexists', return_value=True), patch.object(safety.os.path, 'isdir', return_value=True), patch.object(safety.os.path, 'islink', return_value=True), patch.object(safety.os.path, 'exists', return_value=destination_exists), patch('builtins.open') as opened:
                snapshot = inspect(self.target)
                self.assertEqual('unsupported', snapshot['kind'])
                self.assertTrue(snapshot['occupied'])
                self.assertIsNone(snapshot['inode'])
                opened.assert_not_called()

    def test_unsupported_entry(self):
        with patch.object(safety.os.path, 'lexists', return_value=True), patch.object(safety.os.path, 'islink', return_value=False), patch.object(safety.os.path, 'isdir', side_effect=[True, False]), patch.object(safety.os.path, 'isfile', return_value=False), patch('builtins.open') as opened:
            self.assertEqual('unsupported', inspect(self.target)['kind'])
            opened.assert_not_called()

    def test_pending_deepcopy_and_same_path(self):
        self.target.write_bytes(b'abc')
        snapshot = inspect(self.target)
        snapshot['extra'] = {'nested': []}
        pending = build(snapshot, self.target, self.project)
        self.assertEqual({'target_path', 'target_snapshot', 'source_project_path', 'source_project_object_id'}, set(pending))
        snapshot['extra']['nested'].append(1)
        self.assertEqual([], pending['target_snapshot']['extra']['nested'])
        pending = build(inspect(self.target), self.target, self.project)
        self.assertEqual(id(self.project), pending['source_project_object_id'])
        self.assertTrue(fresh(pending, self.target, self.target, self.project)[0])
        # Empty source normalization is legacy-compatible when both sides agree.
        pending = build(inspect(self.target), '', self.project)
        self.assertTrue(fresh(pending, self.target, '', self.project)[0])

    def test_pending_construction_order(self):
        events = []
        class Snapshot(dict):
            def get(self, key):
                events.append('target')
                return 'target'
            def __deepcopy__(self, memo):
                events.append('copy')
                return {'copied': True}
        with patch.object(safety, 'normalize_project_save_as_path', side_effect=lambda path: events.append('source') or 'source'), patch.object(safety, 'id', create=True, side_effect=lambda obj: events.append('identity') or 42):
            pending = build(Snapshot(), self.source, self.project)
        self.assertEqual(['target', 'copy', 'source', 'identity'], events)
        self.assertEqual(42, pending['source_project_object_id'])

    def test_freshness_uses_normcase_for_both_paths(self):
        self.target.write_bytes(b'abc')
        pending = self.pending()
        pending['target_path'] = str(self.target).upper()
        pending['source_project_path'] = str(self.source).upper()
        with patch.object(safety.os.path, 'normcase', side_effect=lambda value: value.lower()) as normcase:
            self.assertTrue(self.check(pending)[0])
            self.assertEqual(4, normcase.call_count)

    def test_context_rejections_precede_inspection(self):
        pending = self.pending()
        cases = [(None, self.target, self.source, self.project), ({'target_snapshot': None}, self.target, self.source, self.project), (pending, '', self.source, self.project), (pending, self.root / 'other', self.source, self.project), (pending, self.target, self.root / 'other', self.project), (pending, self.target, self.source, object())]
        with patch.object(safety, 'inspect_project_save_as_destination') as inspected:
            for args in cases:
                self.assertEqual((False, {}), fresh(*args))
            inspected.assert_not_called()

    def test_snapshot_changes_and_exact_equality(self):
        self.target.write_bytes(b'abc')
        pending = self.pending()
        for key in ('size', 'mtime_ns', 'device', 'inode', 'sha256'):
            changed = dict(pending['target_snapshot'])
            changed[key] = 'changed'
            with patch.object(safety, 'inspect_project_save_as_destination', return_value=changed):
                self.assertEqual((False, changed), self.check(pending))
        changed = dict(pending['target_snapshot'], extra=True)
        with patch.object(safety, 'inspect_project_save_as_destination', return_value=changed):
            self.assertEqual((False, changed), self.check(pending))
        self.target.write_bytes(b'xyz')
        stamp = pending['target_snapshot']['mtime_ns']
        os.utime(self.target, ns=(stamp, stamp))
        self.assertFalse(self.check(pending)[0])
        self.target.unlink()
        self.assertEqual((False, inspect(self.target)), self.check(pending))
        pending = self.pending()
        self.assertEqual((False, inspect(self.target)), self.check(pending))
        self.target.write_bytes(b'appeared')
        self.assertEqual((False, inspect(self.target)), self.check(pending))

    def test_stat_read_stat_order_and_races(self):
        self.target.write_bytes(b'abc')
        baseline = dict(st_size=3, st_mtime_ns=123, st_dev=4, st_ino=5)
        # Stub classification so the two explicit snapshot stats are isolated.
        for field in baseline:
            events = []
            stats = iter([SimpleNamespace(**baseline), SimpleNamespace(**dict(baseline, **{field: 999}))])
            def stat(*args, **kwargs):
                events.append('stat')
                self.assertEqual({'follow_symlinks': False}, kwargs)
                return next(stats)
            real_open = open
            def reader(*args, **kwargs):
                events.append('open')
                self.assertEqual('rb', args[1])
                return real_open(*args, **kwargs)
            with patch.object(safety.os.path, 'isdir', side_effect=[True, False]), patch.object(safety.os.path, 'isfile', return_value=True), patch.object(safety.os.path, 'islink', return_value=False), patch.object(safety.os.path, 'lexists', return_value=True), patch.object(safety.os, 'stat', side_effect=stat), patch('builtins.open', side_effect=reader):
                with self.assertRaises(OSError):
                    inspect(self.target)
            self.assertEqual(['stat', 'open', 'stat'], events)

    def test_failures_propagate_and_confirmation_fails_closed(self):
        self.target.write_bytes(b'abc')
        pending = self.pending()
        for error in (OSError, TypeError, ValueError):
            with patch.object(safety, 'inspect_project_save_as_destination', side_effect=error):
                self.assertEqual((False, {}), self.check(pending))
        with patch.object(safety, 'inspect_project_save_as_destination', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.check(pending)
        for target in ('builtins.open', 'core.project_save_as_safety.hashlib.sha256'):
            with patch(target, side_effect=OSError):
                with self.assertRaises(OSError):
                    inspect(self.target)
                self.assertEqual((False, {}), self.check(pending))
        for failed_stat in (0, 1):
            stat = self.target.stat()
            with patch.object(safety.os.path, 'isdir', side_effect=[True, False]), patch.object(safety.os.path, 'isfile', return_value=True), patch.object(safety.os.path, 'islink', return_value=False), patch.object(safety.os.path, 'lexists', return_value=True), patch.object(safety.os, 'stat', side_effect=[OSError()] if failed_stat == 0 else [stat, OSError()]):
                with self.assertRaises(OSError):
                    inspect(self.target)
        with patch('builtins.open') as opened:
            opened.return_value.__enter__.return_value.read.side_effect = OSError
            with self.assertRaises(OSError):
                inspect(self.target)
        digest = Mock()
        digest.update.side_effect = OSError
        with patch.object(safety.hashlib, 'sha256', return_value=digest):
            with self.assertRaises(OSError):
                inspect(self.target)
        self.assertEqual(b'abc', self.target.read_bytes())


if __name__ == '__main__':
    unittest.main()
