import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.gallery_variant_promotion import prepare_gallery_variant_promotion_line as prepare
from core.parser import parse_prompt
from core.project import PromptLine


MODULE = 'core.gallery_variant_promotion'


def source_line(**fields):
    values = dict(
        id='parent', original_file_name='parent.png', original_index=3,
        current_index=7, original_text='old', current_text='cat, (blue sky:1.2)',
        tokens=['stale'], negative_prompt='negative', node_path=['node'],
        deleted=True, image_path='original.png', generated_image_path='generated.png',
        selected_candidate_path='selected.png', generated_candidates=[{'path': 'candidate.png'}],
        gallery_variants=[{'path': 'variant.png'}], line_type='workbench',
        separator_label='label', separator_color='red', workbench_source_line_id='source',
        workbench_title='title', workbench_note='note', workbench_status='draft',
    )
    values.update(fields)
    return PromptLine(**values)


class PreparationTests(unittest.TestCase):
    def test_materialization_resets_publication_fields_and_preserves_source_fields(self):
        source = source_line()
        source.extra = {'nested': [1]}
        variant = {'id': 'v', 'source_generation_info': {'nested': []},
                   'lineage_info': {'nested': [], 'unknown': 'kept'}}
        before = copy.deepcopy((source, variant))
        metadata = Mock(side_effect=AssertionError('metadata must stay lazy'))
        result = prepare(source, variant, 'images/variant.png', 'new', metadata)
        self.assertEqual((source, variant), before)
        self.assertIsNot(result, source)
        self.assertEqual(result.id, 'new')
        self.assertEqual(result.original_file_name, 'variant.png')
        self.assertEqual(result.original_text, source.current_text)
        self.assertEqual(result.current_text, source.current_text)
        self.assertEqual(result.tokens, parse_prompt(source.current_text))
        self.assertEqual(result.duplicated_from, source.id)
        self.assertTrue(result.edited)
        self.assertFalse(result.deleted)
        self.assertEqual(result.image_path, 'images/variant.png')
        for name in ('generated_image_path', 'selected_candidate_path', 'line_type',
                     'separator_label', 'separator_color', 'workbench_source_line_id',
                     'workbench_title', 'workbench_note', 'workbench_status'):
            self.assertIsNone(getattr(result, name), name)
        self.assertEqual(result.generated_candidates, [])
        self.assertEqual(result.gallery_variants, [])
        for name in ('negative_prompt', 'original_index', 'current_index', 'node_path', 'extra'):
            self.assertEqual(getattr(result, name), getattr(source, name))
        self.assertIsNot(result.node_path, source.node_path)
        self.assertIsNot(result.extra['nested'], source.extra['nested'])
        for name in ('source_generation_info', 'lineage_info'):
            self.assertIsNot(getattr(result, name), variant[name])
            self.assertIs(getattr(result, name)['nested'], variant[name]['nested'])
        self.assertEqual(result.lineage_info, {
            'nested': [], 'unknown': 'kept', 'lineage_kind': 'gallery_variant_promote_to_route',
            'parent_line_id': 'parent', 'parent_line_index': 7, 'parent_line_label': 'parent.png',
            'parent_image_path': 'selected.png', 'promoted_from_variant_id': 'v',
            'promoted_from_variant_path': 'images/variant.png', 'candidate_image_path': 'images/variant.png',
        })
        metadata.assert_not_called()

    def test_empty_provenance_dicts_suppress_fallback_independently(self):
        for source_info in ({}, None):
            for lineage_info in ({}, None):
                with self.subTest(source_info=source_info, lineage_info=lineage_info):
                    metadata = Mock(return_value={'prompt_text': 'variant prompt', 'source': 'legacy'})
                    result = prepare(source_line(), {'source_generation_info': source_info,
                                     'lineage_info': lineage_info}, 'v.png', 'new', metadata)
                    self.assertEqual(metadata.call_count, int(source_info is None) + int(lineage_info is None))
                    self.assertEqual(result.source_generation_info, {} if source_info == {} else {
                        'source_kind': 'derived_candidate', 'source_image_path': 'v.png',
                        'source_prompt': 'variant prompt', 'source_negative_prompt': 'negative',
                        'source_raw_metadata': {'prompt_text': 'variant prompt', 'source': 'legacy'},
                    })
                    self.assertEqual(result.lineage_info.get('created_from'), None if lineage_info == {} else 'legacy')

    def test_fallback_is_evaluated_twice_in_order_and_metadata_is_not_mutated(self):
        metadata = [{'prompt_text': 'first'}, {'source': 'second'}]
        before = copy.deepcopy(metadata)
        provider = Mock(side_effect=metadata)
        result = prepare(source_line(), {}, 'v.png', 'new', provider)
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(result.source_generation_info['source_prompt'], 'first')
        self.assertEqual(result.lineage_info['created_from'], 'second')
        self.assertEqual(metadata, before)

    def test_parent_image_fallback_and_falsey_variant_id_retain_legacy_lineage(self):
        for selected, generated, image, expected in (
            ('selected', 'generated', 'image', 'selected'),
            ('', 'generated', 'image', 'generated'),
            (None, '', 'image', 'image'),
            (None, None, None, 'stored-parent'),
        ):
            with self.subTest(expected=expected):
                source = source_line(selected_candidate_path=selected, generated_image_path=generated,
                                     image_path=image, original_file_name='', current_index=None)
                result = prepare(source, {'id': '', 'source_generation_info': {},
                    'lineage_info': {'parent_image_path': 'stored-parent', 'promoted_from_variant_id': 'stored-id'}},
                    '', 'new', {})
                self.assertEqual(result.original_file_name, '')
                self.assertEqual(result.lineage_info['parent_image_path'], expected)
                self.assertEqual(result.lineage_info['parent_line_label'], 'parent')
                self.assertIsNone(result.lineage_info['parent_line_index'])
                self.assertEqual(result.lineage_info['promoted_from_variant_id'], 'stored-id')

    def test_preparation_failure_order_and_input_non_mutation(self):
        # Inject failures at real preparation boundaries, without malformed inputs.
        for failure in ('deepcopy', 'identity', 'parse', 'metadata', 'source', 'lineage'):
            with self.subTest(failure=failure):
                source = source_line()
                before = copy.deepcopy(source)
                events = []
                error = RuntimeError(failure)
                def step(name, value):
                    def call(*args):
                        events.append(name)
                        if name == failure:
                            raise error
                        return value(*args) if callable(value) else value
                    return call
                with patch(MODULE + '.copy.deepcopy', side_effect=step('deepcopy', lambda _: copy_of_source)), \
                     patch(MODULE + '.parse_prompt', side_effect=step('parse', [])), \
                     patch(MODULE + '.build_source_generation_info_from_candidate', side_effect=step('source', {})), \
                     patch(MODULE + '.build_lineage_info_from_candidate', side_effect=step('lineage', {})):
                    copy_of_source = PromptLine(**before.__dict__)
                    with self.assertRaises(RuntimeError) as raised:
                        prepare(source, {}, 'v.png', step('identity', 'new'), step('metadata', {}))
                self.assertIs(raised.exception, error)
                order = ['deepcopy', 'identity', 'parse', 'metadata', 'source', 'metadata', 'lineage']
                self.assertEqual(events, order[:order.index(failure) + 1])
                self.assertEqual(source, before)


class CallerBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
        cls.function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                            and node.name == 'promote_gallery_variant_to_route')

    def caller(self, *, exists=True, fail=False):
        events = []
        line = source_line()
        project = SimpleNamespace(prompt_lines=[line])
        def preparation(*args):
            events.append('prepare')
            self.assertEqual(project.prompt_lines, [line])
            self.assertTrue(callable(args[3]))
            self.assertTrue(callable(args[4]))
            if fail:
                raise ValueError('preparation failed')
            return SimpleNamespace(id='new')
        env = dict(get_line_by_id=lambda *a: line, _normalize_candidate_path=lambda p: p,
                   _runtime_asset_path=lambda p: p, os=SimpleNamespace(path=SimpleNamespace(exists=lambda p: exists)),
                   push_history=lambda: events.append('history'), prepare_gallery_variant_promotion_line=preparation,
                   _promoted_route_insert_index=lambda *a: events.append('insert-index') or 1,
                   _reindex_project_lines=lambda p: events.append('reindex'))
        exec(compile(ast.Module(body=[self.function], type_ignores=[]), 'app.py', 'exec'), env)
        return env['promote_gallery_variant_to_route'], project, events

    def test_external_validation_precedes_history_and_preparation(self):
        caller, project, events = self.caller(exists=False)
        self.assertIsNone(caller(project, 'parent', {'path': 'v.png'}))
        self.assertEqual(events, [])

    def test_preparation_failure_follows_history_and_prevents_insertion(self):
        caller, project, events = self.caller(fail=True)
        with self.assertRaisesRegex(ValueError, 'preparation failed'):
            caller(project, 'parent', {'path': 'v.png'})
        self.assertEqual(events, ['history', 'prepare'])
        self.assertEqual(len(project.prompt_lines), 1)

    def test_unmanaged_caller_publishes_only_after_preparation(self):
        caller, project, events = self.caller()
        self.assertEqual(caller(project, 'parent', {'path': 'v.png'}, manage_state=False), 'new')
        self.assertEqual(events, ['prepare', 'insert-index', 'reindex'])
        self.assertEqual(project.prompt_lines[1].id, 'new')


if __name__ == '__main__':
    unittest.main()
