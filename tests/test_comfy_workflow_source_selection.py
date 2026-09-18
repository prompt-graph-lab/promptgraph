"""Runtime contracts for embedded selection and its retained app boundaries."""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import comfy_workflow_source_selection as sources

PROMPT = '{"p": {"inputs": {}}}'
WORKFLOW = '{"w": {"inputs": {}}}'
NO_FIELDS = "no workflow metadata fields were found on this line"
BAD_FIELDS = "metadata workflow fields were found, but no executable ComfyUI API workflow was detected"
SOURCE_ONLY = "source metadata was found, but it is not an executable ComfyUI workflow"
FORCED = "embedded workflow metadata is ignored by setting"


class SourceSelectionTests(unittest.TestCase):
    def test_prompt_precedes_workflow(self):
        result = sources.select_embedded_workflow_source({'prompt': PROMPT, 'workflow': WORKFLOW})
        self.assertEqual(result, dict(workflow_text=PROMPT, selected_source='line metadata `prompt`', fallback_reason='', force_shared=False))

    def test_workflow_when_prompt_absent_unusable_or_malformed(self):
        for prompt in [None, '', 0, False, {}, [], '{bad', '[]', '{"x":{"inputs":[]}}']:
            with self.subTest(prompt=prompt):
                result = sources.select_embedded_workflow_source({'prompt': prompt, 'workflow': WORKFLOW})
                self.assertEqual(result['workflow_text'], WORKFLOW)
                self.assertEqual(result['selected_source'], 'line metadata `workflow`')
                self.assertEqual(result['fallback_reason'], '')

    def test_malformed_and_non_executable_fields(self):
        for text in ['{bad', '[]', 'false', 'null', '{}', '{"nodes": []}', ' ', '{"x":{"inputs":[]}}']:
            with self.subTest(text=text):
                result = sources.select_embedded_workflow_source({'workflow': text})
                self.assertEqual(result['workflow_text'], '')
                self.assertEqual(result['selected_source'], 'shared workflow JSON fallback')
                self.assertEqual(result['fallback_reason'], BAD_FIELDS)

    def test_absent_falsey_and_non_dictionary_metadata(self):
        for raw in [None, [], '', 0, {}, {'prompt': None, 'workflow': ''}, {'prompt': False, 'workflow': 0}, {'prompt': [], 'workflow': {}}]:
            with self.subTest(raw=raw):
                self.assertEqual(sources.select_embedded_workflow_source(raw)['fallback_reason'], NO_FIELDS)
                status = sources.inspect_embedded_workflow_sources(raw)
                self.assertFalse(status['has_executable_workflow'])

    def test_forced_selection_and_diagnostic_classification(self):
        raw = {'prompt': PROMPT, 'workflow': WORKFLOW}
        result = sources.select_embedded_workflow_source(raw, force_shared=True)
        self.assertEqual(result, dict(workflow_text='', force_shared=True, selected_source='shared workflow JSON fallback (forced)', fallback_reason=FORCED))
        status = sources.inspect_embedded_workflow_sources(raw)
        self.assertTrue(status['executable_prompt'])
        self.assertTrue(status['executable_workflow'])
        self.assertEqual(sources.classify_embedded_workflow_source(status, force_shared=True)['fallback_reason'], FORCED)

    def test_case_and_last_lowercased_collision_wins(self):
        for raw, text in [({'Prompt': PROMPT, 'WORKFLOW': WORKFLOW}, PROMPT), ({'prompt': PROMPT, 'PROMPT': '', 'Workflow': WORKFLOW}, WORKFLOW), ({'PROMPT': '', 'prompt': PROMPT}, PROMPT)]:
            self.assertEqual(sources.select_embedded_workflow_source(raw)['workflow_text'], text)
        status = sources.inspect_embedded_workflow_sources({'PROMPT': '', 'Workflow': None, 1: 'ignored'})
        self.assertTrue(status['has_prompt_metadata'])
        self.assertTrue(status['has_workflow_metadata'])

    def test_sources_normalization_flags_and_identity(self):
        for value in [None, (), 'a1111_parameters', {'novelai_exif': True}, False]:
            status = sources.inspect_embedded_workflow_sources({}, metadata_sources=value)
            self.assertEqual(status['metadata_sources'], [])
            self.assertFalse(status['has_a1111_parameters'])
            self.assertFalse(status['has_novelai_exif'])
            self.assertEqual(sources.classify_embedded_workflow_source(status)['fallback_reason'], NO_FIELDS)
        value = ['a1111_parameters', 'novelai_exif']
        status = sources.inspect_embedded_workflow_sources({}, metadata_sources=value)
        self.assertIs(status['metadata_sources'], value)
        self.assertTrue(status['has_a1111_parameters'])
        self.assertTrue(status['has_novelai_exif'])
        self.assertEqual(sources.classify_embedded_workflow_source(status)['fallback_reason'], SOURCE_ONLY)
        self.assertEqual(sources.select_embedded_workflow_source({}, metadata_sources=value)['fallback_reason'], SOURCE_ONLY)

    def test_selection_short_circuits_but_diagnostics_parse_both_before_shapes(self):
        events = []
        def parse(text):
            events.append(('parse', text))
            return text
        def shape(value):
            events.append(('shape', value))
            return True
        with patch.object(sources, '_load_json_from_text', parse), patch.object(sources, '_is_executable_comfy_workflow', shape):
            sources.select_embedded_workflow_source({'prompt': PROMPT, 'workflow': WORKFLOW})
            self.assertEqual(events, [('parse', PROMPT), ('shape', PROMPT)])
            events.clear()
            sources.inspect_embedded_workflow_sources({'prompt': PROMPT, 'workflow': WORKFLOW})
            self.assertEqual(events, [('parse', PROMPT), ('parse', WORKFLOW), ('shape', PROMPT), ('shape', WORKFLOW)])

    def test_shape_node_short_circuit_and_exception_propagation(self):
        class Bad(dict):
            def get(self, key):
                raise RuntimeError('visited')
        with patch.object(sources, '_load_json_from_text', return_value={'a': {'inputs': {}}, 'b': Bad()}):
            self.assertEqual(sources.select_embedded_workflow_source({'prompt': PROMPT})['workflow_text'], PROMPT)
        with patch.object(sources, '_load_json_from_text', return_value={'a': Bad(), 'b': {'inputs': {}}}):
            with self.assertRaisesRegex(RuntimeError, 'visited'):
                sources.select_embedded_workflow_source({'prompt': PROMPT})

    def test_no_input_mutation(self):
        raw = {'prompt': PROMPT, 'workflow': WORKFLOW, 'unknown': {'nested': []}}
        metadata_sources = ['novelai_exif']
        before = copy.deepcopy((raw, metadata_sources))
        sources.select_embedded_workflow_source(raw, metadata_sources=metadata_sources)
        sources.inspect_embedded_workflow_sources(raw, metadata_sources=metadata_sources)
        self.assertEqual((raw, metadata_sources), before)


class AppSourceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
        cls.functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}

    def load(self, name, namespace):
        exec(compile(ast.Module(body=[self.functions[name]], type_ignores=[]), 'app.py', 'exec'), namespace)
        return namespace[name]

    def test_acquisition_and_original_metadata_identity(self):
        project, line = SimpleNamespace(value=[]), SimpleNamespace(current_text='original')
        for raw in [{'prompt': PROMPT}, [], {'workflow': '{bad'}]:
            metadata = {'raw_metadata': raw, 'unknown': []}
            calls = []
            namespace = {'select_embedded_workflow_source': sources.select_embedded_workflow_source,
                         'find_image_metadata_for_line': lambda p, l: calls.append((p, l)) or metadata}
            result = self.load('_workflow_text_from_line_metadata', namespace)(project, line)
            self.assertEqual(calls, [(project, line)])
            self.assertIs(result[2], metadata)
            self.assertEqual(result[:2], (PROMPT, 'line metadata `prompt`') if isinstance(raw, dict) and 'prompt' in raw else ('', ''))
            self.assertEqual(project.value, [])
            self.assertEqual(line.current_text, 'original')

    def test_diagnostics_inspect_before_session_lookup_even_when_forced(self):
        events = []
        class State(dict):
            settings = {}
            def get(self, *args):
                events.append('settings')
                return True
        def inspect(*args, **kwargs):
            events.append('inspect')
            return sources.inspect_embedded_workflow_sources(*args, **kwargs)
        namespace = {'st': SimpleNamespace(session_state=State()),
                     'inspect_embedded_workflow_sources': inspect,
                     'classify_embedded_workflow_source': sources.classify_embedded_workflow_source}
        result = self.load('_workflow_metadata_debug_status', namespace)({'raw_metadata': {'prompt': PROMPT}, 'source_engine': 'comfyui'})
        self.assertEqual(events, ['inspect', 'settings'])
        self.assertEqual(result, dict(metadata_sources=[], has_a1111_parameters=False, has_novelai_exif=False, source_engine='comfyui', has_prompt_metadata=True, has_workflow_metadata=False, executable_prompt=True, executable_workflow=False, has_executable_workflow=True, force_shared=True, selected_source='shared workflow JSON fallback (forced)', fallback_reason=FORCED))

    def test_forced_preview_bypasses_acquisition_and_keeps_path_resolution(self):
        class State(dict):
            settings = {'force_shared_comfy_workflow': True}
        events = []
        namespace = {'st': SimpleNamespace(session_state=State()),
                     '_workflow_text_from_line_metadata': lambda *args: self.fail('metadata acquired'),
                     'resolve_effective_comfy_workflow_path': lambda path: events.append(path) or ('missing.json', 'fallback'),
                     'os': SimpleNamespace(path=SimpleNamespace(exists=lambda path: False))}
        result = self.load('_build_focus_line_workflow_preview', namespace)(object(), object())
        self.assertEqual(events, ['workflow_api.json'])
        self.assertEqual(result['warning'], 'Workflow JSON not found at missing.json')
        self.assertIsNone(result['workflow_json'])
