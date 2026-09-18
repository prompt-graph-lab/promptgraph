"""Runtime contracts for embedded selection and its app-owned boundaries."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import comfy_workflow_source_selection as selection

PROMPT = '{"p": {"inputs": {}}}'
WORKFLOW = '{"w": {"inputs": {"text": "workflow"}}}'
FIELDS_REASON = 'metadata workflow fields were found, but no executable ComfyUI API workflow was detected'
ABSENT_REASON = 'no workflow metadata fields were found on this line'
SOURCE_REASON = 'source metadata was found, but it is not an executable ComfyUI workflow'
FORCED_REASON = 'embedded workflow metadata is ignored by setting'


class SourceSelectionTests(unittest.TestCase):
    def test_prompt_precedence_and_workflow_fallbacks(self):
        for prompt, expected, label in (
            (PROMPT, PROMPT, 'prompt'), (None, WORKFLOW, 'workflow'),
            ('', WORKFLOW, 'workflow'), ('{bad', WORKFLOW, 'workflow'),
            ('[]', WORKFLOW, 'workflow'), ({'p': {'inputs': {}}}, WORKFLOW, 'workflow'),
        ):
            with self.subTest(prompt=prompt):
                raw = {'prompt': prompt, 'workflow': WORKFLOW}
                before = copy.deepcopy(raw)
                result = selection.select_embedded_workflow_source(raw)
                self.assertEqual(result, {'workflow_text': expected,
                    'source_label': f'line metadata `{label}`',
                    'selected_source': f'line metadata `{label}`', 'fallback_reason': ''})
                self.assertEqual(raw, before)

    def test_fallback_reasons_and_non_dictionary_metadata(self):
        for raw, sources, reason in (
            ({'workflow': '{broken'}, None, FIELDS_REASON),
            ({'workflow': '{"nodes": []}'}, None, FIELDS_REASON),
            ({'prompt': 'null'}, None, FIELDS_REASON),
            ({}, None, ABSENT_REASON), (None, None, ABSENT_REASON),
            ([], None, ABSENT_REASON), ('prompt', None, ABSENT_REASON),
            ({}, ['a1111_parameters'], SOURCE_REASON),
            ({}, ('a1111_parameters',), ABSENT_REASON),
            ({}, 'novelai_exif', ABSENT_REASON),
            ({}, {'novelai_exif': True}, ABSENT_REASON),
        ):
            with self.subTest(raw=raw, sources=sources):
                self.assertEqual(selection.select_embedded_workflow_source(raw, metadata_sources=sources), {
                    'workflow_text': '', 'source_label': '',
                    'selected_source': 'shared workflow JSON fallback', 'fallback_reason': reason})

    def test_falsey_fields_and_key_presence(self):
        for value in (None, '', False, 0, [], {}):
            with self.subTest(value=value):
                raw = {'prompt': value, 'workflow': value}
                self.assertEqual(selection.select_embedded_workflow_source(raw)['fallback_reason'], ABSENT_REASON)
                info = selection.inspect_embedded_workflow_sources(raw, [])
                self.assertTrue(info['has_prompt_metadata'])
                self.assertTrue(info['has_workflow_metadata'])
                self.assertFalse(info['executable_prompt'])
                self.assertFalse(info['executable_workflow'])
        self.assertEqual(selection.select_embedded_workflow_source({'prompt': ' '})['fallback_reason'], FIELDS_REASON)

    def test_case_insensitive_keys_last_lowercase_collision_wins(self):
        for raw, expected in (
            ({'PrOmPt': PROMPT, 'WORKFLOW': WORKFLOW}, PROMPT),
            ({'PROMPT': PROMPT, 'prompt': '{bad', 'Workflow': WORKFLOW}, WORKFLOW),
            ({'prompt': '{bad', 'PROMPT': PROMPT, 'workflow': WORKFLOW}, PROMPT),
            ({' prompt ': PROMPT, 'workflow': WORKFLOW}, WORKFLOW),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(selection.select_embedded_workflow_source(raw)['workflow_text'], expected)

    def test_forced_selection_classification_does_not_parse_embedded_fields(self):
        with patch.object(selection, '_load_json_from_text', side_effect=AssertionError('bypassed')):
            result = selection.select_embedded_workflow_source({'prompt': PROMPT}, force_shared=True)
        self.assertEqual(result, {'workflow_text': '', 'source_label': '',
            'selected_source': 'shared workflow JSON fallback (forced)', 'fallback_reason': FORCED_REASON})

    def test_selection_parses_and_checks_one_source_at_a_time(self):
        events = []
        def parse(text):
            events.append(('parse', text))
            return text
        def shape(value):
            events.append(('shape', value))
            return value == PROMPT
        with patch.object(selection, '_load_json_from_text', parse), \
             patch.object(selection, '_is_executable_comfy_workflow', shape):
            selection.select_embedded_workflow_source({'prompt': PROMPT, 'workflow': WORKFLOW})
        self.assertEqual(events, [('parse', PROMPT), ('shape', PROMPT)])
        events.clear()
        with patch.object(selection, '_load_json_from_text', parse), \
             patch.object(selection, '_is_executable_comfy_workflow', shape):
            selection.select_embedded_workflow_source({'workflow': WORKFLOW})
        self.assertEqual(events, [('shape', None), ('parse', WORKFLOW), ('shape', WORKFLOW)])

    def test_diagnostics_parse_both_before_shape_checks_even_if_prompt_works(self):
        events = []
        def parse(text):
            events.append(('parse', text))
            return {'p': {'inputs': {}}}
        def shape(value):
            events.append(('shape', value))
            return True
        with patch.object(selection, '_load_json_from_text', parse), \
             patch.object(selection, '_is_executable_comfy_workflow', shape):
            info = selection.inspect_embedded_workflow_sources({'prompt': PROMPT, 'workflow': WORKFLOW}, [])
        self.assertEqual([name for name, _ in events], ['parse', 'parse', 'shape', 'shape'])
        self.assertTrue(info['executable_prompt'])
        self.assertTrue(info['executable_workflow'])

    def test_shape_rules_and_node_short_circuit(self):
        for text, usable in (('[]', False), ('false', False), ('0', False),
                            ('{"inputs": {}}', False), ('{"n": {"inputs": []}}', False),
                            ('{"n": {"inputs": {}}}', True)):
            with self.subTest(text=text):
                self.assertEqual(bool(selection.select_embedded_workflow_source({'prompt': text})['workflow_text']), usable)
        class BadNode(dict):
            def get(self, key):
                raise RuntimeError('visited later node')
        with patch.object(selection, '_load_json_from_text', return_value={'a': {'inputs': {}}, 'b': BadNode()}):
            self.assertEqual(selection.select_embedded_workflow_source({'prompt': PROMPT})['workflow_text'], PROMPT)
        with patch.object(selection, '_load_json_from_text', return_value={'a': BadNode(), 'b': {'inputs': {}}}):
            with self.assertRaisesRegex(RuntimeError, 'visited later node'):
                selection.select_embedded_workflow_source({'prompt': PROMPT})

    def test_metadata_sources_normalization_and_identity(self):
        for sources in (None, '', ('a1111_parameters',), {'novelai_exif': True}):
            info = selection.inspect_embedded_workflow_sources({}, sources)
            self.assertEqual(info['metadata_sources'], [])
            self.assertFalse(info['has_a1111_parameters'])
            self.assertFalse(info['has_novelai_exif'])
        sources = ['a1111_parameters', 'novelai_exif', 'other']
        info = selection.inspect_embedded_workflow_sources({}, sources)
        self.assertIs(info['metadata_sources'], sources)
        self.assertTrue(info['has_a1111_parameters'])
        self.assertTrue(info['has_novelai_exif'])


class AppSourceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
        names = {'_workflow_text_from_line_metadata', '_workflow_metadata_debug_status',
                 '_build_focus_line_workflow_preview', 'build_single_line_workflow'}
        nodes = [node for node in tree.body if
                 (isinstance(node, ast.FunctionDef) and node.name in names) or
                 (isinstance(node, ast.ImportFrom) and node.module == 'core.comfy_workflow_source_selection')]
        cls.code = compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec')

    def namespace(self, metadata=None, force=False):
        class State(dict):
            def __getattr__(self, name):
                return self[name]
        state = State(settings={}, force_shared_comfy_workflow=force, disabled_modules=set())
        ns = {'find_image_metadata_for_line': Mock(return_value=metadata),
              'st': SimpleNamespace(session_state=state), 'copy': copy}
        exec(self.code, ns)
        return ns

    def test_acquisition_and_original_metadata_identity_remain_in_app(self):
        project, line = SimpleNamespace(lines=[]), SimpleNamespace(text='original')
        before = copy.deepcopy((project, line))
        for raw in ({'PROMPT': PROMPT}, None, [], 'bad'):
            with self.subTest(raw=raw):
                metadata = {'raw_metadata': raw}
                ns = self.namespace(metadata)
                result = ns['_workflow_text_from_line_metadata'](project, line)
                self.assertIs(result[2], metadata)
                ns['find_image_metadata_for_line'].assert_called_once_with(project, line)
                self.assertEqual((project, line), before)

    def test_exact_diagnostic_flags_for_forced_usable_metadata(self):
        sources = ['a1111_parameters', 'novelai_exif']
        metadata = {'raw_metadata': {'PROMPT': PROMPT, 'WORKFLOW': WORKFLOW},
                    'metadata_sources': sources, 'source_engine': 'engine'}
        ns = self.namespace(force=True)
        result = ns['_workflow_metadata_debug_status'](metadata)
        self.assertEqual(result, {
            'metadata_sources': sources, 'has_a1111_parameters': True, 'has_novelai_exif': True,
            'source_engine': 'engine', 'has_prompt_metadata': True, 'has_workflow_metadata': True,
            'executable_prompt': True, 'executable_workflow': True, 'has_executable_workflow': True,
            'force_shared': True, 'selected_source': 'shared workflow JSON fallback (forced)',
            'fallback_reason': FORCED_REASON})
        self.assertIs(result['metadata_sources'], sources)
        ns['find_image_metadata_for_line'].assert_not_called()

    def test_diagnostic_case_collisions_and_fallbacks(self):
        ns = self.namespace()
        for raw, sources, reason in ((None, None, ABSENT_REASON),
                ({'prompt': '', 'workflow': False}, 'a1111_parameters', ABSENT_REASON),
                ({}, ['other'], SOURCE_REASON), ({'workflow': '{bad'}, [], FIELDS_REASON)):
            result = ns['_workflow_metadata_debug_status']({'raw_metadata': raw, 'metadata_sources': sources})
            self.assertEqual(result['fallback_reason'], reason)
            self.assertEqual(result['source_engine'], '')
            self.assertEqual(result['selected_source'], 'shared workflow JSON fallback')
            self.assertFalse(result['has_executable_workflow'])
        result = ns['_workflow_metadata_debug_status']({'raw_metadata':
            {'PROMPT': PROMPT, 'prompt': '{}', 'WORKFLOW': WORKFLOW}})
        self.assertEqual(result['selected_source'], 'line metadata `workflow`')

    def test_diagnostic_inspection_precedes_session_read_and_source_engine_lookup(self):
        events = []
        class Metadata(dict):
            def get(self, key, default=None):
                events.append(key)
                return super().get(key, default)
        class Key:
            def __str__(self):
                events.append('lower key')
                return 'PROMPT'
        class Settings(dict):
            def get(self, *args):
                events.append('settings')
                return False
        ns = self.namespace(force=True)
        ns['st'].session_state['settings'] = Settings()
        with patch.object(selection, '_load_json_from_text', side_effect=lambda _: events.append('parse') or {}), \
             patch.object(selection, '_is_executable_comfy_workflow', side_effect=lambda _: events.append('shape') or False):
            ns['_workflow_metadata_debug_status'](Metadata(raw_metadata={Key(): PROMPT}))
        self.assertEqual(events, ['raw_metadata', 'lower key', 'metadata_sources', 'parse',
                                  'shape', 'shape', 'settings', 'source_engine'])

    def test_forced_execution_and_preview_bypass_metadata_before_filesystem_fallback(self):
        for name in ('build_single_line_workflow', '_build_focus_line_workflow_preview'):
            with self.subTest(name=name):
                ns = self.namespace(force=True)
                ns['find_image_metadata_for_line'].side_effect = AssertionError('must bypass acquisition')
                ns['resolve_effective_comfy_workflow_path'] = Mock(side_effect=RuntimeError('filesystem boundary'))
                line = SimpleNamespace(current_text='original')
                project = SimpleNamespace(module_library={})
                with self.assertRaisesRegex(RuntimeError, 'filesystem boundary'):
                    if name == 'build_single_line_workflow':
                        ns[name]('shared.json', line, {'force_shared_comfy_workflow': True}, project=project)
                    else:
                        ns[name](project, line)
                ns['find_image_metadata_for_line'].assert_not_called()
                self.assertEqual(line.current_text, 'original')


if __name__ == '__main__':
    unittest.main()
