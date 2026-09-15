import ast
import copy
import os
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import gallery_variant_promotion as promotion
from core.parser import parse_prompt
from core.project import Project, PromptLine


def source_line():
    return PromptLine(
        'parent', 'parent.png', 2, 4, 'old', 'cat, blue', ['old'],
        negative_prompt='negative', line_type='workbench', separator_label='label',
        separator_color='red', workbench_source_line_id='ancestor',
        workbench_title='title', workbench_note='note', workbench_status='ready',
        deleted=True, image_path='original.png', generated_image_path='generated.png',
        selected_candidate_path='selected.png', generated_candidates=[{'path': 'candidate.png'}],
        gallery_variants=[{'path': 'variant.png'}], node_path=['node'],
    )


class PreparationTests(unittest.TestCase):
    def test_copy_resets_and_shallow_provenance_contract(self):
        source = source_line()
        variant = {'id': 'v1', 'source_generation_info': {'nested': []},
                   'lineage_info': {'nested': [], 'unknown': 'keep'}}
        before = copy.deepcopy((source, variant))
        metadata = Mock(side_effect=AssertionError('metadata must stay lazy'))
        result = promotion.prepare_gallery_variant_promotion_line(source, variant, 'images/v.png', 'new', metadata)
        self.assertIsInstance(result, PromptLine)
        self.assertIsNot(result, source)
        self.assertEqual((source, variant), before)
        self.assertEqual(result.id, 'new')
        self.assertEqual(result.original_file_name, 'v.png')
        self.assertEqual((result.original_text, result.current_text), (source.current_text, source.current_text))
        self.assertEqual(result.tokens, parse_prompt(source.current_text))
        self.assertEqual(result.duplicated_from, 'parent')
        self.assertTrue(result.edited)
        self.assertFalse(result.deleted)
        self.assertEqual(result.image_path, 'images/v.png')
        for name in ('generated_image_path', 'selected_candidate_path', 'line_type',
                     'separator_label', 'separator_color', 'workbench_source_line_id',
                     'workbench_title', 'workbench_note', 'workbench_status'):
            self.assertIsNone(getattr(result, name), name)
        for name in ('generated_candidates', 'gallery_variants'):
            self.assertEqual(getattr(result, name), [])
            self.assertIsNot(getattr(result, name), getattr(source, name))
        self.assertEqual(result.node_path, source.node_path)
        self.assertIsNot(result.node_path, source.node_path)
        self.assertEqual((result.original_index, result.current_index, result.negative_prompt), (2, 4, 'negative'))
        self.assertIsNot(result.source_generation_info, variant['source_generation_info'])
        self.assertIs(result.source_generation_info['nested'], variant['source_generation_info']['nested'])
        self.assertIsNot(result.lineage_info, variant['lineage_info'])
        self.assertIs(result.lineage_info['nested'], variant['lineage_info']['nested'])
        self.assertEqual(result.lineage_info, {
            'nested': [], 'unknown': 'keep', 'lineage_kind': 'gallery_variant_promote_to_route',
            'parent_line_id': 'parent', 'parent_line_index': 4, 'parent_line_label': 'parent.png',
            'parent_image_path': 'selected.png', 'promoted_from_variant_id': 'v1',
            'promoted_from_variant_path': 'images/v.png', 'candidate_image_path': 'images/v.png',
        })

    def test_falsey_values_and_existing_empty_dicts(self):
        source = source_line()
        source.original_file_name = ''
        source.selected_candidate_path = ''
        source.generated_image_path = None
        source.image_path = None
        result = promotion.prepare_gallery_variant_promotion_line(
            source, {'id': '', 'source_generation_info': {}, 'lineage_info': {'parent_image_path': 'keep'}},
            '', '', Mock(side_effect=AssertionError))
        self.assertEqual(result.original_file_name, '')
        self.assertEqual(result.source_generation_info, {})
        self.assertEqual(result.lineage_info['parent_line_label'], 'parent')
        self.assertEqual(result.lineage_info['parent_image_path'], 'keep')
        self.assertNotIn('promoted_from_variant_id', result.lineage_info)

    def test_missing_provenance_uses_real_promotion_metadata_and_builders(self):
        source = source_line()
        variant = {'path': 'images\\v.png', 'created_at': '2026-09-15',
                   'candidate_metadata': {'source': '', 'run_index': 0}}
        before = copy.deepcopy((source, variant))
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ('_normalize_candidate_path', '_variant_record_for_promotion')]
        namespace = {'os': os}
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'app.py', 'exec'), namespace)
        result = promotion.prepare_gallery_variant_promotion_line(
            source, variant, 'images/v.png', 'new',
            lambda: namespace['_variant_record_for_promotion'](variant))
        self.assertEqual(result.source_generation_info, {
            'source_kind': 'derived_candidate', 'source_image_path': 'images/v.png',
            'source_prompt': 'cat, blue', 'source_negative_prompt': 'negative',
            'source_raw_metadata': {'source': 'gallery_variant_promotion', 'run_index': 0,
                                    'path': 'images/v.png', 'created_at': '2026-09-15'},
        })
        self.assertEqual(result.lineage_info, {
            'lineage_kind': 'gallery_variant_promote_to_route', 'parent_line_id': 'parent',
            'candidate_image_path': 'images/v.png', 'parent_line_index': 4,
            'parent_line_label': 'parent.png', 'parent_image_path': 'selected.png',
            'created_from': 'gallery_variant_promotion', 'candidate_created_at': '2026-09-15',
            'candidate_run_index': 0, 'promoted_from_variant_path': 'images/v.png',
        })
        self.assertEqual((source, variant), before)

    def test_preparation_order_failure_and_builder_identity(self):
        steps = ['copy', 'id', 'parse', 'normalize', 'metadata', 'source', 'metadata', 'lineage', 'selected']
        for fail_at in [None, 'copy', 'id', 'parse', 'normalize', 'metadata', 'source', 'lineage', 'selected']:
            with self.subTest(fail_at=fail_at), ExitStack() as stack:
                source = source_line()
                variant = {'source_generation_info': None, 'lineage_info': None}
                before = copy.deepcopy((source, variant))
                clone = copy.deepcopy(source)
                tokens, source_info, lineage_info = [], {}, {}
                events = []
                error = RuntimeError('preparation failed')
                def step(name, value):
                    def call(*args):
                        events.append(name)
                        if name == fail_at:
                            raise error
                        return value
                    return call
                mocks = {}
                for target, name, value in [
                    ('copy.deepcopy', 'copy', clone), ('parse_prompt', 'parse', tokens),
                    ('normalize_candidate_line_for_main_sequence', 'normalize', object()),
                    ('build_source_generation_info_from_candidate', 'source', source_info),
                    ('build_lineage_info_from_candidate', 'lineage', lineage_info),
                    ('_selected_candidate_path', 'selected', 'selected.png'),
                ]:
                    mocks[name] = stack.enter_context(patch('core.gallery_variant_promotion.' + target, side_effect=step(name, value)))
                prepare = lambda: promotion.prepare_gallery_variant_promotion_line(
                    source, variant, 'v.png', step('id', 'new'), step('metadata', {'source': 'promotion'}))
                if fail_at:
                    with self.assertRaises(RuntimeError) as caught:
                        prepare()
                    self.assertIs(caught.exception, error)
                    self.assertEqual(events, steps[:steps.index(fail_at) + 1])
                else:
                    result = prepare()
                    self.assertEqual(events, steps)
                    self.assertIs(result, clone)
                    self.assertIs(result.tokens, tokens)
                    self.assertIs(result.source_generation_info, source_info)
                    self.assertIs(result.lineage_info, lineage_info)
                    mocks['normalize'].assert_called_once_with(clone)
                    mocks['source'].assert_called_once_with(source, 'v.png', {'source': 'promotion'})
                self.assertEqual((source, variant), before)


class CallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8'))
        cls.functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def test_caller_publication_order_and_failure(self):
        for managed, fails in [(True, False), (False, False), (True, True), (False, True)]:
            with self.subTest(managed=managed, fails=fails):
                events = []
                source = source_line()
                project = Project(prompt_lines=[source])
                new_line = source_line()
                new_line.id = 'new'
                state = type('State', (dict,), {'__getattr__': dict.__getitem__, '__setattr__': dict.__setitem__})()
                state.focused_line_id = 'old-focus'
                def prepare(*args):
                    events.append('prepare')
                    self.assertIs(args[0], source)
                    self.assertEqual(args[3](), 'line_12345678')
                    self.assertEqual(args[4](), {'source': 'metadata'})
                    self.assertEqual(project.prompt_lines, [source])
                    if fails:
                        raise RuntimeError('failed')
                    return new_line
                def reindex(value):
                    self.assertIs(value.prompt_lines[1], new_line)
                    events.append('reindex')
                def graph(value):
                    events.append('graph')
                    return value
                namespace = {
                    'get_line_by_id': lambda *_: source, '_normalize_candidate_path': lambda p: p,
                    '_runtime_asset_path': lambda p: p, 'os': SimpleNamespace(path=SimpleNamespace(exists=lambda p: True)),
                    'push_history': lambda: events.append('history'),
                    'prepare_gallery_variant_promotion_line': prepare,
                    'uuid': SimpleNamespace(uuid4=lambda: SimpleNamespace(hex='1234567890')),
                    '_variant_record_for_promotion': lambda v: {'source': 'metadata'},
                    '_promoted_route_insert_index': lambda *args: events.append('index') or 1,
                    '_reindex_project_lines': reindex, 'build_graph': graph,
                    'restore_focus_after_graph_update': lambda focus: events.append(('focus', focus)),
                    'sync_text_areas': lambda: events.append(('sync', state.highlighted_line_id, state.gallery_expanded_line_id)),
                    'save_current_project_if_possible': lambda reason: events.append(('save', reason)),
                    'st': SimpleNamespace(session_state=state),
                }
                module = ast.Module(body=[self.functions['promote_gallery_variant_to_route']], type_ignores=[])
                exec(compile(module, 'app.py', 'exec'), namespace)
                call = lambda: namespace['promote_gallery_variant_to_route'](project, source.id, {'path': 'v.png'}, manage_state=managed)
                expected = ['history'] if managed else []
                expected += ['prepare']
                if fails:
                    with self.assertRaisesRegex(RuntimeError, 'failed'):
                        call()
                    self.assertEqual(project.prompt_lines, [source])
                else:
                    self.assertEqual(call(), 'new')
                    expected += ['index', 'reindex']
                    if managed:
                        expected += ['graph', ('focus', 'old-focus'), ('sync', 'new', 'new'), ('save', 'gallery variant promoted to route')]
                    self.assertIs(project.prompt_lines[1], new_line)
                self.assertEqual(events, expected)


if __name__ == '__main__':
    unittest.main()
