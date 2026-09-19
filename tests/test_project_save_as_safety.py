"""Direct characterization of read-only Save As safety preparation."""
import copy
import hashlib
import io
import os
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from core import project_save_as_safety as safety


class SaveAsSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'target.json'
        self.source = self.root / 'source.json'
        self.project = object()

    def inspect(self):
        return safety.inspect_project_save_as_destination(self.target)

    def pending(self):
        return safety.build_project_save_as_pending_overwrite(self.inspect(), self.source, self.project)

    def fresh(self, pending):
        return safety.project_save_as_confirmation_is_fresh(pending, self.target, self.source, self.project)

    def test_normalization_rejects_blank_nul_bytes_and_invalid_pathlike(self):
        for value in (None, '', ' \t\n', 'x\x00.json', b'x.json', 123):
            with self.subTest(value=value):
                self.assertEqual(safety.normalize_project_save_as_path(value), '')
        for error in (TypeError, ValueError):
            class BadPath:
                def __fspath__(self):
                    raise error('bad path')
            self.assertEqual(safety.normalize_project_save_as_path(BadPath()), '')
        class BytePath:
            def __fspath__(self):
                return b'x.json'
        self.assertEqual(safety.normalize_project_save_as_path(BytePath()), '')
        with patch.object(safety.os, 'fspath', side_effect=OSError('not swallowed')):
            with self.assertRaisesRegex(OSError, 'not swallowed'):
                safety.normalize_project_save_as_path('x')

    def test_pathlike_relative_strip_and_expanduser_do_not_case_normalize(self):
        self.assertEqual(safety.normalize_project_save_as_path(self.target), str(self.target))
        self.assertEqual(safety.normalize_project_save_as_path(' MiXeD.json '), os.path.abspath('MiXeD.json'))
        events = []
        def expand(value):
            events.append(('expand', value))
            return 'expanded/MiXeD.json'
        def absolute(value):
            events.append(('absolute', value))
            return 'Final/MiXeD.json'
        with patch.object(safety.os.path, 'expanduser', expand), \
             patch.object(safety.os.path, 'abspath', absolute), \
             patch.object(safety.os.path, 'normcase', side_effect=AssertionError('must not normalize case')):
            self.assertEqual(safety.normalize_project_save_as_path(' ~/MiXeD.json '), 'Final/MiXeD.json')
        self.assertEqual(events, [('expand', '~/MiXeD.json'), ('absolute', 'expanded/MiXeD.json')])
        self.assertEqual(safety.normalize_project_save_as_path('~/MiXeD.json'),
                         os.path.abspath(os.path.expanduser('~/MiXeD.json')))

    def test_normalization_catches_only_expected_expansion_and_absolute_errors(self):
        for operation in ('expanduser', 'abspath'):
            for error in (OSError, TypeError, ValueError):
                with self.subTest(operation=operation, error=error), \
                     patch.object(safety.os.path, operation, side_effect=error('bad')):
                    self.assertEqual(safety.normalize_project_save_as_path('x'), '')
        with patch.object(safety.os.path, 'expanduser', side_effect=RuntimeError('unexpected')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                safety.normalize_project_save_as_path('x')

    def test_invalid_path_and_missing_parent_fail_before_entry_inspection(self):
        for value in ('', '\x00', self.root / 'absent' / 'target.json'):
            with self.subTest(value=value), patch.object(safety.os.path, 'lexists') as lexists:
                with self.assertRaises(ValueError):
                    safety.inspect_project_save_as_destination(value)
                lexists.assert_not_called()
        with patch.object(safety.os.path, 'dirname', return_value=''):
            with self.assertRaises(ValueError):
                self.inspect()

    def test_nonexistent_snapshot_and_directory_are_not_authorized(self):
        expected = {'normalized_path': str(self.target), 'occupied': False, 'kind': 'missing',
                    'size': None, 'mtime_ns': None, 'device': None, 'inode': None, 'sha256': ''}
        self.assertEqual(self.inspect(), expected)
        pending = self.pending()
        self.assertEqual(self.fresh(pending), (False, expected))
        self.target.mkdir()
        expected.update(occupied=True, kind='directory')
        self.assertEqual(self.inspect(), expected)
        self.assertEqual(self.fresh(self.pending()), (False, expected))

    def test_regular_file_snapshot_is_complete_and_non_destructive(self):
        payload = b'x' * (1024 * 1024 + 17)
        self.target.write_bytes(payload)
        stat = self.target.stat()
        expected = {'normalized_path': str(self.target), 'occupied': True, 'kind': 'file',
                    'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'device': stat.st_dev,
                    'inode': stat.st_ino, 'sha256': hashlib.sha256(payload).hexdigest()}
        snapshot = self.inspect()
        self.assertEqual(snapshot, expected)
        pending = self.pending()
        before = copy.deepcopy(pending)
        self.assertEqual(self.fresh(pending), (True, expected))
        self.assertEqual(pending, before)
        self.assertEqual(self.target.read_bytes(), payload)
        self.assertEqual(list(self.root.iterdir()), [self.target])
        self.assertEqual(self.target.stat().st_mtime_ns, stat.st_mtime_ns)

    def test_symlink_and_broken_symlink_use_lexists_and_never_read_target(self):
        # Model both link types without requiring Windows symlink privileges.
        for target_exists in (True, False):
            with self.subTest(target_exists=target_exists), \
                 patch.object(safety.os.path, 'exists', return_value=target_exists), \
                 patch.object(safety.os.path, 'lexists', return_value=True) as lexists, \
                 patch.object(safety.os.path, 'islink', return_value=True), \
                 patch.object(safety, 'open', create=True) as opened:
                result = self.inspect()
                self.assertEqual(result['kind'], 'unsupported')
                self.assertTrue(result['occupied'])
                lexists.assert_called_once_with(str(self.target))
                opened.assert_not_called()

    def test_unsupported_entry_is_occupied_without_reading(self):
        with patch.object(safety.os.path, 'lexists', return_value=True), \
             patch.object(safety.os.path, 'islink', return_value=False), \
             patch.object(safety.os.path, 'isdir', side_effect=[True, False]), \
             patch.object(safety.os.path, 'isfile', return_value=False), \
             patch.object(safety, 'open', create=True) as opened:
            result = self.inspect()
            self.assertEqual(result['kind'], 'unsupported')
            self.assertTrue(result['occupied'])
            opened.assert_not_called()

    def test_pending_deepcopy_source_normalization_and_identity_order(self):
        snapshot = {'normalized_path': self.target, 'nested': {'x': []}}
        pending = safety.build_project_save_as_pending_overwrite(snapshot, self.source, self.project)
        self.assertEqual(set(pending), {'target_path', 'target_snapshot', 'source_project_path', 'source_project_object_id'})
        self.assertEqual(pending['target_path'], str(self.target))
        self.assertEqual(pending['source_project_path'], str(self.source))
        self.assertEqual(pending['source_project_object_id'], id(self.project))
        self.assertIsNot(pending['target_snapshot']['nested']['x'], snapshot['nested']['x'])
        events = []
        class Snapshot(dict):
            def get(self, key):
                events.append('target')
                return ''
            def __deepcopy__(self, memo):
                events.append('copy')
                return {}
        with patch.object(safety, 'normalize_project_save_as_path', side_effect=lambda _: events.append('source') or ''), \
             patch.object(safety, 'id', create=True, side_effect=lambda _: events.append('identity') or 42):
            safety.build_project_save_as_pending_overwrite(Snapshot(), '', self.project)
        self.assertEqual(events, ['target', 'copy', 'source', 'identity'])

    def test_source_and_target_changes_reject_before_inspection(self):
        self.target.write_bytes(b'old')
        pending = self.pending()
        cases = ((None, self.target, self.source, self.project),
                 ({'target_snapshot': []}, self.target, self.source, self.project),
                 (pending, '', self.source, self.project),
                 (pending, self.root / 'other', self.source, self.project),
                 (pending, self.target, self.root / 'other', self.project),
                 (pending, self.target, self.source, object()))
        with patch.object(safety, 'inspect_project_save_as_destination') as inspect:
            for args in cases:
                self.assertEqual(safety.project_save_as_confirmation_is_fresh(*args), (False, {}))
            inspect.assert_not_called()

    def test_same_source_target_and_empty_source_context_retain_legacy_semantics(self):
        self.target.write_bytes(b'data')
        for source in (self.target, ''):
            pending = safety.build_project_save_as_pending_overwrite(self.inspect(), source, self.project)
            self.assertTrue(safety.project_save_as_confirmation_is_fresh(pending, self.target, source, self.project)[0])

    def test_freshness_normalizes_both_paths_before_rejection_and_uses_normcase(self):
        pending = {'target_snapshot': {}, 'target_path': 'TARGET', 'source_project_path': 'SOURCE',
                   'source_project_object_id': id(self.project)}
        with patch.object(safety, 'normalize_project_save_as_path', side_effect=['', 'source']) as normalize:
            self.assertEqual(self.fresh(pending), (False, {}))
            self.assertEqual(normalize.call_count, 2)
        snapshot = {'kind': 'file'}
        pending['target_snapshot'] = snapshot
        with patch.object(safety, 'normalize_project_save_as_path', side_effect=['target', 'source']), \
             patch.object(safety.os.path, 'normcase', side_effect=str.lower) as normcase, \
             patch.object(safety, 'inspect_project_save_as_destination', return_value=snapshot):
            self.assertEqual(self.fresh(pending), (True, snapshot))
            self.assertEqual([c.args[0] for c in normcase.call_args_list], ['TARGET', 'target', 'SOURCE', 'source'])

    def test_size_mtime_hash_disappearance_and_appearance_changes(self):
        for change in ('size', 'mtime', 'hash', 'disappear', 'appear'):
            with self.subTest(change=change):
                self.target.write_bytes(b'old')
                if change == 'appear':
                    self.target.unlink()
                pending = self.pending()
                if change in ('size', 'appear'):
                    self.target.write_bytes(b'new-content')
                elif change == 'mtime':
                    old = pending['target_snapshot']['mtime_ns']
                    os.utime(self.target, ns=(old + 2_000_000_000, old + 2_000_000_000))
                elif change == 'hash':
                    self.target.write_bytes(b'NEW')
                    old = pending['target_snapshot']['mtime_ns']
                    os.utime(self.target, ns=(old, old))
                else:
                    self.target.unlink()
                current = self.inspect()
                self.assertEqual(self.fresh(pending), (False, current))
                self.assertNotEqual(current, pending['target_snapshot'])
                if change == 'hash':
                    self.assertEqual(current['size'], pending['target_snapshot']['size'])
                    self.assertEqual(current['mtime_ns'], pending['target_snapshot']['mtime_ns'])

    def test_complete_snapshot_comparison_includes_device_inode_and_unknown_fields(self):
        self.target.write_bytes(b'data')
        pending = self.pending()
        for key in ('device', 'inode', 'unknown'):
            current = dict(pending['target_snapshot'])
            current[key] = current.get(key, 0) + 1
            with self.subTest(key=key), patch.object(safety, 'inspect_project_save_as_destination', return_value=current):
                fresh, returned = self.fresh(pending)
                self.assertFalse(fresh)
                self.assertIs(returned, current)

    def file_probe(self, stack, before, after, opened):
        stack.enter_context(patch.object(safety.os.path, 'isdir', side_effect=[True, False]))
        stack.enter_context(patch.object(safety.os.path, 'lexists', return_value=True))
        stack.enter_context(patch.object(safety.os.path, 'islink', return_value=False))
        stack.enter_context(patch.object(safety.os.path, 'isfile', return_value=True))
        stat = stack.enter_context(patch.object(safety.os, 'stat', side_effect=[before, after]))
        stack.enter_context(patch.object(safety, 'open', create=True, side_effect=opened))
        return stat

    def test_stat_hash_stat_order_and_each_race_signature_field(self):
        original = dict(st_size=3, st_mtime_ns=1, st_dev=2, st_ino=3)
        for changed in (None, *original):
            events = []
            after = dict(original)
            if changed:
                after[changed] += 1
            class Handle(io.BytesIO):
                def read(self, size):
                    events.append(('read', size))
                    return super().read(size)
            with self.subTest(changed=changed), ExitStack() as stack:
                stat = self.file_probe(stack, SimpleNamespace(**original), SimpleNamespace(**after),
                                       lambda *args: events.append('open') or Handle(b'abc'))
                values = iter(stat.side_effect)
                stat.side_effect = lambda *args, **kwargs: events.append('stat') or next(values)
                if changed:
                    with self.assertRaises(OSError):
                        self.inspect()
                else:
                    self.assertEqual(self.inspect()['sha256'], hashlib.sha256(b'abc').hexdigest())
                self.assertEqual(events, ['stat', 'open', ('read', 1024 * 1024), ('read', 1024 * 1024), 'stat'])
                self.assertEqual(stat.call_args.kwargs, {'follow_symlinks': False})

    def test_stat_open_read_and_hash_failures_propagate_and_confirmation_is_stale(self):
        self.target.write_bytes(b'abc')
        pending = self.pending()
        info = SimpleNamespace(st_size=3, st_mtime_ns=1, st_dev=2, st_ino=3)
        for stage in ('first_stat', 'open', 'read', 'hash_init', 'hash_update', 'second_stat', 'hash_hex'):
            failure = OSError(stage)
            with self.subTest(stage=stage), ExitStack() as stack:
                before = failure if stage == 'first_stat' else info
                after = failure if stage == 'second_stat' else info
                handle = Mock()
                handle.__enter__ = Mock(return_value=handle)
                handle.__exit__ = Mock(return_value=False)
                handle.read = Mock(side_effect=failure if stage == 'read' else [b'abc', b''])
                self.file_probe(stack, before, after, Mock(side_effect=failure) if stage == 'open' else Mock(return_value=handle))
                if stage.startswith('hash_'):
                    digest = Mock()
                    if stage == 'hash_update':
                        digest.update.side_effect = failure
                    if stage == 'hash_hex':
                        digest.hexdigest.side_effect = failure
                    stack.enter_context(patch.object(safety.hashlib, 'sha256', side_effect=failure if stage == 'hash_init' else None, return_value=digest))
                with self.assertRaises(OSError) as raised:
                    self.inspect()
                self.assertIs(raised.exception, failure)
            with patch.object(safety, 'inspect_project_save_as_destination', side_effect=failure):
                self.assertEqual(self.fresh(pending), (False, {}))
        for error in (TypeError, ValueError):
            with patch.object(safety, 'inspect_project_save_as_destination', side_effect=error('invalid')):
                self.assertEqual(self.fresh(pending), (False, {}))
        with patch.object(safety, 'inspect_project_save_as_destination', side_effect=RuntimeError('unexpected')):
            with self.assertRaisesRegex(RuntimeError, 'unexpected'):
                self.fresh(pending)
        self.assertEqual(self.target.read_bytes(), b'abc')


if __name__ == '__main__':
    unittest.main()
