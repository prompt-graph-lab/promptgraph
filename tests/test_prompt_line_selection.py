import ast
import copy
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from core import prompt_line_selection as owner


class LineSelectionTests(unittest.TestCase):
    def test_visible_order_stable_falsey_indices_and_identity(self):
        lines = [NS(id='none', current_index=None), NS(id='zero', current_index=0), NS(id='missing'), NS(id='negative', current_index=-1), NS(id='deleted', deleted=True)]
        project = NS(prompt_lines=lines)
        before = copy.deepcopy(project)
        result = owner.get_visible_prompt_lines(project)
        self.assertEqual([x.id for x in result], ['negative', 'zero', 'none', 'missing'])
        self.assertIs(result[0], lines[3])
        self.assertEqual(project, before)
        self.assertEqual(owner.get_visible_prompt_lines(None), [])
        with self.assertRaises(TypeError):
            owner.get_visible_prompt_lines(NS(prompt_lines=None))

    def test_adjacent_first_duplicate_and_endpoints(self):
        project = NS(prompt_lines=[NS(id=x, current_index=i) for i, x in enumerate(['a', 'b', 'a'])])
        self.assertEqual(owner.get_adjacent_focus_line_ids(project, 'a'), (None, 'b'))
        self.assertEqual(owner.get_adjacent_focus_line_ids(project, 'b'), ('a', 'a'))
        self.assertEqual(owner.get_adjacent_focus_line_ids(project, 'missing'), (None, None))

    def test_eligibility_distinguishes_separator_workbench_and_deleted(self):
        for line, expected in [(None, False), (NS(), True), (NS(line_type='separator'), False), (NS(line_type='workbench'), False), (NS(deleted=True), False), (NS(line_type='unknown'), True)]:
            self.assertEqual(owner.is_gallery_operation_prompt_line(line), expected)
        self.assertFalse(owner.is_route_separator(None))
        self.assertFalse(owner.is_workbench_line(None))

    def test_app_imports_preserve_identity(self):
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8'))
        imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == 'core.prompt_line_selection']
        scope = {}
        exec(compile(ast.Module(body=imports, type_ignores=[]), 'app.py', 'exec'), scope)
        for name in ('get_visible_prompt_lines', 'get_adjacent_focus_line_ids', 'is_route_separator', 'is_workbench_line', 'is_gallery_operation_prompt_line'):
            self.assertIs(scope[name], getattr(owner, name))
