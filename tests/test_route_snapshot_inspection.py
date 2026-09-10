import copy
import unittest
from core.route_snapshot_inspection import (
    _short_preview, _route_snapshot_label, _ensure_route_snapshot_metadata,
    _route_snapshot_image_path, _route_compare_line_label,
    _compare_route_snapshots, _sorted_route_snapshot_items,
)

class RouteSnapshotInspectionTests(unittest.TestCase):
    def test_metadata_coercion_and_clamping_without_mutation(self):
        for score, expected in [('',None), (None,None), ('bad',None), ([],None),
                                (False,0.0), (True,1.0), (-4,0.0), ('12',10.0),
                                ('2.5',2.5), (float('inf'),10.0), (float('-inf'),0.0), (float('nan'),10.0)]:
            with self.subTest(score=score):
                snapshot = {'score': score, 'favorite': 'no', 'notes': 3, 'tags': 'x'}
                result = _ensure_route_snapshot_metadata(snapshot)
                self.assertEqual({'score': expected, 'favorite': True, 'notes': '', 'tags': 'x'}, result)
                self.assertIs(score, snapshot['score'])
        self.assertEqual({}, _ensure_route_snapshot_metadata(None))

    def test_unhandled_score_exception_propagates(self):
        class Score:
            def __float__(self): raise OverflowError('score overflow')
        with self.assertRaises(OverflowError):
            _ensure_route_snapshot_metadata({'score': Score()})

    def test_path_precedence_and_identity(self):
        path = object()
        self.assertIs(path, _route_snapshot_image_path({'selected_candidate_path': path, 'generated_image_path': 'g'}))
        self.assertEqual('g', _route_snapshot_image_path({'selected_candidate_path': '', 'generated_image_path': 'g'}))
        self.assertEqual('', _route_snapshot_image_path(None))
        self.assertEqual('', _route_snapshot_image_path({'generated_image_path': 0}))

    def test_labels_falsey_values_bool_index_and_short_preview(self):
        self.assertEqual('1. Untitled sequence', _route_snapshot_label(0, None))
        self.assertEqual('2. ★ None None', _route_snapshot_label(1, {'favorite': True, 'name': None, 'created_at': None}))
        self.assertEqual('Illustration 2: a b', _route_compare_line_label({'line_index': True, 'prompt_text': ' a\n b '}))
        self.assertEqual('Untitled illustration', _route_compare_line_label({'line_index': '1', 'prompt_text': 0}))
        self.assertEqual('x'*77+'...', _route_compare_line_label({'prompt_text': 'x'*81}))
        self.assertEqual('abc...', _short_preview('abcdef', 0))
        with self.assertRaises(AttributeError): _short_preview(None)

    def test_comparison_duplicates_order_equal_paths_and_unmatched_rows(self):
        a = {'items': [None, {'line_id': ''}, {'line_id': 'b', 'generated_image_path': 'old'},
                       {'line_id': 'a', 'generated_image_path': 'same'},
                       {'line_id': 'b', 'generated_image_path': 'new', 'prompt_text': 'latest'},
                       {'line_id': 'c', 'generated_image_path': 'c'}]}
        b = {'items': [{'line_id': 'c', 'generated_image_path': 'd'},
                       {'line_id': 'a', 'generated_image_path': 'same'},
                       {'line_id': 'b', 'generated_image_path': 'other'}, {'line_id': 'only-b'}]}
        before = copy.deepcopy((a,b))
        self.assertEqual([{'line_id': 'b', 'label': 'latest', 'path_a': 'new', 'path_b': 'other'},
                          {'line_id': 'c', 'label': 'Untitled illustration', 'path_a': 'c', 'path_b': 'd'}], _compare_route_snapshots(a,b))
        self.assertEqual(before, (a,b))
        self.assertEqual([], _compare_route_snapshots(None, None))

    def test_equal_paths_skip_bad_label_but_malformed_items_propagate(self):
        a = {'items': [{'line_id': 'x', 'prompt_text': object()}]}
        self.assertEqual([], _compare_route_snapshots(a,a))
        with self.assertRaises(TypeError): _compare_route_snapshots({'items': None}, {})
        with self.assertRaises(TypeError): _compare_route_snapshots({'items': [{'line_id': []}, {'line_id': ['x']}]}, {})

    def test_stable_sort_retains_item_identity_and_duplicate_entries(self):
        items = [{'line_index': '0'}, {'line_index': 2}, {'line_index': False}, {'line_index': 2}, {}, {'line_index': -1}, {'line_index': 0.0}]
        snapshot = {'items': [None] + items + [items[1]]}
        ordered = _sorted_route_snapshot_items(snapshot)
        expected = [items[5], items[2], items[1], items[3], items[1], items[0], items[4], items[6]]
        self.assertEqual(expected, ordered)
        for left,right in zip(expected,ordered): self.assertIs(left,right)
        self.assertEqual([None]+items+[items[1]], snapshot['items'])
        self.assertEqual([], _sorted_route_snapshot_items({'items': None}))
        self.assertEqual([], _sorted_route_snapshot_items(None))
