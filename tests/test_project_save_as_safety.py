import copy
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, mock_open

from core import project_save_as_safety as safety


class SaveAsSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / 'Target.json'
        self.source = Path(self.temp.name) / 'source.json'
        self.project = object()

    def pending(self):
        return safety.build_project_save_as_pending_overwrite(
            safety.inspect_project_save_as_destination(self.target), self.source, self.project)

    def fresh(self, pending):
        return safety.project_save_as_confirmation_is_fresh(
            pending, self.target, self.source, self.project)

    def test_normalization(self):
        for value in ('', '  ', '\x00', 'a\x00b', b'file', None):
            self.assertEqual('', safety.normalize_project_save_as_path(value))
        self.assertEqual(str(self.target), safety.normalize_project_save_as_path(self.target))
        self.assertEqual(os.path.abspath('Mixed.json'), safety.normalize_project_save_as_path(' Mixed.json '))
        with patch.object(safety.os.path, 'expanduser', return_value='expanded') as expand, patch.object(safety.os.path, 'abspath', return_value='ABS') as absolute:
            self.assertEqual('ABS', safety.normalize_project_save_as_path(' ~/Target '))
            expand.assert_called_once_with('~/Target')
            absolute.assert_called_once_with('expanded')
        self.assertEqual(os.path.abspath(os.path.expanduser('~/Target')), safety.normalize_project_save_as_path('~/Target'))
        for error in (TypeError, ValueError):
            with patch.object(safety.os, 'fspath', side_effect=error):
                self.assertEqual('', safety.normalize_project_save_as_path(self.target))
        with patch.object(safety.os, 'fspath', side_effect=OSError):
            self.assertRaises(OSError, safety.normalize_project_save_as_path, self.target)
        for error in (OSError, TypeError, ValueError):
            with patch.object(safety.os.path, 'expanduser', side_effect=error):
                self.assertEqual('', safety.normalize_project_save_as_path(self.target))

    def test_missing_directory_and_invalid_parent(self):
        expected = dict(normalized_path=str(self.target), occupied=False, kind='missing', size=None, mtime_ns=None, device=None, inode=None, sha256='')
        self.assertEqual(expected, safety.inspect_project_save_as_destination(self.target))
        self.assertFalse(self.target.exists())
        self.target.mkdir()
        expected.update(occupied=True, kind='directory')
        self.assertEqual(expected, safety.inspect_project_save_as_destination(self.target))
        for path in (' ', '\x00', self.target / 'absent' / 'file'):
            self.assertRaises(ValueError, safety.inspect_project_save_as_destination, path)

    def test_symlink_and_broken_symlink(self):
        referent = self.source
        referent.write_bytes(b'untouched')
        try:
            self.target.symlink_to(referent)
        except OSError as error:
            self.skipTest(f'Symlink creation unavailable: {error}')
        for broken in (False, True):
            if broken:
                referent.unlink()
            snapshot = safety.inspect_project_save_as_destination(self.target)
            self.assertEqual('unsupported', snapshot['kind'])
            self.assertTrue(snapshot['occupied'])
            self.assertTrue(self.target.is_symlink())

    def test_link_classification_does_not_follow_or_open_target(self):
        # lexists is true for both intact and dangling symlinks; neither is read.
        with patch.object(safety.os.path, 'lexists', return_value=True), patch.object(safety.os.path, 'islink', return_value=True), patch.object(safety.os.path, 'isdir', return_value=True) as isdir, patch('core.project_save_as_safety.open') as opened:
            snapshot = safety.inspect_project_save_as_destination(self.target)
        self.assertEqual('unsupported', snapshot['kind'])
        self.assertTrue(snapshot['occupied'])
        self.assertEqual(1, isdir.call_count)  # Parent validation only.
        opened.assert_not_called()

    def test_unsupported_entry(self):
        with patch.object(safety.os.path, 'lexists', return_value=True), patch.object(safety.os.path, 'islink', return_value=False), patch.object(safety.os.path, 'isdir', side_effect=[True, False]), patch.object(safety.os.path, 'isfile', return_value=False):
            snapshot = safety.inspect_project_save_as_destination(self.target)
        self.assertEqual('unsupported', snapshot['kind'])
        self.assertTrue(snapshot['occupied'])

    def test_regular_file_complete_read_and_no_mutation(self):
        data = b'x' * (1024 * 1024 + 13)
        self.target.write_bytes(data)
        before = self.target.stat()
        snapshot = safety.inspect_project_save_as_destination(self.target)
        self.assertEqual(dict(normalized_path=str(self.target), occupied=True, kind='file', size=len(data), mtime_ns=before.st_mtime_ns, device=before.st_dev, inode=before.st_ino, sha256=hashlib.sha256(data).hexdigest()), snapshot)
        pending = self.pending()
        self.assertEqual((True, snapshot), self.fresh(pending))
        self.assertEqual(data, self.target.read_bytes())
        self.assertEqual(before.st_mtime_ns, self.target.stat().st_mtime_ns)
        self.assertEqual([self.target], list(self.target.parent.iterdir()))

    def test_pending_deepcopy_and_same_path(self):
        self.target.write_bytes(b'data')
        snapshot = safety.inspect_project_save_as_destination(self.target)
        snapshot['extra'] = {'nested': []}
        pending = safety.build_project_save_as_pending_overwrite(snapshot, self.source, self.project)
        snapshot['extra']['nested'].append(1)
        self.assertEqual([], pending['target_snapshot']['extra']['nested'])
        self.assertEqual({'target_path', 'target_snapshot', 'source_project_path', 'source_project_object_id'}, set(pending))
        self.assertEqual(id(self.project), pending['source_project_object_id'])
        pending = safety.build_project_save_as_pending_overwrite(safety.inspect_project_save_as_destination(self.target), self.target, self.project)
        self.assertTrue(safety.project_save_as_confirmation_is_fresh(pending, self.target.parent / '.' / self.target.name, self.target, self.project)[0])

    def test_each_snapshot_field_is_compared(self):
        self.target.write_bytes(b'data')
        pending = self.pending()
        for key, value in [('size', 9), ('mtime_ns', 0), ('device', -1), ('inode', -1), ('sha256', 'changed'), ('occupied', False), ('kind', 'directory'), ('normalized_path', 'other')]:
            current = dict(pending['target_snapshot'], **{key: value})
            with self.subTest(key=key), patch.object(safety, 'inspect_project_save_as_destination', return_value=current):
                self.assertEqual((False, current), self.fresh(pending))
        current = dict(pending['target_snapshot'], extra=True)
        with patch.object(safety, 'inspect_project_save_as_destination', return_value=current):
            self.assertEqual((False, current), self.fresh(pending))

    def test_actual_changes_disappearance_and_appearance(self):
        self.target.write_bytes(b'data')
        for change in ('size', 'mtime', 'hash', 'disappear'):
            pending = self.pending()
            if change == 'size': self.target.write_bytes(b'longer')
            elif change == 'mtime': os.utime(self.target, ns=(0, 0))
            elif change == 'hash':
                self.target.write_bytes(b'LONGER')
                stamp = pending['target_snapshot']['mtime_ns']
                os.utime(self.target, ns=(stamp, stamp))
            else: self.target.unlink()
            self.assertFalse(self.fresh(pending)[0])
        pending = self.pending()
        self.assertEqual((False, pending['target_snapshot']), self.fresh(pending))
        self.target.write_bytes(b'appeared')
        self.assertEqual('file', self.fresh(pending)[1]['kind'])
        self.assertFalse(self.fresh(pending)[0])

    def test_context_rejection_precedes_inspection(self):
        self.target.write_bytes(b'data')
        pending = self.pending()
        cases = [(None, self.target, self.source, self.project), ({}, self.target, self.source, self.project), (pending, '', self.source, self.project), (pending, self.source, self.source, self.project), (pending, self.target, self.target, self.project), (pending, self.target, self.source, object())]
        with patch.object(safety, 'inspect_project_save_as_destination') as inspect:
            for args in cases:
                self.assertEqual((False, {}), safety.project_save_as_confirmation_is_fresh(*args))
            inspect.assert_not_called()

    def test_stat_read_stat_order_and_races(self):
        self.target.write_bytes(b'data')
        original_stat = safety.os.stat
        real = original_stat(self.target)
        fields = ('st_size', 'st_mtime_ns', 'st_dev', 'st_ino')
        for changed in (None,) + fields:
            events = []
            before = SimpleNamespace(**{k: getattr(real, k) for k in fields})
            after = copy.copy(before)
            if changed: setattr(after, changed, getattr(after, changed) + 1)
            stats = iter((before, after))
            def stat(path, **kwargs):
                if kwargs.get('follow_symlinks') is False:
                    events.append('stat')
                    return next(stats)
                return original_stat(path, **kwargs)
            digest = hashlib.sha256()
            class Digest:
                def update(self, chunk):
                    events.append('hash')
                    digest.update(chunk)
                def hexdigest(self): return digest.hexdigest()
            with patch.object(safety.os, 'stat', side_effect=stat), patch.object(safety.hashlib, 'sha256', return_value=Digest()):
                if changed: self.assertRaises(OSError, safety.inspect_project_save_as_destination, self.target)
                else: safety.inspect_project_save_as_destination(self.target)
            self.assertEqual(['stat', 'hash', 'stat'], events)

    def test_failures_propagate_and_confirmation_fails_closed(self):
        self.target.write_bytes(b'data')
        pending = self.pending()
        original_stat = safety.os.stat
        for stage in ('stat', 'second_stat', 'open', 'read', 'hash'):
            calls = []
            def stat(path, **kwargs):
                if kwargs.get('follow_symlinks') is False:
                    calls.append(1)
                    if stage == 'stat' or len(calls) == 2: raise OSError('stat failure')
                return original_stat(path, **kwargs)
            if stage in ('stat', 'second_stat'): context = patch.object(safety.os, 'stat', side_effect=stat)
            elif stage == 'open': context = patch('core.project_save_as_safety.open', side_effect=OSError('open failure'))
            elif stage == 'read':
                handle = mock_open(); handle.return_value.read.side_effect = OSError('read failure')
                context = patch('core.project_save_as_safety.open', handle)
            else: context = patch.object(safety.hashlib, 'sha256', side_effect=ValueError('hash failure'))
            with self.subTest(stage=stage), context:
                self.assertRaises((OSError, ValueError), safety.inspect_project_save_as_destination, self.target)
                calls.clear()
                self.assertEqual((False, {}), self.fresh(pending))
        for error in (OSError, TypeError, ValueError):
            with patch.object(safety, 'inspect_project_save_as_destination', side_effect=error):
                self.assertEqual((False, {}), self.fresh(pending))
        self.assertEqual(b'data', self.target.read_bytes())


if __name__ == '__main__':
    unittest.main()
