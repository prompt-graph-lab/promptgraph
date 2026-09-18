"""Runtime contracts for embedded source selection and retained app boundaries."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core import comfy_workflow_source_selection as selection


PROMPT = '{"p":{"inputs":{"text":"prompt"}}}'
WORKFLOW = '{"w":{"inputs":{}}}'
ABSENT = 'no workflow metadata fields were found on this line'
INVALID = 'metadata workflow fields were found, but no executable ComfyUI API workflow was detected'
SOURCE = 'source metadata was found, but it is not an executable ComfyUI workflow'
FORCED = 'embedded workflow metadata is ignored by setting'


class SourceSelectionTests(unittest.TestCase):
    def test_selection_and_exact_diagnostics(self):
        cases = [
            ({'prompt': PROMPT, 'workflow': WORKFLOW}, PROMPT, 'prompt', '', True, True),
            ({'workflow': WORKFLOW}, WORKFLOW, 'workflow', '', False, True),
            ({'prompt': '{}', 'workflow': WORKFLOW}, WORKFLOW, 'workflow', '', False, True),
            ({'prompt': '{bad', 'workflow': WORKFLOW}, WORKFLOW, 'workflow', '', False, True),
            ({'workflow': '{bad'}, '', '', INVALID, False, False),
            ({'workflow': '{"nodes":[]}'}, '', '', INVALID, False, False),
            ({}, '', '', ABSENT, False, False),
            ({'PrOmPt': PROMPT, 'WORKFLOW': WORKFLOW}, PROMPT, 'prompt', '', True, True),
            ({'PROMPT': PROMPT, 'prompt': '', 'workflow': WORKFLOW}, WORKFLOW, 'workflow', '', False, True),
            ({'prompt': '', 'PROMPT': PROMPT}, PROMPT, 'prompt', '', True, False),
        ]
        for raw, text, key, reason, prompt_ok, workflow_ok in cases:
            with self.subTest(raw=raw):
                before = copy.deepcopy(raw)
                result = selection.select_embedded_workflow_source(raw)
                label = f'line metadata `{key}`' if key else 'shared workflow JSON fallback'
                self.assertEqual(result['selected_source'], label)
                self.assertEqual(result['fallback_reason'], reason)
                self.assertEqual(result['executable_prompt'], prompt_ok)
                self.assertEqual(result['executable_workflow'], workflow_ok)
                self.assertEqual(result['has_executable_workflow'], prompt_ok or workflow_ok)
                self.assertEqual(selection.embedded_workflow_text(raw), (text, label if key else ''))
                self.assertEqual(raw, before)

    def test_falsey_empty_non_string_and_non_dictionary_metadata(self):
        for value in (None, '', 0, False, [], {}):
            for key in ('prompt', 'workflow'):
                with self.subTest(value=value, key=key):
                    result = selection.select_embedded_workflow_source({key: value})
                    self.assertEqual(result['fallback_reason'], ABSENT)
                    self.assertTrue(result[f'has_{key}_metadata'])
                    self.assertEqual(selection.embedded_workflow_text({key: value}), ('', ''))
        for value in (None, [], '', 0, False, 'not a dictionary'):
            result = selection.select_embedded_workflow_source(value)
            self.assertEqual(result['fallback_reason'], ABSENT)
            self.assertFalse(result['has_prompt_metadata'])
            self.assertFalse(result['has_workflow_metadata'])
            self.assertEqual(selection.embedded_workflow_text(value), ('', ''))
        for value in (' ', 'null', 'false', '0', '[]', '{}', '"text"', {'inputs': {}}):
            self.assertEqual(selection.select_embedded_workflow_source({'prompt': value})['fallback_reason'], INVALID)

    def test_sources_normalization_identity_flags_and_forcing(self):
        sources = ['a1111_parameters', 'novelai_exif']
        result = selection.select_embedded_workflow_source({}, metadata_sources=sources)
        self.assertIs(result['metadata_sources'], sources)
        self.assertTrue(result['has_a1111_parameters'])
        self.assertTrue(result['has_novelai_exif'])
        self.assertEqual(result['fallback_reason'], SOURCE)
        for sources in (None, (), 'a1111_parameters', {'novelai_exif': True}, 1):
            result = selection.select_embedded_workflow_source({}, metadata_sources=sources)
            self.assertEqual(result['metadata_sources'], [])
            self.assertEqual(result['fallback_reason'], ABSENT)
        for raw in ({}, {'prompt': PROMPT, 'workflow': WORKFLOW}, {'prompt': '{bad'}):
            result = selection.select_embedded_workflow_source(raw, force_shared=True)
            self.assertIs(result['force_shared'], True)
            self.assertEqual(result['selected_source'], 'shared workflow JSON fallback (forced)')
            self.assertEqual(result['fallback_reason'], FORCED)
            self.assertEqual(result['executable_prompt'], raw.get('prompt') == PROMPT)

    def test_execution_is_lazy_but_diagnostics_parse_both_before_shape_checks(self):
        events = []
        def parse(value):
            events.append(('parse', value))
            return json.loads(value)
        def shape(value):
            events.append(('shape', value))
            return True
        with patch.object(selection, '_load_json_from_text', parse), patch.object(selection, '_is_executable_comfy_workflow', shape):
            selection.embedded_workflow_text({'prompt': PROMPT, 'workflow': WORKFLOW})
            self.assertEqual(events, [('parse', PROMPT), ('shape', json.loads(PROMPT))])
            events.clear()
            selection.select_embedded_workflow_source({'prompt': PROMPT, 'workflow': WORKFLOW}, force_shared=True)
            self.assertEqual(events, [('parse', PROMPT), ('parse', WORKFLOW), ('shape', json.loads(PROMPT)), ('shape', json.loads(WORKFLOW))])

    def test_shape_short_circuit_and_exception_propagation(self):
        class BadNode(dict):
            def get(self, key):
                raise RuntimeError('visited later node')
        for nodes, raises in [({'a': {'inputs': {}}, 'b': BadNode()}, False), ({'a': BadNode(), 'b': {'inputs': {}}}, True)]:
            with patch.object(selection, '_load_json_from_text', return_value=nodes):
                if raises:
                    with self.assertRaisesRegex(RuntimeError, 'visited later node'):
                        selection.embedded_workflow_text({'prompt': PROMPT})
                else:
                    self.assertEqual(selection.embedded_workflow_text({'prompt': PROMPT}), (PROMPT, 'line metadata `prompt`'))
        with patch.object(selection, '_load_json_from_text', side_effect=RuntimeError('parse')):
            with self.assertRaisesRegex(RuntimeError, 'parse'):
                selection.select_embedded_workflow_source({'prompt': PROMPT})


class AppSourceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8'))
        names = {'_workflow_text_from_line_metadata', '_workflow_metadata_debug_status'}
        cls.code = compile(ast.Module(body=[n for n in tree.body if (
            isinstance(n, ast.ImportFrom) and n.module == 'core.comfy_workflow_source_selection'
        ) or (isinstance(n, ast.FunctionDef) and n.name in names)], type_ignores=[]), 'app.py', 'exec')

    def test_acquisition_identity_and_no_project_line_mutation(self):
        project, line = {'project': []}, {'line': []}
        metadata = {'raw_metadata': {'prompt': PROMPT}}
        acquire = Mock(return_value=metadata)
        namespace = {'find_image_metadata_for_line': acquire}
        exec(self.code, namespace)
        result = namespace['_workflow_text_from_line_metadata'](project, line)
        acquire.assert_called_once_with(project, line)
        self.assertEqual(result[:2], (PROMPT, 'line metadata `prompt`'))
        self.assertIs(result[2], metadata)
        self.assertEqual(project, {'project': []})
        self.assertEqual(line, {'line': []})

    def test_diagnostics_parse_before_session_read_and_keep_source_engine(self):
        events = []
        class Settings(dict):
            def get(self, key, default=None):
                events.append('settings')
                return True
        class Session(dict):
            settings = Settings()
            def get(self, key, default=None):
                events.append('session')
                return default
        namespace = {'st': SimpleNamespace(session_state=Session())}
        exec(self.code, namespace)
        def parse(text):
            events.append(text)
            return json.loads(text)
        with patch.object(selection, '_load_json_from_text', parse):
            result = namespace['_workflow_metadata_debug_status']({'raw_metadata': {'prompt': PROMPT, 'workflow': WORKFLOW}, 'source_engine': 'comfyui'})
        self.assertEqual(events, [PROMPT, WORKFLOW, 'settings', 'session'])
        self.assertEqual(result['source_engine'], 'comfyui')
        self.assertEqual(result['fallback_reason'], FORCED)
        self.assertTrue(result['has_executable_workflow'])


if __name__ == '__main__':
    unittest.main()
