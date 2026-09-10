"""Contracts for in-memory AnimaDex record projections, independent of discovery."""
import ast
import copy
import hashlib
from pathlib import Path
import unittest

from core import animadex_record_inspection

NAMES = (
    '_animadex_record_identity', '_animadex_record_search_text',
    '_filter_animadex_records', '_animadex_record_label',
    '_animadex_summary_rows', '_animadex_preview_metadata_rows',
)
F = vars(animadex_record_inspection)


class AnimaDexRecordInspectionTests(unittest.TestCase):
    def test_app_import_surface_preserves_helper_identity(self):
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8'))
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'core.animadex_record_inspection']
        scope = {}
        exec(compile(ast.Module(body=imports, type_ignores=[]), 'app.py', 'exec'), scope)
        for name in NAMES:
            self.assertIs(scope[name], F[name])

    def test_identity_field_order_missing_none_and_utf8_replacement(self):
        f = F[NAMES[0]]
        record = dict(source_type='csv', source_path='a', source_detail=None,
                      character_id=0, name='青', trigger='\ud800', extra='ignored')
        expected = hashlib.sha1('csv|a|None|0|青|?'.encode('utf-8')).hexdigest()
        self.assertEqual(f(record), expected)
        self.assertEqual(f({}), hashlib.sha1(b'|||||').hexdigest())
        self.assertEqual(f({'name': 'a|b', 'trigger': 'c'}), f({'name': 'a', 'trigger': 'b|c'}))
        with self.assertRaises(AttributeError):
            f(None)

    def test_search_field_order_casefold_and_falsey_values(self):
        record = dict(name='Straße', character=0, copyright=None, copyright_name='Work',
                      series='S', work='W', franchise='F', artist='A', trigger='T',
                      core_tags=['青', 0], traits={'z': 'Last', 'a': None}, ignored='hidden')
        self.assertEqual(F[NAMES[1]](record), 'strasse work s w f a t 青 0 last none')
        self.assertEqual(F[NAMES[1]]({}), '')
        with self.assertRaises(AttributeError):
            F[NAMES[1]]({'traits': ['bad']})

    def test_filter_all_terms_order_duplicates_and_aliases(self):
        a = {'name': 'Straße', 'core_tags': ['blue']}
        b = {'name': 'red'}
        records = [a, b, a]
        before = copy.deepcopy(records)
        result = F[NAMES[2]](records, ' STRASSE blue ')
        self.assertEqual(result, [a, a])
        self.assertIs(result[0], a)
        self.assertIsNot(F[NAMES[2]](records, None), records)
        self.assertEqual(F[NAMES[2]](None, 'x'), [])
        self.assertEqual(records, before)
        # Empty-query path does not inspect malformed records.
        self.assertEqual(F[NAMES[2]]([None], 0), [None])
        with self.assertRaises(AttributeError):
            F[NAMES[2]]([None], 'x')

    def test_labels_exact_fallback_precedence(self):
        f = F[NAMES[3]]
        self.assertEqual(f({}), '(unnamed) | unknown work | no trigger | character | unknown')
        self.assertEqual(f(dict(name='', character='C', trigger='T', copyright_name='', copyright='W', series='S', record_type='item', source_type='csv')), 'C | W | T | item | csv')
        self.assertEqual(f({'trigger': 'T', 'work': 'W'}), 'T | W | T | character | unknown')

    def test_summary_preserves_none_and_nested_aliases(self):
        name = {'extension': 1}
        record = dict(name=name, character=None, copyright_name='', copyright='W', core_tags=['x', 'x'])
        before = copy.deepcopy(record)
        rows = F[NAMES[4]]([record, record])
        self.assertEqual(rows[0], {'type': '', 'name': name, 'character': None, 'copyright': 'W', 'series': '', 'work': '', 'trigger': '', 'core tag count': 2, 'source type': ''})
        self.assertIs(rows[0]['name'], name)
        self.assertIsNot(rows[0], rows[1])
        self.assertEqual(record, before)
        self.assertEqual(F[NAMES[4]](None), [])
        with self.assertRaises(TypeError):
            F[NAMES[4]]([{'core_tags': 1}])

    def test_metadata_order_container_formatting_and_falsey_scalars(self):
        metadata = {'dict': {'b': 2, 'a': 1}, 'list': ['x', None], 'empty': '', 'empty_list': [], 'empty_dict': {}, 'none': None, 'zero': 0, 'false': False}
        before = copy.deepcopy(metadata)
        self.assertEqual(F[NAMES[5]](metadata), [
            {'field': 'dict', 'value': 'b: 2, a: 1'},
            {'field': 'list', 'value': 'x, None'},
            {'field': 'none', 'value': 'None'},
            {'field': 'zero', 'value': '0'},
            {'field': 'false', 'value': 'False'},
        ])
        self.assertEqual(metadata, before)
        self.assertEqual(F[NAMES[5]](None), [])
        with self.assertRaises(AttributeError):
            F[NAMES[5]](['x'])


if __name__ == '__main__':
    unittest.main()
